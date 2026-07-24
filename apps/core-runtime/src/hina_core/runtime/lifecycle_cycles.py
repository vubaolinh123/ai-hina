from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from typing import Any

from .lifecycle import (
    HealthReport,
    ServiceDefinition,
    ServiceHealth,
    ServiceRegistry,
    ServiceState,
    ServiceSupervisor,
    SupervisorState,
)


@dataclass(slots=True)
class _ProbeService:
    name: str
    events: list[str]
    running: bool = False
    starts: int = 0
    stops: int = 0

    async def start(self) -> None:
        self.events.append(f"{self.name}:start")
        self.running = True
        self.starts += 1

    async def stop(self) -> None:
        self.events.append(f"{self.name}:stop")
        self.running = False
        self.stops += 1

    async def health(self) -> HealthReport:
        return HealthReport(
            ServiceHealth.HEALTHY if self.running else ServiceHealth.UNHEALTHY
        )


async def run_lifecycle_cycles(cycles: int) -> dict[str, Any]:
    if not 1 <= cycles <= 10_000:
        raise ValueError("cycles must be between 1 and 10000")
    current = asyncio.current_task()
    baseline_tasks = {
        task
        for task in asyncio.all_tasks()
        if task is not current and not task.done()
    }
    events: list[str] = []
    database = _ProbeService("database", events)
    transport = _ProbeService("transport", events)
    registry = ServiceRegistry()
    registry.register(ServiceDefinition("database", database))
    registry.register(
        ServiceDefinition("transport", transport, dependencies=("database",))
    )
    supervisor = ServiceSupervisor(registry)

    expected_cycle = [
        "database:start",
        "transport:start",
        "transport:stop",
        "database:stop",
    ]
    for cycle in range(cycles):
        running = await supervisor.start_all()
        if running.state is not SupervisorState.RUNNING:
            raise AssertionError(f"cycle {cycle} did not reach running")
        stopped = await supervisor.stop_all()
        if stopped.state is not SupervisorState.IDLE:
            raise AssertionError(f"cycle {cycle} did not return to idle")
        if any(status.state is not ServiceState.STOPPED for status in stopped.services):
            raise AssertionError(f"cycle {cycle} left a service active")
        if events[-4:] != expected_cycle:
            raise AssertionError(f"cycle {cycle} lifecycle order drifted")

    await asyncio.sleep(0)
    extra_tasks = [
        task
        for task in asyncio.all_tasks()
        if task is not current and not task.done() and task not in baseline_tasks
    ]
    if extra_tasks:
        raise AssertionError(f"lifecycle left {len(extra_tasks)} pending task(s)")
    return {
        "status": "ok",
        "cycles": cycles,
        "starts": {
            "database": database.starts,
            "transport": transport.starts,
        },
        "stops": {
            "database": database.stops,
            "transport": transport.stops,
        },
        "pendingTasksAdded": 0,
        "finalSupervisorState": str(supervisor.snapshot().state),
        "finalServiceStates": [
            str(status.state) for status in supervisor.snapshot().services
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic service lifecycle cycles.")
    parser.add_argument("--cycles", type=int, default=100)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(run_lifecycle_cycles(args.cycles)),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
