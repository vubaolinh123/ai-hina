# Hina text brain

Local-only text model integration for Hina AI. The package talks to an actual
Ollama or OpenAI-compatible endpoint on loopback, streams provider tokens, and
requires a live GPU resource lease before inference.

It never downloads a model automatically and never substitutes canned text when
the configured provider or model is unavailable.

The conversation layer adds:

- immutable `hina.v1` persona and prompt version;
- strict idle/listening/thinking/speaking/interrupted/error transitions;
- input, pre-tool and outbound safety-policy gates;
- complete-turn-only short-term memory and session relationship state;
- bounded context composition with an explicit no-current-vision invariant;
- typed tool proposals for inspection only—there is no executor.

Provider tokens are buffered until the complete response passes outbound
moderation. A failed, blocked or interrupted partial stream never becomes
assistant output or memory.
