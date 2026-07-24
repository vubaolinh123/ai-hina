from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(APP_ROOT / "src"))

from hina_core.runtime import (  # noqa: E402
    BinaryMediaFrame,
    ControlPlaneServer,
    DurableStore,
    JsonlErrorLogger,
    PrimitiveError,
    RuntimeErrorCode,
    TransportConfig,
)
from hina_core.runtime.transport_demo import run_transport_demo  # noqa: E402


class TransportValueTests(unittest.TestCase):
    def test_transport_refuses_non_loopback_bind(self) -> None:
        with self.assertRaises(PrimitiveError) as raised:
            TransportConfig(host="0.0.0.0")
        self.assertEqual(raised.exception.code, RuntimeErrorCode.NETWORK_BIND_DENIED)

    def test_binary_media_roundtrip_matches_published_header(self) -> None:
        media = BinaryMediaFrame(
            media_id=uuid.uuid4(),
            sequence=42,
            payload=b"\x00audio\xff",
            end_of_stream=True,
        )
        encoded = media.encode()
        decoded = BinaryMediaFrame.decode(encoded)
        contract = json.loads(
            (ROOT / "packages" / "contracts" / "binary-media-frame.v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(encoded[:4], b"HINA")
        self.assertEqual(len(encoded) - len(media.payload), contract["headerBytes"])
        self.assertEqual(contract["websocketOpcode"], 2)
        self.assertEqual(decoded, media)

        invalid = bytearray(encoded)
        invalid[5] = 0x80
        with self.assertRaises(PrimitiveError) as raised:
            BinaryMediaFrame.decode(bytes(invalid))
        self.assertEqual(raised.exception.code, RuntimeErrorCode.MEDIA_INVALID)

    def test_published_control_and_realtime_contracts_match_runtime(self) -> None:
        openapi = json.loads(
            (
                ROOT
                / "packages"
                / "contracts"
                / "openapi"
                / "control-plane.v1.json"
            ).read_text(encoding="utf-8")
        )
        asyncapi = json.loads(
            (
                ROOT
                / "packages"
                / "contracts"
                / "asyncapi"
                / "realtime.v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(openapi["openapi"], "3.1.0")
        self.assertEqual(
            set(openapi["paths"]),
            {
                "/v1/health",
                "/v1/version",
                "/v1/config",
                "/v1/metrics",
                "/v1/model/status",
                "/v1/chat/status",
                "/v1/chat/turns",
                "/v1/chat/turns/{turnId}",
                "/v1/chat/turns/{turnId}/cancel",
                "/v1/chat/sessions/{sessionId}",
                "/v1/chat/sessions/{sessionId}/clear",
                "/v1/speech/status",
                "/v1/speech/transcriptions",
                "/v1/errors",
                "/v1/safety/status",
                "/v1/safety/audit",
                "/v1/safety/evaluate",
                "/v1/safety/control",
                "/v1/safety/sanitize",
                "/v1/safety/context",
                "/v1/safety/moderate",
            },
        )
        self.assertEqual(asyncapi["asyncapi"], "3.0.0")
        self.assertEqual(
            asyncapi["channels"]["realtime"]["address"],
            "/v1/realtime",
        )
        self.assertEqual(
            asyncapi["servers"]["local"]["protocol"],
            "ws",
        )


class TransportServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_smoke_exercises_control_text_binary_and_durable_paths(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            result = await run_transport_demo(
                directory / "runtime.sqlite3",
                directory / "runtime.jsonl",
            )
            self.assertEqual(result["status"], "ok")
            self.assertTrue(result["server"]["loopbackOnly"])
            self.assertEqual(result["control"]["health"], "ready")
            self.assertEqual(result["control"]["configStatus"], 200)
            self.assertTrue(result["realtime"]["eventAccepted"])
            self.assertTrue(result["realtime"]["durable"])
            self.assertTrue(result["realtime"]["duplicateSuppressed"])
            self.assertEqual(result["realtime"]["journalRows"], 1)
            self.assertEqual(result["realtime"]["resumedSequences"], [0])
            self.assertEqual(result["realtime"]["invalidEventCode"], "E_EVENT_REJECTED")
            self.assertEqual(result["binary"]["websocketOpcode"], 2)
            self.assertTrue(result["binary"]["payloadMatches"])
            self.assertFalse(result["binary"]["base64JsonUsed"])
            self.assertEqual(result["errorLog"]["records"], 1)

            log_text = (directory / "runtime.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("hina.unknown.v1", log_text)
            self.assertIn("E_EVENT_REJECTED", log_text)

    async def test_external_origin_and_unmasked_frame_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            logger = JsonlErrorLogger(directory / "runtime.jsonl")
            with DurableStore(directory / "runtime.sqlite3") as store:
                server = ControlPlaneServer(
                    TransportConfig(port=0),
                    durable_store=store,
                    error_logger=logger,
                )
                await server.start()
                host, port = server.address
                try:
                    reader, writer = await asyncio.open_connection(host, port)
                    writer.write(
                        self._handshake(host, port, origin="https://attacker.example")
                    )
                    await writer.drain()
                    rejected = await reader.read()
                    writer.close()
                    await writer.wait_closed()
                    self.assertIn(b"400 Bad Request", rejected)
                    self.assertIn(b"E_WEBSOCKET_HANDSHAKE", rejected)

                    reader, writer = await asyncio.open_connection(host, port)
                    writer.write(
                        self._handshake(host, port, origin=f"http://{host}:{port}")
                    )
                    await writer.drain()
                    response = await reader.readuntil(b"\r\n\r\n")
                    self.assertIn(b"101 Switching Protocols", response)
                    writer.write(b"\x81\x02{}")
                    await writer.drain()
                    first, second = await reader.readexactly(2)
                    self.assertEqual(first & 0x0F, 0x8)
                    length = second & 0x7F
                    close_payload = await reader.readexactly(length)
                    self.assertIn(b"E_WEBSOCKET_PROTOCOL", close_payload)
                    writer.close()
                    await writer.wait_closed()
                finally:
                    await server.stop()

            records = [
                json.loads(line)
                for line in (directory / "runtime.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(
                [record["errorCode"] for record in records],
                ["E_WEBSOCKET_HANDSHAKE", "E_WEBSOCKET_PROTOCOL"],
            )
            self.assertNotIn("attacker.example", json.dumps(records))

    @staticmethod
    def _handshake(host: str, port: int, *, origin: str) -> bytes:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        return (
            "GET /v1/realtime HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Protocol: hina.realtime.v1\r\n"
            f"Origin: {origin}\r\n"
            "\r\n"
        ).encode("ascii")


if __name__ == "__main__":
    unittest.main()
