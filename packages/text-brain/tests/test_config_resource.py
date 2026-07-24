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
        config = ModelGatewayConfig(
            provider=ProviderKind.OPENAI_COMPATIBLE,
            base_url="http://localhost:1234/v1",
            model="local-model",
            api_key="owner-secret",
        )
        status = config.public_status()
        self.assertTrue(status["apiKeyConfigured"])
        self.assertNotIn("owner-secret", str(status))
        self.assertEqual(config.endpoint_path("chat"), "/v1/chat/completions")

    def test_config_rejects_remote_or_credentialed_endpoint(self) -> None:
        for url in (
            "https://example.com/v1",
            "http://user:pass@127.0.0.1:1234",
            "http://127.0.0.1:1234/v2",
        ):
            with self.subTest(url=url), self.assertRaises(TextBrainError):
                ModelGatewayConfig(base_url=url)


class ResourceSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_admission_preserves_headroom_and_release_is_idempotent(self) -> None:
        telemetry = MutableTelemetry(free_vram=10_000)
        scheduler = LocalResourceScheduler(telemetry)
        lease = await scheduler.acquire(
            LocalResourceRequest(owner="model.text", vram_mib=4_096, ram_mib=1_024)
        )
        snapshot = await scheduler.snapshot()
        self.assertEqual(snapshot.active_leases, 1)
        self.assertGreaterEqual(
            snapshot.telemetry.free_vram_mib - lease.request.vram_mib,
            2_048,
        )
        self.assertTrue(await lease.release())
        self.assertFalse(await lease.release())

        with self.assertRaises(TextBrainError) as raised:
            await scheduler.acquire(
                LocalResourceRequest(owner="model.large", vram_mib=8_000, ram_mib=1_024)
            )
        self.assertEqual(raised.exception.code, "E_RESOURCE_CAPACITY")

    async def test_wait_timeout_is_bounded(self) -> None:
        scheduler = LocalResourceScheduler(MutableTelemetry(free_vram=3_000))
        started = asyncio.get_running_loop().time()
        with self.assertRaises(TextBrainError) as raised:
            await scheduler.acquire(
                LocalResourceRequest(owner="model.waiting", vram_mib=2_000, ram_mib=512),
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
                vram_mib=5_000,
                ram_mib=512,
                priority=90,
            ),
            wait_timeout_seconds=0.2,
        )
        self.assertTrue(unloaded.is_set())
        self.assertEqual(low.state, "preempted")
        self.assertEqual(high.state, "active")
        self.assertEqual((await scheduler.snapshot()).active_leases, 1)


if __name__ == "__main__":
    unittest.main()
