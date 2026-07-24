from __future__ import annotations

import math
from dataclasses import dataclass

from .model import NormalizedAudio, VadResult


@dataclass(frozen=True, slots=True)
class EnergyVadConfig:
    frame_duration_ms: int = 30
    rms_threshold: float = 0.008
    min_speech_duration_ms: int = 120

    def __post_init__(self) -> None:
        if self.frame_duration_ms not in {10, 20, 30}:
            raise ValueError("VAD frame duration must be 10, 20 or 30 milliseconds")
        if not 0 < self.rms_threshold < 1:
            raise ValueError("VAD RMS threshold is invalid")
        if not self.frame_duration_ms <= self.min_speech_duration_ms <= 5_000:
            raise ValueError("VAD minimum speech duration is invalid")


class EnergyVad:
    """Deterministic first-pass silence gate before the model's Silero VAD."""

    def __init__(self, config: EnergyVadConfig | None = None) -> None:
        self.config = config or EnergyVadConfig()

    def analyze(self, audio: NormalizedAudio) -> VadResult:
        samples = audio.samples
        frame_samples = audio.sample_rate_hz * self.config.frame_duration_ms // 1_000
        required_frames = math.ceil(
            self.config.min_speech_duration_ms / self.config.frame_duration_ms
        )
        frame_rms: list[float] = []
        for offset in range(0, len(samples), frame_samples):
            frame = samples[offset : offset + frame_samples]
            if len(frame) < frame_samples // 2:
                continue
            frame_rms.append(math.sqrt(sum(value * value for value in frame) / len(frame)))

        longest_start = -1
        longest_length = 0
        current_start = 0
        current_length = 0
        voiced_frames = 0
        for index, value in enumerate(frame_rms):
            if value >= self.config.rms_threshold:
                voiced_frames += 1
                if current_length == 0:
                    current_start = index
                current_length += 1
                if current_length > longest_length:
                    longest_start = current_start
                    longest_length = current_length
            else:
                current_length = 0

        total_rms = math.sqrt(
            sum(value * value for value in samples) / max(1, len(samples))
        )
        peak = max((abs(value) for value in samples), default=0.0)
        detected = longest_length >= required_frames
        start_seconds = (
            longest_start * self.config.frame_duration_ms / 1_000 if detected else None
        )
        end_seconds = (
            min(
                audio.duration_seconds,
                (longest_start + longest_length)
                * self.config.frame_duration_ms
                / 1_000,
            )
            if detected
            else None
        )
        return VadResult(
            speech_detected=detected,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            rms=total_rms,
            peak=peak,
            voiced_ratio=voiced_frames / max(1, len(frame_rms)),
        )
