from __future__ import annotations

import json
import hashlib
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
        vieneu = by_name["vieneu"]
        self.assertEqual("Apache-2.0", vieneu["license_spdx"])
        self.assertIn("v3.2.3@", vieneu["revision"])
        self.assertEqual(
            "sha256:54fd23bf70dcc5bf83885163de67a0ae2b7d2030cf7b53996d5ec97d2dbb20ca",
            vieneu["source_hash"],
        )
        self.assertTrue(
            any("no upstream source" in item.lower() for item in vieneu["modifications"])
        )
        qdrant = by_name["qdrant-client"]
        self.assertEqual("Apache-2.0", qdrant["license_spdx"])
        self.assertIn("v1.18.0@", qdrant["revision"])
        self.assertEqual(
            "sha256:093aa8cf8a420ee3ad2a68b007e1378d7992b2600e0b53c193fc172674f659cd",
            qdrant["source_hash"],
        )
        self.assertTrue(
            any("no upstream source" in item.lower() for item in qdrant["modifications"])
        )
        desktop_dependencies = {
            "electron": ("MIT", "npm:electron@43.2.0"),
            "vue": ("MIT", "npm:vue@3.5.40"),
            "vite": ("MIT", "npm:vite@8.1.5"),
            "@vitejs/plugin-vue": ("MIT", "npm:@vitejs/plugin-vue@6.0.8"),
            "typescript": ("Apache-2.0", "npm:typescript@6.0.3"),
            "vue-tsc": ("MIT", "npm:vue-tsc@3.3.8"),
            "@types/node": ("MIT", "npm:@types/node@26.1.1"),
        }
        for name, (license_spdx, revision) in desktop_dependencies.items():
            component = by_name[name]
            self.assertEqual(license_spdx, component["license_spdx"])
            self.assertEqual(revision, component["revision"])
            self.assertTrue(component["source_hash"].startswith("sha512-"))
            self.assertTrue(
                any(
                    "no upstream source" in item.lower()
                    for item in component["modifications"]
                )
            )

    def test_model_and_asset_registries_exist(self) -> None:
        self.assertTrue((ROOT / "ml" / "models" / "manifests" / "README.md").is_file())
        self.assertTrue((ROOT / "assets" / "manifests" / "README.md").is_file())
        self.assertTrue(
            (
                ROOT
                / "ml"
                / "models"
                / "manifests"
                / "vieneu-tts-v3-turbo.v1.json"
            ).is_file()
        )
        voice = json.loads(
            (
                ROOT
                / "assets"
                / "manifests"
                / "vieneu-truc-ly-preset.v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertFalse(voice["consent_and_use"]["voice_cloning_allowed_by_hina"])
        self.assertFalse(voice["status"]["production_ready"])
        avatar = json.loads(
            (
                ROOT
                / "assets"
                / "manifests"
                / "hina-code-avatar.v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(avatar["license"]["spdx"], "MIT")
        self.assertFalse(avatar["source"]["copied_or_adapted"])
        self.assertFalse(avatar["source"]["depicts_real_person"])
        self.assertFalse(avatar["runtime"]["vrm"])
        for item in avatar["files"]:
            digest = hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest()
            self.assertEqual(digest, item["sha256"])

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
