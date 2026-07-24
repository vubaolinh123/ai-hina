from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    candidate_id: str
    owner_id: str
    session_id: str | None
    source: str
    trust_level: str
    kind: str
    topic: str
    content: str
    content_hash: str
    confidence: float
    sensitivity: str
    status: str
    consent_required: bool
    created_at: str
    expires_at: str | None
    version: int
    decision_at: str | None = None
    decision_actor: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "candidateId": self.candidate_id,
            "ownerId": self.owner_id,
            "sessionId": self.session_id,
            "source": self.source,
            "trustLevel": self.trust_level,
            "kind": self.kind,
            "topic": self.topic,
            "content": self.content,
            "contentHash": self.content_hash,
            "confidence": self.confidence,
            "sensitivity": self.sensitivity,
            "status": self.status,
            "consentRequired": self.consent_required,
            "createdAt": self.created_at,
            "expiresAt": self.expires_at,
            "version": self.version,
            "decisionAt": self.decision_at,
            "decisionActor": self.decision_actor,
        }


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    candidate_id: str
    owner_id: str
    session_id: str | None
    source: str
    trust_level: str
    kind: str
    topic: str
    content: str
    content_hash: str
    confidence: float
    sensitivity: str
    pinned: bool
    status: str
    created_at: str
    updated_at: str
    expires_at: str | None
    version: int

    def as_json(self) -> dict[str, Any]:
        return {
            "memoryId": self.memory_id,
            "candidateId": self.candidate_id,
            "ownerId": self.owner_id,
            "sessionId": self.session_id,
            "source": self.source,
            "trustLevel": self.trust_level,
            "kind": self.kind,
            "topic": self.topic,
            "content": self.content,
            "contentHash": self.content_hash,
            "confidence": self.confidence,
            "sensitivity": self.sensitivity,
            "pinned": self.pinned,
            "status": self.status,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "expiresAt": self.expires_at,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class IndexOperation:
    outbox_id: int
    memory_id: str
    operation: str
    generation: int
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class IndexHit:
    memory_id: str
    score: float


@dataclass(frozen=True, slots=True)
class DeletionReceipt:
    receipt_id: str
    memory_id: str
    owner_id: str
    deleted_at: str
    stores: tuple[str, ...]
    content_hash: str
    adapter_lineage_deleted: bool

    def as_json(self) -> dict[str, Any]:
        return {
            "receiptId": self.receipt_id,
            "memoryId": self.memory_id,
            "ownerId": self.owner_id,
            "deletedAt": self.deleted_at,
            "stores": list(self.stores),
            "contentHash": self.content_hash,
            "adapterLineageDeleted": self.adapter_lineage_deleted,
            "statement": (
                "Active memory data was removed from declared stores. "
                "This receipt does not claim deletion from trained model weights."
            ),
        }
