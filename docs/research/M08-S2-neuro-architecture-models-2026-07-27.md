# M08-S2 research: Neuro architecture, avatar, frontend and 2026 models

- Date: 2026-07-27
- Scope: architecture research only; no upstream source file is copied
- Reviewed revisions:
  - `kimjammer/Neuro` at `5e4b4241c41bb40983aee2cb60d65d6bb481842b`
  - `kimjammer/neurofrontend` at `365dd6d7f9febc87daccd7491054be8954a85c35`
  - `kimjammer/Neuro-LLM-Server` at `b7e15239d1b54045a766f5b654bf8782d95b974f`

## What is useful from Neuro

Neuro is a modular Python application whose independent worker threads share a
`Signals` object. An injection queue supplies prioritized context to a Llama 3
8B text model, a separate MiniCPM-Llama3-V-2.5 int4 server handles images,
RealtimeSTT/RealtimeTTS provide speech, and Socket.IO connects the SvelteKit
operator frontend. The frontend exposes current and queued messages,
thinking/speaking/listening state, interruption, memory, moderation, provider
toggles, vision, and VTube Studio hotkeys/model movement.

The best ideas to retain are:

- explicit current/next-turn observability and cancellation;
- separate operator controls for memory, moderation, vision and avatar actions;
- VTube Studio as an external Live2D renderer controlled through its public API;
- prioritized, typed context rather than concatenating every input equally.

Hina will not copy Neuro's shared mutable global state, untyped prompt injection
or one-thread-per-module lifecycle. Hina keeps typed boundaries, one admission
scheduler, fail-closed capabilities, monotonic freshness and explicit
provenance. Untrusted chat, OCR and VLM output never become executable actions.

Sources:

- https://github.com/kimjammer/Neuro
- https://github.com/kimjammer/neurofrontend
- https://github.com/kimjammer/Neuro-LLM-Server

## Avatar finding and license boundary

Neuro does not contain the avatar shown in its screenshot. Its README says the
author used the default **Hiyori** model from VTube Studio. The MIT licenses on
the three GitHub repositories therefore do not license Hiyori for copying or
redistribution.

Hiyori is a Live2D sample character. Live2D's Free Material License and sample
model terms apply separately, require the applicable attribution/conditions,
restrict redistribution, and do not permit Hina to silently treat the asset as
MIT source code. Hina therefore implements the part Neuro actually owns: a
VTube Studio API adapter. The owner can select Hiyori after installing VTube
Studio and accepting the applicable terms, or select a separately licensed
Live2D model. Hina's existing code-native VRM remains the offline fallback.

Sources:

- https://github.com/DenchiSoft/VTubeStudio
- https://denchisoft.com/license/
- https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html
- https://www.live2d.com/eula/live2d-sample-model-terms_en.html
- https://www.live2d.com/en/learn/sample/momose-hiyori-video/

## 2026 multimodal options

| Candidate | Useful capability | Local footprint / issue | Decision |
| --- | --- | --- | --- |
| Ollama Cloud vision models | Model list and vision inference can evolve independently of the local text brain | Zero local model VRAM; each selected screenshot leaves the machine and requires an owner-supplied bearer key | **M08-S4 preferred configurable screen-reading provider when owner accepts Cloud privacy** |
| Qwen3.5-4B Q4_K_M | Lightweight local Vietnamese text + image, 262K model context, Apache-2.0 | Ollama blob 3.4 GB; measured 3.1 GiB GPU allocation at 4K runtime context | Local screen-reading fallback discovered through `/api/tags` + `/api/show` |
| Qwen3.5-9B Q4_K_M | Better reasoning while retaining image input | Ollama blob 6.6 GB; not measured/promoted under the current Hina workload | Do not auto-download or auto-route |
| Qwen3-VL 8B Thinking Q4_K_M | Strong Vietnamese text/reasoning plus latent vision capability; Apache-2.0 | One 6.14 GB Ollama distribution; measured peak total physical VRAM 9.975 MiB at 8K context | **M03 text brain only; M08 does not send screenshots to this gateway** |
| Qwen3-VL 8B Instruct Q4_K_M | Avoids thinking latency for simple chat | A second 6.1 GB weight would add cache/residency swaps and duplicate most capability | Rejected by owner; not retained locally |
| MiniCPM-o 4.5 | 9B any-to-any streaming vision/speech | Official BF16 footprint is about 19 GB; quantized variants are about 10-11 GB and official limitations include unstable speech/language mixing | Future larger-GPU research profile |
| Qwen-VLA | Vision-language-action with a 1.15B action decoder | Robotics action domain does not match Minecraft and would weaken deterministic verification | Do not use as the game controller |

Primary sources:

- https://huggingface.co/Qwen/Qwen3.5-4B
- https://ollama.com/library/qwen3.5/tags
- https://github.com/QwenLM/Qwen3-VL
- https://huggingface.co/Qwen/Qwen3-VL-8B-Thinking
- https://ollama.com/library/qwen3-vl:8b-thinking-q4_K_M
- https://docs.ollama.com/api/authentication
- https://docs.ollama.com/api/tags
- https://docs.ollama.com/api-reference/show-model-details
- https://docs.ollama.com/capabilities/vision
- https://github.com/OpenBMB/MiniCPM-o
- https://huggingface.co/openbmb/MiniCPM-o-4_5
- https://github.com/QwenLM/Qwen-VLA

## Local measurements and VRAM decision

Hardware on the owner machine is an RTX 5070 Ti with 16.303 MiB total VRAM.
On 2026-07-28 the ambient baseline was 2.597–2.628 MiB. Three real requests
against the pinned Qwen3-VL 8B Thinking Q4_K_M distribution all requested full
GPU offload at an 8.192-token runtime context and unloaded with `keep_alive=0`:

| Request | Cold latency | Peak total physical VRAM |
| --- | ---: | ---: |
| Simple text, same-weight fast path | 2,939 s | 9.975 MiB |
| Arithmetic, hidden thinking | 6,160 s | 9.869 MiB |
| Routine PNG description, pre-provider-split experiment | 4,363 s | 9.805 MiB |

The highest result remains 4.361 MiB below Hina's 14.336-MiB all-on ceiling and
leaves 6.328 MiB physically free on the 16.303-MiB GPU. Hina therefore keeps
Q4_K_M for text: Q3/Q2 could save memory but would trade away Vietnamese and
reasoning quality without a current headroom need. The PNG result is retained
only as historical evidence; active screen reading no longer enters this
gateway.

Heavy providers are serialized by the shared admission scheduler rather than
kept resident simultaneously. `keep_alive=0` is required because the scheduler
cannot truthfully reserve VRAM that Ollama retains after releasing its lease.
The model lease is conservatively 8.192 MiB and the scheduler still rejects any
request that would violate 2.048 MiB headroom.

## Resulting architecture

1. Chat uses one pinned Qwen3-VL 8B Thinking Q4_K_M checkpoint. Simple text uses
   the same-weight pre-closed-thought path and complex text uses bounded hidden
   thinking. There is no second Instruct text checkpoint.
2. Explicit screenshots use a separate provider selected in the desktop
   Dashboard: fixed-endpoint Ollama Cloud with an owner key, or a lightweight
   local Ollama model that advertises `vision`. Cloud adds zero local model
   VRAM; local inference is serialized by the shared scheduler with
   `keep_alive=0`.
3. The Cloud key is stored only as Electron `safeStorage` ciphertext under
   `userData`, restored after restart, and never returned to the renderer,
   runtime status, logs or Git. It remains configured until the owner replaces
   or explicitly clears it.
4. M08 sends event-driven PNG snapshots only; there is no continuous video.
5. Pixels are discarded after inference by default. An owner may explicitly
   start a bounded PNG archive for a game session; retained images remain
   historical and never refresh current-observation TTL.
6. VLM output has TTL at most 15 seconds, is never memorized automatically, and
   remains ineligible to trigger tools without a later verified controller.
7. Minecraft uses the model only as a low-frequency planner; a deterministic
   allowlisted controller and state verifier remain authoritative.
8. VTube Studio is a separately installed renderer on loopback. Hina's
   dashboard owns permission, connection state, hotkeys and movement presets.
