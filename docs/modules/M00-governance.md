# M00 — Governance, Git and multi-agent operating system

- Status: in progress
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

- [ ] Required files and directories validated.
- [ ] TOML/JSON parsed.
- [ ] Agent roster and sandbox defaults validated.
- [ ] Module brief and agent result examples validated.
- [ ] Python and pnpm lockfiles generated and checked.
- [ ] Node/Python smoke tests pass.
- [ ] Loopback and ignore rules validated.
- [ ] Provenance registry validated.
- [ ] CycloneDX SBOM generated.
- [ ] Hardware inventory recorded.
- [ ] GPT-5.5 and GPT-5.4 smoke tests pass.
- [ ] Independent QA/safety review passes on frozen SHA.
- [ ] Gate evidence integrity manifest generated.
- [ ] Owner-approved push to `origin/main`.

## Next module

M01 — Contracts, config, lifecycle and observability spine. Do not start until every M00 item is checked and Gate 6 is recorded.
