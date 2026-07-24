from __future__ import annotations

import io
import wave

from .errors import TtsError


def pcm16_to_wav(pcm16: bytes, *, sample_rate_hz: int) -> bytes:
    if not isinstance(pcm16, bytes) or not pcm16:
        raise TtsError("E_TTS_EMPTY_AUDIO", "TTS provider returned no audio")
    if len(pcm16) % 2:
        raise TtsError("E_TTS_AUDIO", "TTS PCM payload is not 16-bit aligned")
    if not 8_000 <= sample_rate_hz <= 96_000:
        raise TtsError("E_TTS_AUDIO", "TTS sample rate is invalid")
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(pcm16)
    return output.getvalue()
