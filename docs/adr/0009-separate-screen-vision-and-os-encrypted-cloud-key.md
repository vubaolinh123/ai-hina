# ADR-0009: Separate screen vision and OS-encrypted Cloud key

- Status: accepted
- Date: 2026-07-28
- Owners: primary orchestrator and project owner
- Scope: M08-S4

## Context

Hina uses one pinned Qwen3-VL 8B Thinking checkpoint for text so routine and
complex conversation do not require unloading one text model and loading
another. The owner decided that screen reading should evolve independently and
may use Ollama Cloud models, including newer vision models not suitable for a
16 GB local GPU. The desktop must remember the Cloud key across restarts until
the owner replaces or clears it.

A Cloud key is a secret. Persisting it in Vue state, browser storage, a
plaintext configuration file, logs or runtime status would let renderer
compromise or routine diagnostics recover it. Sending arbitrary base URLs would
also turn the provider feature into a server-side request primitive.

## Decision

- The Qwen3-VL 8B Thinking gateway is the text brain only. Simple text uses its
  same-weight fast path; complex text may use bounded hidden reasoning.
- M08 screen images go through a separate perception provider. Supported
  profiles are fixed-endpoint `https://ollama.com` Cloud and fixed-loopback
  `http://127.0.0.1:11434` local Ollama.
- Discovery uses `/api/tags` plus `/api/show` and returns only models that
  advertise the `vision` capability. The local profile additionally enforces
  the M08 lightweight boundary of roughly 5 GB/5B.
- Electron main encrypts the owner-entered Cloud key with `safeStorage` and
  persists only its ciphertext, provider and model under Electron `userData`.
  The decrypted key is available only in Electron main and the loopback
  runtime's process memory. It is never returned to the renderer, logs, status,
  Git or archived screenshot metadata.
- Desktop startup restores the selected provider with bounded retry. The saved
  key remains in force until an operator explicitly replaces or clears it.
  Failure to access OS encryption fails closed rather than writing plaintext.
- Cloud inference has zero local model VRAM cost but sends the explicitly
  selected screenshot to the chosen Cloud service. Local inference acquires a
  shared scheduler lease, requests GPU execution and uses `keep_alive=0`.
- Screenshot TTL, untrusted-data labeling, explicit capture consent, historical
  archive isolation and no-autonomous-tool rules remain unchanged.

## Consequences

The text brain no longer needs to change role or model when a screenshot is
analyzed. The owner can choose current Cloud vision quality without consuming
local model VRAM, or keep pixels local with a smaller model. Cloud mode has an
explicit privacy tradeoff and depends on network/provider availability.

The renderer can submit a new key but cannot read a previously stored one.
Losing access to the Windows user encryption context makes the stored
ciphertext unusable; the owner must enter a new key. Provider/model persistence
is local to the Electron user profile and is not synchronized through Git.

## Verification

- Unit tests reject plaintext/unknown persistence fields and malformed or
  oversized state.
- Desktop security tests prove renderer code has no filesystem, raw network or
  browser-storage secret path and only operator IPC can configure the provider.
- Runtime tests prove the key never appears in status/errors, Cloud uses the
  fixed endpoint, local discovery filters capability/size and local inference
  owns a scheduler lease.
- Route and UI smoke tests prove the saved configuration is restorable and a
  non-developer can discover, select, apply, replace or clear a vision provider.
