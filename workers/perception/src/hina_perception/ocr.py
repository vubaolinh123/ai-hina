from __future__ import annotations

import asyncio
import gc
import hashlib
import importlib.metadata
import importlib.util
import math
import os
import re
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.error import URLError
from urllib.request import urlopen

from .config import OcrConfig
from .errors import PerceptionError


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_ARTIFACT_DOWNLOAD_TIMEOUT_SECONDS = 90


@dataclass(frozen=True, slots=True)
class _Artifact:
    filename: str
    url: str
    sha256: str


# RapidOCR 3.9.1's model manifest pins these URLs and hashes.  We download the
# reviewed artifacts ourselves rather than relying on its default package cache,
# which keeps the cache location, exact file identities, and no-CPU guarantee
# explicit in Hina's own boundary.
_ARTIFACTS = (
    _Artifact(
        "PP-OCRv6_det_small.pth",
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.1/"
        "torch/PP-OCRv6/det/PP-OCRv6_det_small.pth",
        "fbdc74c97ea7b770ab22cbdc1bba01a52bdf1975efcf3442057356d622b05d54",
    ),
    _Artifact(
        "PP-OCRv6_rec_small.pth",
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.1/"
        "torch/PP-OCRv6/rec/PP-OCRv6_rec_small.pth",
        "0107b2ad694ccc9b1db7cf9ed3ffbc93d1795d9e08d9cf823127243a87bce516",
    ),
    _Artifact(
        "ch_ptocr_mobile_v2.0_cls_mobile.pth",
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.1/"
        "torch/PP-OCRv4/cls/ch_ptocr_mobile_v2.0_cls_mobile.pth",
        "bfe13860824b3365c0c7f7ccfcddc8ff11645c60051739ff18bc9913f60c98e1",
    ),
    _Artifact(
        "ppocrv6_dict.txt",
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.1/"
        "paddle/PP-OCRv6/rec/PP-OCRv6_rec_small/ppocrv6_dict.txt",
        "b5f2bfe2bdd9448429e3e82b51c789775d9b42f2403d082b00662eb77e401c5d",
    ),
)


class OcrProvider(Protocol):
    """A bounded local OCR adapter.

    The interface consumes the transient PNG bytes directly.  OCR providers
    must not retain those bytes or return image/crop data.
    """

    async def status(self) -> dict[str, Any]: ...

    async def recognize(self, encoded_png: bytes) -> dict[str, Any]: ...

    async def unload(self) -> None: ...

    async def close(self) -> None: ...


class OcrGpuLease(Protocol):
    @property
    def state(self) -> str: ...

    def assert_active(self) -> None: ...

    async def release(self) -> bool: ...


OcrGpuLeaseFactory = Callable[[Callable[[], Awaitable[None]]], Awaitable[OcrGpuLease]]
OcrEngineFactory = Callable[[dict[str, Any]], Any]
ArtifactEnsurer = Callable[[tuple[_Artifact, ...], OcrConfig], None]


class RapidOcrProvider:
    """RapidOCR PP-OCRv6 with a strict Torch CUDA-only runtime.

    `RapidOCR` creates its detector, recognizer and orientation classifier at
    construction even if orientation is disabled for calls.  All three are
    therefore pinned to Torch CUDA.  This removes the upstream default
    ONNXRuntime CPU path completely instead of merely hoping it is unused.
    """

    def __init__(
        self,
        config: OcrConfig,
        *,
        engine_factory: OcrEngineFactory | None = None,
        artifact_ensurer: ArtifactEnsurer | None = None,
        cuda_available: Callable[[], bool] | None = None,
    ) -> None:
        self.config = config
        self._engine_factory = engine_factory
        self._artifact_ensurer = artifact_ensurer or _ensure_artifacts
        self._cuda_available = cuda_available
        self._engine: Any | None = None
        self._effective_device: str | None = None
        self._last_error_code: str | None = None
        self._closed = False
        self._operation_lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hina-ocr")

    async def status(self) -> dict[str, Any]:
        dependency_available = (
            importlib.util.find_spec("rapidocr") is not None
            and importlib.util.find_spec("torch") is not None
        )
        cuda_available = dependency_available and self._is_cuda_available()
        artifacts_cached = _artifacts_cached(_ARTIFACTS, self.config.cache_dir)
        ready = dependency_available and cuda_available and not self._closed
        return {
            "provider": "rapidocr",
            "version": _rapidocr_version(),
            "model": "PP-OCRv6-small",
            "engine": "torch",
            "configuredDevice": f"cuda:{self.config.device_index}",
            "effectiveDevice": self._effective_device,
            "available": ready,
            "state": "ready" if ready else ("closed" if self._closed else "unavailable"),
            "modelLoaded": self._engine is not None,
            "artifactsCached": artifacts_cached,
            "downloadOnFirstUse": self.config.allow_download,
            "cpuFallback": False,
            "qualityPromotion": "pending-vietnamese-screen-validation",
            "qualityGatePassed": False,
            "lastErrorCode": self._last_error_code,
            "configured": self.config.public_status(),
        }

    async def recognize(self, encoded_png: bytes) -> dict[str, Any]:
        if not isinstance(encoded_png, bytes) or not encoded_png:
            raise PerceptionError("E_PERCEPTION_OCR_REQUEST", "OCR requires non-empty PNG bytes")
        async with self._operation_lock:
            self._assert_open()
            self._require_cuda()
            started = time.monotonic()
            loop = asyncio.get_running_loop()
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(self._executor, self._recognize_sync, encoded_png),
                    timeout=self.config.request_timeout_seconds,
                )
            except TimeoutError as exc:
                self._last_error_code = "E_PERCEPTION_OCR_TIMEOUT"
                raise PerceptionError(
                    "E_PERCEPTION_OCR_TIMEOUT",
                    "local GPU OCR exceeded its bounded request timeout",
                    retryable=True,
                ) from exc
            except PerceptionError as exc:
                self._last_error_code = exc.code
                raise
            except Exception as exc:
                self._last_error_code = "E_PERCEPTION_OCR_INFERENCE"
                raise PerceptionError(
                    "E_PERCEPTION_OCR_INFERENCE",
                    "local GPU OCR inference failed",
                    retryable=True,
                ) from exc
            result["processingMilliseconds"] = _elapsed_ms(started)
            return result

    async def warmup(self) -> None:
        async with self._operation_lock:
            self._assert_open()
            self._require_cuda()
            try:
                await asyncio.get_running_loop().run_in_executor(
                    self._executor,
                    self._warmup_sync,
                )
            except PerceptionError:
                raise
            except Exception as exc:
                self._last_error_code = "E_PERCEPTION_OCR_INFERENCE"
                raise PerceptionError(
                    "E_PERCEPTION_OCR_INFERENCE",
                    "local GPU OCR warmup failed",
                    retryable=True,
                ) from exc

    async def unload(self) -> None:
        async with self._operation_lock:
            engine = self._engine
            self._engine = None
            self._effective_device = None
            if engine is not None:
                del engine
            _clear_cuda_cache()
            gc.collect()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.unload()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _recognize_sync(self, encoded_png: bytes) -> dict[str, Any]:
        engine = self._engine
        if engine is None:
            self._artifact_ensurer(_ARTIFACTS, self.config)
            engine = self._create_engine()
            self._validate_engine_device(engine)
            self._engine = engine
            self._effective_device = f"cuda:{self.config.device_index}"
        output = engine(encoded_png, use_cls=False)
        result = _serialize_output(
            output,
            max_lines=self.config.max_lines,
            max_characters=self.config.max_text_characters,
            minimum_confidence=self.config.minimum_confidence,
        )
        result["effectiveDevice"] = f"cuda:{self.config.device_index}"
        return result

    def _warmup_sync(self) -> None:
        if self._engine is None:
            self._artifact_ensurer(_ARTIFACTS, self.config)
            engine = self._create_engine()
            self._validate_engine_device(engine)
            self._engine = engine
            self._effective_device = f"cuda:{self.config.device_index}"

    def _create_engine(self) -> Any:
        params = self._engine_params()
        if self._engine_factory is not None:
            return self._engine_factory(params)
        try:
            from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR
        except ImportError as exc:
            raise PerceptionError(
                "E_PERCEPTION_OCR_UNAVAILABLE",
                "RapidOCR dependency is unavailable",
                retryable=True,
            ) from exc
        return RapidOCR(
            params={
                **params,
                "Det.engine_type": EngineType.TORCH,
                "Det.model_type": ModelType.SMALL,
                "Det.ocr_version": OCRVersion.PPOCRV6,
                "Cls.engine_type": EngineType.TORCH,
                "Rec.engine_type": EngineType.TORCH,
                "Rec.model_type": ModelType.SMALL,
                "Rec.ocr_version": OCRVersion.PPOCRV6,
            }
        )

    def _engine_params(self) -> dict[str, Any]:
        cache = self.config.cache_dir
        return {
            "Global.use_cls": False,
            "Global.log_level": "warning",
            "Global.max_side_len": 1280,
            "Det.lang_type": "vi",
            "Det.limit_side_len": 960,
            "Det.model_path": str(cache / "PP-OCRv6_det_small.pth"),
            "Cls.model_path": str(cache / "ch_ptocr_mobile_v2.0_cls_mobile.pth"),
            "Rec.lang_type": "vi",
            "Rec.model_path": str(cache / "PP-OCRv6_rec_small.pth"),
            "Rec.rec_keys_path": str(cache / "ppocrv6_dict.txt"),
            "EngineConfig.torch.use_cuda": True,
            "EngineConfig.torch.cuda_ep_cfg.device_id": self.config.device_index,
        }

    def _validate_engine_device(self, engine: Any) -> None:
        devices: list[str] = []
        for component_name in ("text_det", "text_rec", "text_cls"):
            component = getattr(engine, component_name, None)
            session = getattr(component, "session", None)
            device = getattr(session, "device", None)
            devices.append(str(device))
        expected = f"cuda:{self.config.device_index}"
        if not devices or any(device != expected for device in devices):
            self._last_error_code = "E_PERCEPTION_OCR_CUDA"
            raise PerceptionError(
                "E_PERCEPTION_OCR_CUDA",
                "RapidOCR did not initialize every inference stage on the configured CUDA device",
                retryable=True,
            )

    def _is_cuda_available(self) -> bool:
        if self._cuda_available is not None:
            return bool(self._cuda_available())
        try:
            import torch

            return bool(torch.cuda.is_available())
        except Exception:
            return False

    def _require_cuda(self) -> None:
        if not self._is_cuda_available():
            self._last_error_code = "E_PERCEPTION_OCR_CUDA"
            raise PerceptionError(
                "E_PERCEPTION_OCR_CUDA",
                "CUDA OCR is unavailable; CPU fallback is disabled",
                retryable=True,
            )

    def _assert_open(self) -> None:
        if self._closed:
            raise PerceptionError(
                "E_PERCEPTION_OCR_UNAVAILABLE",
                "OCR provider is closed",
                retryable=True,
            )


class ScheduledOcrProvider:
    """Retain a warm OCR model only while the shared scheduler owns its VRAM."""

    def __init__(self, provider: OcrProvider, lease_factory: OcrGpuLeaseFactory) -> None:
        self.provider = provider
        self.lease_factory = lease_factory
        self._operation_lock = asyncio.Lock()
        self._lease: OcrGpuLease | None = None
        self._closed = False

    async def status(self) -> dict[str, Any]:
        status = dict(await self.provider.status())
        lease = self._lease
        status["resourceLease"] = {
            "required": True,
            "state": lease.state if lease is not None else "released",
        }
        return status

    async def recognize(self, encoded_png: bytes) -> dict[str, Any]:
        async with self._operation_lock:
            self._assert_open()
            lease = await self._ensure_lease_locked()
            lease.assert_active()
            return await self.provider.recognize(encoded_png)

    async def warmup(self) -> None:
        async with self._operation_lock:
            self._assert_open()
            lease = await self._ensure_lease_locked()
            lease.assert_active()
            warmup = getattr(self.provider, "warmup", None)
            if warmup is not None:
                await warmup()

    async def unload(self) -> None:
        async with self._operation_lock:
            await self._unload_locked()

    async def close(self) -> None:
        async with self._operation_lock:
            if self._closed:
                return
            self._closed = True
            await self._unload_locked()
            await self.provider.close()

    async def _ensure_lease_locked(self) -> OcrGpuLease:
        lease = self._lease
        if lease is not None and lease.state == "active":
            try:
                lease.assert_active()
                return lease
            except Exception:
                pass
        if lease is not None:
            self._lease = None
            await self.provider.unload()
            await lease.release()
        try:
            lease = await self.lease_factory(self.unload)
            lease.assert_active()
        except Exception as exc:
            raise PerceptionError(
                "E_PERCEPTION_OCR_RESOURCE_LEASE",
                "GPU OCR resource lease was denied",
                retryable=True,
            ) from exc
        self._lease = lease
        return lease

    async def _unload_locked(self) -> None:
        lease = self._lease
        self._lease = None
        try:
            await self.provider.unload()
        finally:
            if lease is not None:
                await lease.release()

    def _assert_open(self) -> None:
        if self._closed:
            raise PerceptionError(
                "E_PERCEPTION_OCR_UNAVAILABLE",
                "OCR provider is closed",
                retryable=True,
            )


def unconfigured_ocr_status() -> dict[str, Any]:
    return {
        "provider": "none",
        "state": "unconfigured",
        "available": False,
        "automatic": False,
        "cpuFallback": False,
        "qualityPromotion": "not-applicable",
        "qualityGatePassed": False,
        "note": "No reviewed local OCR provider is attached to this runtime instance.",
    }


def _ensure_artifacts(artifacts: tuple[_Artifact, ...], config: OcrConfig) -> None:
    cache_dir = config.cache_dir.resolve()
    try:
        cache_dir.relative_to(config.root.resolve())
    except ValueError as exc:
        raise PerceptionError(
            "E_PERCEPTION_OCR_CONFIG",
            "OCR cache path must remain inside the project root",
        ) from exc
    cache_dir.mkdir(parents=True, exist_ok=True)
    for artifact in artifacts:
        target = cache_dir / artifact.filename
        if _file_matches(target, artifact.sha256):
            continue
        if not config.allow_download:
            raise PerceptionError(
                "E_PERCEPTION_OCR_ARTIFACT",
                "reviewed OCR artifacts are missing or invalid and download is disabled",
                retryable=True,
            )
        temporary = target.with_name(f".{target.name}.partial")
        try:
            digest = hashlib.sha256()
            with urlopen(artifact.url, timeout=_ARTIFACT_DOWNLOAD_TIMEOUT_SECONDS) as response:
                with temporary.open("wb") as handle:
                    while chunk := response.read(1024 * 1024):
                        digest.update(chunk)
                        handle.write(chunk)
            if digest.hexdigest() != artifact.sha256:
                raise PerceptionError(
                    "E_PERCEPTION_OCR_ARTIFACT",
                    "downloaded OCR artifact did not match its reviewed SHA-256",
                )
            os.replace(temporary, target)
        except PerceptionError:
            _remove_partial(temporary)
            raise
        except (OSError, URLError) as exc:
            _remove_partial(temporary)
            raise PerceptionError(
                "E_PERCEPTION_OCR_ARTIFACT",
                "reviewed OCR artifact download failed",
                retryable=True,
            ) from exc


def _serialize_output(
    output: Any,
    *,
    max_lines: int,
    max_characters: int,
    minimum_confidence: float,
) -> dict[str, Any]:
    image = getattr(output, "img", None)
    shape = getattr(image, "shape", None)
    if not shape or len(shape) < 2:
        width = height = 1
    else:
        height, width = max(1, int(shape[0])), max(1, int(shape[1]))
    boxes = _as_sequence(getattr(output, "boxes", None))
    texts = _as_sequence(getattr(output, "txts", None))
    scores = _as_sequence(getattr(output, "scores", None))
    lines: list[dict[str, Any]] = []
    budget = max_characters
    for index, raw_text in enumerate(texts[:max_lines]):
        text = _sanitize_text(raw_text)
        if not text or len(text) > budget:
            if len(text) > budget:
                text = text[:budget].rstrip()
            if not text:
                break
        score = _bounded_score(scores[index] if index < len(scores) else 0.0)
        if score < minimum_confidence:
            continue
        box = boxes[index] if index < len(boxes) else None
        lines.append(
            {
                "text": text,
                "confidence": score,
                "box": _normalized_box(box, width=width, height=height),
            }
        )
        budget -= len(text) + 1
        if budget <= 0:
            break
    full_text = "\n".join(line["text"] for line in lines)
    confidence = round(
        sum(float(line["confidence"]) for line in lines) / len(lines), 4
    ) if lines else None
    return {
        "provider": "rapidocr",
        "model": "PP-OCRv6-small",
        "engine": "torch",
        "effectiveDevice": "cuda",
        "state": "ready" if lines else "no-text",
        "text": full_text or None,
        "lineCount": len(lines),
        "meanConfidence": confidence,
        "lines": lines,
    }


def _as_sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    try:
        return list(value)
    except TypeError:
        return []


def _sanitize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(_CONTROL_CHARS.sub("", value).split())


def _bounded_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(score):
        return 0.0
    return round(min(1.0, max(0.0, score)), 4)


def _normalized_box(value: Any, *, width: int, height: int) -> list[float] | None:
    if value is None:
        return None
    flattened: list[float] = []
    try:
        for point in value:
            if isinstance(point, (str, bytes)):
                return None
            coordinates = list(point)
            if len(coordinates) != 2:
                return None
            flattened.extend((float(coordinates[0]) / width, float(coordinates[1]) / height))
    except (TypeError, ValueError):
        return None
    if len(flattened) != 8 or any(not math.isfinite(item) for item in flattened):
        return None
    return [round(min(1.0, max(0.0, item)), 4) for item in flattened]


def _artifacts_cached(artifacts: tuple[_Artifact, ...], cache_dir: Path) -> bool:
    return all(_file_matches(cache_dir / artifact.filename, artifact.sha256) for artifact in artifacts)


def _file_matches(path: Path, expected_sha256: str) -> bool:
    if not path.is_file():
        return False
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == expected_sha256


def _remove_partial(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def _rapidocr_version() -> str | None:
    try:
        return importlib.metadata.version("rapidocr")
    except importlib.metadata.PackageNotFoundError:
        return None


def _clear_cuda_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        return


def _elapsed_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1_000, 3)
