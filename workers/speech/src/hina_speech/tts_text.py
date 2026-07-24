from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from .errors import TtsError


_URL = re.compile(r"https?://[^\s<>{}\[\]]+", re.IGNORECASE)
_BOUNDARY = re.compile(r"(?<=[.!?…;:])\s+|\n+")
_WHITESPACE = re.compile(r"\s+")
_EMOJI = {
    "❤️": " trái tim ",
    "❤": " trái tim ",
    "😊": " vui vẻ ",
    "😂": " cười ",
    "😢": " buồn ",
    "👍": " đồng ý ",
}


def normalize_tts_text(raw: str, *, max_characters: int = 2_000) -> str:
    if not isinstance(raw, str):
        raise TtsError("E_TTS_TEXT", "TTS text must be a string")
    text = unicodedata.normalize("NFC", raw)
    if any(
        unicodedata.category(char) in {"Cc", "Cf"} and char not in {"\n", "\r", "\t"}
        for char in text
    ):
        raise TtsError("E_TTS_TEXT", "TTS text contains unsupported control characters")
    for symbol, spoken in _EMOJI.items():
        text = text.replace(symbol, spoken)
    text = _URL.sub(_speak_url, text)
    text = _WHITESPACE.sub(" ", text).strip()
    if not text:
        raise TtsError("E_TTS_TEXT", "TTS text is empty")
    if len(text) > max_characters:
        raise TtsError("E_TTS_TEXT_TOO_LARGE", "TTS text exceeds the character limit")
    return text


def split_tts_chunks(text: str, *, max_characters: int = 256) -> tuple[str, ...]:
    if not 32 <= max_characters <= 512:
        raise TtsError("E_TTS_CONFIG", "TTS chunk character limit is invalid")
    units = [item.strip() for item in _BOUNDARY.split(text) if item.strip()]
    chunks: list[str] = []
    current = ""
    for unit in units:
        if len(unit) > max_characters:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long_unit(unit, max_characters))
            continue
        candidate = f"{current} {unit}".strip()
        if current and len(candidate) > max_characters:
            chunks.append(current)
            current = unit
        else:
            current = candidate
    if current:
        chunks.append(current)
    if not chunks:
        raise TtsError("E_TTS_TEXT", "TTS chunking produced no text")
    return tuple(chunks)


def _split_long_unit(unit: str, limit: int) -> list[str]:
    words = unit.split()
    chunks: list[str] = []
    current = ""
    for word in words:
        if len(word) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(word[index : index + limit] for index in range(0, len(word), limit))
            continue
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > limit:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _speak_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    parsed = urlsplit(raw.rstrip(".,!?;:"))
    host = parsed.hostname or "liên kết"
    return f" đường dẫn {host.replace('.', ' chấm ')} "
