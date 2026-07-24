from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

from .model import SafetyPolicyError, TrustLevel


SANITATION_POLICY_VERSION = "hina.sanitation.v1"
MAX_RAW_INPUT_BYTES = 16_384
MAX_CONTEXT_ITEMS = 32
MAX_CONTEXT_BYTES = 65_536

SOURCE_TRUST: dict[str, TrustLevel] = {
    "owner.console": TrustLevel.OWNER,
    "local.service": TrustLevel.TRUSTED_LOCAL,
    "authenticated.user": TrustLevel.AUTHENTICATED,
    "public.chat": TrustLevel.PUBLIC,
    "viewer.chat": TrustLevel.UNTRUSTED,
    "web.research": TrustLevel.UNTRUSTED,
    "game.text": TrustLevel.UNTRUSTED,
    "screen.ocr": TrustLevel.UNTRUSTED,
}

_SECRET_PATTERNS = (
    (
        "bearer_token",
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    ),
    (
        "secret_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|password|passwd|secret|token|authorization)"
            r"\s*[:=]\s*[^\s,;]{4,}"
        ),
    ),
    (
        "api_key",
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    ),
    (
        "email",
        re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}\b"),
    ),
    (
        "vn_phone",
        re.compile(r"(?<!\d)(?:\+84|0)(?:3|5|7|8|9)\d{8}(?!\d)"),
    ),
)

_INJECTION_PATTERNS = (
    (
        "instruction_override",
        re.compile(
            r"\b(?:ignore|forget|disregard)\b.{0,60}\b(?:previous|prior|all|system|developer)\b"
            r".{0,30}\b(?:instruction|instructions|message|messages|prompt)\b"
        ),
    ),
    (
        "prompt_exfiltration",
        re.compile(
            r"\b(?:reveal|show|print|repeat|expose)\b.{0,50}\b(?:system|developer|hidden)\b"
            r".{0,20}\b(?:prompt|message|instruction|reasoning)\b"
        ),
    ),
    (
        "jailbreak_request",
        re.compile(r"\b(?:jailbreak|developer mode|you are now dan|do anything now)\b"),
    ),
    (
        "instruction_override_vi",
        re.compile(
            r"\b(?:bo qua|quen|phot lo)\b.{0,60}\b(?:huong dan|chi dan|lenh|prompt)"
            r".{0,30}\b(?:truoc|he thong|developer|ban dau)\b"
        ),
    ),
    (
        "prompt_exfiltration_vi",
        re.compile(
            r"\b(?:tiet lo|hien thi|doc lai|in ra)\b.{0,50}\b(?:prompt|lenh|chi dan|tin nhan)"
            r".{0,25}\b(?:he thong|an|developer)\b"
        ),
    ),
)

_ROLE_SPOOF = re.compile(
    r"(?i)(?:<\|(?:system|developer)\|>|\[(?:system|developer)\]|#{2,}\s*(?:system|developer))"
)


@dataclass(frozen=True, slots=True)
class SanitationResult:
    sanitized_text: str
    evidence: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {
            "sanitizedText": self.sanitized_text,
            "evidence": self.evidence,
            "contextEligible": self.evidence["safeForContext"],
        }


class InputSanitizer:
    def __init__(self, *, signing_key: bytes | None = None) -> None:
        key = signing_key or secrets.token_bytes(32)
        if len(key) < 32:
            raise ValueError("sanitation signing key must contain at least 32 bytes")
        self._signing_key = key

    def status(self) -> dict[str, Any]:
        return {
            "policyVersion": SANITATION_POLICY_VERSION,
            "sourceTrust": {source: str(trust) for source, trust in SOURCE_TRUST.items()},
            "maxRawInputBytes": MAX_RAW_INPUT_BYTES,
            "maxContextItems": MAX_CONTEXT_ITEMS,
            "maxContextBytes": MAX_CONTEXT_BYTES,
        }

    def sanitize(self, raw: Any) -> SanitationResult:
        request = _parse_input_request(raw)
        original = request["text"]
        source = request["source"]
        trust = SOURCE_TRUST[source]
        normalized, unsafe_formatting = _normalize(original)
        sanitized, redactions = _redact(normalized)
        signals = _detect_injection(normalized)
        if unsafe_formatting:
            signals.append("unicode_formatting")
        signals = sorted(set(signals))
        safe_for_context = trust is TrustLevel.OWNER or not signals
        evidence: dict[str, Any] = {
            "evidenceId": str(uuid.uuid4()),
            "policyVersion": SANITATION_POLICY_VERSION,
            "source": source,
            "trustLevel": str(trust),
            "correlationId": request["correlationId"],
            "sessionId": request["sessionId"],
            "contentHash": hashlib.sha256(original.encode("utf-8")).hexdigest(),
            "sanitizedHash": hashlib.sha256(sanitized.encode("utf-8")).hexdigest(),
            "redactions": redactions,
            "signals": signals,
            "safeForContext": safe_for_context,
        }
        evidence["signature"] = self._sign(evidence)
        return SanitationResult(sanitized, evidence)

    def create_context_bundle(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict) or set(raw) != {
            "items",
            "correlationId",
            "sessionId",
        }:
            raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "context request fields are invalid")
        correlation_id = _validate_uuid(raw["correlationId"], "correlation")
        session_id = _validate_uuid(raw["sessionId"], "session")
        items = raw["items"]
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_CONTEXT_ITEMS:
            raise SafetyPolicyError("E_CONTEXT_BOUNDARY", "context item count is invalid")
        context_items: list[dict[str, Any]] = []
        total_bytes = 0
        for item in items:
            validated = self._validate_context_item(item, correlation_id, session_id)
            total_bytes += len(validated["text"].encode("utf-8"))
            if total_bytes > MAX_CONTEXT_BYTES:
                raise SafetyPolicyError("E_CONTEXT_BOUNDARY", "context byte budget exceeded")
            context_items.append(validated)
        bundle_seed = json.dumps(
            {
                "correlationId": correlation_id,
                "sessionId": session_id,
                "hashes": [item["sanitizedHash"] for item in context_items],
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return {
            "bundleId": str(uuid.uuid5(uuid.NAMESPACE_URL, hashlib.sha256(bundle_seed).hexdigest())),
            "correlationId": correlation_id,
            "sessionId": session_id,
            "itemCount": len(context_items),
            "totalBytes": total_bytes,
            "items": context_items,
        }

    def _validate_context_item(
        self,
        raw: Any,
        correlation_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict) or set(raw) != {"text", "evidence"}:
            raise SafetyPolicyError("E_CONTEXT_BOUNDARY", "context item fields are invalid")
        text = raw["text"]
        evidence = raw["evidence"]
        if not isinstance(text, str) or not isinstance(evidence, dict):
            raise SafetyPolicyError("E_CONTEXT_BOUNDARY", "context item is invalid")
        signature = evidence.get("signature")
        unsigned = {key: value for key, value in evidence.items() if key != "signature"}
        if (
            not isinstance(signature, str)
            or not hmac.compare_digest(signature, self._sign(unsigned))
        ):
            raise SafetyPolicyError("E_CONTEXT_BOUNDARY", "sanitation evidence signature is invalid")
        required = {
            "evidenceId",
            "policyVersion",
            "source",
            "trustLevel",
            "correlationId",
            "sessionId",
            "contentHash",
            "sanitizedHash",
            "redactions",
            "signals",
            "safeForContext",
            "signature",
        }
        if set(evidence) != required:
            raise SafetyPolicyError("E_CONTEXT_BOUNDARY", "sanitation evidence fields are invalid")
        if (
            evidence["policyVersion"] != SANITATION_POLICY_VERSION
            or evidence["source"] not in SOURCE_TRUST
            or evidence["trustLevel"] != str(SOURCE_TRUST[evidence["source"]])
            or evidence["correlationId"] != correlation_id
            or evidence["sessionId"] != session_id
            or evidence["sanitizedHash"] != hashlib.sha256(text.encode("utf-8")).hexdigest()
        ):
            raise SafetyPolicyError("E_CONTEXT_BOUNDARY", "sanitation evidence does not match context")
        trust = SOURCE_TRUST[evidence["source"]]
        if evidence["safeForContext"] is not True:
            raise SafetyPolicyError("E_CONTEXT_BOUNDARY", "unsafe context is quarantined")
        return {
            "source": evidence["source"],
            "trustLevel": str(trust),
            "text": text,
            "sanitizedHash": evidence["sanitizedHash"],
            "evidenceId": evidence["evidenceId"],
        }

    def _sign(self, evidence: dict[str, Any]) -> str:
        encoded = json.dumps(
            evidence,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hmac.new(self._signing_key, encoded, hashlib.sha256).hexdigest()


def _parse_input_request(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {
        "source",
        "text",
        "correlationId",
        "sessionId",
    }:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "input request fields are invalid")
    source = raw["source"]
    text = raw["text"]
    if source not in SOURCE_TRUST:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "input source is unknown")
    if not isinstance(text, str) or not text.strip():
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "input text is invalid")
    try:
        byte_length = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "input text is invalid Unicode") from exc
    if byte_length > MAX_RAW_INPUT_BYTES:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", "input text exceeds byte limit")
    return {
        "source": source,
        "text": text,
        "correlationId": _validate_uuid(raw["correlationId"], "correlation"),
        "sessionId": _validate_uuid(raw["sessionId"], "session"),
    }


def _normalize(text: str) -> tuple[str, bool]:
    normalized = unicodedata.normalize("NFKC", text)
    unsafe = False
    characters: list[str] = []
    for char in normalized:
        category = unicodedata.category(char)
        if category == "Cf" or (category.startswith("C") and char not in {"\n", "\t"}):
            unsafe = True
            characters.append(" ")
        else:
            characters.append(char)
    return "".join(characters).strip(), unsafe


def _redact(text: str) -> tuple[str, dict[str, int]]:
    result = text
    counts: dict[str, int] = {}
    for name, pattern in _SECRET_PATTERNS:
        result, count = pattern.subn(f"<redacted:{name}>", result)
        if count:
            counts[name] = count
    return result, counts


def _detect_injection(text: str) -> list[str]:
    signals: list[str] = []
    if _ROLE_SPOOF.search(text):
        signals.append("role_spoofing")
    folded = _fold_for_detection(text)
    for name, pattern in _INJECTION_PATTERNS:
        if pattern.search(folded):
            signals.append(name)
    return signals


def _fold_for_detection(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text).casefold()
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    substitutions = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})
    deobfuscated = without_marks.translate(substitutions)
    return re.sub(r"[^\w]+", " ", deobfuscated, flags=re.UNICODE).strip()


def _validate_uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise SafetyPolicyError("E_SAFETY_BAD_REQUEST", f"{field} identifier is invalid") from exc
