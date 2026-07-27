from __future__ import annotations


class PerceptionError(Exception):
    """Typed perception failure with a stable machine-readable code."""

    def __init__(self, code: str, detail: str, *, retryable: bool = False) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail[:256]
        self.retryable = retryable
        self.reported = False
