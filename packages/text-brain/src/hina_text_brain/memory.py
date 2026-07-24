from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .errors import TextBrainError
from .persona import RelationshipState


MAX_MEMORY_TURNS = 24
MAX_MEMORY_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class MemoryTurn:
    turn_id: str
    user_text: str
    assistant_text: str
    completed_at: str

    @property
    def byte_size(self) -> int:
        return len(self.user_text.encode("utf-8")) + len(self.assistant_text.encode("utf-8"))

    def messages(self) -> tuple[dict[str, str], dict[str, str]]:
        return (
            {"role": "user", "content": self.user_text},
            {"role": "assistant", "content": self.assistant_text},
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "turnId": self.turn_id,
            "user": self.user_text,
            "assistant": self.assistant_text,
            "completedAt": self.completed_at,
        }


@dataclass(slots=True)
class _SessionMemory:
    turns: list[MemoryTurn]
    relationship: RelationshipState


class ShortTermMemory:
    def __init__(
        self,
        *,
        max_turns: int = MAX_MEMORY_TURNS,
        max_bytes: int = MAX_MEMORY_BYTES,
    ) -> None:
        if not 1 <= max_turns <= 256 or not 1_024 <= max_bytes <= 1_048_576:
            raise TextBrainError("E_MEMORY_CONFIG", "short-term memory budget is invalid")
        self.max_turns = max_turns
        self.max_bytes = max_bytes
        self._sessions: dict[str, _SessionMemory] = {}
        self._lock = asyncio.Lock()

    async def append(
        self,
        session_id: str,
        turn_id: str,
        user_text: str,
        assistant_text: str,
    ) -> MemoryTurn:
        turn = MemoryTurn(
            turn_id=turn_id,
            user_text=user_text,
            assistant_text=assistant_text,
            completed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
        if turn.byte_size > self.max_bytes:
            raise TextBrainError("E_CONTEXT_OVERFLOW", "completed turn exceeds memory budget")
        async with self._lock:
            session = self._sessions.setdefault(
                session_id,
                _SessionMemory([], RelationshipState()),
            )
            session.turns.append(turn)
            while (
                len(session.turns) > self.max_turns
                or sum(item.byte_size for item in session.turns) > self.max_bytes
            ):
                session.turns.pop(0)
            session.relationship = session.relationship.advance()
        return turn

    async def context(self, session_id: str) -> tuple[tuple[MemoryTurn, ...], RelationshipState]:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return (), RelationshipState()
            return tuple(session.turns), session.relationship

    async def replay(self, session_id: str) -> dict[str, Any]:
        turns, relationship = await self.context(session_id)
        return {
            "sessionId": session_id,
            "turns": [turn.as_json() for turn in turns],
            "turnCount": len(turns),
            "totalBytes": sum(turn.byte_size for turn in turns),
            "relationship": relationship.as_json(),
        }

    async def clear(self, session_id: str) -> dict[str, Any]:
        async with self._lock:
            existed = self._sessions.pop(session_id, None) is not None
        return {
            "sessionId": session_id,
            "cleared": existed,
            "turnCount": 0,
            "relationship": RelationshipState().as_json(),
        }

    async def status(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "sessionCount": len(self._sessions),
                "turnCount": sum(len(session.turns) for session in self._sessions.values()),
                "maxTurnsPerSession": self.max_turns,
                "maxBytesPerSession": self.max_bytes,
            }
