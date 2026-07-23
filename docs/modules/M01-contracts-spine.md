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

## M01-S1 gate

- [x] Module brief created from the M00 contract.
- [x] Wave A architecture, OSS and QA design reviewed.
- [ ] Contract schemas frozen.
- [ ] Python and TypeScript projections generated deterministically.
- [ ] Runtime boundary validation implemented in both languages.
- [ ] Negative, Unicode, oversize and cross-language tests pass.
- [ ] Deterministic suite passes 20 consecutive runs.
- [ ] Independent QA and safety review pass on frozen SHA.
- [ ] Slice evidence recorded and pushed.

M01 remains open after M01-S1. Do not start M02 until every M01 slice and the
M01 integration gate pass.
