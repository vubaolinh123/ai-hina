from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass

from .errors import MemoryError


_TOKEN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class LexicalHashEmbedder:
    """Deterministic lexical vectors; rebuildable baseline, not a semantic-quality claim."""

    dimensions: int = 256

    def __post_init__(self) -> None:
        if not 64 <= self.dimensions <= 4_096:
            raise MemoryError("E_MEMORY_CONFIG", "embedding dimensions are invalid")

    @property
    def identity(self) -> str:
        return f"hina.lexical-hash.v1:{self.dimensions}"

    def embed(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise MemoryError("E_MEMORY_TEXT", "memory embedding text is empty")
        normalized = unicodedata.normalize("NFC", text).casefold()
        features: list[tuple[str, float]] = []
        for token in _TOKEN.findall(normalized):
            features.append((f"w:{token}", 2.0))
            padded = f"^{token}$"
            features.extend(
                (f"c:{padded[index:index + 3]}", 0.5)
                for index in range(max(1, len(padded) - 2))
            )
        if not features:
            raise MemoryError("E_MEMORY_TEXT", "memory text has no indexable features")
        vector = [0.0] * self.dimensions
        for feature, weight in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            position = value % self.dimensions
            sign = -1.0 if value & 1 else 1.0
            vector[position] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            raise MemoryError("E_MEMORY_TEXT", "memory embedding collapsed to zero")
        return [value / norm for value in vector]
