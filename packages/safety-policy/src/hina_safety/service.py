from __future__ import annotations

import hashlib
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any, Callable

from .audit import AuditTrail
from .model import (
    FEATURE_FLAGS,
    Capability,
    CapabilityManifest,
    DecisionMode,
    RiskLevel,
    SafetyPolicyError,
    TrustLevel,
)
from .moderation import ModerationEngine
from .sanitation import InputSanitizer


_ACTOR = re.compile(r"^[^\x00-\x1f\x7f]{1,128}$")
_CONTROL_BASE = {"action", "actorId", "trustLevel", "correlationId"}


class SafetyController:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._revision = 0
        self._emergency_stopped = False
        self._muted = False
        self._feature_flags = {name: False for name in sorted(FEATURE_FLAGS)}
        self._revoked: set[str] = set()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "revision": self._revision,
                "emergencyStopped": self._emergency_stopped,
                "muted": self._muted,
                "featureFlags": dict(self._feature_flags),
                "revokedCapabilities": sorted(self._revoked),
            }

    def set_emergency(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            if self._emergency_stopped != enabled:
                self._emergency_stopped = enabled
                self._revision += 1
            return self.snapshot()

    def set_muted(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            if self._muted != enabled:
                self._muted = enabled
                self._revision += 1
            return self.snapshot()

    def set_feature(self, feature: str, enabled: bool) -> dict[str, Any]:
        if feature not in FEATURE_FLAGS:
            raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "feature flag is unknown")
        with self._lock:
            if self._feature_flags[feature] != enabled:
                self._feature_flags[feature] = enabled
                self._revision += 1
            return self.snapshot()

    def set_revoked(self, capability: str, enabled: bool) -> dict[str, Any]:
        with self._lock:
            changed = False
            if enabled and capability not in self._revoked:
                self._revoked.add(capability)
                changed = True
            elif not enabled and capability in self._revoked:
                self._revoked.remove(capability)
                changed = True
            if changed:
                self._revision += 1
            return self.snapshot()


class SafetyPolicyService:
    def __init__(
        self,
        manifest: CapabilityManifest,
        audit: AuditTrail,
        *,
        clock: Callable[[], float] | None = None,
        now: Callable[[], datetime] | None = None,
        sanitation_key: bytes | None = None,
        moderation_engine: ModerationEngine | None = None,
    ) -> None:
        self.manifest = manifest
        self.audit = audit
        self.controller = SafetyController()
        self.sanitizer = InputSanitizer(signing_key=sanitation_key)
        self.moderator = moderation_engine or ModerationEngine(self.sanitizer)
        self._clock = clock or time.monotonic
        self._now = now or (lambda: datetime.now(UTC))
        self._rate_events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._budget_used: dict[tuple[str, str], int] = defaultdict(int)
        self._decision_lock = threading.RLock()
        self._control_lock = threading.RLock()

    def status(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.as_json(),
            "state": self.controller.snapshot(),
            "audit": self.audit.status(),
            "sanitation": self.sanitizer.status(),
            "moderation": self.moderator.status(),
        }

    def recent_audit(self, limit: int = 20) -> dict[str, Any]:
        records = self.audit.recent(limit)
        return {
            "records": records,
            "count": len(records),
            "limit": limit,
            "lastHash": self.audit.last_hash,
        }

    def sanitize_input(self, raw: Any) -> dict[str, Any]:
        result = self.sanitizer.sanitize(raw)
        evidence = result.evidence
        self.audit.append(
            event_type="input.sanitized",
            correlation_id=evidence["correlationId"],
            actor_hash=_hash_actor(evidence["source"]),
            session_id=evidence["sessionId"],
            capability=evidence["source"],
            outcome="safe" if evidence["safeForContext"] else "quarantined",
            reason_code=(
                "sanitation_pass"
                if evidence["safeForContext"]
                else "injection_detected"
            ),
            state_revision=self.controller.snapshot()["revision"],
        )
        return result.as_json()

    def create_context(self, raw: Any) -> dict[str, Any]:
        bundle = self.sanitizer.create_context_bundle(raw)
        self.audit.append(
            event_type="context.created",
            correlation_id=bundle["correlationId"],
            actor_hash=_hash_actor("context.boundary"),
            session_id=bundle["sessionId"],
            outcome="allow",
            reason_code="evidence_verified",
            state_revision=self.controller.snapshot()["revision"],
            target="context.bundle",
        )
        return bundle

    def moderate(self, raw: Any) -> dict[str, Any]:
        request = self.moderator.prepare(raw)
        try:
            result = self.moderator.evaluate(
                request,
                state=self.controller.snapshot(),
                authorize=self.evaluate,
            )
        except Exception:
            result = self.moderator.fail_closed(request, "moderation_unavailable")
        try:
            self.audit.append(
                event_type="moderation.decision",
                correlation_id=result["correlationId"],
                actor_hash=_hash_actor(request.actor_id),
                session_id=result["sessionId"],
                capability=result["capability"],
                outcome=result["decision"],
                reason_code=result["reasonCode"],
                state_revision=self.controller.snapshot()["revision"],
                target=result["surface"],
            )
        except SafetyPolicyError:
            result = self.moderator.fail_closed(request, "audit_unavailable")
        return result

    def evaluate(self, raw: Any) -> dict[str, Any]:
        request = _parse_policy_request(raw)
        actor_hash = _hash_actor(request["actorId"])
        capability_name = request["capability"]
        correlation_id = request["correlationId"]
        session_id = request["sessionId"]
        consume = request["consume"]
        trust = request["trustLevel"]

        with self._decision_lock:
            state = self.controller.snapshot()
            capability = self.manifest.by_name.get(capability_name)
            mode, reason = self._decide(capability, trust, state)
            risk = capability.risk if capability is not None else RiskLevel.CRITICAL
            rate_remaining: int | None = None
            budget_remaining: int | None = None
            consumed = False
            pending_events: deque[float] | None = None
            pending_time = 0.0
            pending_budget_key: tuple[str, str] | None = None
            pending_budget_used = 0

            if capability is not None and mode is DecisionMode.ALLOW:
                rate_key = (actor_hash, capability.name)
                session_key = (session_id or f"actor:{actor_hash}", capability.name)
                events = self._rate_events[rate_key]
                now = self._clock()
                while events and events[0] <= now - 60:
                    events.popleft()
                used = self._budget_used[session_key]
                if len(events) >= capability.rate_limit_per_minute:
                    mode, reason = DecisionMode.DENY, "rate_limit_exceeded"
                elif used >= capability.session_budget:
                    mode, reason = DecisionMode.DENY, "session_budget_exhausted"
                elif consume:
                    consumed = True
                    pending_events = events
                    pending_time = now
                    pending_budget_key = session_key
                    pending_budget_used = used + 1
                rate_remaining = max(
                    0,
                    capability.rate_limit_per_minute - len(events) - int(consumed),
                )
                budget_remaining = max(
                    0,
                    capability.session_budget - used - int(consumed),
                )

            result = {
                "capability": capability_name,
                "decision": str(mode),
                "reasonCode": reason,
                "risk": str(risk),
                "consumed": consumed,
                "rateRemaining": rate_remaining,
                "budgetRemaining": budget_remaining,
                "correlationId": correlation_id,
                "stateRevision": state["revision"],
            }
            try:
                self.audit.append(
                    event_type="policy.decision",
                    correlation_id=correlation_id,
                    actor_hash=actor_hash,
                    session_id=session_id,
                    capability=capability_name,
                    outcome=str(mode),
                    reason_code=reason,
                    state_revision=state["revision"],
                )
            except SafetyPolicyError:
                result.update(
                    {
                        "decision": "deny",
                        "reasonCode": "audit_unavailable",
                        "consumed": False,
                    }
                )
                return result
            if consumed:
                assert pending_events is not None
                assert pending_budget_key is not None
                pending_events.append(pending_time)
                self._budget_used[pending_budget_key] = pending_budget_used
            return result

    def apply_control(self, raw: Any) -> dict[str, Any]:
        request = _parse_control_request(raw, self.manifest.by_name)
        action = request["action"]
        actor_hash = _hash_actor(request["actorId"])
        correlation_id = request["correlationId"]

        with self._control_lock:
            if action == "emergency_stop":
                state = self.controller.set_emergency(True)
                audit_recorded = True
                try:
                    self._audit_control(request, actor_hash, state)
                except SafetyPolicyError:
                    audit_recorded = False
                return {"state": state, "action": action, "auditRecorded": audit_recorded}

            current = self.controller.snapshot()
            self.audit.append(
                event_type="operator.control",
                correlation_id=correlation_id,
                actor_hash=actor_hash,
                outcome="requested",
                reason_code=action,
                state_revision=current["revision"],
                capability=request.get("capability"),
                target=request.get("feature"),
                enabled=request.get("enabled"),
            )
            if action == "emergency_reset":
                state = self.controller.set_emergency(False)
            elif action == "set_mute":
                state = self.controller.set_muted(request["enabled"])
            elif action == "set_feature":
                state = self.controller.set_feature(request["feature"], request["enabled"])
            else:
                state = self.controller.set_revoked(request["capability"], request["enabled"])
            return {"state": state, "action": action, "auditRecorded": True}

    def _audit_control(
        self,
        request: dict[str, Any],
        actor_hash: str,
        state: dict[str, Any],
    ) -> None:
        self.audit.append(
            event_type="operator.control",
            correlation_id=request["correlationId"],
            actor_hash=actor_hash,
            outcome="applied",
            reason_code=request["action"],
            state_revision=state["revision"],
            capability=request.get("capability"),
            target=request.get("feature"),
            enabled=request.get("enabled"),
        )

    def _decide(
        self,
        capability: Capability | None,
        trust: TrustLevel,
        state: dict[str, Any],
    ) -> tuple[DecisionMode, str]:
        if state["emergencyStopped"]:
            return DecisionMode.DENY, "emergency_stop"
        if capability is None:
            return DecisionMode.DENY, "unknown_capability"
        if capability.risk is RiskLevel.CRITICAL:
            return DecisionMode.DENY, "critical_capability"
        if capability.name in state["revokedCapabilities"]:
            return DecisionMode.DENY, "capability_revoked"
        if capability.expires_at is not None and self._now().astimezone(UTC) >= capability.expires_at:
            return DecisionMode.DENY, "capability_expired"
        if capability.feature_flag is not None and not state["featureFlags"][capability.feature_flag]:
            return DecisionMode.DENY, "feature_disabled"
        if capability.name == "stream.output" and state["muted"]:
            return DecisionMode.DENY, "operator_muted"
        if trust not in capability.allowed_trust_levels:
            return DecisionMode.DENY, "trust_not_allowed"
        if capability.default_decision is DecisionMode.DENY:
            return DecisionMode.DENY, "manifest_denied"
        if capability.default_decision is DecisionMode.ASK:
            return DecisionMode.ASK, "owner_confirmation_required"
        return DecisionMode.ALLOW, "manifest_allowed"


def _parse_policy_request(raw: Any) -> dict[str, Any]:
    expected = {
        "capability",
        "actorId",
        "trustLevel",
        "correlationId",
        "sessionId",
        "consume",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "policy request fields are invalid")
    capability = raw["capability"]
    if not isinstance(capability, str) or not 1 <= len(capability) <= 128:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "capability is invalid")
    actor = _validate_actor(raw["actorId"])
    correlation = _validate_uuid(raw["correlationId"], "correlation")
    session = (
        _validate_uuid(raw["sessionId"], "session")
        if raw["sessionId"] is not None
        else None
    )
    try:
        trust = TrustLevel(raw["trustLevel"])
    except (TypeError, ValueError) as exc:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "trust level is invalid") from exc
    if not isinstance(raw["consume"], bool):
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "consume must be boolean")
    return {
        "capability": capability,
        "actorId": actor,
        "trustLevel": trust,
        "correlationId": correlation,
        "sessionId": session,
        "consume": raw["consume"],
    }


def _parse_control_request(
    raw: Any,
    capabilities: dict[str, Capability],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "control request must be an object")
    action = raw.get("action")
    expected = {
        "emergency_stop": _CONTROL_BASE,
        "emergency_reset": _CONTROL_BASE,
        "set_mute": _CONTROL_BASE | {"enabled"},
        "set_feature": _CONTROL_BASE | {"feature", "enabled"},
        "set_revocation": _CONTROL_BASE | {"capability", "enabled"},
    }.get(action)
    if expected is None or set(raw) != expected:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "control request fields are invalid")
    try:
        trust = TrustLevel(raw["trustLevel"])
    except (TypeError, ValueError) as exc:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "trust level is invalid") from exc
    if trust is not TrustLevel.OWNER:
        raise SafetyPolicyError("E_SAFETY_CONTROL_DENIED", "owner trust is required")
    result = {
        "action": action,
        "actorId": _validate_actor(raw["actorId"]),
        "trustLevel": trust,
        "correlationId": _validate_uuid(raw["correlationId"], "correlation"),
    }
    if "enabled" in raw:
        if not isinstance(raw["enabled"], bool):
            raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "enabled must be boolean")
        result["enabled"] = raw["enabled"]
    if action == "set_feature":
        if raw["feature"] not in FEATURE_FLAGS:
            raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "feature flag is unknown")
        result["feature"] = raw["feature"]
    if action == "set_revocation":
        if raw["capability"] not in capabilities:
            raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "capability is unknown")
        result["capability"] = raw["capability"]
    return result


def _validate_actor(value: Any) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "actor identifier is invalid")
    return value


def _validate_uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", f"{field} identifier is invalid") from exc


def _hash_actor(actor: str) -> str:
    return hashlib.sha256(actor.encode("utf-8")).hexdigest()
