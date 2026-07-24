# Hina Dev Console

This is the owner-facing local application for manually exercising the real
M01 runtime, M02 safety policy, M03 local text brain, M04 local speech input,
M05 local Vietnamese speech output, M06 consent-gated long-term memory and the
M07 renderer-safe avatar stage. It contains no simulated AI response,
transcript, audio, memory or backend activity.

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
The UI is an admin-style hash-routed dashboard:

- `#/overview` shows runtime readiness and describes each area;
- `#/companion` groups text chat, STT and TTS;
- `#/avatar` renders typed turn/TTS cues and operator safety controls;
- `#/memory` handles candidate consent and active memory lifecycle;
- `#/safety` contains policy, sanitation, moderation and audit controls;
- `#/runtime` groups events, replay, binary frames, metrics, errors and activity.

Every page explains its purpose in plain Vietnamese for non-developers.
The header and management navigation stay visible while only the selected
page content scrolls. Each page starts with a short “when to use” guide, and
form help text is visually separated from its control.
It also reports real local model/VRAM state and supports starting, polling,
interrupting and replaying moderated chat turns. Provider output stays internal
until the complete response passes outbound moderation.
M04 can record the owner microphone or accept a WAV file, send binary audio to
the real loopback endpoint, run VAD and pinned faster-whisper, then copy a real
Vietnamese transcript into the chat composer without auto-sending it. Raw audio
is never persisted.
M05 can synthesize owner-entered text or completed moderated chat responses
through pinned VieNeu ONNX int8, play the returned 48 kHz mono WAV, and cancel
or stop playback when the owner starts speaking. Complete text passes pre-TTS
moderation before inference; voice cloning and runtime audio/text retention are
disabled.
M06 proposes sanitized candidates without auto-promotion. Owner decisions,
versions, trust, source, sensitivity and TTL are authoritative in SQLite.
Qdrant runs in persistent local mode as a rebuildable derived index. Search
hits are revalidated against SQLite; deletion returns a receipt only after both
stores reconcile. Owner memory enters chat only as delimited untrusted user-role
data and is never retrieved for public/viewer turns.
M07 displays the typed avatar states from the runtime and analyzes the real WAV
already playing in the browser to drive mouth amplitude. Manual visual checks
are labeled `manual-preview`. The current repository-original SVG/CSS asset is
an honest fallback (`vrmLoaded=false`), not a VRM or Live2D model.

After updating the source, restart the running console so its Python process
loads the new safety, text-brain, speech, memory and avatar modules.
