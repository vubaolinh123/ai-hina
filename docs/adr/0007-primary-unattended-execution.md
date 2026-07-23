# ADR-0007: Primary unattended execution

- Status: accepted by owner
- Date: 2026-07-24
- Owners: project owner
- Scope: primary GPT-5.6 Sol in this repository

## Decision

The project default for the primary GPT-5.6 Sol session is:

```toml
sandbox_mode = "danger-full-access"
approval_policy = "never"
```

This allows the primary to run shell and network commands without pausing for
interactive approval when the Codex host permits it. Every GPT-5.5/GPT-5.4
custom agent retains the explicit read-only or workspace-write sandbox pinned
in its role file; primary permissions must not be inherited implicitly.

## Risk controls

- Unattended permission does not expand the requested task scope.
- Destructive targets are resolved and checked read-only before execution.
- User-owned or unrelated worktree changes are preserved.
- Source changes are committed in small rollback points before the next slice.
- Secrets, public release, voice cloning, model promotion and risk waivers keep
  their existing human-owner gates.
- Managed application or organization policy may still override project config;
  runtime evidence records the effective permission.

## Consequences

Routine Git, test, dependency and local service operations no longer block on
approval prompts. A mistaken primary command has a larger blast radius, so
small commits, exact paths and rollback evidence are mandatory.
