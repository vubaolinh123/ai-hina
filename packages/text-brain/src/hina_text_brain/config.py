from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping
from urllib.parse import urlsplit

from .errors import TextBrainError


class ProviderKind(StrEnum):
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"


@dataclass(frozen=True, slots=True)
class ModelGatewayConfig:
    provider: ProviderKind = ProviderKind.OLLAMA
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3.5:4b"
    api_key: str | None = None
    health_timeout_seconds: float = 3.0
    request_timeout_seconds: float = 90.0
    retry_attempts: int = 1
    circuit_failure_threshold: int = 3
    circuit_reset_seconds: float = 30.0
    max_output_bytes: int = 1_048_576
    model_vram_mib: int = 4_096
    model_ram_mib: int = 1_024
    max_tokens: int = 512
    temperature: float = 0.7

    def __post_init__(self) -> None:
        _validate_loopback_url(self.base_url)
        if (
            not isinstance(self.model, str)
            or not self.model.strip()
            or len(self.model) > 128
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in self.model)
        ):
            raise TextBrainError("E_MODEL_CONFIG", "model name is invalid")
        if self.api_key is not None and (
            not isinstance(self.api_key, str)
            or not self.api_key
            or len(self.api_key) > 4_096
        ):
            raise TextBrainError("E_MODEL_CONFIG", "provider API key is invalid")
        for value, name, lower, upper in (
            (self.health_timeout_seconds, "health timeout", 0.1, 30.0),
            (self.request_timeout_seconds, "request timeout", 1.0, 600.0),
            (self.circuit_reset_seconds, "circuit reset", 1.0, 600.0),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not lower <= value <= upper:
                raise TextBrainError("E_MODEL_CONFIG", f"{name} is invalid")
        for value, name, lower, upper in (
            (self.retry_attempts, "retry attempts", 0, 5),
            (self.circuit_failure_threshold, "circuit threshold", 1, 100),
            (self.max_output_bytes, "output byte limit", 1_024, 16_777_216),
            (self.model_vram_mib, "model VRAM request", 1, 65_536),
            (self.model_ram_mib, "model RAM request", 1, 262_144),
            (self.max_tokens, "max tokens", 1, 32_768),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise TextBrainError("E_MODEL_CONFIG", f"{name} is invalid")
        if (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not 0 <= self.temperature <= 2
        ):
            raise TextBrainError("E_MODEL_CONFIG", "temperature is invalid")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ModelGatewayConfig:
        values = env if env is not None else os.environ
        try:
            provider = ProviderKind(values.get("HINA_MODEL_PROVIDER", "ollama"))
        except ValueError as exc:
            raise TextBrainError("E_MODEL_CONFIG", "model provider is invalid") from exc
        return cls(
            provider=provider,
            base_url=values.get("HINA_MODEL_BASE_URL", "http://127.0.0.1:11434"),
            model=values.get("HINA_MODEL_NAME", "qwen3.5:4b"),
            api_key=values.get("HINA_MODEL_API_KEY") or None,
            health_timeout_seconds=_env_float(values, "HINA_MODEL_HEALTH_TIMEOUT", 3.0),
            request_timeout_seconds=_env_float(values, "HINA_MODEL_REQUEST_TIMEOUT", 90.0),
            retry_attempts=_env_int(values, "HINA_MODEL_RETRY_ATTEMPTS", 1),
            circuit_failure_threshold=_env_int(values, "HINA_MODEL_CIRCUIT_THRESHOLD", 3),
            circuit_reset_seconds=_env_float(values, "HINA_MODEL_CIRCUIT_RESET", 30.0),
            model_vram_mib=_env_int(values, "HINA_MODEL_VRAM_MIB", 4_096),
            model_ram_mib=_env_int(values, "HINA_MODEL_RAM_MIB", 1_024),
            max_tokens=_env_int(values, "HINA_MODEL_MAX_TOKENS", 512),
            temperature=_env_float(values, "HINA_MODEL_TEMPERATURE", 0.7),
        )

    def public_status(self) -> dict[str, object]:
        return {
            "provider": str(self.provider),
            "baseUrl": self.base_url,
            "model": self.model,
            "apiKeyConfigured": self.api_key is not None,
            "healthTimeoutSeconds": self.health_timeout_seconds,
            "requestTimeoutSeconds": self.request_timeout_seconds,
            "retryAttempts": self.retry_attempts,
            "modelVramMiB": self.model_vram_mib,
            "reservedVramHeadroomMiB": 2_048,
        }

    def endpoint_path(self, operation: str) -> str:
        parsed = urlsplit(self.base_url)
        prefix = parsed.path.rstrip("/")
        if self.provider is ProviderKind.OLLAMA:
            suffix = {"health": "/api/tags", "chat": "/api/chat"}[operation]
        else:
            suffix = {"health": "/models", "chat": "/chat/completions"}[operation]
            if not prefix:
                prefix = "/v1"
        return f"{prefix}{suffix}"


def _validate_loopback_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme not in {"http", "https"}
            or host is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        if host.lower() != "localhost" and not ipaddress.ip_address(host).is_loopback:
            raise ValueError
        if parsed.path not in {"", "/", "/v1"}:
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65_535:
            raise ValueError
    except (AttributeError, TypeError, ValueError) as exc:
        raise TextBrainError(
            "E_MODEL_CONFIG",
            "model base URL must be an HTTP(S) loopback endpoint",
        ) from exc


def _env_int(values: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(values.get(name, str(default)))
    except ValueError as exc:
        raise TextBrainError("E_MODEL_CONFIG", f"{name} must be an integer") from exc


def _env_float(values: Mapping[str, str], name: str, default: float) -> float:
    try:
        return float(values.get(name, str(default)))
    except ValueError as exc:
        raise TextBrainError("E_MODEL_CONFIG", f"{name} must be numeric") from exc
