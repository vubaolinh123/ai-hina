from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import MemoryError


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class MemoryConfig:
    database_path: Path = Path("var/data/hina-memory.sqlite3")
    index_path: Path = Path("var/data/hina-memory-qdrant")
    owner_id: str = "owner.local"
    collection_name: str = "hina_memory_v1"
    vector_size: int = 256
    max_candidate_characters: int = 2_000
    max_active_records: int = 10_000
    default_retrieval_limit: int = 5
    max_retrieval_limit: int = 20
    context_byte_budget: int = 8_192

    def __post_init__(self) -> None:
        for value, label in (
            (self.owner_id, "owner ID"),
            (self.collection_name, "collection name"),
        ):
            if _IDENTIFIER.fullmatch(value) is None:
                raise MemoryError("E_MEMORY_CONFIG", f"memory {label} is invalid")
        for path, label in (
            (self.database_path, "database path"),
            (self.index_path, "index path"),
        ):
            if not isinstance(path, Path) or not path.name:
                raise MemoryError("E_MEMORY_CONFIG", f"memory {label} is invalid")
        if not 64 <= self.vector_size <= 4_096:
            raise MemoryError("E_MEMORY_CONFIG", "memory vector size is invalid")
        if not 128 <= self.max_candidate_characters <= 32_768:
            raise MemoryError("E_MEMORY_CONFIG", "memory candidate limit is invalid")
        if not 1 <= self.max_active_records <= 1_000_000:
            raise MemoryError("E_MEMORY_CONFIG", "memory record limit is invalid")
        if not 1 <= self.default_retrieval_limit <= self.max_retrieval_limit <= 100:
            raise MemoryError("E_MEMORY_CONFIG", "memory retrieval limit is invalid")
        if not 1_024 <= self.context_byte_budget <= 65_536:
            raise MemoryError("E_MEMORY_CONFIG", "memory context budget is invalid")

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        root: Path | None = None,
    ) -> MemoryConfig:
        values = env if env is not None else os.environ
        database = Path(values.get("HINA_MEMORY_DATABASE", "var/data/hina-memory.sqlite3"))
        index = Path(values.get("HINA_MEMORY_INDEX", "var/data/hina-memory-qdrant"))
        if root is not None:
            if not database.is_absolute():
                database = root / database
            if not index.is_absolute():
                index = root / index
        return cls(
            database_path=database,
            index_path=index,
            owner_id=values.get("HINA_MEMORY_OWNER_ID", "owner.local"),
            collection_name=values.get("HINA_MEMORY_COLLECTION", "hina_memory_v1"),
            vector_size=_env_int(values, "HINA_MEMORY_VECTOR_SIZE", 256),
            max_candidate_characters=_env_int(
                values,
                "HINA_MEMORY_MAX_CANDIDATE_CHARACTERS",
                2_000,
            ),
            max_active_records=_env_int(values, "HINA_MEMORY_MAX_RECORDS", 10_000),
            default_retrieval_limit=_env_int(
                values,
                "HINA_MEMORY_DEFAULT_RETRIEVAL_LIMIT",
                5,
            ),
            max_retrieval_limit=_env_int(
                values,
                "HINA_MEMORY_MAX_RETRIEVAL_LIMIT",
                20,
            ),
            context_byte_budget=_env_int(
                values,
                "HINA_MEMORY_CONTEXT_BYTE_BUDGET",
                8_192,
            ),
        )

    def public_status(self) -> dict[str, object]:
        return {
            "ownerId": self.owner_id,
            "authoritativeStore": "sqlite",
            "derivedIndex": "qdrant-local",
            "collection": self.collection_name,
            "embedding": "hina.lexical-hash.v1",
            "vectorSize": self.vector_size,
            "autoPromotion": False,
            "publicMemoryRetrieval": False,
            "contextRole": "user",
        }


def _env_int(values: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(values.get(name, str(default)))
    except ValueError as exc:
        raise MemoryError("E_MEMORY_CONFIG", f"{name} must be an integer") from exc
