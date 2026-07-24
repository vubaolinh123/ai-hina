# M03 — Text brain

- Status: in progress
- Branch: `codex/M03-text-brain`
- Base: `6c21754`
- Completed slice: `M03-S1 — local model gateway, health and resource lease`
- Next slice: `M03-S2 — turn FSM, persona, short-term memory and real chat Console`

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
