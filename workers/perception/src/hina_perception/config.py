from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from .errors import PerceptionError


# The master plan freezes the default screen observation TTL at 15 seconds and
# requires every observation type to carry an exact maximum TTL in its schema.
SCREEN_SNAPSHOT_MAX_TTL_SECONDS = 15.0


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
                "snapshot persistence is unavailable in M08-S1",
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> PerceptionConfig:
        values = env if env is not None else os.environ
        return cls(
            ttl_seconds=_env_float(values, "HINA_PERCEPTION_TTL_SECONDS", SCREEN_SNAPSHOT_MAX_TTL_SECONDS),
            max_snapshot_bytes=_env_int(values, "HINA_PERCEPTION_MAX_SNAPSHOT_BYTES", 1_000_000),
            max_dimension_px=_env_int(values, "HINA_PERCEPTION_MAX_DIMENSION_PX", 4_096),
            min_dimension_px=_env_int(values, "HINA_PERCEPTION_MIN_DIMENSION_PX", 16),
            max_fresh_observations=_env_int(values, "HINA_PERCEPTION_MAX_FRESH", 16),
            rate_limit_per_minute=_env_int(values, "HINA_PERCEPTION_RATE_PER_MINUTE", 12),
            dedup_hamming_threshold=_env_int(values, "HINA_PERCEPTION_DEDUP_THRESHOLD", 4),
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
