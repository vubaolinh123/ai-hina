# M03 — Text brain

- Status: M03-S4/S5 are historical fast candidates; M08-S21/S22 now own the
  active Qwen3.5 4B Q8_0 runtime and adaptive conversation budgets; owner
  manual acceptance remains authoritative
- Branch: `main`
- Base: `6c21754`
- Completed slices: `M03-S1`, `M03-S2`, `M03-S3`, `M03-S4`
- Reviewed candidate: `88d3dd72c3ae8ddc269fff371e30d6e6fc055407`
- Next action: owner manual application test while M04 proceeds

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

## Independent review

- [x] Candidate SHA and remote branch matched with a clean tree.
- [x] Fast unit gate passed: safety 22/22, text brain 22/22, runtime 32/32.
- [x] Contract gate passed: Python 28/28 and Node 13/13.
- [x] Real Dev Console startup smoke passed.
- [x] No P0/P1 blocker was confirmed before the time-boxed reviewer completed.

The reviewer did not run repeat/soak/deep model-quality verification. Those
checks remain explicitly deferred by the owner's fast-development policy.

## M03-S4 concise VTuber response maintenance

- `hina.prompt.v2` answers directly in one or two short sentences and usually
  no more than 45 Vietnamese words; three sentences/80 words are the normal
  ceiling when context is necessary.
- Repeating the question, unnecessary self-introduction, generic disclaimers
  and trailing offers to help are explicitly discouraged.
- Explicit requests for detail, code, lists or step-by-step output override the
  concise default. Missing context produces one short clarification question.
- The gateway default output budget is 192 tokens instead of 512 and remains
  configurable with `HINA_MODEL_MAX_TOKENS`; no generated string is cut by a
  post-processor.
- Future M11 training targets the general traits “brief, reactive and lightly
  playful” using repository-authored, synthetic-reviewed or consented data.
  Neuro-sama transcripts, catchphrases, private models and datasets are not
  copied.
- One live Ollama `qwen3.5:4b` check for “Bạn là ai?” completed with
  `hina.prompt.v2` in one sentence/22 words, with no trailing offer.

## M03-S5 shared 8B Thinking maintenance (2026-07-28)

- Default text model is now the pinned
  `qwen3-vl:8b-thinking-q4_K_M`. Hina does not load or route to a second
  Instruct checkpoint for text. M08 screen reading is deliberately outside
  this gateway and uses its own Ollama Cloud or lightweight local provider.
- A deterministic router uses a raw same-weight prompt with a pre-closed private
  think block for simple text. Requests containing reasoning terms, arithmetic,
  long/multi-question/code input use native hidden thinking.
- Provider output reads only final `content`; Ollama's private `thinking` field
  is never streamed to the renderer. Qwen control tokens inside untrusted
  messages are neutralized before the raw fast path is constructed.
- Runtime context is 8.192 tokens, normal text output is 192 tokens and
  thinking is bounded at 768 tokens. Admission is capped at one
  second and provider work at nine seconds, yielding a default turn deadline
  of ten seconds. Retries are disabled to keep that deadline truthful.
- Every Ollama request asks for full GPU offload and `keep_alive=0`; the shared
  scheduler reserves 8.192 MiB VRAM while retaining at least 2.048 MiB
  headroom for the machine.
- Real RTX 5070 Ti smoke: simple text 2,939 s, arithmetic reasoning 6,160 s,
  and, before the provider split, routine image description 4,363 s. The image
  measurement is retained only as historical evidence and is not the active
  M08 route. Highest observed total physical GPU use was 9.975 MiB of
  16.303 MiB. Exact distribution hashes and settings are in
  `ml/models/manifests/qwen3-vl-8b-thinking-q4-k-m.v1.json`.

## M08-S21/S22 active runtime supersession (2026-07-29)

- The sole default text checkpoint is pinned `qwen3.5:4b-q8_0`; the former
  Qwen3-VL 8B and duplicate Qwen3.5 4B Q4 Ollama caches are absent.
- One deterministic latest-turn router selects viewer, emotional/contextual or
  game-analysis budgets on the same weight. Private reasoning never reaches
  logs, memory, UI or TTS.
- Active context remains 8,192 tokens. Runtime requests full GPU offload,
  reserves 6,144 MiB and keeps the ten-second turn deadline. Explicit screen
  analysis still uses the separate perception provider.
- Refreshed all-on Brain + Faster-Whisper + OmniVoice peaked at 13,990 MiB
  physical VRAM with 2,006 MiB minimum free. Owner application/quality
  acceptance is still required before promotion.
