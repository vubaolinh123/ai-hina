from __future__ import annotations

import unittest
from uuid import uuid4

from hina_perception.errors import PerceptionError
from hina_perception.vision_quality import VisionQualityLedger


class VisionQualityLedgerTests(unittest.TestCase):
    def test_register_review_rerate_and_profile_status_are_deterministic(self) -> None:
        ledger = VisionQualityLedger(capacity=4)
        first = str(uuid4())
        second = str(uuid4())
        ledger.register(
            first,
            provider="ollama_cloud",
            model="minimax-m3",
            state="ready",
            confidence=0.9,
        )
        ledger.register(
            second,
            provider="ollama_cloud",
            model="minimax-m3",
            state="abstained",
            confidence=0.15,
        )

        reviewed = ledger.review(first, "correct", ["gameplay"])
        self.assertFalse(reviewed["replaced"])
        self.assertEqual(reviewed["sceneTags"], ["gameplay"])
        ledger.review(second, "partial", ["menu_hud"])
        before_rerate = ledger.status(
            provider="ollama_cloud",
            model="minimax-m3",
        )
        self.assertEqual(before_rerate["calibration"]["sampleCount"], 2)
        self.assertEqual(
            before_rerate["calibration"]["meanObservedScorePercent"],
            75.0,
        )
        rerated = ledger.review(second, "incorrect", ["chat_text", "menu_hud"])
        self.assertTrue(rerated["replaced"])
        self.assertEqual(rerated["sceneTags"], ["menu_hud", "chat_text"])

        status = ledger.status(provider="ollama_cloud", model="minimax-m3")
        self.assertEqual(status["registeredSamples"], 2)
        self.assertEqual(status["ratedSamples"], 2)
        self.assertEqual(
            status["ratings"],
            {"correct": 1, "partial": 0, "incorrect": 1},
        )
        self.assertEqual(status["weightedScorePercent"], 50.0)
        self.assertEqual(status["calibration"]["sampleCount"], 2)
        self.assertEqual(
            status["calibration"]["meanObservedScorePercent"],
            50.0,
        )
        self.assertFalse(status["candidateTargetMet"])
        self.assertFalse(status["promotionApproved"])
        self.assertFalse(status["storesPixels"])
        self.assertFalse(status["storesSummaries"])
        self.assertEqual(status["schemaVersion"], "1.1")
        self.assertEqual(status["sceneDiversity"]["counts"]["gameplay"], 1)
        self.assertEqual(status["sceneDiversity"]["counts"]["menu_hud"], 1)
        self.assertEqual(status["sceneDiversity"]["counts"]["chat_text"], 1)
        self.assertFalse(status["sceneDiversity"]["targetMet"])

    def test_capacity_evicts_oldest_and_profiles_do_not_mix(self) -> None:
        ledger = VisionQualityLedger(capacity=2)
        removed = str(uuid4())
        local = str(uuid4())
        cloud = str(uuid4())
        ledger.register(
            removed,
            provider="ollama_cloud",
            model="model-a",
            state="ready",
            confidence=0.8,
        )
        ledger.register(
            local,
            provider="ollama_local",
            model="model-b",
            state="ready",
            confidence=0.8,
        )
        ledger.register(
            cloud,
            provider="ollama_cloud",
            model="model-a",
            state="ready",
            confidence=0.8,
        )

        with self.assertRaises(PerceptionError):
            ledger.review(removed, "correct", ["gameplay"])
        self.assertEqual(
            ledger.status(provider="ollama_cloud", model="model-a")[
                "registeredSamples"
            ],
            1,
        )
        self.assertEqual(
            ledger.status(provider="ollama_local", model="model-b")[
                "registeredSamples"
            ],
            1,
        )

    def test_reset_profile_removes_only_exact_profile_and_is_idempotent(self) -> None:
        ledger = VisionQualityLedger()
        cloud_rated = str(uuid4())
        cloud_unrated = str(uuid4())
        local = str(uuid4())
        for observation_id, provider, model in (
            (cloud_rated, "ollama_cloud", "vision-a"),
            (cloud_unrated, "ollama_cloud", "vision-a"),
            (local, "ollama_local", "vision-a"),
        ):
            ledger.register(
                observation_id,
                provider=provider,
                model=model,
                state="ready",
                confidence=0.8,
            )
        ledger.review(cloud_rated, "correct", ["desktop_ui"])
        ledger.review(local, "partial", ["gameplay"])

        reset = ledger.reset_profile(
            provider="ollama_cloud",
            model="vision-a",
        )

        self.assertEqual(reset, {"removedSamples": 2})
        self.assertNotIn(cloud_rated, str(reset))
        cloud_status = ledger.status(
            provider="ollama_cloud",
            model="vision-a",
        )
        self.assertEqual(cloud_status["registeredSamples"], 0)
        self.assertEqual(cloud_status["ratedSamples"], 0)
        local_status = ledger.status(
            provider="ollama_local",
            model="vision-a",
        )
        self.assertEqual(local_status["registeredSamples"], 1)
        self.assertEqual(local_status["ratedSamples"], 1)
        self.assertEqual(local_status["allProfilesRegisteredSamples"], 1)
        self.assertEqual(
            ledger.reset_profile(
                provider="ollama_cloud",
                model="vision-a",
            ),
            {"removedSamples": 0},
        )

    def test_calibration_diagnostics_use_only_rated_current_profile_samples(self) -> None:
        ledger = VisionQualityLedger()
        samples = [
            (0.9, "ready", "correct"),
            (0.6, "ready", "partial"),
            (0.2, "ready", "incorrect"),
            (0.1, "abstained", None),
        ]
        observation_ids: list[str] = []
        for confidence, state, rating in samples:
            observation_id = str(uuid4())
            observation_ids.append(observation_id)
            ledger.register(
                observation_id,
                provider="ollama_cloud",
                model="vision-a",
                state=state,
                confidence=confidence,
            )
            if rating is not None:
                ledger.review(observation_id, rating, ["gameplay"])
        other_profile = str(uuid4())
        ledger.register(
            other_profile,
            provider="ollama_cloud",
            model="vision-b",
            state="ready",
            confidence=1.0,
        )
        ledger.review(other_profile, "incorrect", ["desktop_ui"])

        status = ledger.status(provider="ollama_cloud", model="vision-a")
        self.assertEqual(status["states"], {"ready": 3, "abstained": 1})
        self.assertEqual(status["abstentionRatePercent"], 25.0)
        calibration = status["calibration"]
        self.assertFalse(calibration["calibrated"])
        self.assertTrue(calibration["diagnosticOnly"])
        self.assertEqual(calibration["sampleCount"], 3)
        self.assertFalse(calibration["sufficientEvidence"])
        self.assertEqual(calibration["meanConfidencePercent"], 56.7)
        self.assertEqual(calibration["meanObservedScorePercent"], 50.0)
        self.assertEqual(calibration["meanAbsoluteErrorPercent"], 13.3)
        self.assertEqual(calibration["brierScore"], 0.02)
        self.assertEqual(
            calibration["ratingTruthMapping"],
            {"correct": 1.0, "partial": 0.5, "incorrect": 0.0},
        )
        self.assertEqual(len(calibration["reliabilityBins"]), 5)
        self.assertEqual(
            [item["sampleCount"] for item in calibration["reliabilityBins"]],
            [0, 1, 0, 1, 1],
        )
        self.assertEqual(
            calibration["reliabilityBins"][1]["observedScorePercent"],
            0.0,
        )
        self.assertEqual(
            calibration["reliabilityBins"][3]["observedScorePercent"],
            50.0,
        )
        self.assertEqual(
            calibration["reliabilityBins"][4]["observedScorePercent"],
            100.0,
        )
        self.assertNotIn(observation_ids[0], str(status))
        self.assertNotIn(other_profile, str(status))

    def test_empty_calibration_metrics_are_unknown_not_zero(self) -> None:
        ledger = VisionQualityLedger()
        status = ledger.status(provider="ollama_cloud", model="vision-a")

        self.assertIsNone(status["abstentionRatePercent"])
        calibration = status["calibration"]
        self.assertEqual(calibration["sampleCount"], 0)
        self.assertIsNone(calibration["meanConfidencePercent"])
        self.assertIsNone(calibration["meanObservedScorePercent"])
        self.assertIsNone(calibration["meanAbsoluteErrorPercent"])
        self.assertIsNone(calibration["brierScore"])
        self.assertTrue(
            all(
                item["meanConfidencePercent"] is None
                and item["observedScorePercent"] is None
                for item in calibration["reliabilityBins"]
            )
        )

    def test_invalid_registration_and_review_fail_closed(self) -> None:
        ledger = VisionQualityLedger()
        observation_id = str(uuid4())
        with self.assertRaises(PerceptionError):
            ledger.register(
                observation_id,
                provider="ollama_cloud",
                model="model-a",
                state="error",
                confidence=0.8,
            )
        ledger.register(
            observation_id,
            provider="ollama_cloud",
            model="model-a",
            state="ready",
            confidence=0.8,
        )
        with self.assertRaises(PerceptionError):
            ledger.review(observation_id, "mostly-correct", ["gameplay"])
        with self.assertRaises(PerceptionError):
            ledger.review(  # type: ignore[arg-type]
                observation_id,
                ["correct"],
                ["gameplay"],
            )
        with self.assertRaises(PerceptionError):
            ledger.review(observation_id.upper(), "correct", ["gameplay"])
        with self.assertRaises(PerceptionError):
            ledger.review(str(uuid4()), "correct", ["gameplay"])
        for invalid_tags in (
            [],
            ["gameplay", "gameplay"],
            ["gameplay", "menu_hud", "chat_text", "desktop_ui"],
            ["not-allowlisted"],
            "gameplay",
        ):
            with self.assertRaises(PerceptionError):
                ledger.review(observation_id, "correct", invalid_tags)

    def test_candidate_requires_score_sample_count_and_scene_diversity(self) -> None:
        diverse = VisionQualityLedger()
        narrow = VisionQualityLedger()
        coverage_tags = (
            "gameplay",
            "menu_hud",
            "chat_text",
            "desktop_ui",
        )
        for index in range(20):
            diverse_id = str(uuid4())
            narrow_id = str(uuid4())
            for ledger, observation_id in (
                (diverse, diverse_id),
                (narrow, narrow_id),
            ):
                ledger.register(
                    observation_id,
                    provider="ollama_cloud",
                    model="vision-a",
                    state="ready",
                    confidence=0.9,
                )
            diverse.review(
                diverse_id,
                "correct",
                [coverage_tags[index % len(coverage_tags)]],
            )
            narrow.review(narrow_id, "correct", ["gameplay"])

        diverse_status = diverse.status(
            provider="ollama_cloud",
            model="vision-a",
        )
        narrow_status = narrow.status(
            provider="ollama_cloud",
            model="vision-a",
        )

        self.assertEqual(diverse_status["weightedScorePercent"], 100.0)
        self.assertEqual(diverse_status["sceneDiversity"]["coveredTags"], 4)
        self.assertTrue(diverse_status["sceneDiversity"]["targetMet"])
        self.assertTrue(diverse_status["candidateTargetMet"])
        self.assertEqual(narrow_status["weightedScorePercent"], 100.0)
        self.assertEqual(narrow_status["sceneDiversity"]["coveredTags"], 1)
        self.assertFalse(narrow_status["sceneDiversity"]["targetMet"])
        self.assertFalse(narrow_status["candidateTargetMet"])


if __name__ == "__main__":
    unittest.main()
