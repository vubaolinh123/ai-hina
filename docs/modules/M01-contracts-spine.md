# M01 — Contracts, config, lifecycle and observability spine

- Status: in progress
- Branch: `module/M01-spine`
- Base: `aa7138e`
- Completed slices:
  - `M01-S1 — contract catalog and EventEnvelope v1`
  - `M01-S2 — bounded queues, deadlines, cancellation and idempotency`
  - `M01-S3 — durable journal/outbox/inbox, ACK, resume and replay`
  - `M01-S4 — control plane, realtime WebSocket and binary-media transport`
  - `M01-S5 — service registry/supervisor and lifecycle`
  - `M01-S6 — observability, ResourceLease, fake providers and replay harness`
- Next: `M01 integration gate` (only when the owner requests deep verification)

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
- [x] Slice evidence recorded and pushed.

## M01-S2 fast gate

- [x] Validated module brief with standard-library-only scope.
- [x] Hard-cap queue supports wait, reject-new and drop-oldest policies.
- [x] Monotonic deadlines and cooperative cancellation clean pending waits.
- [x] Concurrent duplicate operations coalesce; completed results replay until
  TTL expiry and the registry remains bounded.
- [x] Owner CLI demo shows queue/drop/timeout/cancel/deduplicate behavior.
- [x] Expected failures write redacted JSONL records with stable error codes and
  correlation IDs.
- [x] Focused fast unit suite passes once on the owner machine.

## M01-S3 fast gate

- [x] Validated module brief with SQLite standard-library-only persistence.
- [x] Journal append and inbox receive reject conflicting reuse while ignoring
  byte-identical duplicate delivery.
- [x] Outbox claims are bounded and use expiring leases; ACK is idempotent and
  unacknowledged work is reclaimed after process restart.
- [x] Inbox checkpoint advances only through contiguous processed sequences.
- [x] Ordered journal replay and durable state survive database close/reopen.
- [x] Owner CLI demo shows append, duplicate suppression, crash recovery, ACK,
  resume and replay behavior.
- [x] Expected durable conflict writes one redacted JSONL error record.
- [x] Focused fast unit suite passes once on the owner machine.

## M01-S4 fast gate

- [x] Validated module brief with standard-library-only transport scope.
- [x] OpenAPI, AsyncAPI and fixed binary-media header contracts are published.
- [x] Control plane exposes bounded health/version/config JSON on loopback only.
- [x] WebSocket version 13 requires the `hina.realtime.v1` subprotocol, masked
  client frames and local browser origin.
- [x] Event messages pass EventEnvelope v1 validation and durable events are
  journaled before acceptance; reconnect can resume bounded journal batches.
- [x] Binary media round-trips with opcode 2 and never enters base64 JSON.
- [x] Invalid event, external origin and unmasked frame paths fail closed and
  write redacted local error records with stable codes.
- [x] Owner can run an ephemeral demo or a persistent server.
- [x] Focused fast suite passes once with all M01-S2 through M01-S4 tests.

## M01-S5 fast gate

- [x] Validated module brief with standard-library-only lifecycle scope.
- [x] Registry rejects duplicate, missing and cyclic service graphs.
- [x] Supervisor starts dependencies in topological order and shuts down in
  reverse order with monotonic per-service timeouts.
- [x] Partial startup failure rolls back every attempted service; a stop failure
  does not skip remaining services and can be retried.
- [x] Registry is immutable while services are active and unlocks after clean
  shutdown.
- [x] Fast five-cycle unit gate adds no pending asyncio tasks.
- [x] Owner demo supervises the real durable store and control server, obtains a
  ready health response, then closes both resources cleanly.
- [x] A separate `pnpm test:lifecycle:100` command exists for owner-requested
  deep verification; it is intentionally not run in the normal fast loop.
- [x] Focused fast suite passes once with all M01-S2 through M01-S5 tests.

## M01-S6 fast gate

- [x] Validated module brief with standard-library-only observability/resource
  scope and deterministic local fake providers.
- [x] JSONL spans are bounded, nested and secret-redacted; a trace write failure
  cannot replace the runtime exception.
- [x] Metric names/labels use a low-cardinality allowlist and series capacity is
  a hard bound.
- [x] Resource admission, expiry and idempotent release preserve at least
  2048 MiB reserved VRAM headroom.
- [x] Fake model/speech/memory/tool providers are deterministic; memory requires
  explicit consent and tools use a fixed non-code-execution allowlist.
- [x] Turn replay validates EventEnvelope v1, rejects conflicting reuse and
  executes model/speech once for duplicate delivery.
- [x] Owner error-report command collects at most 100 redacted error records and
  records build identity without allowing logging failure to mask the source
  error.
- [x] Owner demo produces traces, metrics, one redacted capacity error/report,
  a Vietnamese fake response and zero active leases at exit.
- [x] Focused fast suite passes once with all M01-S2 through M01-S6 tests.

All M01 product slices are implemented. M01 remains open for the deferred
integration/deep gate requested by the owner. Do not start M02 until the
M01 integration gate pass.
