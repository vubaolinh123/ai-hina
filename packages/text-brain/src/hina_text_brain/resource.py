from __future__ import annotations

import asyncio
import ctypes
import inspect
import re
import time
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from .errors import TextBrainError


MIN_VRAM_HEADROOM_MIB = 2_048
_OWNER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
UnloadCallback = Callable[[], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class TelemetrySnapshot:
    gpu_name: str
    total_vram_mib: int
    free_vram_mib: int
    total_ram_mib: int
    free_ram_mib: int

    def __post_init__(self) -> None:
        values = (
            self.total_vram_mib,
            self.free_vram_mib,
            self.total_ram_mib,
            self.free_ram_mib,
        )
        if (
            not self.gpu_name
            or any(isinstance(value, bool) or not isinstance(value, int) for value in values)
            or self.total_vram_mib < MIN_VRAM_HEADROOM_MIB
            or not 0 <= self.free_vram_mib <= self.total_vram_mib
            or self.total_ram_mib < 1
            or not 0 <= self.free_ram_mib <= self.total_ram_mib
        ):
            raise TextBrainError("E_RESOURCE_TELEMETRY", "resource telemetry is invalid")

    def as_json(self) -> dict[str, object]:
        return {
            "gpuName": self.gpu_name,
            "totalVramMiB": self.total_vram_mib,
            "freeVramMiB": self.free_vram_mib,
            "totalRamMiB": self.total_ram_mib,
            "freeRamMiB": self.free_ram_mib,
        }


class TelemetryProvider(Protocol):
    async def snapshot(self) -> TelemetrySnapshot: ...


class NvidiaSmiTelemetry:
    def __init__(self, *, command: str = "nvidia-smi", timeout_seconds: float = 3.0) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds

    async def snapshot(self) -> TelemetrySnapshot:
        try:
            process = await asyncio.create_subprocess_exec(
                self.command,
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except (FileNotFoundError, OSError, TimeoutError) as exc:
            raise TextBrainError(
                "E_RESOURCE_TELEMETRY",
                "NVIDIA telemetry is unavailable",
                retryable=True,
            ) from exc
        if process.returncode != 0:
            raise TextBrainError(
                "E_RESOURCE_TELEMETRY",
                "NVIDIA telemetry command failed",
                retryable=True,
            )
        try:
            first_line = stdout.decode("utf-8").splitlines()[0]
            gpu_name, total_vram, free_vram = (part.strip() for part in first_line.split(",", 2))
            total_ram, free_ram = _system_memory_mib()
            return TelemetrySnapshot(
                gpu_name=gpu_name,
                total_vram_mib=int(total_vram),
                free_vram_mib=int(free_vram),
                total_ram_mib=total_ram,
                free_ram_mib=free_ram,
            )
        except (IndexError, UnicodeDecodeError, ValueError) as exc:
            raise TextBrainError(
                "E_RESOURCE_TELEMETRY",
                "NVIDIA telemetry output is invalid",
                retryable=True,
            ) from exc


@dataclass(frozen=True, slots=True)
class LocalResourceRequest:
    owner: str
    vram_mib: int
    ram_mib: int
    priority: int = 50
    ttl_seconds: float = 120.0
    preemptible: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.owner, str) or _OWNER.fullmatch(self.owner) is None:
            raise TextBrainError("E_RESOURCE_REQUEST", "resource owner is invalid")
        for value, name, maximum in (
            (self.vram_mib, "VRAM", 65_536),
            (self.ram_mib, "RAM", 262_144),
            (self.priority, "priority", 100),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value > maximum
            ):
                raise TextBrainError("E_RESOURCE_REQUEST", f"resource {name} is invalid")
        if self.vram_mib + self.ram_mib <= 0:
            raise TextBrainError("E_RESOURCE_REQUEST", "resource request must be positive")
        if (
            isinstance(self.ttl_seconds, bool)
            or not isinstance(self.ttl_seconds, (int, float))
            or not 0 < self.ttl_seconds <= 86_400
        ):
            raise TextBrainError("E_RESOURCE_REQUEST", "resource lease TTL is invalid")


@dataclass(frozen=True, slots=True)
class SchedulerSnapshot:
    telemetry: TelemetrySnapshot
    active_leases: int
    reserved_vram_mib: int
    reserved_ram_mib: int
    available_vram_mib: int
    available_ram_mib: int
    headroom_mib: int

    def as_json(self) -> dict[str, object]:
        return {
            "telemetry": self.telemetry.as_json(),
            "activeLeases": self.active_leases,
            "reservedVramMiB": self.reserved_vram_mib,
            "reservedRamMiB": self.reserved_ram_mib,
            "availableVramMiB": self.available_vram_mib,
            "availableRamMiB": self.available_ram_mib,
            "headroomMiB": self.headroom_mib,
        }


class LocalResourceLease:
    def __init__(
        self,
        scheduler: LocalResourceScheduler,
        *,
        lease_id: str,
        request: LocalResourceRequest,
        expires_at: float,
    ) -> None:
        self._scheduler = scheduler
        self.lease_id = lease_id
        self.request = request
        self.expires_at_monotonic = expires_at
        self._state = "active"

    @property
    def state(self) -> str:
        return self._state

    def assert_active(self) -> None:
        if self._state != "active" or self._scheduler.clock() >= self.expires_at_monotonic:
            raise TextBrainError("E_RESOURCE_LEASE_EXPIRED", "resource lease is not active")

    async def release(self) -> bool:
        return await self._scheduler.release(self.lease_id)

    async def __aenter__(self) -> LocalResourceLease:
        self.assert_active()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.release()


@dataclass(slots=True)
class _LeaseRecord:
    lease: LocalResourceLease
    unload: UnloadCallback | None


class LocalResourceScheduler:
    def __init__(
        self,
        telemetry: TelemetryProvider,
        *,
        headroom_mib: int = MIN_VRAM_HEADROOM_MIB,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            isinstance(headroom_mib, bool)
            or not isinstance(headroom_mib, int)
            or headroom_mib < MIN_VRAM_HEADROOM_MIB
        ):
            raise TextBrainError("E_RESOURCE_REQUEST", "VRAM headroom is invalid")
        self.telemetry = telemetry
        self.headroom_mib = headroom_mib
        self.clock = clock
        self._condition = asyncio.Condition()
        self._leases: dict[str, _LeaseRecord] = {}

    async def acquire(
        self,
        request: LocalResourceRequest,
        *,
        wait_timeout_seconds: float = 0,
        on_preempt: UnloadCallback | None = None,
    ) -> LocalResourceLease:
        if (
            isinstance(wait_timeout_seconds, bool)
            or not isinstance(wait_timeout_seconds, (int, float))
            or not 0 <= wait_timeout_seconds <= 600
        ):
            raise TextBrainError("E_RESOURCE_REQUEST", "resource wait timeout is invalid")
        deadline = self.clock() + wait_timeout_seconds
        while True:
            callbacks: list[UnloadCallback] = []
            granted: LocalResourceLease | None = None
            should_retry = False
            async with self._condition:
                callbacks.extend(self._prune_expired_locked())
                telemetry = await self.telemetry.snapshot()
                if self._can_admit_locked(request, telemetry):
                    now = self.clock()
                    granted = LocalResourceLease(
                        self,
                        lease_id=str(uuid.uuid4()),
                        request=request,
                        expires_at=now + request.ttl_seconds,
                    )
                    self._leases[granted.lease_id] = _LeaseRecord(granted, on_preempt)
                else:
                    preempted = self._preempt_lower_priority_locked(request, telemetry)
                    callbacks.extend(
                        record.unload
                        for record in preempted
                        if record.unload is not None
                    )
                    if preempted or callbacks:
                        should_retry = True
                        self._condition.notify_all()
                    else:
                        remaining = deadline - self.clock()
                        if remaining <= 0:
                            raise TextBrainError(
                                "E_RESOURCE_CAPACITY",
                                "resource admission would violate local headroom",
                                retryable=True,
                            )
                        try:
                            await asyncio.wait_for(
                                self._condition.wait(),
                                timeout=min(remaining, 0.1),
                            )
                        except TimeoutError:
                            pass
                        should_retry = True
            for callback in callbacks:
                await _safe_unload(callback)
            if granted is not None:
                return granted
            if should_retry:
                continue

    async def release(self, lease_id: str) -> bool:
        async with self._condition:
            record = self._leases.pop(lease_id, None)
            if record is None:
                return False
            record.lease._state = "released"
            self._condition.notify_all()
            return True

    async def snapshot(self) -> SchedulerSnapshot:
        callbacks: list[UnloadCallback]
        async with self._condition:
            callbacks = self._prune_expired_locked()
            telemetry = await self.telemetry.snapshot()
            snapshot = self._snapshot_locked(telemetry)
        for callback in callbacks:
            await _safe_unload(callback)
        return snapshot

    def _can_admit_locked(
        self,
        request: LocalResourceRequest,
        telemetry: TelemetrySnapshot,
    ) -> bool:
        snapshot = self._snapshot_locked(telemetry)
        return (
            request.vram_mib <= snapshot.available_vram_mib
            and request.ram_mib <= snapshot.available_ram_mib
        )

    def _snapshot_locked(self, telemetry: TelemetrySnapshot) -> SchedulerSnapshot:
        reserved_vram = sum(record.lease.request.vram_mib for record in self._leases.values())
        reserved_ram = sum(record.lease.request.ram_mib for record in self._leases.values())
        allocatable_from_total = max(
            0,
            telemetry.total_vram_mib - self.headroom_mib - reserved_vram,
        )
        allocatable_from_live_free = max(0, telemetry.free_vram_mib - self.headroom_mib)
        available_vram = min(allocatable_from_total, allocatable_from_live_free)
        available_ram = max(
            0,
            min(
                telemetry.total_ram_mib - reserved_ram,
                telemetry.free_ram_mib,
            ),
        )
        return SchedulerSnapshot(
            telemetry=telemetry,
            active_leases=len(self._leases),
            reserved_vram_mib=reserved_vram,
            reserved_ram_mib=reserved_ram,
            available_vram_mib=available_vram,
            available_ram_mib=available_ram,
            headroom_mib=self.headroom_mib,
        )

    def _preempt_lower_priority_locked(
        self,
        request: LocalResourceRequest,
        telemetry: TelemetrySnapshot,
    ) -> list[_LeaseRecord]:
        candidates = sorted(
            (
                record
                for record in self._leases.values()
                if record.lease.request.preemptible
                and record.lease.request.priority < request.priority
            ),
            key=lambda item: (item.lease.request.priority, item.lease.expires_at_monotonic),
        )
        preempted: list[_LeaseRecord] = []
        anticipated_free_vram = telemetry.free_vram_mib
        anticipated_free_ram = telemetry.free_ram_mib
        for record in candidates:
            self._leases.pop(record.lease.lease_id, None)
            record.lease._state = "preempted"
            preempted.append(record)
            anticipated_free_vram = min(
                telemetry.total_vram_mib,
                anticipated_free_vram + record.lease.request.vram_mib,
            )
            anticipated_free_ram = min(
                telemetry.total_ram_mib,
                anticipated_free_ram + record.lease.request.ram_mib,
            )
            anticipated = TelemetrySnapshot(
                gpu_name=telemetry.gpu_name,
                total_vram_mib=telemetry.total_vram_mib,
                free_vram_mib=anticipated_free_vram,
                total_ram_mib=telemetry.total_ram_mib,
                free_ram_mib=anticipated_free_ram,
            )
            if self._can_admit_locked(request, anticipated):
                break
        if preempted:
            anticipated = TelemetrySnapshot(
                gpu_name=telemetry.gpu_name,
                total_vram_mib=telemetry.total_vram_mib,
                free_vram_mib=anticipated_free_vram,
                total_ram_mib=telemetry.total_ram_mib,
                free_ram_mib=anticipated_free_ram,
            )
        if not preempted or not self._can_admit_locked(request, anticipated):
            for record in preempted:
                record.lease._state = "active"
                self._leases[record.lease.lease_id] = record
            return []
        return preempted

    def _prune_expired_locked(self) -> list[UnloadCallback]:
        now = self.clock()
        callbacks: list[UnloadCallback] = []
        expired = [
            lease_id
            for lease_id, record in self._leases.items()
            if now >= record.lease.expires_at_monotonic
        ]
        for lease_id in expired:
            record = self._leases.pop(lease_id)
            record.lease._state = "expired"
            if record.unload is not None:
                callbacks.append(record.unload)
        if expired:
            self._condition.notify_all()
        return callbacks


async def _safe_unload(callback: UnloadCallback) -> None:
    try:
        result = callback()
        if inspect.isawaitable(result):
            await result
    except Exception:
        pass


def _system_memory_mib() -> tuple[int, int]:
    if hasattr(ctypes, "windll"):
        class _MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(_MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise TextBrainError("E_RESOURCE_TELEMETRY", "system RAM telemetry failed")
        return status.ullTotalPhys // (1024 * 1024), status.ullAvailPhys // (1024 * 1024)
    try:
        import os

        page_size = os.sysconf("SC_PAGE_SIZE")
        total_pages = os.sysconf("SC_PHYS_PAGES")
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
        return (
            int(page_size * total_pages // (1024 * 1024)),
            int(page_size * available_pages // (1024 * 1024)),
        )
    except (AttributeError, OSError, ValueError) as exc:
        raise TextBrainError("E_RESOURCE_TELEMETRY", "system RAM telemetry failed") from exc
