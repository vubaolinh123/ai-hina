from __future__ import annotations

import json
import re
import threading
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
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(error, PrimitiveError):
            code = error.code
            detail = error.detail
        else:
            code = RuntimeErrorCode.OPERATION_FAILED
            detail = str(error)[:512] or type(error).__name__
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": "error",
            "component": component,
            "operation": operation,
            "errorCode": str(code),
            "message": _redact(detail),
            "correlationId": correlation_id,
            "exceptionType": type(error).__name__,
            "buildCommit": self.build_commit,
            "context": _redact(context or {}),
        }
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded + "\n")
        return record
