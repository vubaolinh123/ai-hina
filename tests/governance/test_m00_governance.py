from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]


def load_validator():
    path = ROOT / "tools" / "dev" / "validate_m00.py"
    spec = importlib.util.spec_from_file_location("validate_m00", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load validate_m00")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_hardware_inventory():
    path = ROOT / "tools" / "dev" / "hardware_inventory.py"
    spec = importlib.util.spec_from_file_location("hardware_inventory", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load hardware_inventory")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class M00GovernanceTests(unittest.TestCase):
    def test_validator_reports_no_errors(self) -> None:
        validator = load_validator()
        self.assertEqual([], validator.collect_errors())

    def test_agent_roster_is_explicit(self) -> None:
        with (ROOT / ".codex" / "config.toml").open("rb") as handle:
            primary = tomllib.load(handle)
        self.assertEqual("gpt-5.6-sol", primary["model"])
        self.assertEqual("danger-full-access", primary["sandbox_mode"])
        self.assertEqual("never", primary["approval_policy"])

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

    def test_handoff_examples_validate_with_draft_2020_12(self) -> None:
        pairs = (
            ("module-brief.schema.json", "MODULE_BRIEF.example.json"),
            ("agent-result.schema.json", "AGENT_RESULT.example.json"),
        )
        for schema_name, example_name in pairs:
            schema = json.loads(
                (ROOT / "docs" / "schemas" / schema_name).read_text(encoding="utf-8")
            )
            example = json.loads(
                (ROOT / "docs" / "templates" / example_name).read_text(
                    encoding="utf-8"
                )
            )
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(
                schema,
                format_checker=FormatChecker(),
            )
            self.assertEqual([], list(validator.iter_errors(example)))

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
        validator = load_validator()
        self.assertEqual(
            "github.com/vubaolinh123/ai-hina",
            validator.canonical_repository(result.stdout),
        )
        for remote in (
            "https://github.com/vubaolinh123/ai-hina.git",
            "git@github.com:vubaolinh123/ai-hina.git",
            "ssh://git@github.com/vubaolinh123/ai-hina.git",
        ):
            self.assertEqual(
                "github.com/vubaolinh123/ai-hina",
                validator.canonical_repository(remote),
            )

    def test_validator_accepts_frozen_detached_checkout(self) -> None:
        validator = load_validator()
        self.assertTrue(validator.is_allowed_m00_checkout(""))
        self.assertTrue(
            validator.is_allowed_m00_checkout("module/M00-governance")
        )
        self.assertTrue(validator.is_allowed_m00_checkout("module/M01-spine"))
        self.assertTrue(
            validator.is_allowed_m00_checkout("integration/M12-release")
        )
        self.assertFalse(validator.is_allowed_m00_checkout("feature/unrelated"))

    def test_hardware_inventory_shape(self) -> None:
        module = load_hardware_inventory()
        payload = module.inventory()
        self.assertEqual("1.0", payload["schema_version"])
        self.assertIsInstance(payload["platform"], dict)
        self.assertIsInstance(payload["gpus"], list)
        self.assertIsInstance(payload["tools"], dict)
        self.assertIn("python", payload["tools"])
        self.assertIn("codex", payload["tools"])

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
