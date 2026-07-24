from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, AsyncIterator


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hina_text_brain import (  # noqa: E402
    LocalResourceScheduler,
    ModelGateway,
    ModelGatewayConfig,
    ProviderHealth,
    TelemetrySnapshot,
    TextBrainError,
)


class StaticTelemetry:
    async def snapshot(self) -> TelemetrySnapshot:
        return TelemetrySnapshot("Test GPU", 16_000, 14_000, 32_000, 28_000)


class ScriptedProvider:
    def __init__(self, scripts: list[list[object]]) -> None:
        self.scripts = scripts
        self.calls = 0
        self.unloads = 0

    async def health(self) -> ProviderHealth:
        return ProviderHealth(True, True, "test", "test-model", ("test-model",))

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        script = self.scripts[self.calls]
        self.calls += 1
        for item in script:
            if isinstance(item, Exception):
                raise item
            yield str(item)

    async def unload(self) -> None:
        self.unloads += 1


async def _collect(gateway: ModelGateway) -> str:
    return "".join(
        [
            token
            async for token in gateway.stream_chat(
                [{"role": "user", "content": "Xin chào"}]
            )
        ]
    )


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_occurs_only_before_first_token(self) -> None:
        provider = ScriptedProvider(
            [
                [TextBrainError("E_MODEL_UNAVAILABLE", "offline", retryable=True)],
                ["Xin ", "chào"],
            ]
        )
        gateway = ModelGateway(
            ModelGatewayConfig(
                model="test-model",
                retry_attempts=1,
                model_vram_mib=1_024,
            ),
            LocalResourceScheduler(StaticTelemetry()),
            provider=provider,
        )
        self.assertEqual(await _collect(gateway), "Xin chào")
        self.assertEqual(provider.calls, 2)
        self.assertEqual((await gateway.status())["circuit"]["state"], "closed")

    async def test_partial_stream_is_not_replayed(self) -> None:
        provider = ScriptedProvider(
            [
                ["partial", TextBrainError("E_MODEL_UNAVAILABLE", "lost", retryable=True)],
                ["must-not-run"],
            ]
        )
        gateway = ModelGateway(
            ModelGatewayConfig(
                model="test-model",
                retry_attempts=1,
                model_vram_mib=1_024,
            ),
            LocalResourceScheduler(StaticTelemetry()),
            provider=provider,
        )
        tokens: list[str] = []
        with self.assertRaises(TextBrainError):
            async for token in gateway.stream_chat(
                [{"role": "user", "content": "test"}]
            ):
                tokens.append(token)
        self.assertEqual(tokens, ["partial"])
        self.assertEqual(provider.calls, 1)

    async def test_circuit_opens_then_allows_one_recovery_probe(self) -> None:
        current_time = 100.0
        provider = ScriptedProvider(
            [
                [TextBrainError("E_MODEL_UNAVAILABLE", "offline", retryable=True)],
                [TextBrainError("E_MODEL_UNAVAILABLE", "offline", retryable=True)],
                ["recovered"],
            ]
        )
        config = ModelGatewayConfig(
            model="test-model",
            retry_attempts=0,
            circuit_failure_threshold=2,
            circuit_reset_seconds=5,
            model_vram_mib=1_024,
        )
        gateway = ModelGateway(
            config,
            LocalResourceScheduler(StaticTelemetry()),
            provider=provider,
            clock=lambda: current_time,
        )
        for _ in range(2):
            with self.assertRaises(TextBrainError):
                await _collect(gateway)
        with self.assertRaises(TextBrainError) as opened:
            await _collect(gateway)
        self.assertEqual(opened.exception.code, "E_MODEL_CIRCUIT_OPEN")
        self.assertEqual(provider.calls, 2)

        current_time += 6
        self.assertEqual(await _collect(gateway), "recovered")
        self.assertEqual((await gateway.status())["circuit"]["state"], "closed")


if __name__ == "__main__":
    unittest.main()
