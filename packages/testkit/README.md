# Hina testkit

Deterministic local-only fake providers for building and testing Hina modules
before real model, speech, memory or tool backends are connected.

The fake tool provider has a fixed allowlist and never executes shell,
JavaScript, Python or network requests. Fake speech bytes are synthetic test
markers, not playable audio.
