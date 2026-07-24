# Hina core runtime

M01-S2 and M01-S3 provide standard-library runtime primitives used by later
workers:

- bounded async queues with explicit overflow policies;
- monotonic deadlines and cooperative cancellation;
- bounded in-memory idempotency with concurrent call coalescing;
- SQLite journal/outbox/inbox with delivery leases, ACK/NACK and ordered replay;
- a visible CLI demo with redacted JSONL error records.

Run from the repository root:

```powershell
pnpm demo:m01-s2
pnpm demo:m01-s3
pnpm test:fast
```

Demo errors are written to `var/logs/m01-s2-demo.jsonl`.
The durable demo keeps its SQLite database at `var/data/m01-s3-demo.sqlite3`
and error log at `var/logs/m01-s3-demo.jsonl`.
