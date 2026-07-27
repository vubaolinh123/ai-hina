# M08 — Perception: screen snapshot, OCR và optional VLM

- Status: M08-S1 runnable candidate; M08 remains active
- Branch: `main` (fast-development mode)
- Active slices: M08-S1 perception spine (owner-consented snapshot ingestion,
  freshness/TTL ledger, safety gating, Dev Console page)

## Runnable target

Trang **Quan sát** trong Dev Console cho owner chụp đúng một khung hình màn
hình/cửa sổ qua hộp thoại chia sẻ của trình duyệt, gửi PNG tới control plane
loopback và xem quan sát còn hạn với đồng hồ đếm ngược TTL thật. Không có gì
được chụp tự động và không có pixel nào được lưu: runtime chỉ giữ evidence
(kích thước, SHA-256, dHash, độ sáng trung bình) trong RAM cho tới khi quan
sát hết hạn.

## Implemented in M08-S1

- `workers/perception` (`hina_perception`), chỉ dùng Python standard library:
  - `PerceptionConfig` với TTL mặc định và tối đa 15 giây theo master plan,
    giới hạn byte/kích thước/tốc độ, và hai giá trị bị khóa: auto-capture off
    và snapshot persistence off (bật qua config sẽ raise lỗi).
  - `summarize_png`: decoder PNG bounded (8-bit, color type 0/2/3/4/6, không
    interlace, kiểm tra CRC) trả về evidence không chứa pixel.
  - `dhash64` + `SnapshotRateLimiter`: perceptual dedup 64-bit và sliding
    window một phút trên monotonic clock.
  - `FreshnessLedger`: bounded, in-memory, expiry bằng monotonic elapsed time
    (đổi giờ hệ thống không thể hồi sinh ảnh cũ); quan sát hết hạn bị loại
    100% khỏi mọi listing/get.
  - `PerceptionService`: mỗi snapshot phải qua `perception.observe` của
    safety policy (`consume=true`). `deny` → chặn; `ask` → cần header
    owner-confirmed; policy crash/kết quả lạ → fail closed. Nguồn hợp lệ chỉ
    là các surface owner; label được sanitize và cắt 120 ký tự.
  - `OcrProvider` chỉ là contract: chưa có dependency OCR nào qua OSS/license
    review nên status báo `contract-ready` thay vì giả vờ đọc được chữ.
- Control plane: `GET /v1/perception/status`, `GET /v1/perception/observations`,
  `POST /v1/perception/snapshots` (binary `image/png`, header correlation/
  session/source/label percent-encoded/owner-confirmed) và
  `POST /v1/perception/clear`. Lỗi có mã `E_PERCEPTION_*` ổn định, map sang
  403/410/413/429/503 tương ứng và ghi vào JSONL error log với
  `pixelDataRetained=false`.
- `HinaRuntimeApplication` tự dựng `PerceptionService` khi safety policy có
  mặt và đóng service trong cả đường lỗi lẫn shutdown.
- Dev Console: navbar **Quan sát**, page-guide riêng, nút chụp qua
  `getDisplayMedia` (hộp thoại chọn màn hình của trình duyệt là consent mỗi
  lần chụp), fallback chọn file PNG, thu nhỏ ≤1280 px + nén dưới 1 MB ngay
  trong browser, danh sách quan sát với countdown 0.5 s và activity log.
- Capability `perception.observe` và feature flag `perception` đã tồn tại từ
  M02 với mặc định tắt; slice này không sửa manifest an toàn.

## Deferred M08 deliverables

OCR provider thật (PaddleOCR hoặc RapidOCR sau license/VRAM review), optional
VLM snapshot với resource lease, capture allowlist theo window/region ở tầng
OS, privacy mask, event/intent-driven capture, replay ≥200 historical/stopped
capture cases và các gate OCR CER/VLM QA của master plan thuộc các slice M08
tiếp theo. Không được đánh dấu M08 complete khi các phần này chưa có evidence.

## Fast evidence (sandbox, Python 3.11/3.13)

- `workers/perception/tests`: 30/30 unit tests pass (config bounds, PNG
  decode/reject, dedup, rate limit, TTL T−ε/T/T+ε, fail-closed policy, label
  sanitize, no-persistence).
- `apps/core-runtime/tests/test_perception_routes.py`: 8/8 route tests pass
  với SafetyPolicyService thật (flag off → deny; ask → cần owner confirm;
  observed → TTL; duplicate; content-type; clear; missing service fail
  closed).
- `node --check app.js` pass; test_dev_console giữ nguyên xanh (một test
  memory cần `qdrant-client` không chạy được trong sandbox và phải chạy trên
  máy owner).
- Owner cần chạy trên Windows: `pnpm test:perception`, `pnpm test:fast`,
  `pnpm smoke:dev-console` và browser workflow thật của trang Quan sát.
