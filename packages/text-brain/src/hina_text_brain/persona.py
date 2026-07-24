from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import TextBrainError


@dataclass(frozen=True, slots=True)
class PersonaSpec:
    schema_version: str
    persona_id: str
    prompt_version: str
    name: str
    primary_language: str
    system_prompt: str
    invariants: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> PersonaSpec:
        try:
            raw = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_pairs,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise TextBrainError("E_PERSONA_INVALID", "persona spec is unreadable") from exc
        expected = {
            "schemaVersion",
            "personaId",
            "promptVersion",
            "name",
            "primaryLanguage",
            "systemPrompt",
            "invariants",
        }
        if not isinstance(raw, dict) or set(raw) != expected or raw["schemaVersion"] != "1.0":
            raise TextBrainError("E_PERSONA_INVALID", "persona fields are invalid")
        for key in ("personaId", "promptVersion", "name", "primaryLanguage", "systemPrompt"):
            value = raw[key]
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value.encode("utf-8")) > 8_192
            ):
                raise TextBrainError("E_PERSONA_INVALID", f"persona {key} is invalid")
        invariants = raw["invariants"]
        if (
            not isinstance(invariants, list)
            or not 1 <= len(invariants) <= 32
            or any(
                not isinstance(item, str)
                or not item.strip()
                or len(item.encode("utf-8")) > 1_024
                for item in invariants
            )
            or len(invariants) != len(set(invariants))
        ):
            raise TextBrainError("E_PERSONA_INVALID", "persona invariants are invalid")
        return cls(
            schema_version="1.0",
            persona_id=raw["personaId"],
            prompt_version=raw["promptVersion"],
            name=raw["name"],
            primary_language=raw["primaryLanguage"],
            system_prompt=raw["systemPrompt"],
            invariants=tuple(invariants),
        )

    def public_status(self) -> dict[str, Any]:
        return {
            "personaId": self.persona_id,
            "promptVersion": self.prompt_version,
            "name": self.name,
            "primaryLanguage": self.primary_language,
            "invariantCount": len(self.invariants),
        }


@dataclass(frozen=True, slots=True)
class RelationshipState:
    completed_turns: int = 0
    familiarity: str = "new"

    def advance(self) -> RelationshipState:
        turns = min(10_000, self.completed_turns + 1)
        if turns >= 20:
            familiarity = "familiar"
        elif turns >= 5:
            familiarity = "acquainted"
        else:
            familiarity = "new"
        return RelationshipState(turns, familiarity)

    def as_json(self) -> dict[str, Any]:
        return {
            "completedTurns": self.completed_turns,
            "familiarity": self.familiarity,
        }


def render_system_prompt(
    persona: PersonaSpec,
    relationship: RelationshipState,
) -> str:
    invariants = "\n".join(f"- {item}" for item in persona.invariants)
    return (
        f"[persona={persona.persona_id}; prompt={persona.prompt_version}]\n"
        f"{persona.system_prompt}\n\n"
        f"Quan hệ phiên hiện tại: {relationship.familiarity}; "
        f"{relationship.completed_turns} lượt hoàn tất. "
        "Đây chỉ là trạng thái phiên, không phải ký ức dài hạn.\n\n"
        "Bất biến:\n"
        f"{invariants}\n\n"
        "Perception hiện tại: không có observation màn hình/camera/game còn hạn. "
        "Không được nói như thể bạn đang nhìn thấy trạng thái hiện tại.\n"
        "Không đưa hidden reasoning ra câu trả lời. Chỉ trả kết luận hữu ích."
    )


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result
