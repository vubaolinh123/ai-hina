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
| Qwen3.5-4B Q4_K_M | Unified Vietnamese text + image, 262K model context, Apache-2.0 | Ollama blob 3.4 GB; measured 3.1 GiB GPU allocation at 4K runtime context | Default shared brain and explicit snapshot VLM |
| Qwen3.5-9B Q4_K_M | Better reasoning while retaining image input | Ollama blob 6.6 GB; unsafe with TTS + STT + desktop ambient load under the 14 GiB all-on ceiling | Optional sequential benchmark profile only |
| Qwen3-VL 4B/8B | Strong dedicated OCR/vision | Adds a second resident model and duplicates the current brain's vision capability | Do not add by default |
| MiniCPM-o 4.5 | 9B any-to-any streaming vision/speech | Official BF16 footprint is about 19 GB; quantized variants are about 10-11 GB and official limitations include unstable speech/language mixing | Future larger-GPU research profile |
| Qwen-VLA | Vision-language-action with a 1.15B action decoder | Robotics action domain does not match Minecraft and would weaken deterministic verification | Do not use as the game controller |

Primary sources:

- https://huggingface.co/Qwen/Qwen3.5-4B
- https://ollama.com/library/qwen3.5/tags
- https://github.com/QwenLM/Qwen3-VL
- https://github.com/OpenBMB/MiniCPM-o
- https://huggingface.co/openbmb/MiniCPM-o-4_5
- https://github.com/QwenLM/Qwen-VLA

## Local measurements and VRAM decision

Hardware on the owner machine is an RTX 5070 Ti with 16,303 MiB total VRAM.
During research the desktop baseline used about 4,875 MiB. A real Ollama
Qwen3.5-4B image request loaded 3.1 GiB entirely on GPU at a 4,096-token runtime
context, completed cold in 3.8 seconds and unloaded successfully with
`keep_alive=0`. The current optimized OmniVoice peak is about 2.27 GiB.

The conservative all-on budget is:

| Consumer | Budget |
| --- | ---: |
| Desktop / display / ambient GPU processes | 4,875 MiB observed |
| Qwen3.5-4B | 3,200 MiB measured rounded up |
| OmniVoice | 2,400 MiB measured rounded up |
| Moonshine STT reservation | 2,000 MiB |
| Runtime margin inside the 14 GiB ceiling | 1,861 MiB |
| Total ceiling | 14,336 MiB |

Heavy inference is still serialized by Hina's admission scheduler and each
Ollama VLM call uses `keep_alive=0`. Qwen3.5-9B is not an all-on default because
its 6.6 GB quantized blob plus the same consumers would exceed the ceiling.
Promotion of any larger profile requires a measured peak, not a model-file-size
estimate.

## Resulting architecture

1. Chat and explicit screenshots share Qwen3.5-4B through the existing Ollama
   gateway and resource scheduler.
2. M08 sends event-driven PNG snapshots only; there is no continuous video.
3. Pixels are discarded after inference. Only a bounded, untrusted text summary
   and existing hash/luminance evidence enter the short-lived observation.
4. VLM output has TTL at most 15 seconds, is never memorized automatically, and
   remains ineligible to trigger tools without a later verified controller.
5. Minecraft uses the model only as a low-frequency planner; a deterministic
   allowlisted controller and state verifier remain authoritative.
6. VTube Studio is a separately installed renderer on loopback. Hina's
   dashboard owns permission, connection state, hotkeys and movement presets.

