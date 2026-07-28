# M08 — Perception: screen snapshot, OCR và optional VLM

- Status: M08-S1/S2 runnable candidate; M08-S3 functional GPU OCR candidate
  pending Vietnamese quality promotion; M08 remains active
- Branch: `main` (fast-development mode)
- Active slices: M08-S1 perception spine (owner-consented snapshot ingestion,
  freshness/TTL ledger, safety gating, Dev Console page); M08-S2 explicit
  Qwen3.5 local image analysis through the shared model scheduler

## Runnable target

Trang **Quan sát** trong Dev Console cho owner chụp đúng một khung hình màn
hình/cửa sổ qua hộp thoại chia sẻ của trình duyệt, gửi PNG tới control plane
loopback và xem quan sát còn hạn với đồng hồ đếm ngược TTL thật. Không có gì
được chụp tự động và không có pixel nào được lưu: runtime chỉ giữ evidence
(kích thước, SHA-256, dHash, độ sáng trung bình) trong RAM cho tới khi quan
sát hết hạn.

Khi owner chủ động đánh dấu **Nhờ Qwen3.5 local phân tích nội dung ảnh**, cùng
PNG đó được đưa qua model local trước khi byte ảnh bị bỏ. Observation chỉ nhận
một mô tả text tối đa 2.000 ký tự, luôn mang `trustLevel=untrusted`,
`decisionSupportEligible=false` và hết hạn cùng TTL. Mô tả không tự đi vào
memory, chat prompt, tool hay bộ điều khiển game.

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

## Implemented in M08-S2

- `LocalHttpChatProvider.analyze_image` dùng Ollama `/api/chat` với PNG base64
  bounded, `stream=false`, `think=false`, context runtime 4.096,
  `keep_alive=0`; OpenAI-compatible provider không được suy đoán payload.
- `ModelGateway.analyze_image` dùng cùng resource scheduler với chat, lease
  `model.vision` priority 70 và reservation 4.096 MiB. Vì text và ảnh dùng
  chung Qwen3.5-4B nên không có VLM thứ hai chiếm VRAM.
- Runtime chỉ truyền callback model đã dựng sẵn vào perception service. Lỗi
  model tạo `vision.state=error` có mã ổn định nhưng vẫn trả observation với
  hash/kích thước/TTL cơ bản; ảnh nguồn không được lưu.
- Route snapshot nhận thêm hai header bounded:
  `X-Hina-Vision-Analyze: true` và `X-Hina-Vision-Question` percent-encoded.
- Trang **Quan sát** giải thích bằng ngôn ngữ phổ thông, có checkbox opt-in,
  câu hỏi tùy chọn, kết quả mô tả/error và nhắc rõ model không thể tự bấm nút
  hoặc điều khiển game.
- Benchmark thật trên RTX 5070 Ti: `qwen3.5:4b` xử lý ảnh PNG 785.947 byte
  bằng GPU, trả mô tả tiếng Việt và không còn resident trong `ollama ps` sau
  request. Blob Ollama 3,4 GB; runtime đo khoảng 3,1 GiB GPU tại context 4K.

## Implemented in M08-S3 (GPU OCR candidate)

- `RapidOcrProvider` bọc `rapidocr==3.9.1` và PP-OCRv6 small Torch theo đúng
  URL/SHA-256 đã ghi trong model manifest. Detector, recognizer và orientation
  classifier đều bị ép sang `cuda:0`; nếu CUDA thiếu, device không khớp, model
  lỗi hoặc lease bị từ chối thì trả lỗi `E_PERCEPTION_OCR_*`, không âm thầm chạy
  CPU/ONNX/Paddle/remote API.
- OCR chỉ chạy khi owner đã chụp snapshot được policy cho phép và bật checkbox
  **Đọc chữ bằng OCR GPU**. Kết quả chỉ gồm text đã giới hạn, confidence và box
  chuẩn hóa; luôn là `untrusted`, không được đưa vào memory/chat/tool/game và
  hết hạn cùng observation tối đa 15 giây. PNG, crop, input tensor và text OCR
  không được ghi vào file hoặc log.
- Scheduler cấp một lease OCR preemptible 1.024 MiB (priority 50) và unload model
  khi bị preempt/shutdown; policy all-on vẫn giữ headroom tối thiểu 2.048 MiB.
- Dev Console hiển thị rõ đây là OCR GPU thử nghiệm, không có CPU fallback, và
  khuyên owner đối chiếu chữ có dấu/chữ nhỏ quan trọng hoặc dùng VLM local cho
  ngữ cảnh ảnh phức tạp. Checkbox không bật capture tự động.
- Smoke thật trên RTX 5070 Ti xác nhận `cuda:0`, peak 644,3 MiB allocated /
  814,0 MiB reserved, không lưu pixel/text. Corpus đã sửa để không crop câu dài
  (câu được xuống dòng như UI, còn CER bỏ qua khác biệt whitespace của wrap): mẫu
  UI ngắn CER 0,0%; mẫu tiếng Việt dài CER 6,944%. Candidate này **chưa qua**
  gate OCR UI rõ ≤5% và không được quality-promote. Số đo và SHA của weights nằm tại
  `ml/models/manifests/rapidocr-ppocrv6-small-torch.v1.json`.

## Ghi chú calibration OCR (2026-07-28)

- Corpus UTF-8 được render không crop câu dài và đo riêng lần kiểm tra thật:
  PP-OCRv6 small/960 có CER dài 6,944%, peak reserved 778–814 MiB; medium cùng
  6,944% nhưng 2.184–2.220 MiB; small/1.280 tệ hơn ở 12,5%/1.430 MiB. Vì không
  có lợi ích, runtime giữ `PP-OCRv6-small`/960/lease 1.024 MiB.
- Đây là quyết định không-promotion. Owner vẫn đối chiếu chữ có dấu/chữ nhỏ quan
  trọng bằng mắt hoặc VLM; output OCR vẫn `untrusted`, TTL ≤15 giây và không có
  quyền tự điều khiển bất cứ thứ gì.

## Deferred M08 deliverables

Chất lượng OCR tiếng Việt (benchmark corpus UI rõ/game UI khó và thay/tinh chỉnh
provider nếu vẫn không qua CER), capture allowlist theo window/region ở tầng OS,
privacy mask, event/intent-driven
capture, replay ≥200 historical/stopped capture cases và các gate OCR CER/VLM
QA của master plan thuộc các slice M08 tiếp theo. Không được đánh dấu M08
complete khi các phần này chưa có evidence.

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

## Fast evidence M08-S2 (owner machine)

- `pnpm test:text-brain`: 28/28 pass.
- `pnpm test:perception`: 33/33 pass.
- `pnpm test:fast`: safety 22, text-brain 28, memory 11, avatar 5, speech 37,
  perception 33 và core-runtime 45 tests đều pass; `node --check app.js` pass.
- Real local image smoke trả mô tả tiếng Việt từ Qwen3.5-4B; model dùng GPU và
  `keep_alive=0` làm `ollama ps` trống sau request.

## Fast evidence M08-S3 (owner machine)

- `pnpm test:perception`: 41 tests pass.
- `uv run --frozen python apps/core-runtime/tests/test_perception_routes.py`:
  11 route tests pass, gồm header OCR tới provider giả và kiểm tra không thể
  đưa raw PNG vào observation.
- `node --check apps/dev-console/public/app.js` và `pnpm smoke:dev-console`
  pass.
- One-off GPU smoke (đã dọn script tạm sau khi ghi số đo) chạy provider thật
  trên `cuda:0`, peak 644,3 MiB allocated / 814,0 MiB reserved, không persist
  pixel/text. Corpus UI Việt dài đo CER 6,944%, nên quality gate ≤5% vẫn fail.
- Runtime route smoke thật đã bật feature flag qua safety API, gửi PNG có
  `X-Hina-OCR-Analyze: true` và nhận `HTTP 200`, `ocr.state=ready`,
  `effectiveDevice=cuda:0`, `decisionSupportEligible=false`.
