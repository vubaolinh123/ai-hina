# M04 — Speech input

- Status: independent fast review passed; awaiting owner manual acceptance
- Branch: `codex/M04-speech-input`
- Base: `88d3dd72c3ae8ddc269fff371e30d6e6fc055407`
- Completed slices: `M04-S1` core audio/VAD/provider, `M04-S2` runtime API/Dev Console

## Runnable scope

The Dev Console records the owner's microphone into an in-memory PCM WAV or
accepts a local WAV file. The runtime decodes and normalizes that binary audio,
runs a deterministic silence gate, and sends admitted Vietnamese speech to the
real faster-whisper provider. The UI never fabricates a transcript when the
provider or model is unavailable.

CPU int8 is the safe default for the first runnable slice. The STT model is
loaded lazily and may be downloaded on the first transcription into
`var/cache/models/faster-whisper`. CUDA is opt-in and must use the shared
resource scheduler; the runtime falls back to the configured CPU profile rather
than bypassing the 2048 MiB VRAM headroom rule.

Raw microphone audio is never persisted. Returned transcripts remain owner
input: the console can copy one into the chat composer, but it never auto-sends
it to the LLM, memory, tools or an outbound channel.

## Fast-development evidence

- `pnpm test:fast`: 90 tests passed (22 safety, 22 text brain, 13 speech,
  33 core runtime).
- `pnpm test:contracts`: 41 tests passed (28 Python, 13 Node).
- `pnpm smoke:dev-console`: runtime and real browser-facing assets started on
  an ephemeral local port.
- `powershell -File tools/dev/Run-M04RealSttSmoke.ps1`: the pinned
  `Systran/faster-whisper-small` model downloaded, loaded and completed a real
  CPU inference. The generated English-voice sample is only a provider/runtime
  smoke and is not Vietnamese quality evidence.
- Provenance validation and CycloneDX SBOM generation passed.
- Independent GPT-5.5 review found one P1 in native inference timeout handling.
  The fix at `cba2a816e0d63f7d0c5756331374c0da9213cc02` keeps the provider in a
  fail-closed draining state and retains the GPU lease until the native worker
  really exits. The same reviewer re-ran the speech unit suite and confirmed
  the P1 closed with no remaining P0/P1 in the scoped re-check.

The owner can now run the Dev Console, record a microphone clip or select an
actual WAV file, transcribe it and manually copy the result into chat. Errors
show a correlation ID and are recorded in `var/logs/hina-runtime.jsonl` without
raw audio payload retention.

## Deferred promotion evidence

The accent/noise corpus, 1000-clip silence gate, WER/CER confidence intervals,
keyword recall, p95 latency benchmark, reconnect soak and deep release
verification remain deferred until the owner requests M04 promotion testing.
