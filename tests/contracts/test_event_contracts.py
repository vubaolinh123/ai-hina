from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "packages" / "contracts"
DRIFT_WORK_ROOT = ROOT / "artifacts" / "verification" / "M01" / "contract-drift-work"
MIN_JS_SAFE_INTEGER = -9_007_199_254_740_991
MAX_JS_SAFE_INTEGER = 9_007_199_254_740_991
sys.path.insert(0, str(CONTRACTS / "src"))

from hina_contracts import (  # noqa: E402
    ErrorCode,
    MAX_JSON_ENVELOPE_BYTES,
    canonicalize_envelope,
    validate_envelope,
    validate_envelope_bytes,
)

PNPM = "pnpm.cmd" if os.name == "nt" else "pnpm"


def load_fixture(name: str) -> dict:
    return json.loads((CONTRACTS / "fixtures" / "golden" / name).read_text(encoding="utf-8"))


def run_typescript_validation(value: object) -> dict:
    return run_typescript_validation_bytes(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def run_typescript_validation_bytes(raw: bytes) -> dict:
    completed = subprocess.run(
        ["node", "packages/contracts/test/canonicalize.mjs"],
        input=raw,
        cwd=ROOT,
        capture_output=True,
    )
    if completed.stdout:
        return json.loads(completed.stdout.decode("utf-8"))
    return {"code": "E_FUZZ_RUNTIME_CRASH", "detail": completed.stderr.decode("utf-8", errors="replace")}


class EventContractTests(unittest.TestCase):
    def assert_code(self, value: object, code: ErrorCode) -> None:
        result = validate_envelope(value)
        self.assertEqual(result.code, code, result.detail)
        self.assertEqual(result.ok, code is ErrorCode.OK)

    def test_golden_fixtures_pass(self) -> None:
        for path in sorted((CONTRACTS / "fixtures" / "golden").glob("*.json")):
            with self.subTest(path=path.name):
                result = validate_envelope_bytes(path.read_bytes())
                self.assertEqual(result.code, ErrorCode.OK, result.detail)
                self.assertIsNotNone(result.canonical_json)

    def test_catalog_schemas_are_draft_2020_12_valid(self) -> None:
        for path in sorted((CONTRACTS / "schemas" / "v1").rglob("*.schema.json")):
            with self.subTest(path=path.relative_to(CONTRACTS).as_posix()):
                Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))

    def test_catalog_and_policy_instances_validate_against_declared_schemas(self) -> None:
        pairs = [
            ("catalog.v1.json", "schemas/v1/catalog.schema.json"),
            ("compatibility-policy.v1.json", "schemas/v1/compatibility-policy.schema.json"),
        ]
        validators: dict[str, Draft202012Validator] = {}
        instances: dict[str, dict] = {}
        for instance_name, schema_name in pairs:
            instance = json.loads((CONTRACTS / instance_name).read_text(encoding="utf-8"))
            schema = json.loads((CONTRACTS / schema_name).read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema)
            with self.subTest(instance=instance_name):
                validator.validate(instance)
            validators[instance_name] = validator
            instances[instance_name] = instance

        duplicate_event = copy.deepcopy(instances["catalog.v1.json"])
        duplicate_event["events"].append(copy.deepcopy(duplicate_event["events"][0]))
        with self.assertRaises(ValidationError):
            validators["catalog.v1.json"].validate(duplicate_event)

        catalog_extra_field = copy.deepcopy(instances["catalog.v1.json"])
        catalog_extra_field["events"][0]["owner"] = "not in schema"
        with self.assertRaises(ValidationError):
            validators["catalog.v1.json"].validate(catalog_extra_field)

        policy = instances["compatibility-policy.v1.json"]
        self.assertEqual(policy["catalogVersion"], f"{policy['currentMajor']}.{policy['currentMinor']}")

        policy_with_previous = copy.deepcopy(policy)
        policy_with_previous["previousVersions"].append(
            {"catalogVersion": "0.9", "disposition": "unsupported", "migrationRequired": False}
        )
        with self.assertRaises(ValidationError):
            validators["compatibility-policy.v1.json"].validate(policy_with_previous)

        policy_extra_field = copy.deepcopy(policy)
        policy_extra_field["unknown"] = True
        with self.assertRaises(ValidationError):
            validators["compatibility-policy.v1.json"].validate(policy_extra_field)

    def test_required_fields_missing_independently(self) -> None:
        fixture = load_fixture("global.echo.json")
        for key in fixture:
            mutated = copy.deepcopy(fixture)
            mutated.pop(key)
            with self.subTest(key=key):
                self.assert_code(mutated, ErrorCode.E_SCHEMA_MISSING_REQUIRED)

    def test_wrong_types_and_enum_values_fail(self) -> None:
        fixture = load_fixture("global.echo.json")
        cases = [
            ("eventId", 7),
            ("media", {}),
            ("payload", []),
            ("trustLevel", "operator"),
            ("sequence", "0"),
        ]
        for key, bad_value in cases:
            mutated = copy.deepcopy(fixture)
            mutated[key] = bad_value
            with self.subTest(key=key):
                self.assert_code(mutated, ErrorCode.E_SCHEMA_WRONG_TYPE)

    def test_unknown_event_and_closed_objects_fail(self) -> None:
        fixture = load_fixture("turn.media.echo.json")
        unknown_event = copy.deepcopy(fixture)
        unknown_event["type"] = "hina.contract.unknown.v1"
        self.assert_code(unknown_event, ErrorCode.E_SCHEMA_UNKNOWN_EVENT)

        envelope_field = copy.deepcopy(fixture)
        envelope_field["extra"] = True
        self.assert_code(envelope_field, ErrorCode.E_SCHEMA_UNKNOWN_FIELD)

        media_field = copy.deepcopy(fixture)
        media_field["media"][0]["label"] = "not inline media"
        self.assert_code(media_field, ErrorCode.E_SCHEMA_UNKNOWN_FIELD)

        payload_field = copy.deepcopy(fixture)
        payload_field["payload"]["extra"] = True
        self.assert_code(payload_field, ErrorCode.E_SCHEMA_UNKNOWN_FIELD)

    def test_identifiers_and_scope_relationships_fail(self) -> None:
        fixture = load_fixture("turn.media.echo.json")
        cases = [
            ("uppercase UUID", lambda item: item.__setitem__("causationId", item["causationId"].upper())),
            ("malformed UUID", lambda item: item.__setitem__("correlationId", "bad")),
            ("global with sessionId", lambda item: (item.__setitem__("scope", "global"), item.__setitem__("sessionId", fixture["sessionId"]))),
            ("session without sessionId", lambda item: (item.__setitem__("scope", "session"), item.__setitem__("sessionId", None), item.__setitem__("turnId", None))),
            ("session with turnId", lambda item: (item.__setitem__("scope", "session"), item.__setitem__("turnId", fixture["turnId"]))),
            ("turn without ids", lambda item: (item.__setitem__("scope", "turn"), item.__setitem__("sessionId", None), item.__setitem__("turnId", None))),
        ]
        for label, mutate in cases:
            mutated = copy.deepcopy(fixture)
            mutate(mutated)
            with self.subTest(label=label):
                self.assert_code(mutated, ErrorCode.E_SCHEMA_INVALID_ID)

    def test_size_boundaries_check_raw_and_canonical_utf8(self) -> None:
        fixture = load_fixture("global.echo.json")
        raw = json.dumps(fixture, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.assertLessEqual(len(raw), MAX_JSON_ENVELOPE_BYTES)
        self.assertEqual(validate_envelope_bytes(raw).code, ErrorCode.OK)
        self.assertEqual(validate_envelope_bytes(b" " * (MAX_JSON_ENVELOPE_BYTES + 1)).code, ErrorCode.E_SCHEMA_OVERSIZE)

        oversized = copy.deepcopy(fixture)
        oversized["payload"]["message"] = "a" * MAX_JSON_ENVELOPE_BYTES
        self.assert_code(oversized, ErrorCode.E_SCHEMA_OVERSIZE)

    def test_inline_media_is_rejected(self) -> None:
        fixture = load_fixture("turn.media.echo.json")
        cases = [
            ("base64", "AAAA"),
            ("bytes", [1, 2, 3]),
            ("dataUri", "data:audio/wav;base64,AAAA"),
            ("path", "C:/tmp/audio.wav"),
            ("raw", [0, 1, 2]),
            ("url", "https://example.invalid/audio.wav"),
        ]
        for key, value in cases:
            mutated = copy.deepcopy(fixture)
            mutated["media"][0][key] = value
            with self.subTest(key=key):
                self.assert_code(mutated, ErrorCode.E_SCHEMA_INLINE_BASE64)

        payload_text = copy.deepcopy(fixture)
        payload_text["payload"]["metadata"]["url"] = "ordinary text, not a media locator"
        self.assert_code(payload_text, ErrorCode.OK)

    def test_metadata_numbers_are_safe_integers_in_both_runtimes(self) -> None:
        subprocess.run([PNPM, "--filter", "@hina/contracts", "build"], cwd=ROOT, check=True)
        fixture = load_fixture("global.echo.json")
        for number in [MIN_JS_SAFE_INTEGER, 0, MAX_JS_SAFE_INTEGER]:
            mutated = copy.deepcopy(fixture)
            mutated["payload"]["metadata"] = {"number": number}
            with self.subTest(valid=number):
                python_result = validate_envelope(mutated)
                self.assertEqual(python_result.code, ErrorCode.OK, python_result.detail)
                typescript_result = run_typescript_validation(mutated)
                self.assertEqual(typescript_result["code"], "OK", typescript_result.get("detail"))
                self.assertEqual(typescript_result["canonicalJson"], python_result.canonical_json)

        python_invalid_cases = [
            ("fractional float", 1.25),
            ("too large", MAX_JS_SAFE_INTEGER + 1),
            ("too small", MIN_JS_SAFE_INTEGER - 1),
        ]
        for label, number in python_invalid_cases:
            mutated = copy.deepcopy(fixture)
            mutated["payload"]["metadata"] = {"number": number}
            with self.subTest(python_invalid=label):
                self.assert_code(mutated, ErrorCode.E_SCHEMA_WRONG_TYPE)

        for label, number in [
            ("fractional number", 1.25),
            ("too large", MAX_JS_SAFE_INTEGER + 1),
            ("too small", MIN_JS_SAFE_INTEGER - 1),
        ]:
            mutated = copy.deepcopy(fixture)
            mutated["payload"]["metadata"] = {"number": number}
            with self.subTest(typescript_invalid=label):
                result = run_typescript_validation(mutated)
                self.assertEqual(result["code"], "E_SCHEMA_WRONG_TYPE", result.get("detail"))

    def test_integral_float_tokens_canonicalize_identically_from_raw_utf8(self) -> None:
        subprocess.run([PNPM, "--filter", "@hina/contracts", "build"], cwd=ROOT, check=True)
        fixture = load_fixture("global.echo.json")
        cases = [
            ("metadata decimal", "metadata", "1.0", 1),
            ("metadata exponent", "metadata", "1e2", 100),
            ("sequence decimal", "sequence", "1.0", 1),
        ]
        for label, field, token, expected in cases:
            raw = self._raw_with_numeric_token(fixture, field, token)
            with self.subTest(label=label):
                python_result = validate_envelope_bytes(raw)
                self.assertEqual(python_result.code, ErrorCode.OK, python_result.detail)
                typescript_result = run_typescript_validation_bytes(raw)
                self.assertEqual(typescript_result["code"], "OK", typescript_result.get("detail"))
                self.assertEqual(typescript_result["canonicalJson"], python_result.canonical_json)
                parsed = json.loads(python_result.canonical_json or "{}")
                if field == "metadata":
                    self.assertEqual(parsed["payload"]["metadata"]["number"], expected)
                else:
                    self.assertEqual(parsed["sequence"], expected)

    def test_fractional_and_out_of_range_tokens_fail_in_both_runtimes(self) -> None:
        subprocess.run([PNPM, "--filter", "@hina/contracts", "build"], cwd=ROOT, check=True)
        fixture = load_fixture("global.echo.json")
        cases = [
            ("metadata fractional", "metadata", "1.25"),
            ("metadata too large", "metadata", str(MAX_JS_SAFE_INTEGER + 1)),
            ("sequence fractional", "sequence", "1.25"),
            ("sequence too large", "sequence", str(MAX_JS_SAFE_INTEGER + 1)),
        ]
        for label, field, token in cases:
            raw = self._raw_with_numeric_token(fixture, field, token)
            with self.subTest(label=label):
                self.assertEqual(validate_envelope_bytes(raw).code, ErrorCode.E_SCHEMA_WRONG_TYPE)
                result = run_typescript_validation_bytes(raw)
                self.assertEqual(result["code"], "E_SCHEMA_WRONG_TYPE", result.get("detail"))

    def test_canonicalize_envelope_normalizes_without_mutating_input(self) -> None:
        value = {"sequence": 1.0, "payload": {"metadata": {"number": 2.0}}, "nested": [3.0, {"four": 4.0}]}
        original = copy.deepcopy(value)
        self.assertEqual(canonicalize_envelope(value), '{"nested":[3,{"four":4}],"payload":{"metadata":{"number":2}},"sequence":1}')
        self.assertEqual(value, original)
        self.assertIsInstance(value["sequence"], float)

    def _raw_with_numeric_token(self, fixture: dict, field: str, token: str) -> bytes:
        mutated = copy.deepcopy(fixture)
        if field == "metadata":
            mutated["payload"]["metadata"] = {"number": 0}
            raw = json.dumps(mutated, ensure_ascii=False, separators=(",", ":")).replace('"number":0', f'"number":{token}')
        elif field == "sequence":
            mutated["sequence"] = 0
            raw = json.dumps(mutated, ensure_ascii=False, separators=(",", ":")).replace('"sequence":0', f'"sequence":{token}')
        else:
            raise ValueError(field)
        return raw.encode("utf-8")

    def test_unicode_preserves_codepoints(self) -> None:
        fixture = load_fixture("global.echo.json")
        samples = [
            "Tieng Viet NFC: Toi yeu ngon ngu Viet Nam",
            "Tie\u0302ng Vie\u0323t NFD",
            "emoji: 😀✨",
            "combining: a\u0301o\u0323",
            "astral: \U0001f9d1\U0001f3fd\u200d\U0001f4bb",
            "rtl: مرحبا Hina",
        ]
        for sample in samples:
            mutated = copy.deepcopy(fixture)
            mutated["payload"]["message"] = sample
            with self.subTest(sample=sample):
                result = validate_envelope(mutated)
                self.assertEqual(result.code, ErrorCode.OK, result.detail)
                parsed = json.loads(result.canonical_json or "{}")
                self.assertEqual(parsed["payload"]["message"], sample)

    def test_deterministic_mutations_fail_closed_without_crashing(self) -> None:
        fixture = load_fixture("session.echo.json")
        mutations = [
            lambda item: item.__setitem__("schemaVersion", "1.1"),
            lambda item: item.__setitem__("occurredAt", "2026-07-24T00:00:00+07:00"),
            lambda item: item["payload"].__setitem__("locale", "vietnamese"),
            lambda item: item["media"].append({}),
            lambda item: item["payload"]["metadata"].__setitem__("nan", float("nan")),
        ]
        for index, mutate in enumerate(mutations):
            mutated = copy.deepcopy(fixture)
            mutate(mutated)
            with self.subTest(index=index):
                result = validate_envelope(mutated)
                self.assertFalse(result.ok)
                self.assertNotEqual(result.code, ErrorCode.E_FUZZ_RUNTIME_CRASH)

    def test_generation_drift_detection_uses_temp_projection(self) -> None:
        temp_root = DRIFT_WORK_ROOT / "case"
        if temp_root.exists():
            shutil.rmtree(temp_root)
        shutil.copytree(CONTRACTS, temp_root / "packages" / "contracts")
        generated = temp_root / "packages" / "contracts" / "src" / "hina_contracts" / "generated.py"
        generated.write_text(generated.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "contracts" / "generate_models.py"), "--check", "--root", str(temp_root)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("E_GEN_DRIFT", completed.stderr)

    def test_python_typescript_roundtrip_matches_canonical_json(self) -> None:
        subprocess.run([PNPM, "--filter", "@hina/contracts", "build"], cwd=ROOT, check=True)
        fixture = load_fixture("turn.media.echo.json")
        fixture["payload"]["metadata"] = {
            "ascii": "first",
            "\u0111i\u1ec3m": "Vietnamese key",
            "\U0001f600": "emoji key",
            "\U00010437": "astral key",
        }
        python_canonical = canonicalize_envelope(fixture)
        completed = subprocess.run(
            ["node", "packages/contracts/test/canonicalize.mjs"],
            input=json.dumps(fixture, ensure_ascii=False),
            cwd=ROOT,
            encoding="utf-8",
            text=True,
            capture_output=True,
            check=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["code"], "OK", result.get("detail"))
        self.assertEqual(result["canonicalJson"], python_canonical)
        reparsed = json.loads(result["canonicalJson"])
        self.assertEqual(canonicalize_envelope(reparsed), python_canonical)

    def test_compatibility_policy_initial_release_is_explicit(self) -> None:
        policy = json.loads((CONTRACTS / "compatibility-policy.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["catalogVersion"], "1.0")
        self.assertEqual(policy["disposition"], "initial_release")
        self.assertEqual(policy["supportedPreviousMajorVersions"], [])
        self.assertFalse(policy["migrationRequired"])

    def test_validation_benchmark_reports_budget_metrics(self) -> None:
        fixture = load_fixture("turn.media.echo.json")
        durations: list[float] = []
        for _ in range(25):
            validate_envelope(fixture)
        for _ in range(250):
            started = time.perf_counter()
            result = validate_envelope(fixture)
            durations.append((time.perf_counter() - started) * 1000)
            self.assertEqual(result.code, ErrorCode.OK, result.detail)
        ordered = sorted(durations)
        p50 = ordered[len(ordered) // 2]
        p95 = ordered[int(len(ordered) * 0.95)]
        maximum = ordered[-1]
        self.assertLessEqual(p95, 5.0, {"p50": p50, "p95": p95, "max": maximum})
