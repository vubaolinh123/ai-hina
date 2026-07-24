# M01 — Contracts, config, lifecycle and observability spine

- Status: in progress
- Branch: `module/M01-spine`
- Base: `aa7138e`
- Active slice: `M01-S1 — contract catalog and EventEnvelope v1`

## Slice sequence

1. M01-S1: contract catalog, EventEnvelope v1, generated Python/TypeScript
   models, runtime validators and cross-language fixtures.
2. M01-S2: bounded queues, deadlines, cancellation and idempotency primitives.
3. M01-S3: durable journal/outbox/inbox, ACK, resume and replay.
4. M01-S4: control plane, realtime WebSocket and binary-media transport.
5. M01-S5: service registry/supervisor and 100-cycle lifecycle test.
6. M01-S6: structured logs, trace/metric API, ResourceLease and fake providers.
7. M01 integration gate: replay, crash/reconnect, compatibility, resource and
   leak suites across every slice.

## Owner manual-test logging requirement

- M01-S6 must provide local structured error logs and an owner-facing collection
  guide before any interactive feature is handed off for manual testing.
- A caught runtime failure records timestamp, component, operation, stable error
  code and available correlation/session/turn identifiers.
- Logs redact secrets, raw PII and hidden reasoning. Logging failure never
  replaces the original failure.
- M01-S1 validators remain side-effect free: callers receive stable
  `ErrorCode`/detail values and the future runtime boundary owns the log record.

## M01-S1 gate

- [x] Module brief created from the M00 contract.
- [x] Wave A architecture, OSS and QA design reviewed.
- [x] Contract schemas frozen.
- [x] Python and TypeScript projections generated deterministically.
- [x] Runtime boundary validation implemented in both languages.
- [x] Negative, Unicode, oversize and cross-language tests pass.
- [x] Deterministic suite passes 20 consecutive runs.
- [x] Independent QA and safety review pass on frozen SHA.
- [ ] Slice evidence recorded and pushed.

M01 remains open after M01-S1. Do not start M02 until every M01 slice and the
M01 integration gate pass.
