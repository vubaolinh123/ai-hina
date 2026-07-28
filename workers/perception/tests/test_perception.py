from __future__ import annotations

import asyncio
import hashlib
import struct
import sys
import unittest
import zlib
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hina_perception import (  # noqa: E402
    FreshnessLedger,
    PerceptionConfig,
    PerceptionError,
    PerceptionService,
    SnapshotRateLimiter,
    dhash64,
    hamming_distance,
    summarize_png,
)


def _chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def encode_png(
    pixels: list[list[tuple[int, int, int]]],
    *,
    color_type: int = 2,
    filter_type: int = 0,
    bit_depth: int = 8,
    interlace: int = 0,
) -> bytes:
    """Minimal deterministic PNG encoder for test fixtures only."""

    height = len(pixels)
    width = len(pixels[0])
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    raw = bytearray()
    previous = bytearray(width * channels)
    for row in pixels:
        line = bytearray()
        for red, green, blue in row:
            if color_type == 0:
                line.append((77 * red + 150 * green + 29 * blue) >> 8)
            elif color_type == 2:
                line.extend((red, green, blue))
            elif color_type == 4:
                line.extend(((77 * red + 150 * green + 29 * blue) >> 8, 255))
            else:
                line.extend((red, green, blue, 255))
        filtered = bytearray(line)
        if filter_type == 1:
            for index in range(len(line) - 1, channels - 1, -1):
                filtered[index] = (line[index] - line[index - channels]) & 0xFF
        elif filter_type == 2:
            for index in range(len(line)):
                filtered[index] = (line[index] - previous[index]) & 0xFF
        elif filter_type == 4:
            for index in range(len(line)):
                left = line[index - channels] if index >= channels else 0
                up = previous[index]
                up_left = previous[index - channels] if index >= channels else 0
                estimate = left + up - up_left
                deltas = (abs(estimate - left), abs(estimate - up), abs(estimate - up_left))
                if deltas[0] <= deltas[1] and deltas[0] <= deltas[2]:
                    predictor = left
                elif deltas[1] <= deltas[2]:
                    predictor = up
                else:
                    predictor = up_left
                filtered[index] = (line[index] - predictor) & 0xFF
        raw.append(filter_type)
        raw.extend(filtered)
        previous = line
    header = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, interlace)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw)))
        + _chunk(b"IEND", b"")
    )


def gradient(width: int = 32, height: int = 32, *, invert: bool = False) -> list[list[tuple[int, int, int]]]:
    rows = []
    for row in range(height):
        line = []
        for column in range(width):
            value = (column * 255) // max(1, width - 1)
            if invert:
                value = 255 - value
            line.append((value, value, value))
        rows.append(line)
    return rows


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.value = start

    def advance(self, seconds: float) -> None:
        self.value += seconds

    def __call__(self) -> float:
        return self.value


class ConfigTests(unittest.TestCase):
    def test_defaults_are_valid_and_capture_stays_off(self) -> None:
        config = PerceptionConfig()
        self.assertEqual(config.ttl_seconds, 15.0)
        self.assertFalse(config.capture_default_enabled)
        self.assertFalse(config.snapshot_persistence)

    def test_ttl_above_screen_maximum_is_rejected(self) -> None:
        with self.assertRaises(PerceptionError) as caught:
            PerceptionConfig(ttl_seconds=15.1)
        self.assertEqual(caught.exception.code, "E_PERCEPTION_CONFIG")

    def test_ttl_below_one_second_is_rejected(self) -> None:
        with self.assertRaises(PerceptionError):
            PerceptionConfig(ttl_seconds=0.5)

    def test_persistence_cannot_be_enabled(self) -> None:
        with self.assertRaises(PerceptionError):
            PerceptionConfig(snapshot_persistence=True)

    def test_auto_capture_cannot_be_enabled(self) -> None:
        with self.assertRaises(PerceptionError):
            PerceptionConfig(capture_default_enabled=True)

    def test_from_env_reads_overrides(self) -> None:
        config = PerceptionConfig.from_env(
            {
                "HINA_PERCEPTION_TTL_SECONDS": "5",
                "HINA_PERCEPTION_RATE_PER_MINUTE": "3",
            }
        )
        self.assertEqual(config.ttl_seconds, 5.0)
        self.assertEqual(config.rate_limit_per_minute, 3)

    def test_from_env_rejects_non_numeric(self) -> None:
        with self.assertRaises(PerceptionError):
            PerceptionConfig.from_env({"HINA_PERCEPTION_TTL_SECONDS": "abc"})


class PngTests(unittest.TestCase):
    def test_summary_matches_across_color_types_and_filters(self) -> None:
        base = None
        for color_type in (0, 2, 4, 6):
            for filter_type in (0, 1, 2, 4):
                encoded = encode_png(
                    gradient(),
                    color_type=color_type,
                    filter_type=filter_type,
                )
                summary = summarize_png(
                    encoded, max_bytes=1_000_000, max_dimension=4_096, min_dimension=16
                )
                self.assertEqual((summary.width, summary.height), (32, 32))
                if base is None:
                    base = summary
                else:
                    self.assertEqual(summary.luma_grid, base.luma_grid)
                    self.assertEqual(summary.mean_luma, base.mean_luma)

    def test_rejects_non_png_and_truncated_and_bad_crc(self) -> None:
        encoded = encode_png(gradient())
        corrupted = bytearray(encoded)
        corrupted[-6] ^= 0xFF
        for payload in (b"", b"not a png", encoded[:40], bytes(corrupted)):
            with self.assertRaises(PerceptionError) as caught:
                summarize_png(payload, max_bytes=1_000_000, max_dimension=4_096, min_dimension=16)
            self.assertIn("SNAPSHOT", caught.exception.code)

    def test_rejects_oversized_body(self) -> None:
        encoded = encode_png(gradient())
        with self.assertRaises(PerceptionError) as caught:
            summarize_png(encoded, max_bytes=64, max_dimension=4_096, min_dimension=16)
        self.assertEqual(caught.exception.code, "E_PERCEPTION_SNAPSHOT_TOO_LARGE")

    def test_rejects_undersized_dimensions(self) -> None:
        encoded = encode_png(gradient(8, 8))
        with self.assertRaises(PerceptionError):
            summarize_png(encoded, max_bytes=1_000_000, max_dimension=4_096, min_dimension=16)

    def test_rejects_sixteen_bit_and_interlaced(self) -> None:
        for encoded in (
            encode_png(gradient(), bit_depth=16),
            encode_png(gradient(), interlace=1),
        ):
            with self.assertRaises(PerceptionError):
                summarize_png(encoded, max_bytes=1_000_000, max_dimension=4_096, min_dimension=16)


class DedupTests(unittest.TestCase):
    def test_identical_images_have_zero_distance(self) -> None:
        first = summarize_png(
            encode_png(gradient()), max_bytes=1_000_000, max_dimension=4_096, min_dimension=16
        )
        second = summarize_png(
            encode_png(gradient()), max_bytes=1_000_000, max_dimension=4_096, min_dimension=16
        )
        self.assertEqual(hamming_distance(dhash64(first), dhash64(second)), 0)

    def test_inverted_gradient_is_far_away(self) -> None:
        first = summarize_png(
            encode_png(gradient()), max_bytes=1_000_000, max_dimension=4_096, min_dimension=16
        )
        second = summarize_png(
            encode_png(gradient(invert=True)),
            max_bytes=1_000_000,
            max_dimension=4_096,
            min_dimension=16,
        )
        self.assertGreater(hamming_distance(dhash64(first), dhash64(second)), 16)

    def test_rate_limiter_uses_monotonic_window(self) -> None:
        clock = FakeClock()
        limiter = SnapshotRateLimiter(2, clock=clock)
        self.assertTrue(limiter.try_acquire())
        self.assertTrue(limiter.try_acquire())
        self.assertFalse(limiter.try_acquire())
        clock.advance(59.9)
        self.assertFalse(limiter.try_acquire())
        clock.advance(0.2)
        self.assertTrue(limiter.try_acquire())


class LedgerTests(unittest.TestCase):
    def test_ttl_boundary_t_minus_t_and_t_plus(self) -> None:
        clock = FakeClock()
        ledger = FreshnessLedger(ttl_seconds=15.0, capacity=4, clock=clock)
        ledger.add("obs-1", {"source": "owner.console"}, dhash=1)

        clock.advance(15.0 - 0.001)
        self.assertEqual(len(ledger.fresh()), 1)

        clock.advance(0.001)
        self.assertEqual(ledger.fresh(), [])
        with self.assertRaises(PerceptionError) as caught:
            ledger.get_fresh("obs-1")
        self.assertEqual(caught.exception.code, "E_PERCEPTION_EXPIRED")

        ledger.add("obs-2", {"source": "owner.console"}, dhash=2)
        clock.advance(15.001)
        self.assertEqual(ledger.fresh(), [])
        self.assertEqual(ledger.counts()["expiredTotal"], 2)

    def test_records_carry_ttl_schema_fields(self) -> None:
        ledger = FreshnessLedger(ttl_seconds=15.0, capacity=4, clock=FakeClock())
        record = ledger.add("obs-1", {"source": "owner.console"}, dhash=1)
        self.assertEqual(record["kind"], "screen.snapshot")
        self.assertEqual(record["trustLevel"], "untrusted")
        self.assertEqual(record["ttlSeconds"], 15.0)
        self.assertEqual(record["expiryClock"], "monotonic-elapsed")
        self.assertIn("capturedAt", record)
        self.assertIn("expiresAt", record)

    def test_capacity_is_bounded(self) -> None:
        ledger = FreshnessLedger(ttl_seconds=15.0, capacity=2, clock=FakeClock())
        for index in range(4):
            ledger.add(f"obs-{index}", {"source": "owner.console"}, dhash=index)
        self.assertEqual(len(ledger.fresh()), 2)
        with self.assertRaises(PerceptionError):
            ledger.get_fresh("obs-0")


class _RecordingEvaluate:
    def __init__(self, decision: str = "allow", *, raise_error: bool = False) -> None:
        self.decision = decision
        self.raise_error = raise_error
        self.calls: list[dict[str, object]] = []

    def __call__(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(payload)
        if self.raise_error:
            raise RuntimeError("policy backend crashed")
        return {
            "decision": self.decision,
            "reasonCode": "manifest_allowed" if self.decision == "allow" else "owner_confirmation_required",
            "stateRevision": 7,
        }


class _FakeOcrProvider:
    def __init__(self, *, result=None, error: Exception | None = None) -> None:
        self.result = result or {
            "provider": "rapidocr",
            "model": "PP-OCRv6-small",
            "engine": "torch",
            "effectiveDevice": "cuda:0",
            "state": "ready",
            "text": "Hina đang quan sát",
            "lineCount": 1,
            "meanConfidence": 0.98,
            "lines": [
                {
                    "text": "Hina đang quan sát",
                    "confidence": 0.98,
                    "box": [0.1, 0.2, 0.9, 0.2, 0.9, 0.3, 0.1, 0.3],
                }
            ],
        }
        self.error = error
        self.calls: list[bytes] = []
        self.closed = False

    async def status(self) -> dict[str, object]:
        return {
            "provider": "rapidocr",
            "state": "ready",
            "available": True,
            "cpuFallback": False,
        }

    async def recognize(self, encoded_png: bytes) -> dict[str, object]:
        self.calls.append(encoded_png)
        if self.error is not None:
            raise self.error
        return self.result

    async def unload(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


CORRELATION = "5d1c0dd2-8a53-4a30-9c5a-6f9df5a3f6ba"


def _service(
    evaluate: _RecordingEvaluate,
    *,
    clock: FakeClock | None = None,
    config: PerceptionConfig | None = None,
    on_error=None,
    vision_analyze=None,
    ocr_provider=None,
) -> PerceptionService:
    return PerceptionService(
        config or PerceptionConfig(),
        safety_evaluate=evaluate,
        vision_analyze=vision_analyze,
        ocr_provider=ocr_provider,
        on_error=on_error,
        clock=clock or FakeClock(),
    )


class ServiceTests(unittest.TestCase):
    def test_allowed_snapshot_produces_untrusted_ttl_observation(self) -> None:
        evaluate = _RecordingEvaluate("allow")
        service = _service(evaluate)
        encoded = encode_png(gradient())
        result = asyncio.run(
            service.ingest_snapshot(
                encoded,
                correlation_id=CORRELATION,
                session_id=None,
                source="owner.console",
                label="Cửa sổ trò chơi\x00\x1f",
            )
        )
        self.assertEqual(result["status"], "observed")
        observation = result["observation"]
        self.assertEqual(observation["trustLevel"], "untrusted")
        self.assertEqual(observation["kind"], "screen.snapshot")
        self.assertEqual(observation["ttlSeconds"], 15.0)
        self.assertEqual(observation["label"], "Cửa sổ trò chơi")
        self.assertEqual(
            observation["evidence"]["sha256"], hashlib.sha256(encoded).hexdigest()
        )
        self.assertEqual(observation["ocr"]["state"], "not-requested")
        self.assertEqual(observation["ocr"]["provider"], "none")
        self.assertFalse(observation["ocr"]["decisionSupportEligible"])
        self.assertEqual(observation["vision"]["state"], "not-requested")
        flattened = str(observation)
        self.assertNotIn("IDAT", flattened)
        self.assertLess(len(flattened), 4_096)
        self.assertEqual(evaluate.calls[0]["capability"], "perception.observe")
        self.assertTrue(evaluate.calls[0]["consume"])

    def test_ask_requires_owner_confirmation(self) -> None:
        evaluate = _RecordingEvaluate("ask")
        service = _service(evaluate)
        encoded = encode_png(gradient())
        with self.assertRaises(PerceptionError) as caught:
            asyncio.run(
                service.ingest_snapshot(
                    encoded,
                    correlation_id=CORRELATION,
                    session_id=None,
                    source="owner.console",
                )
            )
        self.assertEqual(caught.exception.code, "E_PERCEPTION_CONFIRMATION")

        confirmed = asyncio.run(
            service.ingest_snapshot(
                encoded,
                correlation_id=CORRELATION,
                session_id=None,
                source="owner.console",
                owner_confirmed=True,
            )
        )
        self.assertEqual(confirmed["status"], "observed")
        self.assertEqual(confirmed["policy"]["decision"], "ask")
        self.assertTrue(confirmed["policy"]["ownerConfirmed"])

    def test_denied_and_crashing_policy_fail_closed(self) -> None:
        encoded = encode_png(gradient())
        denied = _service(_RecordingEvaluate("deny"))
        with self.assertRaises(PerceptionError) as caught:
            asyncio.run(
                denied.ingest_snapshot(
                    encoded,
                    correlation_id=CORRELATION,
                    session_id=None,
                    source="owner.console",
                    owner_confirmed=True,
                )
            )
        self.assertEqual(caught.exception.code, "E_PERCEPTION_DENIED")

        crashing = _service(_RecordingEvaluate(raise_error=True))
        with self.assertRaises(PerceptionError) as crashed:
            asyncio.run(
                crashing.ingest_snapshot(
                    encoded,
                    correlation_id=CORRELATION,
                    session_id=None,
                    source="owner.console",
                    owner_confirmed=True,
                )
            )
        self.assertEqual(crashed.exception.code, "E_PERCEPTION_POLICY")

    def test_unknown_decision_fails_closed(self) -> None:
        service = _service(_RecordingEvaluate("maybe"))
        with self.assertRaises(PerceptionError) as caught:
            asyncio.run(
                service.ingest_snapshot(
                    encode_png(gradient()),
                    correlation_id=CORRELATION,
                    session_id=None,
                    source="owner.console",
                    owner_confirmed=True,
                )
            )
        self.assertEqual(caught.exception.code, "E_PERCEPTION_POLICY")

    def test_duplicate_snapshot_is_reported_not_duplicated(self) -> None:
        service = _service(_RecordingEvaluate("allow"))
        encoded = encode_png(gradient())
        first = asyncio.run(
            service.ingest_snapshot(
                encoded,
                correlation_id=CORRELATION,
                session_id=None,
                source="owner.console",
            )
        )
        second = asyncio.run(
            service.ingest_snapshot(
                encoded,
                correlation_id=CORRELATION,
                session_id=None,
                source="owner.console",
            )
        )
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(
            second["dedup"]["matchedObservationId"],
            first["observation"]["observationId"],
        )
        listing = asyncio.run(service.observations())
        self.assertEqual(listing["count"], 1)

    def test_explicit_vision_summary_is_bounded_untrusted_and_keeps_no_pixels(self) -> None:
        calls: list[tuple[bytes, str]] = []

        async def analyze(image: bytes, prompt: str) -> str:
            calls.append((image, prompt))
            return "  Có một cửa sổ Minecraft.\nKhông đọc rõ dòng chữ nhỏ.  "

        encoded = encode_png(gradient())
        service = _service(
            _RecordingEvaluate("allow"),
            vision_analyze=analyze,
        )
        result = asyncio.run(
            service.ingest_snapshot(
                encoded,
                correlation_id=CORRELATION,
                session_id=None,
                source="owner.console",
                analyze_with_vlm=True,
                vision_question="Nhân vật đang đứng ở đâu?",
            )
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], encoded)
        self.assertIn("Nhân vật đang đứng ở đâu?", calls[0][1])
        vision = result["observation"]["vision"]
        self.assertEqual(vision["state"], "ready")
        self.assertEqual(
            vision["summary"],
            "Có một cửa sổ Minecraft.\nKhông đọc rõ dòng chữ nhỏ.",
        )
        self.assertEqual(vision["trustLevel"], "untrusted")
        self.assertFalse(vision["decisionSupportEligible"])
        self.assertNotIn("Nhân vật đang đứng", str(result["observation"]))
        self.assertNotIn(encoded.hex()[:32], str(result))

    def test_vision_failure_preserves_base_observation_and_is_reported(self) -> None:
        reports: list[dict[str, str]] = []

        class VisionFailure(Exception):
            code = "E_MODEL_UNAVAILABLE"

        async def analyze(_image: bytes, _prompt: str) -> str:
            raise VisionFailure("offline")

        service = _service(
            _RecordingEvaluate("allow"),
            on_error=reports.append,
            vision_analyze=analyze,
        )
        result = asyncio.run(
            service.ingest_snapshot(
                encode_png(gradient()),
                correlation_id=CORRELATION,
                session_id=None,
                source="owner.console",
                analyze_with_vlm=True,
            )
        )
        self.assertEqual(result["status"], "observed")
        self.assertIn("sha256", result["observation"]["evidence"])
        self.assertEqual(result["observation"]["vision"]["state"], "error")
        self.assertEqual(
            result["observation"]["vision"]["modelErrorCode"],
            "E_MODEL_UNAVAILABLE",
        )
        self.assertEqual(reports[0]["errorCode"], "E_PERCEPTION_VISION")

    def test_vision_question_requires_explicit_analysis(self) -> None:
        service = _service(_RecordingEvaluate("allow"))
        with self.assertRaises(PerceptionError) as caught:
            asyncio.run(
                service.ingest_snapshot(
                    encode_png(gradient()),
                    correlation_id=CORRELATION,
                    session_id=None,
                    source="owner.console",
                    vision_question="Ảnh có gì?",
                )
            )
        self.assertEqual(caught.exception.code, "E_PERCEPTION_REQUEST")

    def test_ocr_is_explicit_bounded_untrusted_and_never_keeps_pixels(self) -> None:
        provider = _FakeOcrProvider()
        encoded = encode_png(gradient())
        service = _service(_RecordingEvaluate("allow"), ocr_provider=provider)

        without_ocr = asyncio.run(
            service.ingest_snapshot(
                encoded,
                correlation_id=CORRELATION,
                session_id=None,
                source="owner.console",
            )
        )
        self.assertEqual(provider.calls, [])
        self.assertEqual(without_ocr["observation"]["ocr"]["state"], "not-requested")

        with_ocr = asyncio.run(
            service.ingest_snapshot(
                encode_png(gradient(invert=True)),
                correlation_id=CORRELATION,
                session_id=None,
                source="owner.console",
                analyze_with_ocr=True,
            )
        )
        ocr = with_ocr["observation"]["ocr"]
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(ocr["state"], "ready")
        self.assertEqual(ocr["text"], "Hina đang quan sát")
        self.assertEqual(ocr["trustLevel"], "untrusted")
        self.assertFalse(ocr["decisionSupportEligible"])
        self.assertEqual(len(ocr["lines"][0]["box"]), 8)
        flattened = str(with_ocr)
        self.assertNotIn("IDAT", flattened)
        self.assertNotIn(provider.calls[0].hex()[:32], flattened)

    def test_ocr_failure_preserves_base_observation_and_is_reported(self) -> None:
        reports: list[dict[str, str]] = []

        class OcrFailure(Exception):
            code = "E_PERCEPTION_OCR_CUDA"

        service = _service(
            _RecordingEvaluate("allow"),
            ocr_provider=_FakeOcrProvider(error=OcrFailure("CUDA unavailable")),
            on_error=reports.append,
        )
        result = asyncio.run(
            service.ingest_snapshot(
                encode_png(gradient()),
                correlation_id=CORRELATION,
                session_id=None,
                source="owner.console",
                analyze_with_ocr=True,
            )
        )
        self.assertEqual(result["status"], "observed")
        self.assertIn("sha256", result["observation"]["evidence"])
        self.assertEqual(result["observation"]["ocr"]["state"], "error")
        self.assertEqual(result["observation"]["ocr"]["errorCode"], "E_PERCEPTION_OCR")
        self.assertEqual(result["observation"]["ocr"]["providerErrorCode"], "E_PERCEPTION_OCR_CUDA")
        self.assertEqual(reports[0]["errorCode"], "E_PERCEPTION_OCR")

    def test_ocr_status_and_close_delegate_to_provider(self) -> None:
        provider = _FakeOcrProvider()
        service = _service(_RecordingEvaluate("allow"), ocr_provider=provider)
        status = asyncio.run(service.status())
        self.assertTrue(status["ocr"]["available"])
        self.assertFalse(status["ocr"]["cpuFallback"])
        asyncio.run(service.close())
        self.assertTrue(provider.closed)

    def test_rate_limit_rejects_after_budget(self) -> None:
        clock = FakeClock()
        config = PerceptionConfig(rate_limit_per_minute=2, dedup_hamming_threshold=0)
        service = _service(_RecordingEvaluate("allow"), clock=clock, config=config)
        half_split = [
            [(255, 255, 255) if column < 16 else (0, 0, 0) for column in range(32)]
            for _ in range(32)
        ]
        images = [
            encode_png(gradient()),
            encode_png(gradient(invert=True)),
            encode_png(half_split),
        ]
        for encoded in images[:2]:
            asyncio.run(
                service.ingest_snapshot(
                    encoded,
                    correlation_id=CORRELATION,
                    session_id=None,
                    source="owner.console",
                )
            )
        with self.assertRaises(PerceptionError) as caught:
            asyncio.run(
                service.ingest_snapshot(
                    images[2],
                    correlation_id=CORRELATION,
                    session_id=None,
                    source="owner.console",
                )
            )
        self.assertEqual(caught.exception.code, "E_PERCEPTION_RATE_LIMIT")
        self.assertTrue(caught.exception.retryable)

    def test_observation_expires_at_ttl_via_service(self) -> None:
        clock = FakeClock()
        service = _service(_RecordingEvaluate("allow"), clock=clock)
        asyncio.run(
            service.ingest_snapshot(
                encode_png(gradient()),
                correlation_id=CORRELATION,
                session_id=None,
                source="owner.console",
            )
        )
        clock.advance(14.999)
        self.assertEqual(asyncio.run(service.observations())["count"], 1)
        clock.advance(0.001)
        listing = asyncio.run(service.observations())
        self.assertEqual(listing["count"], 0)
        self.assertEqual(listing["expiredTotal"], 1)

    def test_invalid_source_and_uuid_are_rejected(self) -> None:
        service = _service(_RecordingEvaluate("allow"))
        encoded = encode_png(gradient())
        with self.assertRaises(PerceptionError):
            asyncio.run(
                service.ingest_snapshot(
                    encoded,
                    correlation_id=CORRELATION,
                    session_id=None,
                    source="viewer.stream",
                )
            )
        with self.assertRaises(PerceptionError):
            asyncio.run(
                service.ingest_snapshot(
                    encoded,
                    correlation_id="not-a-uuid",
                    session_id=None,
                    source="owner.console",
                )
            )

    def test_invalid_snapshot_reports_error_callback(self) -> None:
        reports: list[dict[str, str]] = []
        service = _service(_RecordingEvaluate("allow"), on_error=reports.append)
        with self.assertRaises(PerceptionError):
            asyncio.run(
                service.ingest_snapshot(
                    b"not a png",
                    correlation_id=CORRELATION,
                    session_id=None,
                    source="owner.console",
                )
            )
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["errorCode"], "E_PERCEPTION_SNAPSHOT_INVALID")
        self.assertNotIn("pixels", reports[0])

    def test_clear_requires_owner_surface(self) -> None:
        service = _service(_RecordingEvaluate("allow"))
        asyncio.run(
            service.ingest_snapshot(
                encode_png(gradient()),
                correlation_id=CORRELATION,
                session_id=None,
                source="owner.console",
            )
        )
        with self.assertRaises(PerceptionError):
            asyncio.run(service.clear(source="viewer.stream"))
        result = asyncio.run(service.clear(source="owner.console"))
        self.assertEqual(result, {"status": "cleared", "removed": 1})

    def test_closed_service_is_unavailable(self) -> None:
        service = _service(_RecordingEvaluate("allow"))
        asyncio.run(service.close())
        with self.assertRaises(PerceptionError) as caught:
            asyncio.run(
                service.ingest_snapshot(
                    encode_png(gradient()),
                    correlation_id=CORRELATION,
                    session_id=None,
                    source="owner.console",
                )
            )
        self.assertEqual(caught.exception.code, "E_PERCEPTION_UNAVAILABLE")
        status = asyncio.run(service.status())
        self.assertFalse(status["available"])

    def test_status_reports_honest_contract_state(self) -> None:
        service = _service(_RecordingEvaluate("allow"))
        status = asyncio.run(service.status())
        self.assertFalse(status["capture"]["autoCapture"])
        self.assertFalse(status["capture"]["defaultEnabled"])
        self.assertEqual(status["policy"]["capability"], "perception.observe")
        self.assertEqual(status["policy"]["featureFlag"], "perception")
        self.assertFalse(status["ocr"]["available"])
        self.assertEqual(status["ocr"]["state"], "unconfigured")
        self.assertFalse(status["vision"]["available"])
        self.assertFalse(status["vision"]["decisionSupportEligible"])
        self.assertFalse(status["retention"]["snapshotPersistence"])
        self.assertFalse(status["retention"]["pixelDataRetained"])


if __name__ == "__main__":
    unittest.main()
