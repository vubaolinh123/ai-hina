from __future__ import annotations

import asyncio
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from .errors import TtsError
from .tts_audio import pcm16_to_wav
from .tts_config import TtsConfig
from .tts_provider import TtsProvider
from .tts_text import normalize_tts_text, split_tts_chunks


_SOURCE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
TtsModerator = Callable[[dict[str, Any]], dict[str, Any]]
TtsErrorCallback = Callable[[dict[str, str]], None]


class SpeechOutputService:
    def __init__(
        self,
        config: TtsConfig,
        provider: TtsProvider,
        *,
        moderator: TtsModerator,
        on_error: TtsErrorCallback | None = None,
    ) -> None:
        self.config = config
        self.provider = provider
        self.moderator = moderator
        self.on_error = on_error
        self._admission_lock = asyncio.Lock()
        self._pending = 0
        self._active: dict[str, threading.Event] = {}

    async def status(self) -> dict[str, object]:
        provider = await self.provider.status()
        return {
            "configured": self.config.public_status(),
            "provider": provider,
            "available": bool(provider.get("available")),
            "queue": {
                "pending": self._pending,
                "capacity": self.config.max_pending_syntheses,
                "activeUtterances": len(self._active),
            },
            "output": {
                "transport": "audio/wav",
                "sampleRateHz": 48_000,
                "channels": 1,
                "sampleWidthBits": 16,
                "progressiveHttpStreaming": False,
                "alignment": "estimated_chunk_boundaries",
            },
            "retention": {
                "generatedAudio": False,
                "inputText": False,
                "voiceCloning": False,
            },
        }

    async def synthesize(
        self,
        raw_text: str,
        *,
        utterance_id: str,
        correlation_id: str,
        session_id: str | None,
        source: str,
    ) -> dict[str, Any]:
        _validate_uuid(utterance_id, "utterance ID")
        _validate_uuid(correlation_id, "correlation ID")
        if session_id is not None:
            _validate_uuid(session_id, "session ID")
        if _SOURCE.fullmatch(source) is None:
            raise TtsError("E_TTS_REQUEST", "TTS source is invalid")

        normalized = normalize_tts_text(
            raw_text,
            max_characters=self.config.max_text_characters,
        )
        moderation = self.moderator(
            {
                "surface": "pre_tts",
                "source": source,
                "text": normalized,
                "actorId": source,
                "correlationId": correlation_id,
                "sessionId": session_id,
                "toolProposal": None,
            }
        )
        if moderation.get("decision") != "allow":
            raise TtsError(
                "E_TTS_BLOCKED",
                f"pre-TTS moderation blocked the utterance: {moderation.get('reasonCode', 'blocked')}",
            )
        moderated_text = moderation.get("sanitizedText")
        if not isinstance(moderated_text, str) or not moderated_text.strip():
            raise TtsError("E_TTS_BLOCKED", "pre-TTS moderation returned no speakable text")
        moderated_text = normalize_tts_text(
            moderated_text,
            max_characters=self.config.max_text_characters,
        )
        chunks = split_tts_chunks(
            moderated_text,
            max_characters=self.config.max_chunk_characters,
        )

        admitted = False
        cancel_event = threading.Event()
        async with self._admission_lock:
            if utterance_id in self._active:
                raise TtsError("E_TTS_CONFLICT", "TTS utterance ID is already active")
            if self._pending >= self.config.max_pending_syntheses:
                raise TtsError("E_TTS_QUEUE_FULL", "TTS synthesis queue is full", retryable=True)
            self._pending += 1
            self._active[utterance_id] = cancel_event
            admitted = True

        started = time.monotonic()
        try:
            synthesis = await self.provider.synthesize(chunks, cancel_event)
            wav = pcm16_to_wav(synthesis.pcm16, sample_rate_hz=synthesis.sample_rate_hz)
            return {
                "status": "synthesized",
                "utteranceId": utterance_id,
                "correlationId": correlation_id,
                "sessionId": session_id,
                "source": source,
                "voice": synthesis.voice,
                "sampleRateHz": synthesis.sample_rate_hz,
                "durationSeconds": round(synthesis.duration_seconds, 3),
                "firstChunkMilliseconds": synthesis.first_chunk_milliseconds,
                "processingMilliseconds": synthesis.processing_milliseconds,
                "totalMilliseconds": round((time.monotonic() - started) * 1_000, 3),
                "audioBytes": len(wav),
                "audioWav": wav,
                "events": _events_for_synthesis(
                    utterance_id,
                    correlation_id,
                    session_id,
                    synthesis.chunks,
                ),
                "retention": {
                    "generatedAudio": False,
                    "inputText": False,
                },
            }
        except TtsError as exc:
            self._report_error(
                exc,
                utterance_id=utterance_id,
                correlation_id=correlation_id,
                session_id=session_id,
            )
            raise
        except Exception as exc:
            wrapped = TtsError(
                "E_TTS_OPERATION",
                "unexpected TTS operation failure",
                retryable=True,
            )
            self._report_error(
                wrapped,
                utterance_id=utterance_id,
                correlation_id=correlation_id,
                session_id=session_id,
            )
            raise wrapped from exc
        finally:
            if admitted:
                async with self._admission_lock:
                    self._active.pop(utterance_id, None)
                    self._pending -= 1

    async def cancel(self, utterance_id: str) -> dict[str, Any]:
        _validate_uuid(utterance_id, "utterance ID")
        async with self._admission_lock:
            event = self._active.get(utterance_id)
            if event is not None:
                event.set()
        return {
            "utteranceId": utterance_id,
            "cancelled": event is not None,
        }

    async def close(self) -> None:
        async with self._admission_lock:
            events = tuple(self._active.values())
        for event in events:
            event.set()
        await self.provider.close()

    def _report_error(
        self,
        error: TtsError,
        *,
        utterance_id: str,
        correlation_id: str,
        session_id: str | None,
    ) -> None:
        if self.on_error is None:
            return
        try:
            self.on_error(
                {
                    "errorCode": error.code,
                    "utteranceId": utterance_id,
                    "correlationId": correlation_id,
                    "sessionId": session_id or "",
                }
            )
        except Exception:
            return
        error.reported = True


def _events_for_synthesis(
    utterance_id: str,
    correlation_id: str,
    session_id: str | None,
    chunks: tuple[Any, ...],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        events.append(
            _event(
                "TtsChunk",
                len(events),
                utterance_id,
                correlation_id,
                session_id,
                {
                    "chunkIndex": index,
                    "startSeconds": round(chunk.start_seconds, 3),
                    "endSeconds": round(chunk.end_seconds, 3),
                    "textCharacters": len(chunk.text),
                },
            )
        )
        events.append(
            _event(
                "AudioAlignment",
                len(events),
                utterance_id,
                correlation_id,
                session_id,
                {
                    "chunkIndex": index,
                    "startSeconds": round(chunk.start_seconds, 3),
                    "endSeconds": round(chunk.end_seconds, 3),
                    "accuracy": "estimated_chunk_boundary",
                },
            )
        )
    events.append(
        _event(
            "TtsCompleted",
            len(events),
            utterance_id,
            correlation_id,
            session_id,
            {"chunkCount": len(chunks)},
        )
    )
    return events


def _event(
    event_type: str,
    sequence: int,
    utterance_id: str,
    correlation_id: str,
    session_id: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": event_type,
        "sequence": sequence,
        "utteranceId": utterance_id,
        "correlationId": correlation_id,
        "sessionId": session_id,
        "occurredAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": payload,
    }


def _validate_uuid(value: str, label: str) -> None:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise TtsError("E_TTS_REQUEST", f"{label} is invalid") from exc
    if str(parsed) != value.lower():
        raise TtsError("E_TTS_REQUEST", f"{label} must use canonical UUID form")
