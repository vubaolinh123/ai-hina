from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hina_text_brain import (  # noqa: E402
    LocalResourceRequest,
    LocalResourceScheduler,
    ModelGatewayConfig,
    ProviderKind,
    TelemetrySnapshot,
    TextBrainError,
)
from hina_text_brain.resource import _parse_nvidia_smi_output  # noqa: E402


class MutableTelemetry:
    def __init__(self, *, free_vram: int = 12_000, free_ram: int = 24_000) -> None:
        self.free_vram = free_vram
        self.free_ram = free_ram

    async def snapshot(self) -> TelemetrySnapshot:
        return TelemetrySnapshot(
            gpu_name="Test GPU",
            total_vram_mib=16_000,
            free_vram_mib=self.free_vram,
            total_ram_mib=32_000,
            free_ram_mib=self.free_ram,
        )


class ConfigTests(unittest.TestCase):
    def test_config_accepts_loopback_and_never_exposes_api_key(self) -> None:
        default = ModelGatewayConfig()
        self.assertEqual(default.model, "qwen3-vl:8b-thinking-q4_K_M")
        self.assertEqual(default.request_timeout_seconds, 9.0)
        self.assertEqual(default.warmup_timeout_seconds, 45.0)
        self.assertEqual(default.retry_attempts, 0)
        self.assertEqual(default.model_vram_mib, 8_192)
        config = ModelGatewayConfig(
            provider=ProviderKind.OPENAI_COMPATIBLE,
            base_url="http://localhost:1234/v1",
            model="local-model",
            api_key="owner-secret",
        )
        status = config.public_status()
        self.assertTrue(status["apiKeyConfigured"])
        self.assertNotIn("owner-secret", str(status))
        self.assertEqual(config.max_tokens, 192)
        self.assertEqual(status["maxTokens"], 192)
        self.assertEqual(config.vision_fast_max_tokens, 256)
        self.assertEqual(status["visionFastMaxTokens"], 256)
        self.assertEqual(config.thinking_max_tokens, 768)
        self.assertEqual(status["thinkingMaxTokens"], 768)
        self.assertEqual(config.context_tokens, 8_192)
        self.assertEqual(status["contextTokens"], 8_192)
        self.assertEqual(status["admissionTimeoutSeconds"], 1.0)
        self.assertEqual(status["defaultTurnDeadlineSeconds"], 10.0)
        self.assertEqual(status["warmupTimeoutSeconds"], 45.0)
        self.assertEqual(status["admissionCeilingMiB"], 15_872)
        self.assertEqual(status["reservedVramHeadroomMiB"], 0)
        self.assertEqual(config.temperature, 0.7)
        self.assertEqual(status["temperature"], 0.7)
        self.assertEqual(config.repeat_penalty, 1.15)
        self.assertEqual(status["repeatPenalty"], 1.15)
        self.assertEqual(status["reasoningPolicy"], "deterministic-auto")
        self.assertFalse(status["hiddenReasoningExposed"])
        self.assertEqual(config.endpoint_path("chat"), "/v1/chat/completions")
        self.assertEqual(default.endpoint_path("resident"), "/api/ps")

    def test_config_rejects_remote_or_credentialed_endpoint(self) -> None:
        for url in (
            "https://example.com/v1",
            "http://user:pass@127.0.0.1:1234",
            "http://127.0.0.1:1234/v2",
        ):
            with self.subTest(url=url), self.assertRaises(TextBrainError):
                ModelGatewayConfig(base_url=url)

    def test_config_rejects_invalid_persona_sampling_values(self) -> None:
        for field, value in (
            ("temperature", True),
            ("temperature", 2.1),
            ("warmup_timeout_seconds", 2.9),
            ("warmup_timeout_seconds", 120.1),
            ("repeat_penalty", True),
            ("repeat_penalty", 0),
            ("repeat_penalty", 2.1),
            ("context_tokens", 512),
            ("ollama_gpu_layers", 0),
            ("vision_fast_max_tokens", 0),
            ("thinking_max_tokens", 191),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(TextBrainError):
                ModelGatewayConfig(**{field: value})


class ResourceSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_monitor_status_separates_physical_use_and_active_leases(self) -> None:
        scheduler = LocalResourceScheduler(
            MutableTelemetry(free_vram=11_000),
            clock=lambda: 100.0,
        )
        await scheduler.acquire(
            LocalResourceRequest(
                owner="tts.omnivoice",
                vram_mib=3_072,
                ram_mib=6_144,
                priority=60,
                ttl_seconds=90,
                preemptible=True,
            )
        )
        status = await scheduler.monitor_status()
        self.assertTrue(status["available"])
        self.assertEqual(status["telemetry"]["usedVramMiB"], 5_000)
        self.assertEqual(status["reservedVramMiB"], 3_072)
        self.assertEqual(status["activeLeases"], 1)
        self.assertEqual(
            status["leases"],
            [
                {
                    "owner": "tts.omnivoice",
                    "state": "active",
                    "reservedVramMiB": 3_072,
                    "reservedRamMiB": 6_144,
                    "priority": 60,
                    "preemptible": True,
                    "remainingTtlSeconds": 90.0,
                }
            ],
        )
        self.assertNotIn("leaseId", str(status))

    async def test_live_admission_uses_actual_free_vram_without_double_reserve(self) -> None:
        telemetry = MutableTelemetry(free_vram=10_000)
        scheduler = LocalResourceScheduler(telemetry)
        lease = await scheduler.acquire(
            LocalResourceRequest(owner="model.text", vram_mib=4_096, ram_mib=1_024)
        )
        snapshot = await scheduler.snapshot()
        self.assertEqual(snapshot.active_leases, 1)
        self.assertEqual(snapshot.admission_ceiling_mib, 15_872)
        self.assertEqual(snapshot.live_free_reserve_mib, 0)
        self.assertEqual(snapshot.available_vram_mib, 10_000)
        self.assertTrue(await lease.release())
        self.assertFalse(await lease.release())

        with self.assertRaises(TextBrainError) as raised:
            await scheduler.acquire(
                LocalResourceRequest(owner="model.large", vram_mib=10_001, ram_mib=1_024)
            )
        self.assertEqual(raised.exception.code, "E_RESOURCE_CAPACITY")

    async def test_static_15_point_5_gib_ceiling_still_applies_when_gpu_is_idle(self) -> None:
        scheduler = LocalResourceScheduler(MutableTelemetry(free_vram=16_000))
        snapshot = await scheduler.snapshot()
        self.assertEqual(snapshot.available_vram_mib, 15_872)
        with self.assertRaises(TextBrainError) as raised:
            await scheduler.acquire(
                LocalResourceRequest(owner="model.too-large", vram_mib=15_873, ram_mib=1_024)
            )
        self.assertEqual(raised.exception.code, "E_RESOURCE_CAPACITY")

    async def test_wait_timeout_is_bounded(self) -> None:
        scheduler = LocalResourceScheduler(MutableTelemetry(free_vram=3_000))
        started = asyncio.get_running_loop().time()
        with self.assertRaises(TextBrainError) as raised:
            await scheduler.acquire(
                LocalResourceRequest(owner="model.waiting", vram_mib=3_001, ram_mib=512),
                wait_timeout_seconds=0.03,
            )
        self.assertEqual(raised.exception.code, "E_RESOURCE_CAPACITY")
        self.assertLess(asyncio.get_running_loop().time() - started, 0.5)

    async def test_higher_priority_request_preempts_and_unloads_lower_priority(self) -> None:
        telemetry = MutableTelemetry(free_vram=7_000)
        scheduler = LocalResourceScheduler(telemetry)
        unloaded = asyncio.Event()

        async def unload_low_priority() -> None:
            telemetry.free_vram = 11_000
            unloaded.set()

        low = await scheduler.acquire(
            LocalResourceRequest(
                owner="model.optional",
                vram_mib=4_000,
                ram_mib=512,
                priority=20,
                preemptible=True,
            ),
            on_preempt=unload_low_priority,
        )
        high = await scheduler.acquire(
            LocalResourceRequest(
                owner="model.text",
                vram_mib=8_000,
                ram_mib=512,
                priority=90,
            ),
            wait_timeout_seconds=0.2,
        )
        self.assertTrue(unloaded.is_set())
        self.assertEqual(low.state, "preempted")
        self.assertEqual(high.state, "active")
        self.assertEqual((await scheduler.snapshot()).active_leases, 1)


class NvidiaTelemetryParsingTests(unittest.TestCase):
    def test_parser_exposes_optional_gpu_metrics(self) -> None:
        snapshot = _parse_nvidia_smi_output(
            b"NVIDIA GeForce RTX 5070 Ti, 16303, 4476, 11520, 4, 45, 33.57\r\n",
            total_ram_mib=64_000,
            free_ram_mib=40_000,
        )
        status = snapshot.as_json()
        self.assertEqual(status["usedVramMiB"], 4_476)
        self.assertEqual(status["gpuUtilizationPercent"], 4.0)
        self.assertEqual(status["temperatureCelsius"], 45.0)
        self.assertEqual(status["powerDrawWatts"], 33.57)
        self.assertEqual(status["usedRamMiB"], 24_000)

    def test_parser_keeps_unsupported_values_unknown(self) -> None:
        snapshot = _parse_nvidia_smi_output(
            b"Test GPU, 16000, [N/A], 12000, N/A, N/A, N/A\n",
            total_ram_mib=32_000,
            free_ram_mib=20_000,
        )
        status = snapshot.as_json()
        self.assertEqual(status["usedVramMiB"], 4_000)
        self.assertIsNone(status["gpuUtilizationPercent"])
        self.assertIsNone(status["temperatureCelsius"])
        self.assertIsNone(status["powerDrawWatts"])

    def test_parser_rejects_unbounded_or_malformed_output(self) -> None:
        for raw in (
            b"",
            b"GPU, 16000, 1000\n",
            b"GPU, 16000, nope, 15000, 5, 40, 20\n",
            b"GPU, 16000, 1000, 15000, 101, 40, 20\n",
        ):
            with self.subTest(raw=raw), self.assertRaises(TextBrainError):
                _parse_nvidia_smi_output(
                    raw,
                    total_ram_mib=32_000,
                    free_ram_mib=20_000,
                )


if __name__ == "__main__":
    unittest.main()
