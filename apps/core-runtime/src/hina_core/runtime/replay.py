from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol

from hina_contracts import validate_envelope

from .observability import JsonlTraceWriter, MetricRegistry
from .primitives import (
    IdempotencyRegistry,
    IdempotencySource,
    PrimitiveError,
    RuntimeErrorCode,
)


class ModelProvider(Protocol):
    async def generate(self, prompt: str, *, correlation_id: str) -> str: ...


class SpeechResult(Protocol):
    audio: bytes
    sample_rate_hz: int
    channels: int
    encoding: str


class SpeechProvider(Protocol):
    async def synthesize(self, text: str, *, correlation_id: str) -> SpeechResult: ...


@dataclass(frozen=True, slots=True)
class TurnReplayResult:
    event_id: str
    correlation_id: str
    response_text: str
    audio: bytes
    sample_rate_hz: int
    audio_encoding: str
    source: IdempotencySource


class TurnReplayHarness:
    def __init__(
        self,
        model: ModelProvider,
        speech: SpeechProvider,
        *,
        traces: JsonlTraceWriter | None = None,
        metrics: MetricRegistry | None = None,
        max_events: int = 1_024,
        replay_ttl_seconds: float = 300,
    ) -> None:
        self.model = model
        self.speech = speech
        self.traces = traces
        self.metrics = metrics
        self.max_events = max_events
        self._registry: IdempotencyRegistry[TurnReplayResult] = IdempotencyRegistry(
            max_entries=max_events,
            default_ttl_seconds=replay_ttl_seconds,
        )
        self._fingerprints: OrderedDict[str, str] = OrderedDict()
        self._fingerprint_lock = asyncio.Lock()

    async def replay(self, envelope: Mapping[str, Any]) -> TurnReplayResult:
        validation = validate_envelope(dict(envelope))
        if not validation.ok or validation.canonical_json is None:
            raise PrimitiveError(
                RuntimeErrorCode.EVENT_REJECTED,
                f"replay event validation failed: {validation.code}",
            )
        canonical = validation.canonical_json
        data = json.loads(canonical)
        event_id = data["eventId"]
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        async with self._fingerprint_lock:
            existing = self._fingerprints.get(event_id)
            if existing is not None and existing != fingerprint:
                raise PrimitiveError(
                    RuntimeErrorCode.REPLAY_CONFLICT,
                    "replay eventId was reused with different content",
                )
            if existing is None:
                if len(self._fingerprints) >= self.max_events:
                    self._fingerprints.popitem(last=False)
                self._fingerprints[event_id] = fingerprint
            else:
                self._fingerprints.move_to_end(event_id)

        async def execute() -> TurnReplayResult:
            payload = data.get("payload")
            prompt = payload.get("message") if isinstance(payload, dict) else None
            if not isinstance(prompt, str) or not prompt:
                raise PrimitiveError(RuntimeErrorCode.EVENT_REJECTED, "replay payload has no message")
            trace = (
                self.traces.span(
                    "turn.replay",
                    correlation_id=data["correlationId"],
                    session_id=data.get("sessionId"),
                    turn_id=data.get("turnId"),
                    attributes={
                        "event_type": data["type"],
                        "sequence": data.get("sequence"),
                    },
                )
                if self.traces is not None
                else _NullSpan()
            )
            with trace:
                model_trace = (
                    self.traces.span(
                        "model.generate",
                        correlation_id=data["correlationId"],
                        session_id=data.get("sessionId"),
                        turn_id=data.get("turnId"),
                        attributes={"provider": "fake"},
                    )
                    if self.traces is not None
                    else _NullSpan()
                )
                with model_trace:
                    response_text = await self.model.generate(
                        prompt,
                        correlation_id=data["correlationId"],
                    )
                speech_trace = (
                    self.traces.span(
                        "speech.synthesize",
                        correlation_id=data["correlationId"],
                        session_id=data.get("sessionId"),
                        turn_id=data.get("turnId"),
                        attributes={"provider": "fake"},
                    )
                    if self.traces is not None
                    else _NullSpan()
                )
                with speech_trace:
                    speech = await self.speech.synthesize(
                        response_text,
                        correlation_id=data["correlationId"],
                    )
            return TurnReplayResult(
                event_id=event_id,
                correlation_id=data["correlationId"],
                response_text=response_text,
                audio=speech.audio,
                sample_rate_hz=speech.sample_rate_hz,
                audio_encoding=speech.encoding,
                source=IdempotencySource.EXECUTED,
            )

        result = await self._registry.run_once(event_id, execute)
        if self.metrics is not None:
            self.metrics.increment(
                "hina_replay_total",
                labels={"status": str(result.source)},
            )
        return replace(result.value, source=result.source)


class _NullSpan:
    def __enter__(self) -> _NullSpan:
        return self

    def __exit__(self, *_: object) -> bool:
        return False
