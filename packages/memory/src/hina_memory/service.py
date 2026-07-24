from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Callable

from .config import MemoryConfig
from .errors import MemoryError
from .index import DerivedMemoryIndex
from .model import MemoryCandidate, MemoryRecord
from .store import MemoryStore, utc_now


_SOURCE = frozenset(
    {
        "owner.console",
        "local.service",
        "authenticated.user",
        "public.chat",
        "viewer.chat",
        "web.research",
        "game.text",
        "screen.ocr",
    }
)
_KIND = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_TOPIC = re.compile(r"^[\w](?:[\w ._-]{0,126}[\w])?$", re.UNICODE)
_SENSITIVITY = frozenset({"public", "personal", "sensitive"})


class MemoryService:
    def __init__(
        self,
        config: MemoryConfig,
        store: MemoryStore,
        index: DerivedMemoryIndex,
        sanitizer: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self.config = config
        self.store = store
        self.index = index
        self.sanitize_input = sanitizer

    async def start(self) -> dict[str, Any]:
        await self.reconcile()
        return await self.status()

    async def status(self) -> dict[str, Any]:
        return {
            "available": True,
            **self.config.public_status(),
            "counts": self.store.counts(self.config.owner_id),
        }

    async def propose(self, raw: dict[str, Any]) -> dict[str, Any]:
        expected = {
            "source",
            "sessionId",
            "kind",
            "topic",
            "content",
            "confidence",
            "sensitivity",
            "expiresAt",
            "correlationId",
        }
        if not isinstance(raw, dict) or set(raw) != expected:
            raise MemoryError("E_MEMORY_REQUEST", "memory candidate fields are invalid")
        source = raw["source"]
        session_id = raw["sessionId"]
        kind = raw["kind"]
        topic = raw["topic"]
        content = raw["content"]
        sensitivity = raw["sensitivity"]
        correlation_id = _uuid(raw["correlationId"], "correlation ID")
        if source not in _SOURCE:
            raise MemoryError("E_MEMORY_REQUEST", "memory source is invalid")
        if session_id is not None:
            _uuid(session_id, "session ID")
        if not isinstance(kind, str) or _KIND.fullmatch(kind) is None:
            raise MemoryError("E_MEMORY_REQUEST", "memory kind is invalid")
        if not isinstance(topic, str):
            raise MemoryError("E_MEMORY_REQUEST", "memory topic is invalid")
        normalized_topic = " ".join(topic.casefold().split())
        if _TOPIC.fullmatch(normalized_topic) is None:
            raise MemoryError("E_MEMORY_REQUEST", "memory topic is invalid")
        if not isinstance(content, str) or not content.strip():
            raise MemoryError("E_MEMORY_TEXT", "memory content is empty")
        if len(content) > self.config.max_candidate_characters:
            raise MemoryError("E_MEMORY_TEXT", "memory content exceeds the configured limit")
        if sensitivity not in _SENSITIVITY:
            raise MemoryError("E_MEMORY_REQUEST", "memory sensitivity is invalid")
        confidence = raw["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise MemoryError("E_MEMORY_REQUEST", "memory confidence is invalid")
        confidence = float(confidence)
        if not 0.0 <= confidence <= 1.0:
            raise MemoryError("E_MEMORY_REQUEST", "memory confidence is invalid")
        expires_at = _optional_timestamp(raw["expiresAt"])

        sanitation = self.sanitize_input(
            {
                "source": source,
                "text": content,
                "correlationId": correlation_id,
                "sessionId": session_id or str(uuid.uuid4()),
            }
        )
        if hasattr(sanitation, "as_json"):
            sanitation = sanitation.as_json()
        evidence = sanitation.get("evidence")
        if not isinstance(evidence, dict):
            raise MemoryError("E_MEMORY_SAFETY", "memory sanitation evidence is unavailable")
        signals = evidence.get("signals")
        safe = evidence.get("safeForContext") is True and signals == []
        sanitized = sanitation.get("sanitizedText")
        if not isinstance(sanitized, str):
            raise MemoryError("E_MEMORY_SAFETY", "memory sanitized content is unavailable")
        candidate = MemoryCandidate(
            candidate_id=str(uuid.uuid4()),
            owner_id=self.config.owner_id,
            session_id=session_id,
            source=source,
            trust_level=str(evidence.get("trustLevel", "untrusted")),
            kind=kind,
            topic=normalized_topic,
            content=sanitized if safe else "<quarantined>",
            content_hash=str(evidence.get("contentHash") or _hash(content)),
            confidence=confidence,
            sensitivity=sensitivity,
            status="pending" if safe else "quarantined",
            consent_required=True,
            created_at=utc_now(),
            expires_at=expires_at,
            version=1,
        )
        self.store.add_candidate(candidate)
        return {"candidate": candidate.as_json(), "autoPromoted": False}

    async def decide(self, candidate_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict) or set(raw) != {"action", "expectedVersion"}:
            raise MemoryError("E_MEMORY_REQUEST", "memory decision fields are invalid")
        expected_version = _positive_int(raw["expectedVersion"], "expected version")
        if raw["action"] == "promote" and len(
            self.store.list_records(
                self.config.owner_id,
                limit=self.config.max_active_records + 1,
            )
        ) >= self.config.max_active_records:
            raise MemoryError("E_MEMORY_CAPACITY", "active memory capacity has been reached")
        record = self.store.decide_candidate(
            _uuid(candidate_id, "candidate ID"),
            self.config.owner_id,
            action=raw["action"],
            actor="owner.console",
            expected_version=expected_version,
        )
        if record is None:
            return {
                "candidate": self.store.get_candidate(
                    candidate_id,
                    self.config.owner_id,
                ).as_json(),
                "record": None,
            }
        await self.reconcile()
        return {
            "candidate": self.store.get_candidate(
                candidate_id,
                self.config.owner_id,
            ).as_json(),
            "record": record.as_json(),
        }

    async def candidates(self, *, status: str | None = None) -> dict[str, Any]:
        if status is not None and status not in {
            "pending",
            "quarantined",
            "promoted",
            "rejected",
            "deleted",
        }:
            raise MemoryError("E_MEMORY_REQUEST", "memory candidate status is invalid")
        records = self.store.list_candidates(self.config.owner_id, status=status)
        return {"candidates": [item.as_json() for item in records], "count": len(records)}

    async def records(self) -> dict[str, Any]:
        await self._expire_and_reconcile()
        records = self.store.list_records(self.config.owner_id)
        return {"records": [item.as_json() for item in records], "count": len(records)}

    async def search(self, query: str, *, limit: int | None = None) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise MemoryError("E_MEMORY_TEXT", "memory search query is empty")
        selected_limit = self.config.default_retrieval_limit if limit is None else limit
        if not 1 <= selected_limit <= self.config.max_retrieval_limit:
            raise MemoryError("E_MEMORY_REQUEST", "memory search limit is invalid")
        await self._expire_and_reconcile()
        hits = self.index.query(query, self.config.owner_id, selected_limit * 2)
        by_id = self.store.get_records(
            [hit.memory_id for hit in hits],
            self.config.owner_id,
        )
        memories = []
        for hit in hits:
            record = by_id.get(hit.memory_id)
            if record is None or _is_expired(record):
                continue
            memories.append({"score": hit.score, "record": record.as_json()})
            if len(memories) >= selected_limit:
                break
        return {"memories": memories, "count": len(memories), "query": query}

    async def correct(self, memory_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict) or set(raw) != {
            "content",
            "expectedVersion",
            "correlationId",
        }:
            raise MemoryError("E_MEMORY_REQUEST", "memory correction fields are invalid")
        content = raw["content"]
        if not isinstance(content, str) or not content.strip():
            raise MemoryError("E_MEMORY_TEXT", "memory correction is empty")
        if len(content) > self.config.max_candidate_characters:
            raise MemoryError("E_MEMORY_TEXT", "memory correction exceeds the configured limit")
        correlation_id = _uuid(raw["correlationId"], "correlation ID")
        sanitation = self.sanitize_input(
            {
                "source": "owner.console",
                "text": content,
                "correlationId": correlation_id,
                "sessionId": str(uuid.uuid4()),
            }
        )
        if hasattr(sanitation, "as_json"):
            sanitation = sanitation.as_json()
        correction_evidence = sanitation.get("evidence")
        if (
            sanitation.get("contextEligible") is not True
            or not isinstance(correction_evidence, dict)
            or correction_evidence.get("signals") != []
        ):
            raise MemoryError("E_MEMORY_QUARANTINED", "memory correction failed sanitation")
        sanitized = sanitation.get("sanitizedText")
        if not isinstance(sanitized, str) or not sanitized:
            raise MemoryError("E_MEMORY_SAFETY", "memory correction could not be sanitized")
        record = self.store.update_record(
            _uuid(memory_id, "memory ID"),
            self.config.owner_id,
            content=sanitized,
            content_hash=_hash(sanitized),
            expected_version=_positive_int(raw["expectedVersion"], "expected version"),
            actor="owner.console",
        )
        await self.reconcile()
        return {"record": record.as_json()}

    async def set_pinned(self, memory_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict) or set(raw) != {"pinned", "expectedVersion"}:
            raise MemoryError("E_MEMORY_REQUEST", "memory pin fields are invalid")
        if not isinstance(raw["pinned"], bool):
            raise MemoryError("E_MEMORY_REQUEST", "memory pinned value is invalid")
        record = self.store.update_record(
            _uuid(memory_id, "memory ID"),
            self.config.owner_id,
            pinned=raw["pinned"],
            expected_version=_positive_int(raw["expectedVersion"], "expected version"),
            actor="owner.console",
        )
        await self.reconcile()
        return {"record": record.as_json()}

    async def delete(self, memory_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict) or set(raw) != {"expectedVersion"}:
            raise MemoryError("E_MEMORY_REQUEST", "memory delete fields are invalid")
        validated_id = _uuid(memory_id, "memory ID")
        expected_version = _positive_int(raw["expectedVersion"], "expected version")
        current = self.store.get_record(
            validated_id,
            self.config.owner_id,
            include_inactive=True,
        )
        if current.status == "active":
            self.store.prepare_delete(
                validated_id,
                self.config.owner_id,
                expected_version=expected_version,
                actor="owner.console",
            )
        elif current.status != "deleted":
            raise MemoryError("E_MEMORY_STATE", "memory record cannot be deleted")
        await self.reconcile()
        receipt = self.store.finalize_deletion(memory_id, self.config.owner_id)
        return {"receipt": receipt.as_json()}

    async def export(self) -> dict[str, Any]:
        await self._expire_and_reconcile()
        records = self.store.list_records(self.config.owner_id, include_inactive=True)
        return {
            "schemaVersion": "hina.memory.export.v1",
            "ownerId": self.config.owner_id,
            "exportedAt": utc_now(),
            "records": [record.as_json() for record in records],
            "audit": list(self.store.audit_records(self.config.owner_id)),
        }

    async def context_for_turn(
        self,
        query: str,
        *,
        source: str,
        limit: int | None = None,
    ) -> tuple[MemoryRecord, ...]:
        if source != "owner.console":
            return ()
        result = await self.search(query, limit=limit)
        selected: list[MemoryRecord] = []
        used_bytes = 0
        for item in result["memories"]:
            record = self.store.get_record(
                item["record"]["memoryId"],
                self.config.owner_id,
            )
            record_bytes = len(record.content.encode("utf-8"))
            if used_bytes + record_bytes > self.config.context_byte_budget:
                break
            selected.append(record)
            used_bytes += record_bytes
        return tuple(selected)

    async def reconcile(self) -> dict[str, int]:
        indexed = 0
        failed = 0
        for operation in self.store.pending_operations():
            try:
                if operation.operation == "upsert":
                    record = self.store.get_record(
                        operation.memory_id,
                        self.config.owner_id,
                        include_inactive=True,
                    )
                    if record.status == "active" and record.version == operation.generation:
                        self.index.upsert(record)
                    elif record.status != "active":
                        self.index.delete(operation.memory_id)
                elif operation.operation == "delete":
                    self.index.delete(operation.memory_id)
                else:
                    raise MemoryError("E_MEMORY_INDEX_WRITE", "memory outbox operation is invalid")
                self.store.mark_operation_indexed(operation.outbox_id)
                indexed += 1
            except MemoryError as exc:
                self.store.mark_operation_failed(operation.outbox_id, exc.code)
                failed += 1
        active = self.store.active_ids(self.config.owner_id)
        try:
            for orphan in self.index.list_ids() - active:
                self.index.delete(orphan)
        except MemoryError:
            failed += 1
        return {"indexed": indexed, "failed": failed}

    async def rebuild(self) -> dict[str, Any]:
        self.index.recreate()
        records = self.store.list_records(
            self.config.owner_id,
            limit=self.config.max_active_records,
        )
        for record in records:
            self.index.upsert(record)
        return {
            "status": "rebuilt",
            "recordCount": len(records),
            "embedding": self.config.public_status()["embedding"],
        }

    async def close(self) -> None:
        self.index.close()
        self.store.close()

    async def _expire_and_reconcile(self) -> None:
        self.store.expire_due(self.config.owner_id)
        await self.reconcile()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MemoryError("E_MEMORY_REQUEST", f"memory {label} is invalid")
    return value


def _uuid(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise MemoryError("E_MEMORY_REQUEST", f"memory {label} is invalid")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise MemoryError("E_MEMORY_REQUEST", f"memory {label} is invalid") from exc


def _optional_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MemoryError("E_MEMORY_REQUEST", "memory expiry is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MemoryError("E_MEMORY_REQUEST", "memory expiry is invalid") from exc
    if parsed.tzinfo is None:
        raise MemoryError("E_MEMORY_REQUEST", "memory expiry must include a timezone")
    normalized = parsed.astimezone(UTC)
    if normalized <= datetime.now(UTC):
        raise MemoryError("E_MEMORY_REQUEST", "memory expiry must be in the future")
    return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_expired(record: MemoryRecord) -> bool:
    if record.pinned or record.expires_at is None:
        return False
    return datetime.fromisoformat(record.expires_at.replace("Z", "+00:00")) <= datetime.now(UTC)
