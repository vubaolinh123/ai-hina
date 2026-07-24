# Hina core runtime

M01-S2 introduces standard-library runtime primitives used by later workers:

- bounded async queues with explicit overflow policies;
- monotonic deadlines and cooperative cancellation;
- bounded in-memory idempotency with concurrent call coalescing;
- a visible CLI demo with redacted JSONL error records.

Run from the repository root:

```powershell
pnpm demo:m01-s2
pnpm test:fast
```

Demo errors are written to `var/logs/m01-s2-demo.jsonl`.

