from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, RefResolver
from jsonschema.exceptions import ValidationError

from .generated import EVENT_SCHEMA_FILES, EVENT_TYPES, MAX_JSON_ENVELOPE_BYTES, MAX_JSON_NESTING_DEPTH


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
_MAX_INTEGER_TOKEN_DIGITS = 16


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
        text = raw.decode("utf-8")
        scan_error = _scan_json_text(text)
        if scan_error is not None:
            return ValidationResult(False, ErrorCode.E_SCHEMA_WRONG_TYPE, detail=scan_error)
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_pairs,
            parse_int=_parse_json_int_token,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        return ValidationResult(False, ErrorCode.E_SCHEMA_WRONG_TYPE, detail=str(exc))
    return validate_envelope(parsed)


def validate_envelope(value: Any) -> ValidationResult:
    try:
        semantic_error = _find_structural_string_or_depth_error(value)
        if semantic_error is not None:
            return ValidationResult(False, ErrorCode.E_SCHEMA_WRONG_TYPE, detail=semantic_error)
        normalized = _normalize_json_numbers(value)
        canonical = _dump_canonical(normalized)
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
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
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, str):
        return _normalize_surrogate_pairs(value)
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
        return {
            _normalize_surrogate_pairs(key) if isinstance(key, str) else key: _normalize_json_numbers(child)
            for key, child in value.items()
        }
    return value


def _normalize_surrogate_pairs(value: str) -> str:
    if not any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        return value
    result: list[str] = []
    index = 0
    while index < len(value):
        code = ord(value[index])
        if 0xD800 <= code <= 0xDBFF:
            if index + 1 >= len(value):
                raise ValueError("string contains an unpaired UTF-16 surrogate")
            next_code = ord(value[index + 1])
            if not 0xDC00 <= next_code <= 0xDFFF:
                raise ValueError("string contains an unpaired UTF-16 surrogate")
            result.append(chr(0x10000 + ((code - 0xD800) << 10) + (next_code - 0xDC00)))
            index += 2
            continue
        if 0xDC00 <= code <= 0xDFFF:
            raise ValueError("string contains an unpaired UTF-16 surrogate")
        result.append(value[index])
        index += 1
    return "".join(result)


def _parse_json_int_token(token: str) -> int:
    digits = token[1:] if token.startswith("-") else token
    if len(digits.lstrip("0") or "0") > _MAX_INTEGER_TOKEN_DIGITS:
        raise ValueError("integer token exceeds JavaScript-safe boundary")
    return int(token)


def _bounded_exponent(exponent_text: str, limit: int) -> int:
    negative = exponent_text.startswith("-")
    digits = exponent_text.lstrip("+-").lstrip("0")
    if not digits:
        return 0
    limit_text = str(limit)
    if len(digits) > len(limit_text) or (len(digits) == len(limit_text) and digits > limit_text):
        return -(limit + 1) if negative else limit + 1
    value = int(digits)
    return -value if negative else value


def _exact_safe_integer_token_error(token: str) -> str | None:
    unsigned = token[1:] if token.startswith("-") else token
    mantissa, separator, exponent_text = unsigned.lower().partition("e")
    integer_part, decimal_separator, fraction_part = mantissa.partition(".")
    if not decimal_separator:
        fraction_part = ""
    digits = integer_part + fraction_part
    significant = digits.lstrip("0")
    if not significant:
        return None

    exponent = _bounded_exponent(
        exponent_text if separator else "0",
        len(fraction_part) + _MAX_INTEGER_TOKEN_DIGITS + 1,
    )
    scale = exponent - len(fraction_part)
    if scale < 0:
        fractional_digits = -scale
        if fractional_digits >= len(digits):
            return "number token is not an exact integer"
        if any(digit != "0" for digit in digits[-fractional_digits:]):
            return "number token is not an exact integer"
        exact_digits = digits[:-fractional_digits].lstrip("0") or "0"
    else:
        if len(significant) + scale > _MAX_INTEGER_TOKEN_DIGITS:
            return "number token exceeds JavaScript-safe boundary"
        exact_digits = significant + ("0" * scale)

    if len(exact_digits) > _MAX_INTEGER_TOKEN_DIGITS or int(exact_digits) > _MAX_JS_SAFE_INTEGER:
        return "number token exceeds JavaScript-safe boundary"
    return None


def _reject_duplicate_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object member: {key}")
        result[key] = value
    return result


def _find_structural_string_or_depth_error(value: Any) -> str | None:
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > MAX_JSON_NESTING_DEPTH:
            return f"JSON nesting exceeds {MAX_JSON_NESTING_DEPTH}"
        if isinstance(item, str):
            if _has_unpaired_surrogate(item):
                return "string contains an unpaired UTF-16 surrogate"
            continue
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    return "JSON object member names must be strings"
                if _has_unpaired_surrogate(key):
                    return "object member name contains an unpaired UTF-16 surrogate"
                stack.append((child, depth + 1))
        elif isinstance(item, (list, tuple)):
            for child in item:
                stack.append((child, depth + 1))
    return None


def _has_unpaired_surrogate(value: str) -> bool:
    index = 0
    while index < len(value):
        code = ord(value[index])
        if 0xD800 <= code <= 0xDBFF:
            if index + 1 >= len(value):
                return True
            next_code = ord(value[index + 1])
            if not 0xDC00 <= next_code <= 0xDFFF:
                return True
            index += 2
            continue
        if 0xDC00 <= code <= 0xDFFF:
            return True
        index += 1
    return False


def _scan_json_text(text: str) -> str | None:
    index = 0

    def skip_whitespace() -> None:
        nonlocal index
        while index < len(text) and text[index] in " \t\r\n":
            index += 1

    def parse_value(depth: int) -> str | None:
        nonlocal index
        if depth > MAX_JSON_NESTING_DEPTH:
            return f"JSON nesting exceeds {MAX_JSON_NESTING_DEPTH}"
        skip_whitespace()
        if index >= len(text):
            return "malformed JSON"
        char = text[index]
        if char == "{":
            return parse_object(depth)
        if char == "[":
            return parse_array(depth)
        if char == '"':
            parsed_ok, parsed_value = parse_string()
            return None if parsed_ok else parsed_value
        if char == "-" or "0" <= char <= "9":
            return parse_number()
        for literal in ("true", "false", "null"):
            if text.startswith(literal, index):
                index += len(literal)
                return None
        return "malformed JSON"

    def parse_object(depth: int) -> str | None:
        nonlocal index
        index += 1
        keys: set[str] = set()
        skip_whitespace()
        if index < len(text) and text[index] == "}":
            index += 1
            return None
        while index < len(text):
            skip_whitespace()
            key_ok, key = parse_string()
            if not key_ok:
                return key
            if _has_unpaired_surrogate(key):
                return "object member name contains an unpaired UTF-16 surrogate"
            if key in keys:
                return f"duplicate JSON object member: {key}"
            keys.add(key)
            skip_whitespace()
            if index >= len(text) or text[index] != ":":
                return "malformed JSON"
            index += 1
            value_error = parse_value(depth + 1)
            if value_error is not None:
                return value_error
            skip_whitespace()
            if index < len(text) and text[index] == "}":
                index += 1
                return None
            if index >= len(text) or text[index] != ",":
                return "malformed JSON"
            index += 1
        return "malformed JSON"

    def parse_array(depth: int) -> str | None:
        nonlocal index
        index += 1
        skip_whitespace()
        if index < len(text) and text[index] == "]":
            index += 1
            return None
        while index < len(text):
            value_error = parse_value(depth + 1)
            if value_error is not None:
                return value_error
            skip_whitespace()
            if index < len(text) and text[index] == "]":
                index += 1
                return None
            if index >= len(text) or text[index] != ",":
                return "malformed JSON"
            index += 1
        return "malformed JSON"

    def parse_string() -> tuple[bool, str]:
        nonlocal index
        start = index
        if index >= len(text) or text[index] != '"':
            return False, "malformed JSON"
        index += 1
        while index < len(text):
            char = text[index]
            if char == '"':
                index += 1
                try:
                    parsed = json.loads(text[start:index])
                except json.JSONDecodeError:
                    return False, "malformed JSON"
                return (True, parsed) if isinstance(parsed, str) else (False, "malformed JSON")
            if char == "\\":
                index += 1
                if index >= len(text):
                    return False, "malformed JSON"
                if text[index] == "u":
                    hex_digits = text[index + 1 : index + 5]
                    if len(hex_digits) != 4 or any(digit not in "0123456789abcdefABCDEF" for digit in hex_digits):
                        return False, "malformed JSON"
                    index += 5
                elif text[index] in '"\\/bfnrt':
                    index += 1
                else:
                    return False, "malformed JSON"
            else:
                if ord(char) <= 0x1F:
                    return False, "malformed JSON"
                index += 1
        return False, "malformed JSON"

    def parse_number() -> str | None:
        nonlocal index
        start = index
        if text[index] == "-":
            index += 1
        if index < len(text) and text[index] == "0":
            index += 1
        elif index < len(text) and "1" <= text[index] <= "9":
            while index < len(text) and "0" <= text[index] <= "9":
                index += 1
        else:
            return "malformed JSON"
        if index < len(text) and text[index] == ".":
            index += 1
            if index >= len(text) or not "0" <= text[index] <= "9":
                return "malformed JSON"
            while index < len(text) and "0" <= text[index] <= "9":
                index += 1
        if index < len(text) and text[index] in "eE":
            index += 1
            if index < len(text) and text[index] in "+-":
                index += 1
            if index >= len(text) or not "0" <= text[index] <= "9":
                return "malformed JSON"
            while index < len(text) and "0" <= text[index] <= "9":
                index += 1
        return _exact_safe_integer_token_error(text[start:index])

    error = parse_value(1)
    if error is not None:
        return error
    skip_whitespace()
    return None if index == len(text) else "malformed JSON"


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
