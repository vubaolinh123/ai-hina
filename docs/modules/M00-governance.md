# M00 — Governance, Git and multi-agent operating system

- Status: Gate 6 passed locally; remote Windows CI required before opening M01
- Branch: `module/M00-governance`
- Baseline: `f5bfa98`
- Product code: none

## Scope

- Git baseline and remote.
- Root governance and security documents.
- Codex primary/custom agent configuration.
- Python and Node workspace lockfiles.
- Module/agent handoff schemas and templates.
- CI, validation, provenance and SBOM bootstrap.
- Hardware/model-role preflight.

## Non-goals

- LLM runtime.
- STT/TTS.
- Memory.
- Avatar/perception.
- Minecraft/livestream.
- Training.

## Gate checklist

- [x] Required files and directories validated.
- [x] TOML/JSON parsed.
- [x] Agent roster and sandbox defaults validated.
- [x] Module brief and agent result examples validated.
- [x] Python and pnpm lockfiles generated and checked.
- [x] Node/Python smoke tests pass.
- [x] Loopback and ignore rules validated.
- [x] Provenance registry validated.
- [x] CycloneDX SBOM generated.
- [x] Hardware inventory recorded.
- [x] GPT-5.5 and GPT-5.4 smoke tests pass.
- [x] Independent QA/safety review passes on frozen SHA.
- [x] Gate evidence integrity manifest generated.
- [x] Owner-approved push to `origin/main`.

## Next module

M01 — Contracts, config, lifecycle and observability spine. Do not start until every M00 item is checked and Gate 6 is recorded.
