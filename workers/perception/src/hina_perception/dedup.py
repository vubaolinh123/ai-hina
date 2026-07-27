from __future__ import annotations

import time
from collections import deque
from typing import Callable

from .png import SnapshotSummary


def dhash64(summary: SnapshotSummary) -> int:
    """Difference hash over the 9x8 luma grid; 64 bits, no pixel retention."""

    value = 0
    for row in summary.luma_grid:
        for column in range(len(row) - 1):
            value = (value << 1) | (1 if row[column] > row[column + 1] else 0)
    return value


def hamming_distance(first: int, second: int) -> int:
    return (first ^ second).bit_count()


class SnapshotRateLimiter:
    """Sliding one-minute window on a monotonic clock; no wall-clock jumps."""

    def __init__(
        self,
        limit_per_minute: int,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if limit_per_minute < 1:
            raise ValueError("rate limit must be at least one per minute")
        self.limit_per_minute = limit_per_minute
        self._clock = clock or time.monotonic
        self._events: deque[float] = deque()

    def _prune(self, now: float) -> None:
        while self._events and self._events[0] <= now - 60.0:
            self._events.popleft()

    @property
    def remaining(self) -> int:
        self._prune(self._clock())
        return max(0, self.limit_per_minute - len(self._events))

    def try_acquire(self) -> bool:
        now = self._clock()
        self._prune(now)
        if len(self._events) >= self.limit_per_minute:
            return False
        self._events.append(now)
        return True
