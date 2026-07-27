from __future__ import annotations

from typing import Any, Protocol


class OcrProvider(Protocol):
    """Contract for M08-S2+ OCR providers.

    M08-S1 ships the interface only. No OCR dependency has passed OSS/license
    review yet, so the runtime reports an honest ``contract-ready`` state
    instead of fabricating recognition output.
    """

    async def status(self) -> dict[str, Any]: ...

    async def recognize(self, summary: Any) -> dict[str, Any]: ...

    async def close(self) -> None: ...


def unconfigured_ocr_status() -> dict[str, Any]:
    return {
        "provider": "none",
        "state": "contract-ready",
        "available": False,
        "candidates": ["paddleocr", "rapidocr-onnxruntime"],
        "note": (
            "OCR ships in a later M08 slice after the dependency passes "
            "OSS/license review; observations carry capture evidence only."
        ),
    }
