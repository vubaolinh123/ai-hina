from __future__ import annotations

import asyncio
import base64
import http.client
import json
import ssl
import threading
from dataclasses import dataclass
from typing import Any, AsyncIterator
from urllib.parse import urlsplit

from .config import ModelGatewayConfig, ProviderKind
from .errors import TextBrainError


MAX_MESSAGE_BYTES = 32_768
MAX_CONTEXT_BYTES = 131_072
MAX_VISION_IMAGE_BYTES = 1_000_000
MAX_VISION_PROMPT_BYTES = 8_192
_DONE = object()


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    reachable: bool
    model_available: bool
    provider: str
    model: str
    models: tuple[str, ...]
    error_code: str | None = None

    def as_json(self) -> dict[str, object]:
        return {
            "reachable": self.reachable,
            "modelAvailable": self.model_available,
            "provider": self.provider,
            "model": self.model,
            "models": list(self.models),
            "errorCode": self.error_code,
        }


@dataclass(frozen=True, slots=True)
class _StreamFailure:
    error: TextBrainError


class LocalHttpChatProvider:
    def __init__(self, config: ModelGatewayConfig) -> None:
        self.config = config

    async def health(self) -> ProviderHealth:
        try:
            models = await asyncio.to_thread(self._health_sync)
            return ProviderHealth(
                reachable=True,
                model_available=self.config.model in models,
                provider=str(self.config.provider),
                model=self.config.model,
                models=tuple(models[:64]),
            )
        except TextBrainError as exc:
            return ProviderHealth(
                reachable=False,
                model_available=False,
                provider=str(self.config.provider),
                model=self.config.model,
                models=(),
                error_code=exc.code,
            )

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        normalized = _validate_messages(messages)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[object] = asyncio.Queue(maxsize=128)
        stop = threading.Event()
        connection_holder: dict[str, http.client.HTTPConnection] = {}

        def emit(item: object) -> None:
            if stop.is_set():
                return
            try:
                future = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
                future.result(timeout=5)
            except Exception:
                stop.set()

        def worker() -> None:
            try:
                self._stream_sync(normalized, emit, stop, connection_holder)
            except TextBrainError as exc:
                emit(_StreamFailure(exc))
            except Exception:
                emit(
                    _StreamFailure(
                        TextBrainError(
                            "E_MODEL_UNAVAILABLE",
                            "local model provider stream failed",
                            retryable=True,
                        )
                    )
                )
            finally:
                emit(_DONE)

        thread = threading.Thread(target=worker, name="hina-model-stream", daemon=True)
        thread.start()
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                if isinstance(item, _StreamFailure):
                    raise item.error
                if not isinstance(item, str):
                    raise TextBrainError("E_MODEL_STREAM_INVALID", "provider emitted invalid token")
                yield item
        finally:
            stop.set()
            connection = connection_holder.get("connection")
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass
            await asyncio.to_thread(thread.join, 1.0)

    async def analyze_image(self, image_png: bytes, prompt: str) -> str:
        """Analyze one bounded PNG with the configured local Ollama model.

        OpenAI-compatible multimodal payload conventions differ between local
        servers, so M08-S2 deliberately supports only the pinned Ollama route.
        The image exists only in the request-local body and Ollama is asked to
        unload the model immediately after completing the response.
        """

        normalized_image, normalized_prompt = _validate_vision_request(
            image_png,
            prompt,
        )
        if self.config.provider is not ProviderKind.OLLAMA:
            raise TextBrainError(
                "E_MODEL_REQUEST",
                "image analysis requires the configured Ollama provider",
            )
        return await asyncio.to_thread(
            self._analyze_image_sync,
            normalized_image,
            normalized_prompt,
        )

    async def unload(self) -> None:
        if self.config.provider is not ProviderKind.OLLAMA:
            return
        try:
            await asyncio.to_thread(self._unload_sync)
        except TextBrainError:
            return

    def _health_sync(self) -> list[str]:
        connection = self._connection(self.config.health_timeout_seconds)
        try:
            connection.request(
                "GET",
                self.config.endpoint_path("health"),
                headers=self._headers(),
            )
            response = connection.getresponse()
            body = response.read(1_048_577)
            if response.status != 200:
                raise TextBrainError(
                    "E_MODEL_UNAVAILABLE",
                    f"local model provider health returned HTTP {response.status}",
                    retryable=True,
                )
            if len(body) > 1_048_576:
                raise TextBrainError("E_MODEL_PROTOCOL", "provider health response is too large")
            payload = json.loads(body.decode("utf-8"))
            if self.config.provider is ProviderKind.OLLAMA:
                raw_models = payload.get("models") if isinstance(payload, dict) else None
                names = [
                    item.get("name")
                    for item in raw_models
                    if isinstance(item, dict) and isinstance(item.get("name"), str)
                ] if isinstance(raw_models, list) else []
            else:
                raw_models = payload.get("data") if isinstance(payload, dict) else None
                names = [
                    item.get("id")
                    for item in raw_models
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                ] if isinstance(raw_models, list) else []
            return sorted(set(name for name in names if name and len(name) <= 128))
        except TextBrainError:
            raise
        except (OSError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise TextBrainError(
                "E_MODEL_UNAVAILABLE",
                "local model provider health is unavailable",
                retryable=True,
            ) from exc
        finally:
            connection.close()

    def _stream_sync(
        self,
        messages: list[dict[str, str]],
        emit: Any,
        stop: threading.Event,
        connection_holder: dict[str, http.client.HTTPConnection],
    ) -> None:
        connection = self._connection(self.config.request_timeout_seconds)
        connection_holder["connection"] = connection
        body = self._chat_body(messages)
        try:
            connection.request(
                "POST",
                self.config.endpoint_path("chat"),
                body=body,
                headers=self._headers(content_length=len(body)),
            )
            response = connection.getresponse()
            if response.status != 200:
                response.read(4_096)
                raise TextBrainError(
                    "E_MODEL_UNAVAILABLE",
                    f"local model provider returned HTTP {response.status}",
                    retryable=response.status >= 500 or response.status in {408, 429},
                )
            total_bytes = 0
            while not stop.is_set():
                line = response.readline(65_537)
                if not line:
                    break
                if len(line) > 65_536:
                    raise TextBrainError("E_MODEL_STREAM_INVALID", "provider stream line is too large")
                token, done = self._parse_stream_line(line)
                if token:
                    token_bytes = len(token.encode("utf-8"))
                    total_bytes += token_bytes
                    if total_bytes > self.config.max_output_bytes:
                        raise TextBrainError("E_MODEL_STREAM_INVALID", "provider output exceeds byte limit")
                    emit(token)
                if done:
                    break
        except TextBrainError:
            raise
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise TextBrainError(
                "E_MODEL_UNAVAILABLE",
                "local model provider stream is unavailable",
                retryable=True,
            ) from exc
        finally:
            connection_holder.pop("connection", None)
            connection.close()

    def _parse_stream_line(self, line: bytes) -> tuple[str, bool]:
        try:
            decoded = line.decode("utf-8").strip()
            if not decoded:
                return "", False
            if self.config.provider is ProviderKind.OLLAMA:
                payload = json.loads(decoded)
                if not isinstance(payload, dict) or payload.get("error") is not None:
                    raise ValueError
                message = payload.get("message")
                token = message.get("content", "") if isinstance(message, dict) else ""
                if not isinstance(token, str):
                    raise ValueError
                return token, payload.get("done") is True
            if not decoded.startswith("data:"):
                return "", False
            data = decoded[5:].strip()
            if data == "[DONE]":
                return "", True
            payload = json.loads(data)
            choices = payload.get("choices") if isinstance(payload, dict) else None
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ValueError
            choice = choices[0]
            delta = choice.get("delta")
            token = delta.get("content", "") if isinstance(delta, dict) else ""
            if token is None:
                token = ""
            if not isinstance(token, str):
                raise ValueError
            return token, choice.get("finish_reason") is not None
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise TextBrainError(
                "E_MODEL_STREAM_INVALID",
                "provider emitted malformed stream data",
            ) from exc

    def _unload_sync(self) -> None:
        connection = self._connection(self.config.health_timeout_seconds)
        body = json.dumps(
            {"model": self.config.model, "keep_alive": 0},
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            connection.request(
                "POST",
                "/api/generate",
                body=body,
                headers=self._headers(content_length=len(body)),
            )
            response = connection.getresponse()
            response.read(4_096)
            if response.status != 200:
                raise TextBrainError("E_MODEL_UNAVAILABLE", "provider unload failed")
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise TextBrainError("E_MODEL_UNAVAILABLE", "provider unload failed") from exc
        finally:
            connection.close()

    def _analyze_image_sync(self, image_png: bytes, prompt: str) -> str:
        connection = self._connection(self.config.request_timeout_seconds)
        body = self._vision_body(image_png, prompt)
        try:
            connection.request(
                "POST",
                self.config.endpoint_path("chat"),
                body=body,
                headers=self._headers(content_length=len(body)),
            )
            response = connection.getresponse()
            if response.status != 200:
                response.read(4_096)
                raise TextBrainError(
                    "E_MODEL_UNAVAILABLE",
                    f"local vision provider returned HTTP {response.status}",
                    retryable=response.status >= 500 or response.status in {408, 429},
                )
            raw = response.read(self.config.max_output_bytes + 1)
            if len(raw) > self.config.max_output_bytes:
                raise TextBrainError(
                    "E_MODEL_STREAM_INVALID",
                    "local vision response exceeds byte limit",
                )
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("error") is not None:
                raise ValueError
            message = payload.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str):
                raise ValueError
            result = content.strip()
            if not result:
                raise TextBrainError(
                    "E_MODEL_EMPTY_RESPONSE",
                    "local vision provider returned no text",
                    retryable=True,
                )
            if len(result.encode("utf-8")) > self.config.max_output_bytes:
                raise TextBrainError(
                    "E_MODEL_STREAM_INVALID",
                    "local vision output exceeds byte limit",
                )
            return result
        except TextBrainError:
            raise
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise TextBrainError(
                "E_MODEL_UNAVAILABLE",
                "local vision provider is unavailable",
                retryable=True,
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise TextBrainError(
                "E_MODEL_STREAM_INVALID",
                "local vision provider returned malformed data",
            ) from exc
        finally:
            connection.close()

    def _chat_body(self, messages: list[dict[str, str]]) -> bytes:
        if self.config.provider is ProviderKind.OLLAMA:
            payload: dict[str, Any] = {
                "model": self.config.model,
                "messages": messages,
                "stream": True,
                # Hina alternates a 4B chat model with GPU-only STT/TTS on a
                # 16 GiB card. Keeping Ollama resident after the stream leaves
                # no truthful way for the shared scheduler to preserve its
                # mandatory 2 GiB headroom.
                "keep_alive": 0,
                "think": False,
                "options": {
                    "temperature": self.config.temperature,
                    "repeat_penalty": self.config.repeat_penalty,
                    "num_predict": self.config.max_tokens,
                },
            }
        else:
            payload = {
                "model": self.config.model,
                "messages": messages,
                "stream": True,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            }
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def _vision_body(self, image_png: bytes, prompt: str) -> bytes:
        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [base64.b64encode(image_png).decode("ascii")],
                }
            ],
            "stream": False,
            "keep_alive": 0,
            "think": False,
            "options": {
                "temperature": min(self.config.temperature, 0.2),
                "num_ctx": 4_096,
                "num_predict": self.config.max_tokens,
            },
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def _connection(self, timeout: float) -> http.client.HTTPConnection:
        parsed = urlsplit(self.config.base_url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if parsed.scheme == "https":
            return http.client.HTTPSConnection(
                parsed.hostname,
                port,
                timeout=timeout,
                context=ssl.create_default_context(),
            )
        return http.client.HTTPConnection(parsed.hostname, port, timeout=timeout)

    def _headers(self, *, content_length: int | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "hina-ai-local/0.1",
        }
        if content_length is not None:
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(content_length)
        if self.config.api_key is not None:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers


def _validate_messages(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 64:
        raise TextBrainError("E_MODEL_REQUEST", "message list is invalid")
    total_bytes = 0
    messages: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            raise TextBrainError("E_MODEL_REQUEST", "message fields are invalid")
        role = item["role"]
        content = item["content"]
        if role not in {"system", "user", "assistant"}:
            raise TextBrainError("E_MODEL_REQUEST", "message role is invalid")
        if not isinstance(content, str) or not content:
            raise TextBrainError("E_MODEL_REQUEST", "message content is invalid")
        try:
            size = len(content.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise TextBrainError("E_MODEL_REQUEST", "message content is invalid Unicode") from exc
        if size > MAX_MESSAGE_BYTES:
            raise TextBrainError("E_MODEL_REQUEST", "message exceeds byte limit")
        total_bytes += size
        if total_bytes > MAX_CONTEXT_BYTES:
            raise TextBrainError("E_MODEL_REQUEST", "conversation context exceeds byte limit")
        messages.append({"role": role, "content": content})
    return messages


def _validate_vision_request(image_png: Any, prompt: Any) -> tuple[bytes, str]:
    if (
        not isinstance(image_png, bytes)
        or not 8 <= len(image_png) <= MAX_VISION_IMAGE_BYTES
        or not image_png.startswith(b"\x89PNG\r\n\x1a\n")
    ):
        raise TextBrainError(
            "E_MODEL_REQUEST",
            "vision input must be a bounded PNG image",
        )
    if not isinstance(prompt, str):
        raise TextBrainError("E_MODEL_REQUEST", "vision prompt is invalid")
    normalized_prompt = prompt.strip()
    try:
        prompt_bytes = normalized_prompt.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise TextBrainError("E_MODEL_REQUEST", "vision prompt is invalid Unicode") from exc
    if not normalized_prompt or len(prompt_bytes) > MAX_VISION_PROMPT_BYTES:
        raise TextBrainError("E_MODEL_REQUEST", "vision prompt exceeds byte limit")
    return image_png, normalized_prompt
