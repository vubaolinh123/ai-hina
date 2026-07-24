from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .embedder import LexicalHashEmbedder
from .errors import MemoryError
from .model import IndexHit, MemoryRecord


class DerivedMemoryIndex(Protocol):
    def upsert(self, record: MemoryRecord) -> None: ...

    def delete(self, memory_id: str) -> None: ...

    def query(self, text: str, owner_id: str, limit: int) -> tuple[IndexHit, ...]: ...

    def list_ids(self) -> set[str]: ...

    def recreate(self) -> None: ...

    def close(self) -> None: ...


class QdrantLocalMemoryIndex:
    def __init__(
        self,
        path: Path,
        collection_name: str,
        embedder: LexicalHashEmbedder,
    ) -> None:
        try:
            from qdrant_client import QdrantClient

            path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(path))
        except Exception as exc:
            raise MemoryError(
                "E_MEMORY_INDEX_UNAVAILABLE",
                "Qdrant local memory index could not be opened",
                retryable=True,
            ) from exc
        self.path = path
        self.collection_name = collection_name
        self.embedder = embedder
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        from qdrant_client import models

        try:
            if not self.client.collection_exists(self.collection_name):
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.embedder.dimensions,
                        distance=models.Distance.COSINE,
                    ),
                )
        except Exception as exc:
            raise MemoryError(
                "E_MEMORY_INDEX_UNAVAILABLE",
                "Qdrant memory collection could not be initialized",
                retryable=True,
            ) from exc

    def upsert(self, record: MemoryRecord) -> None:
        from qdrant_client import models

        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=record.memory_id,
                        vector=self.embedder.embed(
                            f"{record.kind} {record.topic} {record.content}"
                        ),
                        payload={
                            "memoryId": record.memory_id,
                            "ownerId": record.owner_id,
                            "kind": record.kind,
                            "topic": record.topic,
                            "source": record.source,
                            "trustLevel": record.trust_level,
                            "sensitivity": record.sensitivity,
                            "generation": record.version,
                        },
                    )
                ],
                wait=True,
            )
        except MemoryError:
            raise
        except Exception as exc:
            raise MemoryError(
                "E_MEMORY_INDEX_WRITE",
                "derived memory index upsert failed",
                retryable=True,
            ) from exc

    def delete(self, memory_id: str) -> None:
        from qdrant_client import models

        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=[memory_id]),
                wait=True,
            )
        except Exception as exc:
            raise MemoryError(
                "E_MEMORY_INDEX_WRITE",
                "derived memory index deletion failed",
                retryable=True,
            ) from exc

    def query(self, text: str, owner_id: str, limit: int) -> tuple[IndexHit, ...]:
        from qdrant_client import models

        try:
            result = self.client.query_points(
                collection_name=self.collection_name,
                query=self.embedder.embed(text),
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="ownerId",
                            match=models.MatchValue(value=owner_id),
                        )
                    ]
                ),
                limit=limit,
                with_payload=False,
                with_vectors=False,
            )
            return tuple(
                IndexHit(str(point.id), float(point.score))
                for point in result.points
            )
        except MemoryError:
            raise
        except Exception as exc:
            raise MemoryError(
                "E_MEMORY_INDEX_QUERY",
                "derived memory index query failed",
                retryable=True,
            ) from exc

    def list_ids(self) -> set[str]:
        identifiers: set[str] = set()
        offset = None
        try:
            while True:
                points, offset = self.client.scroll(
                    collection_name=self.collection_name,
                    limit=256,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
                identifiers.update(str(point.id) for point in points)
                if offset is None:
                    return identifiers
        except Exception as exc:
            raise MemoryError(
                "E_MEMORY_INDEX_QUERY",
                "derived memory index inventory failed",
                retryable=True,
            ) from exc

    def recreate(self) -> None:
        try:
            if self.client.collection_exists(self.collection_name):
                self.client.delete_collection(self.collection_name)
            self._ensure_collection()
        except MemoryError:
            raise
        except Exception as exc:
            raise MemoryError(
                "E_MEMORY_INDEX_WRITE",
                "derived memory index rebuild failed",
                retryable=True,
            ) from exc

    def close(self) -> None:
        self.client.close()
