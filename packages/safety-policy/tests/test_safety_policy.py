from __future__ import annotations

import json
import sys
import tempfile
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hina_safety import (  # noqa: E402
    AuditTrail,
    CapabilityManifest,
    SafetyPolicyError,
    SafetyPolicyService,
)


DEFAULT_MANIFEST = PACKAGE_ROOT / "manifests" / "default.v1.json"
MANIFEST_SCHEMA = PACKAGE_ROOT / "schemas" / "capability-manifest.v1.schema.json"
CORRELATION_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"


def _request(
    capability: str,
    *,
    trust: str = "owner",
    consume: bool = True,
    actor: str = "local-owner",
    session_id: str | None = SESSION_ID,
) -> dict[str, object]:
    return {
        "capability": capability,
        "actorId": actor,
        "trustLevel": trust,
        "correlationId": CORRELATION_ID,
        "sessionId": session_id,
        "consume": consume,
    }


def _control(action: str, **extra: object) -> dict[str, object]:
    return {
        "action": action,
        "actorId": "local-owner",
        "trustLevel": "owner",
        "correlationId": CORRELATION_ID,
        **extra,
    }


class SafetyPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=PACKAGE_ROOT)
        self.directory = Path(self.temporary.name)
        self.clock = 100.0
        self.now = datetime(2026, 7, 24, tzinfo=UTC)
        self.audit = AuditTrail(
            self.directory / "audit.jsonl",
            build_commit="test-build",
            now=lambda: self.now,
        )
        self.service = SafetyPolicyService(
            CapabilityManifest.load(DEFAULT_MANIFEST),
            self.audit,
            clock=lambda: self.clock,
            now=lambda: self.now,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_default_manifest_matches_published_schema(self) -> None:
        schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))
        manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(manifest)
        loaded = CapabilityManifest.from_json(manifest)
        self.assertEqual(loaded.manifest_id, "hina.local.default.v1")
        self.assertEqual(len(loaded.capabilities), 6)

    def test_unknown_critical_trust_feature_and_revocation_fail_closed(self) -> None:
        unknown = self.service.evaluate(_request("tool.unknown"))
        critical = self.service.evaluate(_request("tool.code.execute"))
        public = self.service.evaluate(_request("tool.safe.echo", trust="public"))
        feature_off = self.service.evaluate(_request("memory.promote"))

        self.assertEqual((unknown["decision"], unknown["reasonCode"]), ("deny", "unknown_capability"))
        self.assertEqual((critical["decision"], critical["reasonCode"]), ("deny", "critical_capability"))
        self.assertEqual((public["decision"], public["reasonCode"]), ("deny", "trust_not_allowed"))
        self.assertEqual((feature_off["decision"], feature_off["reasonCode"]), ("deny", "feature_disabled"))

        self.service.apply_control(_control("set_feature", feature="memoryPromotion", enabled=True))
        ask = self.service.evaluate(_request("memory.promote"))
        self.assertEqual((ask["decision"], ask["reasonCode"]), ("ask", "owner_confirmation_required"))

        self.service.apply_control(
            _control("set_revocation", capability="tool.safe.echo", enabled=True)
        )
        revoked = self.service.evaluate(_request("tool.safe.echo"))
        self.assertEqual((revoked["decision"], revoked["reasonCode"]), ("deny", "capability_revoked"))

    def test_expired_capability_denies(self) -> None:
        raw = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        raw["capabilities"][0]["expiresAt"] = (
            self.now - timedelta(seconds=1)
        ).isoformat().replace("+00:00", "Z")
        service = SafetyPolicyService(
            CapabilityManifest.from_json(raw),
            self.audit,
            clock=lambda: self.clock,
            now=lambda: self.now,
        )
        result = service.evaluate(_request("tool.safe.echo"))
        self.assertEqual((result["decision"], result["reasonCode"]), ("deny", "capability_expired"))

    def test_rate_limit_and_session_budget_use_controlled_time(self) -> None:
        raw = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        raw["capabilities"][0]["rateLimitPerMinute"] = 2
        raw["capabilities"][0]["sessionBudget"] = 3
        service = SafetyPolicyService(
            CapabilityManifest.from_json(raw),
            self.audit,
            clock=lambda: self.clock,
            now=lambda: self.now,
        )
        first = service.evaluate(_request("tool.safe.echo"))
        second = service.evaluate(_request("tool.safe.echo"))
        limited = service.evaluate(_request("tool.safe.echo"))
        self.assertTrue(first["consumed"])
        self.assertTrue(second["consumed"])
        self.assertEqual((limited["decision"], limited["reasonCode"]), ("deny", "rate_limit_exceeded"))

        self.clock += 61
        third = service.evaluate(_request("tool.safe.echo"))
        exhausted = service.evaluate(_request("tool.safe.echo"))
        self.assertEqual(third["decision"], "allow")
        self.assertEqual((exhausted["decision"], exhausted["reasonCode"]), ("deny", "session_budget_exhausted"))

    def test_owner_controls_enforce_emergency_mute_and_owner_trust(self) -> None:
        with self.assertRaises(SafetyPolicyError) as denied:
            self.service.apply_control(
                {
                    **_control("set_mute", enabled=False),
                    "trustLevel": "public",
                }
            )
        self.assertEqual(denied.exception.code, "E_SAFETY_CONTROL_DENIED")

        stopped = self.service.apply_control(_control("emergency_stop"))
        self.assertTrue(stopped["state"]["emergencyStopped"])
        blocked = self.service.evaluate(_request("tool.safe.echo"))
        self.assertEqual((blocked["decision"], blocked["reasonCode"]), ("deny", "emergency_stop"))

        self.service.apply_control(_control("emergency_reset"))
        allowed = self.service.evaluate(_request("tool.safe.echo", consume=False))
        self.assertEqual(allowed["decision"], "allow")

        self.service.apply_control(_control("set_feature", feature="streamOutput", enabled=True))
        self.service.apply_control(_control("set_mute", enabled=True))
        muted = self.service.evaluate(_request("stream.output"))
        self.assertEqual((muted["decision"], muted["reasonCode"]), ("deny", "operator_muted"))

    def test_audit_hash_chain_hides_actor_and_detects_tampering(self) -> None:
        self.service.evaluate(_request("tool.safe.echo", actor="owner@example.test"))
        text = self.audit.path.read_text(encoding="utf-8")
        self.assertNotIn("owner@example.test", text)
        self.assertEqual(AuditTrail(self.audit.path).status()["records"], 1)

        record = json.loads(text)
        record["reasonCode"] = "tampered"
        self.audit.path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        failed_closed = self.service.evaluate(_request("tool.safe.echo"))
        self.assertEqual(
            (failed_closed["decision"], failed_closed["reasonCode"], failed_closed["consumed"]),
            ("deny", "audit_unavailable", False),
        )
        with self.assertRaises(SafetyPolicyError) as raised:
            AuditTrail(self.audit.path)
        self.assertEqual(raised.exception.code, "E_SAFETY_AUDIT_INVALID")

    def test_arbitrary_prompt_or_secret_fields_are_rejected_before_audit(self) -> None:
        malicious = {
            **_request("tool.safe.echo"),
            "prompt": "password=must-never-enter-audit",
        }
        with self.assertRaises(SafetyPolicyError):
            self.service.evaluate(malicious)
        self.assertFalse(self.audit.path.exists())


class _UnavailableAudit:
    last_hash = "0" * 64

    def append(self, **_: object) -> dict[str, object]:
        raise SafetyPolicyError("E_SAFETY_AUDIT_UNAVAILABLE", "simulated failure")

    def status(self) -> dict[str, object]:
        return {"verified": False, "records": 0, "lastHash": self.last_hash}

    def recent(self, _: int) -> list[dict[str, object]]:
        return []


class EmergencyFailSafeTests(unittest.TestCase):
    def test_emergency_stop_applies_even_when_audit_is_unavailable(self) -> None:
        service = SafetyPolicyService(
            CapabilityManifest.load(DEFAULT_MANIFEST),
            _UnavailableAudit(),  # type: ignore[arg-type]
        )
        result = service.apply_control(_control("emergency_stop"))
        self.assertTrue(result["state"]["emergencyStopped"])
        self.assertFalse(result["auditRecorded"])

        with self.assertRaises(SafetyPolicyError):
            service.apply_control(_control("emergency_reset"))
        self.assertTrue(service.controller.snapshot()["emergencyStopped"])

        decision = service.evaluate(_request("tool.safe.echo"))
        self.assertEqual(decision["decision"], "deny")
        self.assertEqual(decision["reasonCode"], "audit_unavailable")
        self.assertTrue(service.controller.snapshot()["emergencyStopped"])


if __name__ == "__main__":
    unittest.main()
