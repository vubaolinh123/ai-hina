from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
FEATURE_FLAGS = frozenset(
    {
        "memoryPromotion",
        "perception",
        "gameAction",
        "streamOutput",
    }
)


class SafetyPolicyError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail[:256]


class DecisionMode(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TrustLevel(StrEnum):
    AUTHENTICATED = "authenticated"
    OWNER = "owner"
    PUBLIC = "public"
    TRUSTED_LOCAL = "trusted_local"
    UNTRUSTED = "untrusted"


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    risk: RiskLevel
    default_decision: DecisionMode
    allowed_trust_levels: frozenset[TrustLevel]
    feature_flag: str | None
    rate_limit_per_minute: int
    session_budget: int
    expires_at: datetime | None

    def as_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "risk": str(self.risk),
            "defaultDecision": str(self.default_decision),
            "allowedTrustLevels": sorted(str(level) for level in self.allowed_trust_levels),
            "featureFlag": self.feature_flag,
            "rateLimitPerMinute": self.rate_limit_per_minute,
            "sessionBudget": self.session_budget,
            "expiresAt": (
                self.expires_at.isoformat().replace("+00:00", "Z")
                if self.expires_at is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    schema_version: str
    manifest_id: str
    capabilities: tuple[Capability, ...]

    @property
    def by_name(self) -> dict[str, Capability]:
        return {capability.name: capability for capability in self.capabilities}

    @classmethod
    def load(cls, path: Path) -> CapabilityManifest:
        try:
            raw = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_pairs,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "capability manifest is unreadable") from exc
        return cls.from_json(raw)

    @classmethod
    def from_json(cls, raw: Any) -> CapabilityManifest:
        if not isinstance(raw, dict) or set(raw) != {
            "schemaVersion",
            "manifestId",
            "capabilities",
        }:
            raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "manifest fields are invalid")
        if raw["schemaVersion"] != "1.0" or not _valid_name(raw["manifestId"]):
            raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "manifest identity is invalid")
        items = raw["capabilities"]
        if not isinstance(items, list) or not 1 <= len(items) <= 256:
            raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "capability list is invalid")
        capabilities = tuple(_parse_capability(item) for item in items)
        names = [item.name for item in capabilities]
        if len(names) != len(set(names)):
            raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "capability names must be unique")
        return cls("1.0", raw["manifestId"], capabilities)

    def as_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "manifestId": self.manifest_id,
            "capabilities": [item.as_json() for item in self.capabilities],
        }


def _parse_capability(raw: Any) -> Capability:
    required = {
        "name",
        "risk",
        "defaultDecision",
        "allowedTrustLevels",
        "featureFlag",
        "rateLimitPerMinute",
        "sessionBudget",
        "expiresAt",
    }
    if not isinstance(raw, dict) or set(raw) != required or not _valid_name(raw["name"]):
        raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "capability fields are invalid")
    try:
        risk = RiskLevel(raw["risk"])
        decision = DecisionMode(raw["defaultDecision"])
    except (TypeError, ValueError) as exc:
        raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "capability enum is invalid") from exc
    trust_raw = raw["allowedTrustLevels"]
    if not isinstance(trust_raw, list) or len(trust_raw) != len(set(trust_raw)):
        raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "allowed trust levels are invalid")
    try:
        trust = frozenset(TrustLevel(item) for item in trust_raw)
    except (TypeError, ValueError) as exc:
        raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "allowed trust level is unknown") from exc
    feature = raw["featureFlag"]
    if feature is not None and feature not in FEATURE_FLAGS:
        raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "feature flag is invalid")
    rate = raw["rateLimitPerMinute"]
    budget = raw["sessionBudget"]
    if (
        isinstance(rate, bool)
        or not isinstance(rate, int)
        or not 1 <= rate <= 10_000
        or isinstance(budget, bool)
        or not isinstance(budget, int)
        or not 1 <= budget <= 1_000_000
    ):
        raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "capability limits are invalid")
    expires_at = _parse_datetime(raw["expiresAt"])
    if risk is RiskLevel.CRITICAL and decision is not DecisionMode.DENY:
        raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "critical capability must default deny")
    return Capability(
        name=raw["name"],
        risk=risk,
        default_decision=decision,
        allowed_trust_levels=trust,
        feature_flag=feature,
        rate_limit_per_minute=rate,
        session_budget=budget,
        expires_at=expires_at,
    )


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "capability expiry is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "capability expiry is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise SafetyPolicyError("E_SAFETY_MANIFEST_INVALID", "capability expiry must be UTC")
    return parsed.astimezone(UTC)


def _valid_name(value: Any) -> bool:
    return isinstance(value, str) and _NAME.fullmatch(value) is not None


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result
