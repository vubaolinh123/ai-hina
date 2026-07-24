from .audio import (
    MAX_AUDIO_BYTES,
    MAX_AUDIO_SECONDS,
    TARGET_SAMPLE_RATE_HZ,
    decode_and_normalize_wav,
)
from .capture import (
    AudioDevice,
    BoundedCaptureBuffer,
    CaptureBufferMetrics,
    CaptureState,
)
from .config import (
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_REVISION,
    SpeechConfig,
)
from .errors import SpeechError, TtsError
from .model import NormalizedAudio, SttResult, SttSegment, TtsPcmChunk, TtsSynthesis, VadResult
from .provider import FasterWhisperProvider, GpuLease, GpuLeaseFactory, SttProvider
from .service import SpeechInputService
from .tts_audio import pcm16_to_wav
from .tts_config import (
    ALLOWED_TTS_STYLES,
    ALLOWED_TTS_VOICES,
    DEFAULT_TTS_CODEC_ID,
    DEFAULT_TTS_CODEC_REVISION,
    DEFAULT_TTS_MODEL_ID,
    DEFAULT_TTS_MODEL_REVISION,
    DEFAULT_TTS_VOICE,
    TtsConfig,
)
from .tts_provider import TtsProvider, VieneuTtsProvider
from .tts_service import SpeechOutputService
from .tts_text import normalize_tts_text, split_tts_chunks
from .vad import EnergyVad, EnergyVadConfig

__all__ = [
    "AudioDevice",
    "ALLOWED_TTS_STYLES",
    "ALLOWED_TTS_VOICES",
    "BoundedCaptureBuffer",
    "CaptureBufferMetrics",
    "CaptureState",
    "DEFAULT_MODEL_ID",
    "DEFAULT_MODEL_REVISION",
    "DEFAULT_TTS_CODEC_ID",
    "DEFAULT_TTS_CODEC_REVISION",
    "DEFAULT_TTS_MODEL_ID",
    "DEFAULT_TTS_MODEL_REVISION",
    "DEFAULT_TTS_VOICE",
    "EnergyVad",
    "EnergyVadConfig",
    "FasterWhisperProvider",
    "GpuLease",
    "GpuLeaseFactory",
    "MAX_AUDIO_BYTES",
    "MAX_AUDIO_SECONDS",
    "NormalizedAudio",
    "SpeechConfig",
    "SpeechError",
    "SpeechInputService",
    "SpeechOutputService",
    "SttProvider",
    "SttResult",
    "SttSegment",
    "TtsConfig",
    "TtsError",
    "TtsPcmChunk",
    "TtsProvider",
    "TtsSynthesis",
    "TARGET_SAMPLE_RATE_HZ",
    "VadResult",
    "decode_and_normalize_wav",
    "normalize_tts_text",
    "pcm16_to_wav",
    "split_tts_chunks",
    "VieneuTtsProvider",
]
