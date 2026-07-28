from __future__ import annotations

import asyncio
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


class _SequencedChatOllama(_FakeOllama):
    def __init__(self, responses: list[dict[str, Any] | PerceptionError]) -> None:
        super().__init__()
        self.responses = list(responses)

    async def request(
        self,
        method: str,
        url: str,
        payload: dict[str, object] | None,
        api_key: str | None,
        timeout: float,
        max_bytes: int,
    ) -> dict[str, Any]:
        if not url.endswith("/api/chat"):
            return await super().request(
                method,
                url,
                payload,
                api_key,
                timeout,
                max_bytes,
            )
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
        if not self.responses:
            raise AssertionError("unexpected extra /api/chat request")
        response = self.responses.pop(0)
        if isinstance(response, PerceptionError):
            raise response
        return response


class _BlockingLocalChatOllama(_FakeOllama):
    def __init__(self) -> None:
        super().__init__()
        self.chat_started = asyncio.Event()
        self.allow_chat_completion = asyncio.Event()

    async def request(
        self,
        method: str,
        url: str,
        payload: dict[str, object] | None,
        api_key: str | None,
        timeout: float,
        max_bytes: int,
    ) -> dict[str, Any]:
        if not url.endswith("/api/chat"):
            return await super().request(
                method,
                url,
                payload,
                api_key,
                timeout,
                max_bytes,
            )
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
        self.chat_started.set()
        await self.allow_chat_completion.wait()
        return {"message": {"content": "Ảnh hiển thị một menu trò chơi."}}


class _Lease:
    def __init__(self) -> None:
        self.asserted = False
        self.released = False
        self.assert_count = 0
        self.release_count = 0

    def assert_active(self) -> None:
        self.asserted = True
        self.assert_count += 1

    async def release(self) -> bool:
        self.released = True
        self.release_count += 1
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
        self.assertEqual(
            provider.config.public_status()["recoveryOutputTokens"],
            768,
        )
        self.assertEqual(provider.config.public_status()["maximumAttempts"], 2)
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
        self.assertIs(chat["payload"]["think"], False)
        image = chat["payload"]["messages"][0]["images"][0]  # type: ignore[index]
        self.assertEqual(
            base64.b64decode(image),
            b"\x89PNG\r\n\x1a\nowner-pixels",
        )
        self.assertNotIn("private", result)

    async def test_empty_first_response_gets_one_bounded_recovery_attempt(self) -> None:
        fake = _SequencedChatOllama(
            [
                {
                    "message": {"thinking": "private-first", "content": ""},
                    "done": True,
                    "done_reason": "length",
                    "eval_count": 256,
                },
                {
                    "message": {
                        "thinking": "private-second",
                        "content": (
                            "Ảnh hiển thị bảng điều khiển Hina với trang kiểm "
                            "tra giọng nói."
                        ),
                    },
                    "done": True,
                    "done_reason": "stop",
                    "eval_count": 72,
                },
            ]
        )
        provider = OllamaVisionProvider(
            VisionConfig(),
            request_json=fake.request,
        )
        await provider.configure(
            provider="ollama_cloud",
            model="qwen3-vl:2b",
            api_key="owner-cloud-secret",
        )
        result = await provider.analyze(
            b"\x89PNG\r\n\x1a\nowner-pixels",
            "Mô tả ảnh.",
        )
        self.assertEqual(
            result,
            "Ảnh hiển thị bảng điều khiển Hina với trang kiểm tra giọng nói.",
        )
        self.assertNotIn("private", result)
        chats = [call for call in fake.calls if call["url"].endswith("/api/chat")]
        self.assertEqual(len(chats), 2)
        first_payload = chats[0]["payload"]
        second_payload = chats[1]["payload"]
        assert first_payload is not None
        assert second_payload is not None
        self.assertIs(first_payload["think"], False)
        self.assertIs(second_payload["think"], False)
        self.assertEqual(first_payload["options"]["num_predict"], 512)  # type: ignore[index]
        self.assertEqual(second_payload["options"]["num_predict"], 768)  # type: ignore[index]
        recovery_prompt = second_payload["messages"][0]["content"]  # type: ignore[index]
        self.assertIn("Yêu cầu phục hồi", recovery_prompt)
        self.assertIn("6 đến 8 câu", recovery_prompt)
        self.assertNotIn("private-first", recovery_prompt)

    async def test_partial_length_response_is_not_accepted_as_complete(self) -> None:
        fake = _SequencedChatOllama(
            [
                {
                    "message": {"content": ": bên trái là giao diện với"},
                    "done": True,
                    "done_reason": "length",
                    "eval_count": 256,
                },
                {
                    "message": {
                        "content": (
                            "Ảnh có giao diện ElevenLabs, gồm danh sách bản thu "
                            "và phần cài đặt giọng ở bên phải."
                        ),
                    },
                    "done": True,
                    "done_reason": "stop",
                    "eval_count": 84,
                },
            ]
        )
        provider = OllamaVisionProvider(
            VisionConfig(),
            request_json=fake.request,
        )
        await provider.configure(
            provider="ollama_cloud",
            model="qwen3-vl:2b",
            api_key="owner-cloud-secret",
        )
        result = await provider.analyze(
            b"\x89PNG\r\n\x1a\nowner-pixels",
            "Mô tả ảnh.",
        )
        self.assertNotIn(": bên trái là giao diện với", result)
        self.assertIn("ElevenLabs", result)

    async def test_two_empty_responses_fail_with_stable_code(self) -> None:
        fake = _SequencedChatOllama(
            [
                {"message": {"thinking": "private", "content": ""}},
                {"message": {"thinking": "private-again", "content": "  "}},
            ]
        )
        provider = OllamaVisionProvider(
            VisionConfig(),
            request_json=fake.request,
        )
        await provider.configure(
            provider="ollama_cloud",
            model="qwen3-vl:2b",
            api_key="owner-cloud-secret",
        )
        with self.assertRaises(PerceptionError) as raised:
            await provider.analyze(
                b"\x89PNG\r\n\x1a\nowner-pixels",
                "Mô tả ảnh.",
            )
        self.assertEqual(raised.exception.code, "E_PERCEPTION_VISION_EMPTY")
        self.assertNotIn("private", str(raised.exception))
        chats = [call for call in fake.calls if call["url"].endswith("/api/chat")]
        self.assertEqual(len(chats), 2)

    async def test_two_exhausted_responses_fail_as_truncated(self) -> None:
        fake = _SequencedChatOllama(
            [
                {
                    "message": {"content": "Đoạn đầu"},
                    "done_reason": "length",
                    "eval_count": 256,
                },
                {
                    "message": {"content": "Vẫn chưa hoàn tất"},
                    "done_reason": "length",
                    "eval_count": 768,
                },
            ]
        )
        provider = OllamaVisionProvider(
            VisionConfig(),
            request_json=fake.request,
        )
        await provider.configure(
            provider="ollama_cloud",
            model="qwen3-vl:2b",
            api_key="owner-cloud-secret",
        )
        with self.assertRaises(PerceptionError) as raised:
            await provider.analyze(
                b"\x89PNG\r\n\x1a\nowner-pixels",
                "Mô tả ảnh.",
            )
        self.assertEqual(raised.exception.code, "E_PERCEPTION_VISION_TRUNCATED")

    async def test_provider_error_is_not_retried(self) -> None:
        fake = _SequencedChatOllama(
            [
                PerceptionError(
                    "E_PERCEPTION_VISION_AUTH",
                    "Ollama Cloud rejected the API key",
                )
            ]
        )
        provider = OllamaVisionProvider(
            VisionConfig(),
            request_json=fake.request,
        )
        await provider.configure(
            provider="ollama_cloud",
            model="qwen3-vl:2b",
            api_key="owner-cloud-secret",
        )
        with self.assertRaises(PerceptionError) as raised:
            await provider.analyze(
                b"\x89PNG\r\n\x1a\nowner-pixels",
                "Mô tả ảnh.",
            )
        self.assertEqual(raised.exception.code, "E_PERCEPTION_VISION_AUTH")
        chats = [call for call in fake.calls if call["url"].endswith("/api/chat")]
        self.assertEqual(len(chats), 1)

    async def test_invalid_chat_shape_is_protocol_error_without_retry(self) -> None:
        fake = _SequencedChatOllama([{"done": True, "done_reason": "stop"}])
        provider = OllamaVisionProvider(
            VisionConfig(),
            request_json=fake.request,
        )
        await provider.configure(
            provider="ollama_cloud",
            model="qwen3-vl:2b",
            api_key="owner-cloud-secret",
        )
        with self.assertRaises(PerceptionError) as raised:
            await provider.analyze(
                b"\x89PNG\r\n\x1a\nowner-pixels",
                "Mô tả ảnh.",
            )
        self.assertEqual(raised.exception.code, "E_PERCEPTION_VISION_PROTOCOL")
        chats = [call for call in fake.calls if call["url"].endswith("/api/chat")]
        self.assertEqual(len(chats), 1)

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

    async def test_local_recovery_uses_one_lease_for_both_attempts(self) -> None:
        fake = _SequencedChatOllama(
            [
                {
                    "message": {"content": ""},
                    "done_reason": "length",
                    "eval_count": 256,
                },
                {
                    "message": {"content": "Ảnh hiển thị menu trò chơi."},
                    "done_reason": "stop",
                    "eval_count": 31,
                },
            ]
        )
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
        await provider.configure(
            provider="ollama_local",
            model="qwen3-vl:2b",
            api_key=None,
        )
        result = await provider.analyze(
            b"\x89PNG\r\n\x1a\nowner-pixels",
            "Mô tả ảnh.",
        )
        self.assertEqual(result, "Ảnh hiển thị menu trò chơi.")
        self.assertEqual(len(leases), 1)
        self.assertEqual(leases[0].assert_count, 2)
        self.assertEqual(leases[0].release_count, 1)

    async def test_manual_local_warmup_holds_one_lease_until_unload(self) -> None:
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
        await provider.configure(
            provider="ollama_local",
            model="qwen3-vl:2b",
            api_key=None,
        )
        await provider.warmup()
        self.assertTrue((await provider.status())["operatorResident"])
        self.assertEqual(len(leases), 1)

        result = await provider.analyze(
            b"\x89PNG\r\n\x1a\nowner-pixels",
            "Mô tả ảnh.",
        )
        self.assertEqual(result, "Trong ảnh có một cửa sổ game.")
        self.assertEqual(leases[0].release_count, 0)
        chat = next(call for call in fake.calls if call["url"].endswith("/api/chat"))
        assert chat["payload"] is not None
        self.assertEqual(chat["payload"]["keep_alive"], -1)

        await provider.unload()
        self.assertFalse((await provider.status())["operatorResident"])
        self.assertEqual(leases[0].release_count, 1)

    async def test_unload_waits_for_active_local_analysis(self) -> None:
        fake = _BlockingLocalChatOllama()
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
        await provider.configure(
            provider="ollama_local",
            model="qwen3-vl:2b",
            api_key=None,
        )
        analysis = asyncio.create_task(
            provider.analyze(b"\x89PNG\r\n\x1a\nowner-pixels", "Mô tả ảnh.")
        )
        await asyncio.wait_for(fake.chat_started.wait(), timeout=0.5)
        unloading = asyncio.create_task(provider.unload())
        await asyncio.sleep(0)
        self.assertFalse(unloading.done())
        self.assertFalse(
            any(call["url"].endswith("/api/generate") for call in fake.calls)
        )

        fake.allow_chat_completion.set()
        self.assertEqual(await analysis, "Ảnh hiển thị một menu trò chơi.")
        await asyncio.wait_for(unloading, timeout=0.5)
        self.assertEqual(len(leases), 1)
        self.assertEqual(leases[0].release_count, 1)
        unload_calls = [call for call in fake.calls if call["url"].endswith("/api/generate")]
        self.assertEqual(len(unload_calls), 1)
        self.assertEqual(
            unload_calls[0]["payload"],
            {"model": "qwen3-vl:2b", "keep_alive": 0},
        )

    async def test_recovery_budget_cannot_be_lower_than_initial_budget(self) -> None:
        with self.assertRaises(PerceptionError) as raised:
            VisionConfig(
                max_output_tokens=512,
                recovery_output_tokens=256,
            )
        self.assertEqual(raised.exception.code, "E_PERCEPTION_VISION_CONFIG")

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
