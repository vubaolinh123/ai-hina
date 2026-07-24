from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hina_text_brain import (  # noqa: E402
    LocalHttpChatProvider,
    ModelGatewayConfig,
    ProviderKind,
    TextBrainError,
)


class _ProviderHandler(BaseHTTPRequestHandler):
    mode = "ollama"
    malformed = False
    authorization: str | None = None
    received_body: dict[str, Any] | None = None

    def log_message(self, *_: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/api/tags":
            self._json({"models": [{"name": "hina-local:4b"}]})
            return
        if self.path == "/v1/models":
            self._json({"data": [{"id": "hina-local:4b"}]})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        type(self).authorization = self.headers.get("Authorization")
        length = int(self.headers.get("Content-Length", "0"))
        type(self).received_body = json.loads(self.rfile.read(length).decode("utf-8"))
        if self.path == "/api/chat":
            lines = (
                [b"{not-json}\n"]
                if type(self).malformed
                else [
                    json.dumps(
                        {"message": {"content": "Xin "}, "done": False},
                        ensure_ascii=False,
                    ).encode("utf-8") + b"\n",
                    json.dumps(
                        {"message": {"content": "chao"}, "done": True},
                        ensure_ascii=False,
                    ).encode("utf-8") + b"\n",
                ]
            )
            self._stream(lines, "application/x-ndjson")
            return
        if self.path == "/v1/chat/completions":
            lines = [
                b'data: {"choices":[{"delta":{"content":"Hello "},"finish_reason":null}]}\n\n',
                b'data: {"choices":[{"delta":{"content":"Hina"},"finish_reason":"stop"}]}\n\n',
                b"data: [DONE]\n\n",
            ]
            self._stream(lines, "text/event-stream")
            return
        if self.path == "/api/generate":
            self._json({"done": True})
            return
        self.send_error(404)

    def _json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self, lines: list[bytes], content_type: str) -> None:
        body = b"".join(lines)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()


class ProviderAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _ProviderHandler.malformed = False
        _ProviderHandler.authorization = None
        _ProviderHandler.received_body = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    async def test_ollama_health_and_stream_are_real_http(self) -> None:
        provider = LocalHttpChatProvider(
            ModelGatewayConfig(base_url=self.base_url, model="hina-local:4b")
        )
        health = await provider.health()
        self.assertTrue(health.reachable)
        self.assertTrue(health.model_available)
        tokens = [
            token
            async for token in provider.stream_chat(
                [{"role": "user", "content": "Xin chào"}]
            )
        ]
        self.assertEqual("".join(tokens), "Xin chao")
        self.assertEqual(_ProviderHandler.received_body["model"], "hina-local:4b")
        self.assertTrue(_ProviderHandler.received_body["stream"])

    async def test_openai_compatible_health_stream_and_secret_header(self) -> None:
        provider = LocalHttpChatProvider(
            ModelGatewayConfig(
                provider=ProviderKind.OPENAI_COMPATIBLE,
                base_url=self.base_url,
                model="hina-local:4b",
                api_key="test-secret",
            )
        )
        self.assertTrue((await provider.health()).model_available)
        text = "".join(
            [
                token
                async for token in provider.stream_chat(
                    [{"role": "user", "content": "Hello"}]
                )
            ]
        )
        self.assertEqual(text, "Hello Hina")
        self.assertEqual(_ProviderHandler.authorization, "Bearer test-secret")

    async def test_malformed_provider_stream_fails_without_fake_text(self) -> None:
        _ProviderHandler.malformed = True
        provider = LocalHttpChatProvider(
            ModelGatewayConfig(base_url=self.base_url, model="hina-local:4b")
        )
        tokens: list[str] = []
        with self.assertRaises(TextBrainError) as raised:
            async for token in provider.stream_chat(
                [{"role": "user", "content": "No fake fallback"}]
            ):
                tokens.append(token)
        self.assertEqual(raised.exception.code, "E_MODEL_STREAM_INVALID")
        self.assertEqual(tokens, [])


if __name__ == "__main__":
    unittest.main()
