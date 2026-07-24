from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar


T = TypeVar("T")


class RuntimeErrorCode(StrEnum):
    QUEUE_FULL = "E_QUEUE_FULL"
    DEADLINE_EXCEEDED = "E_DEADLINE_EXCEEDED"
    CANCELLED = "E_CANCELLED"
    IDEMPOTENCY_KEY_INVALID = "E_IDEMPOTENCY_KEY_INVALID"
    IDEMPOTENCY_CAPACITY = "E_IDEMPOTENCY_CAPACITY"
    DURABLE_INVALID_EVENT = "E_DURABLE_INVALID_EVENT"
    JOURNAL_CONFLICT = "E_JOURNAL_CONFLICT"
    OUTBOX_NOT_FOUND = "E_OUTBOX_NOT_FOUND"
    ACK_INVALID_STATE = "E_ACK_INVALID_STATE"
    INBOX_NOT_FOUND = "E_INBOX_NOT_FOUND"
    DURABLE_STORE = "E_DURABLE_STORE"
    NETWORK_BIND_DENIED = "E_NETWORK_BIND_DENIED"
    HTTP_BAD_REQUEST = "E_HTTP_BAD_REQUEST"
    WEBSOCKET_HANDSHAKE = "E_WEBSOCKET_HANDSHAKE"
    WEBSOCKET_PROTOCOL = "E_WEBSOCKET_PROTOCOL"
    FRAME_TOO_LARGE = "E_FRAME_TOO_LARGE"
    EVENT_REJECTED = "E_EVENT_REJECTED"
    CONNECTION_LIMIT = "E_CONNECTION_LIMIT"
    MEDIA_INVALID = "E_MEDIA_INVALID"
    SERVICE_DUPLICATE = "E_SERVICE_DUPLICATE"
    SERVICE_INVALID = "E_SERVICE_INVALID"
    SERVICE_DEPENDENCY = "E_SERVICE_DEPENDENCY"
    SERVICE_CYCLE = "E_SERVICE_CYCLE"
    SERVICE_START_FAILED = "E_SERVICE_START_FAILED"
    SERVICE_STOP_FAILED = "E_SERVICE_STOP_FAILED"
    SERVICE_UNHEALTHY = "E_SERVICE_UNHEALTHY"
    OBSERVABILITY_INVALID = "E_OBSERVABILITY_INVALID"
    METRIC_CAPACITY = "E_METRIC_CAPACITY"
    RESOURCE_INVALID = "E_RESOURCE_INVALID"
    RESOURCE_CAPACITY = "E_RESOURCE_CAPACITY"
    RESOURCE_LEASE_EXPIRED = "E_RESOURCE_LEASE_EXPIRED"
    REPLAY_CONFLICT = "E_REPLAY_CONFLICT"
    SAFETY_BAD_REQUEST = "E_SAFETY_BAD_REQUEST"
    SAFETY_UNAVAILABLE = "E_SAFETY_UNAVAILABLE"
    CHAT_BAD_REQUEST = "E_CHAT_BAD_REQUEST"
    CHAT_NOT_FOUND = "E_CHAT_NOT_FOUND"
    CHAT_CONFLICT = "E_CHAT_CONFLICT"
    CHAT_UNAVAILABLE = "E_CHAT_UNAVAILABLE"
    AVATAR_BAD_REQUEST = "E_AVATAR_BAD_REQUEST"
    AVATAR_FORBIDDEN = "E_AVATAR_FORBIDDEN"
    AVATAR_UNAVAILABLE = "E_AVATAR_UNAVAILABLE"
    OPERATION_FAILED = "E_OPERATION_FAILED"


class PrimitiveError(Exception):
    def __init__(self, code: RuntimeErrorCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Deadline:
    expires_at: float

    @classmethod
    def after(cls, seconds: float) -> Deadline:
        if seconds < 0:
            raise ValueError("deadline seconds must be non-negative")
        return cls(time.monotonic() + seconds)

    @property
    def remaining(self) -> float:
        return max(0.0, self.expires_at - time.monotonic())

    @property
    def expired(self) -> bool:
        return self.remaining <= 0


class CancellationToken:
    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._reason = "operation cancelled"

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def cancel(self, reason: str = "operation cancelled") -> bool:
        if self.cancelled:
            return False
        self._reason = reason[:256] or "operation cancelled"
        self._event.set()
        return True

    async def wait(self) -> None:
        await self._event.wait()

    def throw_if_cancelled(self) -> None:
        if self.cancelled:
            raise PrimitiveError(RuntimeErrorCode.CANCELLED, self.reason)


async def wait_controlled(
    awaitable: Awaitable[T],
    *,
    deadline: Deadline | None = None,
    cancellation: CancellationToken | None = None,
) -> T:
    operation = asyncio.ensure_future(awaitable)
    cancellation_wait: asyncio.Task[None] | None = None
    try:
        if cancellation is not None:
            cancellation.throw_if_cancelled()
            cancellation_wait = asyncio.create_task(cancellation.wait())

        timeout = deadline.remaining if deadline is not None else None
        if timeout is not None and timeout <= 0:
            raise PrimitiveError(RuntimeErrorCode.DEADLINE_EXCEEDED, "deadline exceeded")

        wait_set: set[asyncio.Future[object]] = {operation}
        if cancellation_wait is not None:
            wait_set.add(cancellation_wait)
        done, _ = await asyncio.wait(wait_set, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)

        if operation in done:
            return await operation
        if cancellation_wait is not None and cancellation_wait in done:
            raise PrimitiveError(RuntimeErrorCode.CANCELLED, cancellation.reason)
        raise PrimitiveError(RuntimeErrorCode.DEADLINE_EXCEEDED, "deadline exceeded")
    finally:
        if not operation.done():
            operation.cancel()
        if cancellation_wait is not None and not cancellation_wait.done():
            cancellation_wait.cancel()
        pending = [task for task in (operation, cancellation_wait) if task is not None and not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


class OverflowPolicy(StrEnum):
    REJECT_NEW = "reject_new"
    DROP_OLDEST = "drop_oldest"
    WAIT = "wait"


@dataclass(frozen=True, slots=True)
class QueuePutResult(Generic[T]):
    accepted: bool
    dropped: T | None = None


@dataclass(frozen=True, slots=True)
class QueueMetrics:
    accepted: int
    dequeued: int
    dropped: int
    rejected: int


class BoundedAsyncQueue(Generic[T]):
    def __init__(self, capacity: int, overflow: OverflowPolicy = OverflowPolicy.WAIT) -> None:
        if capacity < 1:
            raise ValueError("queue capacity must be at least one")
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize=capacity)
        self.capacity = capacity
        self.overflow = overflow
        self._accepted = 0
        self._dequeued = 0
        self._dropped = 0
        self._rejected = 0

    @property
    def size(self) -> int:
        return self._queue.qsize()

    @property
    def metrics(self) -> QueueMetrics:
        return QueueMetrics(self._accepted, self._dequeued, self._dropped, self._rejected)

    async def put(
        self,
        item: T,
        *,
        deadline: Deadline | None = None,
        cancellation: CancellationToken | None = None,
    ) -> QueuePutResult[T]:
        if self.overflow is OverflowPolicy.WAIT:
            await wait_controlled(self._queue.put(item), deadline=deadline, cancellation=cancellation)
            self._accepted += 1
            return QueuePutResult(True)

        if self._queue.full() and self.overflow is OverflowPolicy.REJECT_NEW:
            self._rejected += 1
            raise PrimitiveError(RuntimeErrorCode.QUEUE_FULL, f"queue capacity {self.capacity} reached")

        dropped: T | None = None
        if self._queue.full():
            dropped = self._queue.get_nowait()
            self._queue.task_done()
            self._dropped += 1
        self._queue.put_nowait(item)
        self._accepted += 1
        return QueuePutResult(True, dropped)

    async def get(
        self,
        *,
        deadline: Deadline | None = None,
        cancellation: CancellationToken | None = None,
    ) -> T:
        item = await wait_controlled(self._queue.get(), deadline=deadline, cancellation=cancellation)
        self._dequeued += 1
        return item

    def task_done(self) -> None:
        self._queue.task_done()

    async def join(
        self,
        *,
        deadline: Deadline | None = None,
        cancellation: CancellationToken | None = None,
    ) -> None:
        await wait_controlled(self._queue.join(), deadline=deadline, cancellation=cancellation)


class IdempotencySource(StrEnum):
    EXECUTED = "executed"
    COALESCED = "coalesced"
    REPLAYED = "replayed"


@dataclass(frozen=True, slots=True)
class IdempotencyResult(Generic[T]):
    value: T
    source: IdempotencySource


@dataclass(frozen=True, slots=True)
class _Failure:
    code: RuntimeErrorCode
    detail: str


@dataclass(frozen=True, slots=True)
class _Completion(Generic[T]):
    value: T | None = None
    failure: _Failure | None = None


@dataclass(slots=True)
class _Entry(Generic[T]):
    future: asyncio.Future[_Completion[T]]
    expires_at: float
    completed: bool = False


class IdempotencyRegistry(Generic[T]):
    def __init__(
        self,
        max_entries: int = 1024,
        default_ttl_seconds: float = 300.0,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least one")
        if default_ttl_seconds <= 0:
            raise ValueError("default TTL must be positive")
        self.max_entries = max_entries
        self.default_ttl_seconds = default_ttl_seconds
        self._clock = clock or time.monotonic
        self._entries: OrderedDict[str, _Entry[T]] = OrderedDict()
        self._lock = asyncio.Lock()

    @property
    def size(self) -> int:
        return len(self._entries)

    async def run_once(
        self,
        key: str,
        operation: Callable[[], Awaitable[T]],
        *,
        ttl_seconds: float | None = None,
        deadline: Deadline | None = None,
        cancellation: CancellationToken | None = None,
    ) -> IdempotencyResult[T]:
        self._validate_key(key)
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            raise ValueError("TTL must be positive")

        async with self._lock:
            self._prune_expired_locked()
            entry = self._entries.get(key)
            owner = entry is None
            was_completed = entry.completed if entry is not None else False
            if entry is None:
                self._make_capacity_locked()
                entry = _Entry(asyncio.get_running_loop().create_future(), float("inf"))
                self._entries[key] = entry
            else:
                self._entries.move_to_end(key)

        if not owner:
            completion = await wait_controlled(
                asyncio.shield(entry.future),
                deadline=deadline,
                cancellation=cancellation,
            )
            if completion.failure is not None:
                raise PrimitiveError(completion.failure.code, completion.failure.detail)
            return IdempotencyResult(
                completion.value,  # type: ignore[arg-type]
                IdempotencySource.REPLAYED if was_completed else IdempotencySource.COALESCED,
            )

        try:
            value = await wait_controlled(operation(), deadline=deadline, cancellation=cancellation)
        except PrimitiveError as exc:
            await self._fail_owner(key, entry, _Failure(exc.code, exc.detail))
            raise
        except Exception as exc:
            failure = _Failure(RuntimeErrorCode.OPERATION_FAILED, str(exc)[:512] or type(exc).__name__)
            await self._fail_owner(key, entry, failure)
            raise PrimitiveError(failure.code, failure.detail) from exc

        async with self._lock:
            current = self._entries.get(key)
            if current is entry:
                entry.completed = True
                entry.expires_at = self._clock() + ttl
                self._entries.move_to_end(key)
            if not entry.future.done():
                entry.future.set_result(_Completion(value=value))
        return IdempotencyResult(value, IdempotencySource.EXECUTED)

    async def prune_expired(self) -> int:
        async with self._lock:
            return self._prune_expired_locked()

    async def _fail_owner(self, key: str, entry: _Entry[T], failure: _Failure) -> None:
        async with self._lock:
            if self._entries.get(key) is entry:
                del self._entries[key]
            if not entry.future.done():
                entry.future.set_result(_Completion(failure=failure))

    def _prune_expired_locked(self) -> int:
        now = self._clock()
        expired = [key for key, entry in self._entries.items() if entry.completed and entry.expires_at <= now]
        for key in expired:
            del self._entries[key]
        return len(expired)

    def _make_capacity_locked(self) -> None:
        if len(self._entries) < self.max_entries:
            return
        completed_key = next((key for key, entry in self._entries.items() if entry.completed), None)
        if completed_key is not None:
            del self._entries[completed_key]
            return
        raise PrimitiveError(RuntimeErrorCode.IDEMPOTENCY_CAPACITY, "all idempotency slots are in flight")

    @staticmethod
    def _validate_key(key: str) -> None:
        if not key or len(key) > 128 or any(ord(char) < 0x20 or ord(char) == 0x7F for char in key):
            raise PrimitiveError(RuntimeErrorCode.IDEMPOTENCY_KEY_INVALID, "idempotency key is invalid")
