# ADR-0004: Codex agent config compatibility

- Status: accepted
- Date: 2026-07-23
- Owners: project owner, primary orchestrator

## Context

The installed `codex-cli 0.144.6` rejects scalar values such as
`enabled = true` inside the project `[agents]` table. Its parser treats entries
in that table as `AgentRoleToml` declarations. This prevents Codex from loading
the project config at all.

## Decision

- Declare all seven roles explicitly as `[agents.<role>]` tables.
- Point each declaration to a project-scoped `.codex/agents/*.toml` config file.
- Pin model and reasoning effort inside every role file.
- Enforce the three-worker operating limit in `AGENTS.md` and the orchestrator
  protocol instead of an incompatible scalar config key.
- Require `codex doctor` plus exact-model smoke tests before accepting any future
  config syntax migration.

## Consequences

The config loads on the pinned local CLI and role selection stays explicit.
Global agent defaults are intentionally not used, so every new role must state
its model, effort, and sandbox default.

## Verification

`codex doctor --summary --no-color` must report `config loaded`. M00 also parses
the role map and verifies that every declaration points to the expected role
file.
