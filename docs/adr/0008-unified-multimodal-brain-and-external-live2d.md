# ADR-0008: Unified multimodal brain and external Live2D renderer

- Status: superseded for the model boundary by ADR-0009; Live2D decisions remain
  accepted
- Date: 2026-07-27
- Owners: primary orchestrator
- Scope: M08-S2 and M07-S16

## Context

The 2024 Neuro reference uses separate Llama 3 8B text and
MiniCPM-Llama3-V-2.5 vision servers, plus VTube Studio for its visible avatar.
On Hina's 16 GB RTX 5070 Ti, duplicating text and vision weights would spend
VRAM without improving the normal Vietnamese companion path. The displayed
Hiyori avatar is not part of Neuro's MIT repository and has separate Live2D
terms.

Hina must keep all local models below a 14 GiB operational ceiling, preserve at
least 2 GiB for the machine, retain short-lived/untrusted perception semantics,
and avoid presenting a third-party sample avatar as an owned Hina asset.

## Decision

> Historical note (2026-07-28): the shared text/vision model decision below was
> replaced by ADR-0009 after the owner chose a separately configurable Ollama
> Cloud/local screen-reading provider. The Live2D renderer decision remains
> current.

- Qwen3.5-4B Q4_K_M is the default shared text and explicit-snapshot vision
  model through Ollama. The same resource scheduler serializes both workloads;
  VLM requests use a 4,096-token runtime context, bounded output and
  `keep_alive=0`.
- M08 stores no source image. A successful inference adds only a bounded
  untrusted summary to the existing maximum-15-second observation. Failures are
  visible but do not erase the base snapshot evidence.
- Model text is advisory. It cannot invoke a tool, update memory, or assert
  current screen state after expiry.
- A larger 9B profile is not the default and may only be promoted after an
  all-on measured benchmark stays below 14 GiB.
- For games, the multimodal model may propose low-frequency intent. Execution
  remains an allowlisted deterministic controller with post-action state
  verification.
- VTube Studio is Hina's preferred optional Live2D renderer. The desktop main
  process talks only to its loopback public WebSocket API, stores the plugin
  token in local Electron user data without logging it, and exposes bounded
  operator-only IPC for connect, status, hotkeys and model movement.
- Hina does not bundle Hiyori. The dashboard explains that the owner must
  install VTube Studio and choose a model under its separate license. The
  current transparent VRM widget remains available offline.
- No file from Neuro or neurofrontend is copied. Their architecture and
  operator controls are design references; implementation uses Hina contracts
  and the official VTube Studio API.

## Consequences

The default configuration can understand Vietnamese chat and owner-selected
screenshots without a second VLM process. Quality is limited by a 4B model, so
vision remains opt-in and visibly advisory. Live2D quality can match the
external model selected in VTube Studio, while offline use still has a
functional avatar. The owner must complete the one-time VTube Studio plugin
authorization and is responsible for the selected model's terms.

## Verification

- A real local Qwen3.5-4B PNG request succeeds and unloads after the request.
- Unit and route tests prove pixels are not retained, output is bounded,
  failures fail visibly, TTL is preserved, and feature/capability gates remain.
- Desktop tests prove no VTube Studio command is available outside the typed
  operator preload, tokens are never returned to the renderer, and disconnects
  do not break the offline VRM widget.
- The all-on VRAM manifest records a ceiling no greater than 14,336 MiB.
