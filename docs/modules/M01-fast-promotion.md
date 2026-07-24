# M01 fast-development promotion

- Candidate SHA: `bcbd59e9453dc63ab305d331ba73c9a7983e189c`
- Branch: `module/M01-spine`
- Decision: promoted for the next development module
- Owner acceptance signal: owner started the persistent Dev Console and requested
  continuation to the next planned task.

## Evidence used

| Command | Result |
| --- | --- |
| `pnpm test:fast` | 30/30 Python tests pass |
| `pnpm test:contracts` | 28 Python tests and 13 Node tests pass |
| `pnpm smoke:dev-console` | Real loopback application starts and shuts down cleanly |
| `node tools/dev/check-node-workspace.mjs` | Workspace check pass |
| `pnpm install --lockfile-only --frozen-lockfile` | Lockfile check pass |

The fast suite covers contracts, validation, bounded queues, deadlines,
idempotency, durable SQLite state, realtime WebSocket, binary frames, lifecycle,
observability, resource leases, the persistent application assembly, static
security headers, bounded error retrieval and resource cleanup.

## Deferred release evidence

Per the owner-approved fast-development workflow, this promotion does not claim
release readiness and does not include:

- 20-run repeat verification;
- 100 lifecycle cycles;
- stress, soak, chaos or long-running leak measurement;
- independent-agent review or frozen-SHA release evidence bundle.

Those checks remain mandatory only when the owner requests deep verification or
release preparation. They do not block opening M02 for normal development.
