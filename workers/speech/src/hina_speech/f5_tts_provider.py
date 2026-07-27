from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from .errors import TtsError
from .model import TtsPcmChunk, TtsSynthesis
from .tts_config import TtsConfig
from .tts_provider import (
    _float_samples,
    _float_samples_to_pcm16,
    _release_cuda_memory,
    _wait_for_native_worker,
    _wsola_speed_up,
)
from .tts_text import adaptive_speaking_rate


SnapshotDownloader = Callable[..., str]
F5Factory = Callable[[Path, Path, TtsConfig], Any]


class _NativeF5Timeout(TtsError):
    def __init__(self, worker: Future[TtsSynthesis]) -> None:
        super().__init__("E_TTS_TIMEOUT", "F5-TTS inference timed out", retryable=True)
        self.worker = worker


class F5TtsProvider:
    """GPU-only F5-TTS adapter for the owner-authorized Hina reference voice.

    The provider uses the official F5-TTS Python package and the pinned ZaloPay
    Vietnamese checkpoint. The complete voice_demo directory is audited by the
    preparation tool, while inference uses one transcript-aligned reference clip
    as required by F5-TTS zero-shot conditioning.
    """

    def __init__(
        self,
        config: TtsConfig,
        *,
        snapshot_downloader: SnapshotDownloader | None = None,
        model_factory: F5Factory | None = None,
    ) -> None:
        self.config = config
        self.snapshot_downloader = snapshot_downloader
        self.model_factory = model_factory
        self._model: Any | None = None
        self._model_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hina-f5-tts")
        self._active_worker: Future[TtsSynthesis] | None = None
        self._active_cancel: threading.Event | None = None
        self._drain_task: asyncio.Task[None] | None = None
        self._state_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()
        self._last_error_code: str | None = None
        self._closed = False

    async def status(self) -> dict[str, object]:
        dependency_available = self.model_factory is not None or (
            importlib.util.find_spec("f5_tts") is not None
            and importlib.util.find_spec("torch") is not None
            and importlib.util.find_spec("vocos") is not None
        )
        model_cached = _snapshots_are_cached(self.config)
        draining = self._drain_task is not None and not self._drain_task.done()
        return {
            "available": (
                dependency_available
                and (self.config.allow_download or model_cached)
                and not self._closed
                and not draining
            ),
            "dependencyAvailable": dependency_available,
            "modelLoaded": self._model is not None,
            "modelCached": model_cached,
            "effectiveDevice": self.config.device,
            "effectivePrecision": self.config.precision,
            "voice": self.config.voice,
            "sampleRateHz": 24_000,
            "downloadOnFirstUse": self.config.allow_download,
            "referenceAudio": str(self.config.reference_audio_path),
            "referenceAudioSha256": self.config.reference_audio_sha256 or None,
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
                    "F5-TTS GPU warmup timed out",
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
                    "a timed-out F5-TTS inference is still draining",
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
                raise _NativeF5Timeout(worker) from exc
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
                    "F5-TTS inference failed",
                    retryable=True,
                ) from exc
        except _NativeF5Timeout as exc:
            async with self._state_lock:
                self._drain_task = asyncio.create_task(self._finish_drain(exc.worker))
            raise
        finally:
            async with self._state_lock:
                if self._active_worker is worker and worker.done():
                    self._active_worker = None
                    self._active_cancel = None

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
        started = time.monotonic()
        model = self._load_model_sync()
        if cancel_event.is_set():
            raise TtsError("E_TTS_CANCELLED", "TTS utterance was cancelled")
        speaking_rate = adaptive_speaking_rate(" ".join(chunks))
        text = " ".join(_strip_f5_cues(chunk) for chunk in chunks).strip()
        if not text:
            raise TtsError("E_TTS_EMPTY_TEXT", "F5-TTS received no speakable text")
        try:
            samples, sample_rate = model.infer(
                text,
                speed=speaking_rate,
                nfe_step=self.config.nfe_step,
            )
            if cancel_event.is_set():
                raise TtsError("E_TTS_CANCELLED", "TTS utterance was cancelled")
            values = _float_samples(samples)
            if values.size == 0:
                raise TtsError("E_TTS_EMPTY_AUDIO", "F5-TTS returned no audio")
            if int(sample_rate) != 24_000:
                raise TtsError("E_TTS_AUDIO", "F5-TTS returned an unexpected sample rate")
            paced = _wsola_speed_up(values, speaking_rate, sample_rate_hz=24_000)
            pcm = _float_samples_to_pcm16(paced)
            duration = len(pcm) / 2 / 24_000
            if duration > self.config.max_audio_seconds:
                raise TtsError(
                    "E_TTS_AUDIO_TOO_LONG",
                    "TTS output exceeds the duration limit",
                )
            self._last_error_code = None
            chunk = TtsPcmChunk(
                text=text,
                pcm16=pcm,
                start_seconds=0.0,
                end_seconds=duration,
            )
            elapsed = (time.monotonic() - started) * 1_000
            return TtsSynthesis(
                sample_rate_hz=24_000,
                voice=self.config.voice,
                chunks=(chunk,),
                first_chunk_milliseconds=round(elapsed, 3),
                processing_milliseconds=round(elapsed, 3),
                speaking_rate=speaking_rate,
            )
        except TtsError:
            raise
        except Exception as exc:
            raise TtsError(
                "E_TTS_INFERENCE",
                "F5-TTS rejected the utterance",
                retryable=True,
            ) from exc

    def _load_model_sync(self) -> Any:
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                downloader = self.snapshot_downloader
                if downloader is None:
                    from huggingface_hub import snapshot_download

                    downloader = snapshot_download
                model_snapshot = Path(
                    downloader(
                        repo_id=self.config.model_id,
                        revision=self.config.model_revision,
                        cache_dir=str(self.config.model_cache),
                        allow_patterns=[self.config.model_file, "vocab.txt"],
                        local_files_only=not self.config.allow_download,
                    )
                )
                vocoder_snapshot = Path(
                    downloader(
                        repo_id=self.config.vocoder_id,
                        revision=self.config.vocoder_revision,
                        cache_dir=str(self.config.model_cache),
                        allow_patterns=["config.yaml", "pytorch_model.bin"],
                        local_files_only=not self.config.allow_download,
                    )
                )
                _verify_reference_audio(self.config)
                factory = self.model_factory or _create_f5_model
                self._model = factory(model_snapshot, vocoder_snapshot, self.config)
                return self._model
            except TtsError:
                raise
            except Exception as exc:
                raise TtsError(
                    "E_TTS_MODEL_LOAD",
                    "the pinned F5-TTS model or vocoder could not be loaded",
                    retryable=True,
                ) from exc


def _create_f5_model(
    model_snapshot: Path,
    vocoder_snapshot: Path,
    config: TtsConfig,
) -> Any:
    import torch
    from f5_tts.infer.utils_infer import load_model, load_vocoder
    from f5_tts.model import DiT

    if not torch.cuda.is_available():
        raise TtsError("E_TTS_GPU_UNAVAILABLE", "CUDA is required for F5-TTS", retryable=True)
    model_path = model_snapshot / config.model_file
    vocab_path = model_snapshot / "vocab.txt"
    if not model_path.is_file() or not vocab_path.is_file():
        raise TtsError("E_TTS_MODEL_LOAD", "F5-TTS checkpoint files are missing")
    vocoder = load_vocoder(
        "vocos",
        is_local=True,
        local_path=str(vocoder_snapshot),
        device="cuda",
        hf_cache_dir=str(config.model_cache),
    )
    model = load_model(
        DiT,
        dict(dim=1024, depth=22, heads=16, ff_mult=2, text_dim=512, conv_layers=4),
        ckpt_path=str(model_path),
        mel_spec_type="vocos",
        vocab_file=str(vocab_path),
        device="cuda",
    )

    class Runtime:
        def infer(self, text: str, *, speed: float, nfe_step: int) -> tuple[Any, int]:
            import io
            from contextlib import redirect_stdout
            import soundfile as sf
            from f5_tts.infer.utils_infer import (
                chunk_text,
                infer_batch_process,
                preprocess_ref_audio_text,
            )

            with redirect_stdout(io.StringIO()):
                ref_audio, ref_text = preprocess_ref_audio_text(
                    str(config.reference_audio_path),
                    config.reference_text,
                    show_info=lambda _message: None,
                )
                waveform, sample_rate = sf.read(
                    ref_audio,
                    dtype="float32",
                    always_2d=True,
                )
                audio = torch.from_numpy(waveform.T.copy())
                reference_seconds = audio.shape[-1] / int(sample_rate)
                max_chars = max(
                    32,
                    int(
                        len(ref_text.encode("utf-8"))
                        / max(reference_seconds, 0.1)
                        * max(2.0, 22.0 - reference_seconds)
                        * speed
                    ),
                )
                batches = chunk_text(text, max_chars=max_chars)
                result = next(
                    infer_batch_process(
                        (audio, int(sample_rate)),
                        ref_text,
                        batches,
                        model,
                        vocoder,
                        mel_spec_type="vocos",
                        progress=None,
                        nfe_step=nfe_step,
                        speed=speed,
                        device="cuda",
                    )
                )
            waveform, sample_rate, _spectrogram = result
            return waveform, int(sample_rate)

    return Runtime()


def _verify_reference_audio(config: TtsConfig) -> None:
    path = config.reference_audio_path
    if not path.is_file():
        raise TtsError("E_TTS_VOICE_REFERENCE", "the Hina F5 reference WAV is missing")
    if config.reference_audio_sha256:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != config.reference_audio_sha256:
            raise TtsError(
                "E_TTS_VOICE_REFERENCE",
                "the Hina F5 reference WAV failed its SHA-256 check",
            )


def _strip_f5_cues(text: str) -> str:
    import re

    return re.sub(r"\[[^\[\]]{1,48}\]", "", text).replace("  ", " ").strip()


def _snapshots_are_cached(config: TtsConfig) -> bool:
    cache = config.model_cache
    if not cache.is_dir():
        return False
    model_repo = cache / f"models--{config.model_id.replace('/', '--')}" / "snapshots" / config.model_revision
    vocoder_repo = cache / f"models--{config.vocoder_id.replace('/', '--')}" / "snapshots" / config.vocoder_revision
    return (
        (model_repo / config.model_file).is_file()
        and (model_repo / "vocab.txt").is_file()
        and (vocoder_repo / "config.yaml").is_file()
        and (vocoder_repo / "pytorch_model.bin").is_file()
    )
