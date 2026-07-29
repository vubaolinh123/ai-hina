from __future__ import annotations

import asyncio
import hashlib
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from uuid import uuid4


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
        self.assertFalse(config.archive_default_enabled)
        self.assertIsNone(config.archive_root)

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

    def test_archive_cannot_be_default_enabled(self) -> None:
        with self.assertRaises(PerceptionError):
            PerceptionConfig(archive_default_enabled=True)

    def test_from_env_reads_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config = PerceptionConfig.from_env(
                {
                    "HINA_PERCEPTION_TTL_SECONDS": "5",
                    "HINA_PERCEPTION_RATE_PER_MINUTE": "3",
                    "HINA_PERCEPTION_ARCHIVE_MAX_SNAPSHOTS": "25",
                },
                root=root,
            )
            self.assertEqual(config.ttl_seconds, 5.0)
            self.assertEqual(config.rate_limit_per_minute, 3)
            self.assertEqual(config.archive_max_snapshots, 25)
            self.assertEqual(
                config.archive_root,
                (root / "var" / "perception-sessions").resolve(),
            )
            self.assertTrue(config.public_status()["archiveAvailable"])

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


CORRELATION = "5d1c0dd2-8a53-4a30-9c5a-6f9df5a3f6ba"
SESSION = "91a7b739-909a-4868-8652-2f081d402135"


def _service(
    evaluate: _RecordingEvaluate,
    *,
    clock: FakeClock | None = None,
    config: PerceptionConfig | None = None,
    on_error=None,
    vision_analyze=None,
) -> PerceptionService:
    return PerceptionService(
        config or PerceptionConfig(),
        safety_evaluate=evaluate,
        vision_analyze=vision_analyze,
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
        self.assertNotIn("ocr", observation)
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
        self.assertGreaterEqual(vision["confidence"], vision["minimumConfidence"])
        self.assertEqual(vision["confidenceSource"], "summary-heuristic.v1")
        self.assertFalse(vision["confidenceCalibrated"])
        self.assertIsNone(vision["abstainReason"])
        self.assertGreaterEqual(vision["processingMilliseconds"], 0)
        self.assertNotIn("Nhân vật đang đứng", str(result["observation"]))
        self.assertNotIn(encoded.hex()[:32], str(result))

    def test_uncertain_vision_abstains_and_never_enters_fresh_chat_context(self) -> None:
        async def analyze(_image: bytes, _prompt: str) -> str:
            return (
                "Không thể xác định nội dung của ảnh vì ảnh quá mờ để nhận diện. "
                "Không có chi tiết nào đủ chắc chắn để mô tả."
            )

        service = _service(
            _RecordingEvaluate("allow"),
            vision_analyze=analyze,
        )
        result = asyncio.run(
            service.ingest_snapshot(
                encode_png(gradient()),
                correlation_id=CORRELATION,
                session_id=SESSION,
                source="owner.desktop",
                analyze_with_vlm=True,
            )
        )

        vision = result["observation"]["vision"]
        self.assertEqual(vision["state"], "abstained")
        self.assertEqual(vision["abstainReason"], "model-explicitly-uncertain")
        self.assertLess(vision["confidence"], vision["minimumConfidence"])
        self.assertFalse(vision["confidenceCalibrated"])
        self.assertFalse(vision["decisionSupportEligible"])
        self.assertIn("Không thể xác định", vision["summary"])
        self.assertEqual(
            (),
            asyncio.run(
                service.fresh_context_for_turn(SESSION, source="owner.console")
            ),
        )

    def test_owner_scene_qa_rates_real_observation_without_storing_summary(self) -> None:
        summary = "Có một cửa sổ game, nhân vật và thanh trạng thái hiển thị rõ."

        async def analyze(_image: bytes, _prompt: str) -> str:
            return summary

        service = _service(
            _RecordingEvaluate("allow"),
            vision_analyze=analyze,
        )
        result = asyncio.run(
            service.ingest_snapshot(
                encode_png(gradient()),
                correlation_id=CORRELATION,
                session_id=SESSION,
                source="owner.desktop",
                analyze_with_vlm=True,
            )
        )
        observation_id = result["observation"]["observationId"]
        initial = asyncio.run(service.status())["vision"]["qualityReview"]
        self.assertEqual(initial["registeredSamples"], 1)
        self.assertEqual(initial["ratedSamples"], 0)
        self.assertNotIn(summary, str(initial))

        reviewed = asyncio.run(
            service.review_vision_observation(
                observation_id=observation_id,
                rating="correct",
                scene_tags=["gameplay", "menu_hud"],
                source="owner.desktop",
                owner_confirmed=True,
            )
        )
        self.assertFalse(reviewed["replaced"])
        self.assertEqual(reviewed["sceneTags"], ["gameplay", "menu_hud"])
        self.assertEqual(reviewed["qualityReview"]["ratedSamples"], 1)
        self.assertEqual(reviewed["qualityReview"]["weightedScorePercent"], 100.0)
        self.assertFalse(reviewed["qualityReview"]["candidateTargetMet"])
        self.assertFalse(reviewed["qualityReview"]["promotionApproved"])
        self.assertNotIn(summary, str(reviewed))

        rerated = asyncio.run(
            service.review_vision_observation(
                observation_id=observation_id,
                rating="partial",
                scene_tags=["desktop_ui"],
                source="owner.desktop",
                owner_confirmed=True,
            )
        )
        self.assertTrue(rerated["replaced"])
        self.assertEqual(rerated["sceneTags"], ["desktop_ui"])
        self.assertEqual(rerated["qualityReview"]["ratedSamples"], 1)
        self.assertEqual(rerated["qualityReview"]["weightedScorePercent"], 50.0)

    def test_owner_scene_qa_rejects_untrusted_or_unknown_review(self) -> None:
        service = _service(_RecordingEvaluate("allow"))
        for source, owner_confirmed in (
            ("viewer.chat", True),
            ("owner.desktop", False),
        ):
            with self.assertRaises(PerceptionError):
                asyncio.run(
                    service.review_vision_observation(
                        observation_id=str(uuid4()),
                        rating="correct",
                        scene_tags=["gameplay"],
                        source=source,
                        owner_confirmed=owner_confirmed,
                    )
                )
        with self.assertRaises(PerceptionError):
            asyncio.run(
                service.review_vision_observation(
                    observation_id=str(uuid4()),
                    rating="correct",
                    scene_tags=["gameplay"],
                    source="owner.desktop",
                    owner_confirmed=True,
                )
            )

    def test_owner_can_reset_only_current_scene_qa_profile(self) -> None:
        summary = "Cửa sổ game có nhân vật và thanh trạng thái."

        async def analyze(_image: bytes, _prompt: str) -> str:
            return summary

        service = _service(
            _RecordingEvaluate("allow"),
            vision_analyze=analyze,
        )
        result = asyncio.run(
            service.ingest_snapshot(
                encode_png(gradient()),
                correlation_id=CORRELATION,
                session_id=SESSION,
                source="owner.desktop",
                analyze_with_vlm=True,
            )
        )
        observation_id = result["observation"]["observationId"]
        asyncio.run(
            service.review_vision_observation(
                observation_id=observation_id,
                rating="correct",
                scene_tags=["gameplay"],
                source="owner.desktop",
                owner_confirmed=True,
            )
        )

        reset = asyncio.run(
            service.reset_vision_quality_session(
                source="owner.desktop",
                owner_confirmed=True,
            )
        )

        self.assertEqual(reset["status"], "reset")
        self.assertEqual(reset["removedSamples"], 1)
        self.assertEqual(reset["qualityReview"]["registeredSamples"], 0)
        self.assertEqual(reset["qualityReview"]["ratedSamples"], 0)
        self.assertNotIn(observation_id, str(reset))
        self.assertNotIn(summary, str(reset))
        with self.assertRaises(PerceptionError):
            asyncio.run(
                service.review_vision_observation(
                    observation_id=observation_id,
                    rating="correct",
                    scene_tags=["gameplay"],
                    source="owner.desktop",
                    owner_confirmed=True,
                )
            )
        for source, owner_confirmed in (
            ("viewer.chat", True),
            ("owner.desktop", False),
        ):
            with self.assertRaises(PerceptionError):
                asyncio.run(
                    service.reset_vision_quality_session(
                        source=source,
                        owner_confirmed=owner_confirmed,
                    )
                )

    def test_fresh_chat_context_is_semantic_same_session_owner_only_and_expires(self) -> None:
        clock = FakeClock()

        async def analyze(_image: bytes, _prompt: str) -> str:
            return "Có một cửa sổ game và thanh trạng thái."

        service = _service(
            _RecordingEvaluate("allow"),
            clock=clock,
            vision_analyze=analyze,
        )
        result = asyncio.run(
            service.ingest_snapshot(
                encode_png(gradient()),
                correlation_id=CORRELATION,
                session_id=SESSION,
                source="owner.desktop",
                analyze_with_vlm=True,
            )
        )

        fresh = asyncio.run(
            service.fresh_context_for_turn(SESSION, source="owner.console")
        )
        self.assertEqual(1, len(fresh))
        self.assertEqual(
            result["observation"]["observationId"],
            fresh[0]["observationId"],
        )
        self.assertEqual(
            "Có một cửa sổ game và thanh trạng thái.",
            fresh[0]["vision"]["summary"],
        )
        self.assertEqual(
            (),
            asyncio.run(
                service.fresh_context_for_turn(
                    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    source="owner.console",
                )
            ),
        )
        self.assertEqual(
            (),
            asyncio.run(service.fresh_context_for_turn(SESSION, source="viewer.chat")),
        )

        metadata_only = _service(_RecordingEvaluate("allow"))
        asyncio.run(
            metadata_only.ingest_snapshot(
                encode_png(gradient()),
                correlation_id=CORRELATION,
                session_id=SESSION,
                source="owner.console",
            )
        )
        self.assertEqual(
            (),
            asyncio.run(
                metadata_only.fresh_context_for_turn(SESSION, source="owner.console")
            ),
        )

        clock.advance(15.0)
        self.assertEqual(
            (),
            asyncio.run(service.fresh_context_for_turn(SESSION, source="owner.console")),
        )

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
        self.assertGreaterEqual(
            result["observation"]["vision"]["processingMilliseconds"],
            0,
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

    def test_owner_started_archive_writes_only_png_and_stop_keeps_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_root = Path(directory).resolve() / "perception-sessions"
            config = PerceptionConfig(
                archive_root=archive_root,
                archive_max_snapshots=2,
            )
            service = _service(_RecordingEvaluate("allow"), config=config)
            started = asyncio.run(
                service.start_archive(
                    correlation_id=CORRELATION,
                    session_id=SESSION,
                    source="owner.console",
                    owner_confirmed=True,
                )
            )
            archive = started["archive"]
            self.assertEqual(started["status"], "started")
            self.assertTrue(archive["active"])
            archive_session_id = archive["archiveSessionId"]
            self.assertEqual(Path(archive["path"]).parent, archive_root)

            encoded = encode_png(gradient())
            observed = asyncio.run(
                service.ingest_snapshot(
                    encoded,
                    correlation_id=CORRELATION,
                    session_id=SESSION,
                    source="owner.console",
                    owner_confirmed=True,
                    archive_session_id=archive_session_id,
                )
            )
            archived = observed["archive"]
            self.assertTrue(archived["historical"])
            self.assertFalse(archived["decisionSupportEligible"])
            self.assertEqual(Path(archived["path"]).read_bytes(), encoded)
            files = list(Path(archive["path"]).iterdir())
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].suffix, ".png")

            stopped = asyncio.run(
                service.stop_archive(
                    session_id=SESSION,
                    archive_session_id=archive_session_id,
                    source="owner.console",
                )
            )
            self.assertEqual(stopped["status"], "stopped")
            with self.assertRaises(PerceptionError) as caught:
                asyncio.run(
                    service.ingest_snapshot(
                        encode_png(gradient(invert=True)),
                        correlation_id=CORRELATION,
                        session_id=SESSION,
                        source="owner.console",
                        owner_confirmed=True,
                        archive_session_id=archive_session_id,
                    )
                )
            self.assertEqual(caught.exception.code, "E_PERCEPTION_ARCHIVE_STOPPED")
            asyncio.run(service.close())
            self.assertTrue(files[0].exists())

    def test_archive_is_owner_bound_and_quota_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = PerceptionConfig(
                archive_root=Path(directory).resolve() / "perception-sessions",
                archive_max_snapshots=1,
            )
            service = _service(_RecordingEvaluate("allow"), config=config)
            started = asyncio.run(
                service.start_archive(
                    correlation_id=CORRELATION,
                    session_id=SESSION,
                    source="owner.console",
                    owner_confirmed=True,
                )
            )
            archive_session_id = started["archive"]["archiveSessionId"]
            with self.assertRaises(PerceptionError) as owner_error:
                asyncio.run(
                    service.stop_archive(
                        session_id="0f017fb7-2c23-43b2-ab27-12145234f1f9",
                        archive_session_id=archive_session_id,
                        source="owner.console",
                    )
                )
            self.assertEqual(owner_error.exception.code, "E_PERCEPTION_ARCHIVE_OWNER")

            asyncio.run(
                service.ingest_snapshot(
                    encode_png(gradient()),
                    correlation_id=CORRELATION,
                    session_id=SESSION,
                    source="owner.console",
                    owner_confirmed=True,
                    archive_session_id=archive_session_id,
                )
            )
            with self.assertRaises(PerceptionError) as quota_error:
                asyncio.run(
                    service.ingest_snapshot(
                        encode_png(gradient(invert=True)),
                        correlation_id=CORRELATION,
                        session_id=SESSION,
                        source="owner.console",
                        owner_confirmed=True,
                        archive_session_id=archive_session_id,
                    )
                )
            self.assertEqual(quota_error.exception.code, "E_PERCEPTION_ARCHIVE_QUOTA")
            asyncio.run(service.close())

    def test_historical_reanalysis_never_becomes_a_fresh_observation(self) -> None:
        calls: list[bytes] = []

        async def analyze(image: bytes, _prompt: str) -> str:
            calls.append(image)
            return "Ảnh lịch sử có một giao diện trò chơi."

        with tempfile.TemporaryDirectory() as directory:
            config = PerceptionConfig(
                archive_root=Path(directory).resolve() / "perception-sessions",
            )
            service = _service(
                _RecordingEvaluate("allow"),
                config=config,
                vision_analyze=analyze,
            )
            started = asyncio.run(
                service.start_archive(
                    correlation_id=CORRELATION,
                    session_id=SESSION,
                    source="owner.console",
                    owner_confirmed=True,
                )
            )
            archive_session_id = started["archive"]["archiveSessionId"]
            observed = asyncio.run(
                service.ingest_snapshot(
                    encode_png(gradient()),
                    correlation_id=CORRELATION,
                    session_id=SESSION,
                    source="owner.console",
                    owner_confirmed=True,
                    archive_session_id=archive_session_id,
                )
            )
            snapshot_id = observed["archive"]["snapshotId"]
            asyncio.run(service.clear(source="owner.console"))
            historical = asyncio.run(
                service.reanalyze_archive(
                    correlation_id=CORRELATION,
                    session_id=SESSION,
                    archive_session_id=archive_session_id,
                    snapshot_id=snapshot_id,
                    source="owner.console",
                    owner_confirmed=True,
                    vision_question="Đây là màn hình cũ hay hiện tại?",
                )
            )
            self.assertTrue(historical["historical"])
            self.assertFalse(historical["currentObservation"])
            self.assertFalse(historical["decisionSupportEligible"])
            self.assertEqual(historical["vision"]["state"], "ready")
            self.assertEqual(len(calls), 1)
            self.assertEqual(asyncio.run(service.observations())["count"], 0)
            asyncio.run(service.close())

    def test_two_hundred_stopped_archive_replays_never_claim_current(self) -> None:
        replay_count = 200
        analyze_calls = 0

        async def analyze(_image: bytes, _prompt: str) -> str:
            nonlocal analyze_calls
            analyze_calls += 1
            return "Ảnh lịch sử có một giao diện trò chơi và thanh trạng thái."

        async def scenario(root: Path) -> None:
            service = _service(
                _RecordingEvaluate("allow"),
                config=PerceptionConfig(
                    archive_root=root / "perception-sessions",
                ),
                vision_analyze=analyze,
            )
            started = await service.start_archive(
                correlation_id=CORRELATION,
                session_id=SESSION,
                source="owner.console",
                owner_confirmed=True,
            )
            archive_session_id = started["archive"]["archiveSessionId"]
            observed = await service.ingest_snapshot(
                encode_png(gradient()),
                correlation_id=CORRELATION,
                session_id=SESSION,
                source="owner.console",
                owner_confirmed=True,
                archive_session_id=archive_session_id,
            )
            snapshot_id = observed["archive"]["snapshotId"]
            stopped = await service.stop_archive(
                session_id=SESSION,
                archive_session_id=archive_session_id,
                source="owner.console",
            )
            self.assertFalse(stopped["archive"]["active"])
            await service.clear(source="owner.console")

            for _ in range(replay_count):
                historical = await service.reanalyze_archive(
                    correlation_id=CORRELATION,
                    session_id=SESSION,
                    archive_session_id=archive_session_id,
                    snapshot_id=snapshot_id,
                    source="owner.console",
                    owner_confirmed=True,
                    vision_question="Mô tả ảnh lịch sử này.",
                )
                self.assertTrue(historical["historical"])
                self.assertFalse(historical["currentObservation"])
                self.assertFalse(historical["decisionSupportEligible"])
                self.assertEqual(historical["vision"]["state"], "ready")

            self.assertEqual((await service.observations())["count"], 0)
            self.assertEqual(
                await service.fresh_context_for_turn(
                    SESSION,
                    source="owner.console",
                ),
                (),
            )
            await service.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory).resolve()))
        self.assertEqual(analyze_calls, replay_count)

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
        self.assertNotIn("ocr", status)
        self.assertFalse(status["vision"]["available"])
        self.assertFalse(status["vision"]["decisionSupportEligible"])
        self.assertFalse(status["retention"]["snapshotPersistence"])
        self.assertFalse(status["retention"]["pixelDataRetained"])
        self.assertFalse(status["retention"]["archive"]["available"])
        self.assertFalse(status["retention"]["archive"]["active"])


if __name__ == "__main__":
    unittest.main()
