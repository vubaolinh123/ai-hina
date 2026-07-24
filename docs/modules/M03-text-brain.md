# M03 — Text brain

- Status: fast implementation complete; independent review and owner acceptance pending
- Branch: `codex/M03-text-brain`
- Base: `6c21754`
- Completed slices: `M03-S1`, `M03-S2`
- Next action: independent review, then owner manual application test

## M03-S1 implementation

- Loopback-only Ollama and OpenAI-compatible adapters use real HTTP requests.
- Provider responses stream token chunks; malformed/partial streams remain
  explicit failures and never switch to canned text.
- Timeout, retry-before-first-token and circuit breaker behavior are bounded.
- API keys are accepted from environment only and are reduced to a boolean in
  public status.
- Live `nvidia-smi` and OS RAM telemetry drive every model admission.
- A resource lease retains at least 2048 MiB VRAM headroom and is released on
  completion, error or cancellation.
- Higher-priority work can preempt a lower-priority preemptible lease and invoke
  its provider unload callback.
- Dev Console displays actual provider/model/circuit/VRAM state. An absent
  provider is shown as `unavailable`.

## M03-S1 fast gate

- [x] Text brain unit 11/11.
- [x] Safety unit 22/22 and core runtime 31/31 remain green.
- [x] Local test HTTP server covers Ollama JSONL and OpenAI-compatible SSE.
- [x] Real machine status returns HTTP 200, identifies RTX 5070 Ti telemetry,
  retains 2048 MiB headroom and reports the currently absent Ollama provider
  without fake output.

Model download and model-quality promotion are intentionally outside this
slice. `HINA_MODEL_PROVIDER`, `HINA_MODEL_BASE_URL`, `HINA_MODEL_NAME` and
optional `HINA_MODEL_API_KEY` select an already-running local provider.

## M03-S2 implementation

- Versioned frozen `hina.local.vi.v1` persona is separate from dynamic,
  session-scoped relationship state.
- Turn FSM enforces idle/listening/thinking/speaking/interrupted/error and one
  active turn per session.
- Context composer keeps the newest complete memory turns inside 65536 bytes and
  always states that no current screen/camera/game observation exists.
- Input must pass M02 moderation before context. Full provider output must pass
  outbound moderation before it reaches the browser or memory.
- Short-term memory stores successful sanitized pairs only; replay and clear are
  real runtime endpoints.
- Typed tool proposal JSON is schema-checked and pre-tool moderated. It is
  inspectable but no executor exists.
- Dev Console starts, polls, interrupts, replays and clears chat turns against
  the actual configured local provider.
- Turn failures are written to the redacted JSONL error log with turn, session,
  input hash and correlation identifiers but no raw input/output.

## M03-S2 fast gate

- [x] Text brain unit 22/22, including cancellation lease release.
- [x] Safety unit 22/22 and core runtime 32/32.
- [x] Contract suite 28 Python + 13 Node.
- [x] Real Dev Console startup/shutdown smoke.
- [x] Real-machine unavailable-provider probe returns `E_MODEL_UNAVAILABLE`,
  no assistant text, no raw email in logs, and a reportable correlation ID.

The 200+ golden conversation/model-quality benchmark, TTFT/tokens-per-second
baseline and deep repeat/soak gate remain deferred under the owner's fast
development rule. No model is quality-promoted by this implementation gate.
