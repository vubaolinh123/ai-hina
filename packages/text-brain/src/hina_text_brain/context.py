from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import TextBrainError
from .memory import ShortTermMemory
from .persona import PersonaSpec, render_system_prompt


MAX_MODEL_CONTEXT_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class ComposedContext:
    prompt_version: str
    messages: tuple[dict[str, str], ...]
    included_memory_turns: int
    total_bytes: int

    def as_json(self) -> dict[str, Any]:
        return {
            "promptVersion": self.prompt_version,
            "messageCount": len(self.messages),
            "includedMemoryTurns": self.included_memory_turns,
            "totalBytes": self.total_bytes,
        }


class ContextComposer:
    def __init__(
        self,
        persona: PersonaSpec,
        memory: ShortTermMemory,
        *,
        max_bytes: int = MAX_MODEL_CONTEXT_BYTES,
    ) -> None:
        if not 4_096 <= max_bytes <= 1_048_576:
            raise TextBrainError("E_CONTEXT_CONFIG", "model context budget is invalid")
        self.persona = persona
        self.memory = memory
        self.max_bytes = max_bytes

    async def compose(self, session_id: str, user_text: str) -> ComposedContext:
        turns, relationship = await self.memory.context(session_id)
        system = {"role": "system", "content": render_system_prompt(self.persona, relationship)}
        current = {"role": "user", "content": user_text}
        base_size = _message_bytes(system) + _message_bytes(current)
        if base_size > self.max_bytes:
            raise TextBrainError("E_CONTEXT_OVERFLOW", "persona and current input exceed context budget")

        selected = []
        total = base_size
        for turn in reversed(turns):
            pair_size = sum(_message_bytes(message) for message in turn.messages())
            if total + pair_size > self.max_bytes:
                break
            selected.append(turn)
            total += pair_size
        messages = [system]
        for turn in reversed(selected):
            messages.extend(turn.messages())
        messages.append(current)
        return ComposedContext(
            prompt_version=self.persona.prompt_version,
            messages=tuple(messages),
            included_memory_turns=len(selected),
            total_bytes=total,
        )


def _message_bytes(message: dict[str, str]) -> int:
    return len(message["role"].encode("utf-8")) + len(message["content"].encode("utf-8")) + 16
