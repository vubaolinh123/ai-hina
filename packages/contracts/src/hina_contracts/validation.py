from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, RefResolver
from jsonschema.exceptions import ValidationError

from .generated import EVENT_SCHEMA_FILES, EVENT_TYPES, MAX_JSON_ENVELOPE_BYTES


class ErrorCode(StrEnum):
    OK = "OK"
    E_SCHEMA_MISSING_REQUIRED = "E_SCHEMA_MISSING_REQUIRED"
    E_SCHEMA_WRONG_TYPE = "E_SCHEMA_WRONG_TYPE"
    E_SCHEMA_UNKNOWN_EVENT = "E_SCHEMA_UNKNOWN_EVENT"
    E_SCHEMA_UNKNOWN_FIELD = "E_SCHEMA_UNKNOWN_FIELD"
    E_SCHEMA_OVERSIZE = "E_SCHEMA_OVERSIZE"
    E_SCHEMA_INVALID_ID = "E_SCHEMA_INVALID_ID"
    E_SCHEMA_INLINE_BASE64 = "E_SCHEMA_INLINE_BASE64"
    E_ROUNDTRIP_UNICODE_LOSS = "E_ROUNDTRIP_UNICODE_LOSS"
    E_GEN_DRIFT = "E_GEN_DRIFT"
    E_FUZZ_ACCEPTED_INVALID = "E_FUZZ_ACCEPTED_INVALID"
    E_FUZZ_REJECTED_VALID = "E_FUZZ_REJECTED_VALID"
    E_FUZZ_RUNTIME_CRASH = "E_FUZZ_RUNTIME_CRASH"
    E_XLANG_ROUNDTRIP_MISMATCH = "E_XLANG_ROUNDTRIP_MISMATCH"
    E_COMPAT_N_MINUS_1_UNSPECIFIED = "E_COMPAT_N_MINUS_1_UNSPECIFIED"
    E_FLAKY_SUITE = "E_FLAKY_SUITE"
    E_GATE_20_RUN_FAIL = "E_GATE_20_RUN_FAIL"
    E_PERF_P95_BUDGET = "E_PERF_P95_BUDGET"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    code: ErrorCode
    canonical_json: str | None = None
    detail: str | None = None


_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_ROOT = _ROOT / "schemas" / "v1"
_INLINE_KEYS = {"base64", "bytes", "data", "dataUri", "file", "path", "raw", "uri", "url"}
_MIN_JS_SAFE_INTEGER = -9_007_199_254_740_991
_MAX_JS_SAFE_INTEGER = 9_007_199_254_740_991


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_store() -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for path in sorted(_SCHEMA_ROOT.rglob("*.schema.json")):
        schema = _load_json(path)
        schemas[str(path.as_uri())] = schema
        if "$id" in schema:
            schemas[str(schema["$id"])] = schema
    return schemas


def _build_validators() -> dict[str, Draft202012Validator]:
    store = _schema_store()
    resolver = RefResolver(base_uri=(_SCHEMA_ROOT / "events").as_uri() + "/", referrer=None, store=store)
    validators: dict[str, Draft202012Validator] = {}
    for event_type, schema_file in EVENT_SCHEMA_FILES.items():
        schema = _load_json(_ROOT / schema_file)
        Draft202012Validator.check_schema(schema)
        validators[event_type] = Draft202012Validator(schema, resolver=resolver)
    return validators


_VALIDATORS = _build_validators()


def canonicalize_envelope(value: Any) -> str:
    return _dump_canonical(_normalize_json_numbers(value))


def validate_envelope_bytes(raw: bytes) -> ValidationResult:
    if len(raw) > MAX_JSON_ENVELOPE_BYTES:
        return ValidationResult(False, ErrorCode.E_SCHEMA_OVERSIZE, detail="raw JSON exceeds limit")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return ValidationResult(False, ErrorCode.E_SCHEMA_WRONG_TYPE, detail=str(exc))
    return validate_envelope(parsed)


def validate_envelope(value: Any) -> ValidationResult:
    try:
        normalized = _normalize_json_numbers(value)
        canonical = _dump_canonical(normalized)
    except (TypeError, ValueError) as exc:
        return ValidationResult(False, ErrorCode.E_SCHEMA_WRONG_TYPE, detail=str(exc))
    if len(canonical.encode("utf-8")) > MAX_JSON_ENVELOPE_BYTES:
        return ValidationResult(False, ErrorCode.E_SCHEMA_OVERSIZE, detail="canonical JSON exceeds limit")
    if not isinstance(normalized, dict):
        return ValidationResult(False, ErrorCode.E_SCHEMA_WRONG_TYPE, detail="envelope must be object")
    inline_path = _find_inline_media(normalized)
    if inline_path is not None:
        return ValidationResult(False, ErrorCode.E_SCHEMA_INLINE_BASE64, detail=inline_path)
    metadata_number_path = _find_unsafe_metadata_number(normalized)
    if metadata_number_path is not None:
        return ValidationResult(False, ErrorCode.E_SCHEMA_WRONG_TYPE, detail=metadata_number_path)
    event_type = normalized.get("type")
    if event_type is None:
        return _schema_error(ValidationError("type is required", validator="required"))
    if not isinstance(event_type, str):
        return ValidationResult(False, ErrorCode.E_SCHEMA_WRONG_TYPE, detail="type must be string")
    if event_type not in EVENT_TYPES:
        return ValidationResult(False, ErrorCode.E_SCHEMA_UNKNOWN_EVENT, detail=event_type)
    errors = sorted(_VALIDATORS[event_type].iter_errors(normalized), key=lambda err: list(err.absolute_path))
    if errors:
        return _schema_error(errors[0])
    return ValidationResult(True, ErrorCode.OK, canonical_json=canonical)


def _dump_canonical(value: Any) -> str:
    return json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _normalize_json_numbers(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str) or isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("number must be finite")
        if not value.is_integer() or value < _MIN_JS_SAFE_INTEGER or value > _MAX_JS_SAFE_INTEGER:
            raise TypeError("number must be a JavaScript-safe integer")
        return int(value)
    if isinstance(value, list):
        return [_normalize_json_numbers(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_json_numbers(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_json_numbers(child) for key, child in value.items()}
    return value


def _find_inline_media(value: dict[str, Any]) -> str | None:
    media = value.get("media")
    if not isinstance(media, list):
        return None
    for index, item in enumerate(media):
        if not isinstance(item, dict):
            continue
        for key, child in item.items():
            child_path = f"$.media[{index}].{key}"
            if key in _INLINE_KEYS:
                return child_path
            if isinstance(child, str) and child.lower().startswith("data:"):
                return child_path
    return None


def _find_unsafe_metadata_number(value: dict[str, Any]) -> str | None:
    payload = value.get("payload")
    if not isinstance(payload, dict):
        return None
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return None
    for key, child in metadata.items():
        child_path = f"$.payload.metadata.{key}"
        if isinstance(child, bool) or child is None or isinstance(child, str):
            continue
        if isinstance(child, int):
            if _MIN_JS_SAFE_INTEGER <= child <= _MAX_JS_SAFE_INTEGER:
                continue
            return child_path
        if isinstance(child, float):
            return child_path
    return None


def _schema_error(error: ValidationError) -> ValidationResult:
    validator = str(error.validator)
    path = ".".join(str(part) for part in error.absolute_path)
    if validator == "required":
        return ValidationResult(False, ErrorCode.E_SCHEMA_MISSING_REQUIRED, detail=error.message)
    if validator == "additionalProperties":
        return ValidationResult(False, ErrorCode.E_SCHEMA_UNKNOWN_FIELD, detail=error.message)
    if _is_identifier_error(error, path):
        return ValidationResult(False, ErrorCode.E_SCHEMA_INVALID_ID, detail=error.message)
    if validator in {"type", "enum", "const", "anyOf"}:
        return ValidationResult(False, ErrorCode.E_SCHEMA_WRONG_TYPE, detail=error.message)
    return ValidationResult(False, ErrorCode.E_SCHEMA_WRONG_TYPE, detail=error.message)


def _is_identifier_error(error: ValidationError, path: str) -> bool:
    if error.validator == "pattern" and any(token in path for token in ("Id", "id", "occurredAt", "expiresAt", "deadline")):
        return True
    if error.validator == "type" and path in {"sessionId", "turnId"}:
        return True
    if error.validator in {"if", "then"}:
        return True
    return any(_is_identifier_error(child, path) for child in error.context)
