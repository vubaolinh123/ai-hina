from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Callable, Protocol

from .config import ModelGatewayConfig
from .errors import TextBrainError
from .providers import LocalHttpChatProvider, ProviderHealth
from .resource import LocalResourceRequest, LocalResourceScheduler


class ChatProvider(Protocol):
    async def health(self) -> ProviderHealth: ...

    def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...

    async def unload(self) -> None: ...


class ModelGateway:
    def __init__(
        self,
        config: ModelGatewayConfig,
        scheduler: LocalResourceScheduler,
        *,
        provider: ChatProvider | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.scheduler = scheduler
        self.provider = provider or LocalHttpChatProvider(config)
        self.clock = clock
        self._circuit_lock = asyncio.Lock()
        self._circuit_state = "closed"
        self._failure_count = 0
        self._opened_at: float | None = None
        self._half_open_in_flight = False

    async def status(self) -> dict[str, Any]:
        health = await self.provider.health()
        resource: dict[str, Any]
        resource_available = True
        try:
            resource = (await self.scheduler.snapshot()).as_json()
        except TextBrainError as exc:
            resource_available = False
            resource = {
                "available": False,
                "errorCode": exc.code,
                "headroomMiB": self.scheduler.headroom_mib,
            }
        circuit = await self._circuit_snapshot()
        return {
            "configured": self.config.public_status(),
            "provider": health.as_json(),
            "resource": resource,
            "circuit": circuit,
            "available": (
                health.reachable
                and health.model_available
                and resource_available
                and circuit["state"] != "open"
            ),
        }

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        await self._before_request()
        completed = False
        last_error: TextBrainError | None = None
        try:
            for attempt in range(self.config.retry_attempts + 1):
                emitted = False
                lease = await self.scheduler.acquire(
                    LocalResourceRequest(
                        owner="model.text",
                        vram_mib=self.config.model_vram_mib,
                        ram_mib=self.config.model_ram_mib,
                        priority=80,
                        ttl_seconds=self.config.request_timeout_seconds + 10,
                        preemptible=True,
                    ),
                    wait_timeout_seconds=min(5.0, self.config.health_timeout_seconds),
                    on_preempt=self.provider.unload,
                )
                try:
                    async for token in self.provider.stream_chat(messages):
                        lease.assert_active()
                        emitted = True
                        yield token
                    if not emitted:
                        raise TextBrainError(
                            "E_MODEL_EMPTY_RESPONSE",
                            "local model provider returned no text",
                            retryable=True,
                        )
                    completed = True
                    await self._record_success()
                    return
                except TextBrainError as exc:
                    last_error = exc
                    if emitted or not exc.retryable or attempt >= self.config.retry_attempts:
                        await self._record_failure()
                        raise
                finally:
                    await lease.release()
            assert last_error is not None
            await self._record_failure()
            raise last_error
        finally:
            if not completed:
                await self._leave_half_open()

    async def _before_request(self) -> None:
        async with self._circuit_lock:
            if self._circuit_state == "open":
                assert self._opened_at is not None
                if self.clock() - self._opened_at < self.config.circuit_reset_seconds:
                    raise TextBrainError(
                        "E_MODEL_CIRCUIT_OPEN",
                        "local model circuit is open",
                        retryable=True,
                    )
                self._circuit_state = "half_open"
                self._half_open_in_flight = False
            if self._circuit_state == "half_open":
                if self._half_open_in_flight:
                    raise TextBrainError(
                        "E_MODEL_CIRCUIT_OPEN",
                        "local model recovery probe is already running",
                        retryable=True,
                    )
                self._half_open_in_flight = True

    async def _record_success(self) -> None:
        async with self._circuit_lock:
            self._circuit_state = "closed"
            self._failure_count = 0
            self._opened_at = None
            self._half_open_in_flight = False

    async def _record_failure(self) -> None:
        async with self._circuit_lock:
            self._failure_count += 1
            self._half_open_in_flight = False
            if (
                self._circuit_state == "half_open"
                or self._failure_count >= self.config.circuit_failure_threshold
            ):
                self._circuit_state = "open"
                self._opened_at = self.clock()

    async def _leave_half_open(self) -> None:
        async with self._circuit_lock:
            self._half_open_in_flight = False

    async def _circuit_snapshot(self) -> dict[str, Any]:
        async with self._circuit_lock:
            retry_after = 0.0
            if self._circuit_state == "open" and self._opened_at is not None:
                retry_after = max(
                    0.0,
                    self.config.circuit_reset_seconds - (self.clock() - self._opened_at),
                )
            return {
                "state": self._circuit_state,
                "failureCount": self._failure_count,
                "retryAfterSeconds": round(retry_after, 3),
            }
