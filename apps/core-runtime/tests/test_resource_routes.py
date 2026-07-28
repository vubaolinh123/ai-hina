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
from hina_core.runtime.transport_client import get_json, post_json  # noqa: E402


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
            "headroomMiB": 0,
            "admissionCeilingMiB": 15_872,
            "liveFreeReserveMiB": 0,
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
        self.controls: list[str] = []
        self.operator_resident = False
        self.deny_next_warmup = False

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
            "operatorResident": self.operator_resident,
        }

    async def warmup(self) -> dict[str, object]:
        if self.deny_next_warmup:
            self.deny_next_warmup = False
            raise _ResourceDenied()
        self.controls.append("load")
        self.operator_resident = True
        return {"state": "loaded", "operatorResident": True}

    async def unload(self) -> None:
        self.controls.append("unload")
        self.operator_resident = False

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
        self.controls: list[str] = []

    async def status(self) -> dict[str, object]:
        return self._status

    async def warmup(self) -> dict[str, object]:
        self.controls.append("load")
        return self._status

    async def unload(self) -> None:
        self.controls.append("unload")

    async def warmup_ocr(self) -> dict[str, object]:
        self.controls.append("load")
        return self._status

    async def unload_ocr(self) -> dict[str, object]:
        self.controls.append("unload")
        return self._status

    async def warmup_vision(self) -> dict[str, object]:
        self.controls.append("load")
        return self._status

    async def unload_vision(self) -> dict[str, object]:
        self.controls.append("unload")
        return self._status


class _ResourceDenied(Exception):
    code = "E_RESOURCE_CAPACITY"
    detail = "resource admission would violate local headroom"


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
                        "lastPeakReservedMiB": 2_412.5,
                        "lastPostAllocatedMiB": 2_275.0,
                        "lastErrorCode": None,
                    },
                }
            ),
            perception_service=_Service(
                {
                    "available": True,
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
        self.assertEqual(body["limits"]["allOnVramCeilingMiB"], 15_872)
        self.assertEqual(body["limits"]["minimumFreeVramMiB"], 0)
        self.assertIn("already excludes Windows", body["semantics"]["liveFree"])
        self.assertLessEqual(len(body["models"]), 5)
        models = {item["id"]: item for item in body["models"]}
        self.assertEqual(models["brain.text"]["state"], "loaded")
        self.assertEqual(models["brain.text"]["measuredVramMiB"], 7_516)
        self.assertEqual(
            models["brain.text"]["measurementSource"],
            "ollama.api.ps.size_vram",
        )
        self.assertIsNone(models["brain.text"]["providerPeakVramMiB"])
        self.assertEqual(models["speech.stt"]["state"], "unloaded")
        self.assertEqual(models["speech.stt"]["measurementSource"], "unavailable")
        self.assertEqual(models["speech.tts"]["state"], "loaded")
        self.assertEqual(models["speech.tts"]["measuredVramMiB"], 2_275.0)
        self.assertEqual(models["speech.tts"]["providerPeakVramMiB"], 2_412.5)
        self.assertNotIn("perception.ocr", models)
        self.assertEqual(models["perception.vision"]["state"], "cloud-ready")
        self.assertEqual(models["perception.vision"]["configuredVramMiB"], 0)
        self.assertEqual(models["perception.vision"]["measuredVramMiB"], 0)
        self.assertEqual(models["perception.vision"]["providerPeakVramMiB"], 0)
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

    async def test_owner_can_control_allowlisted_model_and_malformed_request_is_rejected(self) -> None:
        host, port = self.server.address
        loaded = await post_json(
            host,
            port,
            "/v1/resources/models/control",
            {
                "modelId": "brain.text",
                "action": "load",
                "source": "owner.desktop",
                "ownerConfirmed": True,
            },
        )
        self.assertEqual(loaded.status, HTTPStatus.OK)
        self.assertEqual(loaded.body["status"], "loaded")
        self.assertIn("load", self.server.model_gateway.controls)
        models = {item["id"]: item for item in loaded.body["resources"]["models"]}
        self.assertTrue(models["brain.text"]["operatorResident"])

        unloaded = await post_json(
            host,
            port,
            "/v1/resources/models/control",
            {
                "modelId": "brain.text",
                "action": "unload",
                "source": "owner.desktop",
                "ownerConfirmed": True,
            },
        )
        self.assertEqual(unloaded.status, HTTPStatus.OK)
        self.assertEqual(unloaded.body["status"], "unloaded")
        self.assertIn("unload", self.server.model_gateway.controls)
        models = {item["id"]: item for item in unloaded.body["resources"]["models"]}
        self.assertFalse(models["brain.text"]["operatorResident"])

        malformed = await post_json(
            host,
            port,
            "/v1/resources/models/control",
            {
                "modelId": "arbitrary-shell-model",
                "action": "load",
                "source": "owner.desktop",
                "ownerConfirmed": True,
            },
        )
        self.assertEqual(malformed.status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(malformed.body["errorCode"], "E_HTTP_BAD_REQUEST")

    async def test_scheduler_denial_is_returned_as_a_bounded_service_error(self) -> None:
        self.server.model_gateway.deny_next_warmup = True
        host, port = self.server.address
        denied = await post_json(
            host,
            port,
            "/v1/resources/models/control",
            {
                "modelId": "brain.text",
                "action": "load",
                "source": "owner.desktop",
                "ownerConfirmed": True,
            },
        )
        self.assertEqual(denied.status, HTTPStatus.SERVICE_UNAVAILABLE)
        self.assertEqual(denied.body["errorCode"], "E_RESOURCE_CAPACITY")
        self.assertNotIn("Traceback", str(denied.body))

    async def test_cloud_model_control_is_explicit_noop(self) -> None:
        host, port = self.server.address
        response = await post_json(
            host,
            port,
            "/v1/resources/models/control",
            {
                "modelId": "perception.vision",
                "action": "load",
                "source": "owner.desktop",
                "ownerConfirmed": True,
            },
        )
        self.assertEqual(response.status, HTTPStatus.OK)
        self.assertTrue(response.body["noOp"])
        self.assertEqual(response.body["status"], "cloud-ready")


if __name__ == "__main__":
    unittest.main()
