from __future__ import annotations

import io
import math
import sys
import wave
from array import array

from .errors import SpeechError
from .model import NormalizedAudio


TARGET_SAMPLE_RATE_HZ = 16_000
MAX_AUDIO_SECONDS = 30.0
MAX_AUDIO_BYTES = 1_048_576
MAX_CHANNELS = 8
MAX_SOURCE_SAMPLE_RATE_HZ = 192_000
MAX_CLIPPED_FRACTION = 0.05


def decode_and_normalize_wav(
    encoded: bytes,
    *,
    target_sample_rate_hz: int = TARGET_SAMPLE_RATE_HZ,
    max_audio_seconds: float = MAX_AUDIO_SECONDS,
) -> NormalizedAudio:
    if not isinstance(encoded, bytes) or not encoded:
        raise SpeechError("E_AUDIO_EMPTY", "WAV audio body is empty")
    if len(encoded) > MAX_AUDIO_BYTES:
        raise SpeechError("E_AUDIO_TOO_LARGE", "WAV audio exceeds the 1048576 byte limit")
    if not 8_000 <= target_sample_rate_hz <= 48_000:
        raise SpeechError("E_AUDIO_CONFIG", "target sample rate is invalid")
    try:
        with wave.open(io.BytesIO(encoded), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frame_count = handle.getnframes()
            compression = handle.getcomptype()
            if not 1 <= channels <= MAX_CHANNELS:
                raise SpeechError("E_AUDIO_FORMAT", "WAV channel count is unsupported")
            if sample_width not in {1, 2, 3, 4}:
                raise SpeechError("E_AUDIO_FORMAT", "WAV sample width is unsupported")
            if not 8_000 <= sample_rate <= MAX_SOURCE_SAMPLE_RATE_HZ:
                raise SpeechError("E_AUDIO_FORMAT", "WAV sample rate is unsupported")
            if compression != "NONE":
                raise SpeechError("E_AUDIO_FORMAT", "compressed WAV audio is unsupported")
            if frame_count <= 0:
                raise SpeechError("E_AUDIO_EMPTY", "WAV contains no audio frames")
            duration_seconds = frame_count / sample_rate
            if duration_seconds > max_audio_seconds:
                raise SpeechError(
                    "E_AUDIO_TOO_LONG",
                    f"WAV duration exceeds the {max_audio_seconds:g} second limit",
                )
            raw = handle.readframes(frame_count)
    except SpeechError:
        raise
    except (EOFError, wave.Error) as exc:
        raise SpeechError("E_AUDIO_FORMAT", "WAV container is malformed") from exc

    expected_bytes = frame_count * channels * sample_width
    if len(raw) != expected_bytes:
        raise SpeechError("E_AUDIO_FORMAT", "WAV sample payload is truncated")
    interleaved = _decode_pcm(raw, sample_width)
    mono, clipped_fraction = _downmix(interleaved, channels)
    if clipped_fraction > MAX_CLIPPED_FRACTION:
        raise SpeechError("E_AUDIO_CLIPPED", "WAV audio is excessively clipped")
    normalized = (
        mono
        if sample_rate == target_sample_rate_hz
        else _resample_linear(mono, sample_rate, target_sample_rate_hz)
    )
    if not normalized:
        raise SpeechError("E_AUDIO_EMPTY", "WAV normalization produced no samples")
    return NormalizedAudio(
        samples=normalized,
        sample_rate_hz=target_sample_rate_hz,
        source_sample_rate_hz=sample_rate,
        source_channels=channels,
        source_sample_width_bytes=sample_width,
        clipped_fraction=clipped_fraction,
    )


def _decode_pcm(raw: bytes, sample_width: int) -> array[float]:
    values = array("f")
    if sample_width == 1:
        values.extend((value - 128) / 128.0 for value in raw)
        return values
    if sample_width == 2:
        pcm = array("h")
        pcm.frombytes(raw)
        if sys.byteorder != "little":
            pcm.byteswap()
        values.extend(value / 32_768.0 for value in pcm)
        return values
    step = sample_width
    denominator = float(1 << (sample_width * 8 - 1))
    for offset in range(0, len(raw), step):
        value = int.from_bytes(raw[offset : offset + step], "little", signed=True)
        values.append(value / denominator)
    return values


def _downmix(interleaved: array[float], channels: int) -> tuple[array[float], float]:
    mono = array("f")
    clipped = 0
    frame_count = len(interleaved) // channels
    for offset in range(0, len(interleaved), channels):
        frame = interleaved[offset : offset + channels]
        if any(abs(value) >= 0.999 for value in frame):
            clipped += 1
        mono.append(sum(frame) / channels)
    return mono, clipped / max(1, frame_count)


def _resample_linear(
    samples: array[float],
    source_rate_hz: int,
    target_rate_hz: int,
) -> array[float]:
    if len(samples) == 1:
        return array("f", samples)
    target_length = max(1, round(len(samples) * target_rate_hz / source_rate_hz))
    ratio = source_rate_hz / target_rate_hz
    result = array("f")
    last = len(samples) - 1
    for index in range(target_length):
        position = min(last, index * ratio)
        left = int(position)
        right = min(last, left + 1)
        fraction = position - left
        value = samples[left] + (samples[right] - samples[left]) * fraction
        if not math.isfinite(value):
            raise SpeechError("E_AUDIO_FORMAT", "WAV contains a non-finite sample")
        result.append(max(-1.0, min(1.0, value)))
    return result
