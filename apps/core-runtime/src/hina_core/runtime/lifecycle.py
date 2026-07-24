from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, TypeVar

from .error_log import JsonlErrorLogger
from .primitives import PrimitiveError, RuntimeErrorCode


_SERVICE_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_ZERO_CORRELATION_ID = "00000000-0000-0000-0000-000000000000"
T = TypeVar("T")


class ServiceHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ServiceState(StrEnum):
    REGISTERED = "registered"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class SupervisorState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class HealthReport:
    status: ServiceHealth
    detail: str = ""


class ManagedService(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def health(self) -> HealthReport: ...


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    name: str
    service: ManagedService
    dependencies: tuple[str, ...] = ()
    start_timeout_seconds: float = 5.0
    stop_timeout_seconds: float = 5.0


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    name: str
    state: ServiceState
    dependencies: tuple[str, ...]
    starts: int
    stops: int
    last_transition_monotonic: float
    last_error_code: str | None


@dataclass(frozen=True, slots=True)
class SupervisorSnapshot:
    state: SupervisorState
    generation: int
    services: tuple[ServiceStatus, ...]


@dataclass(slots=True)
class _MutableStatus:
    state: ServiceState = ServiceState.REGISTERED
    starts: int = 0
    stops: int = 0
    last_transition_monotonic: float = 0.0
    last_error_code: str | None = None


class ServiceRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ServiceDefinition] = {}
        self._locked = False

    def register(self, definition: ServiceDefinition) -> None:
        if self._locked:
            raise PrimitiveError(RuntimeErrorCode.SERVICE_INVALID, "registry is locked while supervisor is active")
        self._validate_definition(definition)
        if definition.name in self._definitions:
            raise PrimitiveError(RuntimeErrorCode.SERVICE_DUPLICATE, "service name is already registered")
        self._definitions[definition.name] = definition

    def get(self, name: str) -> ManagedService:
        try:
            return self._definitions[name].service
        except KeyError as exc:
            raise PrimitiveError(RuntimeErrorCode.SERVICE_DEPENDENCY, "service is not registered") from exc

    def resolve_order(self) -> tuple[ServiceDefinition, ...]:
        missing = [
            (definition.name, dependency)
            for definition in self._definitions.values()
            for dependency in definition.dependencies
            if dependency not in self._definitions
        ]
        if missing:
            raise PrimitiveError(
                RuntimeErrorCode.SERVICE_DEPENDENCY,
                f"service dependency is not registered: {missing[0][0]} -> {missing[0][1]}",
            )

        indegree = {
            name: len(definition.dependencies)
            for name, definition in self._definitions.items()
        }
        dependents: dict[str, list[str]] = {name: [] for name in self._definitions}
        for definition in self._definitions.values():
            for dependency in definition.dependencies:
                dependents[dependency].append(definition.name)
        ready = [name for name in self._definitions if indegree[name] == 0]
        order: list[ServiceDefinition] = []
        while ready:
            name = ready.pop(0)
            order.append(self._definitions[name])
            for dependent in dependents[name]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
        if len(order) != len(self._definitions):
            raise PrimitiveError(RuntimeErrorCode.SERVICE_CYCLE, "service dependency graph contains a cycle")
        return tuple(order)

    def lock(self) -> tuple[ServiceDefinition, ...]:
        order = self.resolve_order()
        self._locked = True
        return order

    def unlock(self) -> None:
        self._locked = False

    @staticmethod
    def _validate_definition(definition: ServiceDefinition) -> None:
        if _SERVICE_NAME.fullmatch(definition.name) is None:
            raise PrimitiveError(RuntimeErrorCode.SERVICE_INVALID, "service name is invalid")
        if len(set(definition.dependencies)) != len(definition.dependencies):
            raise PrimitiveError(RuntimeErrorCode.SERVICE_INVALID, "service dependencies contain duplicates")
        if definition.name in definition.dependencies:
            raise PrimitiveError(RuntimeErrorCode.SERVICE_CYCLE, "service cannot depend on itself")
        if definition.start_timeout_seconds <= 0 or definition.stop_timeout_seconds <= 0:
            raise PrimitiveError(RuntimeErrorCode.SERVICE_INVALID, "service timeout must be positive")


class ServiceSupervisor:
    def __init__(
        self,
        registry: ServiceRegistry,
        *,
        error_logger: JsonlErrorLogger | None = None,
    ) -> None:
        self.registry = registry
        self.error_logger = error_logger
        self._state = SupervisorState.IDLE
        self._generation = 0
        self._order: tuple[ServiceDefinition, ...] = ()
        self._status: dict[str, _MutableStatus] = {}
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> ServiceSupervisor:
        await self.start_all()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop_all()

    async def start_all(self) -> SupervisorSnapshot:
        async with self._lock:
            if self._state is SupervisorState.RUNNING:
                return self.snapshot()
            if self._state in {SupervisorState.STARTING, SupervisorState.STOPPING}:
                raise PrimitiveError(RuntimeErrorCode.SERVICE_INVALID, "supervisor transition is already active")
            if self._state is SupervisorState.FAILED:
                raise PrimitiveError(
                    RuntimeErrorCode.SERVICE_INVALID,
                    "failed supervisor must complete stop_all before restart",
                )

            self._order = self.registry.lock()
            self._status = {
                definition.name: _MutableStatus(
                    state=ServiceState.STOPPED
                    if self._generation > 0
                    else ServiceState.REGISTERED
                )
                for definition in self._order
            }
            self._state = SupervisorState.STARTING
            self._generation += 1
            attempted: list[ServiceDefinition] = []
            try:
                for definition in self._order:
                    attempted.append(definition)
                    await self._start_one(definition)
            except BaseException as exc:
                self._state = SupervisorState.FAILED
                rollback_clean = await self._rollback(attempted)
                if rollback_clean:
                    self.registry.unlock()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                if isinstance(exc, PrimitiveError):
                    self._log(exc, "start_all")
                    raise
                wrapped = PrimitiveError(
                    RuntimeErrorCode.SERVICE_START_FAILED,
                    f"service startup failed with {type(exc).__name__}",
                )
                self._log(wrapped, "start_all")
                raise wrapped from exc
            self._state = SupervisorState.RUNNING
            return self.snapshot()

    async def stop_all(self) -> SupervisorSnapshot:
        async with self._lock:
            if self._state is SupervisorState.IDLE:
                return self.snapshot()
            if self._state in {SupervisorState.STARTING, SupervisorState.STOPPING}:
                raise PrimitiveError(RuntimeErrorCode.SERVICE_INVALID, "supervisor transition is already active")
            self._state = SupervisorState.STOPPING
            failures: list[PrimitiveError] = []
            for definition in reversed(self._order):
                status = self._status[definition.name]
                if status.state not in {
                    ServiceState.RUNNING,
                    ServiceState.STARTING,
                    ServiceState.FAILED,
                }:
                    continue
                try:
                    await self._stop_one(definition)
                except PrimitiveError as exc:
                    failures.append(exc)
                    self._log(exc, "stop_all", service=definition.name)
            if failures:
                self._state = SupervisorState.FAILED
                raise PrimitiveError(
                    RuntimeErrorCode.SERVICE_STOP_FAILED,
                    f"{len(failures)} service(s) failed graceful shutdown",
                ) from failures[0]
            self._state = SupervisorState.IDLE
            self.registry.unlock()
            return self.snapshot()

    async def check_health(self) -> dict[str, HealthReport]:
        async with self._lock:
            reports: dict[str, HealthReport] = {}
            for definition in self._order:
                status = self._status[definition.name]
                if status.state is not ServiceState.RUNNING:
                    reports[definition.name] = HealthReport(ServiceHealth.UNHEALTHY, str(status.state))
                    continue
                try:
                    reports[definition.name] = await self._bounded(
                        definition.service.health(),
                        definition.start_timeout_seconds,
                        RuntimeErrorCode.SERVICE_UNHEALTHY,
                        definition.name,
                        "health",
                    )
                except PrimitiveError as exc:
                    reports[definition.name] = HealthReport(ServiceHealth.UNHEALTHY, exc.detail)
                    self._log(exc, "health", service=definition.name)
            return reports

    def snapshot(self) -> SupervisorSnapshot:
        return SupervisorSnapshot(
            state=self._state,
            generation=self._generation,
            services=tuple(
                ServiceStatus(
                    name=definition.name,
                    state=self._status.get(definition.name, _MutableStatus()).state,
                    dependencies=definition.dependencies,
                    starts=self._status.get(definition.name, _MutableStatus()).starts,
                    stops=self._status.get(definition.name, _MutableStatus()).stops,
                    last_transition_monotonic=self._status.get(
                        definition.name,
                        _MutableStatus(),
                    ).last_transition_monotonic,
                    last_error_code=self._status.get(
                        definition.name,
                        _MutableStatus(),
                    ).last_error_code,
                )
                for definition in self._order
            ),
        )

    async def _start_one(self, definition: ServiceDefinition) -> None:
        status = self._status[definition.name]
        status.state = ServiceState.STARTING
        status.last_transition_monotonic = time.monotonic()
        try:
            await self._bounded(
                definition.service.start(),
                definition.start_timeout_seconds,
                RuntimeErrorCode.SERVICE_START_FAILED,
                definition.name,
                "start",
            )
            health = await self._bounded(
                definition.service.health(),
                definition.start_timeout_seconds,
                RuntimeErrorCode.SERVICE_UNHEALTHY,
                definition.name,
                "health",
            )
            if health.status is not ServiceHealth.HEALTHY:
                raise PrimitiveError(
                    RuntimeErrorCode.SERVICE_UNHEALTHY,
                    f"service {definition.name} did not become healthy",
                )
        except BaseException as exc:
            status.state = ServiceState.FAILED
            status.last_transition_monotonic = time.monotonic()
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, PrimitiveError):
                status.last_error_code = str(exc.code)
                raise
            wrapped = PrimitiveError(
                RuntimeErrorCode.SERVICE_START_FAILED,
                f"service {definition.name} start failed with {type(exc).__name__}",
            )
            status.last_error_code = str(wrapped.code)
            raise wrapped from exc
        status.state = ServiceState.RUNNING
        status.starts += 1
        status.last_error_code = None
        status.last_transition_monotonic = time.monotonic()

    async def _stop_one(self, definition: ServiceDefinition) -> None:
        status = self._status[definition.name]
        status.state = ServiceState.STOPPING
        status.last_transition_monotonic = time.monotonic()
        try:
            await self._bounded(
                definition.service.stop(),
                definition.stop_timeout_seconds,
                RuntimeErrorCode.SERVICE_STOP_FAILED,
                definition.name,
                "stop",
            )
        except BaseException as exc:
            status.state = ServiceState.FAILED
            status.last_transition_monotonic = time.monotonic()
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, PrimitiveError):
                status.last_error_code = str(exc.code)
                raise
            wrapped = PrimitiveError(
                RuntimeErrorCode.SERVICE_STOP_FAILED,
                f"service {definition.name} stop failed with {type(exc).__name__}",
            )
            status.last_error_code = str(wrapped.code)
            raise wrapped from exc
        status.state = ServiceState.STOPPED
        status.stops += 1
        status.last_error_code = None
        status.last_transition_monotonic = time.monotonic()

    async def _rollback(self, attempted: list[ServiceDefinition]) -> bool:
        clean = True
        for definition in reversed(attempted):
            status = self._status[definition.name]
            if status.state not in {
                ServiceState.RUNNING,
                ServiceState.STARTING,
                ServiceState.FAILED,
            }:
                continue
            try:
                await self._stop_one(definition)
            except BaseException as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                clean = False
                error = (
                    exc
                    if isinstance(exc, PrimitiveError)
                    else PrimitiveError(
                        RuntimeErrorCode.SERVICE_STOP_FAILED,
                        f"rollback stop failed with {type(exc).__name__}",
                    )
                )
                self._log(error, "rollback", service=definition.name)
        return clean

    @staticmethod
    async def _bounded(
        operation: Awaitable[T],
        timeout_seconds: float,
        error_code: RuntimeErrorCode,
        service: str,
        phase: str,
    ) -> T:
        try:
            async with asyncio.timeout(timeout_seconds):
                return await operation
        except TimeoutError as exc:
            raise PrimitiveError(
                error_code,
                f"service {service} {phase} timed out",
            ) from exc
        except PrimitiveError:
            raise
        except Exception as exc:
            raise PrimitiveError(
                error_code,
                f"service {service} {phase} failed with {type(exc).__name__}",
            ) from exc

    def _log(
        self,
        error: PrimitiveError,
        operation: str,
        *,
        service: str | None = None,
    ) -> None:
        if self.error_logger is None:
            return
        self.error_logger.log_error(
            error,
            component="runtime.lifecycle",
            operation=operation,
            correlation_id=_ZERO_CORRELATION_ID,
            context={"service": service},
        )
