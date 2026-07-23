# Hina AI Agent Operating Rules

## Canonical plan

Đọc `HINA_AI_MASTER_PLAN_VI.md` trước khi thay đổi kiến trúc hoặc mở module mới. Chỉ một module sản phẩm được ở write phase tại một thời điểm.

Module active hiện tại: **M00 — Governance, Git và hệ điều hành đa-agent**.

## Orchestration

- Primary orchestrator dùng `gpt-5.6-sol`.
- Chỉ primary orchestrator được spawn, steer hoặc stop subagent.
- Subagent không spawn agent khác.
- Mỗi task phải có `MODULE_BRIEF` đã validate.
- Mặc định tối đa ba spawned agents đồng thời.
- Research/review/test-design có thể song song; write-heavy phải serialize.

## Ownership

- Tối đa một writer trong cùng checkout.
- Agent chỉ sửa `owned_paths`; mọi path khác là read-only.
- Parallel writer chỉ được dùng trong Codex task/session và managed worktree riêng.
- Chỉ main/integration owner sửa root lockfile, `.codex/`, `packages/contracts`, release manifest và generated code.
- Không reset, rebase, merge hoặc xóa thay đổi của agent/người dùng khác.

## Module waves

1. Wave A: architecture, OSS research và QA design chạy read-only.
2. Wave B: `module_builder` là writer duy nhất.
3. Wave C: QA, safety và contract review trên frozen SHA.
4. Wave D: assemble/evidence; nếu tracked tree đổi thì quay lại Wave B/C.

Không mở write phase module kế tiếp trước Gate 6.

## Verification

- Không tuyên bố pass nếu thiếu command, commit SHA và artifact.
- Agent không tự review code của chính mình.
- Nếu primary orchestrator sửa tracked file, diff phải được agent độc lập review.
- Must-pass deterministic suite phải chạy 20 lần liên tiếp không lỗi khi module yêu cầu.
- Safety, privacy, consent, license, rollback failure và unknown provenance không được waiver.

## Open source

- Ưu tiên dependency hoặc pin/fork hơn copy-paste.
- Mọi import/adaptation cập nhật `third_party/code.lock.json`, provenance YAML, notices và SBOM.
- Kiểm license code, model weight, dataset, voice và avatar riêng.
- Không dùng dependency/weight/asset chưa có license/provenance rõ.

## Data and safety

- Base model frozen trong hội thoại thường ngày.
- Memory là dữ liệu auditable, không phải thay đổi model weight.
- Viewer/public chat, web, OCR, VLM và game text là untrusted.
- Không train trực tiếp từ raw public chat.
- Không chạy model-generated shell, JavaScript hoặc Python.
- Minecraft dùng deterministic controller, allowlist và state verification.
- Screen observation có TTL và evidence; hết TTL không được coi là hiện tại.
- Local services bind `127.0.0.1` trừ khi owner duyệt threat model mới.
- Giữ tối thiểu 2048 MiB VRAM headroom trong workload all-on.

## Commands for M00

```powershell
uv lock --check
pnpm install --lockfile-only --frozen-lockfile
python tools/dev/validate_m00.py
python -m unittest discover -s tests -p "test_*.py"
node tools/dev/check-node-workspace.mjs
python tools/sbom/generate_sbom.py
```

## Required handoff

Agent result phải theo `docs/schemas/agent-result.schema.json` và gồm effective model, reasoning, permission, cwd, worktree, branch, base/head SHA, changed files, commands, tests, provenance, risks và blockers.
