# Hina Dev Console

This is the owner-facing local application for manually exercising the real
M01 runtime, M02 safety policy, M03 local text brain and M04 local speech input.
It contains no simulated AI response or transcript.

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
It also reports real local model/VRAM state and supports starting, polling,
interrupting and replaying moderated chat turns. Provider output stays internal
until the complete response passes outbound moderation.
M04 can record the owner microphone or accept a WAV file, send binary audio to
the real loopback endpoint, run VAD and pinned faster-whisper, then copy a real
Vietnamese transcript into the chat composer without auto-sending it. Raw audio
is never persisted.

After updating the source, restart the running console so its Python process
loads the new safety, text-brain and speech modules.
