from __future__ import annotations

import asyncio
import gc
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
from .tts_text import adaptive_speaking_rate


SnapshotDownloader = Callable[..., str]
OmniVoiceFactory = Callable[[Path, TtsConfig], Any]

_SAMPLE_RATE_HZ = 24_000
_INTER_SEGMENT_SILENCE_SECONDS = 0.12
_MODEL_PATTERNS = (
    "audio_tokenizer/config.json",
    "audio_tokenizer/model.safetensors",
    "audio_tokenizer/preprocessor_config.json",
    "chat_template.jinja",
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
)
_CUE = re.compile(r"\[([^\[\]\r\n]{1,48})\]", re.IGNORECASE)
_CUE_MAP = {
    "chuckle": "[laughter]",
    "laughter": "[laughter]",
    "laugh": "[laughter]",
    "sigh": "[sigh]",
}


class _NativeOmniVoiceTimeout(TtsError):
    def __init__(self, worker: Future[TtsSynthesis]) -> None:
        super().__init__("E_TTS_TIMEOUT", "OmniVoice inference timed out", retryable=True)
        self.worker = worker


class OmniVoiceTtsProvider:
    """CUDA-only OmniVoice adapter for Hina's fixed synthetic reference voice."""

    def __init__(
        self,
        config: TtsConfig,
        *,
        snapshot_downloader: SnapshotDownloader | None = None,
        model_factory: OmniVoiceFactory | None = None,
    ) -> None:
        self.config = config
        self.snapshot_downloader = snapshot_downloader
        self.model_factory = model_factory
        self._model: Any | None = None
        self._voice_prompt: Any | None = None
        self._model_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="hina-omnivoice-tts",
        )
        self._active_worker: Future[TtsSynthesis] | None = None
        self._active_cancel: threading.Event | None = None
        self._drain_task: asyncio.Task[None] | None = None
        self._state_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()
        self._last_error_code: str | None = None
        self._model_baseline_allocated_mib = 0.0
        self._last_peak_allocated_mib = 0.0
        self._last_peak_reserved_mib = 0.0
        self._last_post_allocated_mib = 0.0
        self._warm_request_count = 0
        self._recycle_required = False
        self._closed = False

    async def status(self) -> dict[str, object]:
        dependency_available = self.model_factory is not None or (
            importlib.util.find_spec("omnivoice") is not None
            and importlib.util.find_spec("torch") is not None
            and importlib.util.find_spec("huggingface_hub") is not None
        )
        cached = _snapshot_is_cached(self.config)
        draining = self._drain_task is not None and not self._drain_task.done()
        model = self._model
        return {
            "available": (
                dependency_available
                and (self.config.allow_download or cached)
                and not self._closed
                and not draining
            ),
            "dependencyAvailable": dependency_available,
            "modelLoaded": model is not None,
            "modelCached": cached,
            "effectiveDevice": "cuda",
            "effectivePrecision": "float16",
            "attentionImplementation": "sdpa",
            "voice": self.config.voice,
            "sampleRateHz": _SAMPLE_RATE_HZ,
            "downloadOnFirstUse": self.config.allow_download,
            "referenceAudio": str(self.config.reference_audio_path),
            "referenceAudioSha256": self.config.reference_audio_sha256 or None,
            "referenceTranscriptConfigured": bool(self.config.reference_text),
            "voicePromptReady": self._voice_prompt is not None,
            "asrLoaded": bool(
                model is not None and getattr(model, "_asr_pipe", None) is not None
            ),
            "batchSize": 1,
            "diffusionSteps": self.config.inference_timesteps,
            "audioChunkDurationSeconds": self.config.audio_chunk_duration_seconds,
            "audioChunkThresholdSeconds": self.config.audio_chunk_threshold_seconds,
            "modelBaselineAllocatedMiB": round(
                self._model_baseline_allocated_mib,
                1,
            ),
            "lastPeakAllocatedMiB": round(self._last_peak_allocated_mib, 1),
            "lastPeakReservedMiB": round(self._last_peak_reserved_mib, 1),
            "lastPostAllocatedMiB": round(self._last_post_allocated_mib, 1),
            "warmRequestCount": self._warm_request_count,
            "recycleRequired": self._recycle_required,
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
                    "OmniVoice GPU warmup timed out",
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
                    "a timed-out OmniVoice inference is still draining",
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
                raise _NativeOmniVoiceTimeout(worker) from exc
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
                    "OmniVoice inference failed",
                    retryable=True,
                ) from exc
        except _NativeOmniVoiceTimeout as exc:
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
                prompt = self._voice_prompt
                self._model = None
                self._voice_prompt = None
                self._model_baseline_allocated_mib = 0.0
                self._warm_request_count = 0
                self._recycle_required = False
        if prompt is not None:
            del prompt
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
        import torch

        started = time.monotonic()
        model, prompt = self._load_model_sync()
        sample_rate = int(getattr(model, "sampling_rate", 0))
        if sample_rate != _SAMPLE_RATE_HZ:
            raise TtsError(
                "E_TTS_AUDIO",
                "OmniVoice returned an unexpected sample rate",
            )
        _verify_reference_audio(self.config)

        gc.collect()
        cuda_available = torch.cuda.is_available()
        if cuda_available:
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
        first_chunk_ms: float | None = None
        output: list[TtsPcmChunk] = []
        sample_cursor = 0
        max_samples = round(self.config.max_audio_seconds * sample_rate)
        silence = np.zeros(
            round(sample_rate * _INTER_SEGMENT_SILENCE_SECONDS),
            dtype=np.float32,
        )
        speaking_rate = min(
            adaptive_speaking_rate(" ".join(chunks)),
            self.config.omnivoice_max_speaking_rate,
        )

        try:
            for index, raw_text in enumerate(chunks):
                if cancel_event.is_set():
                    raise TtsError("E_TTS_CANCELLED", "TTS utterance was cancelled")
                text = _normalize_cues(raw_text)
                if not text:
                    continue
                try:
                    _seed_generation(self.config.generation_seed + index)
                    generated = model.generate(
                        text=text,
                        language="vi",
                        voice_clone_prompt=prompt,
                        speed=speaking_rate,
                        num_step=self.config.inference_timesteps,
                        guidance_scale=self.config.guidance_scale,
                        class_temperature=0.0,
                        denoise=True,
                        preprocess_prompt=True,
                        postprocess_output=True,
                        audio_chunk_duration=self.config.audio_chunk_duration_seconds,
                        audio_chunk_threshold=self.config.audio_chunk_threshold_seconds,
                        pad_duration=0.06,
                        fade_duration=0.03,
                    )
                except Exception as exc:
                    raise TtsError(
                        "E_TTS_INFERENCE",
                        f"OmniVoice failed at speech segment {index + 1}",
                        retryable=True,
                    ) from exc
                if not isinstance(generated, list) or not generated:
                    raise TtsError(
                        "E_TTS_EMPTY_AUDIO",
                        f"OmniVoice segment {index + 1} returned no audio",
                    )
                values = _validated_audio(
                    generated[0],
                    sample_rate=sample_rate,
                    segment=index,
                )
                if first_chunk_ms is None:
                    first_chunk_ms = (time.monotonic() - started) * 1_000
                if output:
                    values = np.concatenate((silence, values))
                pcm = _float_samples_to_pcm16(values)
                start_seconds = sample_cursor / sample_rate
                sample_cursor += len(pcm) // 2
                if sample_cursor > max_samples:
                    cancel_event.set()
                    raise TtsError(
                        "E_TTS_AUDIO_TOO_LONG",
                        "TTS output exceeds the duration limit",
                    )
                output.append(
                    TtsPcmChunk(
                        text=text,
                        pcm16=pcm,
                        start_seconds=start_seconds,
                        end_seconds=sample_cursor / sample_rate,
                    )
                )
                del generated
                del values
        finally:
            self._record_cuda_memory(torch, cuda_available=cuda_available)

        if cancel_event.is_set():
            raise TtsError("E_TTS_CANCELLED", "TTS utterance was cancelled")
        if not output:
            raise TtsError("E_TTS_EMPTY_AUDIO", "OmniVoice returned no audio")
        self._last_error_code = None
        elapsed = (time.monotonic() - started) * 1_000
        return TtsSynthesis(
            sample_rate_hz=sample_rate,
            voice=self.config.voice,
            chunks=tuple(output),
            first_chunk_milliseconds=round(first_chunk_ms or elapsed, 3),
            processing_milliseconds=round(elapsed, 3),
            speaking_rate=speaking_rate,
        )

    def _load_model_sync(self) -> tuple[Any, Any]:
        with self._model_lock:
            if (
                self._model is not None
                and self._voice_prompt is not None
                and not self._recycle_required
            ):
                return self._model, self._voice_prompt
            old_model = self._model
            old_prompt = self._voice_prompt
            self._model = None
            self._voice_prompt = None
            self._model_baseline_allocated_mib = 0.0
            self._warm_request_count = 0
            self._recycle_required = False
            if old_prompt is not None:
                del old_prompt
            if old_model is not None:
                del old_model
            _release_cuda_memory()
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
                factory = self.model_factory or _create_omnivoice
                model = factory(snapshot, self.config)
                prompt = _create_voice_prompt(model, self.config)
                self._model = model
                self._voice_prompt = prompt
                self._model_baseline_allocated_mib = _cuda_allocated_mib()
                return model, prompt
            except TtsError:
                raise
            except Exception as exc:
                raise TtsError(
                    "E_TTS_MODEL_LOAD",
                    "the pinned OmniVoice model could not be loaded",
                    retryable=True,
                ) from exc

    def _record_cuda_memory(self, torch: Any, *, cuda_available: bool) -> None:
        if not cuda_available:
            self._warm_request_count += 1
            return
        self._last_peak_allocated_mib = _bytes_to_mib(
            torch.cuda.max_memory_allocated()
        )
        self._last_peak_reserved_mib = _bytes_to_mib(torch.cuda.max_memory_reserved())
        gc.collect()
        torch.cuda.empty_cache()
        self._last_post_allocated_mib = _bytes_to_mib(torch.cuda.memory_allocated())
        self._warm_request_count += 1
        growth = max(
            0.0,
            self._last_post_allocated_mib - self._model_baseline_allocated_mib,
        )
        if (
            growth > self.config.cuda_growth_recycle_mib
            or self._warm_request_count >= self.config.max_warm_requests
        ):
            self._recycle_required = True


def _create_omnivoice(snapshot: Path, config: TtsConfig) -> Any:
    import torch
    from omnivoice import OmniVoice

    if not torch.cuda.is_available():
        raise TtsError(
            "E_TTS_GPU_UNAVAILABLE",
            "CUDA is required for OmniVoice",
            retryable=True,
        )
    if config.device != "cuda":
        raise TtsError("E_TTS_GPU_UNAVAILABLE", "OmniVoice CPU fallback is disabled")
    if config.precision != "float16":
        raise TtsError(
            "E_TTS_RESOURCE_LEASE",
            "OmniVoice must use the validated float16 CUDA profile",
        )
    model = OmniVoice.from_pretrained(
        str(snapshot),
        device_map="cuda:0",
        dtype=torch.float16,
        attn_implementation="sdpa",
        low_cpu_mem_usage=True,
        local_files_only=True,
        load_asr=False,
    )
    model.eval()
    if not str(model.device).startswith("cuda"):
        raise TtsError("E_TTS_GPU_UNAVAILABLE", "OmniVoice did not load on CUDA")
    if getattr(model, "_asr_pipe", None) is not None:
        raise TtsError("E_TTS_MODEL_LOAD", "OmniVoice loaded an unexpected ASR model")
    return model


def _create_voice_prompt(model: Any, config: TtsConfig) -> Any:
    import torch

    with torch.inference_mode():
        prompt = model.create_voice_clone_prompt(
            ref_audio=str(config.reference_audio_path),
            ref_text=config.reference_text,
            preprocess_prompt=True,
        )
    tokens = getattr(prompt, "ref_audio_tokens", None)
    if tokens is None:
        raise TtsError("E_TTS_VOICE_REFERENCE", "OmniVoice created no voice prompt")
    prompt.ref_audio_tokens = tokens.detach().cpu()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return prompt


def _seed_generation(seed: int) -> None:
    import torch

    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def _validated_audio(raw: Any, *, sample_rate: int, segment: int) -> Any:
    import numpy as np

    values = np.asarray(raw, dtype=np.float32).reshape(-1)
    if values.size < round(sample_rate * 0.15):
        raise TtsError(
            "E_TTS_EMPTY_AUDIO",
            f"OmniVoice segment {segment + 1} was empty",
        )
    if not np.isfinite(values).all():
        raise TtsError(
            "E_TTS_AUDIO",
            f"OmniVoice segment {segment + 1} was non-finite",
        )
    peak = float(np.max(np.abs(values)))
    rms = float(np.sqrt(np.mean(np.square(values, dtype=np.float64))))
    if peak < 1e-4 or rms < 1e-5:
        raise TtsError(
            "E_TTS_EMPTY_AUDIO",
            f"OmniVoice segment {segment + 1} was silent",
        )
    return np.clip(values, -0.99, 0.99)


def _normalize_cues(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        cue = re.sub(r"\s+", " ", match.group(1)).strip().casefold()
        return f" {_CUE_MAP[cue]} " if cue in _CUE_MAP else " "

    return re.sub(r"\s+", " ", _CUE.sub(replace, text)).strip()


def _verify_reference_audio(config: TtsConfig) -> None:
    path = config.reference_audio_path
    if not path.is_file():
        raise TtsError(
            "E_TTS_VOICE_REFERENCE",
            "the fixed Hina reference WAV is missing",
        )
    if not config.reference_text.strip():
        raise TtsError(
            "E_TTS_VOICE_REFERENCE",
            "OmniVoice requires the transcript-aligned Hina reference text",
        )
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
        snapshot = Path(config.model_id)
    else:
        snapshot = (
            cache
            / f"models--{config.model_id.replace('/', '--')}"
            / "snapshots"
            / config.model_revision
        )
    return all((snapshot / name).is_file() for name in _MODEL_PATTERNS)


def _cuda_allocated_mib() -> float:
    try:
        import torch

        if torch.cuda.is_available():
            return _bytes_to_mib(torch.cuda.memory_allocated())
    except Exception:
        pass
    return 0.0


def _bytes_to_mib(value: int) -> float:
    return float(value) / (1024 * 1024)
