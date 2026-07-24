from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass

from .observability import MetricRegistry
from .primitives import PrimitiveError, RuntimeErrorCode


_OWNER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class ResourceInventory:
    total_vram_mib: int
    total_ram_mib: int
    reserved_vram_headroom_mib: int = 2_048

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (
                self.total_vram_mib,
                self.total_ram_mib,
                self.reserved_vram_headroom_mib,
            )
        ):
            raise PrimitiveError(RuntimeErrorCode.RESOURCE_INVALID, "resource inventory values must be integers")
        if self.total_vram_mib < 2_048:
            raise PrimitiveError(
                RuntimeErrorCode.RESOURCE_INVALID,
                "resource inventory must expose at least 2048 MiB VRAM headroom",
            )
        if self.total_ram_mib < 1:
            raise PrimitiveError(RuntimeErrorCode.RESOURCE_INVALID, "RAM inventory must be positive")
        if not 2_048 <= self.reserved_vram_headroom_mib <= self.total_vram_mib:
            raise PrimitiveError(
                RuntimeErrorCode.RESOURCE_INVALID,
                "reserved VRAM headroom must be at least 2048 MiB and not exceed total VRAM",
            )


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    owner: str
    vram_mib: int = 0
    ram_mib: int = 0
    priority: int = 50
    ttl_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not isinstance(self.owner, str) or _OWNER.fullmatch(self.owner) is None:
            raise PrimitiveError(RuntimeErrorCode.RESOURCE_INVALID, "resource owner is invalid")
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (self.vram_mib, self.ram_mib, self.priority)
        ):
            raise PrimitiveError(RuntimeErrorCode.RESOURCE_INVALID, "resource request values must be integers")
        if self.vram_mib < 0 or self.ram_mib < 0 or self.vram_mib + self.ram_mib <= 0:
            raise PrimitiveError(RuntimeErrorCode.RESOURCE_INVALID, "resource request must be positive")
        if not 0 <= self.priority <= 100:
            raise PrimitiveError(RuntimeErrorCode.RESOURCE_INVALID, "resource priority is invalid")
        if (
            isinstance(self.ttl_seconds, bool)
            or not isinstance(self.ttl_seconds, (int, float))
            or not 0 < self.ttl_seconds <= 86_400
        ):
            raise PrimitiveError(RuntimeErrorCode.RESOURCE_INVALID, "resource lease TTL is invalid")


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    active_leases: int
    total_vram_mib: int
    reserved_vram_headroom_mib: int
    used_vram_mib: int
    available_vram_mib: int
    total_ram_mib: int
    used_ram_mib: int
    available_ram_mib: int


class ResourceLease:
    def __init__(
        self,
        scheduler: FakeResourceScheduler,
        *,
        lease_id: str,
        request: ResourceRequest,
        granted_at_monotonic: float,
        expires_at_monotonic: float,
    ) -> None:
        self._scheduler = scheduler
        self.lease_id = lease_id
        self.request = request
        self.granted_at_monotonic = granted_at_monotonic
        self.expires_at_monotonic = expires_at_monotonic
        self._released = False
        self._expired = False

    @property
    def released(self) -> bool:
        return self._released

    @property
    def expired(self) -> bool:
        return self._expired or time.monotonic() >= self.expires_at_monotonic

    async def __aenter__(self) -> ResourceLease:
        self.assert_active()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.release()

    def assert_active(self) -> None:
        if self.expired:
            self._expired = True
            raise PrimitiveError(RuntimeErrorCode.RESOURCE_LEASE_EXPIRED, "resource lease expired")
        if self._released:
            raise PrimitiveError(RuntimeErrorCode.RESOURCE_LEASE_EXPIRED, "resource lease was released")

    async def release(self) -> bool:
        return await self._scheduler.release(self.lease_id)


class FakeResourceScheduler:
    def __init__(
        self,
        inventory: ResourceInventory,
        *,
        metrics: MetricRegistry | None = None,
    ) -> None:
        self.inventory = inventory
        self.metrics = metrics
        self._leases: dict[str, ResourceLease] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, request: ResourceRequest) -> ResourceLease:
        async with self._lock:
            self._prune_expired_locked()
            used_vram = sum(lease.request.vram_mib for lease in self._leases.values())
            used_ram = sum(lease.request.ram_mib for lease in self._leases.values())
            allocatable_vram = (
                self.inventory.total_vram_mib
                - self.inventory.reserved_vram_headroom_mib
            )
            if (
                used_vram + request.vram_mib > allocatable_vram
                or used_ram + request.ram_mib > self.inventory.total_ram_mib
            ):
                if self.metrics is not None:
                    self.metrics.increment(
                        "hina_resource_admission_total",
                        labels={"status": "denied"},
                    )
                raise PrimitiveError(
                    RuntimeErrorCode.RESOURCE_CAPACITY,
                    "resource request would exceed available capacity or reserved VRAM headroom",
                )
            now = time.monotonic()
            lease = ResourceLease(
                self,
                lease_id=str(uuid.uuid4()),
                request=request,
                granted_at_monotonic=now,
                expires_at_monotonic=now + request.ttl_seconds,
            )
            self._leases[lease.lease_id] = lease
            if self.metrics is not None:
                self.metrics.increment(
                    "hina_resource_admission_total",
                    labels={"status": "granted"},
                )
                self._update_metrics_locked()
            return lease

    async def release(self, lease_id: str) -> bool:
        async with self._lock:
            self._prune_expired_locked()
            lease = self._leases.pop(lease_id, None)
            if lease is None:
                return False
            lease._released = True
            if self.metrics is not None:
                self._update_metrics_locked()
            return True

    async def snapshot(self) -> ResourceSnapshot:
        async with self._lock:
            self._prune_expired_locked()
            return self._snapshot_locked()

    def _prune_expired_locked(self) -> int:
        now = time.monotonic()
        expired_ids = [
            lease_id
            for lease_id, lease in self._leases.items()
            if now >= lease.expires_at_monotonic
        ]
        for lease_id in expired_ids:
            lease = self._leases.pop(lease_id)
            lease._expired = True
            lease._released = True
        if expired_ids and self.metrics is not None:
            self.metrics.increment(
                "hina_resource_lease_expired_total",
                amount=len(expired_ids),
                labels={"status": "expired"},
            )
            self._update_metrics_locked()
        return len(expired_ids)

    def _snapshot_locked(self) -> ResourceSnapshot:
        used_vram = sum(lease.request.vram_mib for lease in self._leases.values())
        used_ram = sum(lease.request.ram_mib for lease in self._leases.values())
        allocatable_vram = (
            self.inventory.total_vram_mib
            - self.inventory.reserved_vram_headroom_mib
        )
        return ResourceSnapshot(
            active_leases=len(self._leases),
            total_vram_mib=self.inventory.total_vram_mib,
            reserved_vram_headroom_mib=self.inventory.reserved_vram_headroom_mib,
            used_vram_mib=used_vram,
            available_vram_mib=allocatable_vram - used_vram,
            total_ram_mib=self.inventory.total_ram_mib,
            used_ram_mib=used_ram,
            available_ram_mib=self.inventory.total_ram_mib - used_ram,
        )

    def _update_metrics_locked(self) -> None:
        if self.metrics is None:
            return
        snapshot = self._snapshot_locked()
        self.metrics.set_gauge("hina_resource_active_leases", snapshot.active_leases)
        self.metrics.set_gauge("hina_resource_vram_used_mib", snapshot.used_vram_mib)
        self.metrics.set_gauge(
            "hina_resource_vram_headroom_mib",
            snapshot.reserved_vram_headroom_mib + snapshot.available_vram_mib,
        )
