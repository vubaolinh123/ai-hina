# Workers

Process-isolated native/GPU workers:

- `speech`: VAD, STT, TTS and alignment.
- `perception`: crop, OCR, optional VLM and freshness.

Workers implement generated contracts and do not import core implementation.
