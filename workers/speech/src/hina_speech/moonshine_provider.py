from __future__ import annotations

import asyncio
import importlib.util
import math
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from .config import SpeechConfig
from .errors import SpeechError
from .model import NormalizedAudio, SttResult, SttSegment


class _InferenceTimeout(SpeechError):
    def __init__(self, worker: Future[SttResult]) -> None:
        super().__init__("E_STT_TIMEOUT", "STT inference timed out", retryable=True)
        self.worker = worker


class MoonshineProvider:
    """Moonshine Voice adapter for low-latency Vietnamese on-device STT.

    The upstream package is used through its public Transcriber API; no upstream
    implementation is copied into Hina.
    """

    def __init__(
        self,
        config: SpeechConfig,
        *,
        transcriber_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self.transcriber_factory = transcriber_factory
        self._transcriber: Any | None = None
        self._model_lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hina-moonshine-stt")
        self._closed = False
        self._last_error_code: str | None = None
        self._drain_task: asyncio.Task[None] | None = None

    async def status(self) -> dict[str, object]:
        dependency_available = self.transcriber_factory is not None or (
            importlib.util.find_spec("moonshine_voice") is not None
        )
        return {
            "available": dependency_available,
            "dependencyAvailable": dependency_available,
            "modelLoaded": self._transcriber is not None,
            "operatorResident": self._transcriber is not None,
            "modelCached": _model_is_cached(self.config),
            "effectiveDevice": "cpu",
            "downloadOnFirstUse": self.config.allow_download,
            "lastErrorCode": self._last_error_code,
            "drainingTimedOutInference": self._drain_task is not None and not self._drain_task.done(),
        }

    async def warmup(self) -> None:
        if self._closed:
            raise SpeechError("E_STT_UNAVAILABLE", "STT provider is closed", retryable=True)
        async with self._model_lock:
            await asyncio.get_running_loop().run_in_executor(
                self._executor,
                self._load_transcriber,
            )

    async def transcribe(self, audio: NormalizedAudio) -> SttResult:
        if audio.sample_rate_hz != 16_000:
            raise SpeechError("E_STT_AUDIO", "STT provider requires normalized 16 kHz audio")
        if self._closed:
            raise SpeechError("E_STT_UNAVAILABLE", "STT provider is closed", retryable=True)
        if self._drain_task is not None and not self._drain_task.done():
            raise SpeechError("E_STT_DRAINING", "a timed-out STT inference is still draining", retryable=True)
        async with self._model_lock:
            worker = self._executor.submit(self._transcribe_sync, audio)
            try:
                return await asyncio.wait_for(
                    asyncio.shield(asyncio.wrap_future(worker)),
                    timeout=self.config.request_timeout_seconds,
                )
            except TimeoutError as exc:
                self._last_error_code = "E_STT_TIMEOUT"
                self._drain_task = asyncio.create_task(self._finish_drain(worker))
                raise _InferenceTimeout(worker) from exc
            except SpeechError as exc:
                self._last_error_code = exc.code
                raise
            except Exception as exc:
                self._last_error_code = "E_STT_INFERENCE"
                raise SpeechError("E_STT_INFERENCE", "Moonshine inference failed", retryable=True) from exc

    async def _finish_drain(self, worker: Future[SttResult]) -> None:
        try:
            await asyncio.shield(asyncio.wrap_future(worker))
        except Exception:
            pass
        finally:
            self._drain_task = None

    async def unload(self) -> None:
        if self._drain_task is not None:
            await asyncio.shield(self._drain_task)
        async with self._model_lock:
            transcriber = self._transcriber
            self._transcriber = None
        if transcriber is not None:
            close = getattr(transcriber, "close", None)
            if callable(close):
                close()

    async def close(self) -> None:
        self._closed = True
        await self.unload()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _transcribe_sync(self, audio: NormalizedAudio) -> SttResult:
        transcriber = self._load_transcriber()
        try:
            transcript = transcriber.transcribe_without_streaming(
                list(audio.samples),
                sample_rate=audio.sample_rate_hz,
            )
            segments: list[SttSegment] = []
            for line in getattr(transcript, "lines", ()):
                text = str(getattr(line, "text", "")).strip()
                if not text:
                    continue
                start = max(0.0, float(getattr(line, "start_time", 0.0)))
                end = max(start, start + float(getattr(line, "duration", 0.0)))
                words = getattr(line, "words", None) or ()
                confidence = (
                    sum(max(0.0, min(1.0, float(getattr(word, "confidence", 1.0)))) for word in words)
                    / len(words)
                    if words
                    else 1.0
                )
                segments.append(SttSegment(start, end, text, confidence))
            return SttResult(
                text=" ".join(segment.text for segment in segments).strip(),
                language="vi",
                language_probability=1.0,
                duration_seconds=audio.duration_seconds,
                segments=tuple(segments),
            )
        except SpeechError:
            raise
        except Exception as exc:
            raise SpeechError("E_STT_INFERENCE", "Moonshine rejected the audio", retryable=True) from exc

    def _load_transcriber(self) -> Any:
        if self._transcriber is not None:
            return self._transcriber
        factory = self.transcriber_factory
        model_path: str | Path
        model_arch: Any = self.config.model_arch
        if factory is None:
            if not self.config.allow_download and not _model_is_cached(self.config):
                raise SpeechError(
                    "E_STT_MODEL_LOAD",
                    "cached Moonshine model is unavailable",
                    retryable=True,
                )
            try:
                from moonshine_voice import ModelArch, Transcriber, get_model_for_language
            except ImportError as exc:
                raise SpeechError("E_STT_UNAVAILABLE", "moonshine-voice is not installed", retryable=True) from exc
            factory = Transcriber
            model_arch = ModelArch(self.config.model_arch)
            try:
                model_path, model_arch = get_model_for_language(
                    wanted_language=self.config.language,
                    wanted_model_arch=model_arch,
                    cache_root=self.config.model_cache,
                )
            except Exception as exc:
                if not self.config.allow_download:
                    raise SpeechError("E_STT_MODEL_LOAD", "cached Moonshine model is unavailable", retryable=True) from exc
                raise SpeechError("E_STT_MODEL_LOAD", "Moonshine model download/load failed", retryable=True) from exc
        else:
            model_path = self.config.model_id
        options = {"max_tokens_per_second": 13.0} if self.config.language != "en" else {}
        try:
            self._transcriber = factory(
                model_path=model_path,
                model_arch=model_arch,
                options=options,
            )
            self._last_error_code = None
            return self._transcriber
        except Exception as exc:
            raise SpeechError("E_STT_MODEL_LOAD", "the Moonshine model could not be loaded", retryable=True) from exc


def _model_is_cached(config: SpeechConfig) -> bool:
    if Path(config.model_id).is_dir():
        return True
    root = config.model_cache
    if not root.exists():
        return False
    return any(root.rglob("encoder_model.ort"))
