from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import SpeechError


DEFAULT_MODEL_ID = "Systran/faster-whisper-small"
DEFAULT_MODEL_REVISION = "536b0662742c02347bc0e980a01041f333bce120"


@dataclass(frozen=True, slots=True)
class SpeechConfig:
    model_id: str = DEFAULT_MODEL_ID
    model_revision: str = DEFAULT_MODEL_REVISION
    model_cache: Path = Path("var/cache/models/faster-whisper")
    device: str = "cpu"
    compute_type: str = "int8"
    allow_download: bool = True
    fallback_to_cpu: bool = True
    cpu_threads: int = 8
    beam_size: int = 1
    request_timeout_seconds: float = 90.0
    model_vram_mib: int = 2_048
    model_ram_mib: int = 2_048
    language: str = "vi"
    task: str = "transcribe"
    max_pending_transcriptions: int = 2
    raw_audio_retention: bool = False

    def __post_init__(self) -> None:
        if (
            not self.model_id
            or len(self.model_id) > 256
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in self.model_id)
        ):
            raise SpeechError("E_STT_CONFIG", "STT model identifier is invalid")
        if re.fullmatch(r"[0-9a-f]{40}", self.model_revision) is None:
            raise SpeechError("E_STT_CONFIG", "STT model revision must be a commit SHA")
        if self.device not in {"cpu", "cuda"}:
            raise SpeechError("E_STT_CONFIG", "STT device must be cpu or cuda")
        allowed_compute = {"int8", "int8_float16", "float16", "float32"}
        if self.compute_type not in allowed_compute:
            raise SpeechError("E_STT_CONFIG", "STT compute type is invalid")
        if self.language != "vi" or self.task != "transcribe":
            raise SpeechError("E_STT_CONFIG", "STT language/task lock must remain vi/transcribe")
        if self.raw_audio_retention:
            raise SpeechError("E_STT_CONFIG", "raw audio retention is unavailable in M04-S1")
        for value, name, lower, upper in (
            (self.cpu_threads, "CPU threads", 1, 64),
            (self.beam_size, "beam size", 1, 10),
            (self.model_vram_mib, "model VRAM", 256, 16_384),
            (self.model_ram_mib, "model RAM", 256, 32_768),
            (self.max_pending_transcriptions, "pending transcription limit", 1, 16),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise SpeechError("E_STT_CONFIG", f"STT {name} is invalid")
        if (
            isinstance(self.request_timeout_seconds, bool)
            or not isinstance(self.request_timeout_seconds, (int, float))
            or not 5 <= self.request_timeout_seconds <= 600
        ):
            raise SpeechError("E_STT_CONFIG", "STT request timeout is invalid")

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        root: Path | None = None,
    ) -> SpeechConfig:
        values = env if env is not None else os.environ
        device = values.get("HINA_STT_DEVICE", "cpu").strip().lower()
        default_compute = "float16" if device == "cuda" else "int8"
        cache_value = values.get("HINA_STT_MODEL_CACHE", "var/cache/models/faster-whisper")
        cache = Path(cache_value)
        if not cache.is_absolute() and root is not None:
            cache = root / cache
        return cls(
            model_id=values.get("HINA_STT_MODEL", DEFAULT_MODEL_ID),
            model_revision=values.get("HINA_STT_MODEL_REVISION", DEFAULT_MODEL_REVISION),
            model_cache=cache,
            device=device,
            compute_type=values.get("HINA_STT_COMPUTE_TYPE", default_compute),
            allow_download=_env_bool(values, "HINA_STT_ALLOW_DOWNLOAD", True),
            fallback_to_cpu=_env_bool(values, "HINA_STT_CPU_FALLBACK", True),
            cpu_threads=_env_int(values, "HINA_STT_CPU_THREADS", 8),
            beam_size=_env_int(values, "HINA_STT_BEAM_SIZE", 1),
            request_timeout_seconds=_env_float(values, "HINA_STT_TIMEOUT_SECONDS", 90),
            model_vram_mib=_env_int(values, "HINA_STT_MODEL_VRAM_MIB", 2_048),
            model_ram_mib=_env_int(values, "HINA_STT_MODEL_RAM_MIB", 2_048),
        )

    def public_status(self) -> dict[str, object]:
        return {
            "provider": "faster-whisper",
            "model": self.model_id,
            "modelRevision": self.model_revision,
            "device": self.device,
            "computeType": self.compute_type,
            "allowDownload": self.allow_download,
            "cpuFallback": self.fallback_to_cpu,
            "language": self.language,
            "task": self.task,
            "rawAudioRetention": self.raw_audio_retention,
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
    raise SpeechError("E_STT_CONFIG", f"{name} must be a boolean")


def _env_int(values: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(values.get(name, str(default)))
    except ValueError as exc:
        raise SpeechError("E_STT_CONFIG", f"{name} must be an integer") from exc


def _env_float(values: Mapping[str, str], name: str, default: float) -> float:
    try:
        return float(values.get(name, str(default)))
    except ValueError as exc:
        raise SpeechError("E_STT_CONFIG", f"{name} must be numeric") from exc
