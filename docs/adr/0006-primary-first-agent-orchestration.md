# ADR-0006: Primary-first agent orchestration

- Status: accepted
- Date: 2026-07-24
- Owners: project owner, primary orchestrator
- Scope: repository-wide delivery workflow

## Context

The original four-wave process spawned architecture, OSS, QA, builder, safety,
contract and release roles around one small slice. Most agents rebuilt the
same repository context, while the single-writer rule kept implementation
serial. M01-S1 demonstrated that independent review can find real defects, but
mandatory fan-out multiplied latency and token use without proportional
delivery speed.

## Decision

- GPT-5.6 Sol is the default builder, orchestrator and integration owner.
- Subagents are opt-in, not a mandatory wave. At most two run concurrently.
- A subagent is allowed only for a bounded task that is independent of active
  work and whose expected value exceeds its context/handoff cost.
- Agent context is a small packet: module brief, exact diff or symbols, relevant
  tests and the requested output. Agents do not cold-read the full repository.
- GPT-5.5 handles selected architecture, difficult implementation or safety
  review. GPT-5.4 handles selected OSS research and deterministic QA execution.
- Development uses narrow tests. Full suites run once before freezing; repeat,
  flake and soak gates run once on the final frozen SHA.
- One independent reviewer is selected by risk. A separate QA runner is added
  only when acceptance requires repeat, benchmark, replay or fault evidence.
- Only P0/P1 findings and explicit acceptance failures reopen implementation.
  Lower severities go to a backlog unless the primary records why they block.
- Advisory results are concise. Full `AGENT_RESULT` metadata is reserved for
  frozen-SHA gate evidence.
- A failed or unproductive agent is not replaced automatically; the primary
  resumes the work and records the tooling limitation.

## Role triggers

| Role | Spawn only when |
| --- | --- |
| `architecture_contracts` | A new public boundary, schema or migration rule has material blast radius |
| `oss_researcher` | A new dependency, copied source, model, dataset or asset needs provenance |
| `module_builder` | Work is isolated in a disjoint worktree or primary explicitly delegates a bounded implementation |
| `qa_designer` | Acceptance is ambiguous, adversarial or safety-critical |
| `qa_runner` | A frozen SHA needs independent repeat/benchmark/replay evidence |
| `safety_reviewer` | The diff touches trust, permissions, privacy, public output, actions or provenance |
| `integration_release` | Release evidence assembly is large and contains no product changes |

## Consequences

Small slices finish primarily in one context with fewer repeated reads and
fewer correction loops. Multi-agent review remains available where independence
materially improves confidence. Parallel coding is deferred until packages have
non-overlapping contracts and paths.
