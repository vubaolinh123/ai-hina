from __future__ import annotations

import asyncio
import gc
import hashlib
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
from .tts_text import adaptive_speaking_rate


SnapshotDownloader = Callable[..., str]
SdkFactory = Callable[[Path, Path, TtsConfig], Any]

_MODEL_PATTERNS = (
    "denoiser.onnx",
    "speaker_encoder.onnx",
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
_GPU_MODEL_PATTERNS = (
    "config.json",
    "update/config.json",
    "update/model.safetensors",
    "update/special_tokens_map.json",
    "update/tokenizer.json",
    "update/tokenizer_config.json",
    "denoiser.onnx",
    "speaker_encoder.onnx",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
)


class TtsProvider(Protocol):
    async def status(self) -> dict[str, object]: ...

    async def synthesize(
        self,
        chunks: tuple[str, ...],
        cancel_event: threading.Event,
    ) -> TtsSynthesis: ...

    async def unload(self) -> None: ...

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
                and (
                    (
                        self.config.device == "cuda"
                        and importlib.util.find_spec("torch") is not None
                    )
                    or (
                        self.config.device == "cpu"
                        and importlib.util.find_spec("onnxruntime") is not None
                    )
                )
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
            "effectiveDevice": self.config.device,
            "effectivePrecision": self.config.precision,
            "voice": self.config.voice,
            "sampleRateHz": 48_000,
            "downloadOnFirstUse": self.config.allow_download,
            "drainingTimedOutInference": draining,
            "lastErrorCode": self._last_error_code,
        }

    async def warmup(self) -> None:
        """Load and enroll the fixed voice before the first owner utterance."""
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
                    "VieNeu GPU warmup timed out",
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
        first_chunk_ms: float | None = None
        output: list[TtsPcmChunk] = []
        sample_cursor = 0
        max_samples = round(self.config.max_audio_seconds * 48_000)
        speaking_rate = adaptive_speaking_rate(" ".join(chunks))
        try:
            for text in chunks:
                stream = model.infer_stream(
                    text,
                    voice=self.config.voice,
                    style=self.config.style,
                    max_chars=self.config.max_chunk_characters,
                    apply_watermark=True,
                )
                text_samples: list[Any] = []
                text_start = sample_cursor / 48_000
                for samples in stream:
                    if cancel_event.is_set():
                        close = getattr(stream, "close", None)
                        if close is not None:
                            close()
                        raise TtsError("E_TTS_CANCELLED", "TTS utterance was cancelled")
                    values = _float_samples(samples)
                    if values.size == 0:
                        continue
                    if first_chunk_ms is None:
                        first_chunk_ms = (time.monotonic() - started) * 1_000
                    text_samples.append(values)
                if text_samples:
                    import numpy as np

                    joined = np.concatenate(text_samples)
                    paced = _wsola_speed_up(joined, speaking_rate, sample_rate_hz=48_000)
                    pcm = _float_samples_to_pcm16(paced)
                    sample_cursor += len(pcm) // 2
                    if sample_cursor > max_samples:
                        cancel_event.set()
                        raise TtsError(
                            "E_TTS_AUDIO_TOO_LONG",
                            "TTS output exceeds the duration limit",
                        )
                else:
                    pcm = b""
                if pcm:
                    output.append(
                        TtsPcmChunk(
                            text=text,
                            pcm16=pcm,
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
                speaking_rate=speaking_rate,
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
                        allow_patterns=list(
                            _GPU_MODEL_PATTERNS
                            if self.config.device == "cuda"
                            else _MODEL_PATTERNS
                        ),
                        local_files_only=not self.config.allow_download,
                    )
                )
                codec_snapshot = Path(
                    downloader(
                        repo_id=self.config.codec_id,
                        revision=self.config.codec_revision,
                        cache_dir=str(self.config.model_cache),
                        allow_patterns=(
                            None if self.config.device == "cuda"
                            else list(_CODEC_PATTERNS)
                        ),
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
    if config.device == "cuda":
        try:
            import torch
            if not torch.cuda.is_available():
                raise TtsError("E_TTS_GPU_UNAVAILABLE", "CUDA is not available for VieNeu")
        except TtsError:
            raise
        except Exception as exc:
            raise TtsError(
                "E_TTS_GPU_UNAVAILABLE",
                "PyTorch with CUDA is required for GPU VieNeu TTS",
                retryable=True,
            ) from exc
        model = V3TurboVieNeuTTS(
            backbone_repo=str(model_snapshot),
            model_subfolder="update",
            moss_tokenizer=str(codec_snapshot),
            device="cuda",
            dtype=config.precision,
            backend="pytorch",
            max_batch_size=1,
        )
        if config.reference_voice_enabled:
            _verify_reference_audio(config)
            # Avoid torchaudio/FFmpeg path on Windows: decode the authorized
            # WAV through soundfile and keep the actual VieNeu synthesis on CUDA.
            import soundfile as sf
            waveform, sample_rate = sf.read(
                str(config.reference_audio_path),
                dtype="float32",
                always_2d=False,
            )
            speaker_emb, ref_codes = model.engine.prepare_reference(
                waveform,
                sr=int(sample_rate),
                denoise=False,
                use_ref_codes=True,
            )
            model._preset_voices[config.voice] = {
                "description": "Owner-authorized synthetic Vietnamese Hina voice",
                "gender": "female",
                "style": config.style,
                "speaker_emb": speaker_emb,
                "codes": ref_codes,
            }
            model._default_voice = config.voice
        elif config.voice not in {voice_id for _label, voice_id in model.list_preset_voices()}:
            raise TtsError("E_TTS_VOICE", "the pinned preset voice is unavailable")
        return model

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
    if config.reference_voice_enabled:
        _verify_reference_audio(config)
        model.engine.speaker_encoder = _NumpyOnnxSpeakerEncoder(
            model_snapshot / "speaker_encoder.onnx"
        )
        model.add_voice(
            config.voice,
            config.reference_audio_path,
            denoise=True,
            use_ref_codes=True,
            description="Owner-authorized synthetic Vietnamese Hina voice",
            gender="female",
            style=config.style,
            save=False,
        )
    elif config.voice not in {voice_id for _label, voice_id in model.list_preset_voices()}:
        raise TtsError("E_TTS_VOICE", "the pinned preset voice is unavailable")
    model.max_batch_size = 1
    model._batch_engine = None
    return model


def _release_cuda_memory() -> None:
    """Return unreferenced model allocations before another GPU phase starts."""
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        # Unload is best-effort during shutdown/preemption. Admission telemetry
        # remains the source of truth and will still reject an unsafe request.
        return


class _NumpyOnnxSpeakerEncoder:
    """Torch-free 16 kHz log-mel frontend for VieNeu's frozen speaker encoder."""

    def __init__(self, model_path: Path) -> None:
        import onnxruntime as ort

        if not model_path.is_file():
            raise TtsError("E_TTS_VOICE_REFERENCE", "speaker encoder artifact is missing")
        self._session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        self._input = self._session.get_inputs()[0].name
        self._output = self._session.get_outputs()[0].name

    def embed(self, wav: Any, sample_rate_hz: int) -> Any:
        import numpy as np

        samples = np.asarray(wav, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            raise TtsError("E_TTS_VOICE_REFERENCE", "reference WAV is empty")
        if sample_rate_hz != 16_000:
            target_size = max(1, round(samples.size * 16_000 / sample_rate_hz))
            source_axis = np.arange(samples.size, dtype=np.float64)
            target_axis = np.linspace(0, samples.size - 1, target_size)
            samples = np.interp(target_axis, source_axis, samples).astype(np.float32)
        samples = samples[: 16_000 * 30]
        features = _kaldi_style_fbank(samples, sample_rate_hz=16_000, mel_bins=80)
        result = self._session.run(
            [self._output],
            {self._input: features[None].astype(np.float32)},
        )[0]
        embedding = np.asarray(result[0], dtype=np.float32).reshape(-1)
        if embedding.size != 192 or not np.isfinite(embedding).all():
            raise TtsError(
                "E_TTS_VOICE_REFERENCE",
                "speaker encoder returned an invalid embedding",
            )
        return embedding


def _kaldi_style_fbank(samples: Any, *, sample_rate_hz: int, mel_bins: int) -> Any:
    import numpy as np

    frame_length = round(sample_rate_hz * 0.025)
    frame_shift = round(sample_rate_hz * 0.010)
    fft_size = 1 << (frame_length - 1).bit_length()
    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    if values.size < frame_length:
        values = np.pad(values, (0, frame_length - values.size))
    frame_count = 1 + (values.size - frame_length) // frame_shift
    offsets = np.arange(frame_count)[:, None] * frame_shift
    frames = values[offsets + np.arange(frame_length)[None, :]].copy()
    frames -= frames.mean(axis=1, keepdims=True)
    frames[:, 1:] -= 0.97 * frames[:, :-1].copy()
    frames[:, 0] *= 1.0 - 0.97
    frames *= np.hamming(frame_length).astype(np.float32)
    power = np.abs(np.fft.rfft(frames, n=fft_size, axis=1)) ** 2

    low_hz = 20.0
    high_hz = sample_rate_hz / 2
    to_mel = lambda frequency: 1127.0 * np.log1p(frequency / 700.0)
    from_mel = lambda mel: 700.0 * np.expm1(mel / 1127.0)
    mel_points = np.linspace(to_mel(low_hz), to_mel(high_hz), mel_bins + 2)
    hz_points = from_mel(mel_points)
    bins = np.floor((fft_size + 1) * hz_points / sample_rate_hz).astype(int)
    filters = np.zeros((mel_bins, power.shape[1]), dtype=np.float32)
    for index in range(mel_bins):
        left, center, right = bins[index : index + 3]
        center = max(center, left + 1)
        right = max(right, center + 1)
        filters[index, left:center] = (
            np.arange(left, center, dtype=np.float32) - left
        ) / (center - left)
        filters[index, center:right] = (
            right - np.arange(center, right, dtype=np.float32)
        ) / (right - center)
    feature = np.log(np.maximum(power @ filters.T, 1e-10)).astype(np.float32)
    feature -= feature.mean(axis=0, keepdims=True)
    return feature


def _float_samples_to_pcm16(samples: Any) -> bytes:
    values = _float_samples(samples)
    if values.size == 0:
        return b""
    import numpy as np

    clipped = np.clip(values, -1.0, 1.0)
    return (clipped * 32_767.0).astype("<i2").tobytes()


def _float_samples(samples: Any) -> Any:
    try:
        import numpy as np

        values = np.asarray(samples, dtype=np.float32).reshape(-1)
        if not np.isfinite(values).all():
            raise TtsError("E_TTS_AUDIO", "TTS provider returned non-finite samples")
        return values
    except TtsError:
        raise
    except Exception as exc:
        raise TtsError("E_TTS_AUDIO", "TTS provider returned invalid samples") from exc


def _verify_reference_audio(config: TtsConfig) -> None:
    path = config.reference_audio_path
    if not path.is_file():
        raise TtsError("E_TTS_VOICE_REFERENCE", "the authorized Hina reference WAV is missing")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if not hmac_compare_digest(digest, config.reference_audio_sha256):
        raise TtsError(
            "E_TTS_VOICE_REFERENCE",
            "the authorized Hina reference WAV failed its SHA-256 check",
        )


def hmac_compare_digest(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


def _wsola_speed_up(samples: Any, rate: float, *, sample_rate_hz: int) -> Any:
    import numpy as np

    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    if values.size == 0 or rate <= 1.0005:
        return values.copy()
    bounded_rate = min(1.18, max(1.0, float(rate)))
    frame = max(320, round(sample_rate_hz * 0.04))
    overlap = max(80, round(sample_rate_hz * 0.01))
    synthesis_hop = frame - overlap
    analysis_hop = max(synthesis_hop + 1, round(synthesis_hop * bounded_rate))
    search = max(40, round(sample_rate_hz * 0.005))
    if values.size <= frame + search:
        target = max(1, round(values.size / bounded_rate))
        positions = np.linspace(0, values.size - 1, target)
        return np.interp(positions, np.arange(values.size), values).astype(np.float32)

    estimated = max(frame, round(values.size / bounded_rate) + frame)
    output = np.zeros(estimated, dtype=np.float32)
    output[:frame] = values[:frame]
    input_position = 0
    output_position = synthesis_hop
    fade = np.linspace(0.0, 1.0, overlap, dtype=np.float32)
    while output_position + frame <= output.size:
        expected = input_position + analysis_hop
        if expected + frame >= values.size:
            break
        reference = output[output_position : output_position + overlap]
        low = max(0, expected - search)
        high = min(values.size - frame, expected + search)
        best = expected
        best_score = -float("inf")
        ref_energy = float(np.dot(reference, reference))
        for candidate in range(low, high + 1, max(1, search // 24)):
            probe = values[candidate : candidate + overlap]
            energy = ref_energy * float(np.dot(probe, probe))
            score = (
                float(np.dot(reference, probe)) / math.sqrt(energy)
                if energy > 1e-12
                else -1.0
            )
            if score > best_score:
                best_score = score
                best = candidate
        incoming = values[best : best + frame]
        output[output_position : output_position + overlap] = (
            reference * (1.0 - fade) + incoming[:overlap] * fade
        )
        output[
            output_position + overlap : output_position + frame
        ] = incoming[overlap:]
        input_position = best
        output_position += synthesis_hop
    used = min(output.size, output_position + frame)
    target_length = max(frame, round(values.size / bounded_rate))
    return output[: min(used, target_length)]


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
    requirements = (
        (
            config.model_id,
            config.model_revision,
            "update/model.safetensors" if config.device == "cuda"
            else "onnx_int8/vieneu_prefill.onnx",
        ),
        (
            config.codec_id,
            config.codec_revision,
            "model-00001-of-00001.safetensors" if config.device == "cuda"
            else "moss_audio_tokenizer_decode_full.onnx",
        ),
    )
    for repo_id, revision, required in requirements:
        repo = cache / f"models--{repo_id.replace('/', '--')}" / "snapshots" / revision
        if not (repo / required).is_file():
            return False
    return True
