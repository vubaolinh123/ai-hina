# Third-party notices

## faster-whisper 1.2.1

- Upstream: https://github.com/SYSTRAN/faster-whisper
- Pinned tag/commit: `v1.2.1` /
  `65882eee9f5cdbeeb2d877f1131d48cf241b327d`
- License: MIT
- Copyright: Copyright (c) 2023 SYSTRAN
- Use: runtime dependency behind Hina's local STT provider interface

No faster-whisper source file or snippet is copied into this repository.
Transitive Python packages are pinned by `uv.lock` and emitted in the CycloneDX
SBOM.

Model weights are licensed and tracked separately. The M04 default is
`Systran/faster-whisper-small` at
`536b0662742c02347bc0e980a01041f333bce120`; see its model manifest for the
weight hash and terms.

## F5-TTS 1.1.22

- Upstream: https://github.com/SWivid/F5-TTS
- Distribution: `f5-tts==1.1.22`
- PyPI wheel SHA-256:
  `f0505dfb5463645caa526bace346ed1c89bcc9acb9ef42fdffd56c2c4c0a09d1`
- License: MIT
- Use: runtime dependency behind Hina's local Vietnamese TTS provider

No F5-TTS source file or snippet is copied into this repository. Hina invokes
the pinned package through its inference primitives and decodes the fixed WAV
with soundfile on Windows before CUDA inference. The ZaloPay Vietnamese model
and Vocos weights are licensed and hashed separately in
`ml/models/manifests/f5-tts-vietnamese-zalopay.v1.json`.

## OmniVoice 0.2.1

- Upstream: https://github.com/k2-fsa/OmniVoice
- Distribution: `omnivoice==0.2.1`
- Source commit: `5ba967c4d5b0f08244ae856b033eea583d1e4517`
- PyPI wheel SHA-256:
  `23f113ef51116a16308b55c4c2ac9c08efca7dfb594802f5c8adfb7523313ccc`
- License: Apache-2.0
- Use: default local CUDA/FP16 multilingual TTS provider for owner testing

No OmniVoice source file or snippet is copied into this repository. Hina calls
the pinned package through its official `from_pretrained`,
`create_voice_clone_prompt` and `generate` APIs. The exact OmniVoice model
revision, file hashes and weight license are tracked separately in
`ml/models/manifests/omnivoice-0.6b.v1.json`.

Hina permits only one fixed, hash-bound synthetic owner voice. Generated
OmniVoice audio is not watermarked. The upstream model card identifies the
pretrained weights as CC-BY-NC because of training-data constraints, so this
candidate remains local, non-commercial owner testing only and is not
production-promoted.

## VieNeu-TTS 3.2.3

- Upstream: https://github.com/pnnbao97/VieNeu-TTS
- Pinned tag/commit: `v3.2.3` /
  `452bf58485a37772d8963a7dfb9e13b0d8288a50`
- PyPI wheel SHA-256:
  `54fd23bf70dcc5bf83885163de67a0ae2b7d2030cf7b53996d5ec97d2dbb20ca`
- License: Apache-2.0
- Use: runtime dependency behind Hina's local Vietnamese TTS provider

No VieNeu source file or snippet is copied into this repository. Hina uses
version-specific internal imports from the pinned wheel to inject exact local
model and codec snapshot paths. The integration disables voice cloning and
retention, allows only the bundled `Trúc Ly` preset, and requests upstream audio
watermarking.

The VieNeu-TTS v3 Turbo model and MOSS Audio Tokenizer snapshots are licensed
and hashed separately in `ml/models/manifests`. The bundled preset-voice table
is tracked in `assets/manifests`; upstream distribution exists, but independent
speaker-consent evidence has not been published, so release promotion remains
blocked pending owner review.

## qdrant-client 1.18.0

- Upstream: https://github.com/qdrant/qdrant-client
- Pinned tag/commit: `v1.18.0` /
  `961c21aa930e3e9a0e8b7402cec5dc46b82612c7`
- PyPI wheel SHA-256:
  `093aa8cf8a420ee3ad2a68b007e1378d7992b2600e0b53c193fc172674f659cd`
- License: Apache-2.0
- Use: persistent loopback-free local vector index for derived memory retrieval

No qdrant-client source file or snippet is copied into this repository. Hina
uses the pinned local-mode API behind its own derived-index boundary. SQLite
remains authoritative and the Qdrant collection can be reconciled or rebuilt.

## M07 desktop build stack

The local operator desktop uses these exact npm packages:

- Electron 43.2.0 — MIT — https://github.com/electron/electron
- Vue 3.5.40 — MIT — https://github.com/vuejs/core
- Vite 8.1.5 — MIT — https://github.com/vitejs/vite
- @vitejs/plugin-vue 6.0.8 — MIT —
  https://github.com/vitejs/vite-plugin-vue
- TypeScript 6.0.3 — Apache-2.0 —
  https://github.com/microsoft/TypeScript
- vue-tsc 3.3.8 — MIT — https://github.com/vuejs/language-tools
- @types/node 26.1.1 — MIT —
  https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/node
- ws 8.21.1 — MIT — https://github.com/websockets/ws
- @types/ws 8.18.1 — MIT —
  https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/ws

Each registry artifact is pinned by version and integrity in `pnpm-lock.yaml`
and `third_party/code.lock.json`. No source file or snippet from these projects
is copied into Hina. Electron, Vite, the Vue plugin, TypeScript, vue-tsc,
@types/node and @types/ws are development/runtime-host tooling; Vue and ws are
runtime dependencies. TypeScript 7 is not used because it is currently
incompatible with the pinned Vue type checker. The optional native ws addons
are not installed.

## M07 VRM renderer

- three 0.185.1 — MIT — https://github.com/mrdoob/three.js
- @pixiv/three-vrm 3.5.5 — MIT —
  https://github.com/pixiv/three-vrm
- @types/three 0.185.1 — MIT —
  https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/three

These packages are exact npm dependencies pinned by registry integrity. No
upstream source file or snippet is copied into Hina. The VRM binary is a
separate asset with separate rights and provenance at
`assets/manifests/vrm1-constraint-twist-sample.v1.json`.

## M07-S16 architecture and protocol references

- kimjammer/Neuro at
  `5e4b4241c41bb40983aee2cb60d65d6bb481842b` — MIT —
  https://github.com/kimjammer/Neuro
- kimjammer/neurofrontend at
  `365dd6d7f9febc87daccd7491054be8954a85c35` — MIT —
  https://github.com/kimjammer/neurofrontend
- VTube Studio Public API at
  `882ba5fc8bf06d7795b28bbbb965464f75403618` — MIT —
  https://github.com/DenchiSoft/VTubeStudio

No source file or snippet from these repositories is copied into Hina. Neuro
and neurofrontend informed the module boundary and operator controls; Hina's
TypeScript adapter was independently implemented against the public VTube
Studio WebSocket protocol. The Electron transport uses the pinned `ws` client;
the Node built-in WebSocket was observed to emit an empty frame for a valid
`CurrentModelResponse` on this VTube Studio runtime.

The Hiyori avatar shown in Neuro's screenshot is not contained in or licensed
by Neuro's MIT repository. Hina does not bundle or redistribute Hiyori. Owners
may select Hiyori in a separately installed VTube Studio instance after
reviewing Live2D's Free Material License and sample-model terms, or select a
different model they are licensed to use. VTube Studio application/plugin
terms and every selected Live2D model remain separate from this source notice.
