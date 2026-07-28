from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from .config import PerceptionConfig
from .dedup import SnapshotRateLimiter, dhash64, hamming_distance
from .errors import PerceptionError
from .observation import OBSERVATION_KIND, OBSERVATION_TRUST_LEVEL, FreshnessLedger
from .ocr import OcrProvider, unconfigured_ocr_status
from .png import summarize_png


_SOURCE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_ALLOWED_SOURCES = frozenset({"owner.console", "owner.dev-console", "owner.desktop"})
_CAPABILITY = "perception.observe"
PerceptionErrorCallback = Callable[[dict[str, str]], None]
VisionAnalyzeCallback = Callable[[bytes, str], Awaitable[str]]
_MAX_VISION_QUESTION_CHARS = 500
_MAX_VISION_SUMMARY_CHARS = 2_000
_VISION_PROMPT = (
    "Bạn là bộ phận thị giác cục bộ của Hina. Hãy mô tả ngắn gọn bằng tiếng Việt "
    "những gì thực sự nhìn thấy trong ảnh. Phân biệt rõ điều chắc chắn và điều "
    "không đọc được; không suy đoán danh tính, dữ liệu ngoài ảnh hay hành động cần "
    "thực thi. Ưu tiên chữ quan trọng, trạng thái giao diện và chi tiết hữu ích."
)


class PerceptionService:
    """Owner-consented snapshot ingestion with TTL freshness and fail-closed policy.

    Every snapshot is decoded in memory, reduced to renderer-safe evidence and
    immediately discarded. M08-S2 can optionally ask the shared local model for
    one bounded untrusted text summary before discarding the bytes. No pixel
    data or file is retained or persisted, and nothing here can start a capture
    on its own: each call needs an explicit owner action plus a live
    safety-policy decision.
    """

    def __init__(
        self,
        config: PerceptionConfig,
        *,
        safety_evaluate: Callable[[dict[str, Any]], dict[str, Any]],
        vision_analyze: VisionAnalyzeCallback | None = None,
        ocr_provider: OcrProvider | None = None,
        on_error: PerceptionErrorCallback | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self._evaluate = safety_evaluate
        self._vision_analyze = vision_analyze
        self._ocr_provider = ocr_provider
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
            "ocr": await self._ocr_status(),
            "vision": {
                "available": self._vision_analyze is not None,
                "state": "ready" if self._vision_analyze is not None else "unavailable",
                "provider": "shared-local-model" if self._vision_analyze is not None else "none",
                "mode": "explicit-owner-request",
                "automatic": False,
                "decisionSupportEligible": False,
                "maxSummaryCharacters": _MAX_VISION_SUMMARY_CHARS,
            },
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
        analyze_with_vlm: bool = False,
        vision_question: str | None = None,
        analyze_with_ocr: bool = False,
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
        if not isinstance(analyze_with_vlm, bool):
            raise PerceptionError(
                "E_PERCEPTION_REQUEST",
                "vision analysis option must be a boolean",
            )
        if not isinstance(analyze_with_ocr, bool):
            raise PerceptionError(
                "E_PERCEPTION_REQUEST",
                "OCR analysis option must be a boolean",
            )
        normalized_question = _sanitize_vision_question(vision_question)
        if normalized_question is not None and not analyze_with_vlm:
            raise PerceptionError(
                "E_PERCEPTION_REQUEST",
                "a vision question requires explicit image analysis",
            )
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
                if (
                    not analyze_with_vlm
                    and not analyze_with_ocr
                    and distance <= self.config.dedup_hamming_threshold
                ):
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
            vision = await self._analyze_vision(
                encoded,
                requested=analyze_with_vlm,
                question=normalized_question,
                correlation_id=correlation_id,
                session_id=session_id,
            )
            ocr = await self._analyze_ocr(
                encoded,
                requested=analyze_with_ocr,
                correlation_id=correlation_id,
                session_id=session_id,
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
                    "ocr": ocr,
                    "vision": vision,
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
        if self._ocr_provider is not None:
            await self._ocr_provider.close()

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

    async def _analyze_vision(
        self,
        encoded: bytes,
        *,
        requested: bool,
        question: str | None,
        correlation_id: str,
        session_id: str | None,
    ) -> dict[str, Any]:
        base = {
            "provider": "shared-local-model",
            "requested": requested,
            "automatic": False,
            "decisionSupportEligible": False,
            "trustLevel": "untrusted",
            "questionProvided": question is not None,
        }
        if not requested:
            return {**base, "state": "not-requested", "summary": None}
        if self._vision_analyze is None:
            return {
                **base,
                "state": "unavailable",
                "summary": None,
                "errorCode": "E_PERCEPTION_VISION_UNAVAILABLE",
            }
        prompt = _VISION_PROMPT
        if question is not None:
            prompt = f"{prompt}\nCâu hỏi của chủ máy: {question}"
        try:
            result = await self._vision_analyze(encoded, prompt)
            summary = _sanitize_vision_summary(result)
            return {**base, "state": "ready", "summary": summary}
        except Exception as exc:
            model_code = getattr(exc, "code", "E_MODEL_UNAVAILABLE")
            if not isinstance(model_code, str) or not model_code.startswith("E_MODEL_"):
                model_code = "E_MODEL_UNAVAILABLE"
            error = PerceptionError(
                "E_PERCEPTION_VISION",
                "local image analysis failed; base snapshot evidence was preserved",
                retryable=True,
            )
            self._report_error(error, correlation_id, session_id, len(encoded))
            return {
                **base,
                "state": "error",
                "summary": None,
                "errorCode": "E_PERCEPTION_VISION",
                "modelErrorCode": model_code,
            }

    async def _ocr_status(self) -> dict[str, Any]:
        if self._ocr_provider is None:
            return unconfigured_ocr_status()
        try:
            status = await self._ocr_provider.status()
        except Exception:
            return {
                "provider": "unknown",
                "state": "error",
                "available": False,
                "automatic": False,
                "cpuFallback": False,
                "lastErrorCode": "E_PERCEPTION_OCR_STATUS",
            }
        if not isinstance(status, dict):
            return {
                "provider": "unknown",
                "state": "error",
                "available": False,
                "automatic": False,
                "cpuFallback": False,
                "lastErrorCode": "E_PERCEPTION_OCR_STATUS",
            }
        return status

    async def _analyze_ocr(
        self,
        encoded: bytes,
        *,
        requested: bool,
        correlation_id: str,
        session_id: str | None,
    ) -> dict[str, Any]:
        base = {
            "provider": "rapidocr" if self._ocr_provider is not None else "none",
            "requested": requested,
            "automatic": False,
            "decisionSupportEligible": False,
            "trustLevel": "untrusted",
        }
        if not requested:
            return {
                **base,
                "state": "not-requested",
                "text": None,
                "lineCount": 0,
                "meanConfidence": None,
                "lines": [],
            }
        if self._ocr_provider is None:
            return {
                **base,
                "state": "unavailable",
                "text": None,
                "lineCount": 0,
                "meanConfidence": None,
                "lines": [],
                "errorCode": "E_PERCEPTION_OCR_UNAVAILABLE",
            }
        try:
            result = await self._ocr_provider.recognize(encoded)
            if not isinstance(result, dict):
                raise PerceptionError(
                    "E_PERCEPTION_OCR",
                    "local OCR provider returned an invalid result",
                )
            safe = _sanitize_ocr_result(result)
            return {**safe, **base}
        except Exception as exc:
            provider_code = getattr(exc, "code", "E_PERCEPTION_OCR_INFERENCE")
            if not isinstance(provider_code, str) or not provider_code.startswith("E_PERCEPTION_OCR"):
                provider_code = "E_PERCEPTION_OCR_INFERENCE"
            error = PerceptionError(
                "E_PERCEPTION_OCR",
                "local GPU OCR failed; base snapshot evidence was preserved",
                retryable=True,
            )
            self._report_error(error, correlation_id, session_id, len(encoded))
            return {
                **base,
                "state": "error",
                "text": None,
                "lineCount": 0,
                "meanConfidence": None,
                "lines": [],
                "errorCode": "E_PERCEPTION_OCR",
                "providerErrorCode": provider_code,
            }


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


def _sanitize_vision_question(question: str | None) -> str | None:
    if question is None:
        return None
    if not isinstance(question, str):
        raise PerceptionError("E_PERCEPTION_REQUEST", "vision question is invalid")
    cleaned = " ".join(
        "".join(
            char for char in question if ord(char) >= 0x20 and ord(char) != 0x7F
        ).split()
    )
    if not cleaned:
        return None
    if len(cleaned) > _MAX_VISION_QUESTION_CHARS:
        raise PerceptionError(
            "E_PERCEPTION_REQUEST",
            "vision question exceeds 500 characters",
        )
    return cleaned


def _sanitize_vision_summary(summary: str) -> str:
    if not isinstance(summary, str):
        raise PerceptionError(
            "E_PERCEPTION_VISION",
            "local image analysis returned invalid text",
        )
    cleaned = "\n".join(
        line.strip()
        for line in "".join(
            char
            for char in summary
            if ord(char) >= 0x20 or char in {"\n", "\t"}
        ).splitlines()
        if line.strip()
    ).strip()
    if not cleaned:
        raise PerceptionError(
            "E_PERCEPTION_VISION",
            "local image analysis returned no text",
            retryable=True,
        )
    return cleaned[:_MAX_VISION_SUMMARY_CHARS]


def _sanitize_ocr_result(result: dict[str, Any]) -> dict[str, Any]:
    """Defensively constrain an adapter result before it enters the TTL ledger.

    The provider already normalizes this data, but the service owns the
    persistence boundary.  In particular, no adapter can smuggle a raw image,
    crop or arbitrary nested object into an observation by returning extras.
    """

    state = result.get("state")
    if state not in {"ready", "no-text"}:
        raise PerceptionError("E_PERCEPTION_OCR", "local OCR returned an invalid state")
    lines_raw = result.get("lines", [])
    if not isinstance(lines_raw, list):
        raise PerceptionError("E_PERCEPTION_OCR", "local OCR returned invalid lines")
    lines: list[dict[str, Any]] = []
    character_budget = 4_000
    for raw_line in lines_raw[:100]:
        if not isinstance(raw_line, dict):
            continue
        text = raw_line.get("text")
        if not isinstance(text, str):
            continue
        cleaned = " ".join(
            "".join(
                char for char in text if ord(char) >= 0x20 and ord(char) != 0x7F
            ).split()
        )
        if not cleaned:
            continue
        cleaned = cleaned[:character_budget].rstrip()
        if not cleaned:
            break
        confidence = _sanitize_ocr_confidence(raw_line.get("confidence"))
        if confidence is None:
            continue
        lines.append(
            {
                "text": cleaned,
                "confidence": confidence,
                "box": _sanitize_ocr_box(raw_line.get("box")),
            }
        )
        character_budget -= len(cleaned) + 1
        if character_budget <= 0:
            break
    text = "\n".join(line["text"] for line in lines)
    if state == "ready" and not text:
        state = "no-text"
    mean_confidence = (
        round(sum(float(line["confidence"]) for line in lines) / len(lines), 4)
        if lines
        else None
    )
    provider = result.get("provider")
    model = result.get("model")
    engine = result.get("engine")
    device = result.get("effectiveDevice")
    output: dict[str, Any] = {
        "provider": provider[:64] if isinstance(provider, str) else "rapidocr",
        "model": model[:128] if isinstance(model, str) else "unknown",
        "engine": engine[:64] if isinstance(engine, str) else "unknown",
        "effectiveDevice": device[:64] if isinstance(device, str) else None,
        "state": state,
        "text": text or None,
        "lineCount": len(lines),
        "meanConfidence": mean_confidence,
        "lines": lines,
    }
    milliseconds = result.get("processingMilliseconds")
    if isinstance(milliseconds, (int, float)) and not isinstance(milliseconds, bool):
        output["processingMilliseconds"] = round(max(0.0, min(float(milliseconds), 300_000.0)), 3)
    return output


def _sanitize_ocr_confidence(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not 0.0 <= float(value) <= 1.0:
        return None
    return round(float(value), 4)


def _sanitize_ocr_box(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 8:
        return None
    normalized: list[float] = []
    for coordinate in value:
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
            return None
        if not 0.0 <= float(coordinate) <= 1.0:
            return None
        normalized.append(round(float(coordinate), 4))
    return normalized


def _validate_uuid(value: str, name: str) -> None:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise PerceptionError("E_PERCEPTION_REQUEST", f"{name} is invalid") from exc
    if str(parsed) != value.lower():
        raise PerceptionError("E_PERCEPTION_REQUEST", f"{name} must use canonical UUID form")


def _elapsed_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1_000, 3)
