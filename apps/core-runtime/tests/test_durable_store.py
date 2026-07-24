from __future__ import annotations

import copy
import json
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(APP_ROOT / "src"))

from hina_core.runtime import DurableStore, PrimitiveError, RuntimeErrorCode  # noqa: E402
from hina_core.runtime.durable_demo import run_durable_demo  # noqa: E402


FIXTURE = ROOT / "packages" / "contracts" / "fixtures" / "golden" / "turn.media.echo.json"


def envelope(sequence: int, *, stream_id: str = "test-durable-stream") -> dict:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    value["eventId"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"test-event-{stream_id}-{sequence}"))
    value["streamId"] = stream_id
    value["sequence"] = sequence
    value["idempotencyKey"] = f"test-{stream_id}-{sequence}"
    value["media"] = []
    value["payload"]["message"] = f"event {sequence}"
    value["payload"]["metadata"] = {"sequence": sequence}
    return value


class DurableStoreTests(unittest.TestCase):
    def test_append_is_idempotent_and_replay_is_ordered(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            database = Path(temporary_directory) / "runtime.sqlite3"
            with DurableStore(database) as store:
                events = [envelope(index) for index in range(3)]
                first = store.append_outbox(events[0])
                duplicate = store.append_outbox(events[0])
                store.append_outbox(events[1])
                store.append_outbox(events[2])
                self.assertFalse(first.deduplicated)
                self.assertTrue(duplicate.deduplicated)
                self.assertEqual(store.snapshot().journal, 3)
                self.assertEqual(
                    [event.sequence for event in store.replay_journal("test-durable-stream", after_sequence=0)],
                    [1, 2],
                )

                conflicting = copy.deepcopy(events[0])
                conflicting["payload"]["message"] = "different"
                with self.assertRaises(PrimitiveError) as raised:
                    store.append_outbox(conflicting)
                self.assertEqual(raised.exception.code, RuntimeErrorCode.JOURNAL_CONFLICT)

    def test_outbox_ack_and_expired_lease_survive_reopen(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            database = Path(temporary_directory) / "runtime.sqlite3"
            events = [envelope(index) for index in range(2)]
            with DurableStore(database) as store:
                for event in events:
                    store.append_outbox(event)
                claimed = store.claim_outbox(limit=2, lease_seconds=0.01)
                self.assertEqual([item.delivery_attempts for item in claimed], [1, 1])
                store.ack_outbox(claimed[0].event_id)
                self.assertTrue(store.ack_outbox(claimed[0].event_id).already_acked)

            time.sleep(0.05)
            with DurableStore(database) as reopened:
                reclaimed = reopened.claim_outbox(limit=2, lease_seconds=1)
                self.assertEqual([item.sequence for item in reclaimed], [1])
                self.assertEqual(reclaimed[0].delivery_attempts, 2)
                reopened.ack_outbox(reclaimed[0].event_id)
                snapshot = reopened.snapshot()
                self.assertEqual(snapshot.outbox_acked, 2)
                self.assertEqual(snapshot.outbox_pending, 0)
                self.assertEqual(snapshot.outbox_in_flight, 0)

    def test_inbox_resume_never_skips_sequence_gap(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            database = Path(temporary_directory) / "runtime.sqlite3"
            events = [envelope(index) for index in range(3)]
            with DurableStore(database) as store:
                for event in events:
                    self.assertTrue(store.receive_inbox("consumer", event).inserted)
                self.assertFalse(store.receive_inbox("consumer", events[0]).inserted)
                self.assertEqual(store.complete_inbox("consumer", events[2]["eventId"], {"ok": True}), -1)
                self.assertEqual(store.get_checkpoint("consumer", "test-durable-stream"), -1)
                self.assertEqual(
                    [item.sequence for item in store.resume_inbox("consumer", "test-durable-stream")],
                    [0, 1, 2],
                )
                self.assertEqual(store.complete_inbox("consumer", events[0]["eventId"], {"ok": True}), 0)

            with DurableStore(database) as reopened:
                self.assertEqual(
                    [item.sequence for item in reopened.resume_inbox("consumer", "test-durable-stream")],
                    [1, 2],
                )
                self.assertEqual(reopened.complete_inbox("consumer", events[1]["eventId"], {"ok": True}), 2)
                self.assertEqual(reopened.get_checkpoint("consumer", "test-durable-stream"), 2)
                self.assertEqual(reopened.resume_inbox("consumer", "test-durable-stream"), [])

    def test_visible_demo_recovers_after_restart_and_logs_conflict(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            result = run_durable_demo(directory / "demo.sqlite3", directory / "demo.jsonl")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["journal"]["rows"], 3)
            self.assertEqual(result["journal"]["replayAfterSequence0"], [1, 2])
            self.assertEqual(result["journal"]["conflictCode"], "E_JOURNAL_CONFLICT")
            self.assertEqual(result["outbox"]["reclaimedSequence1Attempts"], 2)
            self.assertEqual(result["outbox"]["acked"], 3)
            self.assertEqual(result["inbox"]["resumedSequences"], [1, 2])
            self.assertEqual(result["inbox"]["checkpointWithGap"], 0)
            self.assertEqual(result["inbox"]["finalCheckpoint"], 2)
            log_text = (directory / "demo.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("demo-secret", log_text)
            self.assertIn("<redacted>", log_text)


if __name__ == "__main__":
    unittest.main()
