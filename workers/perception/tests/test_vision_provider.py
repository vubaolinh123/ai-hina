from __future__ import annotations

import base64
import unittest
from typing import Any

from hina_perception import OllamaVisionProvider, PerceptionError, VisionConfig


class _FakeOllama:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.models = [
            {
                "name": "qwen3-vl:2b",
                "model": "qwen3-vl:2b",
                "size": 1_900_000_000,
                "details": {
                    "parameter_size": "2.0B",
                    "quantization_level": "Q4_K_M",
                },
            },
            {
                "name": "text-only:1b",
                "model": "text-only:1b",
                "size": 900_000_000,
                "details": {
                    "parameter_size": "1.0B",
                    "quantization_level": "Q4_K_M",
                },
            },
            {
                "name": "oversized-quant:4b",
                "model": "oversized-quant:4b",
                "size": 6_000_000_000,
                "details": {
                    "parameter_size": "4.0B",
                    "quantization_level": "Q8_0",
                },
            },
            {
                "name": "too-large:8b",
                "model": "too-large:8b",
                "size": 4_900_000_000,
                "details": {
                    "parameter_size": "8.0B",
                    "quantization_level": "Q4_K_M",
                },
            },
            {
                "name": "unknown-size:2b",
                "model": "unknown-size:2b",
                "details": {
                    "parameter_size": "2.0B",
                    "quantization_level": "Q4_K_M",
                },
            },
        ]

    async def request(
        self,
        method: str,
        url: str,
        payload: dict[str, object] | None,
        api_key: str | None,
        timeout: float,
        max_bytes: int,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "payload": payload,
                "apiKey": api_key,
                "timeout": timeout,
                "maxBytes": max_bytes,
            }
        )
        if url.endswith("/api/tags"):
            return {"models": self.models}
        if url.endswith("/api/show"):
            assert payload is not None
            model = payload["model"]
            if model == "text-only:1b":
                return {
                    "capabilities": ["completion"],
                    "details": {"parameter_size": "1.0B"},
                }
            if model == "too-large:8b":
                return {
                    "capabilities": ["completion", "vision"],
                    "details": {"parameter_size": "8.0B"},
                }
            if model == "oversized-quant:4b":
                return {
                    "capabilities": ["completion", "vision"],
                    "details": {"parameter_size": "4.0B"},
                }
            return {
                "capabilities": ["completion", "vision"],
                "details": {
                    "parameter_size": "2.0B",
                    "quantization_level": "Q4_K_M",
                },
            }
        if url.endswith("/api/chat"):
            return {
                "message": {
                    "thinking": "private",
                    "content": "Trong ảnh có một cửa sổ game.",
                }
            }
        if url.endswith("/api/generate"):
            return {"done": True}
        raise AssertionError(url)


class _Lease:
    def __init__(self) -> None:
        self.asserted = False
        self.released = False

    def assert_active(self) -> None:
        self.asserted = True

    async def release(self) -> bool:
        self.released = True
        return True


class _AuthFailureOllama(_FakeOllama):
    async def request(
        self,
        method: str,
        url: str,
        payload: dict[str, object] | None,
        api_key: str | None,
        timeout: float,
        max_bytes: int,
    ) -> dict[str, Any]:
        if url.endswith("/api/tags"):
            return {"models": self.models[:1]}
        raise PerceptionError(
            "E_PERCEPTION_VISION_AUTH",
            "Ollama Cloud rejected the API key",
        )


class OllamaVisionProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_returns_only_advertised_vision_models(self) -> None:
        fake = _FakeOllama()
        provider = OllamaVisionProvider(
            VisionConfig(),
            request_json=fake.request,
        )
        result = await provider.discover_models(
            provider="ollama_local",
            api_key=None,
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["models"][0]["name"], "qwen3-vl:2b")
        self.assertTrue(result["models"][0]["lightweight"])
        self.assertTrue(result["onlyVisionModels"])
        self.assertTrue(
            all(call["apiKey"] is None for call in fake.calls),
        )

    async def test_discovery_does_not_hide_cloud_auth_failure(self) -> None:
        provider = OllamaVisionProvider(
            VisionConfig(),
            request_json=_AuthFailureOllama().request,
        )
        with self.assertRaises(PerceptionError) as raised:
            await provider.discover_models(
                provider="ollama_cloud",
                api_key="owner-cloud-secret",
            )
        self.assertEqual(raised.exception.code, "E_PERCEPTION_VISION_AUTH")

    async def test_cloud_key_is_used_but_never_returned_by_status(self) -> None:
        fake = _FakeOllama()
        provider = OllamaVisionProvider(
            VisionConfig(),
            request_json=fake.request,
        )
        secret = "owner-cloud-secret"
        status = await provider.configure(
            provider="ollama_cloud",
            model="qwen3-vl:2b",
            api_key=secret,
        )
        self.assertTrue(status["apiKeyConfigured"])
        self.assertNotIn(secret, str(status))
        result = await provider.analyze(
            b"\x89PNG\r\n\x1a\nowner-pixels",
            "Mô tả ảnh.",
        )
        self.assertEqual(result, "Trong ảnh có một cửa sổ game.")
        chat = next(call for call in fake.calls if call["url"].endswith("/api/chat"))
        self.assertEqual(chat["apiKey"], secret)
        assert chat["payload"] is not None
        image = chat["payload"]["messages"][0]["images"][0]  # type: ignore[index]
        self.assertEqual(
            base64.b64decode(image),
            b"\x89PNG\r\n\x1a\nowner-pixels",
        )
        self.assertNotIn("private", result)

    async def test_local_model_must_fit_lightweight_profile_and_use_scheduler(self) -> None:
        fake = _FakeOllama()
        leases: list[_Lease] = []

        async def acquire(_unload: Any) -> _Lease:
            lease = _Lease()
            leases.append(lease)
            return lease

        provider = OllamaVisionProvider(
            VisionConfig(),
            request_json=fake.request,
            acquire_local_lease=acquire,
        )
        with self.assertRaises(PerceptionError) as raised:
            await provider.configure(
                provider="ollama_local",
                model="too-large:8b",
                api_key=None,
            )
        self.assertEqual(raised.exception.code, "E_PERCEPTION_VISION_CAPACITY")

        await provider.configure(
            provider="ollama_local",
            model="qwen3-vl:2b",
            api_key=None,
        )
        await provider.analyze(
            b"\x89PNG\r\n\x1a\nowner-pixels",
            "Mô tả ảnh.",
        )
        self.assertEqual(len(leases), 1)
        self.assertTrue(leases[0].asserted)
        self.assertTrue(leases[0].released)
        chat = next(call for call in fake.calls if call["url"].endswith("/api/chat"))
        assert chat["payload"] is not None
        self.assertEqual(chat["payload"]["keep_alive"], 0)
        self.assertEqual(chat["payload"]["options"]["num_ctx"], 4_096)  # type: ignore[index]
        self.assertEqual(chat["payload"]["options"]["num_gpu"], 999)  # type: ignore[index]

        with self.assertRaises(PerceptionError) as oversized:
            await provider.configure(
                provider="ollama_local",
                model="oversized-quant:4b",
                api_key=None,
            )
        self.assertEqual(
            oversized.exception.code,
            "E_PERCEPTION_VISION_CAPACITY",
        )

        with self.assertRaises(PerceptionError) as unknown_size:
            await provider.configure(
                provider="ollama_local",
                model="unknown-size:2b",
                api_key=None,
            )
        self.assertEqual(
            unknown_size.exception.code,
            "E_PERCEPTION_VISION_CAPACITY",
        )

    async def test_unconfigured_provider_fails_closed(self) -> None:
        provider = OllamaVisionProvider(
            VisionConfig(),
            request_json=_FakeOllama().request,
        )
        with self.assertRaises(PerceptionError) as raised:
            await provider.analyze(
                b"\x89PNG\r\n\x1a\nowner-pixels",
                "Mô tả ảnh.",
            )
        self.assertEqual(raised.exception.code, "E_PERCEPTION_VISION_UNAVAILABLE")
