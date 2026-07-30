import json
import sys
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
SAFETY_ROOT = ROOT / "packages" / "safety-policy"
TEXT_BRAIN_ROOT = ROOT / "packages" / "text-brain"
CONTRACTS_ROOT = ROOT / "packages" / "contracts"
sys.path.insert(0, str(CONTRACTS_ROOT / "src"))
sys.path.insert(0, str(SAFETY_ROOT / "src"))
sys.path.insert(0, str(TEXT_BRAIN_ROOT / "src"))
sys.path.insert(0, str(APP_ROOT / "src"))

from hina_core.runtime import TransportConfig  # noqa: E402
from hina_core.runtime.transport import ControlPlaneServer  # noqa: E402
from hina_core.runtime.transport_client import post_json  # noqa: E402
from hina_safety import AuditTrail, CapabilityManifest, SafetyPolicyService  # noqa: E402
from hina_text_brain import MinecraftGoalPlanner  # noqa: E402


MANIFEST_PATH = SAFETY_ROOT / "manifests" / "default.v1.json"
CORRELATION = "4b825dc6-42b0-4c48-8f1a-9a54f1f9f6da"


class _GoalGateway:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[list[dict[str, str]]] = []

    async def stream_chat(self, messages: list[dict[str, str]]):
        self.calls.append(messages)
        yield self.output


class MinecraftGoalRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(dir=APP_ROOT)
        directory = Path(self._temporary.name)
        self.safety = SafetyPolicyService(
            CapabilityManifest.load(MANIFEST_PATH),
            AuditTrail(directory / "audit.jsonl", build_commit="minecraft-goal-test"),
        )
        self.gateway = _GoalGateway(json.dumps({"goalId": "gather.nearby-log.v1"}))
        self.server = ControlPlaneServer(
            TransportConfig(port=0),
            safety_policy=self.safety,
            minecraft_goal_planner=MinecraftGoalPlanner(self.gateway),
        )
        await self.server.start()
        self.host, self.port = self.server.address

    async def asyncTearDown(self) -> None:
        await self.server.stop()
        self._temporary.cleanup()

    async def _enable_game_action(self) -> None:
        response = await post_json(
            self.host,
            self.port,
            "/v1/safety/control",
            {
                "action": "set_feature",
                "feature": "gameAction",
                "enabled": True,
                "actorId": "owner.desktop",
                "trustLevel": "owner",
                "correlationId": CORRELATION,
            },
        )
        self.assertEqual(response.status, HTTPStatus.OK)

    async def _plan(self, body: dict[str, object]):
        return await post_json(
            self.host,
            self.port,
            "/v1/minecraft/goals/plan",
            body,
        )

    async def test_goal_plan_denies_before_model_when_game_action_is_disabled(self) -> None:
        response = await self._plan(
            {
                "text": "Hina, chặt một khúc gỗ ở gần đi.",
                "source": "owner.desktop",
                "ownerConfirmed": True,
            }
        )

        self.assertEqual(response.status, HTTPStatus.FORBIDDEN)
        self.assertEqual(response.body["errorCode"], "E_MINECRAFT_GOAL_DENIED")
        self.assertEqual(self.gateway.calls, [])

    async def test_owner_goal_becomes_only_one_static_goal_after_safety_enable(self) -> None:
        await self._enable_game_action()
        response = await self._plan(
            {
                "text": "Hina, chặt một khúc gỗ ở gần đi.",
                "source": "owner.desktop",
                "ownerConfirmed": True,
            }
        )

        self.assertEqual(response.status, HTTPStatus.OK)
        self.assertEqual(response.body["state"], "ready")
        self.assertEqual(response.body["goalId"], "gather.nearby-log.v1")
        self.assertEqual(response.body["planVersion"], "minecraft.goal.v1")
        self.assertEqual(len(self.gateway.calls), 1)
        messages = self.gateway.calls[0]
        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        self.assertIn("OWNER_MINECRAFT_GOAL_UNTRUSTED", messages[1]["content"])
        self.assertNotIn("eval", messages[0]["content"].casefold())

    async def test_malformed_or_non_owner_goal_never_reaches_model(self) -> None:
        for body in [
            {
                "text": "chặt cây",
                "source": "owner.desktop",
                "ownerConfirmed": False,
            },
            {
                "text": "chặt cây",
                "source": "viewer.chat",
                "ownerConfirmed": True,
            },
            {
                "text": "chặt cây",
                "source": "owner.desktop",
                "ownerConfirmed": True,
                "coordinates": [1, 2],
            },
        ]:
            response = await self._plan(body)
            self.assertEqual(response.status, HTTPStatus.BAD_REQUEST)
            self.assertEqual(response.body["errorCode"], "E_MINECRAFT_GOAL_BAD_REQUEST")
        self.assertEqual(self.gateway.calls, [])

    async def test_unsupported_goal_does_not_turn_into_a_free_form_action(self) -> None:
        await self._enable_game_action()
        self.gateway.output = json.dumps({"goalId": None})
        response = await self._plan(
            {
                "text": "Hina tự đi tìm kim cương rồi chế đồ đi.",
                "source": "owner.desktop",
                "ownerConfirmed": True,
            }
        )

        self.assertEqual(response.status, HTTPStatus.OK)
        self.assertEqual(response.body["state"], "unsupported")
        self.assertIsNone(response.body["goalId"])
        self.assertEqual(len(self.gateway.calls), 1)
