from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import struct
from dataclasses import dataclass
from typing import Any


_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_WEBSOCKET_PROTOCOL = "hina.realtime.v1"


@dataclass(frozen=True, slots=True)
class HttpJsonResponse:
    status: int
    headers: dict[str, str]
    body: dict[str, Any]


async def get_json(host: str, port: int, path: str) -> HttpJsonResponse:
    reader, writer = await asyncio.open_connection(host, port)
    try:
        authority = _authority(host, port)
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {authority}\r\n"
            "Accept: application/json\r\n"
            "Connection: close\r\n"
            "\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()
        raw = await reader.read()
    finally:
        writer.close()
        await writer.wait_closed()
    head, separator, body = raw.partition(b"\r\n\r\n")
    if not separator:
        raise ConnectionError("HTTP response is truncated")
    lines = head.decode("ascii").split("\r\n")
    status = int(lines[0].split(" ", 2)[1])
    headers = {
        name.strip().lower(): value.strip()
        for line in lines[1:]
        for name, separator, value in [line.partition(":")]
        if separator
    }
    return HttpJsonResponse(status, headers, json.loads(body.decode("utf-8")))


class RealtimeClient:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        max_frame_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._max_frame_bytes = max_frame_bytes

    @classmethod
    async def connect(cls, host: str, port: int) -> RealtimeClient:
        reader, writer = await asyncio.open_connection(host, port)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        authority = _authority(host, port)
        request = (
            "GET /v1/realtime HTTP/1.1\r\n"
            f"Host: {authority}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Protocol: {_WEBSOCKET_PROTOCOL}\r\n"
            f"Origin: http://{authority}\r\n"
            "\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()
        raw_head = await reader.readuntil(b"\r\n\r\n")
        lines = raw_head[:-4].decode("ascii").split("\r\n")
        if not lines[0].startswith("HTTP/1.1 101 "):
            writer.close()
            await writer.wait_closed()
            raise ConnectionError(f"WebSocket upgrade failed: {lines[0]}")
        headers = {
            name.strip().lower(): value.strip()
            for line in lines[1:]
            for name, separator, value in [line.partition(":")]
            if separator
        }
        expected = base64.b64encode(
            hashlib.sha1(f"{key}{_WEBSOCKET_GUID}".encode("ascii")).digest()
        ).decode("ascii")
        if headers.get("sec-websocket-accept") != expected:
            writer.close()
            await writer.wait_closed()
            raise ConnectionError("WebSocket accept key mismatch")
        if headers.get("sec-websocket-protocol") != _WEBSOCKET_PROTOCOL:
            writer.close()
            await writer.wait_closed()
            raise ConnectionError("WebSocket subprotocol mismatch")
        return cls(reader, writer)

    async def __aenter__(self) -> RealtimeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def send_json(self, value: Any) -> None:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        await self._write_masked_frame(0x1, payload)

    async def receive_json(self) -> dict[str, Any]:
        opcode, payload = await self.receive()
        if opcode != 0x1:
            raise ConnectionError(f"expected text frame, received opcode {opcode}")
        value = json.loads(payload.decode("utf-8"))
        if not isinstance(value, dict):
            raise ConnectionError("expected JSON object")
        return value

    async def send_binary(self, payload: bytes) -> None:
        await self._write_masked_frame(0x2, payload)

    async def receive(self) -> tuple[int, bytes]:
        first, second = await self._reader.readexactly(2)
        if first & 0x70 or not first & 0x80:
            raise ConnectionError("server returned unsupported WebSocket frame")
        opcode = first & 0x0F
        if second & 0x80:
            raise ConnectionError("server frame must not be masked")
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", await self._reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", await self._reader.readexactly(8))[0]
        if length > self._max_frame_bytes:
            raise ConnectionError("server WebSocket frame exceeds client limit")
        return opcode, await self._reader.readexactly(length)

    async def close(self) -> None:
        if self._writer.is_closing():
            return
        try:
            await self._write_masked_frame(0x8, struct.pack("!H", 1000))
            await asyncio.wait_for(self.receive(), timeout=1)
        except (ConnectionError, TimeoutError, asyncio.IncompleteReadError):
            pass
        self._writer.close()
        await self._writer.wait_closed()

    async def _write_masked_frame(self, opcode: int, payload: bytes) -> None:
        first = 0x80 | opcode
        length = len(payload)
        if length < 126:
            header = bytes((first, 0x80 | length))
        elif length <= 0xFFFF:
            header = bytes((first, 0x80 | 126)) + struct.pack("!H", length)
        else:
            header = bytes((first, 0x80 | 127)) + struct.pack("!Q", length)
        mask = os.urandom(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self._writer.write(header + mask + masked)
        await self._writer.drain()


def _authority(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
