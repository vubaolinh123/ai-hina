from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from .errors import SpeechError


class CaptureState(StrEnum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    CAPTURING = "capturing"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AudioDevice:
    device_id: str
    label: str
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class CaptureBufferMetrics:
    queued_frames: int
    accepted_frames: int
    dropped_frames: int


class BoundedCaptureBuffer:
    """Latest-audio buffer used by native/browser capture adapters."""

    def __init__(self, capacity_frames: int = 64) -> None:
        if not 2 <= capacity_frames <= 4_096:
            raise ValueError("capture buffer capacity is invalid")
        self.capacity_frames = capacity_frames
        self._frames: deque[bytes] = deque()
        self._accepted = 0
        self._dropped = 0

    def put(self, frame: bytes) -> bytes | None:
        if not isinstance(frame, bytes) or not frame:
            raise SpeechError("E_AUDIO_FRAME", "audio frame must contain bytes")
        dropped = self._frames.popleft() if len(self._frames) >= self.capacity_frames else None
        if dropped is not None:
            self._dropped += 1
        self._frames.append(frame)
        self._accepted += 1
        return dropped

    def get(self) -> bytes | None:
        return self._frames.popleft() if self._frames else None

    def clear(self) -> None:
        self._frames.clear()

    @property
    def metrics(self) -> CaptureBufferMetrics:
        return CaptureBufferMetrics(
            queued_frames=len(self._frames),
            accepted_frames=self._accepted,
            dropped_frames=self._dropped,
        )
