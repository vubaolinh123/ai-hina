from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .primitives import PrimitiveError, RuntimeErrorCode


_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|cookie|password|secret|token)", re.IGNORECASE)
_SECRET_TEXT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|cookie|password|secret|token)\s*[:=]\s*(?:Bearer\s+)?[^\s,;]+"
)
_BEARER_TEXT = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


def _redact(value: Any, key: str | None = None) -> Any:
    if key is not None and _SECRET_KEY.search(key):
        return "<redacted>"
    if isinstance(value, str):
        redacted = _SECRET_TEXT.sub(lambda match: f"{match.group(1)}=<redacted>", value)
        return _BEARER_TEXT.sub("Bearer <redacted>", redacted)
    if isinstance(value, dict):
        return {str(child_key): _redact(child, str(child_key)) for child_key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(child) for child in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return repr(value)


def redact_for_log(value: Any, key: str | None = None) -> Any:
    return _redact(value, key)


def _safe_uuid(value: str | None, *, fallback: str | None = None) -> str | None:
    if value is None:
        return fallback
    try:
        return str(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError):
        return fallback


class JsonlErrorLogger:
    def __init__(self, path: Path, *, build_commit: str = "development") -> None:
        self.path = path
        self.build_commit = build_commit
        self._lock = threading.Lock()

    def log_error(
        self,
        error: PrimitiveError | Exception,
        *,
        component: str,
        operation: str,
        correlation_id: str,
        session_id: str | None = None,
        turn_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(error, PrimitiveError):
            code = error.code
            detail = error.detail
        else:
            code = RuntimeErrorCode.OPERATION_FAILED
            detail = str(error)[:512] or type(error).__name__
        try:
            safe_message = _redact(detail)
            safe_context = _redact(context or {})
        except Exception:
            safe_message = "error detail redaction failed"
            safe_context = {"redaction": "<unavailable>"}
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": "error",
            "component": component,
            "operation": operation,
            "errorCode": str(code),
            "message": safe_message,
            "correlationId": _safe_uuid(
                correlation_id,
                fallback="00000000-0000-0000-0000-000000000000",
            ),
            "exceptionType": type(error).__name__,
            "buildCommit": self.build_commit,
            "contractVersion": "1.x",
            "runtimeProfile": "local",
            "context": safe_context,
        }
        safe_session_id = _safe_uuid(session_id)
        safe_turn_id = _safe_uuid(turn_id)
        if safe_session_id is not None:
            record["sessionId"] = safe_session_id
        if safe_turn_id is not None:
            record["turnId"] = safe_turn_id
        try:
            encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(encoded + "\n")
        except Exception:
            record["loggingFailed"] = True
        return record
