from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .model import SafetyPolicyError


_ZERO_HASH = "0" * 64
_HASH = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class AuditTrail:
    def __init__(
        self,
        path: Path,
        *,
        build_commit: str = "development",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = path
        self.build_commit = build_commit[:64]
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._sequence = 0
        self._last_hash = _ZERO_HASH
        self._load_and_verify()

    @property
    def sequence(self) -> int:
        with self._lock:
            return self._sequence

    @property
    def last_hash(self) -> str:
        with self._lock:
            return self._last_hash

    def status(self) -> dict[str, Any]:
        return self.verify()

    def verify(self) -> dict[str, Any]:
        with self._lock:
            sequence, last_hash = self._scan()
            if sequence != self._sequence or last_hash != self._last_hash:
                raise SafetyPolicyError("E_SAFETY_AUDIT_INVALID", "audit trail changed unexpectedly")
            return {
                "verified": True,
                "records": sequence,
                "lastHash": last_hash,
            }

    def append(
        self,
        *,
        event_type: str,
        correlation_id: str,
        actor_hash: str,
        outcome: str,
        reason_code: str,
        state_revision: int,
        capability: str | None = None,
        session_id: str | None = None,
        target: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        for value in (event_type, outcome, reason_code):
            if _TOKEN.fullmatch(value) is None:
                raise SafetyPolicyError("E_SAFETY_AUDIT_INVALID", "audit token is invalid")
        if _HASH.fullmatch(actor_hash) is None or state_revision < 0:
            raise SafetyPolicyError("E_SAFETY_AUDIT_INVALID", "audit identity is invalid")
        with self._lock:
            self.verify()
            record: dict[str, Any] = {
                "schemaVersion": "1.0",
                "timestamp": self._now().astimezone(UTC).isoformat(),
                "sequence": self._sequence + 1,
                "eventType": event_type,
                "correlationId": correlation_id,
                "actorHash": actor_hash,
                "sessionId": session_id,
                "capability": capability,
                "outcome": outcome,
                "reasonCode": reason_code,
                "stateRevision": state_revision,
                "target": target,
                "enabled": enabled,
                "previousHash": self._last_hash,
                "buildCommit": self.build_commit,
            }
            record["entryHash"] = _record_hash(record)
            encoded = _canonical(record)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(encoded + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise SafetyPolicyError("E_SAFETY_AUDIT_UNAVAILABLE", "audit append failed") from exc
            self._sequence = record["sequence"]
            self._last_hash = record["entryHash"]
            return record

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "audit limit must be between 1 and 100")
        with self._lock:
            self.verify()
            records: deque[dict[str, Any]] = deque(maxlen=limit)
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        if len(line) > 65_536:
                            raise SafetyPolicyError("E_SAFETY_AUDIT_INVALID", "audit record is oversized")
                        record = json.loads(line)
                        if not isinstance(record, dict):
                            raise SafetyPolicyError("E_SAFETY_AUDIT_INVALID", "audit record is invalid")
                        records.append(record)
            except FileNotFoundError:
                return []
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise SafetyPolicyError("E_SAFETY_AUDIT_INVALID", "audit trail is unreadable") from exc
            return list(records)

    def _load_and_verify(self) -> None:
        sequence, previous = self._scan()
        self._sequence = sequence
        self._last_hash = previous

    def _scan(self) -> tuple[int, str]:
        previous = _ZERO_HASH
        sequence = 0
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if len(line) > 65_536:
                        raise SafetyPolicyError("E_SAFETY_AUDIT_INVALID", "audit record is oversized")
                    record = json.loads(line)
                    if (
                        not isinstance(record, dict)
                        or record.get("sequence") != sequence + 1
                        or record.get("previousHash") != previous
                        or record.get("entryHash") != _record_hash(record)
                    ):
                        raise SafetyPolicyError("E_SAFETY_AUDIT_INVALID", "audit hash chain is invalid")
                    sequence = record["sequence"]
                    previous = record["entryHash"]
        except FileNotFoundError:
            return 0, _ZERO_HASH
        except SafetyPolicyError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise SafetyPolicyError("E_SAFETY_AUDIT_INVALID", "audit trail is unreadable") from exc
        return sequence, previous


def _record_hash(record: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in record.items() if key != "entryHash"}
    return hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest()


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
