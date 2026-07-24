from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "apps" / "dev-console" / "public"
SAFETY_ROOT = ROOT / "packages" / "safety-policy"
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(SAFETY_ROOT / "src"))
sys.path.insert(0, str(APP_ROOT / "src"))

from hina_core.runtime import (  # noqa: E402
    HinaRuntimeApplication,
    PrimitiveError,
    RuntimeErrorCode,
    RuntimePaths,
    TransportConfig,
)
from hina_core.runtime.transport_client import get_json, post_json  # noqa: E402


async def _get(host: str, port: int, target: str) -> tuple[int, dict[str, str], bytes]:
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(
        (
            f"GET {target} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
    )
    await writer.drain()
    raw = await reader.read()
    writer.close()
    await writer.wait_closed()
    head, body = raw.split(b"\r\n\r\n", 1)
    lines = head.decode("ascii").split("\r\n")
    status = int(lines[0].split(" ")[1])
    headers = {
        name.lower(): value.strip()
        for line in lines[1:]
        for name, separator, value in [line.partition(":")]
        if separator
    }
    return status, headers, body


class DevConsoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_console_serves_real_client_with_security_headers_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            application = HinaRuntimeApplication(
                TransportConfig(port=0),
                RuntimePaths(
                    database=directory / "runtime.sqlite3",
                    error_log=directory / "runtime.jsonl",
                    static_dir=STATIC_DIR,
                ),
                build_commit="test-build",
            )
            await application.start()
            host, port = application.address
            try:
                status, headers, html = await _get(host, port, "/")
                self.assertEqual(status, HTTPStatus.OK)
                self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
                self.assertIn("default-src 'self'", headers["content-security-policy"])
                self.assertEqual(headers["x-frame-options"], "DENY")
                self.assertIn(b"Hina Dev Console", html)

                status, _, script = await _get(host, port, "/app.js")
                self.assertEqual(status, HTTPStatus.OK)
                self.assertIn(b"new WebSocket", script)
                self.assertIn(b"/v1/safety/evaluate", script)
                self.assertNotIn(b"unknown_capability", script)
                self.assertNotIn(b"fake AI", script)

                status, _, body = await _get(host, port, "/v1/metrics")
                self.assertEqual(status, HTTPStatus.OK)
                metrics = json.loads(body)
                self.assertGreaterEqual(metrics["seriesCount"], 1)
                self.assertLessEqual(metrics["seriesCount"], metrics["maxSeries"])
            finally:
                await application.stop()

    async def test_error_endpoint_is_redacted_bounded_and_rejects_bad_query(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            application = HinaRuntimeApplication(
                TransportConfig(port=0),
                RuntimePaths(
                    database=directory / "runtime.sqlite3",
                    error_log=directory / "runtime.jsonl",
                    static_dir=STATIC_DIR,
                ),
            )
            await application.start()
            host, port = application.address
            try:
                for index in range(105):
                    application.error_logger.log_error(
                        PrimitiveError(
                            RuntimeErrorCode.OPERATION_FAILED,
                            f"token=owner-secret-{index}",
                        ),
                        component="runtime.test",
                        operation="manual_test",
                        correlation_id="00000000-0000-0000-0000-000000000000",
                        context={"authorization": f"Bearer owner-secret-{index}"},
                    )

                status, _, body = await _get(host, port, "/v1/errors?limit=100")
                self.assertEqual(status, HTTPStatus.OK)
                result = json.loads(body)
                self.assertEqual(result["count"], 100)
                self.assertEqual(result["limit"], 100)
                encoded = json.dumps(result)
                self.assertNotIn("owner-secret", encoded)
                self.assertIn("<redacted>", encoded)

                status, _, body = await _get(host, port, "/v1/errors?limit=101")
                self.assertEqual(status, HTTPStatus.BAD_REQUEST)
                self.assertEqual(json.loads(body)["errorCode"], "E_HTTP_BAD_REQUEST")
            finally:
                await application.stop()

    async def test_application_shutdown_releases_socket_and_database(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            application = HinaRuntimeApplication(
                TransportConfig(port=0),
                RuntimePaths(
                    database=directory / "runtime.sqlite3",
                    error_log=directory / "runtime.jsonl",
                    static_dir=STATIC_DIR,
                ),
            )
            await application.start()
            host, port = application.address
            self.assertTrue((directory / "runtime.sqlite3").exists())
            await application.stop()
            self.assertIsNone(application.server)
            self.assertIsNone(application.store)
            with self.assertRaises(OSError):
                await asyncio.open_connection(host, port)

    async def test_safety_controls_are_real_audited_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            application = HinaRuntimeApplication(
                TransportConfig(port=0),
                RuntimePaths(
                    database=directory / "runtime.sqlite3",
                    error_log=directory / "runtime.jsonl",
                    static_dir=STATIC_DIR,
                    audit_log=directory / "safety-audit.jsonl",
                    safety_manifest=SAFETY_ROOT / "manifests" / "default.v1.json",
                ),
                build_commit="safety-test",
            )
            await application.start()
            host, port = application.address
            correlation = "33333333-3333-4333-8333-333333333333"
            session = "44444444-4444-4444-8444-444444444444"
            policy_request = {
                "capability": "tool.safe.echo",
                "actorId": "local-owner",
                "trustLevel": "owner",
                "correlationId": correlation,
                "sessionId": session,
                "consume": True,
            }
            try:
                status = await get_json(host, port, "/v1/safety/status")
                self.assertEqual(status.status, HTTPStatus.OK)
                self.assertEqual(status.body["manifest"]["manifestId"], "hina.local.default.v1")

                allowed = await post_json(host, port, "/v1/safety/evaluate", policy_request)
                self.assertEqual(allowed.status, HTTPStatus.OK)
                self.assertEqual(allowed.body["decision"], "allow")
                self.assertTrue(allowed.body["consumed"])

                stopped = await post_json(
                    host,
                    port,
                    "/v1/safety/control",
                    {
                        "action": "emergency_stop",
                        "actorId": "local-owner",
                        "trustLevel": "owner",
                        "correlationId": correlation,
                    },
                )
                self.assertTrue(stopped.body["state"]["emergencyStopped"])

                blocked = await post_json(host, port, "/v1/safety/evaluate", policy_request)
                self.assertEqual(
                    (blocked.body["decision"], blocked.body["reasonCode"]),
                    ("deny", "emergency_stop"),
                )

                audit = await get_json(host, port, "/v1/safety/audit?limit=20")
                self.assertEqual(audit.status, HTTPStatus.OK)
                self.assertEqual(audit.body["count"], 3)
                self.assertNotIn("local-owner", json.dumps(audit.body))

                rejected = await post_json(
                    host,
                    port,
                    "/v1/safety/evaluate",
                    {
                        **policy_request,
                        "prompt": "token=must-not-enter-log",
                    },
                )
                self.assertEqual(rejected.status, HTTPStatus.BAD_REQUEST)
                self.assertEqual(rejected.body["errorCode"], "E_SAFETY_BAD_REQUEST")
                log_text = (directory / "runtime.jsonl").read_text(encoding="utf-8")
                self.assertNotIn("must-not-enter-log", log_text)
            finally:
                await application.stop()


if __name__ == "__main__":
    unittest.main()
