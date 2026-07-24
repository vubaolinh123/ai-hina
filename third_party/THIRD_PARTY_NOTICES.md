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

Each registry artifact is pinned by version and integrity in `pnpm-lock.yaml`
and `third_party/code.lock.json`. No source file or snippet from these projects
is copied into Hina. Electron, Vite, the Vue plugin, TypeScript, vue-tsc and
@types/node are development/runtime-host tooling; Vue is the renderer runtime
dependency. TypeScript 7 is not used because it is currently incompatible with
the pinned Vue type checker.

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
