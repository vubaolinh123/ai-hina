from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_validator():
    path = ROOT / "tools" / "dev" / "validate_m00.py"
    spec = importlib.util.spec_from_file_location("validate_m00", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load validate_m00")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class M00GovernanceTests(unittest.TestCase):
    def test_validator_reports_no_errors(self) -> None:
        validator = load_validator()
        self.assertEqual([], validator.collect_errors())

    def test_agent_roster_is_explicit(self) -> None:
        agent_files = sorted((ROOT / ".codex" / "agents").glob("*.toml"))
        self.assertEqual(7, len(agent_files))
        models = set()
        for path in agent_files:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
            models.add(data["model"])
            self.assertIn(data["sandbox_mode"], {"read-only", "workspace-write"})
            self.assertNotEqual("danger-full-access", data["sandbox_mode"])
        self.assertEqual({"gpt-5.4", "gpt-5.5"}, models)

    def test_handoff_schemas_are_closed(self) -> None:
        for filename in ("module-brief.schema.json", "agent-result.schema.json"):
            data = json.loads(
                (ROOT / "docs" / "schemas" / filename).read_text(encoding="utf-8")
            )
            self.assertFalse(data["additionalProperties"])
            self.assertEqual(
                "https://json-schema.org/draft/2020-12/schema", data["$schema"]
            )

    def test_security_profiles_fail_closed(self) -> None:
        for profile in ("development", "private", "livestream"):
            with (
                ROOT / "configs" / "profiles" / profile / "profile.toml"
            ).open("rb") as handle:
                data = tomllib.load(handle)
            self.assertFalse(data["public_output_enabled"])

    def test_origin_is_expected_repository(self) -> None:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(
            "https://github.com/vubaolinh123/ai-hina.git",
            result.stdout.strip().rstrip("/"),
        )

    def test_sensitive_runtime_paths_are_ignored(self) -> None:
        candidates = (
            ".env.local",
            "var/data/private.sqlite",
            "ml/datasets/raw/audio.wav",
            "assets/voices/owner.wav",
            "model.safetensors",
        )
        for candidate in candidates:
            result = subprocess.run(
                ["git", "check-ignore", "--quiet", candidate],
                cwd=ROOT,
                check=False,
            )
            self.assertEqual(0, result.returncode, candidate)


if __name__ == "__main__":
    unittest.main()
