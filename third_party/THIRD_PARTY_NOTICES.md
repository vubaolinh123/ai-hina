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
