# ADR-0002: Codex multi-agent delivery model

- Status: accepted
- Date: 2026-07-23
- Owners: project owner, primary orchestrator

## Decision

- Primary: GPT-5.6 Sol.
- Architecture/build/safety/integration: GPT-5.5.
- OSS/QA design/QA execution: GPT-5.4.
- At most three spawned agents initially.
- One writer per checkout.
- Independent review runs on a frozen SHA.
- Any tracked change after validation invalidates that evidence.

## Rationale

This keeps the main context focused, makes role ownership explicit, and avoids concurrent write conflicts while retaining parallel research and review.

## Verification

M00 validates TOML structure and model roster. Runtime smoke tests must confirm model entitlement, effective permission, worktree, branch, and base SHA.
