from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from .errors import PerceptionError


OBSERVATION_KIND = "screen.snapshot"
OBSERVATION_TRUST_LEVEL = "untrusted"


@dataclass(slots=True)
class _LedgerEntry:
    record: dict[str, Any]
    monotonic_deadline: float
    dhash: int


@dataclass(slots=True)
class FreshnessLedger:
    """Bounded in-memory observation store with monotonic-elapsed expiry.

    Wall-clock timestamps are attached for display only; expiry decisions use
    the injected monotonic clock exclusively, so system clock changes can never
    resurrect a stale snapshot. Nothing is ever persisted to disk.
    """

    ttl_seconds: float
    capacity: int
    clock: Callable[[], float] = time.monotonic
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    _entries: OrderedDict[str, _LedgerEntry] = field(default_factory=OrderedDict)
    _expired_total: int = 0
    _accepted_total: int = 0

    def __post_init__(self) -> None:
        if self.ttl_seconds <= 0:
            raise PerceptionError("E_PERCEPTION_CONFIG", "observation TTL must be positive")
        if self.capacity < 1:
            raise PerceptionError("E_PERCEPTION_CONFIG", "observation capacity must be at least one")

    def add(self, observation_id: str, record: dict[str, Any], dhash: int) -> dict[str, Any]:
        moment = self.clock()
        self._prune(moment)
        captured_at = self.now()
        stored = {
            **record,
            "observationId": observation_id,
            "kind": OBSERVATION_KIND,
            "trustLevel": OBSERVATION_TRUST_LEVEL,
            "capturedAt": _timestamp(captured_at),
            "ttlSeconds": float(self.ttl_seconds),
            "expiresAt": _timestamp(captured_at + timedelta(seconds=self.ttl_seconds)),
            "expiryClock": "monotonic-elapsed",
        }
        while len(self._entries) >= self.capacity:
            self._entries.popitem(last=False)
        self._entries[observation_id] = _LedgerEntry(
            record=stored,
            monotonic_deadline=moment + self.ttl_seconds,
            dhash=dhash,
        )
        self._accepted_total += 1
        return dict(stored)

    def fresh(self) -> list[dict[str, Any]]:
        moment = self.clock()
        self._prune(moment)
        results = []
        for entry in self._entries.values():
            record = dict(entry.record)
            record["remainingSeconds"] = round(max(0.0, entry.monotonic_deadline - moment), 3)
            results.append(record)
        results.reverse()
        return results

    def latest_hashes(self, limit: int = 8) -> list[tuple[str, int]]:
        self._prune(self.clock())
        pairs = [
            (observation_id, entry.dhash)
            for observation_id, entry in self._entries.items()
        ]
        return pairs[-limit:]

    def get_fresh(self, observation_id: str) -> dict[str, Any]:
        moment = self.clock()
        self._prune(moment)
        entry = self._entries.get(observation_id)
        if entry is None:
            raise PerceptionError(
                "E_PERCEPTION_EXPIRED",
                "observation is expired or unknown and cannot be used as current context",
            )
        record = dict(entry.record)
        record["remainingSeconds"] = round(max(0.0, entry.monotonic_deadline - moment), 3)
        return record

    def clear(self) -> int:
        removed = len(self._entries)
        self._entries.clear()
        return removed

    def counts(self) -> dict[str, int]:
        self._prune(self.clock())
        return {
            "fresh": len(self._entries),
            "expiredTotal": self._expired_total,
            "acceptedTotal": self._accepted_total,
        }

    def _prune(self, moment: float) -> None:
        expired = [
            observation_id
            for observation_id, entry in self._entries.items()
            if entry.monotonic_deadline <= moment
        ]
        for observation_id in expired:
            del self._entries[observation_id]
        self._expired_total += len(expired)


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
