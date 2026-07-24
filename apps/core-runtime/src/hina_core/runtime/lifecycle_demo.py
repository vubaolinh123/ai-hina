from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from .durable import DurableStore
from .error_log import JsonlErrorLogger
from .lifecycle import (
    HealthReport,
    ServiceDefinition,
    ServiceHealth,
    ServiceRegistry,
    ServiceSupervisor,
)
from .transport import ControlPlaneServer, TransportConfig
from .transport_client import get_json


ROOT = Path(__file__).resolve().parents[5]
DEFAULT_DATABASE = ROOT / "var" / "data" / "m01-s5-demo.sqlite3"
DEFAULT_LOG = ROOT / "var" / "logs" / "m01-s5-demo.jsonl"


class _DurableService:
    def __init__(self, path: Path, events: list[str]) -> None:
        self.path = path
        self.events = events
        self.store: DurableStore | None = None

    async def start(self) -> None:
        self.events.append("durable:start")
        self.store = DurableStore(self.path)

    async def stop(self) -> None:
        self.events.append("durable:stop")
        if self.store is not None:
            self.store.close()
            self.store = None

    async def health(self) -> HealthReport:
        return HealthReport(
            ServiceHealth.HEALTHY if self.store is not None else ServiceHealth.UNHEALTHY,
            "sqlite-open" if self.store is not None else "sqlite-closed",
        )


class _ControlService:
    def __init__(
        self,
        durable: _DurableService,
        logger: JsonlErrorLogger,
        events: list[str],
    ) -> None:
        self.durable = durable
        self.logger = logger
        self.events = events
        self.server: ControlPlaneServer | None = None
        self.address: tuple[str, int] | None = None

    async def start(self) -> None:
        self.events.append("control:start")
        if self.durable.store is None:
            raise RuntimeError("durable dependency is not running")
        self.server = ControlPlaneServer(
            TransportConfig(port=0),
            durable_store=self.durable.store,
            error_logger=self.logger,
        )
        self.address = await self.server.start()

    async def stop(self) -> None:
        self.events.append("control:stop")
        if self.server is not None:
            await self.server.stop()
            self.server = None

    async def health(self) -> HealthReport:
        return HealthReport(
            ServiceHealth.HEALTHY
            if self.server is not None and self.address is not None
            else ServiceHealth.UNHEALTHY,
            "loopback-ready" if self.server is not None else "stopped",
        )


def _reset_database(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        candidate.unlink(missing_ok=True)


async def run_lifecycle_demo(database_path: Path, log_path: Path) -> dict[str, Any]:
    _reset_database(database_path)
    log_path.unlink(missing_ok=True)
    events: list[str] = []
    logger = JsonlErrorLogger(
        log_path,
        build_commit=os.environ.get("HINA_BUILD_COMMIT", "development"),
    )
    durable = _DurableService(database_path, events)
    control = _ControlService(durable, logger, events)
    registry = ServiceRegistry()
    registry.register(ServiceDefinition("durable", durable))
    registry.register(ServiceDefinition("control", control, dependencies=("durable",)))
    supervisor = ServiceSupervisor(registry, error_logger=logger)

    running = await supervisor.start_all()
    assert control.address is not None
    health_response = await get_json(*control.address, "/v1/health")
    health_reports = await supervisor.check_health()
    stopped = await supervisor.stop_all()

    return {
        "status": "ok",
        "supervisor": {
            "runningState": str(running.state),
            "stoppedState": str(stopped.state),
            "generation": stopped.generation,
            "runningServices": [
                status.name for status in running.services if str(status.state) == "running"
            ],
            "stoppedServices": [
                status.name for status in stopped.services if str(status.state) == "stopped"
            ],
        },
        "order": events,
        "health": {
            "controlEndpoint": health_response.body["status"],
            "services": {
                name: str(report.status)
                for name, report in health_reports.items()
            },
        },
        "resources": {
            "controlServerClosed": control.server is None,
            "databaseClosed": durable.store is None,
        },
        "errorLog": {
            "path": str(log_path),
            "records": len(log_path.read_text(encoding="utf-8").splitlines())
            if log_path.exists()
            else 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the visible M01-S5 lifecycle demo.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    args = parser.parse_args()
    result = asyncio.run(
        run_lifecycle_demo(args.database.resolve(), args.log.resolve())
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
