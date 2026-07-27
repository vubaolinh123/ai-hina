from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from .config import PerceptionConfig
from .dedup import SnapshotRateLimiter, dhash64, hamming_distance
from .errors import PerceptionError
from .observation import OBSERVATION_KIND, OBSERVATION_TRUST_LEVEL, FreshnessLedger
from .ocr import unconfigured_ocr_status
from .png import summarize_png


_SOURCE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_ALLOWED_SOURCES = frozenset({"owner.console", "owner.dev-console", "owner.desktop"})
_CAPABILITY = "perception.observe"
PerceptionErrorCallback = Callable[[dict[str, str]], None]


class PerceptionService:
    """Owner-consented snapshot ingestion with TTL freshness and fail-closed policy.

    Every snapshot is decoded in memory, reduced to renderer-safe evidence
    (dimensions, mean luminance, perceptual hash, SHA-256) and immediately
    discarded. No pixel data, file or OCR text is retained or persisted in
    M08-S1, and nothing here can start a capture on its own: each call needs an
    explicit owner action plus a live safety-policy decision.
    """

    def __init__(
        self,
        config: PerceptionConfig,
        *,
        safety_evaluate: Callable[[dict[str, Any]], dict[str, Any]],
        on_error: PerceptionErrorCallback | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self._evaluate = safety_evaluate
        self.on_error = on_error
        self._clock = clock or time.monotonic
        self._ledger = FreshnessLedger(
            ttl_seconds=float(config.ttl_seconds),
            capacity=config.max_fresh_observations,
            clock=self._clock,
        )
        self._rate = SnapshotRateLimiter(
            config.rate_limit_per_minute,
            clock=self._clock,
        )
        self._duplicate_total = 0
        self._denied_total = 0
        self._closed = False

    async def status(self) -> dict[str, Any]:
        counts = self._ledger.counts()
        return {
            "schemaVersion": "1.0",
            "available": not self._closed,
            "capture": {
                "mode": "owner-triggered-snapshot",
                "autoCapture": False,
                "defaultEnabled": self.config.capture_default_enabled,
                "transport": "image/png",
                "consent": "explicit owner action per snapshot",
            },
            "configured": self.config.public_status(),
            "observation": {
                "kind": OBSERVATION_KIND,
                "trustLevel": OBSERVATION_TRUST_LEVEL,
                "expiryClock": "monotonic-elapsed",
                "freshCount": counts["fresh"],
                "expiredTotal": counts["expiredTotal"],
                "acceptedTotal": counts["acceptedTotal"],
                "duplicateTotal": self._duplicate_total,
                "deniedTotal": self._denied_total,
            },
            "policy": {
                "capability": _CAPABILITY,
                "featureFlag": "perception",
                "failClosed": True,
            },
            "rate": {
                "limitPerMinute": self.config.rate_limit_per_minute,
                "remainingThisMinute": self._rate.remaining,
            },
            "ocr": unconfigured_ocr_status(),
            "retention": {
                "snapshotPersistence": False,
                "pixelDataRetained": False,
                "rawImageRetained": False,
            },
        }

    async def ingest_snapshot(
        self,
        encoded: bytes,
        *,
        correlation_id: str,
        session_id: str | None,
        source: str,
        label: str | None = None,
        owner_confirmed: bool = False,
    ) -> dict[str, Any]:
        started = time.monotonic()
        _validate_uuid(correlation_id, "correlation ID")
        if session_id is not None:
            _validate_uuid(session_id, "session ID")
        if _SOURCE.fullmatch(source) is None or source not in _ALLOWED_SOURCES:
            raise PerceptionError(
                "E_PERCEPTION_REQUEST",
                "snapshot source must be an owner-controlled surface",
            )
        normalized_label = _sanitize_label(label)
        if self._closed:
            raise PerceptionError(
                "E_PERCEPTION_UNAVAILABLE",
                "perception service is closed",
                retryable=True,
            )

        decision = self._policy_decision(
            correlation_id=correlation_id,
            session_id=session_id,
            source=source,
            owner_confirmed=owner_confirmed,
        )

        try:
            summary = summarize_png(
                encoded,
                max_bytes=self.config.max_snapshot_bytes,
                max_dimension=self.config.max_dimension_px,
                min_dimension=self.config.min_dimension_px,
            )
            snapshot_hash = dhash64(summary)
            for observation_id, existing_hash in self._ledger.latest_hashes():
                distance = hamming_distance(snapshot_hash, existing_hash)
                if distance <= self.config.dedup_hamming_threshold:
                    self._duplicate_total += 1
                    return {
                        "status": "duplicate",
                        "correlationId": correlation_id,
                        "sessionId": session_id,
                        "policy": decision,
                        "dedup": {
                            "matchedObservationId": observation_id,
                            "hammingDistance": distance,
                            "threshold": self.config.dedup_hamming_threshold,
                        },
                        "observation": self._ledger.get_fresh(observation_id),
                        "processingMilliseconds": _elapsed_ms(started),
                    }
            if not self._rate.try_acquire():
                raise PerceptionError(
                    "E_PERCEPTION_RATE_LIMIT",
                    "snapshot rate limit reached; wait before capturing again",
                    retryable=True,
                )
            observation = self._ledger.add(
                str(uuid4()),
                {
                    "source": source,
                    "label": normalized_label,
                    "correlationId": correlation_id,
                    "sessionId": session_id,
                    "confidence": 1.0,
                    "evidence": {
                        "sha256": hashlib.sha256(encoded).hexdigest(),
                        "dhash": f"{snapshot_hash:016x}",
                        "bytes": len(encoded),
                        "width": summary.width,
                        "height": summary.height,
                        "meanLuma": summary.mean_luma,
                    },
                    "ocr": {"state": "unavailable", "provider": "none"},
                },
                snapshot_hash,
            )
            return {
                "status": "observed",
                "correlationId": correlation_id,
                "sessionId": session_id,
                "policy": decision,
                "observation": observation,
                "processingMilliseconds": _elapsed_ms(started),
            }
        except PerceptionError as exc:
            self._report_error(exc, correlation_id, session_id, len(encoded))
            raise
        except Exception as exc:
            wrapped = PerceptionError(
                "E_PERCEPTION_OPERATION",
                "unexpected snapshot processing failure",
                retryable=True,
            )
            self._report_error(wrapped, correlation_id, session_id, len(encoded))
            raise wrapped from exc

    async def observations(self) -> dict[str, Any]:
        fresh = self._ledger.fresh()
        counts = self._ledger.counts()
        return {
            "observations": fresh,
            "count": len(fresh),
            "freshCount": counts["fresh"],
            "expiredTotal": counts["expiredTotal"],
            "ttlSeconds": float(self.config.ttl_seconds),
            "expiryClock": "monotonic-elapsed",
        }

    async def clear(self, *, source: str) -> dict[str, Any]:
        if source not in _ALLOWED_SOURCES:
            raise PerceptionError(
                "E_PERCEPTION_REQUEST",
                "observation clear must come from an owner surface",
            )
        removed = self._ledger.clear()
        return {"status": "cleared", "removed": removed}

    async def close(self) -> None:
        self._closed = True
        self._ledger.clear()

    def _policy_decision(
        self,
        *,
        correlation_id: str,
        session_id: str | None,
        source: str,
        owner_confirmed: bool,
    ) -> dict[str, Any]:
        try:
            decision = self._evaluate(
                {
                    "capability": _CAPABILITY,
                    "actorId": source,
                    "trustLevel": "owner",
                    "correlationId": correlation_id,
                    "sessionId": session_id,
                    "consume": True,
                }
            )
        except Exception as exc:
            self._denied_total += 1
            raise PerceptionError(
                "E_PERCEPTION_POLICY",
                "safety policy evaluation failed; snapshot capture fails closed",
            ) from exc
        if not isinstance(decision, dict) or "decision" not in decision:
            self._denied_total += 1
            raise PerceptionError(
                "E_PERCEPTION_POLICY",
                "safety policy returned an invalid decision; capture fails closed",
            )
        mode = decision.get("decision")
        reason = str(decision.get("reasonCode", "unknown"))
        if mode == "deny":
            self._denied_total += 1
            raise PerceptionError(
                "E_PERCEPTION_DENIED",
                f"snapshot capture denied by safety policy ({reason})",
            )
        if mode == "ask" and not owner_confirmed:
            self._denied_total += 1
            raise PerceptionError(
                "E_PERCEPTION_CONFIRMATION",
                "safety policy requires an explicit owner confirmation for this snapshot",
            )
        if mode not in {"allow", "ask"}:
            self._denied_total += 1
            raise PerceptionError(
                "E_PERCEPTION_POLICY",
                "safety policy returned an unknown decision; capture fails closed",
            )
        return {
            "decision": mode,
            "reasonCode": reason,
            "ownerConfirmed": owner_confirmed,
            "stateRevision": decision.get("stateRevision"),
        }

    def _report_error(
        self,
        error: PerceptionError,
        correlation_id: str,
        session_id: str | None,
        snapshot_bytes: int,
    ) -> None:
        if self.on_error is None:
            return
        try:
            self.on_error(
                {
                    "errorCode": error.code,
                    "correlationId": correlation_id,
                    "sessionId": session_id or "",
                    "snapshotBytes": str(snapshot_bytes),
                }
            )
        except Exception:
            return
        error.reported = True


def _sanitize_label(label: str | None) -> str | None:
    if label is None:
        return None
    if not isinstance(label, str):
        raise PerceptionError("E_PERCEPTION_REQUEST", "snapshot label is invalid")
    cleaned = "".join(
        char for char in label if ord(char) >= 0x20 and ord(char) != 0x7F
    ).strip()
    if not cleaned:
        return None
    return cleaned[:120]


def _validate_uuid(value: str, name: str) -> None:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise PerceptionError("E_PERCEPTION_REQUEST", f"{name} is invalid") from exc
    if str(parsed) != value.lower():
        raise PerceptionError("E_PERCEPTION_REQUEST", f"{name} must use canonical UUID form")


def _elapsed_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1_000, 3)
