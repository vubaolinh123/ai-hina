# M07 — Avatar stage và operator desktop

- Status: M07-S1/S2/S3/S4/S5 runnable candidate; M07 remains active
- Branch: `codex/M07-avatar-stage`
- Base: `ac29424e4dc58f42f9eeeb9f7a7f2408ad5c2f4f`
- Active slices: M07-S1 avatar state/control plane, M07-S2 code-native runtime
  stage, M07-S3 sandboxed Electron/Vue operator shell, M07-S4 real VRM
  development stage, M07-S5 audio-derived viseme pipeline

## Runnable target

Trang Avatar Stage trong Dev Console phải phản ánh state hội thoại và TTS playback
thật. Visual đầu tiên là SVG/CSS do repository tự tạo để owner có thể chạy và
kiểm tra ngay mà không phải chờ mua/chọn asset. UI phải nói rõ đây là
`code-native fallback`, chưa phải VRM hay Live2D.

Renderer chỉ gọi typed loopback API và đọc audio đã được TTS trả về. Renderer
không đọc database, model, Qdrant hay provider nội bộ. Public/viewer input không
được điều khiển avatar.

## Deferred M07 deliverables

Final owner-approved Hina identity asset, phoneme-accurate alignment,
dropped-frame/A-V benchmark và soak tám giờ được giữ cho các slice M07 tiếp
theo. Không được đánh dấu M07 complete khi các phần này chưa có evidence.

## Implemented in M07-S1/S2/S3/S4/S5

- `packages/avatar`: typed renderer-safe state/cue service, trusted-source
  allowlist, bounded history, neutral fallback và recovery khỏi terminal state.
- Conversation turn FSM phát state callback không chứa raw user/model text.
- Loopback API: status, cue và reset; external request không được giả danh
  `conversation.service` hoặc `runtime.lifecycle`.
- Dev Console có route Avatar Stage, visual SVG/CSS original, manual preview có
  nhãn rõ, trạng thái safety thật và renderer snapshot không chứa DB/model.
- TTS playback gửi cue `speech.output`; Web Audio analyser dùng sample của WAV
  thật để phân loại heuristic `sil/A/I/U/E/O` và intensity, không tuyên bố
  phoneme-accurate và không gửi/lưu raw analyser data.
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
- Desktop dùng `three@0.185.1` và `@pixiv/three-vrm@3.5.5` để load real VRM 1.0
  từ fixed bundled path; không nhận URL/query/user path và không tải runtime.
- `VRM1_Constraint_Twist_Sample` official sample của pixiv/VRM Consortium được
  pin upstream commit + SHA-256. Embedded meta cho phép everyone avatar use,
  corporate commercial use, redistribution và modification redistribution.
- UI ghi rõ đây là development sample, không phải thiết kế Hina cuối cùng.
  Load lỗi tự về SVG code-native; backend `asset.vrmLoaded` không bị sửa thành
  true giả vì renderer-local load state được báo riêng.
- State/expression thật điều khiển deterministic head/breath/expression motion.
  Web SVG và desktop VRM dùng cùng viseme/intensity đã được backend kiểm tra;
  VRM map A/I/U/E/O sang `aa/ih/ou/ee/oh`, không còn speaking-state fake mouth.

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
- Three/VRM typecheck + build pass; Vite emit đúng VRM 10,776,032 byte.
- 8 desktop security/motion/control tests pass; Electron hidden smoke parse VRM
  thật và trả `vrmLoaded=true`.
- Governance 12 tests pass; provenance validator ghi nhận 13 imported
  components và đối chiếu embedded VRM meta với manifest.
- Audio-viseme pure Node: 8/8 tests pass (silence, A/I/U/E/O, stabilizer và
  invalid input); avatar backend 5/5 và Dev Console integration 8/8 pass.
- Real VieNeu browser workflow: WAV 48 kHz phát thật; backend quan sát
  `speaking → U/O/A` với intensity tới 1.0, sau đó `idle | sil | 0`. Lip-sync
  status là `observed-audio-spectral-viseme`, `phonemeAccurate=false`.
