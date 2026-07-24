from __future__ import annotations

import asyncio
import importlib.util
import math
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol

from .errors import TtsError
from .model import TtsPcmChunk, TtsSynthesis
from .tts_config import TtsConfig


SnapshotDownloader = Callable[..., str]
SdkFactory = Callable[[Path, Path, TtsConfig], Any]

_MODEL_PATTERNS = (
    "onnx_int8/config.json",
    "onnx_int8/tokenizer.json",
    "onnx_int8/vieneu_acoustic_cached.onnx",
    "onnx_int8/vieneu_backbone_shared.data",
    "onnx_int8/vieneu_decode_step.onnx",
    "onnx_int8/vieneu_prefill.onnx",
    "onnx_int8/vieneu_v3_heads.npz",
)
_CODEC_PATTERNS = (
    "codec_browser_onnx_meta.json",
    "moss_audio_tokenizer_decode_full.onnx",
    "moss_audio_tokenizer_decode_shared.data",
    "moss_audio_tokenizer_decode_step.onnx",
    "moss_audio_tokenizer_encode.data",
    "moss_audio_tokenizer_encode.onnx",
)


class TtsProvider(Protocol):
    async def status(self) -> dict[str, object]: ...

    async def synthesize(
        self,
        chunks: tuple[str, ...],
        cancel_event: threading.Event,
    ) -> TtsSynthesis: ...

    async def close(self) -> None: ...


class _NativeTtsTimeout(TtsError):
    def __init__(self, worker: Future[TtsSynthesis]) -> None:
        super().__init__("E_TTS_TIMEOUT", "TTS inference timed out", retryable=True)
        self.worker = worker


class VieneuTtsProvider:
    def __init__(
        self,
        config: TtsConfig,
        *,
        snapshot_downloader: SnapshotDownloader | None = None,
        sdk_factory: SdkFactory | None = None,
    ) -> None:
        self.config = config
        self.snapshot_downloader = snapshot_downloader
        self.sdk_factory = sdk_factory
        self._model: Any | None = None
        self._model_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hina-tts")
        self._active_worker: Future[TtsSynthesis] | None = None
        self._active_cancel: threading.Event | None = None
        self._drain_task: asyncio.Task[None] | None = None
        self._state_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()
        self._last_error_code: str | None = None
        self._closed = False

    async def status(self) -> dict[str, object]:
        dependency_available = (
            self.sdk_factory is not None
            or (
                importlib.util.find_spec("vieneu") is not None
                and importlib.util.find_spec("onnxruntime") is not None
                and importlib.util.find_spec("huggingface_hub") is not None
            )
        )
        draining = self._drain_task is not None and not self._drain_task.done()
        model_cached = _snapshots_are_cached(self.config)
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
            "effectiveDevice": "cpu",
            "effectivePrecision": "int8",
            "voice": self.config.voice,
            "sampleRateHz": 48_000,
            "downloadOnFirstUse": self.config.allow_download,
            "drainingTimedOutInference": draining,
            "lastErrorCode": self._last_error_code,
        }

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
                    "a timed-out TTS inference is still draining",
                    retryable=True,
                )
            worker = self._executor.submit(self._synthesize_sync, chunks, cancel_event)
            async_worker = asyncio.wrap_future(worker)
            async_worker.add_done_callback(_consume_asyncio_future)
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
                raise _NativeTtsTimeout(worker) from exc
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
                    "VieNeu-TTS inference failed",
                    retryable=True,
                ) from exc
        except _NativeTtsTimeout as exc:
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
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._model = None

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
        first_chunk_ms: float | None = None
        output: list[TtsPcmChunk] = []
        sample_cursor = 0
        max_samples = round(self.config.max_audio_seconds * 48_000)
        try:
            for text in chunks:
                stream = model.infer_stream(
                    text,
                    voice=self.config.voice,
                    style=self.config.style,
                    max_chars=self.config.max_chunk_characters,
                    apply_watermark=True,
                )
                text_pcm = bytearray()
                text_start = sample_cursor / 48_000
                for samples in stream:
                    if cancel_event.is_set():
                        close = getattr(stream, "close", None)
                        if close is not None:
                            close()
                        raise TtsError("E_TTS_CANCELLED", "TTS utterance was cancelled")
                    pcm = _float_samples_to_pcm16(samples)
                    if not pcm:
                        continue
                    if first_chunk_ms is None:
                        first_chunk_ms = (time.monotonic() - started) * 1_000
                    text_pcm.extend(pcm)
                    sample_cursor += len(pcm) // 2
                    if sample_cursor > max_samples:
                        cancel_event.set()
                        raise TtsError(
                            "E_TTS_AUDIO_TOO_LONG",
                            "TTS output exceeds the duration limit",
                        )
                if text_pcm:
                    output.append(
                        TtsPcmChunk(
                            text=text,
                            pcm16=bytes(text_pcm),
                            start_seconds=text_start,
                            end_seconds=sample_cursor / 48_000,
                        )
                    )
            if cancel_event.is_set():
                raise TtsError("E_TTS_CANCELLED", "TTS utterance was cancelled")
            if not output:
                raise TtsError("E_TTS_EMPTY_AUDIO", "VieNeu-TTS returned no audio")
            self._last_error_code = None
            return TtsSynthesis(
                sample_rate_hz=48_000,
                voice=self.config.voice,
                chunks=tuple(output),
                first_chunk_milliseconds=round(first_chunk_ms or 0.0, 3),
                processing_milliseconds=round((time.monotonic() - started) * 1_000, 3),
            )
        except TtsError:
            raise
        except Exception as exc:
            raise TtsError(
                "E_TTS_INFERENCE",
                "VieNeu-TTS rejected the utterance",
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
                        allow_patterns=list(_MODEL_PATTERNS),
                        local_files_only=not self.config.allow_download,
                    )
                )
                codec_snapshot = Path(
                    downloader(
                        repo_id=self.config.codec_id,
                        revision=self.config.codec_revision,
                        cache_dir=str(self.config.model_cache),
                        allow_patterns=list(_CODEC_PATTERNS),
                        local_files_only=not self.config.allow_download,
                    )
                )
                factory = self.sdk_factory or _create_pinned_vieneu
                self._model = factory(model_snapshot, codec_snapshot, self.config)
                return self._model
            except TtsError:
                raise
            except Exception as exc:
                raise TtsError(
                    "E_TTS_MODEL_LOAD",
                    "the pinned VieNeu-TTS model or codec could not be loaded",
                    retryable=True,
                ) from exc


def _create_pinned_vieneu(
    model_snapshot: Path,
    codec_snapshot: Path,
    config: TtsConfig,
) -> Any:
    from vieneu.base import BaseVieneuTTS
    from vieneu.v3turbo import V3TurboVieNeuTTS
    from vieneu._v3_turbo_engine.onnx_runtime_lite import OnnxV3LiteEngine

    model = V3TurboVieNeuTTS.__new__(V3TurboVieNeuTTS)
    BaseVieneuTTS.__init__(model)
    model.sample_rate = 48_000
    model.engine = OnnxV3LiteEngine(
        checkpoint_path=str(model_snapshot),
        onnx_dir=str(model_snapshot / "onnx_int8"),
        codec_dir=str(codec_snapshot),
        threads=config.cpu_threads,
    )
    model.backend = "onnx"
    model.default_style = "tu_nhien"
    model._preset_voices = {}
    model._default_voice = None
    model._load_v3_voices()
    if config.voice not in {voice_id for _label, voice_id in model.list_preset_voices()}:
        raise TtsError("E_TTS_VOICE", "the pinned preset voice is unavailable")
    model.max_batch_size = 1
    model._batch_engine = None
    return model


def _float_samples_to_pcm16(samples: Any) -> bytes:
    try:
        import numpy as np

        values = np.asarray(samples, dtype=np.float32).reshape(-1)
        if values.size == 0:
            return b""
        if not np.isfinite(values).all():
            raise TtsError("E_TTS_AUDIO", "TTS provider returned non-finite samples")
        clipped = np.clip(values, -1.0, 1.0)
        return (clipped * 32_767.0).astype("<i2").tobytes()
    except TtsError:
        raise
    except Exception as exc:
        raise TtsError("E_TTS_AUDIO", "TTS provider returned invalid samples") from exc


async def _wait_for_native_worker(worker: Future[TtsSynthesis]) -> None:
    while not worker.done():
        try:
            await asyncio.shield(asyncio.wrap_future(worker))
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
        except Exception:
            break
    try:
        worker.result()
    except Exception:
        pass


def _consume_asyncio_future(future: asyncio.Future[TtsSynthesis]) -> None:
    if future.cancelled():
        return
    try:
        future.exception()
    except (asyncio.CancelledError, Exception):
        pass


def _snapshots_are_cached(config: TtsConfig) -> bool:
    cache = config.model_cache
    if not cache.is_dir():
        return False
    for repo_id, revision, required in (
        (config.model_id, config.model_revision, "onnx_int8/vieneu_prefill.onnx"),
        (config.codec_id, config.codec_revision, "moss_audio_tokenizer_decode_full.onnx"),
    ):
        repo = cache / f"models--{repo_id.replace('/', '--')}" / "snapshots" / revision
        if not (repo / required).is_file():
            return False
    return True
