# M09 — Minecraft agent

## Trạng thái

M09 đang ở fast-development write phase. M08 đã dừng write phase ở runnable
candidate. Ngày 2026-07-29 owner chấp nhận dùng provider Vision Cloud hiện tại
và hoãn bộ chấm 20 ảnh đa dạng cho tới khi gặp lỗi thực tế. Đây là quyết định
chuyển module, không phải bằng chứng rằng ngưỡng chất lượng ≥85% đã được đo hoặc
đã pass.

## Slice M09-S1

Mở nền kết nối Minecraft thật bằng Mineflayer trên server local/private có thể
reset. Slice này chỉ sở hữu:

- cấu hình kết nối offline đã validate và chặn public server;
- wrapper Mineflayer sau contract dữ liệu plain của Hina;
- snapshot bounded cho player, inventory và entity gần;
- status HTTP chỉ đọc trên `127.0.0.1`;
- emergency stop idempotent, latched và không chờ server acknowledgement;
- log lỗi có mã ổn định, không ghi chat/sign/book hoặc dữ liệu plugin.

Chưa có LLM planner hoặc skill gameplay trong S1. Runtime không chạy code do
model sinh ra, không dùng `eval`, không gọi shell và không có hành động phá
world. Owner chỉ smoke bằng world/server test có thể reset.

## Lệnh sử dụng sau khi gate xanh

```powershell
pnpm start:minecraft -- --host 127.0.0.1 --port 25565 --username Hina
```

Minecraft server cần chạy offline mode trong môi trường test riêng. Trạng thái
read-only mặc định sẽ ở `http://127.0.0.1:8766/v1/minecraft/status`. Nhấn
`Ctrl+C` tại terminal adapter để kích hoạt emergency stop và ngắt bot.

## Slice kế tiếp

M09-S3 sẽ nối skill controller vào một owner-only control boundary để owner có
thể chạy hành động thật trên server test từ Dashboard. Boundary đó vẫn phải
giữ fixed allowlist và không cho renderer hoặc model tự chọn code/action tùy ý.

## Fast evidence M09-S1 (owner machine)

- `mineflayer@4.37.1` được pin bằng npm integrity và upstream commit
  `03eba44f3e9cb93a0f0bf69a75938246e174dc6f`; không copy source upstream.
- `pnpm test:minecraft`: build TypeScript và 13 unit tests pass. Test bao phủ
  private-target validation, public-target rejection, connection failure,
  snapshot bounds, public type boundary, read-only loopback status và
  emergency stop latched/idempotent.
- `pnpm test:fast`: tổng 270 test pass trên các module đang có, gồm 13 test
  Minecraft mới.
- Production audit không còn finding nào trên dependency path
  `adapters__minecraft` sau khi override hai transitive `uuid` lên `11.1.1`.
  Workspace vẫn báo một advisory `moderate` có sẵn ở `packages/contracts>ajv`;
  finding đó không thuộc dependency path hoặc owned scope của M09-S1.
- License inventory của dependency tree chỉ báo các license permissive. SBOM
  M00 được regenerate thành công.
- Không có Minecraft server resettable đang chạy trong workspace, vì vậy chưa
  có real-server smoke, chưa đo server acknowledgement và chưa tuyên bố
  compatibility với world/version cụ thể. Candidate chỉ dành cho owner local
  test.

## Implemented in M09-S2

- Registry tĩnh hiện chỉ có `look.v1`, version 1, `destructive=false`, tối đa
  một attempt, timeout 2.000 ms và yaw/pitch tolerance 0,05 radian. Caller không
  thể đăng ký callback, đổi budget hoặc gửi field ngoài schema.
- `look.v1` chỉ chạy khi controller online, emergency stop chưa latch, player
  state tồn tại và không có skill khác đang chạy.
- Adapter gọi API `bot.look(yaw, pitch, true)` thật của Mineflayer. Promise
  resolve không phải success evidence: normalized state sau action phải có yaw
  và pitch khớp target trong tolerance thì result mới là `succeeded`.
- Timeout, vendor error, busy, missing precondition, postcondition mismatch và
  emergency cancellation đều trả mã lỗi bounded, không retry. Emergency stop
  abort active skill trước khi clear controls và disconnect.
- Không có movement/pathfinding, chat/sign/book, destructive action, LLM,
  generated code, `eval`, shell hoặc mutating HTTP route.

## Fast evidence M09-S2 (owner machine)

- `pnpm test:minecraft`: build TypeScript và 22 test pass, gồm validation,
  immutable registry, verified success, false-success rejection, vendor error,
  fake-timer timeout, concurrency guard và emergency cancellation.
- `pnpm test:fast`: tổng 279 test pass.
- Module brief và `git diff --check` pass. Không gọi model/GPU/Cloud, không tạo
  world/audio/image test và không chạy Minecraft server thật.
