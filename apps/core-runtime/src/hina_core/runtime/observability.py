from __future__ import annotations

import contextvars
import json
import math
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Any

from .error_log import redact_for_log
from .primitives import PrimitiveError, RuntimeErrorCode


_METRIC_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SPAN_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_ALLOWED_LABELS = {
    "component",
    "error_code",
    "operation",
    "provider",
    "status",
}
_ALLOWED_TRACE_ATTRIBUTES = {
    "attempt",
    "cache",
    "component",
    "event_type",
    "lease_id",
    "model",
    "provider",
    "resource",
    "sequence",
    "status",
    "stream_id",
}
_CURRENT_SPAN: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "hina_current_span",
    default=None,
)


class MetricKind(StrEnum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass(frozen=True, slots=True)
class MetricPoint:
    name: str
    kind: MetricKind
    labels: tuple[tuple[str, str], ...]
    value: float
    count: int
    total: float
    minimum: float | None
    maximum: float | None


@dataclass(slots=True)
class _MutableMetric:
    kind: MetricKind
    value: float = 0
    count: int = 0
    total: float = 0
    minimum: float | None = None
    maximum: float | None = None


class MetricRegistry:
    def __init__(self, *, max_series: int = 256) -> None:
        if not 1 <= max_series <= 100_000:
            raise ValueError("max_series must be between 1 and 100000")
        self.max_series = max_series
        self._series: dict[tuple[str, tuple[tuple[str, str], ...]], _MutableMetric] = {}
        self._lock = threading.RLock()

    @property
    def series_count(self) -> int:
        with self._lock:
            return len(self._series)

    def increment(
        self,
        name: str,
        amount: float = 1,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        value = self._finite(amount)
        if value < 0:
            raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "counter increment cannot be negative")
        with self._lock:
            metric = self._get_or_create(name, MetricKind.COUNTER, labels)
            metric.value += value
            metric.count += 1
            metric.total += value

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        number = self._finite(value)
        with self._lock:
            metric = self._get_or_create(name, MetricKind.GAUGE, labels)
            metric.value = number
            metric.count += 1
            metric.total += number
            metric.minimum = number if metric.minimum is None else min(metric.minimum, number)
            metric.maximum = number if metric.maximum is None else max(metric.maximum, number)

    def observe(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        number = self._finite(value)
        if number < 0:
            raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "histogram value cannot be negative")
        with self._lock:
            metric = self._get_or_create(name, MetricKind.HISTOGRAM, labels)
            metric.value = number
            metric.count += 1
            metric.total += number
            metric.minimum = number if metric.minimum is None else min(metric.minimum, number)
            metric.maximum = number if metric.maximum is None else max(metric.maximum, number)

    def snapshot(self) -> tuple[MetricPoint, ...]:
        with self._lock:
            return tuple(
                MetricPoint(
                    name=name,
                    kind=metric.kind,
                    labels=labels,
                    value=metric.value,
                    count=metric.count,
                    total=metric.total,
                    minimum=metric.minimum,
                    maximum=metric.maximum,
                )
                for (name, labels), metric in sorted(self._series.items())
            )

    def as_json(self) -> dict[str, Any]:
        return {
            "series": [
                {
                    "name": point.name,
                    "kind": str(point.kind),
                    "labels": dict(point.labels),
                    "value": point.value,
                    "count": point.count,
                    "sum": point.total,
                    "min": point.minimum,
                    "max": point.maximum,
                }
                for point in self.snapshot()
            ],
            "seriesCount": self.series_count,
            "maxSeries": self.max_series,
        }

    def _get_or_create(
        self,
        name: str,
        kind: MetricKind,
        labels: dict[str, str] | None,
    ) -> _MutableMetric:
        normalized_name = self._validate_name(name)
        normalized_labels = self._validate_labels(labels or {})
        key = (normalized_name, normalized_labels)
        metric = self._series.get(key)
        if metric is not None:
            if metric.kind is not kind:
                raise PrimitiveError(
                    RuntimeErrorCode.OBSERVABILITY_INVALID,
                    "metric kind cannot change for an existing series",
                )
            return metric
        if len(self._series) >= self.max_series:
            raise PrimitiveError(RuntimeErrorCode.METRIC_CAPACITY, "metric series capacity reached")
        metric = _MutableMetric(kind)
        self._series[key] = metric
        return metric

    @staticmethod
    def _validate_name(name: str) -> str:
        if _METRIC_NAME.fullmatch(name) is None:
            raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "metric name is invalid")
        return name

    @staticmethod
    def _validate_labels(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
        if len(labels) > 5:
            raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "metric has too many labels")
        normalized: list[tuple[str, str]] = []
        for key, value in labels.items():
            if key not in _ALLOWED_LABELS:
                raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "metric label key is not allowed")
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 64
                or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
            ):
                raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "metric label value is invalid")
            normalized.append((key, value))
        return tuple(sorted(normalized))

    @staticmethod
    def _finite(value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "metric value must be numeric")
        try:
            number = float(value)
        except OverflowError as exc:
            raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "metric value must be finite") from exc
        if not math.isfinite(number):
            raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "metric value must be finite")
        return number


class JsonlTraceWriter:
    def __init__(
        self,
        path: Path,
        *,
        metrics: MetricRegistry | None = None,
        build_commit: str = "development",
        max_attributes: int = 16,
    ) -> None:
        if not 0 <= max_attributes <= 32:
            raise ValueError("max_attributes must be between 0 and 32")
        self.path = path
        self.metrics = metrics
        self.build_commit = build_commit
        self.max_attributes = max_attributes
        self._lock = threading.Lock()

    def span(
        self,
        name: str,
        *,
        correlation_id: str,
        session_id: str | None = None,
        turn_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> TraceSpan:
        if _SPAN_NAME.fullmatch(name) is None:
            raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "span name is invalid")
        validated_correlation = self._validate_identifier(correlation_id, "correlation")
        validated_session = (
            self._validate_identifier(session_id, "session")
            if session_id is not None
            else None
        )
        validated_turn = (
            self._validate_identifier(turn_id, "turn")
            if turn_id is not None
            else None
        )
        validated = self._validate_attributes(attributes or {})
        return TraceSpan(
            self,
            name=name,
            correlation_id=validated_correlation,
            session_id=validated_session,
            turn_id=validated_turn,
            attributes=validated,
        )

    def _validate_attributes(self, attributes: dict[str, Any]) -> dict[str, Any]:
        if len(attributes) > self.max_attributes:
            raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "span has too many attributes")
        result: dict[str, Any] = {}
        for key, value in attributes.items():
            if key not in _ALLOWED_TRACE_ATTRIBUTES:
                raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "span attribute key is not allowed")
            if value is not None and not isinstance(value, (bool, int, float, str)):
                raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "span attribute value is invalid")
            if isinstance(value, str) and len(value) > 128:
                raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "span attribute value is too long")
            if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 9_007_199_254_740_991:
                raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "span integer is outside safe range")
            if isinstance(value, float) and not math.isfinite(value):
                raise PrimitiveError(RuntimeErrorCode.OBSERVABILITY_INVALID, "span number must be finite")
            result[key] = redact_for_log(value, key)
        return result

    @staticmethod
    def _validate_identifier(value: str, field: str) -> str:
        try:
            normalized = str(uuid.UUID(value))
        except (AttributeError, TypeError, ValueError):
            raise PrimitiveError(
                RuntimeErrorCode.OBSERVABILITY_INVALID,
                f"{field} identifier is invalid",
            )
        return normalized

    def _write(self, record: dict[str, Any]) -> None:
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded + "\n")


class TraceSpan:
    def __init__(
        self,
        writer: JsonlTraceWriter,
        *,
        name: str,
        correlation_id: str,
        session_id: str | None,
        turn_id: str | None,
        attributes: dict[str, Any],
    ) -> None:
        self.writer = writer
        self.name = name
        self.correlation_id = correlation_id
        self.session_id = session_id
        self.turn_id = turn_id
        self.attributes = attributes
        self.span_id = uuid.uuid4().hex
        self.parent_span_id = _CURRENT_SPAN.get()
        self._token: contextvars.Token[str | None] | None = None
        self._started_monotonic = 0.0
        self._started_at = ""

    def __enter__(self) -> TraceSpan:
        self._started_monotonic = time.monotonic()
        self._started_at = datetime.now(UTC).isoformat()
        self._token = _CURRENT_SPAN.set(self.span_id)
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        duration_ms = max(0.0, (time.monotonic() - self._started_monotonic) * 1000)
        status = "error" if exception_type is not None else "ok"
        record: dict[str, Any] = {
            "timestamp": self._started_at,
            "name": self.name,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id,
            "correlationId": self.correlation_id,
            "sessionId": self.session_id,
            "turnId": self.turn_id,
            "durationMs": round(duration_ms, 3),
            "status": status,
            "buildCommit": self.writer.build_commit,
            "attributes": self.attributes,
        }
        if exception_type is not None:
            record["exceptionType"] = exception_type.__name__
        try:
            self.writer._write(record)
            if self.writer.metrics is not None:
                labels = {"operation": self.name, "status": status}
                self.writer.metrics.increment("hina_span_total", labels=labels)
                self.writer.metrics.observe("hina_span_duration_ms", duration_ms, labels=labels)
        except Exception:
            pass
        finally:
            if self._token is not None:
                _CURRENT_SPAN.reset(self._token)
        return False
