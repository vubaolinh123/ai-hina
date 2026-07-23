# ADR-0002: Codex multi-agent delivery model

- Status: superseded by ADR-0006
- Date: 2026-07-23
- Owners: project owner, primary orchestrator

## Decision

- Primary: GPT-5.6 Sol.
- Architecture/build/safety/integration: GPT-5.5.
- OSS/QA design/QA execution: GPT-5.4.
- At most two opt-in spawned agents.
- One writer per checkout.
- Independent review runs on a frozen SHA.
- Any tracked change after validation invalidates that evidence.

## Rationale

ADR-0006 replaces mandatory multi-agent waves with a primary-first, risk-based
flow after M01-S1 showed that repeated cold context and handoffs dominated
delivery time.

## Verification

M00 validates TOML structure and model roster. Runtime smoke tests must confirm model entitlement, effective permission, worktree, branch, and base SHA.
