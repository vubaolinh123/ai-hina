# M01-S1 gate decision

- Decision: **PASS, subject to the evidence commit passing remote Windows CI**
- Frozen source commit: `525e91895ea0c079f123bcad78691b7b8ddcee01`
- Frozen source tree: `893ba2d5d605295dabd0f68a09d43317e7258224`
- Branch: `module/M01-spine`
- Scope: contract catalog, EventEnvelope v1, generated Python/TypeScript
  projections and runtime validators

## Verification

- `pnpm test:contracts`: PASS.
- Frozen-SHA repeat gate: 20/20 consecutive runs, 0 failed.
- Per run: 28 Python tests and 13 Node tests.
- Required performance assertion: validation p95 remained within 5 ms in every
  run.
- Generator drift checks: PASS in Python and TypeScript.
- Cross-language Unicode/canonical round trips: PASS.
- Negative fixtures, duplicate-key detection, malformed/deep JSON, exact numeric
  token handling and size boundaries: PASS.
- npm dependency license evidence: real installed file and SHA-256 validation
  PASS.
- Initial and final HEAD/tree/tracked status were identical and clean.

Repeat gate time:

- Started: `2026-07-24T12:12:10.677287+00:00`
- Ended: `2026-07-24T12:18:49.317915+00:00`
- Duration: 398.64 seconds

## Review history

Before the owner switched future work to Solo-first, an independent read-only
review found four P1 issues in an earlier candidate. The primary fixed them in
`525e918`; a targeted re-review confirmed 4/4 closed with no remaining P0/P1.
No subagent was used for the final repeat gate or evidence assembly.

## Owner manual testing

M01-S1 is a library/foundation slice and has no interactive UI yet. Validation
failures return stable `ErrorCode` and redacted detail to callers. The
owner-facing structured error-log path and collection bundle are mandatory
deliverables of M01-S6; the contract is documented in
`docs/operations/OWNER_ERROR_REPORTING_VI.md`.

## Known limitations

- M01-S2 through M01-S6 and the M01 integration gate remain open.
- No LLM brain, STT, TTS, memory, avatar, game or livestream feature exists in
  this slice.
- Remote CI is authoritative for the evidence commit. A failed run invalidates
  this conditional PASS.
- Raw repeat output is local/CI evidence and is not tracked in Git; this file
  records its immutable source SHA, tree and result summary.

## Rollback

Rollback the M01-S1 correction to `264e1d7` only for diagnosis; that commit has
known P1 issues and must not be promoted. The last accepted pre-M01 baseline is
`aa7138e`.
