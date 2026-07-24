# Hina text brain

Local-only text model integration for Hina AI. The package talks to an actual
Ollama or OpenAI-compatible endpoint on loopback, streams provider tokens, and
requires a live GPU resource lease before inference.

It never downloads a model automatically and never substitutes canned text when
the configured provider or model is unavailable.
