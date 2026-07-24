from __future__ import annotations

import asyncio
import importlib.util
import math
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from .config import SpeechConfig
from .errors import SpeechError
from .model import NormalizedAudio, SttResult, SttSegment


class GpuLease(Protocol):
    def assert_active(self) -> None: ...

    async def release(self) -> bool: ...


GpuLeaseFactory = Callable[[Callable[[], Awaitable[None]]], Awaitable[GpuLease]]


class SttProvider(Protocol):
    async def status(self) -> dict[str, object]: ...

    async def transcribe(self, audio: NormalizedAudio) -> SttResult: ...

    async def unload(self) -> None: ...


class FasterWhisperProvider:
    def __init__(
        self,
        config: SpeechConfig,
        *,
        gpu_lease_factory: GpuLeaseFactory | None = None,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self.gpu_lease_factory = gpu_lease_factory
        self.model_factory = model_factory
        self._model: Any | None = None
        self._model_lock = asyncio.Lock()
        self._last_error_code: str | None = None
        self._effective_device = config.device

    async def status(self) -> dict[str, object]:
        dependency_available = (
            self.model_factory is not None
            or (
                importlib.util.find_spec("faster_whisper") is not None
                and importlib.util.find_spec("numpy") is not None
            )
        )
        return {
            "available": dependency_available,
            "dependencyAvailable": dependency_available,
            "modelLoaded": self._model is not None,
            "modelCached": _model_is_cached(self.config),
            "effectiveDevice": self._effective_device,
            "downloadOnFirstUse": self.config.allow_download,
            "lastErrorCode": self._last_error_code,
        }

    async def transcribe(self, audio: NormalizedAudio) -> SttResult:
        if audio.sample_rate_hz != 16_000:
            raise SpeechError("E_STT_AUDIO", "STT provider requires normalized 16 kHz audio")
        lease: GpuLease | None = None
        device = self.config.device
        if device == "cuda":
            if self.gpu_lease_factory is None:
                if not self.config.fallback_to_cpu:
                    raise SpeechError(
                        "E_STT_RESOURCE_LEASE",
                        "CUDA STT requires a resource lease",
                        retryable=True,
                    )
                device = "cpu"
            else:
                try:
                    lease = await self.gpu_lease_factory(self.unload)
                    lease.assert_active()
                except Exception as exc:
                    if not self.config.fallback_to_cpu:
                        raise SpeechError(
                            "E_STT_RESOURCE_LEASE",
                            "CUDA STT resource lease was denied",
                            retryable=True,
                        ) from exc
                    device = "cpu"
        try:
            try:
                return await self._run_device(audio, device)
            except SpeechError:
                if device != "cuda" or not self.config.fallback_to_cpu:
                    raise
                if lease is not None:
                    await lease.release()
                    lease = None
                await self.unload()
                return await self._run_device(audio, "cpu")
        finally:
            if lease is not None:
                await lease.release()

    async def _run_device(self, audio: NormalizedAudio, device: str) -> SttResult:
        try:
            async with self._model_lock:
                self._effective_device = device
                return await asyncio.wait_for(
                    asyncio.to_thread(self._transcribe_sync, audio, device),
                    timeout=self.config.request_timeout_seconds,
                )
        except TimeoutError as exc:
            self._last_error_code = "E_STT_TIMEOUT"
            raise SpeechError("E_STT_TIMEOUT", "STT inference timed out", retryable=True) from exc
        except SpeechError as exc:
            self._last_error_code = exc.code
            raise
        except Exception as exc:
            self._last_error_code = "E_STT_INFERENCE"
            raise SpeechError(
                "E_STT_INFERENCE",
                "faster-whisper inference failed",
                retryable=True,
            ) from exc

    async def unload(self) -> None:
        async with self._model_lock:
            self._model = None

    def _transcribe_sync(self, audio: NormalizedAudio, device: str) -> SttResult:
        model = self._load_model(device)
        try:
            import numpy as np

            samples = np.asarray(audio.samples, dtype=np.float32)
            raw_segments, info = model.transcribe(
                samples,
                language="vi",
                task="transcribe",
                beam_size=self.config.beam_size,
                temperature=0,
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters={
                    "min_speech_duration_ms": 120,
                    "min_silence_duration_ms": 300,
                    "speech_pad_ms": 120,
                },
                word_timestamps=False,
            )
            segments: list[SttSegment] = []
            for segment in raw_segments:
                text = str(segment.text).strip()
                if not text:
                    continue
                no_speech_probability = float(getattr(segment, "no_speech_prob", 0.0))
                average_log_probability = float(getattr(segment, "avg_logprob", -1.0))
                if no_speech_probability >= 0.8 and average_log_probability < -0.8:
                    continue
                confidence = max(0.0, min(1.0, math.exp(min(0.0, average_log_probability))))
                segments.append(
                    SttSegment(
                        start_seconds=max(0.0, float(segment.start)),
                        end_seconds=max(float(segment.start), float(segment.end)),
                        text=text,
                        confidence=confidence,
                    )
                )
            transcript = " ".join(segment.text for segment in segments).strip()
            return SttResult(
                text=transcript,
                language="vi",
                language_probability=float(getattr(info, "language_probability", 1.0)),
                duration_seconds=audio.duration_seconds,
                segments=tuple(segments),
            )
        except SpeechError:
            raise
        except Exception as exc:
            raise SpeechError(
                "E_STT_INFERENCE",
                "faster-whisper rejected the audio",
                retryable=True,
            ) from exc

    def _load_model(self, device: str) -> Any:
        if self._model is not None and self._effective_device == device:
            return self._model
        factory = self.model_factory
        if factory is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise SpeechError(
                    "E_STT_UNAVAILABLE",
                    "faster-whisper is not installed",
                    retryable=True,
                ) from exc
            factory = WhisperModel
        compute_type = self.config.compute_type
        if device == "cpu" and compute_type in {"float16", "int8_float16"}:
            compute_type = "int8"
        try:
            self.config.model_cache.mkdir(parents=True, exist_ok=True)
            self._model = factory(
                self.config.model_id,
                device=device,
                compute_type=compute_type,
                cpu_threads=self.config.cpu_threads,
                download_root=str(self.config.model_cache),
                local_files_only=not self.config.allow_download,
                revision=self.config.model_revision,
            )
            self._effective_device = device
            self._last_error_code = None
            return self._model
        except Exception as exc:
            raise SpeechError(
                "E_STT_MODEL_LOAD",
                "the pinned faster-whisper model could not be loaded",
                retryable=True,
            ) from exc


def _model_is_cached(config: SpeechConfig) -> bool:
    cache = config.model_cache
    if Path(config.model_id).is_dir():
        return True
    if not cache.exists():
        return False
    revision = config.model_revision
    repo_folder = f"models--{config.model_id.replace('/', '--')}"
    candidates = (
        cache / repo_folder / "snapshots" / revision,
        cache / revision,
    )
    return any((candidate / "model.bin").is_file() for candidate in candidates)
