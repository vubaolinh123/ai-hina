from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable

from .model import SafetyPolicyError
from .sanitation import InputSanitizer, SanitationResult


MODERATION_POLICY_VERSION = "hina.moderation.v1"
MAX_TOOL_ARGUMENT_BYTES = 8_192

_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_INTENT = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_EXECUTABLE_KEYS = frozenset(
    {
        "argv",
        "bash",
        "cmd",
        "code",
        "command",
        "executable",
        "javascript",
        "powershell",
        "python",
        "script",
        "shell",
    }
)
_EXECUTION_PATTERNS = (
    re.compile(
        r"\b(?:run|execute|launch|invoke)\b.{0,40}"
        r"\b(?:bash|cmd|command|javascript|node|powershell|python|script|shell)\b"
    ),
    re.compile(
        r"\b(?:chay|thuc thi|goi)\b.{0,40}"
        r"\b(?:bash|cmd|javascript|lenh|ma|powershell|python|script|shell)\b"
    ),
    re.compile(r"```(?:bash|bat|cmd|javascript|js|powershell|ps1|py|python|sh)\b"),
    re.compile(r"\b(?:bash|cmd(?:\.exe)?|node|powershell|python(?:3)?)\s+(?:-|/c\b)"),
)
_HIDDEN_REASONING_PATTERNS = (
    re.compile(r"<\s*(?:analysis|think)\s*>"),
    re.compile(r"\[\s*(?:chain[_ -]?of[_ -]?thought|hidden[_ -]?reasoning)\s*\]"),
    re.compile(r"\b(?:chain of thought|hidden reasoning|private reasoning)\b"),
    re.compile(r"\b(?:lap luan an|suy luan noi bo|suy nghi bi mat)\b"),
)


class ModerationSurface(StrEnum):
    INPUT = "input"
    PRE_TOOL = "pre_tool"
    PRE_TTS = "pre_tts"
    OUTBOUND = "outbound"


class ModerationDecision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    QUARANTINE = "quarantine"


@dataclass(frozen=True, slots=True)
class PreparedModeration:
    surface: ModerationSurface
    actor_id: str
    tool_proposal: dict[str, Any] | None
    sanitation: SanitationResult


class ModerationEngine:
    def __init__(self, sanitizer: InputSanitizer) -> None:
        self._sanitizer = sanitizer

    def status(self) -> dict[str, Any]:
        return {
            "policyVersion": MODERATION_POLICY_VERSION,
            "surfaces": [str(surface) for surface in ModerationSurface],
            "maxToolArgumentBytes": MAX_TOOL_ARGUMENT_BYTES,
            "generatedCodeExecution": "denied",
            "hiddenReasoningOutput": "denied",
        }

    def prepare(self, raw: Any) -> PreparedModeration:
        expected = {
            "surface",
            "source",
            "text",
            "actorId",
            "correlationId",
            "sessionId",
            "toolProposal",
        }
        if not isinstance(raw, dict) or set(raw) != expected:
            raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "moderation request fields are invalid")
        try:
            surface = ModerationSurface(raw["surface"])
        except (TypeError, ValueError) as exc:
            raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "moderation surface is invalid") from exc
        actor_id = raw["actorId"]
        if (
            not isinstance(actor_id, str)
            or not 1 <= len(actor_id) <= 128
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in actor_id)
        ):
            raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "moderation actor is invalid")
        proposal = raw["toolProposal"]
        if surface is ModerationSurface.PRE_TOOL:
            proposal = _parse_tool_proposal(proposal)
        elif proposal is not None:
            raise SafetyPolicyError(
                "E_SAFETY_BAD_REQUEST",
                "tool proposal is only valid on the pre_tool surface",
            )
        sanitation = self._sanitizer.sanitize(
            {
                "source": raw["source"],
                "text": raw["text"],
                "correlationId": raw["correlationId"],
                "sessionId": raw["sessionId"],
            }
        )
        return PreparedModeration(surface, actor_id, proposal, sanitation)

    def evaluate(
        self,
        request: PreparedModeration,
        *,
        state: dict[str, Any],
        authorize: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        evidence = request.sanitation.evidence
        surface = request.surface
        if state["emergencyStopped"]:
            return self.block(request, "emergency_stop", ["operator_control"])
        if surface in {ModerationSurface.PRE_TTS, ModerationSurface.OUTBOUND} and state["muted"]:
            return self.block(request, "operator_muted", ["operator_control"])

        if not evidence["safeForContext"]:
            return self.quarantine(request, "unsafe_input", evidence["signals"])

        normalized = _fold_for_detection(request.sanitation.sanitized_text)
        if surface in {ModerationSurface.PRE_TTS, ModerationSurface.OUTBOUND}:
            if evidence["redactions"]:
                return self.block(request, "sensitive_data_redacted", ["sensitive_data"])
            if any(pattern.search(normalized) for pattern in _HIDDEN_REASONING_PATTERNS):
                return self.block(request, "hidden_reasoning", ["hidden_reasoning"])

        policy_decision: dict[str, Any] | None = None
        capability: str | None = None
        if surface is ModerationSurface.PRE_TOOL:
            assert request.tool_proposal is not None
            capability = request.tool_proposal["capability"]
            proposal_text = json.dumps(
                request.tool_proposal,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            executable_key = _find_executable_key(request.tool_proposal["arguments"])
            executable_text = _fold_for_detection(
                f"{request.sanitation.sanitized_text}\n{proposal_text}"
            )
            if executable_key is not None or any(
                pattern.search(executable_text) for pattern in _EXECUTION_PATTERNS
            ):
                return self.block(
                    request,
                    "generated_code_execution",
                    ["generated_code", "executable_request"],
                    capability=capability,
                )
            policy_decision = authorize(
                {
                    "capability": capability,
                    "actorId": request.actor_id,
                    "trustLevel": evidence["trustLevel"],
                    "correlationId": evidence["correlationId"],
                    "sessionId": evidence["sessionId"],
                    "consume": True,
                }
            )
            if policy_decision.get("decision") != "allow":
                return self.block(
                    request,
                    str(policy_decision.get("reasonCode") or "authorization_failed"),
                    ["capability_policy"],
                    capability=capability,
                    policy_decision=policy_decision,
                )

        return self._result(
            request,
            ModerationDecision.ALLOW,
            "moderation_pass",
            [],
            capability=capability,
            policy_decision=policy_decision,
            include_text=True,
        )

    def fail_closed(self, request: PreparedModeration, reason: str) -> dict[str, Any]:
        return self.block(request, reason, ["internal_failure"])

    def block(
        self,
        request: PreparedModeration,
        reason: str,
        categories: list[str],
        *,
        capability: str | None = None,
        policy_decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._result(
            request,
            ModerationDecision.BLOCK,
            reason,
            categories,
            capability=capability,
            policy_decision=policy_decision,
            include_text=False,
        )

    def quarantine(
        self,
        request: PreparedModeration,
        reason: str,
        categories: list[str],
    ) -> dict[str, Any]:
        return self._result(
            request,
            ModerationDecision.QUARANTINE,
            reason,
            categories,
            include_text=False,
        )

    def _result(
        self,
        request: PreparedModeration,
        decision: ModerationDecision,
        reason: str,
        categories: list[str],
        *,
        capability: str | None = None,
        policy_decision: dict[str, Any] | None = None,
        include_text: bool,
    ) -> dict[str, Any]:
        evidence = request.sanitation.evidence
        return {
            "policyVersion": MODERATION_POLICY_VERSION,
            "surface": str(request.surface),
            "decision": str(decision),
            "reasonCode": reason,
            "categories": sorted(set(categories)),
            "source": evidence["source"],
            "trustLevel": evidence["trustLevel"],
            "correlationId": evidence["correlationId"],
            "sessionId": evidence["sessionId"],
            "contentHash": evidence["contentHash"],
            "sanitizedHash": evidence["sanitizedHash"],
            "sanitizedText": request.sanitation.sanitized_text if include_text else None,
            "capability": capability,
            "policyDecision": policy_decision,
        }


def _parse_tool_proposal(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {"capability", "intent", "arguments"}:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "tool proposal fields are invalid")
    capability = raw["capability"]
    intent = raw["intent"]
    arguments = raw["arguments"]
    if not isinstance(capability, str) or _NAME.fullmatch(capability) is None:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "tool proposal capability is invalid")
    if not isinstance(intent, str) or _INTENT.fullmatch(intent) is None:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "tool proposal intent is invalid")
    if not isinstance(arguments, dict):
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "tool proposal arguments are invalid")
    try:
        encoded = json.dumps(
            arguments,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "tool proposal arguments are invalid") from exc
    if len(encoded) > MAX_TOOL_ARGUMENT_BYTES:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "tool proposal arguments exceed byte limit")
    return {
        "capability": capability,
        "intent": intent,
        "arguments": arguments,
    }


def _find_executable_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            folded = _fold_for_detection(str(key)).replace(" ", "_")
            if folded in _EXECUTABLE_KEYS:
                return folded
            found = _find_executable_key(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_executable_key(child)
            if found is not None:
                return found
    return None


def _fold_for_detection(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text).casefold()
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    substitutions = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})
    deobfuscated = without_marks.translate(substitutions)
    return re.sub(r"[^\w<>`./-]+", " ", deobfuscated, flags=re.UNICODE).strip()
