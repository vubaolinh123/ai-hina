from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .errors import PerceptionError


class VisionProviderKind(StrEnum):
    OLLAMA_LOCAL = "ollama_local"
    OLLAMA_CLOUD = "ollama_cloud"


@dataclass(frozen=True, slots=True)
class VisionConfig:
    local_base_url: str = "http://127.0.0.1:11434"
    cloud_base_url: str = "https://ollama.com"
    request_timeout_seconds: float = 20.0
    max_response_bytes: int = 2_097_152
    max_output_tokens: int = 256
    local_context_tokens: int = 4_096
    local_gpu_layers: int = 999
    local_model_vram_mib: int = 5_120
    local_model_ram_mib: int = 1_024
    max_local_model_bytes: int = 5_368_709_120
    max_discovered_models: int = 64

    def __post_init__(self) -> None:
        if self.local_base_url != "http://127.0.0.1:11434":
            raise PerceptionError(
                "E_PERCEPTION_VISION_CONFIG",
                "local vision endpoint must remain the fixed Ollama loopback endpoint",
            )
        if self.cloud_base_url != "https://ollama.com":
            raise PerceptionError(
                "E_PERCEPTION_VISION_CONFIG",
                "cloud vision endpoint must remain the fixed Ollama Cloud endpoint",
            )
        if (
            isinstance(self.request_timeout_seconds, bool)
            or not isinstance(self.request_timeout_seconds, (int, float))
            or not 3.0 <= float(self.request_timeout_seconds) <= 120.0
        ):
            raise PerceptionError(
                "E_PERCEPTION_VISION_CONFIG",
                "vision request timeout is invalid",
            )
        for value, name, lower, upper in (
            (self.max_response_bytes, "response byte limit", 16_384, 8_388_608),
            (self.max_output_tokens, "output token limit", 32, 2_048),
            (self.local_context_tokens, "local context token limit", 1_024, 8_192),
            (self.local_gpu_layers, "local GPU layer request", 1, 9_999),
            (self.local_model_vram_mib, "local VRAM reservation", 512, 8_192),
            (self.local_model_ram_mib, "local RAM reservation", 256, 16_384),
            (self.max_local_model_bytes, "local model byte limit", 500_000_000, 8_000_000_000),
            (self.max_discovered_models, "model discovery limit", 1, 128),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise PerceptionError(
                    "E_PERCEPTION_VISION_CONFIG",
                    f"vision {name} is invalid",
                )

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> VisionConfig:
        values = env if env is not None else os.environ
        return cls(
            request_timeout_seconds=_env_float(
                values,
                "HINA_VISION_TIMEOUT_SECONDS",
                20.0,
            ),
            max_output_tokens=_env_int(values, "HINA_VISION_MAX_TOKENS", 256),
            local_model_vram_mib=_env_int(
                values,
                "HINA_VISION_LOCAL_VRAM_MIB",
                5_120,
            ),
            local_model_ram_mib=_env_int(
                values,
                "HINA_VISION_LOCAL_RAM_MIB",
                1_024,
            ),
        )

    def public_status(self) -> dict[str, object]:
        return {
            "localEndpoint": self.local_base_url,
            "cloudEndpoint": self.cloud_base_url,
            "requestTimeoutSeconds": float(self.request_timeout_seconds),
            "maxOutputTokens": self.max_output_tokens,
            "localContextTokens": self.local_context_tokens,
            "localGpuLayers": self.local_gpu_layers,
            "localModelVramMiB": self.local_model_vram_mib,
            "localModelRamMiB": self.local_model_ram_mib,
            "maxLocalModelBytes": self.max_local_model_bytes,
            "apiKeyPersistenceOwner": "electron-safe-storage",
        }


class VisionLease(Protocol):
    def assert_active(self) -> None: ...

    async def release(self) -> bool: ...


VisionLeaseFactory = Callable[[Callable[[], Awaitable[None]]], Awaitable[VisionLease]]
RequestJson = Callable[
    [str, str, dict[str, object] | None, str | None, float, int],
    Awaitable[dict[str, Any]],
]


class OllamaVisionProvider:
    """Runtime-configurable Ollama vision boundary.

    Ollama Cloud credentials live only in process memory here. Persistence is
    owned by the Electron main process through OS-backed safeStorage; neither
    status nor errors ever return the secret.
    """

    def __init__(
        self,
        config: VisionConfig,
        *,
        request_json: RequestJson | None = None,
        acquire_local_lease: VisionLeaseFactory | None = None,
    ) -> None:
        self.config = config
        self._request_json = request_json or _request_json
        self._acquire_local_lease = acquire_local_lease
        self._state_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()
        self._provider: VisionProviderKind | None = None
        self._model: str | None = None
        self._api_key: str | None = None
        self._model_details: dict[str, object] | None = None
        self._last_error_code: str | None = None
        self._closed = False

    async def status(self) -> dict[str, Any]:
        async with self._state_lock:
            provider = self._provider
            model = self._model
            api_key_configured = self._api_key is not None
            details = dict(self._model_details or {})
            last_error_code = self._last_error_code
            closed = self._closed
        configured = provider is not None and model is not None
        return {
            "provider": str(provider) if provider is not None else "none",
            "model": model,
            "state": "closed" if closed else "ready" if configured else "unconfigured",
            "available": configured and not closed,
            "apiKeyConfigured": api_key_configured,
            "apiKeyReadableByRenderer": False,
            "apiKeyStorage": "electron-safe-storage",
            "automatic": False,
            "decisionSupportEligible": False,
            "localGpuUsed": provider is VisionProviderKind.OLLAMA_LOCAL,
            "cloudImageUpload": provider is VisionProviderKind.OLLAMA_CLOUD,
            "modelDetails": details,
            "lastErrorCode": last_error_code,
            "configured": self.config.public_status(),
        }

    async def discover_models(
        self,
        *,
        provider: str,
        api_key: str | None,
    ) -> dict[str, Any]:
        kind = _validate_provider(provider)
        key = await self._effective_key(kind, api_key)
        base_url = self._base_url(kind)
        try:
            payload = await self._request_json(
                "GET",
                f"{base_url}/api/tags",
                None,
                key,
                self.config.request_timeout_seconds,
                self.config.max_response_bytes,
            )
            raw_models = payload.get("models")
            if not isinstance(raw_models, list):
                raise PerceptionError(
                    "E_PERCEPTION_VISION_PROTOCOL",
                    "Ollama model list response is invalid",
                )
            candidates = [
                item
                for item in raw_models[: self.config.max_discovered_models]
                if isinstance(item, dict)
            ]
            semaphore = asyncio.Semaphore(8)

            async def inspect(item: dict[str, Any]) -> dict[str, Any] | None:
                name = _model_name(item)
                if name is None:
                    return None
                async with semaphore:
                    try:
                        shown = await self._show_model(kind, name, key)
                    except PerceptionError as exc:
                        if exc.code == "E_PERCEPTION_VISION_MODEL":
                            return None
                        raise
                capabilities = shown.get("capabilities")
                if (
                    not isinstance(capabilities, list)
                    or "vision" not in capabilities
                ):
                    return None
                return _public_model_record(kind, name, item, shown)

            inspected = await asyncio.gather(*(inspect(item) for item in candidates))
            models = [
                item
                for item in inspected
                if item is not None
                and (
                    kind is VisionProviderKind.OLLAMA_CLOUD
                    or (
                        bool(item["lightweight"])
                        and isinstance(item["sizeBytes"], int)
                        and item["sizeBytes"] <= self.config.max_local_model_bytes
                    )
                )
            ]
            models.sort(
                key=lambda item: (
                    not bool(item["lightweight"]),
                    int(item["sizeBytes"] or 2**63 - 1),
                    str(item["name"]).casefold(),
                )
            )
            return {
                "provider": str(kind),
                "count": len(models),
                "models": models,
                "apiKeyConfigured": key is not None,
                "onlyVisionModels": True,
                "localSelectionLimitBytes": (
                    self.config.max_local_model_bytes
                    if kind is VisionProviderKind.OLLAMA_LOCAL
                    else None
                ),
            }
        except PerceptionError as exc:
            await self._remember_error(exc.code)
            raise

    async def configure(
        self,
        *,
        provider: str,
        model: str,
        api_key: str | None,
    ) -> dict[str, Any]:
        kind = _validate_provider(provider)
        name = _validate_model(model)
        key = await self._effective_key(kind, api_key)
        try:
            shown = await self._show_model(kind, name, key)
            capabilities = shown.get("capabilities")
            if (
                not isinstance(capabilities, list)
                or "vision" not in capabilities
            ):
                raise PerceptionError(
                    "E_PERCEPTION_VISION_CAPABILITY",
                    "selected Ollama model does not advertise the vision capability",
                )
            listed = (
                await self._listed_local_model(name)
                if kind is VisionProviderKind.OLLAMA_LOCAL
                else {}
            )
            public = _public_model_record(kind, name, listed, shown)
            if (
                kind is VisionProviderKind.OLLAMA_LOCAL
                and (
                    not public["lightweight"]
                    or (
                        isinstance(public["sizeBytes"], int)
                        and public["sizeBytes"] > self.config.max_local_model_bytes
                    )
                )
            ):
                raise PerceptionError(
                    "E_PERCEPTION_VISION_CAPACITY",
                    "local screen-reading model exceeds Hina's lightweight VRAM profile",
                )
            async with self._state_lock:
                if self._closed:
                    raise PerceptionError(
                        "E_PERCEPTION_VISION_UNAVAILABLE",
                        "vision provider is closed",
                    )
                self._provider = kind
                self._model = name
                self._api_key = key if kind is VisionProviderKind.OLLAMA_CLOUD else None
                self._model_details = public
                self._last_error_code = None
            return await self.status()
        except PerceptionError as exc:
            await self._remember_error(exc.code)
            raise

    async def disable(self) -> dict[str, Any]:
        await self.unload()
        async with self._state_lock:
            self._provider = None
            self._model = None
            self._api_key = None
            self._model_details = None
            self._last_error_code = None
        return await self.status()

    async def analyze(self, image_png: bytes, prompt: str) -> str:
        if not isinstance(image_png, bytes) or not image_png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise PerceptionError(
                "E_PERCEPTION_VISION_REQUEST",
                "vision provider accepts validated PNG bytes only",
            )
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8_192:
            raise PerceptionError(
                "E_PERCEPTION_VISION_REQUEST",
                "vision prompt is invalid",
            )
        async with self._state_lock:
            kind = self._provider
            model = self._model
            key = self._api_key
            closed = self._closed
        if closed or kind is None or model is None:
            raise PerceptionError(
                "E_PERCEPTION_VISION_UNAVAILABLE",
                "screen-reading provider has not been configured in the desktop dashboard",
            )
        body: dict[str, object] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt.strip(),
                    "images": [base64.b64encode(image_png).decode("ascii")],
                }
            ],
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": self.config.max_output_tokens,
            },
        }
        if kind is VisionProviderKind.OLLAMA_LOCAL:
            body["keep_alive"] = 0
            options = body["options"]
            assert isinstance(options, dict)
            options["num_ctx"] = self.config.local_context_tokens
            options["num_gpu"] = self.config.local_gpu_layers
        lease: VisionLease | None = None
        async with self._inference_lock:
            try:
                if kind is VisionProviderKind.OLLAMA_LOCAL:
                    if self._acquire_local_lease is None:
                        raise PerceptionError(
                            "E_PERCEPTION_VISION_CAPACITY",
                            "local vision inference requires Hina's shared GPU scheduler",
                        )
                    lease = await self._acquire_local_lease(self.unload)
                result = await self._request_json(
                    "POST",
                    f"{self._base_url(kind)}/api/chat",
                    body,
                    key,
                    self.config.request_timeout_seconds,
                    self.config.max_response_bytes,
                )
                if lease is not None:
                    lease.assert_active()
                message = result.get("message")
                text = message.get("content") if isinstance(message, dict) else None
                if not isinstance(text, str) or not text.strip():
                    raise PerceptionError(
                        "E_PERCEPTION_VISION_EMPTY",
                        "Ollama vision model returned no final text",
                    )
                await self._remember_error(None)
                return text.strip()
            except PerceptionError as exc:
                await self._remember_error(exc.code)
                raise
            finally:
                if lease is not None:
                    await lease.release()

    async def unload(self) -> None:
        async with self._state_lock:
            kind = self._provider
            model = self._model
        if kind is not VisionProviderKind.OLLAMA_LOCAL or model is None:
            return
        try:
            await self._request_json(
                "POST",
                f"{self.config.local_base_url}/api/generate",
                {"model": model, "keep_alive": 0},
                None,
                min(self.config.request_timeout_seconds, 5.0),
                self.config.max_response_bytes,
            )
        except Exception:
            return

    async def close(self) -> None:
        await self.unload()
        async with self._state_lock:
            self._closed = True
            self._provider = None
            self._model = None
            self._api_key = None
            self._model_details = None

    async def _show_model(
        self,
        kind: VisionProviderKind,
        model: str,
        api_key: str | None,
    ) -> dict[str, Any]:
        return await self._request_json(
            "POST",
            f"{self._base_url(kind)}/api/show",
            {"model": model, "verbose": False},
            api_key,
            self.config.request_timeout_seconds,
            self.config.max_response_bytes,
        )

    async def _listed_local_model(self, model: str) -> dict[str, Any]:
        payload = await self._request_json(
            "GET",
            f"{self.config.local_base_url}/api/tags",
            None,
            None,
            self.config.request_timeout_seconds,
            self.config.max_response_bytes,
        )
        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            raise PerceptionError(
                "E_PERCEPTION_VISION_PROTOCOL",
                "Ollama model list response is invalid",
            )
        for item in raw_models[: self.config.max_discovered_models]:
            if isinstance(item, dict) and _model_name(item) == model:
                return item
        raise PerceptionError(
            "E_PERCEPTION_VISION_MODEL",
            "selected local Ollama model is unavailable in the lightweight discovery window",
        )

    async def _effective_key(
        self,
        kind: VisionProviderKind,
        supplied: str | None,
    ) -> str | None:
        if kind is VisionProviderKind.OLLAMA_LOCAL:
            return None
        if supplied is not None:
            return _validate_api_key(supplied)
        async with self._state_lock:
            existing = self._api_key
        if existing is None:
            raise PerceptionError(
                "E_PERCEPTION_VISION_AUTH",
                "Ollama Cloud API key is required",
            )
        return existing

    def _base_url(self, kind: VisionProviderKind) -> str:
        return (
            self.config.local_base_url
            if kind is VisionProviderKind.OLLAMA_LOCAL
            else self.config.cloud_base_url
        )

    async def _remember_error(self, code: str | None) -> None:
        async with self._state_lock:
            self._last_error_code = code


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


async def _request_json(
    method: str,
    url: str,
    payload: dict[str, object] | None,
    api_key: str | None,
    timeout: float,
    max_bytes: int,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _request_json_sync,
        method,
        url,
        payload,
        api_key,
        timeout,
        max_bytes,
    )


def _request_json_sync(
    method: str,
    url: str,
    payload: dict[str, object] | None,
    api_key: str | None,
    timeout: float,
    max_bytes: int,
) -> dict[str, Any]:
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if payload is not None
        else None
    )
    headers = {"Accept": "application/json"}
    if encoded is not None:
        headers["Content-Type"] = "application/json"
    if api_key is not None:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, data=encoded, headers=headers, method=method)
    opener = build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) > max_bytes:
                raise PerceptionError(
                    "E_PERCEPTION_VISION_PROTOCOL",
                    "Ollama response exceeds the configured size limit",
                )
            raw = response.read(max_bytes + 1)
    except HTTPError as exc:
        exc.read(4_096)
        if exc.code in {401, 403}:
            raise PerceptionError(
                "E_PERCEPTION_VISION_AUTH",
                "Ollama Cloud rejected the API key",
            ) from exc
        if exc.code == 404:
            raise PerceptionError(
                "E_PERCEPTION_VISION_MODEL",
                "selected Ollama model is unavailable",
            ) from exc
        raise PerceptionError(
            "E_PERCEPTION_VISION_PROVIDER",
            f"Ollama vision provider returned HTTP {exc.code}",
            retryable=exc.code >= 500 or exc.code in {408, 429},
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise PerceptionError(
            "E_PERCEPTION_VISION_TIMEOUT",
            "Ollama vision provider timed out",
            retryable=True,
        ) from exc
    except (OSError, URLError) as exc:
        raise PerceptionError(
            "E_PERCEPTION_VISION_OFFLINE",
            "Ollama vision provider is unavailable",
            retryable=True,
        ) from exc
    if len(raw) > max_bytes:
        raise PerceptionError(
            "E_PERCEPTION_VISION_PROTOCOL",
            "Ollama response exceeds the configured size limit",
        )
    try:
        decoded = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PerceptionError(
            "E_PERCEPTION_VISION_PROTOCOL",
            "Ollama response is not valid JSON",
        ) from exc
    if not isinstance(decoded, dict):
        raise PerceptionError(
            "E_PERCEPTION_VISION_PROTOCOL",
            "Ollama response must be a JSON object",
        )
    return decoded


def _validate_provider(value: str) -> VisionProviderKind:
    try:
        return VisionProviderKind(value)
    except (TypeError, ValueError) as exc:
        raise PerceptionError(
            "E_PERCEPTION_VISION_CONFIG",
            "vision provider must be ollama_local or ollama_cloud",
        ) from exc


def _validate_model(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 160
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise PerceptionError(
            "E_PERCEPTION_VISION_CONFIG",
            "vision model name is invalid",
        )
    return value.strip()


def _validate_api_key(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 8 <= len(value) <= 4_096
        or value != value.strip()
        or any(ord(char) < 0x21 or ord(char) == 0x7F for char in value)
    ):
        raise PerceptionError(
            "E_PERCEPTION_VISION_AUTH",
            "Ollama Cloud API key is invalid",
        )
    return value


def _model_name(item: dict[str, Any]) -> str | None:
    value = item.get("model", item.get("name"))
    try:
        return _validate_model(value)
    except PerceptionError:
        return None


def _public_model_record(
    kind: VisionProviderKind,
    name: str,
    listed: dict[str, Any],
    shown: dict[str, Any],
) -> dict[str, Any]:
    details = shown.get("details")
    if not isinstance(details, dict):
        details = listed.get("details")
    if not isinstance(details, dict):
        details = {}
    size = listed.get("size")
    size_bytes = size if isinstance(size, int) and 0 < size <= 10**15 else None
    parameter_size = details.get("parameter_size")
    if not isinstance(parameter_size, str):
        parameter_size = None
    quantization = details.get("quantization_level")
    if not isinstance(quantization, str):
        quantization = None
    capabilities = shown.get("capabilities")
    safe_capabilities = [
        value[:32]
        for value in capabilities
        if isinstance(value, str)
    ] if isinstance(capabilities, list) else []
    lightweight = (
        kind is VisionProviderKind.OLLAMA_CLOUD
        or (
            size_bytes is not None
            and size_bytes <= 5_368_709_120
            and _parameter_count_billion(parameter_size) <= 5.0
        )
    )
    return {
        "name": name,
        "sizeBytes": size_bytes,
        "parameterSize": parameter_size,
        "quantization": quantization,
        "capabilities": safe_capabilities,
        "lightweight": lightweight,
        "localGpuUsed": kind is VisionProviderKind.OLLAMA_LOCAL,
    }


def _parameter_count_billion(value: str | None) -> float:
    if value is None:
        return float("inf")
    normalized = value.strip().upper()
    try:
        if normalized.endswith("B"):
            return float(normalized[:-1])
        if normalized.endswith("M"):
            return float(normalized[:-1]) / 1_000
    except ValueError:
        return float("inf")
    return float("inf")


def _env_int(values: dict[str, str], name: str, default: int) -> int:
    try:
        return int(values.get(name, str(default)))
    except ValueError as exc:
        raise PerceptionError(
            "E_PERCEPTION_VISION_CONFIG",
            f"{name} must be an integer",
        ) from exc


def _env_float(values: dict[str, str], name: str, default: float) -> float:
    try:
        return float(values.get(name, str(default)))
    except ValueError as exc:
        raise PerceptionError(
            "E_PERCEPTION_VISION_CONFIG",
            f"{name} must be numeric",
        ) from exc
