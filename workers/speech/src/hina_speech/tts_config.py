from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import TtsError


DEFAULT_TTS_PROVIDER = "voxcpm2"
VOXCPM2_MODEL_ID = "openbmb/VoxCPM2"
VOXCPM2_MODEL_REVISION = "bffb3df5a29440629464e5e839f4d214c8714c3d"
VOXCPM2_PACKAGE_VERSION = "2.0.3"
F5_TTS_MODEL_ID = "zalopay/vietnamese-tts"
F5_TTS_MODEL_REVISION = "1dc4967edb4549e40d820429e487eeeacee8bc08"
F5_TTS_MODEL_FILE = "model_1290000.pt"
DEFAULT_TTS_VOCODER_ID = "charactr/vocos-mel-24khz"
DEFAULT_TTS_VOCODER_REVISION = "0feb3fdd929bcd6649e0e7c5a688cf7dd012ef21"
VIENEU_TTS_MODEL_ID = "pnnbao-ump/VieNeu-TTS-v3-Turbo"
VIENEU_TTS_MODEL_REVISION = "75ff82a72f54d55ed389e1eeb12041d3c4bac7d4"
DEFAULT_TTS_MODEL_ID = VOXCPM2_MODEL_ID
DEFAULT_TTS_MODEL_REVISION = VOXCPM2_MODEL_REVISION
DEFAULT_TTS_MODEL_FILE = F5_TTS_MODEL_FILE
DEFAULT_TTS_CODEC_ID = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano"
DEFAULT_TTS_CODEC_REVISION = "6aa02b01e445cc585582cf0ba480bc3ea6c8dd68"
DEFAULT_TTS_VOICE = "Hina Anime AI v1"
DEFAULT_TTS_REFERENCE_AUDIO = Path(
    "assets/voices/hina-anime-elevenlabs-reference.wav"
)
DEFAULT_TTS_REFERENCE_SHA256 = (
    "f71960d949cdebba997cb4a96bc155ee0095dbb42fe6e609e8cf00b41346441f"
)
DEFAULT_TTS_REFERENCE_TEXT = (
    "Xin chào mọi người, Hina có mặt rồi đây, hôm nay mọi người đi làm, "
    "đi học về có mệt lắm không? Cứ từ từ pha một ly nước ấm, rồi ngồi xuống "
    "đây tâm sự với mình nhé."
)
ALLOWED_TTS_VOICES = frozenset({DEFAULT_TTS_VOICE})
ALLOWED_TTS_STYLES = frozenset({"tu_nhien", "tin_tuc", "doc_truyen"})


@dataclass(frozen=True, slots=True)
class TtsConfig:
    provider: str = DEFAULT_TTS_PROVIDER
    model_id: str = DEFAULT_TTS_MODEL_ID
    model_revision: str = DEFAULT_TTS_MODEL_REVISION
    model_file: str = DEFAULT_TTS_MODEL_FILE
    vocoder_id: str = DEFAULT_TTS_VOCODER_ID
    vocoder_revision: str = DEFAULT_TTS_VOCODER_REVISION
    codec_id: str = DEFAULT_TTS_CODEC_ID
    codec_revision: str = DEFAULT_TTS_CODEC_REVISION
    model_cache: Path = Path("var/cache/models/voxcpm2")
    device: str = "cuda"
    precision: str = "bfloat16"
    voice: str = DEFAULT_TTS_VOICE
    style: str = "tu_nhien"
    allow_download: bool = True
    cpu_threads: int = 8
    request_timeout_seconds: float = 180.0
    max_pending_syntheses: int = 2
    max_text_characters: int = 2_000
    max_chunk_characters: int = 180
    max_audio_seconds: float = 120.0
    raw_audio_retention: bool = False
    voice_cloning_enabled: bool = False
    reference_voice_enabled: bool = True
    reference_audio_path: Path = DEFAULT_TTS_REFERENCE_AUDIO
    reference_audio_sha256: str = DEFAULT_TTS_REFERENCE_SHA256
    reference_text: str = DEFAULT_TTS_REFERENCE_TEXT
    nfe_step: int = 32
    inference_timesteps: int = 10
    guidance_scale: float = 2.0
    generation_seed: int = 42
    model_vram_mib: int = 8_192
    model_ram_mib: int = 6_144
    lease_ttl_seconds: float = 86_400.0
    warmup_on_start: bool = False

    def __post_init__(self) -> None:
        if self.provider not in {"f5-tts", "vieneu", "voxcpm2"}:
            raise TtsError("E_TTS_CONFIG", "TTS provider must be f5-tts, vieneu or voxcpm2")
        for value, name in (
            (self.model_id, "model identifier"),
            (self.vocoder_id, "vocoder identifier"),
        ):
            if (
                not value
                or len(value) > 256
                or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
            ):
                raise TtsError("E_TTS_CONFIG", f"TTS {name} is invalid")
        for value, name in (
            (self.model_revision, "model revision"),
            (self.vocoder_revision, "vocoder revision"),
        ):
            if re.fullmatch(r"[0-9a-f]{40}", value) is None:
                raise TtsError("E_TTS_CONFIG", f"TTS {name} must be a commit SHA")
        if self.device not in {"cpu", "cuda"}:
            raise TtsError("E_TTS_CONFIG", "TTS device must be cpu or cuda")
        if self.provider in {"f5-tts", "voxcpm2"} and self.device != "cuda":
            raise TtsError(
                "E_TTS_RESOURCE_LEASE",
                f"{self.provider} is GPU-only in Hina",
            )
        if self.device == "cpu" and self.precision != "int8":
            raise TtsError("E_TTS_CONFIG", "CPU TTS precision must be int8")
        if (
            self.device == "cuda"
            and self.provider in {"vieneu", "voxcpm2"}
            and self.precision not in {"float16", "bfloat16"}
        ):
            raise TtsError(
                "E_TTS_RESOURCE_LEASE",
                "CUDA TTS requires an explicit GPU precision and ResourceLease profile",
            )
        if self.voice not in ALLOWED_TTS_VOICES:
            raise TtsError("E_TTS_VOICE", "TTS voice is not allowlisted")
        if self.style not in ALLOWED_TTS_STYLES:
            raise TtsError("E_TTS_STYLE", "TTS reading style is invalid")
        if self.raw_audio_retention:
            raise TtsError("E_TTS_CONFIG", "generated audio retention is unavailable in M05")
        if self.voice_cloning_enabled:
            raise TtsError(
                "E_TTS_VOICE_CONSENT",
                "arbitrary voice cloning is unavailable; only the fixed authorized Hina reference is allowed",
            )
        if self.reference_voice_enabled:
            if self.voice != DEFAULT_TTS_VOICE:
                raise TtsError("E_TTS_VOICE_CONSENT", "the reference voice must use the Hina profile")
            if self.reference_audio_sha256 and re.fullmatch(r"[0-9a-f]{64}", self.reference_audio_sha256) is None:
                raise TtsError("E_TTS_CONFIG", "TTS reference audio SHA-256 is invalid")
            if self.provider == "f5-tts" and not self.reference_text.strip():
                raise TtsError("E_TTS_CONFIG", "F5-TTS requires a reference transcript")
        for value, name, lower, upper in (
            (self.cpu_threads, "CPU threads", 1, 64),
            (self.max_pending_syntheses, "pending synthesis limit", 1, 16),
            (self.max_text_characters, "text character limit", 32, 10_000),
            (self.max_chunk_characters, "chunk character limit", 32, 512),
            (self.nfe_step, "F5-TTS NFE step count", 8, 64),
            (self.inference_timesteps, "VoxCPM2 inference step count", 4, 50),
            (self.generation_seed, "generation seed", 0, 2_147_483_647),
            (self.model_vram_mib, "model VRAM", 256, 16_384),
            (self.model_ram_mib, "model RAM", 256, 65_536),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise TtsError("E_TTS_CONFIG", f"TTS {name} is invalid")
        for value, name, lower, upper in (
            (self.request_timeout_seconds, "request timeout", 5.0, 600.0),
            (self.max_audio_seconds, "audio duration limit", 1.0, 600.0),
            (self.guidance_scale, "VoxCPM2 guidance scale", 0.1, 10.0),
            (self.lease_ttl_seconds, "GPU lease TTL", 60.0, 86_400.0),
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
        provider = values.get("HINA_TTS_PROVIDER", DEFAULT_TTS_PROVIDER).strip().lower()
        if provider == "f5-tts":
            default_model = F5_TTS_MODEL_ID
            default_revision = F5_TTS_MODEL_REVISION
            default_cache = "var/cache/models/f5-tts"
            default_precision = "float16"
        elif provider == "vieneu":
            default_model = VIENEU_TTS_MODEL_ID
            default_revision = VIENEU_TTS_MODEL_REVISION
            default_cache = "var/cache/models/vieneu"
            default_precision = "float16"
        else:
            default_model = VOXCPM2_MODEL_ID
            default_revision = VOXCPM2_MODEL_REVISION
            default_cache = "var/cache/models/voxcpm2"
            default_precision = "bfloat16"
        default_device = "cuda"
        cache = Path(values.get("HINA_TTS_MODEL_CACHE", default_cache))
        reference = Path(
            values.get("HINA_TTS_REFERENCE_AUDIO", str(DEFAULT_TTS_REFERENCE_AUDIO))
        )
        if not cache.is_absolute() and root is not None:
            cache = root / cache
        if not reference.is_absolute() and root is not None:
            reference = root / reference
        return cls(
            provider=provider,
            model_id=values.get("HINA_TTS_MODEL", default_model),
            model_revision=values.get("HINA_TTS_MODEL_REVISION", default_revision),
            model_file=values.get("HINA_TTS_MODEL_FILE", F5_TTS_MODEL_FILE),
            vocoder_id=values.get("HINA_TTS_VOCODER", DEFAULT_TTS_VOCODER_ID),
            vocoder_revision=values.get(
                "HINA_TTS_VOCODER_REVISION", DEFAULT_TTS_VOCODER_REVISION
            ),
            codec_id=values.get("HINA_TTS_CODEC", DEFAULT_TTS_CODEC_ID),
            codec_revision=values.get("HINA_TTS_CODEC_REVISION", DEFAULT_TTS_CODEC_REVISION),
            model_cache=cache,
            device=values.get("HINA_TTS_DEVICE", default_device).strip().lower(),
            precision=values.get("HINA_TTS_PRECISION", default_precision).strip().lower(),
            voice=values.get("HINA_TTS_VOICE", DEFAULT_TTS_VOICE).strip(),
            style=values.get("HINA_TTS_STYLE", "tu_nhien").strip().lower(),
            allow_download=_env_bool(values, "HINA_TTS_ALLOW_DOWNLOAD", True),
            cpu_threads=_env_int(values, "HINA_TTS_CPU_THREADS", 8),
            request_timeout_seconds=_env_float(values, "HINA_TTS_TIMEOUT_SECONDS", 180),
            max_pending_syntheses=_env_int(values, "HINA_TTS_MAX_PENDING", 2),
            max_text_characters=_env_int(values, "HINA_TTS_MAX_TEXT_CHARACTERS", 2_000),
            max_chunk_characters=_env_int(values, "HINA_TTS_MAX_CHUNK_CHARACTERS", 256),
            max_audio_seconds=_env_float(values, "HINA_TTS_MAX_AUDIO_SECONDS", 120),
            reference_voice_enabled=_env_bool(
                values, "HINA_TTS_REFERENCE_VOICE_ENABLED", True
            ),
            reference_audio_path=reference,
            reference_audio_sha256=values.get(
                "HINA_TTS_REFERENCE_SHA256", DEFAULT_TTS_REFERENCE_SHA256
            ).strip().lower(),
            reference_text=values.get(
                "HINA_TTS_REFERENCE_TEXT", DEFAULT_TTS_REFERENCE_TEXT
            ).strip(),
            nfe_step=_env_int(values, "HINA_TTS_NFE_STEP", 32),
            inference_timesteps=_env_int(values, "HINA_TTS_INFERENCE_STEPS", 10),
            guidance_scale=_env_float(values, "HINA_TTS_GUIDANCE_SCALE", 2.0),
            generation_seed=_env_int(values, "HINA_TTS_GENERATION_SEED", 42),
            model_vram_mib=_env_int(values, "HINA_TTS_MODEL_VRAM_MIB", 8_192),
            model_ram_mib=_env_int(values, "HINA_TTS_MODEL_RAM_MIB", 6_144),
            lease_ttl_seconds=_env_float(values, "HINA_TTS_LEASE_TTL_SECONDS", 86_400),
            warmup_on_start=_env_bool(values, "HINA_TTS_WARMUP_ON_START", False),
        )

    def public_status(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "providerVersion": (
                "1.1.22"
                if self.provider == "f5-tts"
                else VOXCPM2_PACKAGE_VERSION
                if self.provider == "voxcpm2"
                else "3.2.3"
            ),
            "model": self.model_id,
            "modelRevision": self.model_revision,
            "modelFile": self.model_file if self.provider == "f5-tts" else None,
            "vocoder": self.vocoder_id if self.provider == "f5-tts" else None,
            "vocoderRevision": (
                self.vocoder_revision if self.provider == "f5-tts" else None
            ),
            "codec": self.codec_id if self.provider == "vieneu" else None,
            "codecRevision": (
                self.codec_revision if self.provider == "vieneu" else None
            ),
            "device": self.device,
            "precision": self.precision,
            "voice": self.voice,
            "style": self.style,
            "allowDownload": self.allow_download,
            "rawAudioRetention": self.raw_audio_retention,
            "voiceCloning": self.voice_cloning_enabled,
            "referenceVoiceEnrollment": self.reference_voice_enabled,
            "referenceAudioSha256": self.reference_audio_sha256 or None,
            "adaptiveSpeakingRate": {
                "minimum": 1.0,
                # VoxCPM2 audio is deliberately not time-stretched: the old
                # post-process could corrupt individual parts of long replies.
                "maximum": 1.0 if self.provider == "voxcpm2" else 1.18,
            },
            "expressiveCues": (
                ["chuckle", "sigh", "clear throat"]
                if self.provider == "vieneu"
                else ["reference-prosody"]
            ),
            "referenceTranscriptConfigured": (
                bool(self.reference_text) if self.provider == "f5-tts" else False
            ),
            "nfeStep": self.nfe_step,
            "inferenceTimesteps": self.inference_timesteps if self.provider == "voxcpm2" else None,
            "guidanceScale": self.guidance_scale if self.provider == "voxcpm2" else None,
            "modelVramMiB": self.model_vram_mib,
            "modelRamMiB": self.model_ram_mib,
            "leaseTtlSeconds": self.lease_ttl_seconds,
            "warmupOnStart": self.warmup_on_start,
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
