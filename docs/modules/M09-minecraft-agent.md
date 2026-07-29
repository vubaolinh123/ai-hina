# M09 — Minecraft agent

## Trạng thái

M09 đang ở fast-development write phase. M08 đã dừng write phase ở runnable
candidate sau khi owner chọn tiếp tục dùng Vision Cloud và hoãn bộ chấm 20 ảnh
cho tới khi gặp lỗi thực tế. Đây không phải tuyên bố Vision đã đo và đạt ≥85%.

M09-S1 đến S7 hiện là local runnable candidate. Owner đã xác nhận được phiên
LAN thật; module vẫn chưa production-promote vì chưa có Minecraft server test
có thể reset để chạy acceptance đầy đủ.

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
5. Chờ **Độ tươi trạng thái game** báo “Mới”, rồi thử `look.v1`,
   `move.step.v1` và `move.to.v1`; thành công chỉ được báo sau hậu kiểm.
6. Dùng **Ngắt kết nối** để có thể vào lại, hoặc **Dừng Minecraft ngay** để latch
   toàn bộ adapter tới lần restart Desktop.

Lệnh terminal cũ vẫn dùng được khi cần smoke riêng:

```powershell
pnpm start:minecraft -- --host 127.0.0.1 --port 25565 --username Hina
```

## M09-S4 — Di chuyển ngắn có hậu kiểm

- Registry tĩnh hiện có đúng hai skill: `look.v1` và `move.step.v1`; cả hai đều
  non-destructive, một attempt và có postcondition cố định.
- `move.step.v1` chỉ nhận `north|east|south|west` và 0,25–2 block. Extra field,
  NaN, hướng khác hoặc khoảng cách ngoài range fail trước Mineflayer.
- Player phải online, có state, đang đứng trên đất và không có skill khác chạy.
- Controller xoay về cardinal yaw cố định, chỉ giữ control `forward`, chờ physics
  tick bounded và luôn `clearControlStates()` trong `finally`.
- Sau 20 tick không tiến được thì báo `E_MINECRAFT_SKILL_BLOCKED`; toàn skill có
  timeout 4 giây. Không retry hoặc tự tìm đường vòng.
- Success cần forward progress ≥75% target, không overshoot quá 0,75 block và
  lateral drift ≤0,35 block. Elapsed time hay vendor promise không phải evidence.
- Dashboard owner có hướng/khoảng cách rõ ràng; widget, model và viewer không gọi
  được route này.

Fast evidence:

- `pnpm test:minecraft`: build và 34 tests pass, gồm cardinal mapping, blocked,
  lateral mismatch, airborne precondition, timeout, disconnect/emergency cancel.
- `pnpm test:desktop`: production build và 65 tests pass.
- `pnpm test:fast`: 291 tests pass.
- Module brief và `git diff --check` pass; không model/GPU/Cloud, không world
  artifact và không kết nối server thật.

## M09-S5 — State freshness và movement evidence

- Mineflayer boundary theo dõi physics tick nội bộ, chỉ xuất sequence và tuổi
  trạng thái đã giới hạn. Không xuất packet, chat, plugin data hoặc bot object.
- `look.v1` và `move.step.v1` fail trước khi gửi action nếu chưa nhận physics
  tick hoặc tick mới nhất quá 1.000 ms; unknown age không bị giả thành 0.
- Dashboard hiện rõ trạng thái **Mới / Đã cũ / Chưa nhận physics tick** và vô
  hiệu hóa hai action khi world-state chưa đủ tươi.
- Mỗi movement attempt trả số physics tick đã quan sát, số tick đang đứng yên và
  forward progress lớn nhất; Dashboard hiện ba số này ngay trong kết quả owner.
  Blocked ở 20 stagnant tick vẫn một attempt, không retry/pathfinding và luôn
  nhả controls trong `finally`.
- S5 không thêm skill, model call, GPU/VRAM, Vision path hoặc file world-state.

Fast evidence:

- `pnpm test:minecraft`: build và 38 tests pass.
- `pnpm test:desktop`: production build và 65 tests pass.
- `pnpm test:fast`: 295 tests pass.
- Module brief, Desktop typecheck và `git diff --check` pass; không chạy server,
  model, GPU, Cloud hoặc tạo evidence thô.

## M09-S6 — Quay rồi đi tới tọa độ rất gần

- Theo chỉ thị owner tiếp tục phát triển và sẽ tự test sau, `move.to.v1` được
  mở trước manual acceptance S3–S5 nhưng không được ghi là real-server pass.
- Request chỉ nhận đúng `targetX/targetZ` hữu hạn trong world bound. Khoảng cách
  tính từ world state mới phải nằm trong 0,25–2 block; quá gần/quá xa fail trước
  khi xoay hoặc bật `forward`.
- Controller tính vector và yaw deterministic, quay một lần rồi dùng cùng loop
  movement đã kiểm chứng của `move.step.v1`: một attempt, timeout 4 giây, 20
  stagnant physics tick thì blocked và luôn nhả controls.
- Success vẫn cần forward progress ≥75%, overshoot ≤0,75 block và lateral drift
  ≤0,35 block. Evidence bổ sung khoảng cách còn lại tới tọa độ đích.
- Dashboard owner có ô X/Z, tự gợi ý điểm cách vị trí hiện tại 1 block, hiển thị
  khoảng cách trước khi cho bấm và gửi qua route/IPC fixed owner-only. Widget,
  model, viewer, chat/sign/book và plugin payload không có authority.
- Không thêm pathfinding, retry, obstacle avoidance, jump/sprint, combat, mining,
  placing, model call, GPU/Cloud hoặc persistence.

Fast evidence:

- `pnpm test:minecraft`: build và 46 tests pass.
- `pnpm test:desktop`: production build và 66 tests pass.
- `pnpm test:fast`: 303 tests pass.
- Module brief, Desktop typecheck và `git diff --check` pass; không chạy server
  Minecraft thật và không tạo world/model/media artifact.

## Slice kế tiếp

Owner sẽ test S3–S6 trên resettable server. Slice sau chỉ được mở từ lỗi thực tế
hoặc capability deterministic tiếp theo; pathfinder, LLM planner, phá block và
combat vẫn chưa được mở.

## M09-S6A — Windows PowerShell launcher hotfix

- Owner log xác nhận `pnpm start:desktop` dừng trước khi mở Minecraft service vì
  Windows PowerShell 5.1/.NET Framework không có static API
  `RandomNumberGenerator.Fill`.
- Launcher vẫn sinh đúng 32 byte CSPRNG và URL-safe Base64 không padding, nhưng
  dùng API tương thích `RandomNumberGenerator.Create().GetBytes(...)` và luôn
  dispose generator trong `finally`.
- Không đổi token size, port, route, quyền owner, child environment boundary hay
  cơ chế khôi phục/xóa biến môi trường khi Desktop đóng.
- Desktop security regression chạy chính helper production bằng
  `powershell.exe`, kiểm 43 ký tự URL-safe và decode đúng 32 byte mà không in
  token ra log.

Fast evidence:

- `pnpm test:desktop`: production build và 67 tests pass.
- `pnpm smoke:desktop`: same launcher path pass; model warmup, Minecraft service
  `ready/disconnected` và Electron typed-IPC smoke đều hoàn tất.
- Module brief và `git diff --check` pass; không thêm dependency hoặc artifact
  runtime mới.

## M09-S6B — Kết nối thất bại có thể thử lại

- Minecraft Java đang ở màn hình chính không mở một server tại `127.0.0.1:25565`.
  Với single-player, owner phải vào world, chọn **Open to LAN** và dùng đúng cổng
  LAN mà game hiện trong chat; `25565` là cổng thường dùng của dedicated server.
- Controller nay giải phóng bot và listener của đúng attempt gặp pre-spawn error,
  kick, end, timeout hoặc factory failure; status trở về `disconnected` nhưng giữ
  `lastError` đã chuẩn hóa để Dashboard hiển thị. Không auto-retry hay scan mạng.
- Callback cũ không thể tác động attempt mới. Khi socket mất sau lúc online,
  controller cũng giải phóng bot để owner reconnect thay vì kẹt ở
  `E_MINECRAFT_ALREADY_STARTED`.
- Dashboard nhắc rõ khác biệt giữa menu chính, LAN world và dedicated server;
  lỗi `ECONNREFUSED` kèm hướng dẫn ngắn ngay trong notice.

Fast evidence:

- `pnpm test:minecraft`: build và 48 tests pass, gồm retry sau ECONNREFUSED,
  callback socket cũ và reconnect sau end.
- `pnpm test:desktop`: production build và 67 tests pass.
- Không khởi tạo server, không quét port, không thêm retry tự động, model/GPU hay
  artifact runtime; real-server acceptance vẫn do owner thực hiện.

## M09-S7 — Live world inspector

- Dashboard Minecraft nay hiển thị snapshot giới hạn đã có sẵn từ Mineflayer:
  các ô đồ đang mang và thực thể gần Hina, kèm trạng thái rỗng khi game chưa trả
  dữ liệu. Không tạo route, request, dependency hay capability gameplay mới.
- Tên, loại và nhãn từ game chỉ được render bằng Vue interpolation như dữ liệu
  không tin cậy; chúng không đi vào text brain, memory, TTS hoặc action planner.
- Nút **Dùng X/Z này** chỉ chép tọa độ thực thể đã hiện vào form `move.to.v1`.
  Di chuyển vẫn cần chính owner bấm nút xác nhận có sẵn, chịu giới hạn 0,25–2
  block và các hậu kiểm M09-S6.

Fast evidence:

- Module brief schema pass và `git diff --check` pass.
- `pnpm test:desktop`: production build và 67 tests pass.
- Không khởi động server/game, không gọi model/GPU/Cloud, không tạo screenshot
  hoặc lưu world artifact; owner sẽ kiểm tra UI trong phiên Minecraft thật.
