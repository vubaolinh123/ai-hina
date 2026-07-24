from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from hina_contracts import validate_envelope

from .primitives import PrimitiveError, RuntimeErrorCode


_STABLE_ERROR_CODE = re.compile(r"^E_[A-Z0-9_]{1,62}$")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat()


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise PrimitiveError(RuntimeErrorCode.DURABLE_INVALID_EVENT, "value is not canonical JSON") from exc


@dataclass(frozen=True, slots=True)
class DurableEvent:
    journal_id: int
    event_id: str
    stream_id: str
    sequence: int
    idempotency_key: str
    event_type: str
    canonical_json: str
    delivery_attempts: int = 0

    @property
    def envelope(self) -> dict[str, Any]:
        return json.loads(self.canonical_json)


@dataclass(frozen=True, slots=True)
class JournalAppendResult:
    event: DurableEvent
    deduplicated: bool


@dataclass(frozen=True, slots=True)
class AckResult:
    event_id: str
    already_acked: bool


@dataclass(frozen=True, slots=True)
class InboxReceiveResult:
    event_id: str
    inserted: bool


@dataclass(frozen=True, slots=True)
class DurableSnapshot:
    journal: int
    inbox: int
    outbox_pending: int
    outbox_in_flight: int
    outbox_acked: int


class DurableStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._connection = sqlite3.connect(
            self.path,
            timeout=5,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._initialize()

    def __enter__(self) -> DurableStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def append_outbox(self, envelope: Mapping[str, Any]) -> JournalAppendResult:
        data, canonical = self._validated_durable_envelope(envelope)
        inserted_at = _timestamp()
        with self._transaction(immediate=True):
            existing = self._connection.execute(
                "SELECT * FROM journal WHERE event_id = ?",
                (data["eventId"],),
            ).fetchone()
            if existing is not None:
                if existing["canonical_json"] != canonical:
                    raise PrimitiveError(
                        RuntimeErrorCode.JOURNAL_CONFLICT,
                        "eventId was reused with different content",
                    )
                return JournalAppendResult(self._row_to_event(existing), True)
            try:
                cursor = self._connection.execute(
                    """
                    INSERT INTO journal(
                        event_id, stream_id, sequence, idempotency_key,
                        event_type, canonical_json, inserted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["eventId"],
                        data["streamId"],
                        data["sequence"],
                        data["idempotencyKey"],
                        data["type"],
                        canonical,
                        inserted_at,
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO outbox(event_id, state, attempts, next_attempt_at)
                    VALUES (?, 'pending', 0, ?)
                    """,
                    (data["eventId"], inserted_at),
                )
            except sqlite3.IntegrityError as exc:
                raise PrimitiveError(
                    RuntimeErrorCode.JOURNAL_CONFLICT,
                    "stream sequence or idempotency identity conflicts with durable history",
                ) from exc
            return JournalAppendResult(
                DurableEvent(
                    journal_id=int(cursor.lastrowid),
                    event_id=data["eventId"],
                    stream_id=data["streamId"],
                    sequence=data["sequence"],
                    idempotency_key=data["idempotencyKey"],
                    event_type=data["type"],
                    canonical_json=canonical,
                ),
                False,
            )

    def claim_outbox(self, *, limit: int = 32, lease_seconds: float = 30.0) -> list[DurableEvent]:
        if limit < 1 or limit > 1024:
            raise ValueError("claim limit must be between 1 and 1024")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = _utc_now()
        now_text = _timestamp(now)
        lease_until = _timestamp(now + timedelta(seconds=lease_seconds))
        with self._transaction(immediate=True):
            rows = self._connection.execute(
                """
                SELECT j.*, o.attempts
                FROM outbox AS o
                JOIN journal AS j ON j.event_id = o.event_id
                WHERE
                    (o.state = 'pending' AND o.next_attempt_at <= ?)
                    OR
                    (o.state = 'in_flight' AND o.lease_until <= ?)
                ORDER BY j.journal_id
                LIMIT ?
                """,
                (now_text, now_text, limit),
            ).fetchall()
            claimed: list[DurableEvent] = []
            for row in rows:
                attempts = int(row["attempts"]) + 1
                self._connection.execute(
                    """
                    UPDATE outbox
                    SET state = 'in_flight', attempts = ?, lease_until = ?, last_error_code = NULL
                    WHERE event_id = ?
                    """,
                    (attempts, lease_until, row["event_id"]),
                )
                claimed.append(self._row_to_event(row, delivery_attempts=attempts))
            return claimed

    def ack_outbox(self, event_id: str) -> AckResult:
        with self._transaction(immediate=True):
            row = self._connection.execute(
                "SELECT state FROM outbox WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise PrimitiveError(RuntimeErrorCode.OUTBOX_NOT_FOUND, "outbox event was not found")
            if row["state"] == "acked":
                return AckResult(event_id, True)
            if row["state"] != "in_flight":
                raise PrimitiveError(
                    RuntimeErrorCode.ACK_INVALID_STATE,
                    f"cannot ACK outbox event in state {row['state']}",
                )
            self._connection.execute(
                """
                UPDATE outbox
                SET state = 'acked', acked_at = ?, lease_until = NULL, last_error_code = NULL
                WHERE event_id = ?
                """,
                (_timestamp(), event_id),
            )
            return AckResult(event_id, False)

    def nack_outbox(self, event_id: str, *, error_code: str, retry_after_seconds: float = 0) -> None:
        if _STABLE_ERROR_CODE.fullmatch(error_code) is None:
            raise ValueError("NACK requires a stable E_* error code")
        if retry_after_seconds < 0:
            raise ValueError("retry delay cannot be negative")
        with self._transaction(immediate=True):
            row = self._connection.execute(
                "SELECT state FROM outbox WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise PrimitiveError(RuntimeErrorCode.OUTBOX_NOT_FOUND, "outbox event was not found")
            if row["state"] != "in_flight":
                raise PrimitiveError(
                    RuntimeErrorCode.ACK_INVALID_STATE,
                    f"cannot NACK outbox event in state {row['state']}",
                )
            next_attempt = _utc_now() + timedelta(seconds=retry_after_seconds)
            self._connection.execute(
                """
                UPDATE outbox
                SET state = 'pending', next_attempt_at = ?, lease_until = NULL, last_error_code = ?
                WHERE event_id = ?
                """,
                (_timestamp(next_attempt), error_code, event_id),
            )

    def receive_inbox(self, consumer_id: str, envelope: Mapping[str, Any]) -> InboxReceiveResult:
        self._validate_consumer(consumer_id)
        data, canonical = self._validated_durable_envelope(envelope)
        with self._transaction(immediate=True):
            existing = self._connection.execute(
                "SELECT canonical_json FROM inbox WHERE consumer_id = ? AND event_id = ?",
                (consumer_id, data["eventId"]),
            ).fetchone()
            if existing is not None:
                if existing["canonical_json"] != canonical:
                    raise PrimitiveError(
                        RuntimeErrorCode.JOURNAL_CONFLICT,
                        "inbox eventId was reused with different content",
                    )
                return InboxReceiveResult(data["eventId"], False)
            try:
                self._connection.execute(
                    """
                    INSERT INTO inbox(
                        consumer_id, event_id, stream_id, sequence, canonical_json, received_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        consumer_id,
                        data["eventId"],
                        data["streamId"],
                        data["sequence"],
                        canonical,
                        _timestamp(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise PrimitiveError(
                    RuntimeErrorCode.JOURNAL_CONFLICT,
                    "consumer stream sequence conflicts with inbox history",
                ) from exc
            return InboxReceiveResult(data["eventId"], True)

    def complete_inbox(self, consumer_id: str, event_id: str, result: Any) -> int:
        self._validate_consumer(consumer_id)
        result_json = _canonical_json(result)
        with self._transaction(immediate=True):
            row = self._connection.execute(
                """
                SELECT stream_id, sequence, processed_at, result_json
                FROM inbox WHERE consumer_id = ? AND event_id = ?
                """,
                (consumer_id, event_id),
            ).fetchone()
            if row is None:
                raise PrimitiveError(RuntimeErrorCode.INBOX_NOT_FOUND, "inbox event was not found")
            if row["processed_at"] is not None and row["result_json"] != result_json:
                raise PrimitiveError(
                    RuntimeErrorCode.JOURNAL_CONFLICT,
                    "processed inbox result cannot be replaced",
                )
            if row["processed_at"] is None:
                self._connection.execute(
                    """
                    UPDATE inbox SET processed_at = ?, result_json = ?
                    WHERE consumer_id = ? AND event_id = ?
                    """,
                    (_timestamp(), result_json, consumer_id, event_id),
                )
            return self._advance_checkpoint_locked(consumer_id, row["stream_id"])

    def get_checkpoint(self, consumer_id: str, stream_id: str) -> int:
        self._validate_consumer(consumer_id)
        with self._lock:
            self._ensure_open()
            row = self._connection.execute(
                "SELECT last_sequence FROM checkpoints WHERE consumer_id = ? AND stream_id = ?",
                (consumer_id, stream_id),
            ).fetchone()
            return int(row["last_sequence"]) if row is not None else -1

    def resume_inbox(self, consumer_id: str, stream_id: str, *, limit: int = 1024) -> list[DurableEvent]:
        self._validate_consumer(consumer_id)
        if limit < 1 or limit > 10_000:
            raise ValueError("resume limit must be between 1 and 10000")
        checkpoint = self.get_checkpoint(consumer_id, stream_id)
        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                """
                SELECT
                    0 AS journal_id, event_id, stream_id, sequence,
                    '' AS idempotency_key, '' AS event_type, canonical_json
                FROM inbox
                WHERE consumer_id = ? AND stream_id = ? AND sequence > ?
                ORDER BY sequence
                LIMIT ?
                """,
                (consumer_id, stream_id, checkpoint, limit),
            ).fetchall()
            return [self._row_to_event(row) for row in rows]

    def replay_journal(self, stream_id: str, *, after_sequence: int = -1, limit: int = 1024) -> list[DurableEvent]:
        if after_sequence < -1:
            raise ValueError("after_sequence cannot be less than -1")
        if limit < 1 or limit > 10_000:
            raise ValueError("replay limit must be between 1 and 10000")
        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                """
                SELECT * FROM journal
                WHERE stream_id = ? AND sequence > ?
                ORDER BY sequence
                LIMIT ?
                """,
                (stream_id, after_sequence, limit),
            ).fetchall()
            return [self._row_to_event(row) for row in rows]

    def snapshot(self) -> DurableSnapshot:
        with self._lock:
            self._ensure_open()
            journal = int(self._connection.execute("SELECT COUNT(*) FROM journal").fetchone()[0])
            inbox = int(self._connection.execute("SELECT COUNT(*) FROM inbox").fetchone()[0])
            states = {
                row["state"]: int(row["count"])
                for row in self._connection.execute(
                    "SELECT state, COUNT(*) AS count FROM outbox GROUP BY state"
                ).fetchall()
            }
            return DurableSnapshot(
                journal=journal,
                inbox=inbox,
                outbox_pending=states.get("pending", 0),
                outbox_in_flight=states.get("in_flight", 0),
                outbox_acked=states.get("acked", 0),
            )

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS journal(
                journal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                stream_id TEXT NOT NULL,
                sequence INTEGER NOT NULL CHECK(sequence >= 0),
                idempotency_key TEXT NOT NULL,
                event_type TEXT NOT NULL,
                canonical_json TEXT NOT NULL,
                inserted_at TEXT NOT NULL,
                UNIQUE(stream_id, sequence)
            );

            CREATE TABLE IF NOT EXISTS outbox(
                event_id TEXT PRIMARY KEY REFERENCES journal(event_id) ON DELETE CASCADE,
                state TEXT NOT NULL CHECK(state IN ('pending', 'in_flight', 'acked')),
                attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                next_attempt_at TEXT NOT NULL,
                lease_until TEXT,
                acked_at TEXT,
                last_error_code TEXT
            );

            CREATE TABLE IF NOT EXISTS inbox(
                consumer_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                stream_id TEXT NOT NULL,
                sequence INTEGER NOT NULL CHECK(sequence >= 0),
                canonical_json TEXT NOT NULL,
                received_at TEXT NOT NULL,
                processed_at TEXT,
                result_json TEXT,
                PRIMARY KEY(consumer_id, event_id),
                UNIQUE(consumer_id, stream_id, sequence)
            );

            CREATE TABLE IF NOT EXISTS checkpoints(
                consumer_id TEXT NOT NULL,
                stream_id TEXT NOT NULL,
                last_sequence INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(consumer_id, stream_id)
            );

            CREATE INDEX IF NOT EXISTS idx_outbox_delivery
                ON outbox(state, next_attempt_at, lease_until);
            CREATE INDEX IF NOT EXISTS idx_inbox_resume
                ON inbox(consumer_id, stream_id, sequence);
            PRAGMA user_version = 1;
            """
        )

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[None]:
        with self._lock:
            self._ensure_open()
            try:
                self._connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield
            except PrimitiveError:
                self._connection.rollback()
                raise
            except sqlite3.Error as exc:
                self._connection.rollback()
                raise PrimitiveError(
                    RuntimeErrorCode.DURABLE_STORE,
                    f"durable store failed with {type(exc).__name__}",
                ) from exc
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def _advance_checkpoint_locked(self, consumer_id: str, stream_id: str) -> int:
        row = self._connection.execute(
            "SELECT last_sequence FROM checkpoints WHERE consumer_id = ? AND stream_id = ?",
            (consumer_id, stream_id),
        ).fetchone()
        checkpoint = int(row["last_sequence"]) if row is not None else -1
        expected = checkpoint + 1
        rows = self._connection.execute(
            """
            SELECT sequence, processed_at FROM inbox
            WHERE consumer_id = ? AND stream_id = ? AND sequence > ?
            ORDER BY sequence
            """,
            (consumer_id, stream_id, checkpoint),
        ).fetchall()
        for candidate in rows:
            sequence = int(candidate["sequence"])
            if sequence != expected or candidate["processed_at"] is None:
                break
            checkpoint = sequence
            expected += 1
        if checkpoint >= 0:
            self._connection.execute(
                """
                INSERT INTO checkpoints(consumer_id, stream_id, last_sequence, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(consumer_id, stream_id) DO UPDATE SET
                    last_sequence = excluded.last_sequence,
                    updated_at = excluded.updated_at
                WHERE excluded.last_sequence > checkpoints.last_sequence
                """,
                (consumer_id, stream_id, checkpoint, _timestamp()),
            )
        return checkpoint

    @staticmethod
    def _validated_durable_envelope(envelope: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
        result = validate_envelope(dict(envelope))
        if not result.ok or result.canonical_json is None:
            raise PrimitiveError(
                RuntimeErrorCode.DURABLE_INVALID_EVENT,
                f"{result.code}: {result.detail or 'event validation failed'}",
            )
        data = json.loads(result.canonical_json)
        if data.get("streamId") is None or data.get("sequence") is None or data.get("idempotencyKey") is None:
            raise PrimitiveError(
                RuntimeErrorCode.DURABLE_INVALID_EVENT,
                "durable event requires streamId, sequence and idempotencyKey",
            )
        return data, result.canonical_json

    @staticmethod
    def _validate_consumer(consumer_id: str) -> None:
        if not consumer_id or len(consumer_id) > 128 or any(ord(char) < 0x20 for char in consumer_id):
            raise ValueError("consumer_id is invalid")

    @staticmethod
    def _row_to_event(row: sqlite3.Row, *, delivery_attempts: int = 0) -> DurableEvent:
        return DurableEvent(
            journal_id=int(row["journal_id"]),
            event_id=row["event_id"],
            stream_id=row["stream_id"],
            sequence=int(row["sequence"]),
            idempotency_key=row["idempotency_key"],
            event_type=row["event_type"],
            canonical_json=row["canonical_json"],
            delivery_attempts=delivery_attempts,
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise PrimitiveError(RuntimeErrorCode.DURABLE_STORE, "durable store is closed")
