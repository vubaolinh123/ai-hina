from __future__ import annotations


class SpeechError(Exception):
    def __init__(self, code: str, detail: str, *, retryable: bool = False) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


class TtsError(SpeechError):
    """Stable speech-output failure surfaced by the local TTS boundary."""

    def __init__(self, code: str, detail: str, *, retryable: bool = False) -> None:
        super().__init__(code, detail, retryable=retryable)
        self.reported = False
