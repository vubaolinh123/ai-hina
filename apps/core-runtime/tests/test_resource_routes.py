from __future__ import annotations

import sys
import unittest
from http import HTTPStatus
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(APP_ROOT / "src"))

from hina_core.runtime.transport import ControlPlaneServer, TransportConfig  # noqa: E402
from hina_core.runtime.transport_client import get_json  # noqa: E402


class _Scheduler:
    async def monitor_status(self) -> dict[str, object]:
        return {
            "available": True,
            "telemetry": {
                "gpuName": "Test GPU",
                "totalVramMiB": 16_303,
                "usedVramMiB": 8_500,
                "freeVramMiB": 7_803,
                "totalRamMiB": 65_536,
                "usedRamMiB": 20_000,
                "freeRamMiB": 45_536,
                "gpuUtilizationPercent": 42.0,
                "temperatureCelsius": 51.0,
                "powerDrawWatts": None,
            },
            "activeLeases": 1,
            "reservedVramMiB": 3_072,
            "reservedRamMiB": 6_144,
            "availableVramMiB": 5_755,
            "availableRamMiB": 45_536,
            "headroomMiB": 2_048,
            "leases": [
                {
                    "owner": "tts.omnivoice",
                    "state": "active",
                    "reservedVramMiB": 3_072,
                    "reservedRamMiB": 6_144,
                    "priority": 60,
                    "preemptible": True,
                    "remainingTtlSeconds": 110.0,
                }
            ],
        }


class _ModelGateway:
    def __init__(self) -> None:
        self.scheduler = _Scheduler()

    async def status(self) -> dict[str, object]:
        return {
            "configured": {
                "provider": "ollama",
                "model": "qwen3-vl:8b-thinking-q4_K_M",
                "modelVramMiB": 8_192,
            },
            "provider": {
                "reachable": True,
                "modelAvailable": True,
                "errorCode": None,
            },
            "available": True,
        }

    async def resident_models(self) -> list[dict[str, object]]:
        return [
            {
                "name": "qwen3-vl:8b-thinking-q4_K_M",
                "sizeVramBytes": 7_516 * 1024 * 1024,
            }
        ]


class _Service:
    def __init__(self, status: dict[str, object]) -> None:
        self._status = status

    async def status(self) -> dict[str, object]:
        return self._status


class ResourceRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = ControlPlaneServer(
            TransportConfig(port=0),
            model_gateway=_ModelGateway(),
            speech_service=_Service(
                {
                    "available": True,
                    "configured": {
                        "provider": "faster-whisper",
                        "model": "large-v3",
                        "modelVramMiB": 2_048,
                    },
                    "provider": {
                        "modelLoaded": False,
                        "lastErrorCode": None,
                    },
                }
            ),
            tts_service=_Service(
                {
                    "available": True,
                    "configured": {
                        "provider": "omnivoice",
                        "model": "k2-fsa/OmniVoice-0.6B",
                        "modelVramMiB": 3_072,
                        "referenceAudio": "D:/owner/private/anime_voice.mp3",
                    },
                    "provider": {
                        "modelLoaded": True,
                        "modelBaselineAllocatedMiB": 2_270.5,
                        "lastErrorCode": None,
                    },
                }
            ),
            perception_service=_Service(
                {
                    "available": True,
                    "ocr": {
                        "provider": "rapidocr",
                        "model": "PP-OCRv6-small",
                        "available": True,
                        "modelLoaded": False,
                        "configured": {"modelVramMiB": 1_024},
                    },
                    "vision": {
                        "provider": "ollama_cloud",
                        "model": "gemma3:4b-cloud",
                        "available": True,
                        "localGpuUsed": False,
                        "apiKeyConfigured": True,
                        "configured": {"localModelVramMiB": 5_120},
                    },
                }
            ),
        )
        await self.server.start()

    async def asyncTearDown(self) -> None:
        await self.server.stop()

    async def test_resource_status_is_bounded_truthful_and_redacted(self) -> None:
        host, port = self.server.address
        response = await get_json(host, port, "/v1/resources/status")
        self.assertEqual(response.status, HTTPStatus.OK)
        body = response.body
        self.assertEqual(body["physical"]["telemetry"]["usedVramMiB"], 8_500)
        self.assertEqual(body["physical"]["reservedVramMiB"], 3_072)
        self.assertEqual(body["limits"]["allOnVramCeilingMiB"], 14_336)
        self.assertEqual(body["limits"]["minimumFreeVramMiB"], 2_048)
        self.assertLessEqual(len(body["models"]), 5)
        models = {item["id"]: item for item in body["models"]}
        self.assertEqual(models["brain.text"]["state"], "loaded")
        self.assertEqual(models["brain.text"]["measuredVramMiB"], 7_516)
        self.assertEqual(models["speech.stt"]["state"], "unloaded")
        self.assertEqual(models["speech.tts"]["state"], "loaded")
        self.assertEqual(models["perception.vision"]["state"], "cloud-ready")
        self.assertEqual(models["perception.vision"]["configuredVramMiB"], 0)
        if sys.platform == "win32":
            self.assertIsInstance(body["processes"]["coreRuntime"]["rssMiB"], int)
            self.assertGreater(body["processes"]["coreRuntime"]["rssMiB"], 0)
        serialized = str(body)
        self.assertNotIn("anime_voice.mp3", serialized)
        self.assertNotIn("apiKeyConfigured", serialized)
        self.assertNotIn("leaseId", serialized)
        self.assertFalse(body["semantics"]["historyPersistence"])

    async def test_resource_route_degrades_when_scheduler_telemetry_fails(self) -> None:
        async def fail() -> dict[str, object]:
            raise RuntimeError("driver details must not leak")

        self.server.model_gateway.scheduler.monitor_status = fail
        host, port = self.server.address
        response = await get_json(host, port, "/v1/resources/status")
        self.assertEqual(response.status, HTTPStatus.OK)
        self.assertFalse(response.body["physical"]["available"])
        self.assertEqual(
            response.body["physical"]["errorCode"],
            "E_RESOURCE_TELEMETRY",
        )
        self.assertNotIn("driver details", str(response.body))


if __name__ == "__main__":
    unittest.main()
