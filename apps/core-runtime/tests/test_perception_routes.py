from __future__ import annotations

import asyncio
import struct
import sys
import tempfile
import unittest
import zlib
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
SAFETY_ROOT = ROOT / "packages" / "safety-policy"
PERCEPTION_ROOT = ROOT / "workers" / "perception"
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(SAFETY_ROOT / "src"))
sys.path.insert(0, str(PERCEPTION_ROOT / "src"))
sys.path.insert(0, str(APP_ROOT / "src"))

from hina_core.runtime import TransportConfig  # noqa: E402
from hina_core.runtime.transport import ControlPlaneServer  # noqa: E402
from hina_core.runtime.transport_client import get_json, post_json  # noqa: E402
from hina_perception import PerceptionConfig, PerceptionService  # noqa: E402
from hina_safety import AuditTrail, CapabilityManifest, SafetyPolicyService  # noqa: E402


MANIFEST_PATH = SAFETY_ROOT / "manifests" / "default.v1.json"
CORRELATION = "4b825dc6-42b0-4c48-8f1a-9a54f1f9f6da"


def _chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def _png(seed: int = 0, size: int = 32) -> bytes:
    raw = bytearray()
    for row in range(size):
        raw.append(0)
        for column in range(size):
            value = (column * 255 // (size - 1) + seed * 96) % 256
            raw.extend((value, value, value))
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw)))
        + _chunk(b"IEND", b"")
    )


class _FakeClock:
    def __init__(self) -> None:
        self.value = 5_000.0

    def advance(self, seconds: float) -> None:
        self.value += seconds

    def __call__(self) -> float:
        return self.value


async def _post_snapshot(
    host: str,
    port: int,
    body: bytes,
    *,
    content_type: str = "image/png",
    owner_confirmed: bool = True,
    label: str | None = None,
) -> tuple[int, dict[str, object]]:
    import json as json_module

    reader, writer = await asyncio.open_connection(host, port)
    headers = [
        "POST /v1/perception/snapshots HTTP/1.1",
        f"Host: {host}:{port}",
        f"Content-Type: {content_type}",
        f"Content-Length: {len(body)}",
        f"X-Hina-Correlation-Id: {CORRELATION}",
        "X-Hina-Source: owner.console",
    ]
    if owner_confirmed:
        headers.append("X-Hina-Owner-Confirmed: true")
    if label is not None:
        headers.append(f"X-Hina-Label: {quote(label)}")
    headers.append("Connection: close")
    writer.write(("\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    await writer.wait_closed()
    head, response_body = raw.split(b"\r\n\r\n", 1)
    status = int(head.decode("ascii").split("\r\n")[0].split(" ")[1])
    return status, json_module.loads(response_body.decode("utf-8"))


class PerceptionRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(dir=APP_ROOT)
        directory = Path(self._temporary.name)
        self.safety = SafetyPolicyService(
            CapabilityManifest.load(MANIFEST_PATH),
            AuditTrail(directory / "audit.jsonl", build_commit="perception-test"),
        )
        self.clock = _FakeClock()
        self.perception = PerceptionService(
            PerceptionConfig(),
            safety_evaluate=self.safety.evaluate,
            clock=self.clock,
        )
        self.server = ControlPlaneServer(
            TransportConfig(port=0),
            safety_policy=self.safety,
            perception_service=self.perception,
        )
        await self.server.start()
        self.host, self.port = self.server.address

    async def asyncTearDown(self) -> None:
        await self.server.stop()
        await self.perception.close()
        self._temporary.cleanup()

    async def _enable_perception_flag(self) -> None:
        response = await post_json(
            self.host,
            self.port,
            "/v1/safety/control",
            {
                "action": "set_feature",
                "feature": "perception",
                "enabled": True,
                "actorId": "owner.console",
                "trustLevel": "owner",
                "correlationId": CORRELATION,
            },
        )
        assert response.status == HTTPStatus.OK

    async def test_status_route_reports_contract_state(self) -> None:
        response = await get_json(self.host, self.port, "/v1/perception/status")
        self.assertEqual(response.status, HTTPStatus.OK)
        self.assertFalse(response.body["capture"]["autoCapture"])
        self.assertEqual(response.body["policy"]["capability"], "perception.observe")
        self.assertEqual(response.body["ocr"]["state"], "contract-ready")

    async def test_snapshot_is_denied_while_feature_flag_is_off(self) -> None:
        status, body = await _post_snapshot(self.host, self.port, _png())
        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertEqual(body["errorCode"], "E_PERCEPTION_DENIED")
        self.assertIn("feature_disabled", body["message"])

    async def test_snapshot_requires_owner_confirmation_after_flag_enable(self) -> None:
        await self._enable_perception_flag()
        status, body = await _post_snapshot(
            self.host, self.port, _png(), owner_confirmed=False
        )
        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertEqual(body["errorCode"], "E_PERCEPTION_CONFIRMATION")

    async def test_confirmed_snapshot_creates_ttl_bounded_observation(self) -> None:
        await self._enable_perception_flag()
        status, body = await _post_snapshot(
            self.host, self.port, _png(), label="Màn hình trò chơi"
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(body["status"], "observed")
        observation = body["observation"]
        self.assertEqual(observation["trustLevel"], "untrusted")
        self.assertEqual(observation["label"], "Màn hình trò chơi")
        self.assertEqual(observation["ttlSeconds"], 15.0)

        listing = await get_json(self.host, self.port, "/v1/perception/observations")
        self.assertEqual(listing.status, HTTPStatus.OK)
        self.assertEqual(listing.body["count"], 1)

        self.clock.advance(15.001)
        expired = await get_json(self.host, self.port, "/v1/perception/observations")
        self.assertEqual(expired.body["count"], 0)
        self.assertEqual(expired.body["expiredTotal"], 1)

    async def test_duplicate_snapshot_is_flagged(self) -> None:
        await self._enable_perception_flag()
        first_status, _ = await _post_snapshot(self.host, self.port, _png())
        self.assertEqual(first_status, HTTPStatus.OK)
        second_status, second_body = await _post_snapshot(self.host, self.port, _png())
        self.assertEqual(second_status, HTTPStatus.OK)
        self.assertEqual(second_body["status"], "duplicate")

    async def test_wrong_content_type_and_empty_body_are_rejected(self) -> None:
        await self._enable_perception_flag()
        status, body = await _post_snapshot(
            self.host, self.port, _png(), content_type="image/jpeg"
        )
        self.assertEqual(status, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        self.assertEqual(body["errorCode"], "E_PERCEPTION_CONTENT_TYPE")

        status, body = await _post_snapshot(self.host, self.port, b"")
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(body["errorCode"], "E_PERCEPTION_SNAPSHOT_EMPTY")

    async def test_clear_route_requires_exact_payload(self) -> None:
        await self._enable_perception_flag()
        status, _ = await _post_snapshot(self.host, self.port, _png())
        self.assertEqual(status, HTTPStatus.OK)

        bad = await post_json(
            self.host, self.port, "/v1/perception/clear", {"action": "drop"}
        )
        self.assertEqual(bad.status, HTTPStatus.BAD_REQUEST)

        cleared = await post_json(
            self.host, self.port, "/v1/perception/clear", {"action": "clear"}
        )
        self.assertEqual(cleared.status, HTTPStatus.OK)
        self.assertEqual(cleared.body["removed"], 1)

    async def test_missing_service_fails_closed(self) -> None:
        bare = ControlPlaneServer(TransportConfig(port=0))
        await bare.start()
        host, port = bare.address
        try:
            response = await get_json(host, port, "/v1/perception/status")
            self.assertEqual(response.status, HTTPStatus.SERVICE_UNAVAILABLE)
            self.assertEqual(response.body["errorCode"], "E_PERCEPTION_UNAVAILABLE")
            status, body = await _post_snapshot(host, port, _png())
            self.assertEqual(status, HTTPStatus.SERVICE_UNAVAILABLE)
            self.assertEqual(body["errorCode"], "E_PERCEPTION_UNAVAILABLE")
        finally:
            await bare.stop()


if __name__ == "__main__":
    unittest.main()
