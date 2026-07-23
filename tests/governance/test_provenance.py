from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ProvenanceTests(unittest.TestCase):
    def test_m00_imports_no_third_party_source(self) -> None:
        data = json.loads(
            (ROOT / "third_party" / "code.lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual("1.0", data["schema_version"])
        self.assertEqual([], data["components"])

    def test_model_and_asset_registries_exist(self) -> None:
        self.assertTrue((ROOT / "ml" / "models" / "manifests" / "README.md").is_file())
        self.assertTrue((ROOT / "assets" / "manifests" / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()
