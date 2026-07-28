from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import PerceptionError


# The master plan freezes the default screen observation TTL at 15 seconds and
# requires every observation type to carry an exact maximum TTL in its schema.
SCREEN_SNAPSHOT_MAX_TTL_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class OcrConfig:
    """Fixed local OCR profile for explicit M08 owner actions.

    The provider deliberately exposes no CPU fallback.  A missing CUDA runtime
    is an honest unavailable state rather than a silent slower/privacy-different
    execution path.  The model cache contains only reviewed model artifacts;
    screenshots never enter it.
    """

    root: Path
    cache_dir: Path
    device: str = "cuda"
    device_index: int = 0
    model_vram_mib: int = 1_024
    model_ram_mib: int = 1_024
    request_timeout_seconds: float = 90.0
    max_lines: int = 100
    max_text_characters: int = 4_000
    minimum_confidence: float = 0.35
    allow_download: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or not isinstance(self.cache_dir, Path):
            raise PerceptionError("E_PERCEPTION_CONFIG", "OCR paths must be Path values")
        if self.device != "cuda":
            raise PerceptionError(
                "E_PERCEPTION_CONFIG",
                "M08 OCR is CUDA-only and does not support a CPU fallback",
            )
        for value, name, lower, upper in (
            (self.device_index, "OCR CUDA device index", 0, 15),
            (self.model_vram_mib, "OCR VRAM reservation", 256, 8_192),
            (self.model_ram_mib, "OCR RAM reservation", 256, 16_384),
            (self.max_lines, "OCR line limit", 1, 200),
            (self.max_text_characters, "OCR text limit", 128, 8_000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise PerceptionError("E_PERCEPTION_CONFIG", f"perception {name} is invalid")
        if (
            isinstance(self.request_timeout_seconds, bool)
            or not isinstance(self.request_timeout_seconds, (int, float))
            or not 5.0 <= float(self.request_timeout_seconds) <= 300.0
        ):
            raise PerceptionError("E_PERCEPTION_CONFIG", "OCR request timeout is invalid")
        if (
            isinstance(self.minimum_confidence, bool)
            or not isinstance(self.minimum_confidence, (int, float))
            or not 0.0 <= float(self.minimum_confidence) <= 1.0
        ):
            raise PerceptionError("E_PERCEPTION_CONFIG", "OCR confidence threshold is invalid")
        if not isinstance(self.allow_download, bool):
            raise PerceptionError("E_PERCEPTION_CONFIG", "OCR download policy is invalid")

    @classmethod
    def from_env(
        cls,
        *,
        root: Path,
        env: Mapping[str, str] | None = None,
    ) -> OcrConfig:
        values = env if env is not None else os.environ
        fixed_root = root.resolve()
        return cls(
            root=fixed_root,
            # `var/cache` is a legacy user-data junction in some Hina installs.
            # Keep OCR artifacts in a physical repository-local path so the OCR
            # boundary never silently follows that junction outside this project.
            cache_dir=fixed_root / "var" / "models" / "rapidocr-ppocrv6-small",
            device=values.get("HINA_OCR_DEVICE", "cuda").strip().lower(),
            device_index=_env_int(values, "HINA_OCR_DEVICE_INDEX", 0),
            model_vram_mib=_env_int(values, "HINA_OCR_MODEL_VRAM_MIB", 1_024),
            model_ram_mib=_env_int(values, "HINA_OCR_MODEL_RAM_MIB", 1_024),
            request_timeout_seconds=_env_float(values, "HINA_OCR_TIMEOUT_SECONDS", 90.0),
            max_lines=_env_int(values, "HINA_OCR_MAX_LINES", 100),
            max_text_characters=_env_int(values, "HINA_OCR_MAX_TEXT_CHARACTERS", 4_000),
            minimum_confidence=_env_float(values, "HINA_OCR_MIN_CONFIDENCE", 0.35),
            allow_download=_env_bool(values, "HINA_OCR_ALLOW_DOWNLOAD", True),
        )

    def public_status(self) -> dict[str, object]:
        return {
            "device": f"cuda:{self.device_index}",
            "modelVramMiB": self.model_vram_mib,
            "modelRamMiB": self.model_ram_mib,
            "requestTimeoutSeconds": float(self.request_timeout_seconds),
            "maxLines": self.max_lines,
            "maxTextCharacters": self.max_text_characters,
            "minimumConfidence": float(self.minimum_confidence),
            "downloadOnFirstUse": self.allow_download,
            "cpuFallback": False,
        }


@dataclass(frozen=True, slots=True)
class PerceptionConfig:
    ttl_seconds: float = SCREEN_SNAPSHOT_MAX_TTL_SECONDS
    max_snapshot_bytes: int = 1_000_000
    max_dimension_px: int = 4_096
    min_dimension_px: int = 16
    max_fresh_observations: int = 16
    rate_limit_per_minute: int = 12
    dedup_hamming_threshold: int = 4
    capture_default_enabled: bool = False
    snapshot_persistence: bool = False
    archive_root: Path | None = None
    archive_default_enabled: bool = False
    archive_max_session_bytes: int = 268_435_456
    archive_max_snapshots: int = 300

    def __post_init__(self) -> None:
        if (
            isinstance(self.ttl_seconds, bool)
            or not isinstance(self.ttl_seconds, (int, float))
            or not 1.0 <= float(self.ttl_seconds) <= SCREEN_SNAPSHOT_MAX_TTL_SECONDS
        ):
            raise PerceptionError(
                "E_PERCEPTION_CONFIG",
                "screen snapshot TTL must be between 1 and 15 seconds",
            )
        for value, name, lower, upper in (
            (self.max_snapshot_bytes, "snapshot byte limit", 1_024, 1_000_000),
            (self.max_dimension_px, "maximum dimension", 64, 8_192),
            (self.min_dimension_px, "minimum dimension", 9, 256),
            (self.max_fresh_observations, "fresh observation limit", 1, 64),
            (self.rate_limit_per_minute, "rate limit", 1, 60),
            (self.dedup_hamming_threshold, "dedup hamming threshold", 0, 16),
            (
                self.archive_max_session_bytes,
                "archive session byte limit",
                1_000_000,
                2_147_483_648,
            ),
            (self.archive_max_snapshots, "archive snapshot limit", 1, 10_000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise PerceptionError("E_PERCEPTION_CONFIG", f"perception {name} is invalid")
        if self.min_dimension_px >= self.max_dimension_px:
            raise PerceptionError(
                "E_PERCEPTION_CONFIG",
                "perception minimum dimension must be below the maximum",
            )
        if self.capture_default_enabled:
            raise PerceptionError(
                "E_PERCEPTION_CONFIG",
                "automatic capture cannot be enabled by configuration in M08-S1",
            )
        if self.snapshot_persistence:
            raise PerceptionError(
                "E_PERCEPTION_CONFIG",
                "implicit snapshot persistence is unavailable; use an explicit archive session",
            )
        if self.archive_default_enabled:
            raise PerceptionError(
                "E_PERCEPTION_CONFIG",
                "snapshot archive must remain inactive until the owner starts a session",
            )
        if self.archive_root is not None:
            if not isinstance(self.archive_root, Path) or not self.archive_root.is_absolute():
                raise PerceptionError(
                    "E_PERCEPTION_CONFIG",
                    "snapshot archive root must be an absolute Path",
                )

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        root: Path | None = None,
    ) -> PerceptionConfig:
        values = env if env is not None else os.environ
        archive_root = None
        if root is not None:
            fixed_root = root.resolve()
            archive_root = (fixed_root / "var" / "perception-sessions").resolve()
            if not archive_root.is_relative_to(fixed_root):
                raise PerceptionError(
                    "E_PERCEPTION_CONFIG",
                    "snapshot archive root escaped the repository",
                )
        return cls(
            ttl_seconds=_env_float(values, "HINA_PERCEPTION_TTL_SECONDS", SCREEN_SNAPSHOT_MAX_TTL_SECONDS),
            max_snapshot_bytes=_env_int(values, "HINA_PERCEPTION_MAX_SNAPSHOT_BYTES", 1_000_000),
            max_dimension_px=_env_int(values, "HINA_PERCEPTION_MAX_DIMENSION_PX", 4_096),
            min_dimension_px=_env_int(values, "HINA_PERCEPTION_MIN_DIMENSION_PX", 16),
            max_fresh_observations=_env_int(values, "HINA_PERCEPTION_MAX_FRESH", 16),
            rate_limit_per_minute=_env_int(values, "HINA_PERCEPTION_RATE_PER_MINUTE", 12),
            dedup_hamming_threshold=_env_int(values, "HINA_PERCEPTION_DEDUP_THRESHOLD", 4),
            archive_root=archive_root,
            archive_max_session_bytes=_env_int(
                values,
                "HINA_PERCEPTION_ARCHIVE_MAX_SESSION_BYTES",
                268_435_456,
            ),
            archive_max_snapshots=_env_int(
                values,
                "HINA_PERCEPTION_ARCHIVE_MAX_SNAPSHOTS",
                300,
            ),
        )

    def public_status(self) -> dict[str, object]:
        return {
            "ttlSeconds": float(self.ttl_seconds),
            "maxTtlSeconds": SCREEN_SNAPSHOT_MAX_TTL_SECONDS,
            "maxSnapshotBytes": self.max_snapshot_bytes,
            "maxDimensionPx": self.max_dimension_px,
            "minDimensionPx": self.min_dimension_px,
            "maxFreshObservations": self.max_fresh_observations,
            "rateLimitPerMinute": self.rate_limit_per_minute,
            "dedupHammingThreshold": self.dedup_hamming_threshold,
            "captureDefaultEnabled": self.capture_default_enabled,
            "snapshotPersistence": self.snapshot_persistence,
            "archiveAvailable": self.archive_root is not None,
            "archiveDefaultEnabled": self.archive_default_enabled,
            "archiveRoot": str(self.archive_root) if self.archive_root is not None else None,
            "archiveMaxSessionBytes": self.archive_max_session_bytes,
            "archiveMaxSnapshots": self.archive_max_snapshots,
        }


def _env_int(values: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(values.get(name, str(default)))
    except ValueError as exc:
        raise PerceptionError("E_PERCEPTION_CONFIG", f"{name} must be an integer") from exc


def _env_float(values: Mapping[str, str], name: str, default: float) -> float:
    try:
        return float(values.get(name, str(default)))
    except ValueError as exc:
        raise PerceptionError("E_PERCEPTION_CONFIG", f"{name} must be numeric") from exc


def _env_bool(values: Mapping[str, str], name: str, default: bool) -> bool:
    raw = values.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise PerceptionError("E_PERCEPTION_CONFIG", f"{name} must be a boolean")
