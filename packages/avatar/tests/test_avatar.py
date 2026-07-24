from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hina_avatar import AvatarError, AvatarStageService, AvatarState  # noqa: E402


class AvatarStageServiceTests(unittest.TestCase):
    def test_one_thousand_requested_transitions_never_stick(self) -> None:
        service = AvatarStageService()
        randomizer = random.Random(7)
        states = list(AvatarState)
        for _ in range(1_000):
            target = randomizer.choice(states)
            status = service.apply_cue(
                {
                    "source": "owner.console",
                    "state": str(target),
                    "mode": "manual-preview",
                }
            )
            self.assertEqual(status["state"], str(target))
        recovered = service.reset()
        self.assertEqual(recovered["state"], "idle")
        self.assertEqual(recovered["expression"], "neutral")

    def test_invalid_expression_and_viseme_fall_back_and_intensity_is_bounded(self) -> None:
        service = AvatarStageService()
        status = service.apply_cue(
            {
                "source": "speech.output",
                "state": "speaking",
                "expression": "execute-shell",
                "viseme": "../../A",
                "intensity": 9.5,
                "mode": "tts-playback",
                "utteranceId": "utterance-1",
            }
        )
        self.assertEqual(status["expression"], "neutral")
        self.assertEqual(status["viseme"], "sil")
        self.assertEqual(status["intensity"], 1.0)
        self.assertFalse(status["asset"]["vrmLoaded"])
        self.assertEqual(
            status["lipSync"]["mode"], "observed-audio-spectral-viseme"
        )
        self.assertFalse(status["lipSync"]["phonemeAccurate"])

    def test_untrusted_sources_and_unknown_fields_fail_closed(self) -> None:
        service = AvatarStageService()
        for source in ("viewer.chat", "public.chat", "web.research"):
            with self.assertRaises(AvatarError) as raised:
                service.apply_cue({"source": source, "state": "speaking"})
            self.assertEqual(raised.exception.code, "E_AVATAR_SOURCE")
        with self.assertRaises(AvatarError):
            service.apply_cue(
                {
                    "source": "owner.console",
                    "state": "idle",
                    "modelPath": "C:/secret-model",
                }
            )

    def test_terminal_states_recover_and_history_is_bounded(self) -> None:
        service = AvatarStageService(history_limit=8)
        service.apply_cue({"source": "conversation.service", "state": "error"})
        recovered = service.apply_cue(
            {"source": "conversation.service", "state": "speaking"}
        )
        self.assertEqual(recovered["state"], "speaking")
        for index in range(10):
            service.apply_cue(
                {
                    "source": "owner.console",
                    "state": "idle" if index % 2 else "listening",
                    "mode": "manual-preview",
                }
            )
        self.assertEqual(service.status()["historyDepth"], 8)
        self.assertLessEqual(len(service.history()), 8)
        sequences = [entry["sequence"] for entry in service.history()]
        self.assertEqual(sequences, sorted(sequences))

    def test_turn_observation_contains_identifiers_but_no_text(self) -> None:
        service = AvatarStageService()
        status = service.observe_turn_state(
            {
                "state": "thinking",
                "correlationId": "correlation-1",
                "sessionId": "session-1",
                "turnId": "turn-1",
                "text": "must not cross boundary",
            }
        )
        self.assertEqual(status["source"], "conversation.service")
        self.assertEqual(status["turnId"], "turn-1")
        self.assertNotIn("text", status)
        self.assertNotIn("must not cross boundary", str(service.history()))


if __name__ == "__main__":
    unittest.main()
