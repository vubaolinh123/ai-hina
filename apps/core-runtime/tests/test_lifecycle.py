from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(APP_ROOT / "src"))

from hina_core.runtime import (  # noqa: E402
    HealthReport,
    JsonlErrorLogger,
    PrimitiveError,
    RuntimeErrorCode,
    ServiceDefinition,
    ServiceHealth,
    ServiceRegistry,
    ServiceState,
    ServiceSupervisor,
    SupervisorState,
)
from hina_core.runtime.lifecycle_cycles import run_lifecycle_cycles  # noqa: E402
from hina_core.runtime.lifecycle_demo import run_lifecycle_demo  # noqa: E402


@dataclass(slots=True)
class ProbeService:
    name: str
    events: list[str]
    fail_start: bool = False
    fail_stops: int = 0
    start_delay: float = 0
    running: bool = False

    async def start(self) -> None:
        self.events.append(f"{self.name}:start")
        if self.start_delay:
            await asyncio.sleep(self.start_delay)
        if self.fail_start:
            raise RuntimeError("expected start failure")
        self.running = True

    async def stop(self) -> None:
        self.events.append(f"{self.name}:stop")
        if self.fail_stops:
            self.fail_stops -= 1
            raise RuntimeError("expected stop failure")
        self.running = False

    async def health(self) -> HealthReport:
        return HealthReport(
            ServiceHealth.HEALTHY if self.running else ServiceHealth.UNHEALTHY
        )


class ServiceRegistryTests(unittest.TestCase):
    def test_duplicate_missing_and_cycle_fail_closed(self) -> None:
        events: list[str] = []
        duplicate = ServiceRegistry()
        duplicate.register(ServiceDefinition("one", ProbeService("one", events)))
        with self.assertRaises(PrimitiveError) as raised:
            duplicate.register(ServiceDefinition("one", ProbeService("other", events)))
        self.assertEqual(raised.exception.code, RuntimeErrorCode.SERVICE_DUPLICATE)

        missing = ServiceRegistry()
        missing.register(
            ServiceDefinition(
                "child",
                ProbeService("child", events),
                dependencies=("missing",),
            )
        )
        with self.assertRaises(PrimitiveError) as raised:
            missing.resolve_order()
        self.assertEqual(raised.exception.code, RuntimeErrorCode.SERVICE_DEPENDENCY)

        cycle = ServiceRegistry()
        cycle.register(
            ServiceDefinition("first", ProbeService("first", events), dependencies=("second",))
        )
        cycle.register(
            ServiceDefinition("second", ProbeService("second", events), dependencies=("first",))
        )
        with self.assertRaises(PrimitiveError) as raised:
            cycle.resolve_order()
        self.assertEqual(raised.exception.code, RuntimeErrorCode.SERVICE_CYCLE)


class ServiceSupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_failure_rolls_back_in_reverse_order_and_logs(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            log_path = Path(temporary_directory) / "lifecycle.jsonl"
            events: list[str] = []
            database = ProbeService("database", events)
            worker = ProbeService("worker", events, fail_start=True)
            registry = ServiceRegistry()
            registry.register(ServiceDefinition("database", database))
            registry.register(
                ServiceDefinition("worker", worker, dependencies=("database",))
            )
            supervisor = ServiceSupervisor(
                registry,
                error_logger=JsonlErrorLogger(log_path),
            )

            with self.assertRaises(PrimitiveError) as raised:
                await supervisor.start_all()
            self.assertEqual(raised.exception.code, RuntimeErrorCode.SERVICE_START_FAILED)
            self.assertEqual(
                events,
                ["database:start", "worker:start", "worker:stop", "database:stop"],
            )
            self.assertEqual(supervisor.snapshot().state, SupervisorState.FAILED)
            self.assertTrue(
                all(
                    status.state is ServiceState.STOPPED
                    for status in supervisor.snapshot().services
                )
            )
            self.assertEqual((await supervisor.stop_all()).state, SupervisorState.IDLE)
            records = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["errorCode"], "E_SERVICE_START_FAILED")

    async def test_stop_failure_does_not_skip_remaining_services_and_can_retry(self) -> None:
        events: list[str] = []
        database = ProbeService("database", events)
        worker = ProbeService("worker", events, fail_stops=1)
        registry = ServiceRegistry()
        registry.register(ServiceDefinition("database", database))
        registry.register(
            ServiceDefinition("worker", worker, dependencies=("database",))
        )
        supervisor = ServiceSupervisor(registry)
        await supervisor.start_all()

        with self.assertRaises(PrimitiveError) as raised:
            await supervisor.stop_all()
        self.assertEqual(raised.exception.code, RuntimeErrorCode.SERVICE_STOP_FAILED)
        self.assertEqual(
            events,
            ["database:start", "worker:start", "worker:stop", "database:stop"],
        )
        stopped = await supervisor.stop_all()
        self.assertEqual(stopped.state, SupervisorState.IDLE)
        self.assertEqual(events[-1], "worker:stop")
        self.assertTrue(all(status.state is ServiceState.STOPPED for status in stopped.services))

    async def test_start_timeout_is_bounded_and_rolls_back_attempt(self) -> None:
        events: list[str] = []
        slow = ProbeService("slow", events, start_delay=0.05)
        registry = ServiceRegistry()
        registry.register(
            ServiceDefinition(
                "slow",
                slow,
                start_timeout_seconds=0.005,
            )
        )
        supervisor = ServiceSupervisor(registry)
        with self.assertRaises(PrimitiveError) as raised:
            await supervisor.start_all()
        self.assertEqual(raised.exception.code, RuntimeErrorCode.SERVICE_START_FAILED)
        self.assertEqual(events, ["slow:start", "slow:stop"])
        await supervisor.stop_all()

    async def test_registry_is_locked_only_while_services_are_active(self) -> None:
        events: list[str] = []
        registry = ServiceRegistry()
        registry.register(ServiceDefinition("first", ProbeService("first", events)))
        supervisor = ServiceSupervisor(registry)
        await supervisor.start_all()
        with self.assertRaises(PrimitiveError) as raised:
            registry.register(ServiceDefinition("second", ProbeService("second", events)))
        self.assertEqual(raised.exception.code, RuntimeErrorCode.SERVICE_INVALID)
        await supervisor.stop_all()
        registry.register(ServiceDefinition("second", ProbeService("second", events)))
        self.assertEqual(
            [definition.name for definition in registry.resolve_order()],
            ["first", "second"],
        )

    async def test_fast_five_cycle_gate_leaves_no_pending_tasks(self) -> None:
        result = await run_lifecycle_cycles(5)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["cycles"], 5)
        self.assertEqual(result["starts"]["database"], 5)
        self.assertEqual(result["stops"]["transport"], 5)
        self.assertEqual(result["pendingTasksAdded"], 0)
        self.assertEqual(result["finalSupervisorState"], "idle")

    async def test_visible_demo_supervises_real_database_and_control_server(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            result = await run_lifecycle_demo(
                directory / "runtime.sqlite3",
                directory / "runtime.jsonl",
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["supervisor"]["runningState"], "running")
            self.assertEqual(result["supervisor"]["stoppedState"], "idle")
            self.assertEqual(
                result["order"],
                ["durable:start", "control:start", "control:stop", "durable:stop"],
            )
            self.assertEqual(result["health"]["controlEndpoint"], "ready")
            self.assertEqual(
                result["health"]["services"],
                {"durable": "healthy", "control": "healthy"},
            )
            self.assertTrue(result["resources"]["controlServerClosed"])
            self.assertTrue(result["resources"]["databaseClosed"])
            self.assertEqual(result["errorLog"]["records"], 0)


if __name__ == "__main__":
    unittest.main()
