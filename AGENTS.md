# Hina AI Agent Operating Rules

## Canonical plan

Đọc `HINA_AI_MASTER_PLAN_VI.md` trước khi thay đổi kiến trúc hoặc mở module mới. Chỉ một module sản phẩm được ở write phase tại một thời điểm.

Module active hiện tại: **M07 — Avatar stage và operator desktop**. M01,
M02 và M03 đã qua fast unit/contract/startup gate; repeat/soak/deep release
verification được hoãn tới khi owner yêu cầu. M04-S1/S2 đã qua fast gate,
real-provider smoke và independent review; P1 native inference timeout đã đóng
tại `cba2a816e0d63f7d0c5756331374c0da9213cc02`. Ngày 2026-07-25 owner chỉ thị
“Tiếp tục đi”, được ghi nhận là quyết định cho phép chuyển từ candidate M04 sang
M05 trong fast-development mode. M05-S1/S2/S3 đã có candidate chạy thật: fast
unit/contract/governance/startup đều xanh và real VieNeu CPU smoke đã sinh WAV.
Đúng một independent reviewer đã PASS candidate, không có P0/P1; page-unload
cancellation P2 đã sửa, còn voice-consent P2 tiếp tục chặn public/production
promotion. Owner vẫn thực hiện manual feature testing và báo lỗi bằng
correlation ID. Ngày 2026-07-25 owner chỉ thị “tiếp tục task tiếp theo”, được ghi
nhận là cho phép chuyển từ candidate M05 sang M06 trong fast-development mode.
M06 đồng thời sở hữu việc tổ chức lại Dev Console thành dashboard nhiều trang
logic để owner quản lý memory và các module đã chạy thật. M06-S1 là reviewed
runnable candidate: fast unit/contract/governance/startup/browser workflow đều
xanh; independent reviewer PASS frozen SHA `76986f53eb84de7bb276c22b925524c7442577a5`
không có P0/P1. P2 derived-index isolation được giữ trong backlog và M06 hiện
chỉ hỗ trợ local single-owner. Ngày 2026-07-25 owner chỉ thị “tiếp tục các task
tiếp theo đi”, được ghi nhận là cho phép mở M07 trong fast-development mode.
M07-S1/S2/S3 hiện là runnable candidate: avatar state/control plane, turn
callback, stage code-native, Web Audio amplitude từ TTS thật và Electron/Vue
operator shell sandboxed đã qua fast unit/contract/governance/startup/browser/
desktop IPC smoke gate. Browser đã xác nhận cue `speech.output` chuyển stage sang
`speaking` và mở miệng theo WAV thật; Electron smoke đã xác nhận renderer local
gọi control plane qua typed preload IPC. M07 tiếp tục với three-vrm adapter và
asset có provenance; chưa gọi independent reviewer trước khi module hoàn tất.

Legacy AIRI skill paths dưới `D:\ProjectAiri` mặc định ánh xạ sang repository
hiện tại `D:\ProjectHinaAI`, trừ khi owner chỉ định workspace khác.

## Orchestration

- Primary orchestrator dùng `gpt-5.6-sol`.
- Primary 5.6 Sol dùng project default `danger-full-access` và `approval_policy =
  "never"` theo quyết định của owner; không dừng để xin approval cho shell,
  network hoặc ghi ngoài workspace khi runtime cho phép.
- Quyền unrestricted của primary không truyền ngầm cho subagent. Mỗi custom
  agent vẫn phải dùng `sandbox_mode` được pin trong role file.
- Chỉ primary orchestrator được spawn, steer hoặc stop subagent.
- Subagent không spawn agent khác.
- Mỗi task phải có `MODULE_BRIEF` đã validate.
- Primary là builder và integration owner mặc định; không spawn agent cho việc
  mà primary có thể hoàn thành nhanh hơn chi phí handoff.
- Mặc định không spawn agent. Tối đa hai subagent đồng thời và chỉ khi công
  việc độc lập, bounded, chạy song song thật sự và có đầu ra được dùng ngay.
- Owner mode từ 2026-07-24 là **Solo-first**: primary không spawn subagent trừ
  khi owner yêu cầu rõ trong task hiện tại. Primary tự code/test/commit; owner
  thực hiện manual acceptance và báo lỗi bằng error log/correlation ID.
- Mỗi agent chỉ nhận context packet gồm brief, diff và tối đa các file trực
  tiếp liên quan; không yêu cầu đọc toàn repository hoặc toàn master plan.
- Advisory agent hoàn thành trong một lượt, trả kết quả ngắn; không tự mở vòng
  nghiên cứu tiếp theo. Chỉ frozen-SHA gate mới cần `AGENT_RESULT` đầy đủ.
- Research/review/test-design có thể song song; write-heavy chỉ song song khi
  worktree và `owned_paths` không giao nhau.

## Ownership

- Tối đa một writer trong cùng checkout.
- Agent chỉ sửa `owned_paths`; mọi path khác là read-only.
- Parallel writer chỉ được dùng trong Codex task/session và managed worktree riêng.
- Chỉ main/integration owner sửa root lockfile, `.codex/`, `packages/contracts`, release manifest và generated code.
- Không reset, rebase, merge hoặc xóa thay đổi của agent/người dùng khác.
- Quyền không cần approval không thay đổi target/scope: lệnh phá hủy chỉ chạy
  khi yêu cầu hiện tại đã xác định rõ target và có kiểm tra read-only trước.

## Lean module flow

1. Primary chốt brief, acceptance tests và scope.
2. Chỉ mở tối đa hai advisory agent nếu có trigger rõ:
   - architecture cho boundary/schema mới có blast radius lớn;
   - OSS cho dependency/source mới;
   - QA design cho hành vi khó kiểm thử hoặc safety-critical.
3. Primary triển khai vertical slice và chạy test hẹp trong lúc code.
4. Trong fast-development mode, primary chỉ chạy unit/smoke test hẹp một lần
   trên máy owner; không freeze SHA hoặc tạo evidence bundle cho iteration thường.
5. Chọn đúng một independent reviewer theo rủi ro và một QA runner nếu module
   yêu cầu benchmark/repeat gate. Không chạy mọi role theo mặc định.
6. Chỉ P0/P1 hoặc vi phạm acceptance criterion làm quay lại write phase. P2/P3
   được ghi backlog trừ khi primary chứng minh nó chặn release.
7. Flake/repeat/soak/full-workflow chỉ chạy khi owner yêu cầu rõ để dò bug sâu
   hoặc chuẩn bị release. Iteration thường commit/push sau fast unit/smoke pass.

Không mở write phase module kế tiếp trước Gate 6.

## Verification

- Handoff iteration thường phải ghi command unit/smoke và kết quả; commit SHA và
  artifact đầy đủ chỉ bắt buộc cho deep gate/release do owner yêu cầu.
- Agent không tự review code của chính mình.
- Trong owner Solo-first mode, tracked diff của primary không bắt buộc qua
  subagent review; phải có automated test evidence và owner manual acceptance.
  Khi owner yêu cầu independent review trở lại, reviewer vẫn phải read-only.
- Không chạy suite lặp 20 lần theo mặc định. Chỉ chạy khi owner yêu cầu deep
  verification trong task hiện tại.
- Không để nhiều agent chạy cùng một full suite hoặc cùng tạo một loại evidence.
- Agent prompt tối đa hóa tham chiếu file/diff và tối thiểu hóa nội dung lặp lại;
  không paste master plan hoặc research report vào prompt implementation.
- Nếu agent không tạo giá trị trong một lượt, primary tiếp quản thay vì spawn
  agent thay thế hoặc tạo chuỗi correction session.
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
uv run --frozen python tools/dev/validate_m00.py
uv run --frozen python -m unittest discover -s tests -p "test_*.py"
node tools/dev/check-node-workspace.mjs
uv run --frozen python tools/sbom/generate_sbom.py
```

## Required handoff

Agent result phải theo `docs/schemas/agent-result.schema.json` và gồm effective model, reasoning, permission, cwd, worktree, branch, base/head SHA, changed files, commands, tests, provenance, risks và blockers.
