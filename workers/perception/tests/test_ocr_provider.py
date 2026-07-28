from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hina_perception import OcrConfig, PerceptionError, RapidOcrProvider, ScheduledOcrProvider


class _FakeEngine:
    def __init__(self, *, device: str = "cuda:0") -> None:
        session = SimpleNamespace(device=device)
        self.text_det = SimpleNamespace(session=session)
        self.text_rec = SimpleNamespace(session=session)
        self.text_cls = SimpleNamespace(session=session)
        self.calls: list[bytes] = []

    def __call__(self, encoded: bytes, *, use_cls: bool) -> object:
        self.calls.append(encoded)
        assert use_cls is False
        return SimpleNamespace(
            img=SimpleNamespace(shape=(100, 200, 3)),
            boxes=[[[20, 20], [180, 20], [180, 50], [20, 50]]],
            txts=(" Hina\x00 đang quan sát ",),
            scores=(0.98765,),
        )


class _FakeLease:
    state = "active"

    def __init__(self) -> None:
        self.released = False

    def assert_active(self) -> None:
        if self.released:
            raise RuntimeError("released")

    async def release(self) -> bool:
        self.released = True
        self.state = "released"
        return True


class _FakeProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.unloaded = 0
        self.closed = False

    async def status(self) -> dict[str, object]:
        return {"provider": "fake", "available": True}

    async def recognize(self, _encoded: bytes) -> dict[str, object]:
        self.calls += 1
        return {"state": "ready", "text": "đúng"}

    async def unload(self) -> None:
        self.unloaded += 1

    async def close(self) -> None:
        self.closed = True


class OcrConfigTests(unittest.TestCase):
    def test_cuda_only_config_rejects_cpu_and_invalid_headroom_inputs(self) -> None:
        root = Path.cwd()
        with self.assertRaises(PerceptionError) as cpu:
            OcrConfig(root=root, cache_dir=root / "var" / "cache", device="cpu")
        self.assertEqual(cpu.exception.code, "E_PERCEPTION_CONFIG")
        with self.assertRaises(PerceptionError):
            OcrConfig(root=root, cache_dir=root / "var" / "cache", model_vram_mib=128)

    def test_env_keeps_model_cache_inside_project_and_disables_cpu_fallback(self) -> None:
        root = Path.cwd()
        config = OcrConfig.from_env(root=root, env={"HINA_OCR_ALLOW_DOWNLOAD": "false"})
        self.assertEqual(config.cache_dir, root / "var" / "models" / "rapidocr-ppocrv6-small")
        self.assertFalse(config.allow_download)
        self.assertFalse(config.public_status()["cpuFallback"])


class RapidOcrProviderTests(unittest.TestCase):
    def _config(self) -> tuple[tempfile.TemporaryDirectory[str], OcrConfig]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        return temporary, OcrConfig(root=root, cache_dir=root / "var" / "cache")

    def test_provider_uses_only_cuda_serializes_bounded_text_and_discards_image(self) -> None:
        temporary, config = self._config()
        try:
            engine = _FakeEngine()
            ensured: list[object] = []
            params_seen: dict[str, object] = {}
            provider = RapidOcrProvider(
                config,
                engine_factory=lambda params: params_seen.update(params) or engine,
                artifact_ensurer=lambda artifacts, _config: ensured.extend(artifacts),
                cuda_available=lambda: True,
            )
            result = asyncio.run(provider.recognize(b"tiny-png"))
            self.assertEqual(len(ensured), 4)
            self.assertEqual(engine.calls, [b"tiny-png"])
            self.assertEqual(result["state"], "ready")
            self.assertEqual(result["effectiveDevice"], "cuda:0")
            self.assertEqual(result["text"], "Hina đang quan sát")
            self.assertEqual(result["lineCount"], 1)
            self.assertEqual(result["lines"][0]["box"], [0.1, 0.2, 0.9, 0.2, 0.9, 0.5, 0.1, 0.5])
            self.assertEqual(params_seen["EngineConfig.torch.use_cuda"], True)
            self.assertEqual(params_seen["Rec.lang_type"], "vi")
            self.assertNotIn("img", result)
            self.assertNotIn("tiny-png", str(result))
            status = asyncio.run(provider.status())
            self.assertTrue(status["modelLoaded"])
            self.assertEqual(status["effectiveDevice"], "cuda:0")
            self.assertFalse(status["qualityGatePassed"])
            asyncio.run(provider.close())
        finally:
            temporary.cleanup()

    def test_provider_fails_closed_when_cuda_is_unavailable_or_engine_uses_cpu(self) -> None:
        temporary, config = self._config()
        try:
            unavailable = RapidOcrProvider(config, cuda_available=lambda: False)
            with self.assertRaises(PerceptionError) as caught:
                asyncio.run(unavailable.recognize(b"tiny-png"))
            self.assertEqual(caught.exception.code, "E_PERCEPTION_OCR_CUDA")
            asyncio.run(unavailable.close())

            cpu_engine = _FakeEngine(device="cpu")
            provider = RapidOcrProvider(
                config,
                engine_factory=lambda _params: cpu_engine,
                artifact_ensurer=lambda _artifacts, _config: None,
                cuda_available=lambda: True,
            )
            with self.assertRaises(PerceptionError) as engine_error:
                asyncio.run(provider.recognize(b"tiny-png"))
            self.assertEqual(engine_error.exception.code, "E_PERCEPTION_OCR_CUDA")
            asyncio.run(provider.close())
        finally:
            temporary.cleanup()

    def test_scheduled_provider_keeps_one_lease_and_unloads_on_close(self) -> None:
        provider = _FakeProvider()
        leases: list[_FakeLease] = []

        async def acquire(_unload):
            lease = _FakeLease()
            leases.append(lease)
            return lease

        scheduled = ScheduledOcrProvider(provider, acquire)
        self.assertEqual(asyncio.run(scheduled.recognize(b"one"))["text"], "đúng")
        self.assertEqual(asyncio.run(scheduled.recognize(b"two"))["text"], "đúng")
        self.assertEqual(provider.calls, 2)
        self.assertEqual(len(leases), 1)
        asyncio.run(scheduled.close())
        self.assertTrue(leases[0].released)
        self.assertEqual(provider.unloaded, 1)
        self.assertTrue(provider.closed)


if __name__ == "__main__":
    unittest.main()
