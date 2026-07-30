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

## M09-S8 — Mục tiêu tự nhiên, controller xác minh

- Theo quyết định owner, Dashboard không còn là bảng điều khiển yaw/pitch,
  hướng, khoảng cách, X/Z hay các nút hành động vi mô. Các thao tác đó cũng bị
  gỡ khỏi preload, Electron IPC và HTTP control surface; primitive typed cũ chỉ
  còn ở bên trong controller để có thể được ghép vào state machine đã review ở
  slice sau.
- Owner chỉ nhập một câu mục tiêu. Text brain dùng đúng checkpoint local hiện
  có để chọn **một** goal ID từ allowlist cố định hoặc trả `unsupported`. Output
  phải là exact JSON, không được có reasoning, code, tool call, tọa độ hay action
  sequence; malformed/unknown output fail closed. Prompt, output thô và hidden
  reasoning không được persist, render hay đưa sang TTS.
- Goal chạy thật đầu tiên là `harvest.nearby-log.v1`: controller chỉ tìm một log
  normal allowlist trong tầm với tối đa 4,5 block, yêu cầu player on-ground và
  physics state còn mới, dig đúng một lần với timeout 12 giây, rồi re-read block
  mục tiêu để xác minh đã biến mất. Không có tự đi tìm cây, craft/equip rìu,
  combat, loop, retry hay autonomous play.
- Safety `game.action` vẫn tắt mặc định. Chỉ owner Desktop bật rõ ràng trên
  Runtime & Safety mới có thể plan; sau đó Electron main mới gọi typed goal
  endpoint. Widget, viewer/public chat, Minecraft game text/sign/book, OCR/VLM
  và model không có quyền gọi gameplay action.
- Disconnect hoặc emergency stop abort goal đang chạy, gọi `stopDigging`, nhả
  controls rồi mới release socket. Kết quả chỉ là evidence game state đã giới
  hạn, không ghi world scan hay artifact ra đĩa.

### Cách owner thử sau khi pull

1. Chạy `pnpm start:desktop`, vào **Runtime & Safety** và bật **Quyền giao mục
   tiêu Minecraft**.
2. Vào **Minecraft**, kết nối LAN world/server riêng như trước. Đợi trạng thái
   physics là **Mới** và đặt Hina đứng trên mặt đất, cạnh một log thường trong
   tầm với.
3. Nhập: `Hina, chặt một khúc gỗ ở gần đi.` rồi bấm **Giao mục tiêu cho Hina**.
4. Chỉ coi là thành công khi Dashboard báo hậu kiểm block đã biến mất. Nếu log
   ở xa hoặc không có, Hina phải từ chối/thất bại an toàn, không tự đi tìm.

Fast evidence:

- `pnpm test:minecraft`: adapter build và 54 tests pass.
- `pnpm test:desktop`: production build và 67 tests pass; Desktop typecheck pass.
- Text-goal planner 4 tests, core goal-route 4 tests, Safety 22 tests và contract
  suite đều pass.
- Chưa kết nối LAN/server thật hoặc gọi provider model thật trong gate này;
  manual real-world acceptance vẫn do owner thực hiện.

## M09-S9 — Tiếp cận log gần bằng state machine bị giới hạn

- Goal cũ `harvest.nearby-log.v1` đã nghỉ hưu ở mọi typed boundary. Text brain chỉ
  còn được chọn `harvest.nearby-log.v2` hoặc `unsupported`; model không tạo tọa độ,
  chuỗi hành động, Mineflayer call, code hay reasoning hiển thị.
- Controller tự tìm **một** log thường trong allowlist ở bán kính ngang tối đa 8 block.
  Nó từ chối target lệch tầng, target sai khoảng cách, chunk/đường đi không rõ, nền
  không phẳng/trống hoặc block không còn đào được. Không quét thay thế hay retry.
- Với log ngoài tầm đào, controller chỉ đi thẳng tối đa 3 đoạn, từng đoạn không quá 2
  block. Mỗi đoạn phải có physics state mới, player đứng trên đất, ground/feet/head
  đã kiểm chứng qua Mineflayer, postcondition displacement và cleanup control. Sau đó
  nó re-check target có thể đào, dig đúng một lần và reread chính block đó.
- Không có pathfinder, tránh vật cản, jump/sprint, craft/equip rìu, combat, nhặt đồ,
  loop nền hay gameplay control thủ công. Disconnect/emergency stop abort cả tiếp cận
  lẫn đào, clear control và gọi `stopDigging` trước khi nhả socket.

### Cách owner thử sau khi pull

1. Mở LAN world/server và kết nối Hina như M09-S8; bật **Quyền giao mục tiêu
   Minecraft** trong Runtime & Safety.
2. Đặt Hina trên mặt đất phẳng, cùng tầng với một log bình thường; log có thể cách tối
   đa 8 block theo mặt phẳng ngang và đường thẳng tới nó phải trống.
3. Gửi: `Hina, chặt một khúc gỗ ở gần đi.` Hina có thể tiến tối đa 3 đoạn rồi đào một
   block; nếu có vật cản, dốc, target lệch tầng hoặc không đào được, kết quả phải fail
   an toàn thay vì tự tìm đường vòng.
4. Chỉ chấp nhận thành công khi Dashboard báo hậu kiểm block mục tiêu đã biến mất.

Fast evidence:

- Module brief schema pass; `pnpm test:minecraft` build + 61 tests pass.
- `pnpm test:desktop` production build + 67 tests pass.
- Text goal planner 4 tests, core goal route 4 tests và contract suite đều pass.
- Không chạy LAN/server Minecraft thật, provider model thật, GPU hay deep/soak gate;
  owner vẫn là người xác nhận hành vi trong world thật.

## M09-S10 — Tự chọn rìu đang có trước khi chặt

- `harvest.nearby-log.v2` giữ nguyên một goal natural-language và không tăng bề mặt
  quyền. Model không biết hoặc chọn tool/slot; chỉ controller deterministic mới đọc
  inventory Mineflayer cục bộ sau khi approach đã pass.
- Controller quét đúng một priority cố định: netherite, diamond, iron, golden, stone,
  wooden axe. Nếu tìm thấy, nó equip đúng một rìu và kiểm chứng `heldItem`; nếu không
  có rìu allowlist, nó unequip để dùng tay trống. Không craft, recipe lookup, đổi tool
  lần hai hay fallback thử lại.
- Sau tool selection controller lại kiểm tra cancellation, physics freshness và exact
  target diggable trước một dig duy nhất. Equip/unequip không xác minh được, target
  đổi state hoặc emergency stop đều fail an toàn trước dig; raw inventory/tool không
  được persist hay đưa vào model/UI.

Fast evidence:

- Module brief schema pass; `pnpm test:minecraft` build + 66 tests pass.
- `pnpm test:desktop` production build + 67 tests pass.
- Không chạy LAN/server Minecraft thật, provider model thật hay deep/soak gate;
  owner vẫn kiểm tra chất lượng gameplay trong world thật.

## M09-S11 — Decision trace của workflow Minecraft

- Lỗi owner thấy “Sẵn sàng…” nhưng Hina đứng im có hai phần. Dòng đó chỉ là trạng
  thái điều kiện của form, không phải kết quả model. Đồng thời `refreshMinecraft()`
  trước đây xóa mọi notice bắt đầu bằng `E_` ngay sau request, nên lỗi controller
  thật biến mất trước khi owner kịp đọc.
- Desktop nay giữ lỗi planner/controller sau refresh và hiển thị decision trace ngay
  cạnh ô nhập: nhận request, model phân loại, goal allowlist, controller, hậu kiểm
  hoặc lỗi. Mỗi bước có workflow UUID, thứ tự và elapsed time; cùng trace bounded
  được ghi ra terminal dưới prefix `[hina-desktop:minecraft:TRACE]`.
- Event đi Electron main → typed preload → operator renderer bằng schema đúng chín
  field, tối đa tám record trong RAM và reset mỗi request. Widget không nhận trace;
  không có file trace, model call, network request hay quyền gameplay mới.
- Dashboard công khai profile `minecraft.goal.v1`, hai JSON result hợp lệ và mô tả
  policy để owner chỉnh workflow. Raw system prompt, raw model output và hidden
  chain-of-thought không được render/log/persist; chúng không phải state evidence và
  không được dùng để điều khiển Mineflayer.

Fast evidence:

- Module brief schema pass; Desktop production build + 69 tests pass, gồm parser
  từ chối field `reasoning`, `prompt`, event dư field, sai UUID/bounds.
- Minecraft build + 66 tests pass; controller/allowlist/Safety không đổi.
- Audit thật trước fix xác nhận ba request owner ngày 2026-07-30 đều qua preflight
  và consume `game.action`, nên planner đã chọn goal hợp lệ; lỗi thực thi bị UI xóa.
  Không chạy lại LAN/model smoke trong slice này.

## M09-S11A — Sandboxed preload startup hotfix

- Desktop từng không khởi động vì sandboxed Electron preload cố tải runtime module
  tương đối `./minecraft-workflow`. File build có tồn tại nhưng sandbox preload chỉ
  cho phép tập module giới hạn, nên bridge `window.hinaDesktop` không được tạo và
  `getWindowMode` lỗi theo sau.
- Parser event Minecraft nay tự chứa trong preload; import chung chỉ còn `type` và
  bị TypeScript loại khỏi JavaScript build. Schema chín field và giới hạn tám event
  không đổi, không mở thêm IPC/quyền gameplay hay dữ liệu cho renderer.
- Regression test đọc chính `dist-electron/preload.js` và chặn
  `require("./minecraft-workflow")`. Desktop production build + 69 tests pass; smoke
  qua đúng launcher `start:desktop` xác nhận Operator/Widget cùng tải local renderer
  với typed IPC, không còn lỗi preload/module/getWindowMode.

## M09-S12 — Tự tìm đường có giới hạn tới một khúc gỗ đã load

- Trace thực tế của owner chứng minh model đã chọn đúng goal nhưng
  `harvest.nearby-log.v2` chỉ cho đi thẳng ngắn và từ chối khi log chưa ở trong
  tầm tay. Bản mới `harvest.nearby-log.v3` mở vùng tìm mục tiêu tới 32 block
  ngang và 8 block dọc, nhưng model vẫn chỉ được trả đúng một goal ID tĩnh hoặc
  `unsupported`; model không thấy tọa độ, route hay primitive điều khiển.
- Controller dùng `mineflayer-pathfinder` 2.4.5 để chạy đúng một A* bị giới hạn
  tới tầm nhìn/chặt của một log allowlist đã load. Policy cố định không cho
  pathfinder đào, đặt block, scaffold, tower, mở cửa, sprint, parkour hoặc đi
  vào chất lỏng; độ rơi tối đa một block, search radius 40 block, planning
  deadline 5 giây và toàn goal tối đa 30 giây.
- Sau khi đi tới, controller đọc lại physics freshness, `onGround` và exact
  target diggable; sau đó mới chọn rìu theo priority cố định hoặc tay không,
  chặt đúng một lần và xác minh chính block đó đã biến mất. Timeout, disconnect,
  emergency stop, target đổi hoặc không có route đều dừng và clear controls.
- Đây chưa phải workflow “tự đi khám phá, lấy nhiều gỗ và craft rìu”. Hina chỉ
  tìm trong chunk/vùng đang load, không retry mục tiêu khác và không thu gom
  theo loop. Các năng lực đó phải là goal deterministic được review riêng.

### Cách owner thử

1. Khởi động lại Desktop và kết nối lại LAN world để adapter nạp dependency mới.
2. Bật quyền Minecraft trong **Runtime & Safety**, bảo đảm Hina đứng trên đất và
   có một cây trong vùng đã load, cách không quá 32 block.
3. Gửi `Hina, chặt một khúc gỗ ở gần đi.` Trace phải hiện
   `harvest.nearby-log.v3` rồi bước A* giới hạn; Hina đi tới và chặt đúng một log.
4. Thử ngăn đường hoàn toàn hoặc bật emergency stop: goal phải dừng, không đào
   hay đặt block để vượt qua và không tự retry.

Fast evidence:

- `pnpm test:minecraft`: build + 66 tests pass; gồm path success, no-route,
  stale-state, exact-target, timeout/emergency cancellation và retired goal.
- Text brain 58 tests, contracts 41 tests, Desktop production build + 69 tests,
  toàn bộ `pnpm test:fast` và startup `pnpm smoke:desktop` đều pass.
- Chưa chạy goal trên LAN world thật trong gate tự động; owner vẫn xác nhận
  navigation/chặt cây trong world thật sau khi khởi động lại Desktop.

## M09-S12A — Sửa exact-target lookup với block palette không có position

- Trace LAN của owner đã đi qua model và allowlist đúng, nhưng controller dừng tại
  `Cannot read properties of null (reading 'x')`. Live stack xác định lỗi ở
  callback `matching` của `findBlock`: Mineflayer dùng callback này để lọc
  palette bằng block mẫu có `position=null`, trong khi code exact-target cũ đọc
  `position.x` ngay ở pha đó.
- Exact-target lookup nay dùng đúng contract hai tầng của Mineflayer:
  `matching` chỉ so tên log allowlist và `useExtraInfo` mới kiểm tra finite
  position/tọa độ của block thật. Vì vậy palette probe không còn chạm vào tọa độ.
- Goal `GoalLookAtBlock`, movement policy và hành vi connect/spawn được giữ
  nguyên; hotfix không thêm capability, retry hay quyền điều khiển mới.
- Lỗi target lookup/goal/pathfinder thật được ghi một stack bounded tối đa 2.048 ký tự ra terminal
  với prefix `[hina-minecraft:path:ERROR]`; prompt, model reasoning, route và
  tọa độ không được đưa vào Desktop hay persistence.

Fast evidence:

- `pnpm test:minecraft`: build + 67 tests pass, gồm regression bắt buộc
  `matching` không đọc position trước boundary `useExtraInfo`.
- Real LAN acceptance bằng chính adapter production pass: online/world ready,
  một goal thành công trong 3.530,749 ms, đúng một attempt và postcondition xác
  nhận exact target không còn. Không dùng route/action script giả lập.
- Desktop production build + 69 tests, module-brief schema, provenance guard,
  `git diff --check` và startup smoke qua đúng launcher đều pass.

## M09-S13 — Goal cấp cao chặt và nhặt một khúc gỗ

- Goal model-selectable hiện tại là `gather.nearby-log.v1`; toàn bộ
  `harvest.nearby-log.v1/v2/v3` đã nghỉ hưu ở typed planner, core, Electron,
  HTTP service và adapter. Model vẫn chỉ trả một ID tĩnh hoặc `null`, không trả
  tọa độ, route, tool, entity ID hay chuỗi thao tác.
- Một câu tự nhiên như `Hina, chặt một khúc gỗ ở gần đi.` nay chạy một
  state-machine controller duy nhất: tìm log allowlist đã load, A* có giới hạn,
  chọn rìu/tay theo policy, chặt đúng một lần, nhận diện drop mới cùng loại trong
  phạm vi 2,5 block quanh exact target và đi nhặt bằng tối đa một `GoalNear`.
  Các micro-step không xuất hiện thành nút UI hoặc model tool.
- Trước khi chặt, controller khóa inventory count cùng toàn bộ entity ID đã tồn
  tại. Drop cũ, item sai loại, entity invalid hoặc item ở ngoài vùng exact target
  không được chọn. Sau hành động, success cần đồng thời exact block biến mất và
  inventory count của đúng loại log tăng; lời mô tả hoặc việc `dig()` resolve
  không đủ để báo thành công.
- Pickup có tối đa 40 physics tick để quan sát sau khi chặt, chỉ một path attempt
  và vẫn nằm trong deadline toàn goal 30 giây. Timeout, disconnect và emergency
  stop hủy cả path/dig/pickup; không thử cây khác, không explore chunk chưa load,
  không craft và không chạy background.
- Dashboard vẫn chỉ có form mục tiêu tự nhiên. Trace owner nay mô tả chuỗi
  tìm/đi/chặt/nhặt và hậu kiểm block + inventory; hidden reasoning, raw prompt,
  tọa độ, route và entity ID vẫn không render hoặc persist.

Fast evidence:

- `pnpm test:minecraft`: build + 72 tests pass; có success, inventory delta,
  drop cũ/sai/xa, không nhặt được, false-success và emergency cancellation.
- Text-brain 58 tests, core Minecraft route 4 tests và Desktop production
  build + 69 tests pass. Module brief, toàn bộ `pnpm test:fast` và startup
  `pnpm smoke:desktop` đều xanh; chưa chạy destructive LAN goal tự động trong
  slice này, owner sẽ thử world thật.
