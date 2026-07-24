# Hina Dev Console

This is the owner-facing local application for manually exercising the real
M01 runtime and the M02 safety policy. It contains no simulated AI response.

From the repository root:

```powershell
pnpm start:dev-console
```

The command starts a persistent loopback-only service, opens
`http://127.0.0.1:8765/` and keeps running until `Ctrl+C`.

`pnpm smoke:dev-console` performs a short real startup/shutdown check without
opening a browser. It is a technical smoke test, not the interactive app.

The console can call the control API, connect to the realtime WebSocket, append
and deduplicate durable echo events, replay a stream, round-trip a binary media
frame, inspect bounded metrics and redacted error records, evaluate real
capability policy, operate emergency stop/mute/feature flags/revocation, and
inspect the SHA-256 chained safety audit.

After updating the source, restart the running console so its Python process
loads the new safety module.
