import json
import sys
import unittest
from pathlib import Path
from typing import AsyncIterator


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hina_text_brain import MinecraftGoalPlanner, TextBrainError  # noqa: E402


class ScriptedGateway:
    def __init__(self, scripts: list[list[object]]) -> None:
        self._scripts = scripts
        self.calls = 0
        self.messages: list[list[dict[str, str]]] = []

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        self.messages.append(messages)
        script = self._scripts[self.calls]
        self.calls += 1
        for item in script:
            if isinstance(item, Exception):
                raise item
            yield str(item)


class MinecraftGoalPlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_goal_is_selected_only_as_a_static_identifier(self) -> None:
        gateway = ScriptedGateway([["{\"goalId\":", "\"harvest.nearby-log.v3\"}"]])
        planner = MinecraftGoalPlanner(gateway)

        result = await planner.plan("Hina, chặt một khúc gỗ ở gần đi.")

        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["goalId"], "harvest.nearby-log.v3")
        self.assertEqual(result["planVersion"], "minecraft.goal.v1")
        self.assertEqual(len(gateway.messages), 1)
        system, user = gateway.messages[0]
        self.assertEqual(system["role"], "system")
        self.assertEqual(user["role"], "user")
        self.assertIn("OWNER_MINECRAFT_GOAL_UNTRUSTED", user["content"])
        self.assertIn("không được tạo lệnh mineflayer", system["content"].casefold())
        self.assertNotIn("Hina, chặt", system["content"])

    async def test_unsupported_intent_returns_null_goal_without_free_form_plan(self) -> None:
        gateway = ScriptedGateway([[json.dumps({"goalId": None})]])
        planner = MinecraftGoalPlanner(gateway)

        result = await planner.plan("Tự đi tìm kim cương, craft đồ rồi đánh quái đi.")

        self.assertEqual(result["state"], "unsupported")
        self.assertIsNone(result["goalId"])
        self.assertEqual(set(result), {"state", "goalId", "label", "planVersion"})

    async def test_hidden_reasoning_and_schema_changes_fail_closed(self) -> None:
        for output in [
            "<think>do not expose this</think>{\"goalId\":null}",
            "{\"goalId\":\"harvest.nearby-log.v3\",\"targetX\":1}",
            "{\"goalId\":\"move.to.v1\"}",
            "not json",
        ]:
            gateway = ScriptedGateway([[output]])
            planner = MinecraftGoalPlanner(gateway)
            with self.subTest(output=output), self.assertRaises(TextBrainError) as raised:
                await planner.plan("chặt cây")
            self.assertEqual(raised.exception.code, "E_MINECRAFT_GOAL_MODEL")

    async def test_empty_and_oversized_owner_text_fail_before_model_call(self) -> None:
        gateway = ScriptedGateway([[json.dumps({"goalId": None})]])
        planner = MinecraftGoalPlanner(gateway)
        for text in ["", " " * 5, "🙂" * 513]:
            with self.subTest(text_length=len(text)), self.assertRaises(TextBrainError) as raised:
                await planner.plan(text)
            self.assertEqual(raised.exception.code, "E_MINECRAFT_GOAL_BAD_REQUEST")
        self.assertEqual(gateway.calls, 0)
