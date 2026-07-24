from __future__ import annotations

from array import array
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NormalizedAudio:
    samples: array[float]
    sample_rate_hz: int
    source_sample_rate_hz: int
    source_channels: int
    source_sample_width_bytes: int
    clipped_fraction: float

    @property
    def duration_seconds(self) -> float:
        return len(self.samples) / self.sample_rate_hz

    @property
    def peak(self) -> float:
        return max((abs(value) for value in self.samples), default=0.0)


@dataclass(frozen=True, slots=True)
class VadResult:
    speech_detected: bool
    start_seconds: float | None
    end_seconds: float | None
    rms: float
    peak: float
    voiced_ratio: float


@dataclass(frozen=True, slots=True)
class SttSegment:
    start_seconds: float
    end_seconds: float
    text: str
    confidence: float


@dataclass(frozen=True, slots=True)
class SttResult:
    text: str
    language: str
    language_probability: float
    duration_seconds: float
    segments: tuple[SttSegment, ...]
