from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any


class FakeProviderError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class FakeModelProvider:
    def __init__(self, *, model_name: str = "hina-fake-model-v1") -> None:
        self.model_name = model_name
        self.call_count = 0
        self.prompt_hashes: list[str] = []

    async def generate(self, prompt: str, *, correlation_id: str) -> str:
        if not isinstance(prompt, str) or not prompt or len(prompt) > 4_096:
            raise FakeProviderError("E_FAKE_MODEL_INPUT", "fake model prompt is invalid")
        if not isinstance(correlation_id, str) or not correlation_id:
            raise FakeProviderError("E_FAKE_MODEL_INPUT", "correlation ID is invalid")
        self.call_count += 1
        self.prompt_hashes.append(hashlib.sha256(prompt.encode("utf-8")).hexdigest())
        return f"Hina (fake) trả lời: {prompt}"


@dataclass(frozen=True, slots=True)
class FakeSpeechResult:
    audio: bytes
    sample_rate_hz: int
    channels: int
    encoding: str


class FakeSpeechProvider:
    def __init__(self) -> None:
        self.call_count = 0
        self.text_hashes: list[str] = []

    async def synthesize(self, text: str, *, correlation_id: str) -> FakeSpeechResult:
        if not isinstance(text, str) or not text or len(text) > 8_192:
            raise FakeProviderError("E_FAKE_SPEECH_INPUT", "fake speech text is invalid")
        if not isinstance(correlation_id, str) or not correlation_id:
            raise FakeProviderError("E_FAKE_SPEECH_INPUT", "correlation ID is invalid")
        self.call_count += 1
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        self.text_hashes.append(digest.hex())
        return FakeSpeechResult(
            audio=b"HINA_FAKE_PCM16LE\x00" + digest,
            sample_rate_hz=16_000,
            channels=1,
            encoding="fake-pcm16le",
        )


class FakeMemoryProvider:
    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self.write_count = 0

    async def remember(self, key: str, value: Any, *, consent: bool) -> None:
        self._validate_key(key)
        if consent is not True:
            raise FakeProviderError("E_CONSENT_REQUIRED", "memory write requires explicit consent")
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise FakeProviderError("E_FAKE_MEMORY_VALUE", "memory value must be JSON") from exc
        if len(encoded.encode("utf-8")) > 65_536:
            raise FakeProviderError("E_FAKE_MEMORY_VALUE", "memory value exceeds fake provider limit")
        self._values[key] = copy.deepcopy(value)
        self.write_count += 1

    async def recall(self, key: str) -> Any | None:
        self._validate_key(key)
        return copy.deepcopy(self._values.get(key))

    @property
    def size(self) -> int:
        return len(self._values)

    @staticmethod
    def _validate_key(key: str) -> None:
        if (
            not isinstance(key, str)
            or not key
            or len(key) > 128
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in key)
        ):
            raise FakeProviderError("E_FAKE_MEMORY_KEY", "memory key is invalid")


class FakeToolProvider:
    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "echo":
            if set(arguments) != {"text"} or not isinstance(arguments["text"], str):
                raise FakeProviderError("E_FAKE_TOOL_ARGUMENT", "echo requires one text argument")
            result: Any = {"text": arguments["text"][:1_024]}
        elif name == "add":
            if set(arguments) != {"left", "right"}:
                raise FakeProviderError("E_FAKE_TOOL_ARGUMENT", "add requires left and right")
            left, right = arguments["left"], arguments["right"]
            if any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in (left, right)
            ):
                raise FakeProviderError("E_FAKE_TOOL_ARGUMENT", "add values must be integers")
            if (
                abs(left) > 9_007_199_254_740_991
                or abs(right) > 9_007_199_254_740_991
                or abs(left + right) > 9_007_199_254_740_991
            ):
                raise FakeProviderError("E_FAKE_TOOL_ARGUMENT", "add result exceeds safe integer range")
            result = {"value": left + right}
        else:
            raise FakeProviderError("E_FAKE_TOOL_UNKNOWN", "fake tool is not allowlisted")
        self.call_count += 1
        return result
