# Hina core runtime

M01-S2 through M01-S6 provide standard-library runtime primitives used by later
workers:

- bounded async queues with explicit overflow policies;
- monotonic deadlines and cooperative cancellation;
- bounded in-memory idempotency with concurrent call coalescing;
- SQLite journal/outbox/inbox with delivery leases, ACK/NACK and ordered replay;
- loopback-only health/version/config endpoints and a WebSocket realtime plane;
- binary media frames that never place media bytes in base64 JSON;
- deterministic service dependency ordering, startup rollback and graceful
  reverse shutdown;
- bounded JSONL traces, low-cardinality metrics and redacted owner error reports;
- resource leases that preserve at least 2048 MiB VRAM headroom;
- deterministic fake providers and idempotent turn replay;
- a visible CLI demo with redacted JSONL error records.

Run from the repository root:

```powershell
pnpm demo:m01-s2
pnpm demo:m01-s3
pnpm demo:m01-s4
pnpm demo:m01-s5
pnpm demo:m01-s6
pnpm test:fast
```

Run the persistent local control plane with:

```powershell
pnpm start:control
pnpm report:errors
```

The explicit deep lifecycle command is available but is not part of the normal
fast loop:

```powershell
pnpm test:lifecycle:100
```

Demo errors are written to `var/logs/m01-s2-demo.jsonl`.
The durable demo keeps its SQLite database at `var/data/m01-s3-demo.sqlite3`
and error log at `var/logs/m01-s3-demo.jsonl`.
The realtime demo writes `var/data/m01-s4-demo.sqlite3` and
`var/logs/m01-s4-demo.jsonl`. The persistent server defaults to
`http://127.0.0.1:8765` and logs to `var/logs/hina-runtime.jsonl`.
The lifecycle demo writes `var/data/m01-s5-demo.sqlite3` and only creates
`var/logs/m01-s5-demo.jsonl` if a caught lifecycle error occurs.
The observability demo writes traces/errors under `var/logs`, metrics under
`var/metrics` and the bounded report under `var/reports`.
