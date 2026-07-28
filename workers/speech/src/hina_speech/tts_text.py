from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from .errors import TtsError


_URL = re.compile(r"https?://[^\s<>{}\[\]]+", re.IGNORECASE)
_BOUNDARY = re.compile(r"(?<=[.!?…;:])\s+|\n+")
_SOFT_BOUNDARY = re.compile(r"(?<=[,，—–])\s+")
_WHITESPACE = re.compile(r"\s+")
_EXPRESSIVE_CUE = re.compile(r"\[([^\[\]]{1,48})\]", re.IGNORECASE)
_PARENTHETICAL_ASIDE = re.compile(r"\s*\(([^()\r\n]{1,300})\)")
_DASH_BOUNDARY = re.compile(r"\s*[—–]\s*")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([,.;:!?])")
_CUE_ALIASES = {
    "chuckle": "chuckle",
    "chuckles": "chuckle",
    "laugh": "chuckle",
    "laughs": "chuckle",
    "cười": "chuckle",
    "sigh": "sigh",
    "sighs": "sigh",
    "thở dài": "sigh",
    "take a deep breath": "sigh",
    "takes a deep breath": "sigh",
    "inhale": "sigh",
    "exhale": "sigh",
    "clear throat": "clear throat",
    "clears throat": "clear throat",
    "hắng giọng": "clear throat",
}
_EMOJI = {
    "❤️": " trái tim ",
    "❤": " trái tim ",
    "😊": " vui vẻ ",
    "😂": " [chuckle] ",
    "😢": " buồn ",
    "👍": " đồng ý ",
    "🖊️": " ",
    "🖊": " ",
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
    text = _EXPRESSIVE_CUE.sub(_normalize_expressive_cue, text)
    text = _PARENTHETICAL_ASIDE.sub(_normalize_parenthetical_aside, text)
    text = _URL.sub(_speak_url, text)
    # A long dash is visually convenient but makes local voices concatenate
    # clauses unpredictably. Turn it into a sentence pause before chunking.
    text = _DASH_BOUNDARY.sub(". ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    text = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", text)
    if not text:
        raise TtsError("E_TTS_TEXT", "TTS text is empty")
    if len(text) > max_characters:
        raise TtsError("E_TTS_TEXT_TOO_LARGE", "TTS text exceeds the character limit")
    return text


def adaptive_speaking_rate(text: str) -> float:
    speakable_characters = len(_EXPRESSIVE_CUE.sub("", text).strip())
    if speakable_characters <= 120:
        return 1.0
    if speakable_characters <= 320:
        return round(1.0 + (speakable_characters - 120) * 0.0004, 3)
    return round(min(1.18, 1.08 + (speakable_characters - 320) * 0.0002), 3)


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
    clauses = [item.strip() for item in _SOFT_BOUNDARY.split(unit) if item.strip()]
    if len(clauses) > 1:
        chunks: list[str] = []
        current = ""
        for clause in clauses:
            if len(clause) > limit:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(_split_words(clause, limit))
                continue
            candidate = f"{current} {clause}".strip()
            if current and len(candidate) > limit:
                chunks.append(current)
                current = clause
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks
    return _split_words(unit, limit)


def _split_words(unit: str, limit: int) -> list[str]:
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


def _normalize_expressive_cue(match: re.Match[str]) -> str:
    cue = _WHITESPACE.sub(" ", match.group(1)).strip().casefold()
    supported = _CUE_ALIASES.get(cue)
    return f" [{supported}] " if supported is not None else " "


def _normalize_parenthetical_aside(match: re.Match[str]) -> str:
    """Keep an aside speakable while making it a clean prosody boundary.

    A parenthetical tail is often where OmniVoice starts rushing when it is
    attached to a long preceding clause. If the preceding text already ends in
    punctuation (or an expressive cue), whitespace is enough because the
    existing boundary splitter will separate it. Otherwise add a full-stop
    boundary; parentheses themselves are decorative and are not sent to TTS.
    """

    aside = _WHITESPACE.sub(" ", match.group(1)).strip()
    if not aside:
        return " "
    prefix = match.string[: match.start()].rstrip()
    if not prefix:
        return f" {aside} "
    cue_at_end = bool(
        re.search(r"\[(?:chuckle|sigh|clear throat)\]\s*$", prefix, re.IGNORECASE)
    )
    separator = " " if cue_at_end or prefix[-1] in ".!?…;:" else ". "
    return f"{separator}{aside} "
