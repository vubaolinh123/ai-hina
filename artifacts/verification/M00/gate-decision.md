# M00 Gate 6 decision

- Decision: **PASS, subject to the same commit passing the remote Windows CI**
- Frozen implementation commit: `b89ec28c13f6ce76c6deff827547a087a7810216`
- Frozen tree: `188e572faa9617243dc2f06b5356ac7b04c585d3`
- Baseline commit: `f5bfa98`
- Product code introduced: none

## Agent recommendation

- GPT-5.4/high independent QA: PASS; canonical gate completed in the detached
  validation worktree, 12 tests passed and 0 failed.
- GPT-5.5/xhigh independent safety review: PASS; 0 blocking findings.
- GPT-5.6 Sol release coordinator recommendation: promote the reviewed M00 tree
  as the governance baseline and do not open M01 until the remote CI is green.

## Owner decision

The owner explicitly approved the master plan, authorized implementation, and
requested that the source be pushed to
`https://github.com/vubaolinh123/ai-hina.git`. This approves the M00 baseline
merge/push only. It does not approve public livestreaming, voice cloning,
third-party imports, model downloads, adapter promotion, or later risk waivers.

## Verification

- `codex doctor --summary --no-color`: config loaded.
- Exact-model smoke: GPT-5.4/high and GPT-5.5/xhigh returned the expected result
  with `approval=never` and `sandbox=read-only`.
- `powershell -NoProfile -ExecutionPolicy Bypass -File tools/dev/Invoke-M00Gate.ps1`:
  PASS on Windows and on a detached validation worktree.
- Python governance/provenance suite: 12 passed, 0 failed.
- Node workspace check: PASS.
- Python compile check: PASS.
- uv and pnpm frozen lock checks: PASS.
- CycloneDX SBOM and hardware inventory: generated.
- Tracked source diff after QA: clean.

## Findings closed

- HTTPS and SSH forms of the approved GitHub origin are normalized.
- Codex CLI-compatible role declarations replace the rejected scalar agent
  table.
- Agent-result contracts record effective sandbox and approval policy.
- GitHub Actions are pinned to full commit SHAs.
- Research candidates are separated from imported/frozen dependencies.
- Detached frozen checkouts are accepted.
- PowerShell native command failures stop the gate.
- Artifact hashing is recursive and uses a read-only commit tree lookup.

## Known limitations

- No product runtime, model weight, dataset, voice, avatar, Minecraft adapter, or
  livestream integration exists in M00.
- Third-party and model candidates remain `research_only` and unfrozen.
- Remote CI status is authoritative in GitHub Checks for this exact commit; a
  failed run invalidates this conditional PASS and blocks `main`.
- The committed integrity manifest anchors the independently reviewed
  implementation SHA above. CI regenerates an uploaded manifest for the final
  evidence commit; `codex-smoke.json` retains the reviewed SHA and tree.
- The non-fatal local Codex model-cache warning is recorded in
  `codex-smoke.json`; it did not change the observed model or effort.

## Rollback

M00 can be rolled back to baseline commit `f5bfa98`. No database, user data,
model weights, runtime service, or irreversible migration exists.
