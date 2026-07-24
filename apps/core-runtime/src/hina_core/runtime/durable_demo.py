from __future__ import annotations

import argparse
import copy
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from .durable import DurableStore
from .error_log import JsonlErrorLogger
from .primitives import PrimitiveError


ROOT = Path(__file__).resolve().parents[5]
DEFAULT_DATABASE = ROOT / "var" / "data" / "m01-s3-demo.sqlite3"
DEFAULT_LOG = ROOT / "var" / "logs" / "m01-s3-demo.jsonl"
FIXTURE = ROOT / "packages" / "contracts" / "fixtures" / "golden" / "turn.media.echo.json"


def _demo_envelope(sequence: int) -> dict[str, Any]:
    envelope = json.loads(FIXTURE.read_text(encoding="utf-8"))
    envelope["eventId"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"hina-m01-s3-event-{sequence}"))
    envelope["streamId"] = "demo-durable-stream"
    envelope["sequence"] = sequence
    envelope["idempotencyKey"] = f"demo-durable-{sequence}"
    envelope["payload"]["message"] = f"Durable event {sequence}"
    envelope["payload"]["metadata"] = {"demo": "m01-s3", "sequence": sequence}
    envelope["media"] = []
    return envelope


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _reset_database(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        candidate.unlink(missing_ok=True)


def run_durable_demo(database_path: Path, log_path: Path, *, reset: bool = True) -> dict[str, Any]:
    if reset:
        _reset_database(database_path)
        log_path.unlink(missing_ok=True)
    logger = JsonlErrorLogger(log_path, build_commit=os.environ.get("HINA_BUILD_COMMIT", "development"))
    events = [_demo_envelope(sequence) for sequence in range(3)]

    with DurableStore(database_path) as store:
        append_results = [store.append_outbox(event) for event in events]
        duplicate = store.append_outbox(events[0])
        first_claim = store.claim_outbox(limit=2, lease_seconds=0.01)
        store.ack_outbox(first_claim[0].event_id)

    time.sleep(0.05)

    with DurableStore(database_path) as store:
        recovered_claim = store.claim_outbox(limit=3, lease_seconds=1)
        for claimed in recovered_claim:
            store.ack_outbox(claimed.event_id)

        for event in events:
            store.receive_inbox("demo-consumer", event)
        duplicate_inbox = store.receive_inbox("demo-consumer", events[0])
        checkpoint_before_crash = store.complete_inbox(
            "demo-consumer",
            events[0]["eventId"],
            {"status": "processed"},
        )

    with DurableStore(database_path) as store:
        resumed = store.resume_inbox("demo-consumer", "demo-durable-stream")
        checkpoint_with_gap = store.complete_inbox(
            "demo-consumer",
            events[2]["eventId"],
            {"status": "processed"},
        )
        final_checkpoint = store.complete_inbox(
            "demo-consumer",
            events[1]["eventId"],
            {"status": "processed"},
        )
        replayed = store.replay_journal("demo-durable-stream", after_sequence=0)

        conflicting = copy.deepcopy(events[0])
        conflicting["payload"]["message"] = "conflicting event content"
        try:
            store.append_outbox(conflicting)
        except PrimitiveError as exc:
            logger.log_error(
                exc,
                component="runtime.durable",
                operation="append_outbox",
                correlation_id=events[0]["correlationId"],
                context={"eventId": events[0]["eventId"], "authorization": "Bearer demo-secret"},
            )
            conflict_code = str(exc.code)
        else:
            conflict_code = "MISSING_EXPECTED_CONFLICT"
        snapshot = store.snapshot()

    reclaimed = next(event for event in recovered_claim if event.sequence == 1)
    return {
        "status": "ok",
        "database": _display_path(database_path),
        "errorLog": _display_path(log_path),
        "journal": {
            "rows": snapshot.journal,
            "duplicateAppendIgnored": duplicate.deduplicated,
            "appendedSequences": [result.event.sequence for result in append_results],
            "replayAfterSequence0": [event.sequence for event in replayed],
            "conflictCode": conflict_code,
        },
        "outbox": {
            "firstClaim": [event.sequence for event in first_claim],
            "recoveredAfterRestart": [event.sequence for event in recovered_claim],
            "reclaimedSequence1Attempts": reclaimed.delivery_attempts,
            "acked": snapshot.outbox_acked,
            "pending": snapshot.outbox_pending,
            "inFlight": snapshot.outbox_in_flight,
        },
        "inbox": {
            "duplicateIgnored": not duplicate_inbox.inserted,
            "checkpointBeforeRestart": checkpoint_before_crash,
            "resumedSequences": [event.sequence for event in resumed],
            "checkpointWithGap": checkpoint_with_gap,
            "finalCheckpoint": final_checkpoint,
        },
        "errorRecords": 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the visible M01-S3 durable delivery demo.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--keep", action="store_true", help="keep existing demo database and log")
    args = parser.parse_args()
    result = run_durable_demo(args.database.resolve(), args.log.resolve(), reset=not args.keep)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
