from __future__ import annotations

import asyncio
import base64
import http.client
import json
import re
import ssl
import threading
import time
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
_QWEN_CONTROL_TOKENS = (
    "<|im_start|>",
    "<|im_end|>",
    "<think>",
    "</think>",
)
_REASONING_TERMS = re.compile(
    r"\b(?:"
    r"analy[sz]e|compare|debug|evaluate|explain why|plan|prove|reason|strategy|"
    r"chứng minh|debug|đánh giá|giả sử|giải bài|giải thích|lập kế hoạch|"
    r"nếu.+thì|nguyên nhân|phân tích|so sánh|suy luận|tại sao|tính|tối ưu|vì sao"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)
_REASONING_MATH = re.compile(r"(?:\d[\d., ]*)\s*(?:%|[+\-*/=<>])")
_VISION_REASONING_TERMS = re.compile(
    r"\b(?:"
    r"analy[sz]e|compare|debug|evaluate|explain why|plan|prove|reason|strategy|"
    r"chứng minh|debug|đánh giá|giải thích|lập kế hoạch|nguyên nhân|phân tích|"
    r"so sánh|suy luận|tại sao|tối ưu|vì sao|chiến lược"
    r")\b",
    re.IGNORECASE,
)


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
        self._operator_pinned = False

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
        self._operator_pinned = False
        try:
            await asyncio.to_thread(self._unload_sync)
        except TextBrainError:
            return

    async def warmup(self) -> None:
        if self.config.provider is not ProviderKind.OLLAMA:
            raise TextBrainError(
                "E_MODEL_REQUEST",
                "manual model loading requires the configured Ollama provider",
            )
        await asyncio.to_thread(self._warmup_sync)

    def set_operator_pinned(self, enabled: bool) -> None:
        self._operator_pinned = bool(enabled)

    async def resident_models(self) -> list[dict[str, object]]:
        """Return Ollama models that are currently resident, not merely installed."""

        if self.config.provider is not ProviderKind.OLLAMA:
            return []
        return await asyncio.to_thread(self._resident_models_sync)

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

    def _resident_models_sync(self) -> list[dict[str, object]]:
        connection = self._connection(self.config.health_timeout_seconds)
        try:
            connection.request(
                "GET",
                self.config.endpoint_path("resident"),
                headers=self._headers(),
            )
            response = connection.getresponse()
            body = response.read(1_048_577)
            if response.status != 200:
                raise TextBrainError(
                    "E_MODEL_UNAVAILABLE",
                    f"local model provider residency returned HTTP {response.status}",
                    retryable=True,
                )
            if len(body) > 1_048_576:
                raise TextBrainError(
                    "E_MODEL_PROTOCOL",
                    "provider residency response is too large",
                )
            payload = json.loads(body.decode("utf-8"))
            raw_models = payload.get("models") if isinstance(payload, dict) else None
            if not isinstance(raw_models, list):
                raise ValueError
            models: list[dict[str, object]] = []
            for item in raw_models[:64]:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("model")
                if not isinstance(name, str) or not name or len(name) > 128:
                    continue
                details = item.get("details")
                quantization = (
                    details.get("quantization_level")
                    if isinstance(details, dict)
                    else None
                )
                models.append(
                    {
                        "name": name,
                        "sizeBytes": _bounded_nonnegative_int(item.get("size")),
                        "sizeVramBytes": _bounded_nonnegative_int(
                            item.get("size_vram")
                        ),
                        "contextLength": _bounded_nonnegative_int(
                            item.get("context_length")
                        ),
                        "quantization": (
                            quantization[:32]
                            if isinstance(quantization, str)
                            else None
                        ),
                    }
                )
            return models
        except TextBrainError:
            raise
        except (
            OSError,
            TimeoutError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            ValueError,
        ) as exc:
            raise TextBrainError(
                "E_MODEL_UNAVAILABLE",
                "local model provider residency is unavailable",
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
        deadline = time.monotonic() + self.config.request_timeout_seconds
        if (
            self.config.provider is ProviderKind.OLLAMA
            and _requires_hidden_thinking(messages)
        ):
            try:
                self._stream_reasoned_ollama_sync(
                    messages,
                    emit,
                    stop,
                    connection_holder,
                    deadline,
                )
            finally:
                if not self._operator_pinned:
                    self._unload_sync()
            return

        connection = self._connection(self.config.request_timeout_seconds)
        connection_holder["connection"] = connection
        if self.config.provider is ProviderKind.OLLAMA:
            endpoint = self.config.endpoint_path("generate")
            body = self._fast_generate_body(messages)
            stream_kind = "ollama-generate"
        else:
            endpoint = self.config.endpoint_path("chat")
            body = self._chat_body(messages)
            stream_kind = (
                "ollama-chat"
                if self.config.provider is ProviderKind.OLLAMA
                else "openai-chat"
            )
        try:
            connection.request(
                "POST",
                endpoint,
                body=body,
                headers=self._headers(content_length=len(body)),
            )
            response = connection.getresponse()
            _assert_before_deadline(deadline)
            if response.status != 200:
                response.read(4_096)
                raise TextBrainError(
                    "E_MODEL_UNAVAILABLE",
                    f"local model provider returned HTTP {response.status}",
                    retryable=response.status >= 500 or response.status in {408, 429},
                )
            total_bytes = 0
            while not stop.is_set():
                _set_remaining_socket_timeout(connection, deadline)
                line = response.readline(65_537)
                _assert_before_deadline(deadline)
                if not line:
                    break
                if len(line) > 65_536:
                    raise TextBrainError("E_MODEL_STREAM_INVALID", "provider stream line is too large")
                token, done = self._parse_stream_line(line, stream_kind=stream_kind)
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
        except TimeoutError as exc:
            raise TextBrainError(
                "E_MODEL_TIMEOUT",
                "local model exceeded the configured response deadline",
                retryable=True,
            ) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise TextBrainError(
                "E_MODEL_UNAVAILABLE",
                "local model provider stream is unavailable",
                retryable=True,
            ) from exc
        finally:
            connection_holder.pop("connection", None)
            connection.close()

    def _stream_reasoned_ollama_sync(
        self,
        messages: list[dict[str, str]],
        emit: Any,
        stop: threading.Event,
        connection_holder: dict[str, http.client.HTTPConnection],
        deadline: float,
    ) -> None:
        """Run a bounded private scratchpad, then stream only its final answer."""

        reasoning_connection = self._connection(self.config.request_timeout_seconds)
        connection_holder["connection"] = reasoning_connection
        try:
            body = self._chat_body(messages)
            reasoning_connection.request(
                "POST",
                self.config.endpoint_path("chat"),
                body=body,
                headers=self._headers(content_length=len(body)),
            )
            response = reasoning_connection.getresponse()
            _assert_before_deadline(deadline)
            if response.status != 200:
                response.read(4_096)
                raise TextBrainError(
                    "E_MODEL_UNAVAILABLE",
                    f"local model provider returned HTTP {response.status}",
                    retryable=response.status >= 500 or response.status in {408, 429},
                )
            _set_remaining_socket_timeout(reasoning_connection, deadline)
            raw = response.read(self.config.max_output_bytes + 1)
            _assert_before_deadline(deadline)
            if len(raw) > self.config.max_output_bytes:
                raise TextBrainError(
                    "E_MODEL_STREAM_INVALID",
                    "private reasoning response exceeds byte limit",
                )
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("error") is not None:
                raise ValueError
            message = payload.get("message")
            if not isinstance(message, dict):
                raise ValueError
            content = message.get("content", "")
            thinking = message.get("thinking", "")
            if not isinstance(content, str) or not isinstance(thinking, str):
                raise ValueError
            if content.strip() and payload.get("done_reason") != "length":
                emit(content)
                return
            if not thinking.strip():
                raise TextBrainError(
                    "E_MODEL_EMPTY_RESPONSE",
                    "local model returned no private scratchpad or final answer",
                    retryable=True,
                )
        except TextBrainError:
            raise
        except TimeoutError as exc:
            raise TextBrainError(
                "E_MODEL_TIMEOUT",
                "local model exceeded the configured response deadline",
                retryable=True,
            ) from exc
        except (
            OSError,
            http.client.HTTPException,
            json.JSONDecodeError,
            UnicodeDecodeError,
            ValueError,
        ) as exc:
            raise TextBrainError(
                "E_MODEL_UNAVAILABLE",
                "local model private reasoning request failed",
                retryable=True,
            ) from exc
        finally:
            connection_holder.pop("connection", None)
            reasoning_connection.close()

        if stop.is_set():
            return

        answer_connection = self._connection(self.config.request_timeout_seconds)
        connection_holder["connection"] = answer_connection
        body = self._reasoned_generate_body(messages, thinking)
        try:
            answer_connection.request(
                "POST",
                self.config.endpoint_path("generate"),
                body=body,
                headers=self._headers(content_length=len(body)),
            )
            response = answer_connection.getresponse()
            _assert_before_deadline(deadline)
            if response.status != 200:
                response.read(4_096)
                raise TextBrainError(
                    "E_MODEL_UNAVAILABLE",
                    f"local model provider returned HTTP {response.status}",
                    retryable=response.status >= 500 or response.status in {408, 429},
                )
            total_bytes = 0
            while not stop.is_set():
                _set_remaining_socket_timeout(answer_connection, deadline)
                line = response.readline(65_537)
                _assert_before_deadline(deadline)
                if not line:
                    break
                if len(line) > 65_536:
                    raise TextBrainError(
                        "E_MODEL_STREAM_INVALID",
                        "provider stream line is too large",
                    )
                token, done = self._parse_stream_line(
                    line,
                    stream_kind="ollama-generate",
                )
                if token:
                    token_bytes = len(token.encode("utf-8"))
                    total_bytes += token_bytes
                    if total_bytes > self.config.max_output_bytes:
                        raise TextBrainError(
                            "E_MODEL_STREAM_INVALID",
                            "provider output exceeds byte limit",
                        )
                    emit(token)
                if done:
                    break
        except TextBrainError:
            raise
        except TimeoutError as exc:
            raise TextBrainError(
                "E_MODEL_TIMEOUT",
                "local model exceeded the configured response deadline",
                retryable=True,
            ) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise TextBrainError(
                "E_MODEL_UNAVAILABLE",
                "local model provider stream is unavailable",
                retryable=True,
            ) from exc
        finally:
            connection_holder.pop("connection", None)
            answer_connection.close()

    def _parse_stream_line(
        self,
        line: bytes,
        *,
        stream_kind: str,
    ) -> tuple[str, bool]:
        try:
            decoded = line.decode("utf-8").strip()
            if not decoded:
                return "", False
            if stream_kind == "ollama-generate":
                payload = json.loads(decoded)
                if not isinstance(payload, dict) or payload.get("error") is not None:
                    raise ValueError
                token = payload.get("response", "")
                if not isinstance(token, str):
                    raise ValueError
                return token, payload.get("done") is True
            if stream_kind == "ollama-chat":
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

    def _warmup_sync(self) -> None:
        # A cold 8B checkpoint can legitimately take longer than the small
        # availability probe.  Owner-triggered warmup has its own bounded
        # deadline, while health checks remain fast.
        connection = self._connection(self.config.warmup_timeout_seconds)
        body = json.dumps(
            {
                "model": self.config.model,
                "prompt": " ",
                "stream": False,
                "keep_alive": -1,
                "think": False,
                "options": {
                    "num_predict": 1,
                    # Force-load must reflect the context that real turns use;
                    # a 2K probe understated resident KV memory and caused the
                    # first 8K turn to reload inside its nine-second deadline.
                    "num_ctx": self.config.context_tokens,
                    "num_gpu": self.config.ollama_gpu_layers,
                },
            },
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
            response.read(self.config.max_output_bytes + 1)
            if response.status != 200:
                raise TextBrainError(
                    "E_MODEL_UNAVAILABLE",
                    f"provider warmup returned HTTP {response.status}",
                    retryable=True,
                )
        except TextBrainError:
            raise
        except TimeoutError as exc:
            raise TextBrainError(
                "E_MODEL_UNAVAILABLE",
                "provider warmup timed out",
                retryable=True,
            ) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise TextBrainError(
                "E_MODEL_UNAVAILABLE",
                "provider warmup connection failed",
                retryable=True,
            ) from exc
        finally:
            connection.close()

    def _analyze_image_sync(self, image_png: bytes, prompt: str) -> str:
        connection = self._connection(self.config.request_timeout_seconds)
        body = self._vision_body(image_png, prompt)
        deadline = time.monotonic() + self.config.request_timeout_seconds
        try:
            connection.request(
                "POST",
                self.config.endpoint_path("chat"),
                body=body,
                headers=self._headers(content_length=len(body)),
            )
            response = connection.getresponse()
            _assert_before_deadline(deadline)
            if response.status != 200:
                response.read(4_096)
                raise TextBrainError(
                    "E_MODEL_UNAVAILABLE",
                    f"local vision provider returned HTTP {response.status}",
                    retryable=response.status >= 500 or response.status in {408, 429},
                )
            _set_remaining_socket_timeout(connection, deadline)
            raw = response.read(self.config.max_output_bytes + 1)
            _assert_before_deadline(deadline)
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
        except TimeoutError as exc:
            raise TextBrainError(
                "E_MODEL_TIMEOUT",
                "local vision model exceeded the configured response deadline",
                retryable=True,
            ) from exc
        except (OSError, http.client.HTTPException) as exc:
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
                "stream": False,
                # Keep the same resident checkpoint between the private
                # scratchpad and final-answer pass. The second pass releases it
                # when the operator has not explicitly pinned the model.
                "keep_alive": -1,
                "think": True,
                "options": {
                    "temperature": self.config.temperature,
                    "repeat_penalty": self.config.repeat_penalty,
                    "num_predict": self.config.thinking_max_tokens,
                    "num_ctx": self.config.context_tokens,
                    "num_gpu": self.config.ollama_gpu_layers,
                    "stop": [
                        "<|im_end|>",
                        "<think>",
                        "\n---\n",
                        "\n**Phân tích hành vi",
                        "\nPhân tích hành vi:",
                        "\nSystem prompt:",
                        "\nDeveloper instruction:",
                    ],
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

    def _reasoned_generate_body(
        self,
        messages: list[dict[str, str]],
        thinking: str,
    ) -> bytes:
        payload = {
            "model": self.config.model,
            "prompt": _qwen_reasoned_prompt(messages, thinking),
            "raw": True,
            "stream": True,
            # The wrapper explicitly unloads non-pinned models after this
            # second pass, including cancellation and error paths.
            "keep_alive": -1,
            "options": {
                "temperature": self.config.temperature,
                "repeat_penalty": self.config.repeat_penalty,
                "num_predict": self.config.max_tokens,
                "num_ctx": self.config.context_tokens,
                "num_gpu": self.config.ollama_gpu_layers,
                "stop": [
                    "<|im_end|>",
                    "<think>",
                    "\n---\n",
                    "\n**Phân tích hành vi",
                    "\nPhân tích hành vi:",
                    "\nSystem prompt:",
                    "\nDeveloper instruction:",
                ],
            },
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def _fast_generate_body(self, messages: list[dict[str, str]]) -> bytes:
        if self.config.provider is not ProviderKind.OLLAMA:
            raise TextBrainError(
                "E_MODEL_REQUEST",
                "the same-weight fast path requires the configured Ollama provider",
            )
        payload = {
            "model": self.config.model,
            "prompt": _qwen_no_think_prompt(messages),
            "raw": True,
            "stream": True,
            "keep_alive": -1 if self._operator_pinned else 0,
            "options": {
                "temperature": self.config.temperature,
                "repeat_penalty": self.config.repeat_penalty,
                "num_predict": self.config.max_tokens,
                "num_ctx": self.config.context_tokens,
                "num_gpu": self.config.ollama_gpu_layers,
                # If the thinking checkpoint tries to open another thought
                # block, stop instead of exposing hidden reasoning as text.
                "stop": [
                    "<|im_end|>",
                    "<think>",
                    "\n---\n",
                    "\n**Phân tích hành vi",
                    "\nPhân tích hành vi:",
                    "\nSystem prompt:",
                    "\nDeveloper instruction:",
                ],
            },
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def _vision_body(self, image_png: bytes, prompt: str) -> bytes:
        requires_thinking = _requires_hidden_vision_thinking(prompt)
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(image_png).decode("ascii")],
            }
        ]
        if not requires_thinking:
            # Ollama's Qwen3-VL renderer inserts the correct image tokens before
            # this assistant prefix. Closing the private block gives routine
            # screenshot description a reliable same-weight path; no Instruct
            # checkpoint or second model tag is loaded.
            messages.append(
                {
                    "role": "assistant",
                    "content": "<think>\n\n</think>\n\n",
                }
            )
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "keep_alive": -1 if self._operator_pinned else 0,
            "think": True,
            "options": {
                "temperature": (
                    self.config.temperature
                    if requires_thinking
                    else min(self.config.temperature, 0.3)
                ),
                "repeat_penalty": self.config.repeat_penalty,
                "num_ctx": self.config.context_tokens,
                "num_predict": (
                    self.config.thinking_max_tokens
                    if requires_thinking
                    else self.config.vision_fast_max_tokens
                ),
                "num_gpu": self.config.ollama_gpu_layers,
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


def _requires_hidden_thinking(messages: list[dict[str, str]]) -> bool:
    latest_user = next(
        (
            item["content"]
            for item in reversed(messages)
            if item.get("role") == "user"
        ),
        "",
    )
    normalized = " ".join(latest_user.casefold().split())
    if len(normalized) >= 220:
        return True
    if _REASONING_TERMS.search(normalized) is not None:
        return True
    if _REASONING_MATH.search(normalized) is not None:
        return True
    if "```" in latest_user or latest_user.count("\n") >= 3:
        return True
    return latest_user.count("?") + latest_user.count("？") >= 2


def _requires_hidden_vision_thinking(prompt: str) -> bool:
    normalized = " ".join(prompt.casefold().split())
    if _VISION_REASONING_TERMS.search(normalized) is not None:
        return True
    if _REASONING_MATH.search(normalized) is not None:
        return True
    if "```" in prompt or prompt.count("?") + prompt.count("？") >= 2:
        return True
    return False


def _qwen_no_think_prompt(messages: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for item in messages:
        role = item["role"]
        content = _neutralize_qwen_control_tokens(item["content"])
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>\n")
    # Qwen3-VL Thinking is a separate checkpoint rather than a hybrid switch.
    # Closing the private block in the raw prompt gives simple text requests a
    # same-weight fast path without loading a second Instruct checkpoint.
    parts.append("<|im_start|>assistant\n<think>\n\n</think>\n\n")
    return "".join(parts)


def _qwen_reasoned_prompt(
    messages: list[dict[str, str]],
    thinking: str,
) -> str:
    parts: list[str] = []
    for item in messages:
        role = item["role"]
        content = _neutralize_qwen_control_tokens(item["content"])
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>\n")
    private_scratchpad = _neutralize_qwen_control_tokens(thinking)
    parts.append(
        "<|im_start|>assistant\n"
        f"<think>\n{private_scratchpad}\n</think>\n\n"
    )
    return "".join(parts)


def _neutralize_qwen_control_tokens(value: str) -> str:
    result = value
    for token in _QWEN_CONTROL_TOKENS:
        visible = token.replace("<", "‹").replace(">", "›")
        result = re.sub(re.escape(token), visible, result, flags=re.IGNORECASE)
    return result


def _assert_before_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("model request deadline exceeded")


def _set_remaining_socket_timeout(
    connection: http.client.HTTPConnection,
    deadline: float,
) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("model request deadline exceeded")
    if connection.sock is not None:
        connection.sock.settimeout(max(0.05, remaining))


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


def _bounded_nonnegative_int(value: object) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > 1 << 50
    ):
        return None
    return value
