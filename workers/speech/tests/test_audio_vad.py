from __future__ import annotations

import io
import math
import struct
import sys
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SPEECH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SPEECH_ROOT / "src"))

from hina_speech import (  # noqa: E402
    BoundedCaptureBuffer,
    EnergyVad,
    SpeechError,
    decode_and_normalize_wav,
)


def wav_bytes(
    *,
    sample_rate: int = 16_000,
    channels: int = 1,
    duration_seconds: float = 0.3,
    amplitude: float = 0.2,
    frequency: float = 440.0,
) -> bytes:
    frame_count = round(sample_rate * duration_seconds)
    frames = bytearray()
    for index in range(frame_count):
        sample = int(
            max(-1.0, min(1.0, amplitude * math.sin(2 * math.pi * frequency * index / sample_rate)))
            * 32_767
        )
        frames.extend(struct.pack("<h", sample) * channels)
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(frames))
    return output.getvalue()


def clipped_wav_bytes(*, sample_rate: int = 16_000, duration_seconds: float = 0.2) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(
            struct.pack("<h", 32_767) * round(sample_rate * duration_seconds)
        )
    return output.getvalue()


class AudioNormalizationTests(unittest.TestCase):
    def test_stereo_48khz_is_downmixed_and_resampled_to_16khz(self) -> None:
        audio = decode_and_normalize_wav(
            wav_bytes(sample_rate=48_000, channels=2, duration_seconds=0.25)
        )
        self.assertEqual(audio.sample_rate_hz, 16_000)
        self.assertEqual(audio.source_sample_rate_hz, 48_000)
        self.assertEqual(audio.source_channels, 2)
        self.assertEqual(len(audio.samples), 4_000)
        self.assertAlmostEqual(audio.duration_seconds, 0.25, places=3)
        self.assertGreater(audio.peak, 0.15)

    def test_empty_malformed_too_long_and_clipped_audio_fail_closed(self) -> None:
        cases = [
            (b"", "E_AUDIO_EMPTY"),
            (b"not-a-wav", "E_AUDIO_FORMAT"),
            (wav_bytes(duration_seconds=0.2), "E_AUDIO_TOO_LONG"),
            (clipped_wav_bytes(), "E_AUDIO_CLIPPED"),
        ]
        for index, (encoded, expected) in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(SpeechError) as raised:
                    decode_and_normalize_wav(
                        encoded,
                        max_audio_seconds=0.1 if expected == "E_AUDIO_TOO_LONG" else 30,
                    )
                self.assertEqual(raised.exception.code, expected)

    def test_silence_is_rejected_and_sustained_signal_is_admitted(self) -> None:
        silence = decode_and_normalize_wav(wav_bytes(amplitude=0.0))
        speech = decode_and_normalize_wav(wav_bytes(amplitude=0.2))
        vad = EnergyVad()
        self.assertFalse(vad.analyze(silence).speech_detected)
        admitted = vad.analyze(speech)
        self.assertTrue(admitted.speech_detected)
        self.assertIsNotNone(admitted.start_seconds)
        self.assertGreater(admitted.voiced_ratio, 0.8)


class CaptureBufferTests(unittest.TestCase):
    def test_capture_buffer_drops_oldest_frame_under_backpressure(self) -> None:
        buffer = BoundedCaptureBuffer(capacity_frames=2)
        self.assertIsNone(buffer.put(b"one"))
        self.assertIsNone(buffer.put(b"two"))
        self.assertEqual(buffer.put(b"three"), b"one")
        self.assertEqual(buffer.get(), b"two")
        self.assertEqual(buffer.get(), b"three")
        self.assertEqual(buffer.metrics.accepted_frames, 3)
        self.assertEqual(buffer.metrics.dropped_frames, 1)


if __name__ == "__main__":
    unittest.main()
