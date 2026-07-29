# M09 — Minecraft agent

## Trạng thái

M09 đang ở fast-development write phase. M08 đã dừng write phase ở runnable
candidate sau khi owner chọn tiếp tục dùng Vision Cloud và hoãn bộ chấm 20 ảnh
cho tới khi gặp lỗi thực tế. Đây không phải tuyên bố Vision đã đo và đạt ≥85%.

M09-S1, S2 và S3 hiện là local runnable candidate. Chưa production-promote vì
workspace chưa có Minecraft server test có thể reset để owner chạy acceptance.

## M09-S1 — Connection spine

- Pin `mineflayer@4.37.1` theo npm integrity và upstream commit
  `03eba44f3e9cb93a0f0bf69a75938246e174dc6f`; không copy source upstream.
- Chỉ dùng offline auth tới localhost/private IP; public IP và DNS bị chặn.
- Mineflayer/Prismarine type nằm sau internal port của Hina.
- World snapshot bounded chỉ gồm player, inventory và entity gần. Không đưa
  chat, sign, book, NBT, scoreboard hay plugin payload vào Hina.
- Status HTTP read-only bind đúng `127.0.0.1`.
- Emergency stop idempotent, latched và không chờ server acknowledgement.

Fast evidence: adapter build + 13 tests, repository fast suite 270 tests. Audit
dependency path Minecraft có 0 finding sau khi override transitive `uuid` lên
11.1.1. Workspace còn advisory AJV có sẵn ngoài owned scope M09.

## M09-S2 — Kỹ năng look.v1 có hậu kiểm

- Registry tĩnh có đúng một skill `look.v1`, version 1,
  `destructive=false`, một attempt, timeout 2.000 ms.
- Exact-schema input giới hạn yaw/pitch; unknown skill, extra field, NaN và góc
  ngoài range đều fail trước Mineflayer.
- Adapter gọi `bot.look(yaw, pitch, true)` thật, nhưng promise resolve chưa phải
  success. Normalized post-state phải khớp target trong tolerance 0,05 radian.
- Busy, precondition, vendor error, timeout, postcondition mismatch và
  emergency cancellation đều là bounded failure, không retry.

Fast evidence: adapter build + 22 tests, repository fast suite 279 tests.

## M09-S3 — Owner control trong Desktop

- `pnpm start:desktop` build và tự khởi Minecraft control service ở trạng thái
  disconnected trên đúng `127.0.0.1:8766`; không tự vào server game.
- Launcher sinh secret 32 byte mới cho từng phiên bằng CSPRNG, chỉ truyền qua
  environment của tiến trình con và thu hồi khi Desktop đóng. Secret, URL nội
  bộ và object Mineflayer không đi qua preload/renderer, không được persist.
- Status/health vẫn read-only. Connect, disconnect, `look.v1` và emergency stop
  yêu cầu Bearer secret, `X-Hina-Source: owner.desktop`, JSON ≤8.192 byte, exact
  schema và `ownerConfirmed=true`.
- Electron main chỉ nhận lệnh từ operator main frame qua typed IPC. Widget bị
  từ chối. POST không được replay/retry tự động.
- Dashboard có page **Minecraft** riêng bằng tiếng Việt: owner nhập server
  local/private, xem world state bounded, thử `look.v1`, ngắt kết nối hoặc dừng
  khẩn cấp. Page chỉ presentation/intent; network và secret ở Electron main.
- Disconnect thường hủy skill đang chạy nhưng cho phép reconnect. Emergency
  stop hủy skill, nhả controls, ngắt bot và latch tới khi restart adapter.

Fast evidence:

- `pnpm test:minecraft`: build TypeScript và 26 tests pass.
- `pnpm test:desktop`: production build và 64 tests pass.
- `pnpm test:fast`: 283 tests pass.
- Module brief, TypeScript typecheck, PowerShell parse và `git diff --check`
  pass. Status-server tests dùng loopback TCP thật trên ephemeral port.
- Chưa kết nối server Minecraft thật vì workspace không có resettable server.

## Cách owner thử sau khi pull

1. Chạy `pnpm start:desktop`.
2. Mở page **Minecraft**. Dịch vụ phải báo “Chưa kết nối game”.
3. Chạy một Minecraft test server offline mode ở localhost/LAN riêng.
4. Nhập IP/port/username và bấm **Kết nối Hina**.
5. Thử `look.v1`, xem góc yaw/pitch được hậu kiểm.
6. Dùng **Ngắt kết nối** để có thể vào lại, hoặc **Dừng Minecraft ngay** để latch
   toàn bộ adapter tới lần restart Desktop.

Lệnh terminal cũ vẫn dùng được khi cần smoke riêng:

```powershell
pnpm start:minecraft -- --host 127.0.0.1 --port 25565 --username Hina
```

## Slice kế tiếp

M09-S4 sẽ mở một kỹ năng di chuyển ngắn theo hướng cố định với timeout, quãng
đường tối đa và hậu kiểm vị trí. Kỹ năng vẫn chỉ dành cho server test có thể
reset; chưa có pathfinder, planner LLM, phá block hay chiến đấu.
