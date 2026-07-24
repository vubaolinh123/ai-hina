from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from .error_log import JsonlErrorLogger
from .primitives import (
    BoundedAsyncQueue,
    CancellationToken,
    Deadline,
    IdempotencyRegistry,
    OverflowPolicy,
    PrimitiveError,
    wait_controlled,
)


ROOT = Path(__file__).resolve().parents[5]
DEFAULT_LOG = ROOT / "var" / "logs" / "m01-s2-demo.jsonl"


async def run_demo(log_path: Path, *, reset_log: bool = True) -> dict[str, Any]:
    if reset_log:
        log_path.unlink(missing_ok=True)
    logger = JsonlErrorLogger(log_path, build_commit=os.environ.get("HINA_BUILD_COMMIT", "development"))

    queue = BoundedAsyncQueue[str](2, OverflowPolicy.DROP_OLDEST)
    await queue.put("job-a")
    await queue.put("job-b")
    drop_result = await queue.put("job-c")
    remaining = [await queue.get(), await queue.get()]
    queue.task_done()
    queue.task_done()
    await queue.join(deadline=Deadline.after(1))

    error_codes: dict[str, str] = {}
    reject_queue = BoundedAsyncQueue[str](1, OverflowPolicy.REJECT_NEW)
    await reject_queue.put("kept")
    try:
        await reject_queue.put("rejected")
    except PrimitiveError as exc:
        error_codes["queueFull"] = str(exc.code)
        logger.log_error(
            exc,
            component="runtime.queue",
            operation="put",
            correlation_id="demo-queue",
            context={"capacity": 1, "apiToken": "demo-secret"},
        )

    try:
        await wait_controlled(asyncio.sleep(0.05), deadline=Deadline.after(0.005))
    except PrimitiveError as exc:
        error_codes["deadline"] = str(exc.code)
        logger.log_error(
            exc,
            component="runtime.deadline",
            operation="wait",
            correlation_id="demo-deadline",
        )

    token = CancellationToken()
    token.cancel("owner requested demo cancellation")
    try:
        await wait_controlled(asyncio.sleep(0.05), cancellation=token)
    except PrimitiveError as exc:
        error_codes["cancellation"] = str(exc.code)
        logger.log_error(
            exc,
            component="runtime.cancellation",
            operation="wait",
            correlation_id="demo-cancel",
        )

    registry = IdempotencyRegistry[dict[str, int]](max_entries=8, default_ttl_seconds=60)
    side_effects = 0

    async def side_effect() -> dict[str, int]:
        nonlocal side_effects
        side_effects += 1
        await asyncio.sleep(0.01)
        return {"sideEffects": side_effects}

    first, second = await asyncio.gather(
        registry.run_once("demo-turn-1", side_effect),
        registry.run_once("demo-turn-1", side_effect),
    )
    third = await registry.run_once("demo-turn-1", side_effect)

    try:
        display_log = str(log_path.relative_to(ROOT))
    except ValueError:
        display_log = str(log_path)

    return {
        "status": "ok",
        "queue": {
            "capacity": queue.capacity,
            "dropped": drop_result.dropped,
            "remaining": remaining,
            "metrics": {
                "accepted": queue.metrics.accepted,
                "dequeued": queue.metrics.dequeued,
                "dropped": queue.metrics.dropped,
                "rejected": queue.metrics.rejected,
            },
        },
        "idempotency": {
            "sideEffects": side_effects,
            "sources": [first.source, second.source, third.source],
            "result": third.value,
        },
        "controls": error_codes,
        "errorLog": display_log,
        "errorRecords": 3,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the visible M01-S2 runtime primitive demo.")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--keep-log", action="store_true", help="append instead of resetting the demo log")
    args = parser.parse_args()
    result = asyncio.run(run_demo(args.log.resolve(), reset_log=not args.keep_log))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
