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

        reviewed = ledger.review(first, "correct")
        self.assertFalse(reviewed["replaced"])
        ledger.review(second, "partial")
        rerated = ledger.review(second, "incorrect")
        self.assertTrue(rerated["replaced"])

        status = ledger.status(provider="ollama_cloud", model="minimax-m3")
        self.assertEqual(status["registeredSamples"], 2)
        self.assertEqual(status["ratedSamples"], 2)
        self.assertEqual(
            status["ratings"],
            {"correct": 1, "partial": 0, "incorrect": 1},
        )
        self.assertEqual(status["weightedScorePercent"], 50.0)
        self.assertFalse(status["candidateTargetMet"])
        self.assertFalse(status["promotionApproved"])
        self.assertFalse(status["storesPixels"])
        self.assertFalse(status["storesSummaries"])

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
            ledger.review(removed, "correct")
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
            ledger.review(observation_id, "mostly-correct")
        with self.assertRaises(PerceptionError):
            ledger.review(observation_id, ["correct"])  # type: ignore[arg-type]
        with self.assertRaises(PerceptionError):
            ledger.review(observation_id.upper(), "correct")
        with self.assertRaises(PerceptionError):
            ledger.review(str(uuid4()), "correct")


if __name__ == "__main__":
    unittest.main()
