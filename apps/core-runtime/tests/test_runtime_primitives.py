from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
SRC = APP_ROOT / "src"
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(SRC))

from hina_core.runtime import (  # noqa: E402
    BoundedAsyncQueue,
    CancellationToken,
    Deadline,
    IdempotencyRegistry,
    IdempotencySource,
    JsonlErrorLogger,
    OverflowPolicy,
    PrimitiveError,
    RuntimeErrorCode,
    wait_controlled,
)
from hina_core.runtime.demo import run_demo  # noqa: E402


class RuntimePrimitiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_policies_keep_hard_capacity(self) -> None:
        reject = BoundedAsyncQueue[str](1, OverflowPolicy.REJECT_NEW)
        await reject.put("first")
        with self.assertRaisesRegex(PrimitiveError, "capacity") as raised:
            await reject.put("second")
        self.assertEqual(raised.exception.code, RuntimeErrorCode.QUEUE_FULL)
        self.assertEqual(reject.size, 1)

        drop = BoundedAsyncQueue[str](2, OverflowPolicy.DROP_OLDEST)
        await drop.put("a")
        await drop.put("b")
        result = await drop.put("c")
        self.assertEqual(result.dropped, "a")
        self.assertEqual(drop.size, 2)
        self.assertEqual([await drop.get(), await drop.get()], ["b", "c"])

        waiting = BoundedAsyncQueue[str](1, OverflowPolicy.WAIT)
        await waiting.put("one")
        pending = asyncio.create_task(waiting.put("two", deadline=Deadline.after(0.5)))
        await asyncio.sleep(0)
        self.assertFalse(pending.done())
        self.assertEqual(await waiting.get(), "one")
        waiting.task_done()
        await pending
        self.assertEqual(waiting.size, 1)

    async def test_deadline_and_cancellation_clean_up_pending_work(self) -> None:
        finalized = asyncio.Event()

        async def slow() -> None:
            try:
                await asyncio.sleep(1)
            finally:
                finalized.set()

        slow_task = asyncio.create_task(slow())
        await asyncio.sleep(0)
        with self.assertRaises(PrimitiveError) as deadline:
            await wait_controlled(slow_task, deadline=Deadline.after(0.005))
        self.assertEqual(deadline.exception.code, RuntimeErrorCode.DEADLINE_EXCEEDED)
        self.assertTrue(finalized.is_set())

        token = CancellationToken()
        token.cancel("test cancelled")
        with self.assertRaises(PrimitiveError) as cancelled:
            await wait_controlled(asyncio.sleep(1), cancellation=token)
        self.assertEqual(cancelled.exception.code, RuntimeErrorCode.CANCELLED)

    async def test_idempotency_coalesces_replays_and_stays_bounded(self) -> None:
        registry = IdempotencyRegistry[int](max_entries=2, default_ttl_seconds=1)
        side_effects = 0

        async def operation() -> int:
            nonlocal side_effects
            side_effects += 1
            await asyncio.sleep(0.01)
            return side_effects

        first, second = await asyncio.gather(
            registry.run_once("same-key", operation),
            registry.run_once("same-key", operation),
        )
        replay = await registry.run_once("same-key", operation)
        self.assertEqual(side_effects, 1)
        self.assertEqual({first.source, second.source}, {IdempotencySource.EXECUTED, IdempotencySource.COALESCED})
        self.assertEqual(replay.source, IdempotencySource.REPLAYED)
        self.assertEqual(replay.value, 1)

        await registry.run_once("second-key", operation)
        await registry.run_once("third-key", operation)
        self.assertLessEqual(registry.size, 2)

        clock_now = 100.0
        expiring = IdempotencyRegistry[int](
            max_entries=2,
            default_ttl_seconds=0.005,
            clock=lambda: clock_now,
        )
        expiry_side_effects = 0

        async def expiring_operation() -> int:
            nonlocal expiry_side_effects
            expiry_side_effects += 1
            return expiry_side_effects

        await expiring.run_once("expires", expiring_operation)
        clock_now += 0.006
        after_expiry = await expiring.run_once("expires", expiring_operation)
        self.assertEqual(after_expiry.source, IdempotencySource.EXECUTED)
        self.assertEqual(expiry_side_effects, 2)

    async def test_demo_is_visible_and_writes_redacted_error_log(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            log_path = Path(temporary_directory) / "demo.jsonl"
            result = await run_demo(log_path)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["queue"]["dropped"], "job-a")
            self.assertEqual(result["idempotency"]["sideEffects"], 1)
            self.assertEqual(result["errorRecords"], 3)
            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            records = [json.loads(line) for line in lines]
            self.assertTrue(all(record["errorCode"].startswith("E_") for record in records))
            self.assertNotIn("demo-secret", log_path.read_text(encoding="utf-8"))
            self.assertIn("<redacted>", log_path.read_text(encoding="utf-8"))


class ErrorLogTests(unittest.TestCase):
    def test_logger_redacts_secret_keys_and_inline_values(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            path = Path(temporary_directory) / "errors.jsonl"
            logger = JsonlErrorLogger(path)
            logger.log_error(
                PrimitiveError(
                    RuntimeErrorCode.OPERATION_FAILED,
                    "token=visible-secret authorization: Bearer second-visible-secret failed",
                ),
                component="test",
                operation="redaction",
                correlation_id="test-redaction",
                context={"password": "visible-secret", "safe": "kept"},
            )
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("visible-secret", text)
            self.assertNotIn("second-visible-secret", text)
            self.assertIn("<redacted>", text)
            self.assertIn('"safe":"kept"', text)


if __name__ == "__main__":
    unittest.main()
