# M07 — Avatar stage và operator desktop

- Status: M07-S1/S2/S3 runnable candidate; M07 remains active
- Branch: `codex/M07-avatar-stage`
- Base: `ac29424e4dc58f42f9eeeb9f7a7f2408ad5c2f4f`
- Active slices: M07-S1 avatar state/control plane, M07-S2 code-native runtime
  stage, M07-S3 sandboxed Electron/Vue operator shell

## Runnable target

Trang Avatar Stage trong Dev Console phải phản ánh state hội thoại và TTS playback
thật. Visual đầu tiên là SVG/CSS do repository tự tạo để owner có thể chạy và
kiểm tra ngay mà không phải chờ mua/chọn asset. UI phải nói rõ đây là
`code-native fallback`, chưa phải VRM hay Live2D.

Renderer chỉ gọi typed loopback API và đọc audio đã được TTS trả về. Renderer
không đọc database, model, Qdrant hay provider nội bộ. Public/viewer input không
được điều khiển avatar.

## Deferred M07 deliverables

Three-vrm adapter, licensed VRM/Live2D asset, phoneme/viseme alignment,
dropped-frame/A-V benchmark và soak tám giờ được giữ cho các slice M07 tiếp
theo. Không được đánh dấu M07 complete khi các phần này chưa có evidence.

## Implemented in M07-S1/S2/S3

- `packages/avatar`: typed renderer-safe state/cue service, trusted-source
  allowlist, bounded history, neutral fallback và recovery khỏi terminal state.
- Conversation turn FSM phát state callback không chứa raw user/model text.
- Loopback API: status, cue và reset; external request không được giả danh
  `conversation.service` hoặc `runtime.lifecycle`.
- Dev Console có route Avatar Stage, visual SVG/CSS original, manual preview có
  nhãn rõ, trạng thái safety thật và renderer snapshot không chứa DB/model.
- TTS playback gửi cue `speech.output`; Web Audio analyser dùng sample của WAV
  thật để điều khiển độ mở miệng, không tuyên bố phoneme-accurate.
- Asset manifest ghi license, quyền sử dụng và SHA-256 của source visual.
- `apps/desktop`: ứng dụng Electron 43/Vue 3 chạy thật từ local files; renderer
  bật Chromium sandbox + context isolation, tắt Node integration/webview/remote
  navigation và có CSP không cho renderer gọi network.
- Preload chỉ expose sáu method có tên cố định. Electron main map từng method
  sang allowlist route `127.0.0.1`; từ chối URL khác, cue giả danh runtime,
  safety action ngoài allowlist và IPC từ frame không phải main frame.
- Desktop hiển thị avatar/safety state thật hoặc lỗi offline rõ ràng; manual
  preview, reset, mute và emergency stop đều gọi control plane hiện có.
- Electron, Vue, Vite và toolchain TypeScript được pin version/integrity/license
  trong lock/provenance; không copy source upstream.

## Fast evidence

- `tools/dev/Invoke-FastUnit.ps1`: 123 tests passed.
- `pnpm test:contracts`: 28 Python contract tests và 13 Node contract tests pass.
- Governance/provenance: 12 tests pass; avatar source hashes khớp manifest.
- Dev Console startup smoke pass trên port tạm.
- In-app browser desktop + 390 px: route/layout responsive, sidebar đứng yên khi
  main scroll, manual preview/reset gọi backend thật, không có body overflow.
- Real VieNeu browser workflow: WAV 506,924 byte/5.28 giây được tạo; lần chạy
  kế tiếp quan sát khi audio đang phát `avatarState=speaking`,
  `mode=tts-playback · happy`, `mouthRy>7`; sau playback về idle; console error
  và warning đều bằng 0.
- Desktop `vue-tsc` + main/preload typecheck pass; 6 security/control-client
  tests pass.
- Electron hidden smoke load local renderer, gọi health/avatar qua typed preload
  IPC thật và trả `loaded-local-file-with-typed-ipc`.
- Governance 12 tests pass; provenance validator ghi nhận 10 imported
  components.
