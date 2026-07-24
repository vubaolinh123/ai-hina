from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import TtsError


DEFAULT_TTS_MODEL_ID = "pnnbao-ump/VieNeu-TTS-v3-Turbo"
DEFAULT_TTS_MODEL_REVISION = "75ff82a72f54d55ed389e1eeb12041d3c4bac7d4"
DEFAULT_TTS_CODEC_ID = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX"
DEFAULT_TTS_CODEC_REVISION = "ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae"
DEFAULT_TTS_VOICE = "Trúc Ly"
ALLOWED_TTS_VOICES = frozenset({DEFAULT_TTS_VOICE})
ALLOWED_TTS_STYLES = frozenset({"tu_nhien", "tin_tuc", "doc_truyen"})


@dataclass(frozen=True, slots=True)
class TtsConfig:
    model_id: str = DEFAULT_TTS_MODEL_ID
    model_revision: str = DEFAULT_TTS_MODEL_REVISION
    codec_id: str = DEFAULT_TTS_CODEC_ID
    codec_revision: str = DEFAULT_TTS_CODEC_REVISION
    model_cache: Path = Path("var/cache/models/vieneu")
    device: str = "cpu"
    precision: str = "int8"
    voice: str = DEFAULT_TTS_VOICE
    style: str = "tu_nhien"
    allow_download: bool = True
    cpu_threads: int = 8
    request_timeout_seconds: float = 180.0
    max_pending_syntheses: int = 2
    max_text_characters: int = 2_000
    max_chunk_characters: int = 256
    max_audio_seconds: float = 120.0
    raw_audio_retention: bool = False
    voice_cloning_enabled: bool = False

    def __post_init__(self) -> None:
        for value, name in (
            (self.model_id, "model identifier"),
            (self.codec_id, "codec identifier"),
        ):
            if (
                not value
                or len(value) > 256
                or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
            ):
                raise TtsError("E_TTS_CONFIG", f"TTS {name} is invalid")
        for value, name in (
            (self.model_revision, "model revision"),
            (self.codec_revision, "codec revision"),
        ):
            if re.fullmatch(r"[0-9a-f]{40}", value) is None:
                raise TtsError("E_TTS_CONFIG", f"TTS {name} must be a commit SHA")
        if self.device != "cpu":
            raise TtsError(
                "E_TTS_RESOURCE_LEASE",
                "M05 fast slice permits CPU TTS only; CUDA requires ResourceLease integration",
            )
        if self.precision != "int8":
            raise TtsError("E_TTS_CONFIG", "M05 CPU TTS precision must be int8")
        if self.voice not in ALLOWED_TTS_VOICES:
            raise TtsError("E_TTS_VOICE", "TTS voice is not allowlisted")
        if self.style not in ALLOWED_TTS_STYLES:
            raise TtsError("E_TTS_STYLE", "TTS reading style is invalid")
        if self.raw_audio_retention:
            raise TtsError("E_TTS_CONFIG", "generated audio retention is unavailable in M05")
        if self.voice_cloning_enabled:
            raise TtsError("E_TTS_VOICE_CONSENT", "voice cloning is unavailable in M05")
        for value, name, lower, upper in (
            (self.cpu_threads, "CPU threads", 1, 64),
            (self.max_pending_syntheses, "pending synthesis limit", 1, 16),
            (self.max_text_characters, "text character limit", 32, 10_000),
            (self.max_chunk_characters, "chunk character limit", 32, 512),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise TtsError("E_TTS_CONFIG", f"TTS {name} is invalid")
        for value, name, lower, upper in (
            (self.request_timeout_seconds, "request timeout", 5.0, 600.0),
            (self.max_audio_seconds, "audio duration limit", 1.0, 600.0),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not lower <= float(value) <= upper
            ):
                raise TtsError("E_TTS_CONFIG", f"TTS {name} is invalid")

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        root: Path | None = None,
    ) -> TtsConfig:
        values = env if env is not None else os.environ
        cache = Path(values.get("HINA_TTS_MODEL_CACHE", "var/cache/models/vieneu"))
        if not cache.is_absolute() and root is not None:
            cache = root / cache
        return cls(
            model_id=values.get("HINA_TTS_MODEL", DEFAULT_TTS_MODEL_ID),
            model_revision=values.get("HINA_TTS_MODEL_REVISION", DEFAULT_TTS_MODEL_REVISION),
            codec_id=values.get("HINA_TTS_CODEC", DEFAULT_TTS_CODEC_ID),
            codec_revision=values.get("HINA_TTS_CODEC_REVISION", DEFAULT_TTS_CODEC_REVISION),
            model_cache=cache,
            device=values.get("HINA_TTS_DEVICE", "cpu").strip().lower(),
            precision=values.get("HINA_TTS_PRECISION", "int8").strip().lower(),
            voice=values.get("HINA_TTS_VOICE", DEFAULT_TTS_VOICE).strip(),
            style=values.get("HINA_TTS_STYLE", "tu_nhien").strip().lower(),
            allow_download=_env_bool(values, "HINA_TTS_ALLOW_DOWNLOAD", True),
            cpu_threads=_env_int(values, "HINA_TTS_CPU_THREADS", 8),
            request_timeout_seconds=_env_float(values, "HINA_TTS_TIMEOUT_SECONDS", 180),
            max_pending_syntheses=_env_int(values, "HINA_TTS_MAX_PENDING", 2),
            max_text_characters=_env_int(values, "HINA_TTS_MAX_TEXT_CHARACTERS", 2_000),
            max_chunk_characters=_env_int(values, "HINA_TTS_MAX_CHUNK_CHARACTERS", 256),
            max_audio_seconds=_env_float(values, "HINA_TTS_MAX_AUDIO_SECONDS", 120),
        )

    def public_status(self) -> dict[str, object]:
        return {
            "provider": "vieneu",
            "providerVersion": "3.2.3",
            "model": self.model_id,
            "modelRevision": self.model_revision,
            "codec": self.codec_id,
            "codecRevision": self.codec_revision,
            "device": self.device,
            "precision": self.precision,
            "voice": self.voice,
            "style": self.style,
            "allowDownload": self.allow_download,
            "rawAudioRetention": self.raw_audio_retention,
            "voiceCloning": self.voice_cloning_enabled,
        }


def _env_bool(values: Mapping[str, str], name: str, default: bool) -> bool:
    raw = values.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise TtsError("E_TTS_CONFIG", f"{name} must be a boolean")


def _env_int(values: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(values.get(name, str(default)))
    except ValueError as exc:
        raise TtsError("E_TTS_CONFIG", f"{name} must be an integer") from exc


def _env_float(values: Mapping[str, str], name: str, default: float) -> float:
    try:
        return float(values.get(name, str(default)))
    except ValueError as exc:
        raise TtsError("E_TTS_CONFIG", f"{name} must be numeric") from exc
