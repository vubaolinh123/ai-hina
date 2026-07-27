from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .errors import TtsError
from .model import TtsPcmChunk, TtsSynthesis
from .tts_config import TtsConfig
from .tts_provider import (
    _float_samples_to_pcm16,
    _release_cuda_memory,
    _wait_for_native_worker,
)


SnapshotDownloader = Callable[..., str]
VoxCpmFactory = Callable[[Path, TtsConfig], Any]

_MODEL_PATTERNS = (
    "audiovae.pth",
    "config.json",
    "model.safetensors",
    "special_tokens_map.json",
    "tokenization_voxcpm2.py",
    "tokenizer.json",
    "tokenizer_config.json",
)
_CUE = re.compile(r"\[[^\[\]\r\n]{1,48}\]")


class _NativeVoxCpmTimeout(TtsError):
    def __init__(self, worker: Future[TtsSynthesis]) -> None:
        super().__init__("E_TTS_TIMEOUT", "VoxCPM2 inference timed out", retryable=True)
        self.worker = worker


class VoxCpm2TtsProvider:
    """CUDA-only VoxCPM2 adapter for Hina's fixed synthetic reference voice."""

    def __init__(
        self,
        config: TtsConfig,
        *,
        snapshot_downloader: SnapshotDownloader | None = None,
        model_factory: VoxCpmFactory | None = None,
    ) -> None:
        self.config = config
        self.snapshot_downloader = snapshot_downloader
        self.model_factory = model_factory
        self._model: Any | None = None
        self._model_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hina-voxcpm2-tts")
        self._active_worker: Future[TtsSynthesis] | None = None
        self._active_cancel: threading.Event | None = None
        self._drain_task: asyncio.Task[None] | None = None
        self._state_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()
        self._last_error_code: str | None = None
        self._closed = False

    async def status(self) -> dict[str, object]:
        dependency_available = self.model_factory is not None or (
            importlib.util.find_spec("voxcpm") is not None
            and importlib.util.find_spec("torch") is not None
            and importlib.util.find_spec("huggingface_hub") is not None
        )
        cached = _snapshot_is_cached(self.config)
        draining = self._drain_task is not None and not self._drain_task.done()
        return {
            "available": (
                dependency_available
                and (self.config.allow_download or cached)
                and not self._closed
                and not draining
            ),
            "dependencyAvailable": dependency_available,
            "modelLoaded": self._model is not None,
            "modelCached": cached,
            "effectiveDevice": "cuda",
            "effectivePrecision": "bfloat16",
            "voice": self.config.voice,
            "sampleRateHz": 48_000,
            "downloadOnFirstUse": self.config.allow_download,
            "referenceAudio": str(self.config.reference_audio_path),
            "referenceAudioSha256": self.config.reference_audio_sha256 or None,
            "badcaseRetry": True,
            "drainingTimedOutInference": draining,
            "lastErrorCode": self._last_error_code,
        }

    async def warmup(self) -> None:
        async with self._inference_lock:
            worker = self._executor.submit(self._load_model_sync)
            try:
                await asyncio.wait_for(
                    asyncio.shield(asyncio.wrap_future(worker)),
                    timeout=self.config.request_timeout_seconds,
                )
            except TimeoutError as exc:
                self._last_error_code = "E_TTS_TIMEOUT"
                raise TtsError(
                    "E_TTS_TIMEOUT",
                    "VoxCPM2 GPU warmup timed out",
                    retryable=True,
                ) from exc

    async def synthesize(
        self,
        chunks: tuple[str, ...],
        cancel_event: threading.Event,
    ) -> TtsSynthesis:
        async with self._inference_lock:
            if cancel_event.is_set():
                raise TtsError("E_TTS_CANCELLED", "TTS utterance was cancelled")
            return await self._synthesize_serial(chunks, cancel_event)

    async def _synthesize_serial(
        self,
        chunks: tuple[str, ...],
        cancel_event: threading.Event,
    ) -> TtsSynthesis:
        if self._closed:
            raise TtsError("E_TTS_UNAVAILABLE", "TTS provider is closed", retryable=True)
        async with self._state_lock:
            if self._drain_task is not None and not self._drain_task.done():
                raise TtsError(
                    "E_TTS_DRAINING",
                    "a timed-out VoxCPM2 inference is still draining",
                    retryable=True,
                )
            worker = self._executor.submit(self._synthesize_sync, chunks, cancel_event)
            async_worker = asyncio.wrap_future(worker)
            self._active_worker = worker
            self._active_cancel = cancel_event
        try:
            try:
                return await asyncio.wait_for(
                    asyncio.shield(async_worker),
                    timeout=self.config.request_timeout_seconds,
                )
            except TimeoutError as exc:
                cancel_event.set()
                self._last_error_code = "E_TTS_TIMEOUT"
                raise _NativeVoxCpmTimeout(worker) from exc
            except asyncio.CancelledError:
                cancel_event.set()
                await _wait_for_native_worker(worker)
                raise
            except TtsError as exc:
                self._last_error_code = exc.code
                raise
            except Exception as exc:
                self._last_error_code = "E_TTS_INFERENCE"
                raise TtsError(
                    "E_TTS_INFERENCE",
                    "VoxCPM2 inference failed",
                    retryable=True,
                ) from exc
        except _NativeVoxCpmTimeout as exc:
            async with self._state_lock:
                self._drain_task = asyncio.create_task(self._finish_drain(exc.worker))
            raise
        finally:
            async with self._state_lock:
                if self._active_worker is worker and worker.done():
                    self._active_worker = None
                    self._active_cancel = None

    async def unload(self) -> None:
        drain = self._drain_task
        if drain is not None and drain is not asyncio.current_task():
            await asyncio.shield(drain)
        async with self._inference_lock:
            with self._model_lock:
                model = self._model
                self._model = None
        if model is not None:
            del model
        _release_cuda_memory()

    async def close(self) -> None:
        self._closed = True
        async with self._state_lock:
            active = self._active_worker
            cancel = self._active_cancel
            drain = self._drain_task
        if cancel is not None:
            cancel.set()
        if active is not None and not active.done():
            await _wait_for_native_worker(active)
        if drain is not None:
            await asyncio.shield(drain)
        await self.unload()
        self._executor.shutdown(wait=True, cancel_futures=True)

    async def _finish_drain(self, worker: Future[TtsSynthesis]) -> None:
        try:
            await _wait_for_native_worker(worker)
        finally:
            async with self._state_lock:
                if self._active_worker is worker:
                    self._active_worker = None
                    self._active_cancel = None
                if self._drain_task is asyncio.current_task():
                    self._drain_task = None

    def _synthesize_sync(
        self,
        chunks: tuple[str, ...],
        cancel_event: threading.Event,
    ) -> TtsSynthesis:
        import numpy as np

        started = time.monotonic()
        model = self._load_model_sync()
        sample_rate = int(getattr(model.tts_model, "sample_rate", 0))
        if sample_rate != 48_000:
            raise TtsError("E_TTS_AUDIO", "VoxCPM2 returned an unexpected sample rate")
        _verify_reference_audio(self.config)

        first_chunk_ms: float | None = None
        output: list[TtsPcmChunk] = []
        sample_cursor = 0
        max_samples = round(self.config.max_audio_seconds * sample_rate)
        silence = np.zeros(round(sample_rate * 0.12), dtype=np.float32)

        for index, raw_text in enumerate(chunks):
            if cancel_event.is_set():
                raise TtsError("E_TTS_CANCELLED", "TTS utterance was cancelled")
            text = _strip_cues(raw_text)
            if not text:
                continue
            try:
                _seed_generation(self.config.generation_seed + index)
                values = model.generate(
                    text=text,
                    reference_wav_path=str(self.config.reference_audio_path),
                    cfg_value=self.config.guidance_scale,
                    inference_timesteps=self.config.inference_timesteps,
                    normalize=False,
                    denoise=False,
                    retry_badcase=True,
                    retry_badcase_max_times=3,
                    retry_badcase_ratio_threshold=6.0,
                )
            except Exception as exc:
                raise TtsError(
                    "E_TTS_INFERENCE",
                    f"VoxCPM2 failed at speech segment {index + 1}",
                    retryable=True,
                ) from exc
            values = _validated_audio(values, sample_rate=sample_rate, segment=index)
            if first_chunk_ms is None:
                first_chunk_ms = (time.monotonic() - started) * 1_000
            if output:
                values = np.concatenate((silence, values))
            pcm = _float_samples_to_pcm16(values)
            start_seconds = sample_cursor / sample_rate
            sample_cursor += len(pcm) // 2
            if sample_cursor > max_samples:
                cancel_event.set()
                raise TtsError("E_TTS_AUDIO_TOO_LONG", "TTS output exceeds the duration limit")
            output.append(
                TtsPcmChunk(
                    text=text,
                    pcm16=pcm,
                    start_seconds=start_seconds,
                    end_seconds=sample_cursor / sample_rate,
                )
            )

        if cancel_event.is_set():
            raise TtsError("E_TTS_CANCELLED", "TTS utterance was cancelled")
        if not output:
            raise TtsError("E_TTS_EMPTY_AUDIO", "VoxCPM2 returned no audio")
        self._last_error_code = None
        elapsed = (time.monotonic() - started) * 1_000
        return TtsSynthesis(
            sample_rate_hz=sample_rate,
            voice=self.config.voice,
            chunks=tuple(output),
            first_chunk_milliseconds=round(first_chunk_ms or elapsed, 3),
            processing_milliseconds=round(elapsed, 3),
            # Do not time-stretch diffusion output: the previous WSOLA pass was
            # a major source of corruption on long Vietnamese responses.
            speaking_rate=1.0,
        )

    def _load_model_sync(self) -> Any:
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                downloader = self.snapshot_downloader
                if downloader is None:
                    from huggingface_hub import snapshot_download

                    downloader = snapshot_download
                snapshot = Path(
                    downloader(
                        repo_id=self.config.model_id,
                        revision=self.config.model_revision,
                        cache_dir=str(self.config.model_cache),
                        allow_patterns=list(_MODEL_PATTERNS),
                        local_files_only=not self.config.allow_download,
                    )
                )
                _verify_reference_audio(self.config)
                factory = self.model_factory or _create_voxcpm2
                self._model = factory(snapshot, self.config)
                return self._model
            except TtsError:
                raise
            except Exception as exc:
                raise TtsError(
                    "E_TTS_MODEL_LOAD",
                    "the pinned VoxCPM2 model could not be loaded",
                    retryable=True,
                ) from exc


def _create_voxcpm2(snapshot: Path, config: TtsConfig) -> Any:
    import torch
    from voxcpm import VoxCPM

    if not torch.cuda.is_available():
        raise TtsError("E_TTS_GPU_UNAVAILABLE", "CUDA is required for VoxCPM2", retryable=True)
    if config.device != "cuda":
        raise TtsError("E_TTS_GPU_UNAVAILABLE", "VoxCPM2 CPU fallback is disabled")
    return VoxCPM.from_pretrained(
        str(snapshot),
        load_denoiser=False,
        optimize=False,
        device="cuda",
        local_files_only=True,
    )


def _seed_generation(seed: int) -> None:
    import torch

    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def _validated_audio(raw: Any, *, sample_rate: int, segment: int) -> Any:
    import numpy as np

    values = np.asarray(raw, dtype=np.float32).reshape(-1)
    if values.size < round(sample_rate * 0.15):
        raise TtsError("E_TTS_EMPTY_AUDIO", f"VoxCPM2 segment {segment + 1} was empty")
    if not np.isfinite(values).all():
        raise TtsError("E_TTS_AUDIO", f"VoxCPM2 segment {segment + 1} was non-finite")
    peak = float(np.max(np.abs(values)))
    rms = float(np.sqrt(np.mean(np.square(values, dtype=np.float64))))
    if peak < 1e-4 or rms < 1e-5:
        raise TtsError("E_TTS_EMPTY_AUDIO", f"VoxCPM2 segment {segment + 1} was silent")
    values = np.clip(values, -0.99, 0.99)
    fade = min(round(sample_rate * 0.008), values.size // 4)
    if fade > 1:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        values[:fade] *= ramp
        values[-fade:] *= ramp[::-1]
    return values


def _strip_cues(text: str) -> str:
    return re.sub(r"\s+", " ", _CUE.sub("", text)).strip()


def _verify_reference_audio(config: TtsConfig) -> None:
    path = config.reference_audio_path
    if not path.is_file():
        raise TtsError("E_TTS_VOICE_REFERENCE", "the fixed Hina reference WAV is missing")
    if config.reference_audio_sha256:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != config.reference_audio_sha256:
            raise TtsError(
                "E_TTS_VOICE_REFERENCE",
                "the fixed Hina reference WAV failed its SHA-256 check",
            )


def _snapshot_is_cached(config: TtsConfig) -> bool:
    cache = config.model_cache
    if Path(config.model_id).is_dir():
        return True
    snapshot = (
        cache
        / f"models--{config.model_id.replace('/', '--')}"
        / "snapshots"
        / config.model_revision
    )
    return all((snapshot / name).is_file() for name in _MODEL_PATTERNS if "/" not in name)
