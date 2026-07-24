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
  - `M01-S6 — observability, ResourceLease, test providers and replay harness`
  - `M01-S7 — owner-facing persistent Dev Console`
- Next: `M01 integration gate` (chỉ chạy khi owner yêu cầu deep verification)

## Slice sequence

1. M01-S1: contract catalog, EventEnvelope v1, generated Python/TypeScript
   models, runtime validators và cross-language fixtures.
2. M01-S2: bounded queues, deadlines, cancellation và idempotency primitives.
3. M01-S3: durable journal/outbox/inbox, ACK, resume và replay.
4. M01-S4: control plane, realtime WebSocket và binary-media transport.
5. M01-S5: service registry/supervisor và lifecycle.
6. M01-S6: structured logs, trace/metric API, ResourceLease và test providers.
7. M01-S7: ứng dụng local chạy lâu dài để owner thao tác với runtime thật.
8. M01 integration gate: replay, crash/reconnect, compatibility, resource và
   leak suites xuyên suốt các slice.

## Owner manual-test logging requirement

- Runtime ghi lỗi có cấu trúc vào `var/logs/hina-runtime.jsonl`.
- Bản ghi lỗi có timestamp, component, operation, stable error code và các
  correlation/session/turn identifier khi có.
- Logs che secret, raw PII và hidden reasoning. Logging failure không được thay
  thế lỗi gốc.
- Dev Console chỉ đọc tối đa 100 bản ghi đã redaction và không nhận path tùy ý.

## M01-S1 gate

- [x] Contract schemas và compatibility policy được đóng băng.
- [x] Python/TypeScript projections được generate deterministic.
- [x] Runtime boundary validation hoạt động ở cả hai ngôn ngữ.
- [x] Negative, Unicode, oversize và cross-language tests pass.
- [x] Deterministic suite đã pass 20 lần và independent review ở slice này.

## M01-S2 fast gate

- [x] Hard-cap queue hỗ trợ wait, reject-new và drop-oldest.
- [x] Monotonic deadline và cancellation dọn pending waits.
- [x] Concurrent duplicate operations được coalesce và cache có giới hạn.
- [x] Smoke harness kiểm tra queue/drop/timeout/cancel/deduplicate.
- [x] Expected failure ghi redacted JSONL với stable error code.

## M01-S3 fast gate

- [x] SQLite journal/inbox từ chối conflicting reuse và bỏ qua duplicate giống hệt.
- [x] Outbox lease có hạn; ACK idempotent; unacknowledged work được reclaim.
- [x] Inbox checkpoint chỉ tiến qua contiguous processed sequence.
- [x] Ordered replay và durable state sống qua close/reopen.
- [x] Smoke harness kiểm tra append, dedupe, crash recovery, ACK và replay.

## M01-S4 fast gate

- [x] OpenAPI, AsyncAPI và fixed binary-media header được publish.
- [x] Control plane chỉ bind loopback và trả health/version/config.
- [x] WebSocket yêu cầu subprotocol, masked client frames và local origin.
- [x] Durable event được journal trước acceptance; reconnect có bounded replay.
- [x] Binary media dùng opcode 2, không đi qua base64 JSON.
- [x] Invalid event, external origin và unmasked frame fail closed.

## M01-S5 fast gate

- [x] Registry từ chối duplicate, missing và cyclic dependency graph.
- [x] Supervisor start theo topological order và stop theo reverse order.
- [x] Partial startup failure rollback; stop failure không bỏ qua service còn lại.
- [x] Fast five-cycle test không để pending asyncio task.
- [x] `pnpm test:lifecycle:100` tồn tại nhưng chỉ chạy khi owner yêu cầu.

## M01-S6 fast gate

- [x] JSONL spans bounded, nested và secret-redacted.
- [x] Metric names/labels có allowlist và hard capacity.
- [x] Resource admission giữ ít nhất 2048 MiB VRAM headroom.
- [x] Deterministic test providers không chạy generated code.
- [x] Turn replay validate EventEnvelope và coalesce duplicate execution.
- [x] Owner error-report command thu tối đa 100 redacted records.

## M01-S7 fast gate

- [x] Module brief định nghĩa rõ đây là application thật, không giả lập AI.
- [x] `pnpm start:dev-console` chạy service persistent tại loopback cho đến
  `Ctrl+C`.
- [x] Browser client gọi HTTP và WebSocket thật trên cùng runtime origin.
- [x] Owner gửi durable event, thử dedupe, replay SQLite và binary opcode 2.
- [x] Owner xem bounded metrics và redacted error records ngay trên console.
- [x] Static assets dùng allowlist, CSP, no-store, nosniff và deny framing.
- [x] Unit tests bao phủ static serving, metrics, error bound/redaction và
  application shutdown.
- [x] Fast suite pass 30/30; contract suite pass 28 Python và 13 Node tests.

Các product slice M01 đã có mã chạy. M01 vẫn mở vì integration/deep gate được
owner chủ động hoãn. Không mở M02 trước khi gate này pass.
