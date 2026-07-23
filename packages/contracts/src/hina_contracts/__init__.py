"""Hina AI contract validation runtime."""

from .generated import (
    CATALOG_DIGEST,
    CATALOG_VERSION,
    EVENT_TYPES,
    HINA_CONTRACT_ECHO_V1,
    MAX_JSON_ENVELOPE_BYTES,
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
    "ErrorCode",
    "ValidationResult",
    "canonicalize_envelope",
    "validate_envelope",
    "validate_envelope_bytes",
]
