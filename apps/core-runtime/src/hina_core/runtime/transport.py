from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import ipaddress
import json
import os
import struct
import time
from collections import deque
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID
from uuid import uuid4

from hina_contracts import validate_envelope

from .durable import DurableStore
from .error_log import JsonlErrorLogger, redact_for_log
from .observability import MetricRegistry
from .primitives import PrimitiveError, RuntimeErrorCode


_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_WEBSOCKET_PROTOCOL = "hina.realtime.v1"
_BINARY_HEADER = struct.Struct("!4sBBI16s")
_BINARY_MAGIC = b"HINA"
_BINARY_VERSION = 1
_END_OF_STREAM = 0x01
_ZERO_CORRELATION_ID = "00000000-0000-0000-0000-000000000000"
_MAX_ERROR_LOG_SCAN_BYTES = 4 * 1024 * 1024
_STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/audio-viseme.js": ("audio-viseme.js", "text/javascript; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
_STATIC_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "connect-src 'self' ws://127.0.0.1:* ws://[::1]:*; "
        "img-src 'self' data:; "
        "media-src 'self' blob:; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "microphone=(self)",
}


@dataclass(frozen=True, slots=True)
class TransportConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    max_http_header_bytes: int = 16_384
    max_control_body_bytes: int = 1_048_576
    max_text_frame_bytes: int = 1_114_112
    max_binary_frame_bytes: int = 2_097_152
    max_connections: int = 16
    idle_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError as exc:
            raise PrimitiveError(
                RuntimeErrorCode.NETWORK_BIND_DENIED,
                "control plane host must be a numeric loopback address",
            ) from exc
        if not address.is_loopback:
            raise PrimitiveError(
                RuntimeErrorCode.NETWORK_BIND_DENIED,
                "control plane may bind only to loopback",
            )
        if not 0 <= self.port <= 65_535:
            raise ValueError("port must be between 0 and 65535")
        if not 1_024 <= self.max_http_header_bytes <= 65_536:
            raise ValueError("HTTP header limit must be between 1024 and 65536")
        if not 1_024 <= self.max_control_body_bytes <= 1_048_576:
            raise ValueError("control body limit must be between 1024 and 1048576")
        if not 1_024 <= self.max_text_frame_bytes <= 16 * 1024 * 1024:
            raise ValueError("text frame limit is outside the supported range")
        if not _BINARY_HEADER.size <= self.max_binary_frame_bytes <= 64 * 1024 * 1024:
            raise ValueError("binary frame limit is outside the supported range")
        if not 1 <= self.max_connections <= 1_024:
            raise ValueError("connection limit must be between 1 and 1024")
        if self.idle_timeout_seconds <= 0:
            raise ValueError("idle timeout must be positive")


@dataclass(frozen=True, slots=True)
class BinaryMediaFrame:
    media_id: UUID
    sequence: int
    payload: bytes
    end_of_stream: bool = False

    def encode(self) -> bytes:
        if not 0 <= self.sequence <= 0xFFFF_FFFF:
            raise PrimitiveError(RuntimeErrorCode.MEDIA_INVALID, "media sequence is outside uint32")
        if not isinstance(self.payload, bytes):
            raise PrimitiveError(RuntimeErrorCode.MEDIA_INVALID, "media payload must be bytes")
        flags = _END_OF_STREAM if self.end_of_stream else 0
        return _BINARY_HEADER.pack(
            _BINARY_MAGIC,
            _BINARY_VERSION,
            flags,
            self.sequence,
            self.media_id.bytes,
        ) + self.payload

    @classmethod
    def decode(cls, raw: bytes) -> BinaryMediaFrame:
        if len(raw) < _BINARY_HEADER.size:
            raise PrimitiveError(RuntimeErrorCode.MEDIA_INVALID, "binary media header is truncated")
        magic, version, flags, sequence, media_id = _BINARY_HEADER.unpack_from(raw)
        if magic != _BINARY_MAGIC or version != _BINARY_VERSION:
            raise PrimitiveError(RuntimeErrorCode.MEDIA_INVALID, "binary media magic or version is invalid")
        if flags & ~_END_OF_STREAM:
            raise PrimitiveError(RuntimeErrorCode.MEDIA_INVALID, "binary media flags are invalid")
        return cls(
            media_id=UUID(bytes=media_id),
            sequence=sequence,
            payload=raw[_BINARY_HEADER.size :],
            end_of_stream=bool(flags & _END_OF_STREAM),
        )


@dataclass(frozen=True, slots=True)
class _HttpRequest:
    method: str
    target: str
    version: str
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class _WebSocketFrame:
    opcode: int
    payload: bytes


class ControlPlaneServer:
    def __init__(
        self,
        config: TransportConfig,
        *,
        durable_store: DurableStore | None = None,
        error_logger: JsonlErrorLogger | None = None,
        metrics: MetricRegistry | None = None,
        static_dir: Path | None = None,
        safety_policy: Any | None = None,
        model_gateway: Any | None = None,
        conversation_service: Any | None = None,
        speech_service: Any | None = None,
        tts_service: Any | None = None,
        memory_service: Any | None = None,
        avatar_service: Any | None = None,
        build_commit: str | None = None,
    ) -> None:
        self.config = config
        self.durable_store = durable_store
        self.error_logger = error_logger
        self.metrics = metrics or MetricRegistry()
        self.static_dir = static_dir.resolve() if static_dir is not None else None
        self.safety_policy = safety_policy
        self.model_gateway = model_gateway
        self.conversation_service = conversation_service
        self.speech_service = speech_service
        self.tts_service = tts_service
        self.memory_service = memory_service
        self.avatar_service = avatar_service
        self.build_commit = build_commit or os.environ.get("HINA_BUILD_COMMIT", "development")
        self._server: asyncio.AbstractServer | None = None
        self._started_at = 0.0
        self._active_connections = 0
        self._writers: set[asyncio.StreamWriter] = set()

    @property
    def address(self) -> tuple[str, int]:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("control plane is not running")
        host, port = self._server.sockets[0].getsockname()[:2]
        return str(host), int(port)

    @property
    def active_connections(self) -> int:
        return self._active_connections

    async def __aenter__(self) -> ControlPlaneServer:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()

    async def start(self) -> tuple[str, int]:
        if self._server is not None:
            return self.address
        self._server = await asyncio.start_server(
            self._handle_connection,
            host=self.config.host,
            port=self.config.port,
            limit=self.config.max_http_header_bytes + 4,
        )
        self._started_at = time.monotonic()
        return self.address

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.close()
            await server.wait_closed()
        writers = tuple(self._writers)
        for writer in writers:
            writer.close()
        if writers:
            await asyncio.gather(
                *(writer.wait_closed() for writer in writers),
                return_exceptions=True,
            )
        self._writers.clear()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = self._peer_name(writer)
        if self._active_connections >= self.config.max_connections:
            await self._send_json_response(
                writer,
                HTTPStatus.SERVICE_UNAVAILABLE,
                self._error_body(RuntimeErrorCode.CONNECTION_LIMIT, "connection limit reached"),
            )
            writer.close()
            await writer.wait_closed()
            return

        self._active_connections += 1
        self._writers.add(writer)
        upgraded = False
        try:
            request = await self._read_http_request(reader)
            if self._is_websocket_upgrade(request):
                self._validate_websocket_handshake(request)
                upgraded = True
                await self._serve_websocket(reader, writer, request, peer)
            else:
                await self._serve_control_request(writer, request)
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
            pass
        except PrimitiveError as exc:
            self._log_error(exc, "connection", peer=peer)
            if not upgraded and not writer.is_closing():
                await self._send_json_response(
                    writer,
                    self._http_status_for(exc.code),
                    self._error_body(exc.code, exc.detail),
                )
        except Exception as exc:
            wrapped = PrimitiveError(RuntimeErrorCode.OPERATION_FAILED, "unexpected transport failure")
            self._log_error(wrapped, "connection", peer=peer, exception=exc)
            if not upgraded and not writer.is_closing():
                await self._send_json_response(
                    writer,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    self._error_body(wrapped.code, wrapped.detail),
                )
        finally:
            self._writers.discard(writer)
            self._active_connections -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, TimeoutError):
                pass

    async def _read_http_request(self, reader: asyncio.StreamReader) -> _HttpRequest:
        try:
            raw = await asyncio.wait_for(
                reader.readuntil(b"\r\n\r\n"),
                timeout=self.config.idle_timeout_seconds,
            )
        except asyncio.LimitOverrunError as exc:
            raise PrimitiveError(RuntimeErrorCode.FRAME_TOO_LARGE, "HTTP headers exceed limit") from exc
        if len(raw) > self.config.max_http_header_bytes:
            raise PrimitiveError(RuntimeErrorCode.FRAME_TOO_LARGE, "HTTP headers exceed limit")
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise PrimitiveError(RuntimeErrorCode.HTTP_BAD_REQUEST, "HTTP headers must be ASCII") from exc
        lines = text[:-4].split("\r\n")
        if not lines or len(lines[0].split(" ")) != 3:
            raise PrimitiveError(RuntimeErrorCode.HTTP_BAD_REQUEST, "malformed HTTP request line")
        method, target, version = lines[0].split(" ")
        if version != "HTTP/1.1" or not target.startswith("/"):
            raise PrimitiveError(RuntimeErrorCode.HTTP_BAD_REQUEST, "unsupported HTTP request")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            name, separator, value = line.partition(":")
            normalized = name.strip().lower()
            if not separator or not normalized or normalized in headers:
                raise PrimitiveError(RuntimeErrorCode.HTTP_BAD_REQUEST, "malformed or duplicate HTTP header")
            headers[normalized] = value.strip()
        try:
            content_length = int(headers.get("content-length", "0") or "0")
        except ValueError as exc:
            raise PrimitiveError(RuntimeErrorCode.HTTP_BAD_REQUEST, "Content-Length is invalid") from exc
        if content_length < 0:
            raise PrimitiveError(RuntimeErrorCode.HTTP_BAD_REQUEST, "Content-Length is invalid")
        if "transfer-encoding" in headers:
            raise PrimitiveError(RuntimeErrorCode.HTTP_BAD_REQUEST, "Transfer-Encoding is not supported")
        if content_length > self.config.max_control_body_bytes:
            raise PrimitiveError(RuntimeErrorCode.FRAME_TOO_LARGE, "control request body exceeds limit")
        body = (
            await asyncio.wait_for(
                reader.readexactly(content_length),
                timeout=self.config.idle_timeout_seconds,
            )
            if content_length
            else b""
        )
        return _HttpRequest(
            method=method,
            target=target,
            version=version,
            headers=headers,
            body=body,
        )

    async def _serve_control_request(self, writer: asyncio.StreamWriter, request: _HttpRequest) -> None:
        parsed_target = urlsplit(request.target)
        path = parsed_target.path
        if request.method not in {"GET", "POST"}:
            self._record_metric("hina_http_requests_total", operation="method_rejected", status="error")
            await self._send_json_response(
                writer,
                HTTPStatus.METHOD_NOT_ALLOWED,
                self._error_body(RuntimeErrorCode.HTTP_BAD_REQUEST, "only GET and POST are supported"),
                extra_headers={"Allow": "GET, POST"},
            )
            return
        if request.method == "GET" and request.body:
            raise PrimitiveError(RuntimeErrorCode.HTTP_BAD_REQUEST, "GET request body is not supported")
        if request.method == "GET" and path in _STATIC_FILES and self.static_dir is not None:
            self._record_metric("hina_http_requests_total", operation="static", status="ok")
            await self._serve_static_file(writer, path)
            return
        if request.method == "POST" and path == "/v1/speech/transcriptions":
            await self._serve_speech_transcription(writer, request)
            return
        if request.method == "POST" and path == "/v1/tts/synthesis":
            await self._serve_tts_synthesis(writer, request)
            return
        tts_cancel_id = _tts_cancel_route(path)
        if request.method == "POST" and tts_cancel_id is not None:
            await self._serve_tts_cancel(writer, request, tts_cancel_id)
            return

        body: dict[str, Any]
        if request.method == "POST":
            body = await self._serve_post(path, request)
        elif path == "/v1/health":
            body = {
                "status": "ready",
                "service": "hina-core-runtime",
                "uptimeSeconds": round(max(0.0, time.monotonic() - self._started_at), 3),
                "activeConnections": self._active_connections,
            }
        elif path == "/v1/version":
            body = {
                "service": "hina-core-runtime",
                "buildCommit": self.build_commit,
                "controlApi": "v1",
                "realtimeProtocol": _WEBSOCKET_PROTOCOL,
                "binaryMediaVersion": _BINARY_VERSION,
            }
        elif path == "/v1/config":
            body = {
                "host": self.config.host,
                "port": self.address[1],
                "loopbackOnly": True,
                "limits": {
                    "httpHeaderBytes": self.config.max_http_header_bytes,
                    "controlBodyBytes": self.config.max_control_body_bytes,
                    "textFrameBytes": self.config.max_text_frame_bytes,
                    "binaryFrameBytes": self.config.max_binary_frame_bytes,
                    "connections": self.config.max_connections,
                },
            }
        elif path == "/v1/metrics":
            body = self.metrics.as_json()
        elif path == "/v1/errors":
            limit = _parse_error_limit(parsed_target.query)
            records = (
                _read_recent_error_records(self.error_logger.path, limit)
                if self.error_logger is not None
                else []
            )
            body = {
                "records": records,
                "count": len(records),
                "limit": limit,
            }
        elif path == "/v1/safety/status":
            body = self._safety_call("status")
        elif path == "/v1/safety/audit":
            limit = _parse_safety_audit_limit(parsed_target.query)
            body = self._safety_call("recent_audit", limit)
        elif path == "/v1/model/status":
            if self.model_gateway is None:
                raise PrimitiveError(
                    RuntimeErrorCode.OPERATION_FAILED,
                    "model gateway is unavailable",
                )
            body = await self.model_gateway.status()
        elif path == "/v1/chat/status":
            body = await self._chat_call("status")
        elif path == "/v1/speech/status":
            body = await self._speech_status()
        elif path == "/v1/tts/status":
            body = await self._tts_status()
        elif path == "/v1/memory/status":
            body = await self._memory_call("status")
        elif path == "/v1/avatar/status":
            body = self._avatar_call("status")
        elif path == "/v1/memory/candidates":
            status = _parse_memory_candidate_query(parsed_target.query)
            body = await self._memory_call("candidates", status=status)
        elif path == "/v1/memory/records":
            _require_empty_query(parsed_target.query)
            body = await self._memory_call("records")
        elif path == "/v1/memory/search":
            query, limit = _parse_memory_search_query(parsed_target.query)
            body = await self._memory_call("search", query, limit=limit)
        elif path == "/v1/memory/export":
            _require_empty_query(parsed_target.query)
            body = await self._memory_call("export")
        elif _chat_route(path, "turns"):
            body = await self._chat_call("get_turn", _chat_route(path, "turns"))
        elif _chat_route(path, "sessions"):
            body = await self._chat_call("replay", _chat_route(path, "sessions"))
        else:
            self._record_metric("hina_http_requests_total", operation="not_found", status="error")
            await self._send_json_response(
                writer,
                HTTPStatus.NOT_FOUND,
                self._error_body(RuntimeErrorCode.HTTP_BAD_REQUEST, "route was not found"),
            )
            return
        self._record_metric("hina_http_requests_total", operation=path[4:], status="ok")
        await self._send_json_response(writer, HTTPStatus.OK, body)

    async def _serve_post(self, path: str, request: _HttpRequest) -> dict[str, Any]:
        if path.startswith("/v1/safety/"):
            body_error = RuntimeErrorCode.SAFETY_BAD_REQUEST
        elif path.startswith("/v1/chat/"):
            body_error = RuntimeErrorCode.CHAT_BAD_REQUEST
        else:
            body_error = RuntimeErrorCode.HTTP_BAD_REQUEST
        payload = _parse_json_body(request, error_code=body_error)
        if path == "/v1/safety/evaluate":
            return self._safety_call("evaluate", payload)
        if path == "/v1/safety/control":
            return self._safety_call("apply_control", payload)
        if path == "/v1/safety/sanitize":
            return self._safety_call("sanitize_input", payload)
        if path == "/v1/safety/context":
            return self._safety_call("create_context", payload)
        if path == "/v1/safety/moderate":
            return self._safety_call("moderate", payload)
        if path == "/v1/chat/turns":
            return await self._chat_call("start_turn", payload)
        if path == "/v1/avatar/cues":
            if payload.get("source") not in {"owner.console", "speech.output"}:
                raise PrimitiveError(  # type: ignore[arg-type]
                    "E_AVATAR_SOURCE",
                    "external avatar cues require an owner or observed speech source",
                )
            return self._avatar_call("apply_cue", payload)
        if path == "/v1/avatar/reset":
            if payload != {"action": "reset"}:
                raise PrimitiveError(
                    RuntimeErrorCode.AVATAR_BAD_REQUEST,
                    "avatar reset request is invalid",
                )
            return self._avatar_call("reset")
        if path == "/v1/memory/candidates":
            return await self._memory_call("propose", payload)
        candidate_id = _memory_item_route(path, "candidates", "decision")
        if candidate_id is not None:
            return await self._memory_call("decide", candidate_id, payload)
        for suffix, operation in (
            ("correct", "correct"),
            ("pin", "set_pinned"),
            ("delete", "delete"),
        ):
            memory_id = _memory_item_route(path, "records", suffix)
            if memory_id is not None:
                return await self._memory_call(operation, memory_id, payload)
        if path == "/v1/memory/rebuild":
            if payload != {"action": "rebuild"}:
                raise PrimitiveError(
                    RuntimeErrorCode.HTTP_BAD_REQUEST,
                    "memory rebuild request is invalid",
                )
            return await self._memory_call("rebuild")
        turn_id = _chat_route(path, "turns", suffix="cancel")
        if turn_id is not None:
            if payload:
                raise PrimitiveError(
                    RuntimeErrorCode.CHAT_BAD_REQUEST,
                    "cancel request body must be empty",
                )
            return await self._chat_call("cancel_turn", turn_id)
        session_id = _chat_route(path, "sessions", suffix="clear")
        if session_id is not None:
            if payload != {"action": "clear"}:
                raise PrimitiveError(
                    RuntimeErrorCode.CHAT_BAD_REQUEST,
                    "clear request body is invalid",
                )
            return await self._chat_call("clear_session", session_id)
        raise PrimitiveError(RuntimeErrorCode.HTTP_BAD_REQUEST, "POST route was not found")

    async def _speech_status(self) -> dict[str, Any]:
        if self.speech_service is None:
            raise PrimitiveError(
                RuntimeErrorCode.OPERATION_FAILED,
                "speech input service is unavailable",
            )
        result = await self.speech_service.status()
        if not isinstance(result, dict):
            raise PrimitiveError(
                RuntimeErrorCode.OPERATION_FAILED,
                "speech input service returned invalid status",
            )
        return result

    async def _serve_speech_transcription(
        self,
        writer: asyncio.StreamWriter,
        request: _HttpRequest,
    ) -> None:
        correlation_id = request.headers.get("x-hina-correlation-id") or str(uuid4())
        session_id = request.headers.get("x-hina-session-id") or None
        source = request.headers.get("x-hina-source", "owner.dev-console")
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in {"audio/wav", "audio/x-wav"}:
            self._log_speech_request_error(
                "E_AUDIO_CONTENT_TYPE",
                correlation_id,
                session_id,
                len(request.body),
            )
            await self._send_json_response(
                writer,
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {
                    "status": "error",
                    "errorCode": "E_AUDIO_CONTENT_TYPE",
                    "message": "speech transcription requires an audio/wav body",
                    "correlationId": correlation_id,
                },
            )
            return
        if not request.body:
            self._log_speech_request_error(
                "E_AUDIO_EMPTY",
                correlation_id,
                session_id,
                0,
            )
            await self._send_json_response(
                writer,
                HTTPStatus.BAD_REQUEST,
                {
                    "status": "error",
                    "errorCode": "E_AUDIO_EMPTY",
                    "message": "WAV audio body is empty",
                    "correlationId": correlation_id,
                },
            )
            return
        if self.speech_service is None:
            self._log_speech_request_error(
                "E_STT_UNAVAILABLE",
                correlation_id,
                session_id,
                len(request.body),
            )
            await self._send_json_response(
                writer,
                HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "status": "error",
                    "errorCode": "E_STT_UNAVAILABLE",
                    "message": "speech input service is unavailable",
                    "correlationId": correlation_id,
                },
            )
            return
        try:
            body = await self.speech_service.transcribe_wav(
                request.body,
                correlation_id=correlation_id,
                session_id=session_id,
                source=source,
            )
        except Exception as exc:
            code = getattr(exc, "code", "")
            if not isinstance(code, str) or not (
                code.startswith("E_AUDIO_") or code.startswith("E_STT_")
            ):
                raise
            if code == "E_STT_QUEUE_FULL":
                status = HTTPStatus.TOO_MANY_REQUESTS
            elif code in {
                "E_STT_UNAVAILABLE",
                "E_STT_DRAINING",
                "E_STT_MODEL_LOAD",
                "E_STT_INFERENCE",
                "E_STT_TIMEOUT",
                "E_STT_RESOURCE_LEASE",
                "E_STT_OPERATION",
            }:
                status = HTTPStatus.SERVICE_UNAVAILABLE
            else:
                status = HTTPStatus.BAD_REQUEST
            if not getattr(exc, "reported", False):
                self._log_speech_request_error(
                    code,
                    correlation_id,
                    session_id,
                    len(request.body),
                )
            self._record_metric(
                "hina_http_requests_total",
                operation="speech/transcriptions",
                status="error",
            )
            await self._send_json_response(
                writer,
                status,
                {
                    "status": "error",
                    "errorCode": code,
                    "message": getattr(exc, "detail", "speech request failed")[:256],
                    "correlationId": correlation_id,
                },
            )
            return
        self._record_metric(
            "hina_http_requests_total",
            operation="speech/transcriptions",
            status="ok",
        )
        await self._send_json_response(writer, HTTPStatus.OK, body)

    async def _tts_status(self) -> dict[str, Any]:
        if self.tts_service is None:
            return {
                "available": False,
                "errorCode": "E_TTS_UNAVAILABLE",
                "message": "speech output service requires the safety policy",
            }
        result = await self.tts_service.status()
        if not isinstance(result, dict):
            raise PrimitiveError(
                RuntimeErrorCode.OPERATION_FAILED,
                "speech output service returned invalid status",
            )
        return result

    async def _serve_tts_synthesis(
        self,
        writer: asyncio.StreamWriter,
        request: _HttpRequest,
    ) -> None:
        correlation_id = request.headers.get("x-hina-correlation-id") or str(uuid4())
        payload = _parse_json_body(request, error_code=RuntimeErrorCode.HTTP_BAD_REQUEST)
        expected = {"text", "utteranceId", "sessionId", "source"}
        if set(payload) != expected:
            await self._send_tts_error(
                writer,
                HTTPStatus.BAD_REQUEST,
                "E_TTS_REQUEST",
                "TTS request fields are invalid",
                correlation_id,
                None,
                None,
            )
            return
        utterance_id = payload.get("utteranceId")
        session_id = payload.get("sessionId")
        source = payload.get("source")
        if (
            not isinstance(utterance_id, str)
            or (session_id is not None and not isinstance(session_id, str))
            or not isinstance(source, str)
        ):
            await self._send_tts_error(
                writer,
                HTTPStatus.BAD_REQUEST,
                "E_TTS_REQUEST",
                "TTS request identifiers are invalid",
                correlation_id,
                utterance_id if isinstance(utterance_id, str) else None,
                session_id if isinstance(session_id, str) else None,
            )
            return
        if self.tts_service is None:
            await self._send_tts_error(
                writer,
                HTTPStatus.SERVICE_UNAVAILABLE,
                "E_TTS_UNAVAILABLE",
                "speech output service is unavailable",
                correlation_id,
                utterance_id,
                session_id,
            )
            return
        try:
            result = await self.tts_service.synthesize(
                payload.get("text"),
                utterance_id=utterance_id,
                correlation_id=correlation_id,
                session_id=session_id,
                source=source,
            )
        except Exception as exc:
            code = getattr(exc, "code", "")
            if not isinstance(code, str) or not code.startswith("E_TTS_"):
                raise
            if code == "E_TTS_QUEUE_FULL":
                status = HTTPStatus.TOO_MANY_REQUESTS
            elif code == "E_TTS_CONFLICT":
                status = HTTPStatus.CONFLICT
            elif code == "E_TTS_BLOCKED":
                status = HTTPStatus.FORBIDDEN
            elif code in {
                "E_TTS_UNAVAILABLE",
                "E_TTS_DRAINING",
                "E_TTS_MODEL_LOAD",
                "E_TTS_INFERENCE",
                "E_TTS_TIMEOUT",
                "E_TTS_RESOURCE_LEASE",
                "E_TTS_OPERATION",
            }:
                status = HTTPStatus.SERVICE_UNAVAILABLE
            else:
                status = HTTPStatus.BAD_REQUEST
            if not getattr(exc, "reported", False):
                self._log_tts_request_error(
                    code,
                    correlation_id,
                    utterance_id,
                    session_id,
                )
            await self._send_tts_error(
                writer,
                status,
                code,
                getattr(exc, "detail", "TTS request failed"),
                correlation_id,
                utterance_id,
                session_id,
                log_error=False,
            )
            return
        wav = result.pop("audioWav", None)
        if not isinstance(wav, bytes) or not wav.startswith(b"RIFF"):
            raise PrimitiveError(
                RuntimeErrorCode.OPERATION_FAILED,
                "speech output service returned invalid audio",
            )
        self._record_metric(
            "hina_http_requests_total",
            operation="tts/synthesis",
            status="ok",
        )
        alignment = [
            event["payload"]
            for event in result.get("events", [])
            if isinstance(event, dict)
            and event.get("type") == "AudioAlignment"
            and isinstance(event.get("payload"), dict)
        ]
        await self._send_response(
            writer,
            HTTPStatus.OK,
            wav,
            content_type="audio/wav",
            extra_headers={
                "X-Hina-Utterance-Id": utterance_id,
                "X-Hina-Correlation-Id": correlation_id,
                "X-Hina-Duration-Milliseconds": str(
                    round(float(result.get("durationSeconds", 0)) * 1_000)
                ),
                "X-Hina-First-Chunk-Milliseconds": str(
                    result.get("firstChunkMilliseconds", 0)
                ),
                "X-Hina-Processing-Milliseconds": str(
                    result.get("processingMilliseconds", 0)
                ),
                "X-Hina-Event-Count": str(len(result.get("events", []))),
                "X-Hina-Alignment": json.dumps(
                    alignment,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
            },
        )

    async def _serve_tts_cancel(
        self,
        writer: asyncio.StreamWriter,
        request: _HttpRequest,
        utterance_id: str,
    ) -> None:
        correlation_id = request.headers.get("x-hina-correlation-id") or str(uuid4())
        try:
            payload = _parse_json_body(request, error_code=RuntimeErrorCode.HTTP_BAD_REQUEST)
            if payload:
                raise PrimitiveError(
                    RuntimeErrorCode.HTTP_BAD_REQUEST,
                    "TTS cancel request body must be empty",
                )
            if self.tts_service is None:
                raise PrimitiveError(
                    RuntimeErrorCode.OPERATION_FAILED,
                    "speech output service is unavailable",
                )
            result = await self.tts_service.cancel(utterance_id)
        except Exception as exc:
            code = getattr(exc, "code", "")
            if isinstance(code, str) and code.startswith("E_TTS_"):
                await self._send_tts_error(
                    writer,
                    HTTPStatus.BAD_REQUEST,
                    code,
                    getattr(exc, "detail", "TTS cancel failed"),
                    correlation_id,
                    utterance_id,
                    None,
                )
                return
            raise
        self._record_metric(
            "hina_http_requests_total",
            operation="tts/cancel",
            status="ok",
        )
        await self._send_json_response(writer, HTTPStatus.OK, result)

    async def _send_tts_error(
        self,
        writer: asyncio.StreamWriter,
        status: HTTPStatus,
        code: str,
        message: str,
        correlation_id: str,
        utterance_id: str | None,
        session_id: str | None,
        *,
        log_error: bool = True,
    ) -> None:
        if log_error:
            self._log_tts_request_error(
                code,
                correlation_id,
                utterance_id,
                session_id,
            )
        self._record_metric(
            "hina_http_requests_total",
            operation="tts/synthesis",
            status="error",
        )
        await self._send_json_response(
            writer,
            status,
            {
                "status": "error",
                "errorCode": code,
                "message": message[:256],
                "correlationId": correlation_id,
                "utteranceId": utterance_id,
            },
        )

    def _log_tts_request_error(
        self,
        code: str,
        correlation_id: str,
        utterance_id: str | None,
        session_id: str | None,
    ) -> None:
        if self.error_logger is None:
            return
        self.error_logger.log_error(
            PrimitiveError(code, "speech output request failed"),  # type: ignore[arg-type]
            component="speech.output",
            operation="synthesize",
            correlation_id=correlation_id,
            session_id=session_id,
            context={
                "utteranceId": utterance_id,
                "generatedAudioRetained": False,
                "inputTextRetained": False,
            },
        )

    def _log_speech_request_error(
        self,
        code: str,
        correlation_id: str,
        session_id: str | None,
        audio_bytes: int,
    ) -> None:
        if self.error_logger is None:
            return
        self.error_logger.log_error(
            PrimitiveError(code, "speech input request failed"),  # type: ignore[arg-type]
            component="speech.input",
            operation="transcribe",
            correlation_id=correlation_id,
            session_id=session_id,
            context={
                "audioBytes": audio_bytes,
                "rawAudioRetained": False,
            },
        )

    def _safety_call(self, operation: str, *args: Any) -> dict[str, Any]:
        if self.safety_policy is None:
            raise PrimitiveError(RuntimeErrorCode.SAFETY_UNAVAILABLE, "safety policy is unavailable")
        try:
            result = getattr(self.safety_policy, operation)(*args)
        except Exception as exc:
            code = getattr(exc, "code", "")
            if not isinstance(code, str) or not (
                code.startswith("E_SAFETY_") or code == "E_CONTEXT_BOUNDARY"
            ):
                raise
            unavailable = code in {
                "E_SAFETY_AUDIT_INVALID",
                "E_SAFETY_AUDIT_UNAVAILABLE",
                "E_SAFETY_MANIFEST_INVALID",
            }
            raise PrimitiveError(
                RuntimeErrorCode.SAFETY_UNAVAILABLE if unavailable else RuntimeErrorCode.SAFETY_BAD_REQUEST,
                getattr(exc, "detail", "safety policy rejected the request"),
            ) from exc
        if not isinstance(result, dict):
            raise PrimitiveError(RuntimeErrorCode.SAFETY_UNAVAILABLE, "safety policy returned invalid data")
        return result

    async def _chat_call(self, operation: str, *args: Any) -> dict[str, Any]:
        if self.conversation_service is None:
            raise PrimitiveError(
                RuntimeErrorCode.CHAT_UNAVAILABLE,
                "conversation service is unavailable",
            )
        try:
            result = await getattr(self.conversation_service, operation)(*args)
        except Exception as exc:
            code = getattr(exc, "code", "")
            if code == "E_TURN_NOT_FOUND":
                runtime_code = RuntimeErrorCode.CHAT_NOT_FOUND
            elif code == "E_TURN_ACTIVE":
                runtime_code = RuntimeErrorCode.CHAT_CONFLICT
            elif isinstance(code, str) and (
                code.startswith("E_CHAT_")
                or code.startswith("E_TURN_")
                or code.startswith("E_CONTEXT_")
                or code.startswith("E_PERSONA_")
            ):
                runtime_code = RuntimeErrorCode.CHAT_BAD_REQUEST
            else:
                raise
            raise PrimitiveError(
                runtime_code,
                getattr(exc, "detail", "conversation request was rejected"),
            ) from exc
        if not isinstance(result, dict):
            raise PrimitiveError(
                RuntimeErrorCode.CHAT_UNAVAILABLE,
                "conversation service returned invalid data",
            )
        return result

    async def _memory_call(
        self,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self.memory_service is None:
            raise PrimitiveError(
                "E_MEMORY_UNAVAILABLE",  # type: ignore[arg-type]
                "long-term memory service is unavailable",
            )
        try:
            result = await getattr(self.memory_service, operation)(*args, **kwargs)
        except Exception as exc:
            code = getattr(exc, "code", "")
            if not isinstance(code, str) or not code.startswith("E_MEMORY_"):
                raise
            raise PrimitiveError(  # type: ignore[arg-type]
                code,
                getattr(exc, "detail", "memory request was rejected"),
            ) from exc
        if not isinstance(result, dict):
            raise PrimitiveError(
                "E_MEMORY_UNAVAILABLE",  # type: ignore[arg-type]
                "long-term memory service returned invalid data",
            )
        return result

    def _avatar_call(self, operation: str, *args: Any) -> dict[str, Any]:
        if self.avatar_service is None:
            raise PrimitiveError(
                RuntimeErrorCode.AVATAR_UNAVAILABLE,
                "avatar stage service is unavailable",
            )
        try:
            result = getattr(self.avatar_service, operation)(*args)
        except Exception as exc:
            code = getattr(exc, "code", "")
            if not isinstance(code, str) or not code.startswith("E_AVATAR_"):
                raise
            raise PrimitiveError(  # type: ignore[arg-type]
                code,
                getattr(exc, "detail", "avatar cue was rejected"),
            ) from exc
        if not isinstance(result, dict):
            raise PrimitiveError(
                RuntimeErrorCode.AVATAR_UNAVAILABLE,
                "avatar stage service returned invalid data",
            )
        return result

    async def _serve_static_file(self, writer: asyncio.StreamWriter, route: str) -> None:
        assert self.static_dir is not None
        filename, content_type = _STATIC_FILES[route]
        path = self.static_dir / filename
        try:
            encoded = path.read_bytes()
        except OSError:
            await self._send_json_response(
                writer,
                HTTPStatus.NOT_FOUND,
                self._error_body(RuntimeErrorCode.HTTP_BAD_REQUEST, "console asset was not found"),
            )
            return
        if len(encoded) > 1_048_576:
            raise PrimitiveError(RuntimeErrorCode.FRAME_TOO_LARGE, "console asset exceeds size limit")
        await self._send_response(
            writer,
            HTTPStatus.OK,
            encoded,
            content_type=content_type,
            extra_headers=_STATIC_SECURITY_HEADERS,
        )

    async def _serve_websocket(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        request: _HttpRequest,
        peer: str,
    ) -> None:
        key = request.headers["sec-websocket-key"]
        accept = base64.b64encode(
            hashlib.sha1(f"{key}{_WEBSOCKET_GUID}".encode("ascii")).digest()
        ).decode("ascii")
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            f"Sec-WebSocket-Protocol: {_WEBSOCKET_PROTOCOL}\r\n"
            "\r\n"
        )
        writer.write(response.encode("ascii"))
        await self._drain(writer)

        awaiting_pong = False
        while not writer.is_closing():
            try:
                try:
                    frame = await self._read_websocket_frame(reader)
                except TimeoutError:
                    if awaiting_pong:
                        raise PrimitiveError(
                            RuntimeErrorCode.WEBSOCKET_PROTOCOL,
                            "WebSocket peer did not answer the keepalive ping",
                        )
                    await self._write_websocket_frame(writer, 0x9, b"hina")
                    awaiting_pong = True
                    continue
                if frame.opcode == 0x1:
                    awaiting_pong = False
                    response_body = self._handle_text_message(frame.payload)
                    encoded_response = json.dumps(
                        response_body,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                    if len(encoded_response) > self.config.max_text_frame_bytes:
                        raise PrimitiveError(
                            RuntimeErrorCode.FRAME_TOO_LARGE,
                            "realtime response exceeds configured text limit",
                        )
                    await self._write_websocket_frame(
                        writer,
                        0x1,
                        encoded_response,
                    )
                elif frame.opcode == 0x2:
                    awaiting_pong = False
                    media = BinaryMediaFrame.decode(frame.payload)
                    self._record_metric(
                        "hina_realtime_messages_total",
                        operation="binary",
                        status="ok",
                    )
                    await self._write_websocket_frame(writer, 0x2, media.encode())
                elif frame.opcode == 0x8:
                    await self._write_websocket_frame(writer, 0x8, frame.payload[:125])
                    return
                elif frame.opcode == 0x9:
                    awaiting_pong = False
                    await self._write_websocket_frame(writer, 0xA, frame.payload)
                elif frame.opcode == 0xA:
                    awaiting_pong = False
                    continue
                else:
                    raise PrimitiveError(RuntimeErrorCode.WEBSOCKET_PROTOCOL, "unsupported WebSocket opcode")
            except PrimitiveError as exc:
                self._record_metric(
                    "hina_realtime_messages_total",
                    operation="message",
                    status="error",
                )
                self._log_error(exc, "websocket_message", peer=peer)
                if exc.code in {
                    RuntimeErrorCode.EVENT_REJECTED,
                    RuntimeErrorCode.MEDIA_INVALID,
                }:
                    await self._write_websocket_frame(
                        writer,
                        0x1,
                        json.dumps(
                            self._error_body(exc.code, exc.detail),
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode("utf-8"),
                    )
                    continue
                await self._write_websocket_close(writer, exc.code)
                return

    def _handle_text_message(self, raw: bytes) -> dict[str, Any]:
        try:
            message = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise PrimitiveError(RuntimeErrorCode.EVENT_REJECTED, "realtime message is invalid JSON") from exc
        if not isinstance(message, dict):
            raise PrimitiveError(RuntimeErrorCode.EVENT_REJECTED, "realtime message must be an object")
        kind = message.get("kind")
        if kind == "event":
            if set(message) != {"kind", "envelope"}:
                raise PrimitiveError(RuntimeErrorCode.EVENT_REJECTED, "event message fields are invalid")
            result = validate_envelope(message["envelope"])
            if not result.ok or result.canonical_json is None:
                raise PrimitiveError(RuntimeErrorCode.EVENT_REJECTED, f"event validation failed: {result.code}")
            envelope = json.loads(result.canonical_json)
            durable = all(
                envelope.get(field) is not None
                for field in ("streamId", "sequence", "idempotencyKey")
            )
            deduplicated = False
            if durable:
                if self.durable_store is None:
                    raise PrimitiveError(RuntimeErrorCode.EVENT_REJECTED, "durable store is unavailable")
                deduplicated = self.durable_store.append_outbox(envelope).deduplicated
            self._record_metric(
                "hina_realtime_messages_total",
                operation="event",
                status="ok",
            )
            return {
                "kind": "event.accepted",
                "eventId": envelope["eventId"],
                "durable": durable,
                "deduplicated": deduplicated,
            }
        if kind == "resume":
            if set(message) != {"kind", "streamId", "afterSequence"}:
                raise PrimitiveError(RuntimeErrorCode.EVENT_REJECTED, "resume message fields are invalid")
            stream_id = message["streamId"]
            after_sequence = message["afterSequence"]
            if (
                not isinstance(stream_id, str)
                or not stream_id
                or len(stream_id) > 128
                or isinstance(after_sequence, bool)
                or not isinstance(after_sequence, int)
                or after_sequence < -1
                or any(ord(char) < 0x20 or ord(char) == 0x7F for char in stream_id)
            ):
                raise PrimitiveError(RuntimeErrorCode.EVENT_REJECTED, "resume cursor is invalid")
            if self.durable_store is None:
                raise PrimitiveError(RuntimeErrorCode.EVENT_REJECTED, "durable store is unavailable")
            candidates = self.durable_store.replay_journal(
                stream_id,
                after_sequence=after_sequence,
                limit=33,
            )
            events = []
            used_bytes = 512
            response_budget = self.config.max_text_frame_bytes - 2_048
            for event in candidates[:32]:
                event_bytes = len(event.canonical_json.encode("utf-8")) + 1
                if used_bytes + event_bytes > response_budget:
                    break
                events.append(event)
                used_bytes += event_bytes
            next_sequence = events[-1].sequence if events else after_sequence
            self._record_metric(
                "hina_realtime_messages_total",
                operation="resume",
                status="ok",
            )
            return {
                "kind": "resume.events",
                "streamId": stream_id,
                "afterSequence": after_sequence,
                "events": [event.envelope for event in events],
                "nextSequence": next_sequence,
                "hasMore": len(events) < len(candidates),
            }
        raise PrimitiveError(RuntimeErrorCode.EVENT_REJECTED, "realtime message kind is unknown")

    async def _read_websocket_frame(self, reader: asyncio.StreamReader) -> _WebSocketFrame:
        async with asyncio.timeout(self.config.idle_timeout_seconds):
            return await self._read_websocket_frame_within_timeout(reader)

    async def _read_websocket_frame_within_timeout(
        self,
        reader: asyncio.StreamReader,
    ) -> _WebSocketFrame:
        try:
            first, second = await reader.readexactly(2)
        except asyncio.IncompleteReadError:
            raise
        fin = bool(first & 0x80)
        reserved = first & 0x70
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if not fin or reserved:
            raise PrimitiveError(RuntimeErrorCode.WEBSOCKET_PROTOCOL, "fragmented or reserved frame is unsupported")
        if not masked:
            raise PrimitiveError(RuntimeErrorCode.WEBSOCKET_PROTOCOL, "client WebSocket frame must be masked")
        if length == 126:
            length = struct.unpack("!H", await reader.readexactly(2))[0]
        elif length == 127:
            raw_length = await reader.readexactly(8)
            if raw_length[0] & 0x80:
                raise PrimitiveError(RuntimeErrorCode.WEBSOCKET_PROTOCOL, "WebSocket length is invalid")
            length = struct.unpack("!Q", raw_length)[0]
        if opcode >= 0x8 and length > 125:
            raise PrimitiveError(RuntimeErrorCode.WEBSOCKET_PROTOCOL, "control frame is too large")
        limit = (
            self.config.max_binary_frame_bytes
            if opcode == 0x2
            else self.config.max_text_frame_bytes
        )
        if length > limit:
            raise PrimitiveError(RuntimeErrorCode.FRAME_TOO_LARGE, "WebSocket frame exceeds configured limit")
        mask = await reader.readexactly(4)
        payload = bytearray(await reader.readexactly(length))
        for index in range(length):
            payload[index] ^= mask[index % 4]
        return _WebSocketFrame(opcode=opcode, payload=bytes(payload))

    async def _write_websocket_frame(
        self,
        writer: asyncio.StreamWriter,
        opcode: int,
        payload: bytes,
    ) -> None:
        first = 0x80 | opcode
        length = len(payload)
        if length < 126:
            header = bytes((first, length))
        elif length <= 0xFFFF:
            header = bytes((first, 126)) + struct.pack("!H", length)
        else:
            header = bytes((first, 127)) + struct.pack("!Q", length)
        writer.write(header + payload)
        await self._drain(writer)

    async def _write_websocket_close(
        self,
        writer: asyncio.StreamWriter,
        code: RuntimeErrorCode,
    ) -> None:
        reason = str(code).encode("utf-8")[:123]
        await self._write_websocket_frame(writer, 0x8, struct.pack("!H", 1008) + reason)

    def _validate_websocket_handshake(self, request: _HttpRequest) -> None:
        path = urlsplit(request.target).path
        if request.method != "GET" or path != "/v1/realtime":
            raise PrimitiveError(RuntimeErrorCode.WEBSOCKET_HANDSHAKE, "WebSocket route is invalid")
        headers = request.headers
        connection_tokens = {token.strip().lower() for token in headers.get("connection", "").split(",")}
        if headers.get("upgrade", "").lower() != "websocket" or "upgrade" not in connection_tokens:
            raise PrimitiveError(RuntimeErrorCode.WEBSOCKET_HANDSHAKE, "WebSocket upgrade headers are invalid")
        if headers.get("sec-websocket-version") != "13":
            raise PrimitiveError(RuntimeErrorCode.WEBSOCKET_HANDSHAKE, "WebSocket version 13 is required")
        protocols = {item.strip() for item in headers.get("sec-websocket-protocol", "").split(",")}
        if _WEBSOCKET_PROTOCOL not in protocols:
            raise PrimitiveError(RuntimeErrorCode.WEBSOCKET_HANDSHAKE, "realtime subprotocol is required")
        try:
            decoded_key = base64.b64decode(headers["sec-websocket-key"], validate=True)
        except (KeyError, ValueError, binascii.Error) as exc:
            raise PrimitiveError(RuntimeErrorCode.WEBSOCKET_HANDSHAKE, "WebSocket key is invalid") from exc
        if len(decoded_key) != 16:
            raise PrimitiveError(RuntimeErrorCode.WEBSOCKET_HANDSHAKE, "WebSocket key is invalid")
        origin = headers.get("origin")
        if origin is not None and not _origin_is_loopback(origin):
            raise PrimitiveError(RuntimeErrorCode.WEBSOCKET_HANDSHAKE, "WebSocket origin is not local")

    @staticmethod
    def _is_websocket_upgrade(request: _HttpRequest) -> bool:
        return request.headers.get("upgrade", "").lower() == "websocket"

    async def _send_json_response(
        self,
        writer: asyncio.StreamWriter,
        status: HTTPStatus,
        body: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        encoded = json.dumps(
            body,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        await self._send_response(
            writer,
            status,
            encoded,
            content_type="application/json; charset=utf-8",
            extra_headers=extra_headers,
        )

    async def _send_response(
        self,
        writer: asyncio.StreamWriter,
        status: HTTPStatus,
        encoded: bytes,
        *,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(encoded)),
            "Connection": "close",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        }
        headers.update(extra_headers or {})
        head = [f"HTTP/1.1 {status.value} {status.phrase}"]
        head.extend(f"{name}: {value}" for name, value in headers.items())
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode("ascii") + encoded)
        await self._drain(writer)

    def _record_metric(self, name: str, *, operation: str, status: str) -> None:
        try:
            self.metrics.increment(
                name,
                labels={"operation": operation, "status": status},
            )
        except PrimitiveError:
            # Observability must not take down the runtime when its bounded
            # registry reaches capacity.
            pass

    async def _drain(self, writer: asyncio.StreamWriter) -> None:
        try:
            await asyncio.wait_for(
                writer.drain(),
                timeout=self.config.idle_timeout_seconds,
            )
        except TimeoutError as exc:
            raise PrimitiveError(
                RuntimeErrorCode.WEBSOCKET_PROTOCOL,
                "transport write timed out",
            ) from exc

    @staticmethod
    def _error_body(code: RuntimeErrorCode, detail: str) -> dict[str, Any]:
        return {
            "status": "error",
            "errorCode": str(code),
            "message": detail[:256],
        }

    @staticmethod
    def _http_status_for(code: RuntimeErrorCode) -> HTTPStatus:
        code_value = str(code)
        if code_value == "E_MEMORY_NOT_FOUND":
            return HTTPStatus.NOT_FOUND
        if code_value in {
            "E_MEMORY_VERSION_CONFLICT",
            "E_MEMORY_CONTRADICTION",
            "E_MEMORY_STATE",
        }:
            return HTTPStatus.CONFLICT
        if code_value == "E_MEMORY_DELETE_PENDING" or code_value.startswith(
            "E_MEMORY_INDEX_"
        ) or code_value == "E_MEMORY_UNAVAILABLE":
            return HTTPStatus.SERVICE_UNAVAILABLE
        if code_value == "E_AVATAR_SOURCE":
            return HTTPStatus.FORBIDDEN
        if code_value == "E_AVATAR_UNAVAILABLE":
            return HTTPStatus.SERVICE_UNAVAILABLE
        if code is RuntimeErrorCode.FRAME_TOO_LARGE:
            return HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE
        if code is RuntimeErrorCode.CONNECTION_LIMIT:
            return HTTPStatus.SERVICE_UNAVAILABLE
        if code is RuntimeErrorCode.SAFETY_UNAVAILABLE:
            return HTTPStatus.SERVICE_UNAVAILABLE
        if code is RuntimeErrorCode.CHAT_UNAVAILABLE:
            return HTTPStatus.SERVICE_UNAVAILABLE
        if code is RuntimeErrorCode.CHAT_NOT_FOUND:
            return HTTPStatus.NOT_FOUND
        if code is RuntimeErrorCode.CHAT_CONFLICT:
            return HTTPStatus.CONFLICT
        return HTTPStatus.BAD_REQUEST

    def _log_error(
        self,
        error: PrimitiveError,
        operation: str,
        *,
        peer: str,
        exception: Exception | None = None,
    ) -> None:
        if self.error_logger is None:
            return
        self.error_logger.log_error(
            error,
            component="runtime.transport",
            operation=operation,
            correlation_id=_ZERO_CORRELATION_ID,
            context={
                "peer": peer,
                "exceptionType": type(exception).__name__ if exception is not None else None,
            },
        )

    @staticmethod
    def _peer_name(writer: asyncio.StreamWriter) -> str:
        peer = writer.get_extra_info("peername")
        if isinstance(peer, tuple) and peer:
            return str(peer[0])
        return "local"


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _origin_is_loopback(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            return False
        return ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False


def _parse_error_limit(query: str) -> int:
    parsed = parse_qs(query, keep_blank_values=True)
    if set(parsed) - {"limit"} or len(parsed.get("limit", [])) > 1:
        raise PrimitiveError(RuntimeErrorCode.HTTP_BAD_REQUEST, "error query is invalid")
    raw_limit = parsed.get("limit", ["20"])[0]
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise PrimitiveError(RuntimeErrorCode.HTTP_BAD_REQUEST, "error limit is invalid") from exc
    if not 1 <= limit <= 100:
        raise PrimitiveError(RuntimeErrorCode.HTTP_BAD_REQUEST, "error limit must be between 1 and 100")
    return limit


def _parse_safety_audit_limit(query: str) -> int:
    parsed = parse_qs(query, keep_blank_values=True)
    if set(parsed) - {"limit"} or len(parsed.get("limit", [])) > 1:
        raise PrimitiveError(RuntimeErrorCode.SAFETY_BAD_REQUEST, "audit query is invalid")
    raw_limit = parsed.get("limit", ["20"])[0]
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise PrimitiveError(RuntimeErrorCode.SAFETY_BAD_REQUEST, "audit limit is invalid") from exc
    if not 1 <= limit <= 100:
        raise PrimitiveError(RuntimeErrorCode.SAFETY_BAD_REQUEST, "audit limit must be between 1 and 100")
    return limit


def _parse_json_body(
    request: _HttpRequest,
    *,
    error_code: RuntimeErrorCode,
) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type != "application/json" or not request.body:
        raise PrimitiveError(error_code, "JSON request body is required")
    try:
        value = json.loads(
            request.body.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PrimitiveError(error_code, "request body is invalid JSON") from exc
    if not isinstance(value, dict):
        raise PrimitiveError(error_code, "request body must be an object")
    return value


def _chat_route(path: str, collection: str, *, suffix: str | None = None) -> str | None:
    parts = path.strip("/").split("/")
    expected_length = 5 if suffix is not None else 4
    if (
        len(parts) != expected_length
        or parts[:3] != ["v1", "chat", collection]
        or (suffix is not None and parts[-1] != suffix)
    ):
        return None
    return parts[3]


def _tts_cancel_route(path: str) -> str | None:
    parts = path.strip("/").split("/")
    if (
        len(parts) != 5
        or parts[:3] != ["v1", "tts", "utterances"]
        or parts[-1] != "cancel"
    ):
        return None
    return parts[3]


def _memory_item_route(path: str, collection: str, suffix: str) -> str | None:
    parts = path.strip("/").split("/")
    if (
        len(parts) != 5
        or parts[:3] != ["v1", "memory", collection]
        or parts[-1] != suffix
    ):
        return None
    return parts[3]


def _require_empty_query(query: str) -> None:
    if query:
        raise PrimitiveError(
            RuntimeErrorCode.HTTP_BAD_REQUEST,
            "query parameters are not supported for this route",
        )


def _parse_memory_candidate_query(query: str) -> str | None:
    parsed = parse_qs(query, keep_blank_values=True)
    if set(parsed) - {"status"} or len(parsed.get("status", [])) > 1:
        raise PrimitiveError(
            RuntimeErrorCode.HTTP_BAD_REQUEST,
            "memory candidate query is invalid",
        )
    return parsed.get("status", [None])[0]


def _parse_memory_search_query(query: str) -> tuple[str, int | None]:
    parsed = parse_qs(query, keep_blank_values=True)
    if set(parsed) - {"q", "limit"} or len(parsed.get("q", [])) != 1:
        raise PrimitiveError(
            RuntimeErrorCode.HTTP_BAD_REQUEST,
            "memory search query is invalid",
        )
    raw_limit = parsed.get("limit", [None])
    if len(raw_limit) > 1:
        raise PrimitiveError(
            RuntimeErrorCode.HTTP_BAD_REQUEST,
            "memory search limit is invalid",
        )
    try:
        limit = None if raw_limit[0] is None else int(raw_limit[0])
    except ValueError as exc:
        raise PrimitiveError(
            RuntimeErrorCode.HTTP_BAD_REQUEST,
            "memory search limit is invalid",
        ) from exc
    return parsed["q"][0], limit


def _read_recent_error_records(path: Path, limit: int) -> list[dict[str, Any]]:
    records: deque[dict[str, Any]] = deque(maxlen=limit)
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            start = max(0, size - _MAX_ERROR_LOG_SCAN_BYTES)
            handle.seek(start)
            if start:
                handle.readline()
            for raw_line in handle:
                if len(raw_line) > 65_536:
                    continue
                try:
                    record = json.loads(raw_line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(record, dict) and record.get("level") == "error":
                    redacted = redact_for_log(record)
                    if isinstance(redacted, dict):
                        records.append(redacted)
    except FileNotFoundError:
        return []
    except OSError:
        return []
    return list(records)
