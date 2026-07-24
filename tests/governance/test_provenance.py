from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ProvenanceTests(unittest.TestCase):
    def test_runtime_dependencies_are_pinned_without_untracked_source_copy(self) -> None:
        data = json.loads(
            (ROOT / "third_party" / "code.lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual("1.0", data["schema_version"])
        by_name = {item["name"]: item for item in data["components"]}
        faster_whisper = by_name["faster-whisper"]
        self.assertEqual("MIT", faster_whisper["license_spdx"])
        self.assertIn("v1.2.1@", faster_whisper["revision"])
        self.assertTrue(faster_whisper["source_hash"].startswith("sha256:"))
        self.assertTrue(
            any(
                "no upstream source" in item.lower()
                for item in faster_whisper["modifications"]
            )
        )

    def test_model_and_asset_registries_exist(self) -> None:
        self.assertTrue((ROOT / "ml" / "models" / "manifests" / "README.md").is_file())
        self.assertTrue((ROOT / "assets" / "manifests" / "README.md").is_file())

    def test_research_candidates_are_explicitly_unfrozen(self) -> None:
        for path in (
            ROOT / "third_party" / "candidates.json",
            ROOT / "ml" / "models" / "manifests" / "candidates.json",
        ):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("research_only", data["status"])
            self.assertFalse(data["frozen"])
            self.assertGreater(len(data["candidates"]), 0)
            for candidate in data["candidates"]:
                self.assertIsNone(candidate["revision"])
                self.assertTrue(candidate["source_url"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
