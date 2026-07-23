# Threat model: M00 bootstrap

## Assets

- Git history and remote.
- Codex configuration and agent permissions.
- Future secrets, model weights, user data and release evidence.

## Trust boundaries

- Local workspace vs GitHub remote.
- Parent Codex permission override vs custom-agent defaults.
- Repository files vs untrusted upstream code.
- Tracked evidence vs ignored sensitive artifacts.

## Threats and controls

| ID | Threat | Control | Verification |
|---|---|---|---|
| M00-T01 | Secret committed | Ignore patterns, secret-free examples, review | Governance tests |
| M00-T02 | Agent edits outside ownership | Module brief, one writer, worktree checks | Agent rules and schema |
| M00-T03 | Silent model/permission fallback | Runtime fields in result, smoke test | Preflight evidence |
| M00-T04 | Unlicensed code copied | Code lock, provenance, notices, SBOM | Provenance validator |
| M00-T05 | Sensitive artifact tracked | Artifact allowlist and ignore rules | Git ignore tests |
| M00-T06 | Unsafe service exposure | Loopback default | Config validation |
| M00-T07 | Evidence applies to wrong commit | SHA/tree hash and integrity manifest | Gate validator |
| M00-T08 | Unattended primary command has unrestricted host/network impact | Owner-explicit primary-only policy, bounded task scope, read-only target resolution before destructive actions, protected subagent sandboxes, Git rollback | Config/governance tests and Git history |

## Fail-closed

- Unknown custom-agent model or missing required agent file fails M00 validation.
- Invalid provenance registry or non-loopback default fails validation.
- Missing evidence hash blocks Gate 6.
