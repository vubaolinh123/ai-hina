"""Hina AI contract validation runtime."""

from .generated import (
    CATALOG_DIGEST,
    CATALOG_VERSION,
    EVENT_TYPES,
    HINA_CONTRACT_ECHO_V1,
    MAX_JSON_ENVELOPE_BYTES,
    MAX_JSON_NESTING_DEPTH,
)
from .validation import (
    ErrorCode,
    ValidationResult,
    canonicalize_envelope,
    validate_envelope,
    validate_envelope_bytes,
)

__all__ = [
    "CATALOG_DIGEST",
    "CATALOG_VERSION",
    "EVENT_TYPES",
    "HINA_CONTRACT_ECHO_V1",
    "MAX_JSON_ENVELOPE_BYTES",
    "MAX_JSON_NESTING_DEPTH",
    "ErrorCode",
    "ValidationResult",
    "canonicalize_envelope",
    "validate_envelope",
    "validate_envelope_bytes",
]
