# M02 — Safety, permissions, moderation and audit

- Status: fast-promoted; owner manual acceptance pending
- Branch: `codex/M02-safety`
- Base: `196b38e`
- Completed slices: `M02-S1`, `M02-S2`, `M02-S3`
- Next module: `M03 — text brain`

## Slice sequence

1. M02-S1: capability manifest, allow/ask/deny, budgets, revocation, feature
   flags, emergency controls and hash-chained audit.
2. M02-S2: trust-boundary normalization, prompt/input sanitation evidence and
   secret/PII redaction.
3. M02-S3: pre-tool, pre-TTS and outbound moderation with fail-closed adapters.
4. M02 integration and owner manual acceptance.

M02 intentionally exposes policy, sanitation and moderation decisions only. It
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

## M02-S2 fast gate

- [x] Fixed source registry derives trust; callers cannot submit a trust upgrade.
- [x] NFKC normalization removes unsafe formatting before VI/EN injection checks.
- [x] Common bearer/API credentials, secret assignments, email and Vietnamese
  phone numbers are redacted.
- [x] HMAC-bound evidence ties sanitized text to source, trust, session and
  correlation identifiers.
- [x] Any evidence marked unsafe is rejected at the ContextBundle boundary,
  including authenticated and trusted-local sources.
- [x] Dev Console calls the real sanitation and ContextBundle endpoints.

## M02-S3 fast gate

- [x] Input, pre-tool, pre-TTS and outbound surfaces return explicit
  `allow | block | quarantine` decisions.
- [x] Pre-tool accepts a typed proposal only and applies the capability authority.
- [x] Generated shell, PowerShell, JavaScript and Python execution requests are
  blocked; no executor is present.
- [x] Hidden reasoning and redacted sensitive data cannot reach TTS/outbound.
- [x] Emergency stop, mute, moderation failure and audit failure fail closed.
- [x] Browser contains no duplicated allow/block rules; Moderation Lab calls the
  loopback backend.
- [x] Final M02 fast gate: safety unit 22/22, core runtime 31/31, contract
  28 Python + 13 Node and real startup smoke pass once.

Repeat, soak and deep release verification remain deferred until the owner asks.
