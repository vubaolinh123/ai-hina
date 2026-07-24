from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .durable import DurableStore
from .error_log import JsonlErrorLogger
from .observability import MetricRegistry
from .transport import ControlPlaneServer, TransportConfig


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    database: Path
    error_log: Path
    static_dir: Path | None = None
    audit_log: Path | None = None
    safety_manifest: Path | None = None


class HinaRuntimeApplication:
    """Owns the persistent resources that make up the local M01 application."""

    def __init__(
        self,
        config: TransportConfig,
        paths: RuntimePaths,
        *,
        build_commit: str = "development",
    ) -> None:
        self.config = config
        self.paths = paths
        self.build_commit = build_commit
        self.metrics = MetricRegistry()
        self.error_logger = JsonlErrorLogger(
            paths.error_log.resolve(),
            build_commit=build_commit,
        )
        self.store: DurableStore | None = None
        self.server: ControlPlaneServer | None = None
        self.safety_policy: Any | None = None

    @property
    def address(self) -> tuple[str, int]:
        if self.server is None:
            raise RuntimeError("Hina runtime application is not running")
        return self.server.address

    async def __aenter__(self) -> HinaRuntimeApplication:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()

    async def start(self) -> tuple[str, int]:
        if self.server is not None:
            return self.server.address
        safety_policy = None
        if self.paths.audit_log is not None or self.paths.safety_manifest is not None:
            if self.paths.audit_log is None or self.paths.safety_manifest is None:
                raise ValueError("audit_log and safety_manifest must be configured together")
            from hina_safety import AuditTrail, CapabilityManifest, SafetyPolicyService

            manifest = CapabilityManifest.load(self.paths.safety_manifest.resolve())
            audit = AuditTrail(
                self.paths.audit_log.resolve(),
                build_commit=self.build_commit,
            )
            safety_policy = SafetyPolicyService(manifest, audit)
        store = DurableStore(self.paths.database.resolve())
        server = ControlPlaneServer(
            self.config,
            durable_store=store,
            error_logger=self.error_logger,
            metrics=self.metrics,
            static_dir=self.paths.static_dir,
            safety_policy=safety_policy,
            build_commit=self.build_commit,
        )
        try:
            await server.start()
        except Exception:
            store.close()
            raise
        self.store = store
        self.server = server
        self.safety_policy = safety_policy
        self.metrics.set_gauge(
            "hina_runtime_ready",
            1,
            labels={"component": "core_runtime"},
        )
        return server.address

    async def serve_forever(self) -> None:
        if self.server is None:
            await self.start()
        assert self.server is not None
        await self.server.serve_forever()

    async def stop(self) -> None:
        server = self.server
        store = self.store
        self.server = None
        self.store = None
        self.safety_policy = None
        if server is not None:
            await server.stop()
        if store is not None:
            store.close()
