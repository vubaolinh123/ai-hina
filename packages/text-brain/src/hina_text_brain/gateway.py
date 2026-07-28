from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Callable, Protocol

from .config import ModelGatewayConfig
from .errors import TextBrainError
from .providers import LocalHttpChatProvider, ProviderHealth
from .resource import LocalResourceRequest, LocalResourceScheduler


_ADMISSION_TIMEOUT_SECONDS = 1.0


class ChatProvider(Protocol):
    async def health(self) -> ProviderHealth: ...

    def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...

    async def analyze_image(self, image_png: bytes, prompt: str) -> str: ...

    async def unload(self) -> None: ...

    async def warmup(self) -> None: ...


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
        self._operator_lock = asyncio.Condition()
        self._operator_lease: Any | None = None
        self._operator_users = 0
        self._request_users = 0

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
            "operatorResident": await self._operator_is_resident(),
        }

    async def warmup(self) -> dict[str, Any]:
        """Pin the text model through the shared scheduler until unload.

        This is an owner-only operator action. It deliberately uses a
        non-preemptible, bounded lease rather than asking Ollama to remain
        resident outside Hina's resource accounting.
        """

        async with self._operator_lock:
            lease = self._operator_lease
            if lease is not None and lease.state == "active":
                lease.assert_active()
                return {"state": "loaded", "operatorResident": True}
            if lease is not None:
                self._operator_lease = None
                await lease.release()
            try:
                lease = await self.scheduler.acquire(
                    LocalResourceRequest(
                        owner="model.text.operator",
                        vram_mib=self.config.model_vram_mib,
                        ram_mib=self.config.model_ram_mib,
                        priority=95,
                        ttl_seconds=86_400,
                        preemptible=False,
                    ),
                    wait_timeout_seconds=min(
                        _ADMISSION_TIMEOUT_SECONDS,
                        self.config.health_timeout_seconds,
                    ),
                )
                pin = getattr(self.provider, "set_operator_pinned", None)
                if pin is not None:
                    pin(True)
                warmup = getattr(self.provider, "warmup", None)
                if warmup is None:
                    raise TextBrainError(
                        "E_MODEL_REQUEST",
                        "configured model provider does not support manual loading",
                    )
                await warmup()
            except Exception:
                if lease is not None:
                    await lease.release()
                pin = getattr(self.provider, "set_operator_pinned", None)
                if pin is not None:
                    pin(False)
                raise
            self._operator_lease = lease
            return {"state": "loaded", "operatorResident": True}

    async def unload(self) -> None:
        """Release an owner-pinned text lease after active work is finished."""

        async with self._operator_lock:
            while self._operator_users or self._request_users:
                await self._operator_lock.wait()
            lease = self._operator_lease
            self._operator_lease = None
            pin = getattr(self.provider, "set_operator_pinned", None)
            if pin is not None:
                pin(False)
            try:
                await self.provider.unload()
            finally:
                if lease is not None:
                    await lease.release()

    async def resident_models(self) -> list[dict[str, object]]:
        resident = getattr(self.provider, "resident_models", None)
        if resident is None:
            return []
        try:
            result = await resident()
        except TextBrainError:
            return []
        if not isinstance(result, list):
            return []
        return [item for item in result[:64] if isinstance(item, dict)]

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
                lease, owned = await self._borrow_or_acquire(
                    owner="model.text",
                    priority=80,
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
                    await self._return_lease(lease, owned)
            assert last_error is not None
            await self._record_failure()
            raise last_error
        finally:
            if not completed:
                await self._leave_half_open()

    async def analyze_image(self, image_png: bytes, prompt: str) -> str:
        """Run one explicit snapshot through the shared local model lease."""

        await self._before_request()
        completed = False
        last_error: TextBrainError | None = None
        try:
            for attempt in range(self.config.retry_attempts + 1):
                lease, owned = await self._borrow_or_acquire(
                    owner="model.vision",
                    priority=70,
                )
                try:
                    result = await self.provider.analyze_image(image_png, prompt)
                    lease.assert_active()
                    if not isinstance(result, str) or not result.strip():
                        raise TextBrainError(
                            "E_MODEL_EMPTY_RESPONSE",
                            "local vision provider returned no text",
                            retryable=True,
                        )
                    completed = True
                    await self._record_success()
                    return result.strip()
                except TextBrainError as exc:
                    last_error = exc
                    if not exc.retryable or attempt >= self.config.retry_attempts:
                        await self._record_failure()
                        raise
                finally:
                    await self._return_lease(lease, owned)
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

    async def _borrow_or_acquire(
        self,
        *,
        owner: str,
        priority: int,
    ) -> tuple[Any, bool]:
        async with self._operator_lock:
            operator = self._operator_lease
            if operator is not None and operator.state == "active":
                try:
                    operator.assert_active()
                except Exception:
                    self._operator_lease = None
                    pin = getattr(self.provider, "set_operator_pinned", None)
                    if pin is not None:
                        pin(False)
                    await operator.release()
                else:
                    self._operator_users += 1
                    return operator, False
            elif operator is not None:
                self._operator_lease = None
                await operator.release()
        lease = await self.scheduler.acquire(
            LocalResourceRequest(
                owner=owner,
                vram_mib=self.config.model_vram_mib,
                ram_mib=self.config.model_ram_mib,
                priority=priority,
                ttl_seconds=self.config.request_timeout_seconds + 10,
                preemptible=True,
            ),
            wait_timeout_seconds=min(
                _ADMISSION_TIMEOUT_SECONDS,
                self.config.health_timeout_seconds,
            ),
            on_preempt=self.provider.unload,
        )
        async with self._operator_lock:
            self._request_users += 1
        return lease, True

    async def _return_lease(self, lease: Any, owned: bool) -> None:
        if owned:
            await lease.release()
            async with self._operator_lock:
                self._request_users = max(0, self._request_users - 1)
                self._operator_lock.notify_all()
            return
        async with self._operator_lock:
            self._operator_users = max(0, self._operator_users - 1)
            self._operator_lock.notify_all()

    async def _operator_is_resident(self) -> bool:
        async with self._operator_lock:
            lease = self._operator_lease
            if lease is None:
                return False
            try:
                lease.assert_active()
            except Exception:
                return False
            return True

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
