from __future__ import annotations

import copy
import unittest

from tools.sbom.generate_sbom import (
    load_npm_evidence,
    npm_lock_components,
    npm_lock_scopes,
    parse_pnpm_lock,
    validate_npm_evidence,
)


class SbomContractTests(unittest.TestCase):
    def test_npm_evidence_matches_frozen_pnpm_lock(self) -> None:
        lock = parse_pnpm_lock()
        scopes = npm_lock_scopes(lock)
        evidence = validate_npm_evidence(lock, scopes)
        self.assertEqual(set(scopes), set(evidence))
        self.assertEqual(scopes["ajv@8.17.1"], "runtime")
        self.assertEqual(scopes["typescript@5.9.3"], "build")

    def test_npm_evidence_drift_fails_closed(self) -> None:
        lock = parse_pnpm_lock()
        scopes = npm_lock_scopes(lock)
        for field, value in [
            ("integrity", "sha512-not-the-lock"),
            ("purl", "pkg:npm/ajv@0.0.0"),
            ("scope", "build"),
        ]:
            evidence = copy.deepcopy(load_npm_evidence())
            evidence["packages"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                validate_npm_evidence(lock, scopes, evidence)

        missing = copy.deepcopy(load_npm_evidence())
        missing["packages"].pop()
        with self.assertRaisesRegex(ValueError, "evidence mismatch"):
            validate_npm_evidence(lock, scopes, missing)

    def test_npm_sbom_components_include_integrity_scope_license_and_purls(self) -> None:
        components = npm_lock_components()
        by_name = {component["name"]: component for component in components}
        for name in [
            "ajv",
            "fast-deep-equal",
            "fast-uri",
            "json-schema-traverse",
            "require-from-string",
            "typescript",
        ]:
            with self.subTest(name=name):
                component = by_name[name]
                self.assertTrue(component["purl"].startswith(f"pkg:npm/{name}@"))
                self.assertTrue(component["licenses"][0]["license"]["id"])
                self.assertTrue(component["externalReferences"][0]["url"].startswith("https://github.com/"))
                properties = {item["name"]: item["value"] for item in component["properties"]}
                self.assertIn(properties["hina:dependency-scope"], {"runtime", "build"})
                self.assertTrue(properties["hina:pnpm-integrity"].startswith("sha512-"))
                self.assertTrue(properties["hina:license-evidence"].startswith("packages/contracts/npm-license-evidence.v1.json#"))

        self.assertEqual(by_name["fast-uri"]["licenses"][0]["license"]["id"], "BSD-3-Clause")


if __name__ == "__main__":
    unittest.main()
