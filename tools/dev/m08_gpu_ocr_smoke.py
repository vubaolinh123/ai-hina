"""Run an explicit, no-persistence Vietnamese GPU OCR smoke for M08-S3.

The script renders its test image entirely in memory, sends PNG bytes once to
the real local provider, prints bounded JSON evidence, and always unloads the
model.  It deliberately reports the broad Vietnamese-text CER as a metric; a
functional GPU smoke is not mistaken for the later quality-promotion gate.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from io import BytesIO
from pathlib import Path
from unicodedata import normalize


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers" / "perception" / "src"))

from hina_perception import OcrConfig, RapidOcrProvider  # noqa: E402


SHORT_TEXT = "Hina đang quan sát màn hình"
LONG_TEXT = "Xin chào! Đây là phép thử OCR tiếng Việt. Trạng thái: Sẵn sàng GPU CUDA."


def _levenshtein(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, 1):
        current = [left_index]
        for right_index, right_char in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _cer(expected: str, actual: str | None) -> float:
    normalized_expected = normalize("NFC", expected)
    normalized_actual = normalize("NFC", actual or "")
    return round(
        100 * _levenshtein(normalized_expected, normalized_actual) / max(1, len(normalized_expected)),
        3,
    )


def _image_bytes(lines: list[str]) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    font_path = Path(r"C:\Windows\Fonts\arial.ttf")
    font = ImageFont.truetype(str(font_path), 48)
    image = Image.new("RGB", (1400, 360), "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((72, 50 + index * 120), line, font=font, fill="black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def _run() -> dict[str, object]:
    import torch

    provider = RapidOcrProvider(OcrConfig.from_env(root=ROOT))
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    try:
        short = await provider.recognize(_image_bytes([SHORT_TEXT]))
        long = await provider.recognize(_image_bytes([LONG_TEXT]))
        elapsed = round((time.perf_counter() - started) * 1_000, 3)
        short_cer = _cer(SHORT_TEXT, short.get("text"))
        long_cer = _cer(LONG_TEXT, long.get("text"))
        status = await provider.status()
        if status.get("effectiveDevice") != "cuda:0":
            raise RuntimeError("OCR smoke did not execute on cuda:0")
        return {
            "schemaVersion": "1.0",
            "provider": status.get("provider"),
            "model": status.get("model"),
            "engine": status.get("engine"),
            "effectiveDevice": status.get("effectiveDevice"),
            "shortText": short.get("text"),
            "longText": long.get("text"),
            "shortVietnameseUiCerPercent": short_cer,
            "longVietnameseUiCerPercent": long_cer,
            "clearUiQualityGatePassed": short_cer <= 5.0 and long_cer <= 5.0,
            "processingMilliseconds": elapsed,
            "peakAllocatedMiB": round(torch.cuda.max_memory_allocated() / (1024 * 1024), 1),
            "peakReservedMiB": round(torch.cuda.max_memory_reserved() / (1024 * 1024), 1),
            "snapshotPixelsPersisted": False,
            "ocrTextPersisted": False,
        }
    finally:
        await provider.close()


if __name__ == "__main__":
    # PowerShell sessions on older Windows images can still expose a legacy
    # code page.  Keep the Vietnamese smoke evidence readable in the launcher
    # log instead of failing after successful inference during JSON printing.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(asyncio.run(_run()), ensure_ascii=False))
