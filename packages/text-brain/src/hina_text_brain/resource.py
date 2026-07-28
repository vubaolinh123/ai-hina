from __future__ import annotations

import asyncio
import csv
import ctypes
import io
import inspect
import re
import time
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from .errors import TextBrainError


# The admission ceiling leaves a small static cushion on a nominal 16 GiB card
# (15.5 GiB usable by Hina).  NVIDIA's live ``memory.free`` already excludes
# Windows, the desktop compositor and other GPU applications, so those bytes
# must not be subtracted a second time by the scheduler.
DEFAULT_HINA_VRAM_ADMISSION_CEILING_MIB = 15_872
DEFAULT_LIVE_FREE_RESERVE_MIB = 0
MIN_VRAM_HEADROOM_MIB = 0
MAX_TELEMETRY_OUTPUT_BYTES = 65_536
_OWNER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
UnloadCallback = Callable[[], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class TelemetrySnapshot:
    gpu_name: str
    total_vram_mib: int
    free_vram_mib: int
    total_ram_mib: int
    free_ram_mib: int
    used_vram_mib: int | None = None
    gpu_utilization_percent: float | None = None
    temperature_celsius: float | None = None
    power_draw_watts: float | None = None

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
        optional_values = (
            (self.used_vram_mib, 0, self.total_vram_mib),
            (self.gpu_utilization_percent, 0, 100),
            (self.temperature_celsius, -100, 200),
            (self.power_draw_watts, 0, 10_000),
        )
        if any(
            value is not None
            and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not lower <= value <= upper
            )
            for value, lower, upper in optional_values
        ):
            raise TextBrainError("E_RESOURCE_TELEMETRY", "resource telemetry is invalid")

    def as_json(self) -> dict[str, object]:
        used_vram_mib = (
            self.used_vram_mib
            if self.used_vram_mib is not None
            else self.total_vram_mib - self.free_vram_mib
        )
        return {
            "gpuName": self.gpu_name,
            "totalVramMiB": self.total_vram_mib,
            "usedVramMiB": used_vram_mib,
            "freeVramMiB": self.free_vram_mib,
            "totalRamMiB": self.total_ram_mib,
            "freeRamMiB": self.free_ram_mib,
            "usedRamMiB": self.total_ram_mib - self.free_ram_mib,
            "gpuUtilizationPercent": self.gpu_utilization_percent,
            "temperatureCelsius": self.temperature_celsius,
            "powerDrawWatts": self.power_draw_watts,
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
                (
                    "--query-gpu=name,memory.total,memory.used,memory.free,"
                    "utilization.gpu,temperature.gpu,power.draw"
                ),
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=MAX_TELEMETRY_OUTPUT_BYTES,
            )
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except (FileNotFoundError, OSError, TimeoutError, ValueError) as exc:
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
        if len(stdout) > MAX_TELEMETRY_OUTPUT_BYTES:
            raise TextBrainError(
                "E_RESOURCE_TELEMETRY",
                "NVIDIA telemetry output exceeds the limit",
                retryable=True,
            )
        total_ram, free_ram = _system_memory_mib()
        return _parse_nvidia_smi_output(
            stdout,
            total_ram_mib=total_ram,
            free_ram_mib=free_ram,
        )


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
    admission_ceiling_mib: int
    live_free_reserve_mib: int

    def as_json(self) -> dict[str, object]:
        return {
            "telemetry": self.telemetry.as_json(),
            "activeLeases": self.active_leases,
            "reservedVramMiB": self.reserved_vram_mib,
            "reservedRamMiB": self.reserved_ram_mib,
            "availableVramMiB": self.available_vram_mib,
            "availableRamMiB": self.available_ram_mib,
            "headroomMiB": self.headroom_mib,
            "admissionCeilingMiB": self.admission_ceiling_mib,
            "liveFreeReserveMiB": self.live_free_reserve_mib,
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
        admission_ceiling_mib: int = DEFAULT_HINA_VRAM_ADMISSION_CEILING_MIB,
        live_free_reserve_mib: int = DEFAULT_LIVE_FREE_RESERVE_MIB,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            isinstance(headroom_mib, bool)
            or not isinstance(headroom_mib, int)
            or headroom_mib < MIN_VRAM_HEADROOM_MIB
        ):
            raise TextBrainError("E_RESOURCE_REQUEST", "VRAM headroom is invalid")
        for value, name in (
            (admission_ceiling_mib, "VRAM admission ceiling"),
            (live_free_reserve_mib, "live-free VRAM reserve"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value > 65_536
            ):
                raise TextBrainError("E_RESOURCE_REQUEST", f"{name} is invalid")
        self.telemetry = telemetry
        self.headroom_mib = headroom_mib
        self.admission_ceiling_mib = admission_ceiling_mib
        self.live_free_reserve_mib = live_free_reserve_mib
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

    async def monitor_status(self) -> dict[str, object]:
        """Return a bounded, read-only scheduler view for owner diagnostics.

        Physical measurements may fail independently from the lease ledger.
        Reservations are therefore still visible during a telemetry outage and
        are explicitly kept separate from measured allocation.
        """

        callbacks: list[UnloadCallback]
        async with self._condition:
            callbacks = self._prune_expired_locked()
            leases = self._lease_status_locked()
            reserved_vram = sum(
                record.lease.request.vram_mib for record in self._leases.values()
            )
            reserved_ram = sum(
                record.lease.request.ram_mib for record in self._leases.values()
            )
            try:
                telemetry = await self.telemetry.snapshot()
            except TextBrainError as exc:
                status: dict[str, object] = {
                    "available": False,
                    "errorCode": exc.code,
                    "telemetry": None,
                    "activeLeases": len(self._leases),
                    "reservedVramMiB": reserved_vram,
                    "reservedRamMiB": reserved_ram,
                    "availableVramMiB": None,
                    "availableRamMiB": None,
                    "headroomMiB": self.headroom_mib,
                    "admissionCeilingMiB": self.admission_ceiling_mib,
                    "liveFreeReserveMiB": self.live_free_reserve_mib,
                    "leases": leases,
                }
            else:
                snapshot = self._snapshot_locked(telemetry)
                status = {
                    "available": True,
                    **snapshot.as_json(),
                    "leases": leases,
                }
        for callback in callbacks:
            await _safe_unload(callback)
        return status

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
        # The configured Hina ceiling protects a small static cushion even if
        # the GPU is otherwise idle. ``free_vram_mib`` is already post-Windows
        # and post-other-process usage, so subtract only the explicit live
        # reserve (zero in the owner-approved 15.5 GiB profile).
        effective_ceiling = min(
            telemetry.total_vram_mib,
            self.admission_ceiling_mib,
        )
        allocatable_from_total = max(0, effective_ceiling - reserved_vram)
        allocatable_from_live_free = max(
            0,
            telemetry.free_vram_mib - self.live_free_reserve_mib,
        )
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
            admission_ceiling_mib=effective_ceiling,
            live_free_reserve_mib=self.live_free_reserve_mib,
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

    def _lease_status_locked(self) -> list[dict[str, object]]:
        now = self.clock()
        return [
            {
                "owner": record.lease.request.owner,
                "state": record.lease.state,
                "reservedVramMiB": record.lease.request.vram_mib,
                "reservedRamMiB": record.lease.request.ram_mib,
                "priority": record.lease.request.priority,
                "preemptible": record.lease.request.preemptible,
                "remainingTtlSeconds": round(
                    max(0.0, record.lease.expires_at_monotonic - now),
                    3,
                ),
            }
            for record in sorted(
                self._leases.values(),
                key=lambda item: (
                    -item.lease.request.priority,
                    item.lease.request.owner,
                ),
            )
        ]


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


def _parse_nvidia_smi_output(
    raw: bytes,
    *,
    total_ram_mib: int,
    free_ram_mib: int,
) -> TelemetrySnapshot:
    try:
        text = raw.decode("utf-8")
        rows = list(csv.reader(io.StringIO(text)))
        if len(rows) != 1 or len(rows[0]) != 7:
            raise ValueError
        fields = [field.strip() for field in rows[0]]
        gpu_name = fields[0]
        total_vram = int(fields[1])
        used_vram = _optional_int(fields[2])
        free_vram = int(fields[3])
        utilization = _optional_float(fields[4])
        temperature = _optional_float(fields[5])
        power_draw = _optional_float(fields[6])
        return TelemetrySnapshot(
            gpu_name=gpu_name,
            total_vram_mib=total_vram,
            free_vram_mib=free_vram,
            total_ram_mib=total_ram_mib,
            free_ram_mib=free_ram_mib,
            used_vram_mib=used_vram,
            gpu_utilization_percent=utilization,
            temperature_celsius=temperature,
            power_draw_watts=power_draw,
        )
    except (IndexError, UnicodeDecodeError, ValueError) as exc:
        raise TextBrainError(
            "E_RESOURCE_TELEMETRY",
            "NVIDIA telemetry output is invalid",
            retryable=True,
        ) from exc


def _optional_int(value: str) -> int | None:
    parsed = _optional_float(value)
    return int(parsed) if parsed is not None else None


def _optional_float(value: str) -> float | None:
    if value.casefold() in {"n/a", "[n/a]", "na", "not supported"}:
        return None
    return float(value)
