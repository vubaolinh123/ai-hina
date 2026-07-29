# M08 — Perception: screen snapshot và Vision

- Status: M08-S1/S2 runnable candidate; M08-S3 GPU OCR is historical and retired
  by M08-S19; M08-S4 8B Thinking text brain +
  configurable vision provider + optional session archive is a runnable
  candidate; M08-S5 realtime resource dashboard is a runnable candidate;
  M08-S6 desktop full-frame low-resolution capture is a runnable candidate;
  M08-S7 vision result + persisted configuration hotfix is a runnable candidate;
  M08-S8 bounded empty/truncated vision recovery is a runnable candidate;
  M08-S9 fresh same-session observation context is a runnable candidate;
  M08-S10 resource controls + output-quality maintenance is a runnable candidate;
  M08-S11 capture/runtime-capacity hotfix is a runnable candidate;
  M08-S12 conversation ergonomics/persona boundary is a runnable candidate;
  M08-S13 Perception dashboard modularity is a runnable candidate;
  M08-S14 Resources dashboard modularity is a runnable candidate;
  M08-S15 Speech dashboard modularity is a runnable candidate;
  M08-S16 Live2D dashboard modularity is a runnable candidate;
  M08-S17 Avatar/Runtime dashboard modularity is a runnable candidate;
  M08-S18 Avatar/Runtime trusted composable modularity is a runnable candidate;
  M08-S19 observation isolation/OCR retirement/truthful VRAM is a runnable candidate;
  M08-S20 desktop recovery/chat layout/partial-offload reasoning is a runnable
  candidate; the TTS replacement gate retained OmniVoice because tested public
  alternatives did not beat its Vietnamese owner-reference baseline;
  M08-S21 adaptive reasoning budgets and M08-S22 Qwen3.5 4B Q8_0 migration are
  runnable local candidates pending owner application acceptance; the refreshed
  all-on fast resource gate passed;
  M08 remains active
- Branch: `main` (fast-development mode)
- Active slices: M08-S1 perception spine (owner-consented snapshot ingestion,
  freshness/TTL ledger, safety gating, Dev Console page); M08-S2 explicit
  local image analysis through the shared model scheduler (historical);
  M08-S4 keeps one Qwen3-VL 8B Thinking text-brain checkpoint, moves screen
  reading to a separate Ollama Cloud/lightweight-local provider and adds
  owner-started, bounded PNG retention for a game session; M08-S5 exposes the
  all-on RAM/VRAM/model state needed to operate those providers safely;
  M08-S6 moves the primary capture authority into Electron main and sends the
  complete selected source at a bounded owner-selected resolution; M08-S7
  makes final analysis/error state and persisted Cloud configuration explicit;
  M08-S8 retries only empty or output-budget-truncated VLM completions once;
  M08-S9 lets one fresh same-session semantic observation inform owner chat
  without turning the snapshot into system instructions, memory or a tool;
  M08-S10 adds owner-only scheduler-safe model controls and prevents hidden
  model text from reaching the chat or TTS output; M08-S11 removes double
  counting of Windows VRAM, makes Brain/STT manual warmup real, and exposes
  capture-versus-vision timing without adding image persistence; M08-S12
  keeps companion chat/prompt and dashboard boundaries explicit; M08-S13 moves
  the complete owner-facing Perception workflow into a dedicated page component
  while preserving the existing capture and secret boundaries; M08-S19 isolates
  consecutive images, retires local OCR and makes model VRAM sources explicit;
  M08-S20 bounds desktop resource-control recovery and fixes the chat viewport;
  M08-S21 selects bounded viewer/emotional/game budgets on one checkpoint;
  M08-S22 replaces the retired 8B cache with one full-GPU Qwen3.5 4B Q8_0
  checkpoint while the independent Vision route remains unchanged

## Runnable target

Trang **Quan sát** trong Dev Console cho owner chụp đúng một khung hình màn
hình/cửa sổ qua hộp thoại chia sẻ của trình duyệt, gửi PNG tới control plane
loopback và xem quan sát còn hạn với đồng hồ đếm ngược TTL thật. Không có gì
được chụp tự động. Mặc định không có pixel nào được lưu: runtime chỉ giữ
evidence (kích thước, SHA-256, dHash, độ sáng trung bình) trong RAM cho tới khi
quan sát hết hạn. Owner có thể chủ động mở một phiên lưu PNG có quota; trạng
thái này mặc định tắt và không thay đổi TTL/ngữ nghĩa “ảnh hiện tại”.

Dashboard desktop hiện là capture path chính: owner bấm đọc danh sách nguồn,
chọn một màn hình/cửa sổ từ preview tạm thời rồi bấm gửi. Electron main giữ
source ID thật sau một opaque grant 60 giây dùng một lần; renderer chỉ nhận
token. Toàn bộ khung hình được giữ nguyên bố cục và hạ cạnh dài xuống
640/960/1.280 px (mặc định 960) trước khi gửi.

Khi owner chủ động đánh dấu **Nhờ provider vision đã chọn phân tích nội dung
ảnh**, cùng PNG đó được đưa qua Ollama Cloud hoặc model Ollama local nhẹ đã cấu
hình trong Dashboard desktop. Observation chỉ nhận một mô tả text
tối đa 2.000 ký tự, luôn mang `trustLevel=untrusted`,
`decisionSupportEligible=false` và hết hạn cùng TTL. Trong tối đa 15 giây,
owner có thể hỏi Hina về ảnh vừa chụp trong đúng phiên chat đó. Runtime đưa
tối đa một mô tả semantic vào user-role block bị giới hạn và gắn nhãn
untrusted; không đưa raw pixel/hash/box vào prompt, không ghi vào memory,
không cấp quyền tool và không cho Hina tuyên bố đang nhìn màn hình trực tiếp.

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

## Implemented in M08-S2 (historical 4B baseline)

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

M08-S4 supersedes model selection and runtime parameters above; this baseline
is retained only for audit/rollback comparison.

## Implemented in M08-S3 (historical GPU OCR candidate, retired in M08-S19)

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
  gate OCR UI rõ ≤5% và không được quality-promote. Active model manifest and
  provenance were deleted when M08-S19 retired this product path; Git history
  and the M08-S3 Module Brief retain the audit decision.

## Ghi chú calibration OCR (2026-07-28)

- Corpus UTF-8 được render không crop câu dài và đo riêng lần kiểm tra thật:
  PP-OCRv6 small/960 có CER dài 6,944%, peak reserved 778–814 MiB; medium cùng
  6,944% nhưng 2.184–2.220 MiB; small/1.280 tệ hơn ở 12,5%/1.430 MiB. Vì không
  có lợi ích, runtime giữ `PP-OCRv6-small`/960/lease 1.024 MiB.
- Đây là quyết định không-promotion. M08-S19 sau đó xóa provider, dependency,
  scheduler row và UI OCR; owner dùng Vision cho nội dung chữ/màn hình.

## Implemented in M08-S4 (8B Thinking brain + vision provider + session archive)

- Default text brain uses exactly one pinned
  `qwen3-vl:8b-thinking-q4_K_M` checkpoint. No Instruct checkpoint is loaded or
  swapped. Simple chat uses the same-weight preclosed-thought fast path; complex
  text uses bounded hidden thinking. Hidden reasoning never reaches UI/TTS/log.
- Screen perception no longer calls `ModelGateway.analyze_image`. Runtime owns
  a separate configurable `OllamaVisionProvider`: `ollama_cloud` uses the fixed
  `https://ollama.com/api` boundary and zero local model VRAM;
  `ollama_local` discovers `/api/tags`, verifies each candidate with `/api/show`
  capability `vision`, keeps only the lightweight ≤5 GB/approximately ≤5B
  profile, acquires a 5.120 MiB shared scheduler lease, bounds local context at
  4.096 tokens, requests `num_gpu=999` and sends `keep_alive=0`.
- Dashboard desktop has a dedicated **Quan sát** page. The owner can enter or
  replace an Ollama Cloud key, discover the models the account can access,
  inspect parameter/size/VRAM fields and apply a model. Electron main encrypts
  the key through OS `safeStorage` under `userData`; renderer/status/logs/Git
  never receive persisted plaintext. Provider/model/key survive restart and
  are restored into runtime RAM automatically; **Xóa API key đã lưu** is the
  explicit removal action.
- Runtime uses context 8.192, text-fast/thinking budgets 192/768, full GPU
  offload request, `keep_alive=0`, a text-brain scheduler reservation of
  8.192 MiB and a default end-to-end brain deadline of ten seconds
  (one-second admission + nine-second provider deadline).
- Real RTX 5070 Ti text-brain smoke passed for simple chat (2,939 s) and
  arithmetic reasoning (6,160 s). Peak total physical VRAM was 9.975 MiB of
  16.303 MiB, leaving 6.328 MiB free. The earlier 4,363-second image number is
  retained only as pre-separation evidence; Ollama Cloud adds no local model
  VRAM. A Cloud call is intentionally not spent until the owner applies a model
  through the new encrypted Dashboard setting.
- Optional archive remains default-off and can start only after a current
  owner action plus the existing `perception.observe` policy decision. The
  service generates every UUID/path, writes only revalidated PNG with exclusive
  create + fsync, and caps each session at 300 images or 256 MiB under
  `var/perception-sessions/<uuid>`.
- Dashboard displays the exact root/session/file path and provides **Bắt đầu lưu
  phiên**, **Dừng lưu**, and **Đọc lại ảnh cuối**. Stopping or shutting down
  prevents new writes but deliberately leaves PNGs for the owner to remove
  after the game session.
- Historical reanalysis revalidates the stored PNG and calls the currently
  configured vision provider, but never creates a `FreshnessLedger`
  observation. Its response is explicitly `historical=true`,
  `currentObservation=false`, `decisionSupportEligible=false`.
- Normal capture remains RAM-only. Archive files contain no OCR/model output,
  prompt, metadata sidecar or conversation data. In-memory archive indices are
  bounded and cannot accept caller-provided paths.
- Exact upstream revision, Ollama digest/blob SHA, license and measurements are
  recorded in
  `ml/models/manifests/qwen3-vl-8b-thinking-q4-k-m.v1.json`.

## Implemented in M08-S5 (realtime resource observability)

- Control plane có route chỉ đọc `GET /v1/resources/status`. Response chỉ gồm
  telemetry vật lý, lease scheduler, model/service state và RSS tiến trình đã
  whitelist; không trả prompt, chat, ảnh, API key, command line hoặc đường dẫn
  voice/private.
- `NvidiaSmiTelemetry` đọc VRAM total/used/free, GPU utilization, nhiệt độ,
  power và RAM hệ thống bằng subprocess không qua shell với output bounded.
  Trường driver không hỗ trợ được giữ là `null`, không giả thành số 0.
- `LocalResourceScheduler.monitor_status()` trả reservation và lease owner,
  priority, preemptible, TTL còn lại. Reservation được ghi rõ là admission
  budget, không phải allocation cộng thêm vào số physical.
- Ollama `/api/ps` phân biệt model đã cài với model đang resident. STT/TTS/OCR
  dùng status `modelLoaded` của provider; vision Cloud được đánh dấu remote và
  có local model VRAM bằng 0.
- Electron main giữ history tối đa 100 transition load/unload trong RAM và bổ
  sung RSS của desktop. Renderer chỉ gọi typed operator IPC, không có quyền
  process/network/filesystem. Poll 1,5 giây chỉ chạy khi page **Tài nguyên AI**
  đang mở; chart giữ tối đa 60 mẫu.
- Dashboard giải thích cho người không phải developer: physical use khác
  reservation thế nào, loaded/unloaded nghĩa gì, Cloud ảnh hưởng VRAM ra sao,
  và cảnh báo đỏ khi vượt trần 14.336 MiB hoặc còn dưới 2.048 MiB VRAM.

## Implemented in M08-S6 (desktop full-frame low-resolution capture)

- Owner quyết định không dùng crop hoặc privacy mask: Hina nhận toàn bộ nội
  dung của đúng màn hình/cửa sổ đã chọn. Để giảm payload/token/latency, owner
  chọn cạnh dài 640, 960 hoặc 1.280 px; desktop mặc định 960 px và không phóng
  to nguồn nhỏ.
- `desktopCapturer.getSources` chỉ chạy trong Electron main. Renderer sandboxed
  nhận preview PNG bounded, tên nguồn và UUID token; raw
  `DesktopCapturerSource.id` không rời main process.
- Mỗi source listing tạo grant in-memory tối đa 48 nguồn, hết hạn sau 60 giây
  và bị tiêu thụ sau đúng một capture attempt. Widget không được list/capture;
  chỉ operator window có typed IPC.
- Main process lấy lại đúng source đã allowlist, encode PNG ≤1 MB rồi POST tới
  route perception loopback với `owner.desktop` + owner confirmation. Không có
  interval/auto-capture, không lưu source list/preview/snapshot xuống đĩa.
- Trang **Quan sát** desktop cho bật/tắt đúng feature flag `perception`, chọn
  nguồn, resolution, label, OCR GPU và provider vision đã cấu hình; mọi lỗi
  được log ra console `pnpm start:desktop`.
- Electron 43 API được dùng trực tiếp từ dependency đã pin; không thêm package
  hoặc source copy mới.

## Implemented in M08-S7 (vision result and persisted configuration hotfix)

- Correlation `c5b5b0d3-ba26-48b1-8c01-12770539ea47` chứng minh base snapshot
  được nhận nhưng MiniMax M3 Cloud trả `E_PERCEPTION_VISION_EMPTY`. Model có
  capability thinking và request cũ không đặt `think`, nên budget 256 token có
  thể kết thúc trước khi `message.content` xuất hiện.
- Explicit image analysis nay gửi `think=false`. Hidden reasoning không được
  dùng làm fallback/summary; chỉ final `message.content` không rỗng mới tạo
  `vision.state=ready`.
- Dashboard không còn đồng nhất snapshot acceptance với analysis success. Nó
  hiện riêng `ready`, `not-requested` hoặc `error`, provider/model error code và
  correlation ID; console cũng ghi error code bounded.
- Khi status trả provider/model/key đã lưu, model được thêm ngay vào select dù
  chưa discovery và vision checkbox mặc định bật cho capture explicit. Sau khi
  owner tự đổi checkbox, refresh status không ghi đè lựa chọn đó.
- UI chỉ nhận boolean `apiKeyConfigured`. Ô key trống tiếp tục dùng ciphertext
  cũ; key mới được verify với provider trước rồi mới atomically thay ciphertext,
  không trả plaintext về renderer/log/status.
- Real Cloud smoke sau restart dùng chính persisted `minimax-m3`, trả
  `vision.state=ready` và summary Việt 140 ký tự. Archive vẫn tắt, normal capture
  không persist pixel và feature perception được restore về tắt sau smoke.

## Implemented in M08-S8 (bounded empty/truncated response recovery)

- Hai correlation owner `64b371e7-80db-467d-ac6f-f59c8b6fbb2d` và
  `215e4ffc-d15e-4c42-a8d7-80f20d4c28d1` trên build `317462e` xác nhận cùng
  snapshot 144.950 byte vẫn trả `E_PERCEPTION_VISION_EMPTY` dù request đã đặt
  `think=false`. Một ảnh UI phức tạp khác còn tạo final text cụt
  `": bên trái là trình soạn thảo văn bản với"` ở budget 256.
- Provider nay đọc `done_reason` và `eval_count` của Ollama. Final content rỗng
  hoặc đã chạm output budget không được coi là summary hoàn chỉnh; đúng một
  recovery request được phép dùng prompt bắt đầu ngay bằng kết luận và ceiling
  768 token. Mọi lỗi auth/offline/timeout/protocol/capacity vẫn không retry.
- Cả hai request giữ `stream=false`, `think=false`; `message.thinking` không
  được dùng làm summary, không đưa vào recovery prompt và không ghi log. Nếu
  lượt thứ hai vẫn rỗng hoặc bị cắt, provider trả mã ổn định tương ứng
  `E_PERCEPTION_VISION_EMPTY` hoặc `E_PERCEPTION_VISION_TRUNCATED`.
- Local-provider recovery giữ đúng một scheduler lease cho cả hai lượt, assert
  lease sau từng response rồi release đúng một lần.

## Implemented in M08-S9 (fresh same-session observation context)

- `PerceptionService.fresh_context_for_turn` đọc lại freshness từ monotonic
  ledger đúng lúc compose turn. Chỉ `owner.console`, đúng session UUID và đúng
  một observation semantic mới nhất được chọn; metadata-only, archived,
  expired, khác session hoặc khác lane đều bị loại.
- `ContextComposer` đặt dữ liệu vào user-role block
  `[UNTRUSTED_FRESH_OBSERVATION_DATA]`, escape delimiter giả do ảnh/OCR chứa và
  chỉ cho qua label, kích thước, TTL còn lại, vision summary cùng OCR text đã
  bound. System prompt chỉ nhận trusted availability metadata. Nếu block không
  vừa byte budget, turn quay về trạng thái không có ảnh thay vì cắt dở hoặc lỗi.
- Desktop capture dùng cùng UUID với phiên chat. Sau khi phân tích thành công,
  nút **Hỏi Hina ngay về ảnh vừa chụp** chuyển sang trang Chat và gửi câu hỏi
  trong đúng session; sau 15 giây nút không thể hồi sinh context đã hết hạn.
- Observation không được thêm vào short-term replay, long-term memory, tool
  proposal hoặc game controller. Model được nhắc nói “ảnh vừa chụp”, không nói
  “mình đang nhìn màn hình”.
- Launcher chạy bounded fast-path check trên đúng checkpoint Thinking/GPU trước
  khi mở operator rồi unload bằng `keep_alive=0`, tránh first-turn timeout do
  cold load mà không giữ thêm model. Parser cũng bỏ toàn bộ prefix trước orphan
  `</think>`; block có `<think>` thật vẫn fail closed và hidden text không đi
  vào replay/TTS.

## Implemented in M08-S10 (resource control and output quality)

- Trang **Tài nguyên AI** có thao tác **Tải cưỡng ép** và **Gỡ cưỡng ép** cho
  từng provider local. Electron renderer chỉ gọi typed operator IPC; runtime
  chỉ nhận model ID allowlist, `load|unload`, `owner.desktop` và xác nhận owner.
  Không có đường truyền lệnh hay tên model tùy ý. Cloud vision báo rõ không có
  VRAM local để tải và trả no-op thay vì giả lập resident state.
- Warmup luôn xin lease từ scheduler nên vẫn giữ headroom 2.048 MiB. Text brain
  có operator pin riêng; STT, TTS, OCR và local VLM chỉ unload sau công việc
  đang chạy. Local VLM serializes warmup/unload để force-unload không giải
  phóng checkpoint giữa một lượt phân tích.
- VLM prompt yêu cầu overview tiếng Việt 6–8 câu, bao quát cảnh/bố cục,
  thực thể và trạng thái, chữ đọc được, tín hiệu trực quan, cùng mức độ không
  chắc chắn. Initial budget là 512 token, recovery cho empty/truncated vẫn
  giới hạn 768 token; summary bị bound ở 3.500 ký tự.
- Conversation chỉ phát final answer sạch. Prefix/suffix hidden reasoning,
  system/developer prompt, control token, markdown heading nội bộ và pattern
  `--- **Phân tích hành vi:**` cùng dòng đều bị loại trước moderation, replay
  và TTS. Dashboard hiện **Hina đang suy nghĩ…** trong lúc turn còn chạy rồi
  xóa nó khi complete/interrupted/error.
- Persona yêu cầu câu trả lời tiếng Việt ngắn, dấu câu đầy đủ và không markdown;
  normalizer đổi dash thành ranh giới câu rõ ràng trước OmniVoice. Profile
  OmniVoice vẫn giữ rate tự nhiên 1.0x, tối đa 110 ký tự mỗi chunk.
- Không thêm dependency/model, không lưu hidden text/pixel/audio/API key, không
  mở release promotion hoặc deep verification trong slice này.

## Deferred M08 deliverables

Chất lượng OCR tiếng Việt (benchmark corpus UI rõ/game UI khó và thay/tinh chỉnh
provider nếu vẫn không qua CER), event/intent-driven capture, replay ≥200
historical/stopped capture cases và các gate OCR CER/VLM QA của master plan
thuộc các slice M08 tiếp theo. Capture allowlist theo source ở Electron main đã
có; yêu cầu region/crop/privacy-mask được owner chủ động supersede ngày
2026-07-28 bằng full-frame downscale, nên không còn là blocker hoàn tất M08.
Không được đánh dấu M08 complete khi các phần còn lại chưa có evidence.

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

## Fast evidence M08-S4 (owner machine)

- `pnpm test:text-brain`: 33 tests pass.
- `pnpm test:perception`: 50 tests pass, including Cloud-secret redaction,
  capability-filtered discovery, Cloud auth failure propagation, local
  byte/parameter capacity rejection, bounded context/full-GPU request and
  scheduler lease.
- `python -m unittest discover ... test_perception_routes.py`: 13 route tests
  pass, including start → archived PNG → clear current observations →
  historical reanalysis → stop while the PNG remains outside the TTL ledger,
  plus vision discover/configure/disable without secret reflection.
- `pnpm test:desktop`: 42 tests pass, including OS-encrypted provider state,
  strict IPC and a renderer that cannot read the stored key.
- `node --check apps/dev-console/public/app.js` and the Node workspace check
  pass.
- Two real text requests used the pinned Thinking checkpoint with
  `keep_alive=0`; simple/complex latency and VRAM stayed inside the
  ten-second/14-GiB gates listed above. Real local model discovery returned only
  capability-verified candidates and excluded the 8B brain from the
  lightweight vision selection.

## Fast evidence M08-S5 (owner machine)

- `pnpm test:text-brain`: 38 tests pass, gồm `/api/ps` residency parsing và
  không lộ digest/field ngoài allowlist.
- Resource scheduler/config tests: 10 pass; resource control-plane route tests:
  2 pass, gồm degraded telemetry và redaction.
- `pnpm --filter @hina/desktop test`: build + 46 tests pass, gồm bounded
  transition tracker, operator-only IPC và renderer không có process/network.
- `node tools/dev/check-node-workspace.mjs`: pass.
- Fast Electron startup smoke qua page thật pass: typed IPC trả 5 model row,
  chart nhận sample đầu và core RSS là số dương. Live endpoint sau smoke trên
  RTX 5070 Ti trả 2.199 MiB VRAM used, 13.797 MiB free, 15.496 MiB RAM system
  used và 563 MiB core RSS; không có lease active, text/STT/TTS/OCR đều
  `unloaded`, vision Cloud `cloud-ready`. Đây là snapshot quan sát, không phải
  all-on benchmark hoặc số cố định.

## Fast evidence M08-S6 (owner machine)

- `pnpm --filter @hina/desktop typecheck`: pass.
- `pnpm --filter @hina/desktop test`: build + 52 tests pass, gồm grant
  expiry/single-use, opaque source token, preset resolution, full-frame aspect,
  PNG/header contract, operator authority và renderer isolation.
- Electron smoke thật tìm thấy 9 source, không trả source ID, render đúng page
  **Quan sát** với mặc định 960 px và chặn widget gọi capture.
- Cùng smoke đã bật quyền perception tạm thời, chụp/gửi một full-frame
  640×360/144.619-byte tới runtime với `status=observed`,
  `persistedByDesktop=false`, không gọi OCR/VLM, rồi trả feature flag về trạng
  thái ban đầu. Không tạo screenshot/audio/script test trên đĩa.

## Fast evidence M08-S7 (owner machine)

- `pnpm test:perception`: 50 tests pass.
- `pnpm --filter @hina/desktop test`: build + 52 tests pass.
- `pnpm --filter @hina/desktop typecheck`: pass.
- Real persisted MiniMax M3 Cloud request trên PNG tracked hiện hữu:
  `vision.state=ready`, summary 140 ký tự, provider/model error `null`.
- Không tạo raw screenshot, audio, fixture hoặc one-off script mới; archive và
  normal pixel persistence đều giữ tắt.

## Fast evidence M08-S8 (owner machine)

- `pnpm test:perception`: 58 tests pass, gồm empty recovery, truncated partial
  rejection, double-failure code, no-retry provider error và one-lease local
  recovery.
- Real persisted MiniMax M3 Cloud request trên ảnh UI 2.082×1.167/280.451 byte:
  `vision.state=ready`, summary Việt hoàn chỉnh 3 câu, 16.703 ms,
  `lastErrorCode=null`.
- Snapshot test không được archive; `pixelDataRetained=false`. Không tạo raw
  screenshot, fixture, script one-off hoặc debug dump mới.

## Fast evidence M08-S9 (owner machine)

- `pnpm test:text-brain`: 41 tests pass; `pnpm test:perception`: 59 tests pass;
  `uv run --frozen python apps/core-runtime/tests/test_dev_console.py`: 9 tests
  pass với `PYTHONPATH` workspace; `pnpm --filter @hina/desktop test`: 53 tests
  pass; `pnpm smoke:dev-console`: pass.
- Startup fast-path trên cùng Qwen3-VL 8B Thinking hoàn tất trong 2,76 giây,
  full GPU và unload sau check. Không load checkpoint thứ hai.
- Real in-memory capture 960×286/211.545 byte qua persisted MiniMax M3 trả
  `vision.state=ready`. Fresh chat correlation
  `529261da-3298-4a7b-8781-cf17d083b50d` báo
  `includedFreshObservations=1` và mô tả đúng nội dung hai màn hình. Sau 16 giây,
  correlation `7aa1fbbb-4b04-4086-9578-79458bb38fad` báo
  `includedFreshObservations=0`.
- Smoke giữ PNG trong `MemoryStream`, không ghi ảnh ra đĩa; archive tắt,
  `pixelDataRetained=false`, feature perception được trả về tắt. Script
  one-off và artifact latency đã được xóa sau khi lấy số đo.

## Fast evidence M08-S10 (owner machine)

- Narrow tests passed: text brain 44, speech 22, perception 61 and resource
  route 5. Desktop build + 53 tests and desktop typecheck passed.
- `pnpm smoke:desktop` now uses the same launcher as `pnpm start:desktop`,
  waits for the loopback control plane and passed end-to-end in smoke mode.
  This prevents the former false `E_DESKTOP_CONTROL_OFFLINE` result caused by
  starting Electron directly.
- New tests cover allowlist/owner confirmation, scheduler denial, local
  warmup/unload state, active VLM analysis waiting for unload, detailed
  recovery prompt and inline hidden-analysis stripping.
- This slice created no raw screenshot, audio, cache/model download, fixture,
  debug dump or one-off script. A cleanup audit identified legacy M07 smoke
  files under `var/tmp`; the platform denied the verified deletion operation,
   so their exact targets remain listed for owner cleanup. Generated desktop
   build output remains the normal runnable artifact of `pnpm start:desktop`,
   not verification evidence.

## Implemented in M08-S11 (capture latency, manual warmup and capacity hotfix)

- Owner-approved admission ceiling is now **15,872 MiB (15.5 GiB)**. NVIDIA
  `memory.free` already excludes Windows, the compositor and other GPU apps, so
  scheduler admission no longer subtracts an additional fixed 2,048 MiB. The
  live free value remains a hard physical cap; this is not permission to exceed
  what is actually free on the card.
- Text-brain owner warmup now has a separate bounded 45-second cold-load
  deadline instead of the 3-second health-probe timeout, disables thinking for
  its one-token request, and reports a bounded HTTP/timeout/connection cause.
- `FasterWhisperProvider` now implements true owner Force load / Force unload:
  the configured CUDA model is loaded under an accounted scheduler lease, stays
  resident only until explicit unload or preemption, and never falls back to CPU
  for a manual CUDA load. Timeout drainage retains the lease until the native
  worker is truly finished.
- Vision accepts a complete punctuated final even if a Cloud provider labels it
  `length`; incomplete output still gets exactly one shorter recovery request.
  The normal overview target is 4–6 sentences/≤140 words, while recovery is
  3–4 sentences/≤110 words. Vision result now includes bounded processing time.
- Electron now reports three non-sensitive progress phases—capture, PNG encode,
  and runtime analysis—and displays source lookup, encoding, runtime and total
  time after a result. Raw pixel bytes, source IDs, Cloud keys and prompts still
  never cross typed renderer IPC or get logged.

## Fast evidence M08-S11 (owner machine)

- `pnpm test:text-brain`: 46 tests pass, including the 15.5-GiB static ceiling,
  live-free hard cap and owner warmup request shape.
- `pnpm test:speech`: 40 tests pass, including CUDA Faster-Whisper Force load,
  reuse during one transcription and exact release on Force unload.
- `pnpm test:perception`: 62 tests pass, including complete-at-boundary Vision
  acceptance, incomplete recovery and timing fields on ready/error results.
- `pnpm --filter @hina/desktop typecheck` and `pnpm test:desktop` pass; desktop
  build has 53 tests, including typed capture progress with no raw source ID in
  the renderer bridge.
- This maintenance slice intentionally runs no real Cloud capture, native model
  warmup or all-on VRAM benchmark against the owner’s active desktop session.
  It creates no raw screenshot, audio, model cache, fixture or one-off script.

## Implemented in M08-S12 (conversation ergonomics and persona boundary)

- `hina.prompt.v4` defines Hina as an emotionally present conversational
  companion, not a technical tutor. It no longer permits code, HTML, commands,
  syntax or step-by-step technical tutorials, even for an owner request. A
  direct technical request is answered by a short in-character redirect before
  the model is called; code-shaped model output is replaced by the same safe
  companion response before moderation, memory, UI or TTS.
- The output finalizer removes only a trailing, non-actionable meta disclaimer
  such as “(Chú ý: đây chỉ là phản hồi giả định …)”. It does not erase direct
  action-oriented medical or safety advice in the main answer.
- Text context now has a 8,192-token configured window and a conservative
  32,768-byte composition guard for the default brain. Desktop shows aggregate
  context window, last composed approximate token use, recent turns and included
  approved memory/fresh-observation counts. The meter is explicitly an estimate
  based on UTF-8 bytes; no prompt, hidden reasoning or raw history is exposed.
- Dashboard navigation, Overview and Chat are now modules under
  `apps/desktop/src/dashboard/`. Chat owns its scroll behavior: new messages
  follow automatically unless the owner scrolls away, while the composer stays
  sticky below the fixed header/nav on desktop and returns to normal flow on a
  compact window. The documented migration rule prevents new root markup from
  being added to legacy pages.

## Fast evidence M08-S12 (owner machine)

- `pnpm test:text-brain`: 47 tests pass, including meta-disclaimer removal,
  zero provider calls for a direct HTML request, code-shaped output fallback,
  8,192-token context telemetry and no prompt text in status.
- `pnpm --filter @hina/desktop typecheck` and `pnpm test:desktop` pass; desktop
  build has 54 tests, including modular renderer isolation, context-meter and
  sticky-composer assertions.
- `pnpm test:fast` passes: text 47, speech 40, perception 62 and core runtime
  55 plus the existing narrow suites. No real model, Cloud, voice, screenshot,
  cache/model download, fixture or one-off script was created for this slice.

## Implemented in M08-S13 (Perception page modularity)

- `apps/desktop/src/dashboard/pages/PerceptionPage.vue` now owns all owner-facing
  markup for the explicit màn hình/cửa sổ picker, bounded resolution and OCR/VLM
  choices, result/error/timing explanation, and Cloud/local Vision provider
  controls. It has no direct Electron, Node, fetch, storage or model-runtime
  access.
- `App.vue` stays the sole owner of `window.hinaDesktop`, Safety feature control,
  opaque single-use source grants, the chat session UUID, Vision key lifecycle,
  capture progress/error logging and actual capture/Vision IPC. The extracted
  page receives only typed bounded display state and emits intent/field updates.
- No capture behavior changed: capture remains explicit owner-click only,
  source IDs remain in Electron main, the 60-second grant remains single-use,
  Cloud keys remain encrypted behind `safeStorage`, and image/observation TTL
  semantics are unchanged.
- The dashboard architecture rule now records Perception as migrated. Speech,
  Resources, Live2D and Avatar/Runtime are still legacy root pages and must be
  moved one full page at a time rather than adding more `App.vue` markup.

## Fast evidence M08-S13 (owner machine)

- `pnpm --filter @hina/desktop typecheck`: pass.
- `pnpm test:desktop`: build + 54 tests pass, including the extracted
  Perception page in renderer-isolation, key-boundary and opaque-grant checks.
- No model, Cloud request, capture, audio, cache/model download, fixture or
  one-off script was created for this UI-boundary slice.

## Implemented in M08-S15 (Speech page modularity)

- `apps/desktop/src/dashboard/pages/SpeechPage.vue` now owns all owner-facing
  markup for the explicit Mic/STT/TTS test workflow: runtime status, realtime
  preference, start/stop recording controls, transcript/correlation display,
  bounded TTS text and playback UI. It has no direct Electron, Node,
  MediaDevices, fetch, storage or model-runtime access.
- `App.vue` remains the sole owner of `MicrophoneRecorder`, `getUserMedia`, WAV
  construction, realtime transcript throttling, TTS audio object-URL lifecycle,
  typed speech IPC and error logging. The page emits intent or field updates;
  recording still begins only after the existing explicit owner click.
- This extraction does not change audio duration/size bounds, STT/TTS provider
  selection, GPU scheduling, microphone permissions, persistence or speech
  content. The TTS heading now correctly identifies the active OmniVoice GPU
  runtime rather than the retired VieNeu label.
- The dashboard architecture rule now records Speech as migrated. Only Live2D
  and Avatar/Runtime remain legacy root pages for future bounded migration.

## Fast evidence M08-S15 (owner machine)

- `pnpm --filter @hina/desktop typecheck`: pass.
- `pnpm test:desktop`: build + 54 tests pass, including SpeechPage in renderer
  isolation and the preserved microphone/typed-IPC boundary checks.
- No microphone capture, TTS inference, model, Cloud request, cache/model
  download, fixture or one-off script was created for this UI-boundary slice.

## Implemented in M08-S16 (Live2D page modularity)

- `apps/desktop/src/dashboard/pages/Live2DPage.vue` now owns all owner-facing
  markup for VTube Studio status, explicit connect/disconnect/refresh, fixed
  hotkey and movement controls, Spout2 status and asset/provenance explanation.
  It has no direct Electron, Node, WebSocket, fetch, storage or bridge-runtime
  access.
- `App.vue` and Electron main remain sole owners of typed VTube Studio IPC,
  encrypted token lifecycle, `ws` transport, fixed hotkey/movement dispatch,
  Spout bridge polling and error logging. The extracted page receives no token,
  protocol frame, WebSocket handle, arbitrary payload capability or raw frame.
- This extraction does not change VTube Studio endpoint/authorization behavior,
  Spout sender allowlist/loopback, transparent-capture guidance or the VRM
  fallback. The user-visible controls retain their existing disabled states.
- The dashboard architecture rule now records Live2D as migrated. Avatar/Runtime
  remains the final legacy root page for a future bounded migration slice.

## Fast evidence M08-S16 (owner machine)

- `pnpm --filter @hina/desktop typecheck`: pass.
- `pnpm test:desktop`: build + 54 tests pass, including Live2DPage in renderer
  isolation and preserved VTube Studio/Spout typed-boundary checks.
- No VTube Studio connection, Spout capture, model, Cloud request, cache/model
  download, fixture or one-off script was created for this UI-boundary slice.

## Implemented in M08-S14 (Resources page modularity)

- `apps/desktop/src/dashboard/pages/ResourcesPage.vue` now owns all owner-facing
  markup for realtime RAM/VRAM telemetry, model residency, scheduler leases,
  bounded in-memory timeline and Force load/unload affordances. It has no direct
  Electron, Node, fetch, storage, NVIDIA tooling or model-runtime access.
- `App.vue` remains the sole owner of visibility-scoped 1.5-second polling,
  bounded 60-sample history, telemetry/error logging, resource analysis and the
  typed, allowlisted resource-control IPC call. The page emits only refresh or a
  `{ model, action }` intent; scheduler admission remains authoritative.
- No resource behavior changed: Cloud remains a no-op for local residency,
  missing driver metrics remain null/“Không hỗ trợ” instead of zero, and owner
  controls still cannot execute arbitrary model names or system commands.
- The dashboard architecture rule now records Resources as migrated. Speech,
  Live2D and Avatar/Runtime remain legacy root pages and must be moved as whole,
  bounded page slices.

## Fast evidence M08-S14 (owner machine)

- `pnpm --filter @hina/desktop typecheck`: pass.
- `pnpm test:desktop`: build + 54 tests pass, including ResourcesPage in
  renderer-isolation, typed resource IPC and no-direct-system-access checks.
- No model, Cloud request, capture, audio, cache/model download, fixture or
  one-off script was created for this UI-boundary slice.

## Implemented in M08-S17 (Avatar and Runtime page modularity)

- `apps/desktop/src/dashboard/pages/AvatarPage.vue` now owns the complete
  owner-facing Avatar Stage: lazy-stage presentation, SVG fallback, renderer
  telemetry, manual preview, visual provenance and bounded renderer snapshot.
  It receives a stage component/status data and emits only typed stage events or
  fixed preview/retry intent; it has no Electron, Node, network, storage or
  model-runtime capability.
- `apps/desktop/src/dashboard/pages/RuntimePage.vue` now owns the complete
  **Runtime & Safety** page. Widget show/hide/reset, mute and emergency controls
  emit only their pre-existing fixed action set. The page never receives a raw
  IPC handle, window handle, token, stored position record or arbitrary command.
- `App.vue` remains the sole owner of VRM lazy loading/recovery, typed avatar,
  widget and Safety IPC, polling, retry/backoff, widget persistence lifecycle
  and console error logging. No renderer, widget, VRM, Safety or control-plane
  behavior changed; this is a page-boundary refactor only.
- The dashboard migration is now complete for all current pages. New owner UI
  belongs in a `dashboard/pages` component rather than the `App.vue` shell.

## Fast evidence M08-S17 (owner machine)

- `pnpm --filter @hina/desktop typecheck`: pass.
- `pnpm test:desktop`: production build + 54 tests pass, including both pages in
  renderer isolation and the preserved lazy-VRM/widget/Safety typed-boundary
  checks.
- No real desktop/widget/avatar session, VTube Studio/Spout connection,
  microphone, TTS, model, Cloud request, cache/model download, fixture or
  one-off script was created for this UI-boundary slice.

## Implemented in M08-S18 (Avatar/Runtime trusted composable)

- `apps/desktop/src/composables/use-avatar-runtime.ts` now owns Avatar/Widget/
  Runtime state, the fixed typed preload calls for Avatar/Widget and Runtime
  mute/emergency controls, bounded control-plane retry/backoff, 250 ms Avatar
  polling, one-second Safety/widget polling and all VRM event/recovery state.
  It imports only Vue and local metrics typing; no Electron, Node, fetch,
  persistence, process, model or arbitrary-command capability.
- `App.vue` now composes this trusted renderer boundary with global lifecycle,
  navigation and the remaining independent workflows. It no longer contains the
  Avatar/Runtime state machine, inline typed IPC handlers, poll timers or VRM
  recovery implementation. The existing Perception feature-flag action remains
  in its separate workflow and refreshes Safety through the composable.
- `AvatarPage.vue` and `RuntimePage.vue` remain pure typed presentation/intent
  components. All existing fixed controls and disabled states keep their former
  behavior; this slice adds no provider/model/VRAM/network work.

## Fast evidence M08-S18 (owner machine)

- `pnpm --filter @hina/desktop typecheck`: pass.
- `pnpm test:desktop`: production build + 54 tests pass, including the composable
  in the trusted-renderer isolation check and preserved lazy-VRM/Safety/widget
  contracts.
- No real desktop/widget/avatar session, VTube Studio/Spout connection,
  microphone, TTS, model, Cloud request, cache/model download, fixture or
  one-off script was created for this UI-boundary slice.

## Implemented in M08-S19 (observation isolation, OCR retirement and truthful VRAM)

- A chat turn that includes a fresh screenshot now excludes earlier
  screenshot-derived user/assistant turns from short-term replay. The current
  turn still receives exactly the newest same-session observation within the
  15-second monotonic TTL. This prevents screenshot 2 from carrying screenshot
  1's description back into the model.
- The final-answer sanitizer now truncates or rejects provider output that
  exposes internal observation delimiters or English control narration such as
  `UNTRUSTED_FRESH_OBSERVATION_DATA`, “I need to check the context” or “Looking
  back at the previous observation”. Rejected text never reaches memory, desktop
  chat or TTS.
- The failed local OCR candidate has been retired from runtime construction,
  snapshot headers/contracts, desktop and Dev Console UI, scheduler controls,
  Python dependencies, model manifest and active provenance. Screen reading now
  uses the explicit owner-triggered Cloud/local Vision provider only. Historical
  M08-S3 documentation remains an audit record and is not an active runtime
  contract.
- Resource rows now distinguish:
  - `measuredVramMiB`: current provider-reported resident/allocated value;
  - `providerPeakVramMiB`: peak measured inside the most recent provider
    request when that provider exposes a CUDA allocator counter;
  - `sampledPeakVramMiB`: the highest current value observed by the desktop's
    1.5-second polling loop during this desktop session;
  - `measurementSource` and `measurementNote`: the source and limitation of the
    number.
- Ollama rows use `/api/ps.size_vram`; OmniVoice uses its Torch CUDA allocated
  and reserved counters; Cloud Vision is truthfully zero local model VRAM.
  Faster-Whisper remains `null` with an explicit explanation because CTranslate2
  does not expose exact per-model VRAM inside the shared native worker. A fixed
  reservation is never displayed as a measured allocation.

### Context-window budget for the current Qwen3-VL 8B brain

The installed model reports 36 layers, 8 KV heads and 128 dimensions for both
K and V. With an f16 KV cache, the theoretical cache cost is:

`36 × 8 × (128 K + 128 V) × 2 bytes = 147,456 bytes/token`.

| Context | f16 KV cache | Increase over 8,192 | q8_0 increase over 8,192 |
| --- | ---: | ---: | ---: |
| 8,192 | 1,152 MiB | — | — |
| 16,384 | 2,304 MiB | 1,152 MiB | about 576 MiB |
| 32,768 | 4,608 MiB | 3,456 MiB | about 1,728 MiB |
| 50,000 | 7,031 MiB | 5,879 MiB | about 2,940 MiB |

These are KV-cache estimates, not a promise of total process memory. Quantized
weights, CUDA graphs/work buffers, allocator fragmentation and parallel requests
are additional. The brain currently appears around 5 GiB resident at 8,192
tokens, so a 50,000-token f16 profile is roughly 10.7 GiB before transient
buffers; q8_0 KV is roughly 7.9 GiB before transient buffers. Loading STT and
OmniVoice at the same time would leave unsafe headroom on a 16 GiB card.

M08-S19 therefore keeps the runtime window at 8,192. A later benchmark may
promote 16K first with Flash Attention and q8_0 KV, while long-lived continuity
continues to use summaries and consented memory rather than replaying 50K raw
tokens. A short question can drive GPU compute utilization high, but it cannot
fill 50K of semantic history; configured context allocation and accumulated
tokens, not “thinking power”, dominate KV-cache VRAM.

Official references:

- [Ollama FAQ: Flash Attention and KV-cache
  quantization](https://docs.ollama.com/faq#how-can-i-enable-flash-attention)
- [Ollama API: running models and
  `size_vram`](https://github.com/ollama/ollama/blob/main/docs/api.md#list-running-models)
- [OmniVoice official repository](https://github.com/k2-fsa/OmniVoice)
- [OmniVoice generation parameters and long-form
  chunking](https://github.com/k2-fsa/OmniVoice/blob/master/docs/generation-parameters.md)

### OmniVoice research result

As of 2026-07-29, the official end-user checkpoint is still
`k2-fsa/OmniVoice`, 0.6B parameters. `k2-fsa/OmniVoice-Emilia` is also 0.6B,
trained only on the Chinese/English Emilia subsets, and its own model card
recommends the full checkpoint for superior regular use; it is not an upgrade
for Vietnamese. No official larger OmniVoice checkpoint was found.

The remaining swallowed/rushed words are therefore treated as a long-form
conditioning and Vietnamese normalization problem, not solved by swapping to a
non-existent larger official checkpoint. The official implementation already
documents automatic sentence chunking and stable reuse of a generated/reference
voice prompt. Future TTS work should A/B punctuation-aware Vietnamese chunks,
number/abbreviation normalization and a fixed high-quality reference prompt;
community Vietnamese fine-tunes require separate dataset, license and quality
provenance before they may replace the pinned checkpoint.

## Fast evidence M08-S19 (owner machine)

- Text-brain conversation tests: 21 pass, including consecutive screenshot
  isolation and internal-marker leakage.
- Perception worker tests: 38 pass after OCR retirement.
- Perception route tests: 11 pass after removal of the OCR header/status
  contract.
- Resource route tests: 5 pass with current/provider-peak/source assertions and
  no OCR model row.
- `pnpm test:fast`: pass — Safety 22, Text brain 49, Memory 11, Avatar 5,
  Speech 40, Perception 54 and Core Runtime 53 tests.
- `pnpm test:desktop`: production build + 54 tests pass; sampled peak is retained
  only in memory for the current desktop session.
- `pnpm smoke:dev-console`: loopback startup/health smoke pass.

## Implemented in M08-S20 (desktop recovery, voice gate and all-on VRAM)

- Electron resource `load`/`unload` calls now allow a 120-second cold-operation
  window and retry only a true loopback `E_DESKTOP_CONTROL_OFFLINE` condition
  with bounded 250/500/1,000/2,000/4,000 ms backoff. A timed-out POST is never
  replayed. Logs include the allowlisted model/action while keeping payloads and
  prompts out of the renderer console.
- The Ollama startup smoke checks `/api/ps` before probing and preserves a
  checkpoint that was already resident. Re-running `start:desktop` no longer
  evicts an owner-pinned Brain behind the scheduler's back.
- The chat page is a viewport-bounded grid. Its message list owns the vertical
  scroll and bottom padding, while the composer remains reachable without
  compressing or clipping the last assistant message.
- Ollama still runs the same `qwen3-vl:8b-thinking-q4_K_M` weights and 8,192
  context. The text brain now requests 32 of 36 text layers on GPU; four layers
  run from system RAM. Flash Attention, q8_0 KV cache, one parallel request and
  one loaded Ollama model remain the launcher defaults.
- Selective Thinking is now two bounded passes on that same checkpoint:
  256 private scratchpad tokens followed by a 128-token final-answer pass. The
  scratchpad never crosses the provider boundary into logs, memory, desktop or
  TTS.
- A Vietnamese TTS replacement was not promoted. VieNeu v2 Standard and the
  public `splendor1811/omnivoice-vietnamese` checkpoint both failed owner-
  reference reverse-STT quality. G-OmniVoice is the next credible candidate but
  its files require owner acceptance of gated Hugging Face terms before a real
  A/B can run. The measured current OmniVoice baseline remains the default.
- Detailed research and measurements are in
  `docs/research/M08-S20-vietnamese-tts-ollama-vram-2026-07-29.md`. The future
  owner-curated SFT/QLoRA plus preference-learning workflow is in
  `docs/architecture/hina-conversation-learning.md`.

## Fast evidence M08-S20 (owner machine)

- Brain, Faster-Whisper large-v3 and OmniVoice were forced resident together.
- Simple owner turn: 2.673 s, completed.
- Selectively reasoned owner turn: 5.789 s, completed.
- 100 ms NVIDIA sampling across both turns: 12,905 MiB physical peak, 3,091
  MiB minimum free, 99% maximum GPU utilization.
- Ollama `/api/ps`: brain resident about 4,735 MiB at 8,192 context.
- OmniVoice provider baseline: 1,946.3 MiB allocated; Faster-Whisper remains
  `null` per-model because CTranslate2 exposes no trustworthy model-only CUDA
  counter in the shared native worker.
- Text-brain provider/config tests: 21 pass. Desktop production build and 56
  security/contract tests pass; real Electron startup smoke reports runtime,
  local VRM, resource IPC and transparent widget ready.

## Implemented in M08-S21/S22 (adaptive budgets and Qwen3.5 4B Q8_0)

- The latest user message selects one immutable budget before provider I/O:
  routine viewer `0/96`, reflective viewer `192/128`, emotional/contextual
  `256/128`, game analysis `384/160`, and explicit critical multi-step game
  analysis `512/192` reasoning/output tokens.
- Every profile uses the same `qwen3.5:4b-q8_0` checkpoint. Private scratchpad
  text never crosses into emitted tokens, logs, memory, desktop or TTS.
- The Ollama distribution is pinned at manifest digest
  `8722f47c2791e6554c3244d2444b433c6241eed92d2093b53ef105626a6dcb36`;
  its 5,279,282,560-byte Q8_0 blob hashes to
  `acaad28d51b81c74cae813475866f274730f97e4e687464cdd0ac369ef20032c`.
- Runtime requests full GPU offload, active context 8,192, one parallel request,
  `keep_alive=0` unless owner-pinned, and a 6,144 MiB scheduler reservation.
  Screen image payloads still go only to the separate Cloud/light-local Vision
  provider.
- Narrow owner-GPU smoke reported 5,184,558,201 resident model bytes on GPU.
  Cold fast, emotional and game-analysis turns completed in 6.647, 4.533 and
  7.533 seconds. The former Qwen3-VL 8B tag and duplicate Qwen3.5 4B Q4 tag were
  removed only after this smoke passed.
- Refreshed all-on owner-GPU evidence kept Qwen3.5 Q8_0, Faster-Whisper and
  OmniVoice resident together. A real text turn completed in 5.313 seconds.
  A real TTS request returned its first chunk in 1.266 seconds and completed in
  2.584 seconds. Physical VRAM peaked at 13,990 MiB with 2,006 MiB minimum free
  and 91% peak GPU utilization. The fast resource gate passed; owner
  application/quality acceptance is still required before promotion.
