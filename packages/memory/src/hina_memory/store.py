from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import MemoryError
from .model import DeletionReceipt, IndexOperation, MemoryCandidate, MemoryRecord


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class MemoryStore:
    """Authoritative, auditable SQLite store for consent-managed memory."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    session_id TEXT,
                    source TEXT NOT NULL,
                    trust_level TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    sensitivity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    consent_required INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    version INTEGER NOT NULL,
                    decision_at TEXT,
                    decision_actor TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_memory_candidates_status
                    ON memory_candidates(owner_id, status, created_at);

                CREATE TABLE IF NOT EXISTS memory_records (
                    memory_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE
                        REFERENCES memory_candidates(candidate_id),
                    owner_id TEXT NOT NULL,
                    session_id TEXT,
                    source TEXT NOT NULL,
                    trust_level TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    sensitivity TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    version INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_records_active
                    ON memory_records(owner_id, status, kind, topic);

                CREATE TABLE IF NOT EXISTS memory_outbox (
                    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error_code TEXT,
                    created_at TEXT NOT NULL,
                    indexed_at TEXT,
                    UNIQUE(memory_id, operation, generation)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_outbox_pending
                    ON memory_outbox(state, outbox_id);

                CREATE TABLE IF NOT EXISTS memory_audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    candidate_id TEXT,
                    memory_id TEXT,
                    content_hash TEXT,
                    occurred_at TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS deletion_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL UNIQUE,
                    owner_id TEXT NOT NULL,
                    deleted_at TEXT NOT NULL,
                    stores_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    adapter_lineage_deleted INTEGER NOT NULL
                );
                """
            )

    def add_candidate(self, candidate: MemoryCandidate) -> MemoryCandidate:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO memory_candidates (
                    candidate_id, owner_id, session_id, source, trust_level,
                    kind, topic, content, content_hash, confidence, sensitivity,
                    status, consent_required, created_at, expires_at, version,
                    decision_at, decision_actor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.candidate_id,
                    candidate.owner_id,
                    candidate.session_id,
                    candidate.source,
                    candidate.trust_level,
                    candidate.kind,
                    candidate.topic,
                    candidate.content,
                    candidate.content_hash,
                    candidate.confidence,
                    candidate.sensitivity,
                    candidate.status,
                    int(candidate.consent_required),
                    candidate.created_at,
                    candidate.expires_at,
                    candidate.version,
                    candidate.decision_at,
                    candidate.decision_actor,
                ),
            )
            self._audit(
                "candidate.created",
                "system",
                candidate.owner_id,
                candidate_id=candidate.candidate_id,
                content_hash=candidate.content_hash,
                details={"source": candidate.source, "status": candidate.status},
            )
        return candidate

    def get_candidate(self, candidate_id: str, owner_id: str) -> MemoryCandidate:
        row = self._connection.execute(
            "SELECT * FROM memory_candidates WHERE candidate_id = ? AND owner_id = ?",
            (candidate_id, owner_id),
        ).fetchone()
        if row is None:
            raise MemoryError("E_MEMORY_NOT_FOUND", "memory candidate was not found")
        return _candidate_from_row(row)

    def list_candidates(
        self,
        owner_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> tuple[MemoryCandidate, ...]:
        if status is None:
            rows = self._connection.execute(
                """
                SELECT * FROM memory_candidates
                WHERE owner_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (owner_id, limit),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT * FROM memory_candidates
                WHERE owner_id = ? AND status = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (owner_id, status, limit),
            ).fetchall()
        return tuple(_candidate_from_row(row) for row in rows)

    def decide_candidate(
        self,
        candidate_id: str,
        owner_id: str,
        *,
        action: str,
        actor: str,
        expected_version: int,
    ) -> MemoryRecord | None:
        if action not in {"promote", "reject"}:
            raise MemoryError("E_MEMORY_DECISION", "memory decision is invalid")
        now = utc_now()
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT * FROM memory_candidates WHERE candidate_id = ? AND owner_id = ?",
                (candidate_id, owner_id),
            ).fetchone()
            if row is None:
                raise MemoryError("E_MEMORY_NOT_FOUND", "memory candidate was not found")
            candidate = _candidate_from_row(row)
            if candidate.version != expected_version:
                raise MemoryError("E_MEMORY_VERSION_CONFLICT", "memory candidate version changed")
            if candidate.status not in {"pending", "quarantined"}:
                raise MemoryError("E_MEMORY_STATE", "memory candidate is no longer pending")
            if candidate.status == "quarantined" and action == "promote":
                raise MemoryError("E_MEMORY_QUARANTINED", "quarantined memory cannot be promoted")
            next_status = "promoted" if action == "promote" else "rejected"
            self._connection.execute(
                """
                UPDATE memory_candidates
                SET status = ?, content = CASE WHEN ? = 'rejected' THEN '<rejected>' ELSE content END,
                    version = version + 1, decision_at = ?, decision_actor = ?
                WHERE candidate_id = ?
                """,
                (next_status, next_status, now, actor, candidate_id),
            )
            if action == "reject":
                self._audit(
                    "candidate.rejected",
                    actor,
                    owner_id,
                    candidate_id=candidate_id,
                    content_hash=candidate.content_hash,
                )
                return None
            conflicting = self._connection.execute(
                """
                SELECT memory_id, content_hash FROM memory_records
                WHERE owner_id = ? AND kind = ? AND topic = ? AND status = 'active'
                LIMIT 1
                """,
                (owner_id, candidate.kind, candidate.topic),
            ).fetchone()
            if conflicting is not None:
                raise MemoryError(
                    "E_MEMORY_CONTRADICTION",
                    "an active memory already owns this kind and topic; correct or delete it first",
                )
            memory_id = str(uuid.uuid4())
            self._connection.execute(
                """
                INSERT INTO memory_records (
                    memory_id, candidate_id, owner_id, session_id, source,
                    trust_level, kind, topic, content, content_hash, confidence,
                    sensitivity, pinned, status, created_at, updated_at,
                    expires_at, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'active', ?, ?, ?, 1)
                """,
                (
                    memory_id,
                    candidate_id,
                    owner_id,
                    candidate.session_id,
                    candidate.source,
                    candidate.trust_level,
                    candidate.kind,
                    candidate.topic,
                    candidate.content,
                    candidate.content_hash,
                    candidate.confidence,
                    candidate.sensitivity,
                    now,
                    now,
                    candidate.expires_at,
                ),
            )
            self._enqueue(memory_id, "upsert", 1, {"reason": "promoted"}, now)
            self._audit(
                "memory.promoted",
                actor,
                owner_id,
                candidate_id=candidate_id,
                memory_id=memory_id,
                content_hash=candidate.content_hash,
            )
            return self.get_record(memory_id, owner_id, include_inactive=True)

    def get_record(
        self,
        memory_id: str,
        owner_id: str,
        *,
        include_inactive: bool = False,
    ) -> MemoryRecord:
        query = "SELECT * FROM memory_records WHERE memory_id = ? AND owner_id = ?"
        parameters: tuple[Any, ...] = (memory_id, owner_id)
        if not include_inactive:
            query += " AND status = 'active'"
        row = self._connection.execute(query, parameters).fetchone()
        if row is None:
            raise MemoryError("E_MEMORY_NOT_FOUND", "memory record was not found")
        return _record_from_row(row)

    def get_records(
        self,
        memory_ids: list[str] | tuple[str, ...],
        owner_id: str,
    ) -> dict[str, MemoryRecord]:
        if not memory_ids:
            return {}
        placeholders = ",".join("?" for _ in memory_ids)
        rows = self._connection.execute(
            f"""
            SELECT * FROM memory_records
            WHERE owner_id = ? AND status = 'active'
              AND memory_id IN ({placeholders})
            """,
            (owner_id, *memory_ids),
        ).fetchall()
        return {str(row["memory_id"]): _record_from_row(row) for row in rows}

    def list_records(
        self,
        owner_id: str,
        *,
        include_inactive: bool = False,
        limit: int = 100,
    ) -> tuple[MemoryRecord, ...]:
        status = "" if include_inactive else "AND status = 'active'"
        rows = self._connection.execute(
            f"""
            SELECT * FROM memory_records
            WHERE owner_id = ? {status}
            ORDER BY pinned DESC, updated_at DESC LIMIT ?
            """,
            (owner_id, limit),
        ).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def update_record(
        self,
        memory_id: str,
        owner_id: str,
        *,
        content: str | None = None,
        content_hash: str | None = None,
        pinned: bool | None = None,
        expected_version: int,
        actor: str,
    ) -> MemoryRecord:
        with self._lock, self._connection:
            current = self.get_record(memory_id, owner_id)
            if current.version != expected_version:
                raise MemoryError("E_MEMORY_VERSION_CONFLICT", "memory record version changed")
            next_content = current.content if content is None else content
            next_hash = current.content_hash if content_hash is None else content_hash
            next_pinned = current.pinned if pinned is None else pinned
            next_version = current.version + 1
            now = utc_now()
            self._connection.execute(
                """
                UPDATE memory_records
                SET content = ?, content_hash = ?, pinned = ?, version = ?, updated_at = ?
                WHERE memory_id = ? AND owner_id = ? AND status = 'active'
                """,
                (
                    next_content,
                    next_hash,
                    int(next_pinned),
                    next_version,
                    now,
                    memory_id,
                    owner_id,
                ),
            )
            self._enqueue(memory_id, "upsert", next_version, {"reason": "updated"}, now)
            self._audit(
                "memory.corrected" if content is not None else "memory.pin_changed",
                actor,
                owner_id,
                memory_id=memory_id,
                content_hash=next_hash,
                details={"pinned": next_pinned},
            )
            return self.get_record(memory_id, owner_id)

    def prepare_delete(
        self,
        memory_id: str,
        owner_id: str,
        *,
        expected_version: int,
        actor: str,
    ) -> MemoryRecord:
        with self._lock, self._connection:
            current = self.get_record(memory_id, owner_id)
            if current.version != expected_version:
                raise MemoryError("E_MEMORY_VERSION_CONFLICT", "memory record version changed")
            now = utc_now()
            next_version = current.version + 1
            self._connection.execute(
                """
                UPDATE memory_records
                SET content = '<deleted>', status = 'deleted', pinned = 0,
                    version = ?, updated_at = ?
                WHERE memory_id = ? AND owner_id = ?
                """,
                (next_version, now, memory_id, owner_id),
            )
            self._connection.execute(
                """
                UPDATE memory_candidates
                SET content = '<deleted>', status = 'deleted', version = version + 1
                WHERE candidate_id = ?
                """,
                (current.candidate_id,),
            )
            self._enqueue(memory_id, "delete", next_version, {"reason": "owner_delete"}, now)
            self._audit(
                "memory.delete_requested",
                actor,
                owner_id,
                candidate_id=current.candidate_id,
                memory_id=memory_id,
                content_hash=current.content_hash,
            )
            return self.get_record(memory_id, owner_id, include_inactive=True)

    def expire_due(self, owner_id: str, *, now: str | None = None) -> tuple[str, ...]:
        threshold = now or utc_now()
        rows = self._connection.execute(
            """
            SELECT memory_id, version FROM memory_records
            WHERE owner_id = ? AND status = 'active' AND pinned = 0
              AND expires_at IS NOT NULL AND expires_at <= ?
            """,
            (owner_id, threshold),
        ).fetchall()
        expired: list[str] = []
        for row in rows:
            self.prepare_delete(
                str(row["memory_id"]),
                owner_id,
                expected_version=int(row["version"]),
                actor="system.expiry",
            )
            expired.append(str(row["memory_id"]))
        return tuple(expired)

    def pending_operations(self, limit: int = 100) -> tuple[IndexOperation, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM memory_outbox
            WHERE state IN ('pending', 'failed')
            ORDER BY outbox_id LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return tuple(
            IndexOperation(
                outbox_id=int(row["outbox_id"]),
                memory_id=str(row["memory_id"]),
                operation=str(row["operation"]),
                generation=int(row["generation"]),
                payload=json.loads(str(row["payload_json"])),
            )
            for row in rows
        )

    def mark_operation_indexed(self, outbox_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE memory_outbox
                SET state = 'indexed', attempts = attempts + 1,
                    last_error_code = NULL, indexed_at = ?
                WHERE outbox_id = ?
                """,
                (utc_now(), outbox_id),
            )

    def mark_operation_failed(self, outbox_id: int, error_code: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE memory_outbox
                SET state = 'failed', attempts = attempts + 1,
                    last_error_code = ?
                WHERE outbox_id = ?
                """,
                (error_code[:128], outbox_id),
            )

    def finalize_deletion(self, memory_id: str, owner_id: str) -> DeletionReceipt:
        existing = self._connection.execute(
            "SELECT * FROM deletion_receipts WHERE memory_id = ? AND owner_id = ?",
            (memory_id, owner_id),
        ).fetchone()
        if existing is not None:
            return _receipt_from_row(existing)
        record = self.get_record(memory_id, owner_id, include_inactive=True)
        if record.status != "deleted":
            raise MemoryError("E_MEMORY_STATE", "memory deletion was not requested")
        pending = self._connection.execute(
            """
            SELECT 1 FROM memory_outbox
            WHERE memory_id = ? AND operation = 'delete'
              AND generation = ? AND state != 'indexed'
            """,
            (memory_id, record.version),
        ).fetchone()
        if pending is not None:
            raise MemoryError(
                "E_MEMORY_DELETE_PENDING",
                "memory deletion is waiting for derived-index reconciliation",
                retryable=True,
            )
        receipt = DeletionReceipt(
            receipt_id=str(uuid.uuid4()),
            memory_id=memory_id,
            owner_id=owner_id,
            deleted_at=utc_now(),
            stores=("sqlite-authoritative", "qdrant-derived"),
            content_hash=record.content_hash,
            adapter_lineage_deleted=False,
        )
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO deletion_receipts (
                    receipt_id, memory_id, owner_id, deleted_at, stores_json,
                    content_hash, adapter_lineage_deleted
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.receipt_id,
                    receipt.memory_id,
                    receipt.owner_id,
                    receipt.deleted_at,
                    json.dumps(receipt.stores),
                    receipt.content_hash,
                    int(receipt.adapter_lineage_deleted),
                ),
            )
            self._audit(
                "memory.deleted",
                "system.reconciler",
                owner_id,
                memory_id=memory_id,
                content_hash=record.content_hash,
                details={"stores": list(receipt.stores)},
            )
        return receipt

    def active_ids(self, owner_id: str) -> set[str]:
        rows = self._connection.execute(
            "SELECT memory_id FROM memory_records WHERE owner_id = ? AND status = 'active'",
            (owner_id,),
        ).fetchall()
        return {str(row["memory_id"]) for row in rows}

    def audit_records(self, owner_id: str, limit: int = 100) -> tuple[dict[str, Any], ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM memory_audit WHERE owner_id = ?
            ORDER BY sequence DESC LIMIT ?
            """,
            (owner_id, limit),
        ).fetchall()
        return tuple(
            {
                "sequence": int(row["sequence"]),
                "eventId": str(row["event_id"]),
                "action": str(row["action"]),
                "actor": str(row["actor"]),
                "candidateId": row["candidate_id"],
                "memoryId": row["memory_id"],
                "contentHash": row["content_hash"],
                "occurredAt": str(row["occurred_at"]),
                "details": json.loads(str(row["details_json"])),
            }
            for row in rows
        )

    def counts(self, owner_id: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for table, key in (
            ("memory_candidates", "candidates"),
            ("memory_records", "records"),
        ):
            rows = self._connection.execute(
                f"SELECT status, COUNT(*) AS count FROM {table} WHERE owner_id = ? GROUP BY status",
                (owner_id,),
            ).fetchall()
            for row in rows:
                result[f"{key}.{row['status']}"] = int(row["count"])
        pending = self._connection.execute(
            "SELECT COUNT(*) FROM memory_outbox WHERE state != 'indexed'"
        ).fetchone()
        result["outbox.pending"] = int(pending[0])
        return result

    def close(self) -> None:
        self._connection.close()

    def _enqueue(
        self,
        memory_id: str,
        operation: str,
        generation: int,
        payload: dict[str, Any],
        now: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT OR IGNORE INTO memory_outbox (
                memory_id, operation, generation, payload_json, state, created_at
            ) VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (
                memory_id,
                operation,
                generation,
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                now,
            ),
        )

    def _audit(
        self,
        action: str,
        actor: str,
        owner_id: str,
        *,
        candidate_id: str | None = None,
        memory_id: str | None = None,
        content_hash: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO memory_audit (
                event_id, action, actor, owner_id, candidate_id, memory_id,
                content_hash, occurred_at, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                action,
                actor,
                owner_id,
                candidate_id,
                memory_id,
                content_hash,
                utc_now(),
                json.dumps(details or {}, separators=(",", ":"), sort_keys=True),
            ),
        )


def _candidate_from_row(row: sqlite3.Row) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=str(row["candidate_id"]),
        owner_id=str(row["owner_id"]),
        session_id=row["session_id"],
        source=str(row["source"]),
        trust_level=str(row["trust_level"]),
        kind=str(row["kind"]),
        topic=str(row["topic"]),
        content=str(row["content"]),
        content_hash=str(row["content_hash"]),
        confidence=float(row["confidence"]),
        sensitivity=str(row["sensitivity"]),
        status=str(row["status"]),
        consent_required=bool(row["consent_required"]),
        created_at=str(row["created_at"]),
        expires_at=row["expires_at"],
        version=int(row["version"]),
        decision_at=row["decision_at"],
        decision_actor=row["decision_actor"],
    )


def _record_from_row(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        memory_id=str(row["memory_id"]),
        candidate_id=str(row["candidate_id"]),
        owner_id=str(row["owner_id"]),
        session_id=row["session_id"],
        source=str(row["source"]),
        trust_level=str(row["trust_level"]),
        kind=str(row["kind"]),
        topic=str(row["topic"]),
        content=str(row["content"]),
        content_hash=str(row["content_hash"]),
        confidence=float(row["confidence"]),
        sensitivity=str(row["sensitivity"]),
        pinned=bool(row["pinned"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        expires_at=row["expires_at"],
        version=int(row["version"]),
    )


def _receipt_from_row(row: sqlite3.Row) -> DeletionReceipt:
    return DeletionReceipt(
        receipt_id=str(row["receipt_id"]),
        memory_id=str(row["memory_id"]),
        owner_id=str(row["owner_id"]),
        deleted_at=str(row["deleted_at"]),
        stores=tuple(json.loads(str(row["stores_json"]))),
        content_hash=str(row["content_hash"]),
        adapter_lineage_deleted=bool(row["adapter_lineage_deleted"]),
    )
