from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable

from .context import ComposedContext, ContextComposer
from .errors import TextBrainError
from .gateway import ModelGateway
from .memory import ShortTermMemory
from .persona import PersonaSpec


MAX_ASSISTANT_BYTES = 16_384
MAX_TRACKED_TURNS = 256
_CHAT_SOURCES = frozenset(
    {
        "owner.console",
        "authenticated.user",
        "public.chat",
        "viewer.chat",
    }
)
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class TurnState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ERROR = "error"


_TRANSITIONS = {
    TurnState.IDLE: frozenset({TurnState.LISTENING}),
    TurnState.LISTENING: frozenset(
        {TurnState.THINKING, TurnState.INTERRUPTED, TurnState.ERROR}
    ),
    TurnState.THINKING: frozenset(
        {TurnState.SPEAKING, TurnState.INTERRUPTED, TurnState.ERROR}
    ),
    TurnState.SPEAKING: frozenset(
        {TurnState.IDLE, TurnState.INTERRUPTED, TurnState.ERROR}
    ),
    TurnState.INTERRUPTED: frozenset(),
    TurnState.ERROR: frozenset(),
}


class TurnMachine:
    def __init__(self) -> None:
        self.state = TurnState.IDLE
        self.history = [
            {
                "state": str(TurnState.IDLE),
                "timestamp": _timestamp(),
            }
        ]

    def transition(self, target: TurnState) -> None:
        if target not in _TRANSITIONS[self.state]:
            raise TextBrainError(
                "E_TURN_TRANSITION",
                f"turn transition {self.state}->{target} is invalid",
            )
        self.state = target
        self.history.append(
            {
                "state": str(target),
                "timestamp": _timestamp(),
            }
        )


@dataclass(slots=True)
class TurnRecord:
    turn_id: str
    session_id: str
    correlation_id: str
    source: str
    input_hash: str
    machine: TurnMachine
    created_at: str
    outcome: str = "running"
    sanitized_user_text: str | None = None
    assistant_text: str | None = None
    prompt_version: str | None = None
    context_summary: dict[str, Any] | None = None
    tool_proposal: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    task: asyncio.Task[None] | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    def as_json(self) -> dict[str, Any]:
        return {
            "turnId": self.turn_id,
            "sessionId": self.session_id,
            "correlationId": self.correlation_id,
            "state": str(self.machine.state),
            "stateHistory": list(self.machine.history),
            "outcome": self.outcome,
            "createdAt": self.created_at,
            "user": self.sanitized_user_text,
            "assistant": self.assistant_text,
            "promptVersion": self.prompt_version,
            "context": self.context_summary,
            "toolProposal": self.tool_proposal,
            "errorCode": self.error_code,
            "errorMessage": self.error_message,
        }


class ConversationService:
    def __init__(
        self,
        gateway: ModelGateway,
        safety_policy: Any,
        persona: PersonaSpec,
        *,
        memory: ShortTermMemory | None = None,
        context_composer: ContextComposer | None = None,
        long_term_memory: Any | None = None,
        on_error: Callable[[dict[str, str]], None] | None = None,
    ) -> None:
        if safety_policy is None:
            raise TextBrainError("E_CHAT_CONFIG", "safety policy is required")
        self.gateway = gateway
        self.safety_policy = safety_policy
        self.persona = persona
        self.memory = memory or ShortTermMemory()
        self.context_composer = context_composer or ContextComposer(
            persona,
            self.memory,
            long_term_memory=long_term_memory,
        )
        self.on_error = on_error
        self._turns: dict[str, TurnRecord] = {}
        self._active_by_session: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def status(self) -> dict[str, Any]:
        async with self._lock:
            active = len(self._active_by_session)
            tracked = len(self._turns)
        return {
            "persona": self.persona.public_status(),
            "memory": await self.memory.status(),
            "activeTurns": active,
            "trackedTurns": tracked,
            "outboundPartialStreaming": False,
            "toolExecution": False,
        }

    async def start_turn(self, raw: Any) -> dict[str, Any]:
        request = _parse_turn_request(raw)
        async with self._lock:
            if request["sessionId"] in self._active_by_session:
                raise TextBrainError(
                    "E_TURN_ACTIVE",
                    "session already has an active turn",
                )
            self._prune_turns_locked()
            turn_id = str(uuid.uuid4())
            record = TurnRecord(
                turn_id=turn_id,
                session_id=request["sessionId"],
                correlation_id=str(uuid.uuid4()),
                source=request["source"],
                input_hash=hashlib.sha256(request["text"].encode("utf-8")).hexdigest(),
                machine=TurnMachine(),
                created_at=_timestamp(),
            )
            record.machine.transition(TurnState.LISTENING)
            self._turns[turn_id] = record
            self._active_by_session[record.session_id] = turn_id
            record.task = asyncio.create_task(
                self._run_turn(record, request["text"]),
                name=f"hina-turn-{turn_id}",
            )
            return record.as_json()

    async def get_turn(self, turn_id: str) -> dict[str, Any]:
        normalized = _validate_uuid(turn_id, "turn")
        async with self._lock:
            record = self._turns.get(normalized)
            if record is None:
                raise TextBrainError("E_TURN_NOT_FOUND", "turn was not found")
            return record.as_json()

    async def wait_turn(self, turn_id: str, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
        normalized = _validate_uuid(turn_id, "turn")
        async with self._lock:
            record = self._turns.get(normalized)
            if record is None:
                raise TextBrainError("E_TURN_NOT_FOUND", "turn was not found")
            task = record.task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
            except TimeoutError:
                pass
        return await self.get_turn(normalized)

    async def cancel_turn(self, turn_id: str) -> dict[str, Any]:
        normalized = _validate_uuid(turn_id, "turn")
        async with self._lock:
            record = self._turns.get(normalized)
            if record is None:
                raise TextBrainError("E_TURN_NOT_FOUND", "turn was not found")
            if record.outcome != "running":
                return record.as_json()
            record.cancel_event.set()
            if record.machine.state in {
                TurnState.LISTENING,
                TurnState.THINKING,
                TurnState.SPEAKING,
            }:
                record.machine.transition(TurnState.INTERRUPTED)
            record.outcome = "interrupted"
            self._active_by_session.pop(record.session_id, None)
            task = record.task
            if task is not None:
                task.cancel()
            return record.as_json()

    async def replay(self, session_id: str) -> dict[str, Any]:
        return await self.memory.replay(_validate_uuid(session_id, "session"))

    async def clear_session(self, session_id: str) -> dict[str, Any]:
        normalized = _validate_uuid(session_id, "session")
        async with self._lock:
            if normalized in self._active_by_session:
                raise TextBrainError("E_TURN_ACTIVE", "cannot clear an active session")
        return await self.memory.clear(normalized)

    async def close(self) -> None:
        async with self._lock:
            tasks = [
                record.task
                for record in self._turns.values()
                if record.task is not None and not record.task.done()
            ]
            for record in self._turns.values():
                if record.task in tasks and record.outcome == "running":
                    record.cancel_event.set()
                    if record.machine.state in {
                        TurnState.LISTENING,
                        TurnState.THINKING,
                        TurnState.SPEAKING,
                    }:
                        record.machine.transition(TurnState.INTERRUPTED)
                    record.outcome = "interrupted"
                    record.task.cancel()
            self._active_by_session.clear()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_turn(self, record: TurnRecord, raw_text: str) -> None:
        try:
            moderated_input = self.safety_policy.moderate(
                {
                    "surface": "input",
                    "source": record.source,
                    "text": raw_text,
                    "actorId": f"chat.{record.source}",
                    "correlationId": record.correlation_id,
                    "sessionId": record.session_id,
                    "toolProposal": None,
                }
            )
            if moderated_input.get("decision") != "allow":
                raise TextBrainError(
                    "E_CHAT_INPUT_BLOCKED",
                    f"chat input was {moderated_input.get('decision', 'blocked')}",
                )
            sanitized_user = moderated_input.get("sanitizedText")
            if not isinstance(sanitized_user, str) or not sanitized_user:
                raise TextBrainError("E_CHAT_INPUT_BLOCKED", "sanitized chat input is empty")
            record.sanitized_user_text = sanitized_user
            record.machine.transition(TurnState.THINKING)
            context = await self.context_composer.compose(
                record.session_id,
                sanitized_user,
                source=record.source,
            )
            record.prompt_version = context.prompt_version
            record.context_summary = context.as_json()
            response = await self._collect_model_output(record, context)
            proposal = _parse_tool_proposal(response)
            if proposal is not None:
                tool_decision = self.safety_policy.moderate(
                    {
                        "surface": "pre_tool",
                        "source": "local.service",
                        "text": response,
                        "actorId": "model.text-brain",
                        "correlationId": record.correlation_id,
                        "sessionId": record.session_id,
                        "toolProposal": proposal,
                    }
                )
                if tool_decision.get("decision") != "allow":
                    raise TextBrainError(
                        "E_TOOL_PROPOSAL_BLOCKED",
                        "typed tool proposal was blocked by policy",
                    )
                record.tool_proposal = proposal

            moderated_output = self.safety_policy.moderate(
                {
                    "surface": "outbound",
                    "source": "local.service",
                    "text": response,
                    "actorId": "model.text-brain",
                    "correlationId": record.correlation_id,
                    "sessionId": record.session_id,
                    "toolProposal": None,
                }
            )
            if moderated_output.get("decision") != "allow":
                raise TextBrainError(
                    "E_CHAT_OUTPUT_BLOCKED",
                    "model output was blocked by outbound moderation",
                )
            assistant = moderated_output.get("sanitizedText")
            if not isinstance(assistant, str) or not assistant.strip():
                raise TextBrainError("E_MODEL_EMPTY_RESPONSE", "model returned no safe text")
            if record.cancel_event.is_set():
                raise asyncio.CancelledError
            record.machine.transition(TurnState.SPEAKING)
            record.assistant_text = assistant
            await self.memory.append(
                record.session_id,
                record.turn_id,
                sanitized_user,
                assistant,
            )
            record.machine.transition(TurnState.IDLE)
            record.outcome = "completed"
        except asyncio.CancelledError:
            if record.outcome == "running":
                if record.machine.state in {
                    TurnState.LISTENING,
                    TurnState.THINKING,
                    TurnState.SPEAKING,
                }:
                    record.machine.transition(TurnState.INTERRUPTED)
                record.outcome = "interrupted"
            record.assistant_text = None
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, TextBrainError)
                else TextBrainError("E_CHAT_FAILED", "conversation turn failed")
            )
            if record.machine.state in {
                TurnState.LISTENING,
                TurnState.THINKING,
                TurnState.SPEAKING,
            }:
                record.machine.transition(TurnState.ERROR)
            record.outcome = "error"
            record.assistant_text = None
            record.tool_proposal = None
            record.error_code = error.code
            record.error_message = error.detail
            self._notify_error(record)
        finally:
            async with self._lock:
                if self._active_by_session.get(record.session_id) == record.turn_id:
                    self._active_by_session.pop(record.session_id, None)

    async def _collect_model_output(
        self,
        record: TurnRecord,
        context: ComposedContext,
    ) -> str:
        parts: list[str] = []
        total_bytes = 0
        async for token in self.gateway.stream_chat(list(context.messages)):
            if record.cancel_event.is_set():
                raise asyncio.CancelledError
            total_bytes += len(token.encode("utf-8"))
            if total_bytes > MAX_ASSISTANT_BYTES:
                raise TextBrainError(
                    "E_MODEL_OUTPUT_TOO_LARGE",
                    "model output exceeds moderation boundary",
                )
            parts.append(token)
        return "".join(parts).strip()

    def _notify_error(self, record: TurnRecord) -> None:
        if self.on_error is None or record.error_code is None:
            return
        try:
            self.on_error(
                {
                    "turnId": record.turn_id,
                    "sessionId": record.session_id,
                    "correlationId": record.correlation_id,
                    "errorCode": record.error_code,
                    "inputHash": record.input_hash,
                }
            )
        except Exception:
            pass

    def _prune_turns_locked(self) -> None:
        if len(self._turns) < MAX_TRACKED_TURNS:
            return
        removable = [
            turn_id
            for turn_id, record in self._turns.items()
            if record.outcome != "running"
        ]
        for turn_id in removable[: max(1, len(self._turns) - MAX_TRACKED_TURNS + 1)]:
            self._turns.pop(turn_id, None)


def _parse_turn_request(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict) or set(raw) != {"sessionId", "source", "text"}:
        raise TextBrainError("E_CHAT_BAD_REQUEST", "chat turn fields are invalid")
    session_id = _validate_uuid(raw["sessionId"], "session")
    source = raw["source"]
    text = raw["text"]
    if source not in _CHAT_SOURCES:
        raise TextBrainError("E_CHAT_BAD_REQUEST", "chat source is invalid")
    if not isinstance(text, str) or not text.strip():
        raise TextBrainError("E_CHAT_BAD_REQUEST", "chat text is invalid")
    try:
        if len(text.encode("utf-8")) > 16_384:
            raise TextBrainError("E_CHAT_BAD_REQUEST", "chat text exceeds byte limit")
    except UnicodeEncodeError as exc:
        raise TextBrainError("E_CHAT_BAD_REQUEST", "chat text is invalid Unicode") from exc
    return {
        "sessionId": session_id,
        "source": source,
        "text": text,
    }


def _parse_tool_proposal(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        value = json.loads(stripped, object_pairs_hook=_reject_duplicate_pairs)
    except (json.JSONDecodeError, ValueError) as exc:
        if '"tool_proposal"' in stripped[:256]:
            raise TextBrainError("E_TOOL_PROPOSAL_INVALID", "tool proposal JSON is invalid") from exc
        return None
    if not isinstance(value, dict) or value.get("type") != "tool_proposal":
        return None
    if set(value) != {"type", "capability", "intent", "arguments"}:
        raise TextBrainError("E_TOOL_PROPOSAL_INVALID", "tool proposal fields are invalid")
    if (
        not isinstance(value["capability"], str)
        or _TOOL_NAME.fullmatch(value["capability"]) is None
        or not isinstance(value["intent"], str)
        or _TOOL_NAME.fullmatch(value["intent"]) is None
        or not isinstance(value["arguments"], dict)
    ):
        raise TextBrainError("E_TOOL_PROPOSAL_INVALID", "tool proposal values are invalid")
    try:
        argument_size = len(
            json.dumps(
                value["arguments"],
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise TextBrainError("E_TOOL_PROPOSAL_INVALID", "tool proposal arguments are invalid") from exc
    if argument_size > 8_192:
        raise TextBrainError("E_TOOL_PROPOSAL_INVALID", "tool proposal arguments are too large")
    return {
        "capability": value["capability"],
        "intent": value["intent"],
        "arguments": value["arguments"],
    }


def _validate_uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise TextBrainError("E_CHAT_BAD_REQUEST", f"{field} identifier is invalid") from exc


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
