# M02 — Safety, permissions, moderation and audit

- Status: in progress; M02-S1 implemented
- Branch: `codex/M02-safety`
- Base: `196b38e`
- Completed slice: `M02-S1 — capability policy, operator controls and audit spine`
- Next slice: `M02-S2 — trust boundary, sanitation evidence and redaction`

## Slice sequence

1. M02-S1: capability manifest, allow/ask/deny, budgets, revocation, feature
   flags, emergency controls and hash-chained audit.
2. M02-S2: trust-boundary normalization, prompt/input sanitation evidence and
   secret/PII redaction.
3. M02-S3: pre-tool, pre-TTS and outbound moderation with fail-closed adapters.
4. M02 integration and owner manual acceptance.

M02-S1 intentionally exposes only local policy decisions and control state. It
does not execute a tool, produce speech, promote memory or send stream output.

## M02-S1 fast gate

- [x] Versioned manifest and JSON Schema define six initial capabilities.
- [x] Unknown, expired, revoked, critical and feature-disabled capabilities deny.
- [x] Allow decisions consume monotonic rate and bounded session budget only
  after audit append succeeds.
- [x] Owner-only controls manage emergency stop, mute, feature flags and
  revocation.
- [x] Emergency stop applies even if audit writing is unavailable.
- [x] Audit records exclude raw prompt/context, hash actor identity and form a
  verified SHA-256 chain.
- [x] Runtime exposes bounded safety GET/POST endpoints on loopback.
- [x] Dev Console provides a real capability evaluator and operator controls.
- [x] Safety unit 8/8, core runtime 31/31, contract 28 Python + 13 Node and
  real startup smoke pass once; deep verification deferred.
