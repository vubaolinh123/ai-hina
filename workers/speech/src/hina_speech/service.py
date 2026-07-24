from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from .audio import decode_and_normalize_wav
from .config import SpeechConfig
from .errors import SpeechError
from .model import SttResult
from .provider import SttProvider
from .vad import EnergyVad


_SOURCE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
SpeechErrorCallback = Callable[[dict[str, str]], None]


class SpeechInputService:
    def __init__(
        self,
        config: SpeechConfig,
        provider: SttProvider,
        *,
        vad: EnergyVad | None = None,
        on_error: SpeechErrorCallback | None = None,
    ) -> None:
        self.config = config
        self.provider = provider
        self.vad = vad or EnergyVad()
        self.on_error = on_error
        self._inference = asyncio.Semaphore(1)
        self._admission_lock = asyncio.Lock()
        self._pending = 0

    async def status(self) -> dict[str, object]:
        provider = await self.provider.status()
        return {
            "configured": self.config.public_status(),
            "provider": provider,
            "available": bool(provider.get("available")),
            "capture": {
                "transport": "audio/wav",
                "browserMicrophone": True,
                "nativeDeviceAdapter": "contract-ready",
                "maxAudioBytes": 1_048_576,
                "maxAudioSeconds": 30,
                "targetSampleRateHz": 16_000,
            },
            "vad": {
                "provider": "energy+faster-whisper-silero",
                "silenceGate": True,
            },
            "queue": {
                "pending": self._pending,
                "capacity": self.config.max_pending_transcriptions,
            },
            "retention": {
                "rawAudio": False,
                "transcriptPersistence": False,
            },
        }

    async def transcribe_wav(
        self,
        encoded: bytes,
        *,
        correlation_id: str,
        session_id: str | None,
        source: str,
    ) -> dict[str, Any]:
        _validate_uuid(correlation_id, "correlation ID")
        if session_id is not None:
            _validate_uuid(session_id, "session ID")
        if _SOURCE.fullmatch(source) is None:
            raise SpeechError("E_STT_REQUEST", "speech source is invalid")

        admitted = False
        async with self._admission_lock:
            if self._pending >= self.config.max_pending_transcriptions:
                raise SpeechError(
                    "E_STT_QUEUE_FULL",
                    "speech transcription queue is full",
                    retryable=True,
                )
            self._pending += 1
            admitted = True
        started = time.monotonic()
        audio = None
        try:
            audio = decode_and_normalize_wav(encoded)
            vad = self.vad.analyze(audio)
            base = {
                "correlationId": correlation_id,
                "sessionId": session_id,
                "source": source,
                "language": "vi",
                "task": "transcribe",
                "speechDetected": vad.speech_detected,
                "audio": {
                    "durationSeconds": round(audio.duration_seconds, 3),
                    "sampleRateHz": audio.sample_rate_hz,
                    "sourceSampleRateHz": audio.source_sample_rate_hz,
                    "sourceChannels": audio.source_channels,
                    "rawAudioRetained": False,
                    "rms": round(vad.rms, 6),
                    "peak": round(vad.peak, 6),
                    "voicedRatio": round(vad.voiced_ratio, 6),
                },
            }
            if not vad.speech_detected:
                return {
                    **base,
                    "status": "silence",
                    "transcript": "",
                    "segments": [],
                    "events": [
                        _event(
                            "TranscriptFinal",
                            0,
                            correlation_id,
                            session_id,
                            {"text": "", "language": "vi", "speechDetected": False},
                        )
                    ],
                    "processingMilliseconds": round(
                        (time.monotonic() - started) * 1_000,
                        3,
                    ),
                }
            async with self._inference:
                result = await self.provider.transcribe(audio)
            return {
                **base,
                "status": "transcribed",
                "transcript": result.text,
                "segments": [
                    {
                        "startSeconds": round(segment.start_seconds, 3),
                        "endSeconds": round(segment.end_seconds, 3),
                        "text": segment.text,
                        "confidence": round(segment.confidence, 6),
                    }
                    for segment in result.segments
                ],
                "events": _events_for_result(
                    result,
                    correlation_id=correlation_id,
                    session_id=session_id,
                    speech_start=vad.start_seconds or 0.0,
                    speech_end=vad.end_seconds or audio.duration_seconds,
                ),
                "processingMilliseconds": round(
                    (time.monotonic() - started) * 1_000,
                    3,
                ),
            }
        except SpeechError as exc:
            self._report_error(
                exc,
                correlation_id=correlation_id,
                session_id=session_id,
                audio_bytes=len(encoded),
                duration_seconds=audio.duration_seconds if audio is not None else None,
            )
            raise
        except Exception as exc:
            wrapped = SpeechError(
                "E_STT_OPERATION",
                "unexpected speech transcription failure",
                retryable=True,
            )
            self._report_error(
                wrapped,
                correlation_id=correlation_id,
                session_id=session_id,
                audio_bytes=len(encoded),
                duration_seconds=audio.duration_seconds if audio is not None else None,
            )
            raise wrapped from exc
        finally:
            if admitted:
                async with self._admission_lock:
                    self._pending -= 1

    async def close(self) -> None:
        close = getattr(self.provider, "close", None)
        if close is not None:
            await close()
        else:
            await self.provider.unload()

    def _report_error(
        self,
        error: SpeechError,
        *,
        correlation_id: str,
        session_id: str | None,
        audio_bytes: int,
        duration_seconds: float | None,
    ) -> None:
        if self.on_error is None:
            return
        try:
            self.on_error(
                {
                    "errorCode": error.code,
                    "correlationId": correlation_id,
                    "sessionId": session_id or "",
                    "audioBytes": str(audio_bytes),
                    "durationMilliseconds": (
                        str(round(duration_seconds * 1_000))
                        if duration_seconds is not None
                        else ""
                    ),
                }
            )
        except Exception:
            return
        error.reported = True


def _events_for_result(
    result: SttResult,
    *,
    correlation_id: str,
    session_id: str | None,
    speech_start: float,
    speech_end: float,
) -> list[dict[str, Any]]:
    events = [
        _event(
            "SpeechStarted",
            0,
            correlation_id,
            session_id,
            {"offsetSeconds": round(speech_start, 3)},
        ),
        _event(
            "SpeechEnded",
            1,
            correlation_id,
            session_id,
            {"offsetSeconds": round(speech_end, 3)},
        ),
    ]
    for segment in result.segments:
        events.append(
            _event(
                "TranscriptPartial",
                len(events),
                correlation_id,
                session_id,
                {
                    "text": segment.text,
                    "language": "vi",
                    "startSeconds": round(segment.start_seconds, 3),
                    "endSeconds": round(segment.end_seconds, 3),
                    "confidence": round(segment.confidence, 6),
                },
            )
        )
    events.append(
        _event(
            "TranscriptFinal",
            len(events),
            correlation_id,
            session_id,
            {
                "text": result.text,
                "language": "vi",
                "speechDetected": True,
                "languageProbability": round(result.language_probability, 6),
            },
        )
    )
    return events


def _event(
    event_type: str,
    sequence: int,
    correlation_id: str,
    session_id: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": event_type,
        "sequence": sequence,
        "correlationId": correlation_id,
        "sessionId": session_id,
        "occurredAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": payload,
    }


def _validate_uuid(value: str, label: str) -> None:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise SpeechError("E_STT_REQUEST", f"{label} is invalid") from exc
    if str(parsed) != value.lower():
        raise SpeechError("E_STT_REQUEST", f"{label} must use canonical UUID form")
