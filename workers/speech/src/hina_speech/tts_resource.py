from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Protocol

from .errors import TtsError
from .model import TtsSynthesis
from .tts_provider import TtsProvider


class TtsGpuLease(Protocol):
    @property
    def state(self) -> str: ...

    def assert_active(self) -> None: ...

    async def release(self) -> bool: ...


TtsGpuLeaseFactory = Callable[
    [Callable[[], Awaitable[None]]],
    Awaitable[TtsGpuLease],
]


class ScheduledTtsProvider:
    """Keep a TTS model warm only while the shared GPU scheduler owns it.

    The lease is intentionally lower priority than chat and STT. A later text
    or microphone request preempts this provider, waits for any active native
    synthesis to finish, unloads the weights, and only then admits the next
    workload. This prevents CUDA allocations from living outside scheduler
    accounting while still avoiding a reload between consecutive TTS tests.
    """

    def __init__(
        self,
        provider: TtsProvider,
        lease_factory: TtsGpuLeaseFactory,
    ) -> None:
        self.provider = provider
        self.lease_factory = lease_factory
        self._operation_lock = asyncio.Lock()
        self._lease: TtsGpuLease | None = None
        self._closed = False

    async def status(self) -> dict[str, object]:
        status = dict(await self.provider.status())
        lease = self._lease
        status["resourceLease"] = {
            "required": True,
            "state": lease.state if lease is not None else "released",
        }
        return status

    async def warmup(self) -> None:
        async with self._operation_lock:
            self._assert_open()
            await self._ensure_lease_locked()
            warmup = getattr(self.provider, "warmup", None)
            if warmup is not None:
                await warmup()

    async def synthesize(
        self,
        chunks: tuple[str, ...],
        cancel_event: threading.Event,
    ) -> TtsSynthesis:
        async with self._operation_lock:
            self._assert_open()
            lease = await self._ensure_lease_locked()
            lease.assert_active()
            return await self.provider.synthesize(chunks, cancel_event)

    async def unload(self) -> None:
        async with self._operation_lock:
            await self._unload_locked()

    async def close(self) -> None:
        async with self._operation_lock:
            if self._closed:
                return
            self._closed = True
            await self._unload_locked()
            await self.provider.close()

    async def _ensure_lease_locked(self) -> TtsGpuLease:
        lease = self._lease
        if lease is not None and lease.state == "active":
            try:
                lease.assert_active()
                return lease
            except Exception:
                # Remove an expired lease ourselves before acquire() prunes it;
                # otherwise its preemption callback would re-enter unload()
                # while this operation lock is held.
                pass
        if lease is not None:
            self._lease = None
            await self.provider.unload()
            await lease.release()
        try:
            lease = await self.lease_factory(self.unload)
            lease.assert_active()
        except Exception as exc:
            raise TtsError(
                "E_TTS_RESOURCE_LEASE",
                "CUDA TTS resource lease was denied",
                retryable=True,
            ) from exc
        self._lease = lease
        return lease

    async def _unload_locked(self) -> None:
        lease = self._lease
        self._lease = None
        try:
            await self.provider.unload()
        finally:
            if lease is not None:
                await lease.release()

    def _assert_open(self) -> None:
        if self._closed:
            raise TtsError("E_TTS_UNAVAILABLE", "TTS provider is closed", retryable=True)
