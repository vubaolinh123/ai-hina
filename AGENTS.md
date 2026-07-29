# Hina AI Agent Operating Rules

## Canonical plan

Đọc `HINA_AI_MASTER_PLAN_VI.md` trước khi thay đổi kiến trúc hoặc mở module mới. Chỉ một module sản phẩm được ở write phase tại một thời điểm.

Module active hiện tại: **M09 — Minecraft agent**. M08 đã dừng write phase ở
runnable candidate theo quyết định owner ngày 2026-07-29: tiếp tục dùng Vision
Cloud hiện tại và hoãn bộ chấm 20 ảnh đa dạng cho tới khi gặp lỗi thực tế. Đây
không phải tuyên bố rằng ngưỡng ≥85% đã được đo hoặc pass. M09 chỉ dùng
Mineflayer sau deterministic controller, typed allowlist, state verification và
emergency stop; LLM không được chạy generated code, `eval` hoặc shell. M01,
M02 và M03 đã qua fast unit/contract/startup gate. Runtime persona hiện dùng
`hina.prompt.v4`: mặc định 1–2 câu/≤45 từ, normal ceiling 3 câu/80 từ,
`max_tokens=192`, chỉ mở rộng cho chuyện/ngữ cảnh đời thường hoặc safety. Năm few-shot do owner cung cấp
đã được nhúng dưới dạng mẫu đã chỉnh để giữ sự thật, đồng cảm và roast hành
vi/bình luận thay vì công kích con người; trusted source map cố định
`creator_owner/known_user/viewer` và output mặc định sạch cho TTS. Ollama chat
dùng `temperature=0.7` + `repeat_penalty=1.15`: A/B thật cho thấy 0.85 có lúc
tràn 79 từ, còn profile 0.7 cho sáu tình huống live ở 9–34 từ, không
markdown/emoji. Future M11 style data không copy Neuro-sama transcript/dataset.
Hina là companion giao tiếp/cảm xúc: direct code/HTML/command/tutorial được
redirect trước provider, code-shaped output bị thay trước memory/TTS, còn trailing
meta disclaimer bị loại nhưng lời khuyên action an toàn vẫn giữ.
Repeat/soak/deep release verification được hoãn tới khi owner yêu cầu.
M04-S1/S2 đã qua fast gate,
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
M07-S1/S2/S3/S4/S5/S6/S7/S8/S9/S10 hiện là runnable candidate: avatar state/control plane, turn
callback, stage code-native, Web Audio spectral viseme từ TTS thật và Electron/Vue
operator shell sandboxed đã qua fast unit/contract/governance/startup/browser/
desktop IPC smoke gate. Browser đã xác nhận cue `speech.output` chuyển stage sang
`speaking` và mở miệng theo WAV thật; Electron smoke đã xác nhận renderer local
gọi control plane qua typed preload IPC và tải real VRM 1.0 development sample
qua `@pixiv/three-vrm`. Sample có embedded license/provenance nhưng không phải
thiết kế Hina cuối cùng. S6 đã lazy-load VRM, thêm telemetry frame thật, cap
60 FPS và fault-inject WebGL loss → SVG fallback → VRM recovery trong fast
Electron smoke. Frozen OBS benchmark, lip-sync p95 sâu, final Hina asset và soak
tám giờ vẫn deferred theo owner. S7 đã sửa CSP khiến texture nhúng từng bị trắng,
thêm profile `hina-kawaii-v0.1` với 20 texture/13 material pastel, pose tay hạ,
blink, nơ, má hồng, váy kín đáo và stage sticky; đây là prototype dùng base VRM
có license, chưa tuyên bố artwork độc quyền/final. M07-S8 thêm companion widget
Electron transparent/frameless/always-on-top, native drag surface và đúng một
Voice control chỉ lộ khi hover/focus; Operator window hiện hữu vẫn giữ nguyên.
M07-S9 thêm persistence `schemaVersion/x/y` đã validate/clamp trong userData và
Operator-only hide/show/reset controls; không lưu dữ liệu hội thoại/audio.
Real smoke xác nhận widget mode IPC, alpha PNG trong suốt, hover thật và
hide/show/reset qua Operator.
M07-S10 bổ sung dashboard desktop nhiều page, chat text thật kèm VieNeu WAV,
typed chat/TTS IPC, hover Voice rõ ràng, offline exponential backoff và launcher
`start:desktop` tự khởi control plane loopback. Theo yêu cầu owner, M04-S3 cũng
đổi STT mặc định sang Moonshine Vietnamese Base 0.0.73; Faster-Whisper vẫn là
rollback. Fast unit/contract/desktop smoke và real Moonshine CPU smoke đều xanh.
Moonshine Vietnamese weight có license phi thương mại nên vẫn chặn commercial
promotion cho tới khi được clearance riêng.
Chưa gọi independent reviewer trước khi module thực sự hoàn tất.
Ngày 2026-07-27 quality hotfix đã loại F5-TTS Vietnamese ZaloPay khỏi desktop
default: cả `model_960000.pt` và `model_1290000.pt` đều sinh nonsense/noise với
reference Hina và không qua round-trip STT. Desktop trở lại VieNeu-TTS v3 Turbo
CUDA/float16, dùng owner reference hash-bound; real smoke sinh WAV 48 kHz và
round-trip nhận lại đúng câu thử gần như nguyên văn. F5 chỉ còn experimental,
không được tự động chọn hoặc promotion.
Ngày 2026-07-27 M07-S14 thay desktop default bằng VoxCPM2 2B
CUDA/BF16 tại revision đã pin. Provider dùng đúng một reference Hina hash-bound,
chia câu dài 180 ký tự, retry/validate từng segment và không time-stretch hậu kỳ.
Short/long WAV 48 kHz đều qua Faster-Whisper large-v3 CUDA round-trip với
similarity 1.0. Lỗi `E_RESOURCE_CAPACITY` được đóng bằng scheduler lease TTS
priority thấp có unload khi preempt, STT unload trước release, Ollama
`keep_alive: 0` và tắt startup TTS warmup; real sequence TTS→chat→TTS pass trong
headroom 2048 MiB. Candidate vẫn chờ owner nghe A/B, chưa production-promote.
Ngày 2026-07-27 owner yêu cầu thay và xóa sạch VoxCPM2. M07-S15 đã chuyển
desktop default sang `k2-fsa/OmniVoice` 0.6B, package 0.2.1 và checkpoint
revision đã pin, CUDA/float16, SDPA, batch 1, optional ASR tắt và reference Hina
tám giây có transcript khớp + SHA-256. Profile chất lượng dùng 32 diffusion
steps, chunk tối đa 110 ký tự ưu tiên dấu câu và rate cố định 1.0× để không
rush câu dài. Trên RTX 5070 Ti, peak reserved đo
2270 MiB, scheduler reservation 3072 MiB, vòng 12 request không tăng allocated
VRAM; short/long reverse-STT similarity lần lượt 0.9733/0.9285. Code/cache/deps
VoxCPM2 đã nghỉ hưu; M07-S14 chỉ còn lịch sử audit. OmniVoice code Apache-2.0
nhưng pretrained weight CC-BY-NC, nên chỉ local non-commercial owner testing,
không commercial/public/production promotion.
Ngày 2026-07-27 M07-S15 quality maintenance đã chuẩn hóa emoji trang trí
(`🖊️` bị bỏ, `😂` thành cue `[chuckle]`), loại dấu ngoặc trang trí khỏi văn bản
đọc và tách phần aside thành chunk riêng với 160 ms pause. Câu hồi quy của owner
được sinh WAV OmniVoice CUDA/FP16 24 kHz không clipping; Faster-Whisper
large-v3 CUDA đọc lại similarity 0.9694. Speaking rate thực tế là 1.0×.
Ngày 2026-07-27 M07-S16 thêm adapter VTube Studio Public API tùy chọn qua
Electron main process, typed IPC và token cục bộ không lộ ra renderer; VRM
transparent vẫn là fallback. M07-S17 giữ compatibility branch cho runtime
VTube Studio cũ/khác có thể gửi đúng một text frame rỗng cho
`CurrentModelRequest`; client chỉ diễn giải trường hợp hẹp, đơn nhất đó thành
`modelLoaded=false`, JSON hỏng khác vẫn fail closed. M07-S18 đã thay Node
WebSocket built-in bằng `ws@8.21.1` (RFC-6455, MIT) sau A/B trên VTube Studio
1.35.10: transport cũ nhận frame rỗng dù model Hiyori đã tải, còn `ws` nhận
`CurrentModelResponse` JSON thật với `modelLoaded=true` và 3 hotkey. Unit/build
xanh và live loopback hiện xác nhận model thật; dashboard không còn báo sai
“chưa tải model” khi owner đã chọn model.
M07-S19 nối sender `VTubeStudioSpout` thật qua worker Spout2 tùy chọn chạy
loopback, giữ PNG mới nhất trong RAM và đưa frame Live2D vào widget; renderer
không đọc Spout trực tiếp. Widget fallback VRM khi worker lỗi, vẫn giữ native
drag và đúng ba control hover. Bridge đã qua build, 39 desktop unit tests,
real sender smoke và Electron smoke với Spout bật; frame hiện tại báo
`transparent=false` cho tới khi owner bật “Transparent in capture” trong tab
camera của VTube Studio. `liru` là alpha/BSD-2-Clause, chỉ dùng local testing
qua Python 3.13 isolated worker; chưa production-promote. Late-online smoke
khởi Hina trước rồi mới mở VTube Studio cũng tự reconnect từ 0×0 lên
720×405/ready, không cần restart Hina.
Ngày 2026-07-26 owner chỉ thị “Tiếp tục hoàn thành Plan” và chọn mở M08 —
Perception trong fast-development mode; M07 giữ trạng thái runnable candidate
với các deep gate (frozen OBS benchmark, lip-sync p95, final Hina asset, soak
8 giờ, independent review toàn module) tiếp tục deferred theo owner.
M08-S1 perception spine là runnable candidate: worker `hina_perception`
(PNG evidence không lưu pixel, dedup dHash, rate limit, FreshnessLedger TTL
≤15 s theo monotonic clock), route `/v1/perception/*` gate qua
`perception.observe` + feature flag `perception` (mặc định tắt, fail closed),
và trang Dev Console **Quan sát** với capture một lần qua hộp thoại
getDisplayMedia. Slice được viết trong cloud sandbox (Claude) theo Solo-first:
30 unit + 8 route tests xanh trên Python 3.11/3.13 sandbox. Ngày 2026-07-27,
Windows `pnpm test:fast` (bao gồm 30 perception tests và runtime route tests)
cùng `pnpm smoke:dev-console` đã pass; M08-S1 fast gate được coi là xanh.
M08-S2 sau đó tái sử dụng Qwen3.5-4B local làm VLM theo explicit capture,
scheduler lease và `keep_alive=0`; không lưu pixel/base64, chỉ giữ summary
untrusted trong TTL ≤15 giây. M08-S3 đã thêm RapidOCR 3.9.1 + PP-OCRv6 small
Torch GPU-only; corrected Vietnamese UI CER dài 6,944% chưa qua gate ≤5% nên
output vẫn untrusted/không được autonomous decision support.
Ngày 2026-07-28 owner chọn chỉ dùng một bản Thinking thay vì swap Instruct/
Thinking. M08-S4 chuyển default sang `qwen3-vl:8b-thinking-q4_K_M` pinned chỉ
cho text brain: simple text dùng same-weight preclosed-thought; câu text phức
tạp dùng hidden thinking bounded, context 8.192, budget 192/768, admission 1 s
+ provider 9 s, full GPU request, `keep_alive=0`, lease 8.192 MiB. Real RTX
5070 Ti smoke simple/complex lần lượt 2,939/6,160 s; peak total physical VRAM
tối đa 9.975/16.303 MiB.
Theo điều chỉnh tiếp theo của owner, explicit screen VLM không còn đi qua
text-brain 8B. Runtime dùng `OllamaVisionProvider` riêng: Ollama Cloud endpoint
cố định hoặc Ollama local capability-verified trong profile nhẹ ≤5 GB/≈5B.
Desktop có page Quan sát; Cloud key được Electron `safeStorage` mã hóa dưới
userData, tự restore sau restart, chỉ đổi/xóa qua owner IPC và không lộ qua
renderer/status/log/Git. Cloud vision thêm 0 model VRAM local; local vision dùng
lease 5.120 MiB + context 4.096 + `num_gpu=999` + `keep_alive=0`.
M08-S4 cũng thêm owner-started
PNG session archive mặc định tắt, quota 300 ảnh/256 MiB dưới
`var/perception-sessions`; dashboard hiện exact path và start/stop/reanalyze.
Ảnh lịch sử không làm mới TTL, luôn `currentObservation=false` và
`decisionSupportEligible=false`; stop/shutdown không tự xóa file vì owner sẽ
tự dọn sau phiên chơi.
M08-S5 resource observability là runnable candidate: control plane expose một
route read-only đã whitelist cho physical RAM/VRAM, scheduler reservation/lease
và trạng thái model; Ollama `/api/ps` phân biệt installed với resident.
Dashboard desktop có page **Tài nguyên AI**, poll 1,5 giây chỉ khi page đang mở,
giữ chart 60 mẫu và timeline load/unload 100 transition trong RAM. Electron
main bổ sung RSS desktop qua operator-only typed IPC; renderer không đọc
process/GPU/network trực tiếp. UI phân biệt physical allocation với admission
reservation, ghi Cloud vision dùng 0 local model VRAM và cảnh báo khi used vượt
14.336 MiB hoặc free dưới 2.048 MiB. NVIDIA field không hỗ trợ giữ `null`, không
giả thành 0. Fast unit/build và Electron startup/page smoke hiện xanh; live
post-smoke snapshot báo 2.199 MiB VRAM used, 13.797 MiB free và core RSS
563 MiB khi không có lease active. Đây không phải all-on benchmark; deep
all-on/soak vẫn deferred theo owner.
Ngày 2026-07-28 owner quyết định không crop/privacy-mask ảnh màn hình mà gửi
toàn bộ source đã chọn ở độ phân giải thấp hơn. M08-S6 là runnable candidate:
Electron main dùng `desktopCapturer`, giữ raw source ID sau opaque grant 60
giây/single-use và chỉ trả preview/token bounded cho operator renderer. Owner
chọn cạnh dài 640/960/1.280 px (mặc định 960), OCR/VLM opt-in rồi bấm gửi đúng
một lần; widget bị chặn và không có auto-capture/persistence. Fast desktop
build/typecheck + 52 tests xanh; Electron smoke thật tìm 9 source, không lộ ID
và gửi full-frame 640×360/144.619 byte tới runtime với `status=observed`.
Ngày 2026-07-29 M08-S7 đóng lỗi owner correlation
`c5b5b0d3-ba26-48b1-8c01-12770539ea47`: snapshot đã được nhận nhưng MiniMax M3
trả `E_PERCEPTION_VISION_EMPTY` vì token budget bị dùng cho thinking và desktop
không render nhánh vision error. Provider explicit screen analysis nay gửi
Ollama `think=false`; Dashboard tự chọn vision khi provider đã restore, phân
biệt evidence-only/success/error và hiện provider error + correlation ID. Key
Cloud/model mã hóa đã lưu được hydrate ngay không cần discovery/chọn lại; ô key
trống dùng key cũ, key mới chỉ ghi đè sau khi `/api/show` + configure thành
công. Real `minimax-m3` Cloud smoke trả summary Việt 140 ký tự,
`vision.state=ready`, không persist pixel; feature flag được trả về trạng thái
tắt sau smoke. Perception 50 tests và desktop 52 tests xanh.
Ngày 2026-07-29 M08-S8 đóng hai correlation
`64b371e7-80db-467d-ac6f-f59c8b6fbb2d` và
`215e4ffc-d15e-4c42-a8d7-80f20d4c28d1`: MiniMax M3 vẫn có thể trả final rỗng
hoặc bị cắt ở 256 token dù `think=false`. Provider nay chỉ retry đúng một lần
khi final rỗng hoặc `done_reason/eval_count` chứng minh hết budget, với prompt
trả lời trực tiếp và ceiling phục hồi 768 token. Partial bị cắt không được dùng;
hidden thinking không được đọc/log/trả về; lỗi auth/network/timeout/protocol
không retry. Real smoke ảnh UI 2.082×1.167 trả summary Việt hoàn chỉnh trong
16,703 giây, không persist pixel; 58 perception tests xanh.
Ngày 2026-07-29 M08-S9 nối một observation semantic vừa chụp vào đúng phiên
chat `owner.console` trong TTL tối đa 15 giây. Runtime chọn tối đa một observation
mới nhất bằng monotonic ledger, cùng session UUID; đưa nó vào bounded user-role
block untrusted và loại raw pixel/hash/box, ảnh lịch sử, session/lane khác,
memory cùng tool. Desktop capture dùng chính chat session và có nút hỏi ngay;
system prompt chỉ nói “ảnh vừa chụp”, không tuyên bố live view. Real
capture-to-chat 960×286 báo `includedFreshObservations=1`; sau 16 giây báo `0`,
không persist pixel. Text-brain 41, perception 59, core integration 9, desktop
53 tests và Dev Console smoke xanh. Launcher warm đúng checkpoint Thinking trên
GPU trong 2,76 giây rồi `keep_alive=0`, đóng cold first-turn timeout mà không
giữ model thứ hai. Prefix trước orphan `</think>` cũng bị loại trước
moderation/replay/TTS; explicit `<think>` vẫn fail closed.
Ngày 2026-07-29 M08-S10 thêm owner-only force load/unload trong trang **Tài
nguyên AI**. Control route chỉ nhận allowlist model, action `load|unload`,
`owner.desktop` và `ownerConfirmed=true`; scheduler/headroom vẫn là authority,
Cloud vision no-op thay vì giả có VRAM. Text brain có lease pin operator;
STT/TTS/OCR/local VLM chỉ unload sau active work, local VLM serialize
warmup/unload. VLM overview bounded 6–8 câu/3.500 ký tự. Hidden reasoning,
prompt/control token và inline suffix `--- **Phân tích hành vi:**` bị cắt
trước moderation/replay/TTS; desktop hiện thinking non-persistent. TTS chuẩn
hóa dash/dấu câu nhưng giữ OmniVoice natural 1.0x/110 ký tự. Fast gate xanh:
text 44, speech 22, perception 61, resource route 5, desktop 53/typecheck và
startup smoke qua launcher. Slice không tạo raw test artifact mới; legacy M07
smoke files trong `var/tmp` đã được audit nhưng còn chờ owner cleanup vì môi
trường chặn thao tác xóa đã xác minh. M08 vẫn active; không có deep/release
promotion.
Ngày 2026-07-29 M08-S12 thay runtime persona bằng `hina.prompt.v4`: Hina là
companion giao tiếp/cảm xúc, không phải technical tutor. Direct request cho
code/HTML/command/tutorial được redirect trước provider; output có hình dạng
code bị thay bằng redirect trước moderation, memory, desktop và TTS. Finalizer
chỉ cắt trailing meta disclaimer “Chú ý/Lưu ý: phản hồi giả định”, không bỏ lời
khuyên action an toàn. Context status/turn chỉ public window 8.192 token,
estimate UTF-8 byte và counters aggregate, không prompt/reasoning/raw history.
Desktop tách `DashboardNav`, `OverviewPage`, `ChatPage`; Chat tự follow message
trừ khi owner scroll away và composer sticky desktop. Mọi UI mới phải đi vào
page/component, không thêm markup vào legacy `App.vue` root; migration còn lại
Speech/Resources/Live2D/Avatar/Runtime làm theo bounded slice. Fast gate:
text 47, speech 40, perception 62, core 55, desktop typecheck/build+54.
Ngày 2026-07-29 M08-S13 chuyển toàn bộ trang **Quan sát** sang
`dashboard/pages/PerceptionPage.vue`. Component chỉ là typed presentation và
intent boundary: không import Electron/Node/network/storage/model runtime;
`App.vue` vẫn sở hữu Safety, session chat, opaque source grant, Vision key/IPC
và console error. Không thay capture explicit, grant 60 giây/single-use,
source-ID boundary, key `safeStorage`, pixel persistence hay TTL. Dashboard
migration còn lại chỉ gồm Speech/Resources/Live2D/Avatar/Runtime. Desktop
typecheck và build + 54 tests xanh, không chạy model/Cloud/capture thật.
Ngày 2026-07-29 M08-S14 chuyển toàn bộ trang **Tài nguyên AI** sang
`dashboard/pages/ResourcesPage.vue`. Component chỉ nhận telemetry/residency/
lease/timeline bounded và phát refresh hoặc `{ model, action }` intent, không
import Electron/Node/network/storage/runtime. `App.vue` vẫn sở hữu poll 1,5
giây, sample history, resource analysis, typed resource IPC và scheduler/error
boundary. Không đổi VRAM limits, Cloud no-op, null telemetry hoặc allowlisted
Force load/unload. Migration legacy còn lại: Speech/Live2D/Avatar/Runtime.
Desktop typecheck/build + 54 tests xanh, không chạy model hay benchmark all-on.
Ngày 2026-07-29 M08-S15 chuyển toàn bộ trang **Mic / STT / TTS** sang
`dashboard/pages/SpeechPage.vue`. Component chỉ là presentation/intent, không
import Electron/Node/MediaDevices/network/storage/runtime. `App.vue` vẫn sở hữu
mic stream, WAV, realtime throttle, audio URL lifecycle, typed speech IPC và
error log. Không đổi provider/GPU/permission/audio bound/persistence hoặc
auto-listen; nhãn TTS nay đúng OmniVoice. Migration legacy còn lại: Live2D và
Avatar/Runtime. Desktop typecheck/build + 54 tests xanh, không chạy mic/TTS thật.
Ngày 2026-07-29 M08-S16 chuyển toàn bộ trang **Live2D / VTube Studio** sang
`dashboard/pages/Live2DPage.vue`. Component chỉ nhận status bounded và phát
fixed intent, không import Electron/Node/WebSocket/network/storage/bridge.
`App.vue`/Electron main vẫn sở hữu token, `ws`, typed IPC, hotkey/movement
allowlist, Spout polling và error log. Không đổi endpoint/auth, sender
allowlist/loopback, transparent guidance hay VRM fallback. Migration legacy còn
lại: Avatar/Runtime. Desktop typecheck/build + 54 tests xanh, không mở VTS thật.
Ngày 2026-07-29 M08-S17 chuyển toàn bộ trang **Avatar Stage** và **Runtime &
Safety** sang `dashboard/pages/AvatarPage.vue` và `RuntimePage.vue`. Hai page
chỉ là presentation/typed-intent: không import Electron/Node/network/storage/
model runtime. `App.vue` vẫn sole owner VRM lazy-load/recovery, stage event,
avatar/widget/Safety IPC, polling, widget persistence/drag lifecycle,
retry/backoff và error log. Không đổi renderer, fallback, widget visibility,
mute/emergency semantics hay control-plane. Migration dashboard page hiện tại đã
hoàn tất; UI mới phải vào component/page thay vì thêm markup lớn vào `App.vue`.
Desktop typecheck/build + 54 tests xanh, không chạy desktop/model/VTS/Spout/mic/
TTS/Cloud thật.
Ngày 2026-07-29 M08-S11 hotfix capture/runtime capacity: owner phê duyệt trần
admission Hina **15.872 MiB (15,5 GiB)**. `nvidia-smi memory.free` đã phản ánh
VRAM Windows/compositor/app khác, vì vậy scheduler không trừ thêm 2.048 MiB;
free thực tế vẫn là hard cap vật lý. Brain Force load dùng cold-load deadline
45 giây và một-token `think=false` thay vì health probe 3 giây. Faster-Whisper
large-v3 CUDA nay hỗ trợ Force load/unload thật bằng scheduler lease pin cho
tới unload/preemption, không CPU fallback. Vision chấp nhận final có dấu câu
hoàn chỉnh dù provider gắn `length`; final chưa hoàn chỉnh chỉ recovery một lần
với budget ngắn hơn. Capture UI hiện báo ba pha capture/encode/analyze cùng
milliseconds từng chặng, không lộ source ID/pixel/key. Fast tests xanh: text
46, speech 40, perception 62, desktop build+53/typecheck; không chạy real
Cloud/native warmup hoặc all-on benchmark khi desktop owner đang hoạt động.
Ngày 2026-07-29 M08-S18 chuyển Avatar/Widget/Runtime state machine khỏi
`App.vue` sang trusted renderer composable `use-avatar-runtime.ts`; pages giữ
presentation/typed intent, không đổi VRM/widget/Safety semantics. Desktop
typecheck/build + 54 tests xanh.
Ngày 2026-07-29 M08-S19 khóa lỗi hai ảnh liên tiếp: turn có ảnh mới loại các
turn cũ từng dùng fresh observation khỏi replay; finalizer chặn delimiter và
English control narration trước memory/desktop/TTS. Local RapidOCR/PP-OCRv6 đã
nghỉ hưu khỏi runtime/contract/UI/dependency/manifest/provenance; screen
understanding chỉ dùng explicit Cloud/local Vision. Resource telemetry tách
current/provider peak/dashboard sampled peak kèm measurement source; unknown
không giả thành reservation. Runtime giữ context 8.192 token; 50K chỉ là
research estimate vì KV f16 thêm khoảng 5.879 MiB (q8_0 khoảng 2.940 MiB) chưa
tính buffer và không vừa all-on budget an toàn hiện tại. GitNexus `ai-hina`
được dùng để query/context/impact trước edit và `detect_changes` trước commit;
generated `.gitnexus` index không phải source artifact.
Ngày 2026-07-29 M08-S20 sửa resource-control desktop: cold load/unload có timeout
120 giây, chỉ retry `E_DESKTOP_CONTROL_OFFLINE` theo backoff bounded và không
replay POST đã timeout; startup probe bảo toàn model đã resident trong `/api/ps`
thay vì unload Brain owner-pinned; chat page dùng inner scroll với composer luôn
reachable.
Text brain giữ `qwen3-vl:8b-thinking-q4_K_M` Q4_K_M/context 8.192 nhưng chuyển
4/36 text layer sang RAM (`num_gpu=32`). Selective Thinking chạy private
scratchpad 256 token rồi final 128 token trên cùng checkpoint; reasoning không
được log/memory/UI/TTS. Real all-on Brain + Faster-Whisper + OmniVoice đạt peak
12.905 MiB, free tối thiểu 3.091 MiB; simple/complex turn hoàn tất 2,673/5,789
giây. TTS gate không promote model mới: VieNeu v2 và public Vietnamese OmniVoice
fine-tune fail reverse-STT owner reference; G-OmniVoice cần owner accept gated
Hugging Face terms. OmniVoice hiện tại vẫn là default có evidence tốt nhất.
Future style learning phải theo owner-curated offline QLoRA SFT + preference
pairs trong `docs/architecture/hina-conversation-learning.md`, không online
self-training từ live/public chat. Fast gate M08-S20: text-brain 21 test,
desktop production build + 56 test và Electron startup smoke xanh.
Ngày 2026-07-29 M08-S21 thêm adaptive conversation budget trên đúng một
checkpoint: viewer thường 0–192 reasoning/96–128 output, cảm xúc/ngữ cảnh
256/128, game 384–512/160–192; chỉ latest user message chọn profile và hidden
reasoning không vào log/memory/UI/TTS.
Ngày 2026-07-29 owner duyệt M08-S22: text brain mặc định chuyển sang pinned
`qwen3.5:4b-q8_0` Q8_0, Ollama digest
`8722f47c2791e6554c3244d2444b433c6241eed92d2093b53ef105626a6dcb36`.
Runtime giữ context 8.192, full-GPU request (`num_gpu=999`), reservation
6.144 MiB, một checkpoint và deadline 10 giây; explicit screen Vision vẫn tách
Cloud/light-local. Narrow smoke đo 5.184.558.201 resident bytes trên GPU và
cold fast/emotional/game 6,647/4,533/7,533 giây. Cache Qwen3-VL 8B cùng bản
Qwen3.5 4B Q4 dư thừa đã bị xóa sau smoke. Refreshed all-on Brain +
Faster-Whisper + OmniVoice đạt peak physical 13.990 MiB, minimum free
2.006 MiB và peak GPU utilization 91%; text turn thật hoàn tất 5,313 giây,
TTS first chunk 1,266 giây/request 2,584 giây. Fast resource gate xanh nhưng
vẫn chờ owner application/quality acceptance trước promotion.
Ngày 2026-07-29 M08-S23 thêm fail-closed Vision confidence/abstention:
`summary-heuristic.v1` chấm điểm deterministic trên final summary với threshold
0,60, luôn ghi rõ chưa hiệu chuẩn và không được coi là xác suất đúng semantic.
Model tự báo không đủ dữ kiện, summary quá ngắn hoặc dưới threshold chuyển
`state=abstained`; text chỉ hiện để owner tham khảo và không vào fresh chat
context, memory, TTS hay decision support. Dashboard phân biệt ready/abstained/
error, tắt nút hỏi ảnh cho abstained và đã dọn các nhánh OCR desktop còn sót.
Fast gate: perception 55 test, core perception route 11 test, desktop typecheck
+ production build/56 test xanh; chưa claim ≥85% scene QA hay calibration.
Ngày 2026-07-29 M08-S24 thêm owner Vision scene-QA thật trên Dashboard:
observation `ready|abstained` có thể được owner chấm Đúng/Thiếu/Sai qua typed
IPC và route fixed loopback yêu cầu `owner.desktop` + `ownerConfirmed=true`.
Ledger giữ tối đa 100 record trong RAM, chỉ gồm UUID, provider/model, state,
confidence chưa hiệu chuẩn và categorical rating; không giữ pixel, summary,
prompt, label, chat, key hay correction. Chấm lại thay nhãn cũ, không tăng mẫu.
Điểm phiên theo profile dùng Đúng=1/Thiếu=0,5/Sai=0; cần tối thiểu 20 ảnh thật
và ≥85% mới hiện candidate, nhưng `promotionApproved=false` cho tới khi owner
duyệt độ đa dạng và calibration. Fast gate: perception 60, route 13,
`pnpm test:fast` 246, desktop typecheck + production build/57 test xanh; không
chạy model/Cloud/capture thật và không tạo raw test artifact.
Ngày 2026-07-29 M08-S25 bổ sung calibration diagnostics trên cùng ledger:
theo profile hiện tại, status có ready/abstained count, abstention rate, mean
confidence, mean observed owner score, mean absolute error, Brier score và năm
reliability bin cố định. Mapping truth công khai Đúng=1/Thiếu=0,5/Sai=0; record
chưa chấm không vào calibration math, chấm lại cập nhật tại chỗ. Empty giữ
`null`, không giả 0; không trả UUID/per-sample data. Dashboard ghi rõ
`diagnosticOnly=true`, `calibrated=false`; đủ 20 mẫu cũng không tự đổi threshold
0,60 hay promotion. Fast gate: perception 62, `pnpm test:fast` 248, desktop
typecheck + production build/57 test xanh; không model/Cloud/capture/artifact.
Ngày 2026-07-29 M08-S26 thêm reset phiên owner Vision scene-QA theo đúng
provider/model đang active. Renderer chỉ có typed IPC không tham số; Electron
main bắt buộc operator và tự gắn `owner.desktop` + `ownerConfirmed=true`; route
loopback kiểm tra exact field/type. Reset chỉ xóa rated/unrated record trong RAM
của profile hiện tại, giữ profile khác, provider/model, archive, threshold và
`promotionApproved=false`; response chỉ có aggregate + số mẫu đã xóa. Dashboard
hỏi xác nhận, disable khi profile trống và xóa last renderer result sau success
để observation cũ không bị chấm lại. Fast gate: perception 64, route 14,
`pnpm test:fast` 251, desktop typecheck + production build/57 test xanh; không
model/Cloud/capture/artifact. Gate ≥85% vẫn chờ owner chấm ít nhất 20 ảnh thật
đa dạng và duyệt lỗi quan sát.
Ngày 2026-07-29 M08-S27 đóng deterministic stale/historical replay gate:
test tạo một owner archive tạm, ghi một PNG, stop archive và clear live ledger
trước khi reanalyze cùng snapshot 200 lần qua service boundary. Kết quả 0/200
false current claim: mọi response đều `historical=true`,
`currentObservation=false`, `decisionSupportEligible=false`; observations và
fresh owner chat context luôn rỗng. Exact TTL T−ε/T/T+ε vẫn xanh. Perception 65,
`pnpm test:fast` 252; không đổi production code, không model/Cloud/capture thật
và TemporaryDirectory không giữ artifact. Scene-QA ≥85% vẫn chờ owner.
Ngày 2026-07-29 M08-S28 đóng test-matrix prompt injection hiển thị trên màn
hình. Vision summary vẫn là đúng một `user` message untrusted có boundary cố
định; marker giả role/control phổ biến của ChatML, Llama, XML và bracketed
roles được render inert nhưng text cảnh tiếng Việt vẫn đọc được. Ma trận 28
case Anh/Việt chứng minh payload không vào system prompt/replay, không tạo role
mới, không đóng boundary thật và `toolExecution=false`. Text-brain 54 tests
xanh, `pnpm test:fast` 253; không model/Cloud/capture/dependency/VRAM/artifact.
Gate scene-QA ≥85% vẫn chờ owner.
Ngày 2026-07-29 M08-S29 đóng failure path dropped frame/capture worker. Sau khi
consume grant hợp lệ, Electron clear observation ledger qua fixed loopback route
trước khi gọi OS lấy frame mới. Source biến mất, thumbnail rỗng, encode lỗi hoặc
downstream worker offline vì vậy không thể để ảnh trước tiếp tục thành fresh
chat context; clear fail thì abort trước OS capture. Operation chỉ ở main
process, không lộ preload/renderer. Desktop typecheck/build + 58 tests và
`pnpm test:fast` 253 xanh; không real capture/model/Cloud/VRAM/artifact.
Scene-QA ≥85% vẫn chờ owner.
Ngày 2026-07-29 M08-S30 đóng deterministic VLM burst/resource-pressure gate.
Local Ollama Vision vẫn serialize admission/inference/recovery/release; burst 32
request có peak active `/api/chat` bằng 1 và mỗi transient lease release đúng
một lần. `E_RESOURCE_CAPACITY` hoặc `E_RESOURCE_LEASE_EXPIRED` được map thành
retryable `E_PERCEPTION_VISION_CAPACITY` trước model call, không CPU fallback.
Perception 68 và `pnpm test:fast` 256 xanh; không real model/Cloud/capture/GPU/
artifact. Scene-QA ≥85% vẫn là gate owner cần chấm.
Ngày 2026-07-29 M08-S31 làm gate scene-diversity đo được trên Dashboard. Mỗi
rating cần 1–3 fixed scene tag; tag rỗng/trùng/lạ/quá ba fail closed. Ledger
chỉ giữ metadata bounded trong RAM và trả aggregate counts. Một nhóm được phủ
khi có ≥2 ảnh; `candidateTargetMet` cần đồng thời ≥20 ảnh, score ≥85% và ≥4
nhóm được phủ, còn `promotionApproved=false`. Perception 69, route 14, Desktop
build/58 + typecheck và `pnpm test:fast` 257 xanh; không model/Cloud/capture/
GPU/artifact. Owner vẫn phải chấm và duyệt phiên ảnh thật trước M08 promotion.
Ngày 2026-07-29 owner quyết định tiếp tục dùng Vision Cloud hiện tại và hoãn
phiên chấm 20 ảnh cho tới khi gặp lỗi thực tế. M08 vì vậy dừng write phase ở
runnable candidate; quyết định chuyển sang M09 không được ghi thành quality
pass ≥85%. M09-S1 đã mở connection spine thật bằng pinned
`mineflayer@4.37.1`: chỉ offline auth tới loopback/RFC1918/private IPv6, vendor
types không qua public boundary, snapshot player/inventory/entity bounded,
status chỉ đọc trên `127.0.0.1`, `Ctrl+C` gọi emergency stop latched/idempotent.
Không có LLM, generated code, `eval`, shell, chat/sign/book payload, pathfinder
hoặc destructive action. Build + 13 adapter tests và `pnpm test:fast` 270 xanh;
audit không còn finding trên dependency path Minecraft sau override `uuid`
11.1.1. Real resettable-server smoke vẫn chờ owner nên S1 chỉ là local runnable
candidate, không production promotion.
M09-S2 thêm fixed typed skill registry với đúng `look.v1` non-destructive. Skill
chỉ chạy khi online/not-emergency/player-present/no-concurrent-skill, budget một
attempt, timeout 2 giây và postcondition yaw/pitch tolerance 0,05 radian.
Mineflayer promise resolve không được coi là success nếu normalized state
verifier không đồng ý. Timeout/vendor error/busy/precondition mismatch/
postcondition mismatch/emergency cancellation có stable failure và không retry;
e-stop abort active skill trước clear controls/disconnect. Không có mutating
HTTP, pathfinder/movement, LLM/generated code hoặc destructive action.
Minecraft 22 tests và `pnpm test:fast` 279 xanh; real resettable-server smoke
vẫn chờ owner.
Future M11 dùng post-trained Hugging Face `Qwen/Qwen3.5-4B` frozen làm QLoRA
SFT base, sau đó DPO/ORPO từ dữ liệu owner-curated. Không train trực tiếp GGUF,
không mặc định bắt đầu từ raw Base và Qwen3.5-9B chỉ benchmark/fallback thủ công,
không làm teacher/label source. Proactive streamer behavior phải do bounded
event-driven initiative planner (`extended_silence`, `recap_due`, `topic_decay`,
interruption...) phối hợp memory/policy; không chỉ do system prompt ép chủ động.

Legacy AIRI skill paths dưới `D:\ProjectAiri` mặc định ánh xạ sang repository
hiện tại `D:\ProjectHinaAI`, trừ khi owner chỉ định workspace khác.

M09-S3 thêm disconnected control service tự khởi cùng Desktop trên
`127.0.0.1:8766`. Launcher tạo secret CSPRNG 32 byte theo phiên, chỉ truyền qua
child environment và thu hồi khi đóng; Electron main giữ secret/network, widget
bị chặn và renderer chỉ có typed owner IPC. Connect/disconnect/`look.v1`/
emergency-stop dùng Bearer + `owner.desktop`, exact schema, body ≤8.192 byte và
không replay POST. Dashboard có page Minecraft giải thích/hiển thị world state
thật. Disconnect cho reconnect; e-stop latch tới restart. Minecraft 26 tests,
Desktop build/64 tests và fast suite 283 tests xanh; chưa có real resettable
server smoke nên chưa promotion.
M09-S4 thêm đúng một skill `move.step.v1`: cardinal direction, 0,25–2 block,
on-ground precondition, một attempt, timeout 4 giây, 20 stagnant physics tick
thì blocked và luôn clear controls trong `finally`. Success chỉ khi normalized
displacement đạt ≥75% target, overshoot ≤0,75 block và lateral drift ≤0,35
block. Không retry, pathfinder, jump/sprint, combat, phá block hay model/viewer
execution. Route vẫn owner-only qua ephemeral-secret IPC. Minecraft 34 tests,
Desktop build/65 tests và fast suite 291 tests xanh; real resettable-server
acceptance vẫn pending.
M09-S5 không thêm skill mới: Mineflayer port chỉ xuất bounded physics tick
sequence/age, và `look.v1`/`move.step.v1` fail trước action nếu chưa có tick
hoặc tick cũ quá 1.000 ms. Movement result có tick count, stagnant count và
maximum forward progress cho success/failure; blocked vẫn một attempt, không
retry/pathfinding và luôn clear controls. Dashboard hiện state fresh/stale/
unavailable và khóa action khi chưa fresh. Minecraft 38 tests, Desktop build/65
tests và fast suite 295 tests xanh; Vision/model/VRAM không đổi, real resettable
server acceptance vẫn pending.
M09-S6 thêm `move.to.v1` owner-only theo quyết định tiếp tục phát triển và owner
sẽ manual-test sau. Skill chỉ nhận absolute X/Z hữu hạn, yêu cầu target cách
current player 0,25–2 block cùng fresh physics/on-ground state, quay một lần rồi
giữ đúng `forward` trong bounded loop dùng chung với `move.step.v1`. Một attempt,
timeout 4 giây, 20 stagnant tick thì blocked, không retry/pathfinding và luôn
clear controls. Success cần ≥75% target-axis progress, overshoot ≤0,75 block,
lateral drift ≤0,35 block; evidence có khoảng cách còn lại. Desktop dùng fixed
owner-only route/IPC và khóa nút ngoài khoảng cách; widget/model/viewer/game
text không có authority. Minecraft 46 tests, Desktop build/66 tests và fast
suite 303 tests xanh; chưa chạy resettable server thật nên chưa promotion.
M09-S6A sửa blocker startup do Windows PowerShell 5.1 không hỗ trợ static
`RandomNumberGenerator.Fill`. Secret Minecraft mỗi phiên vẫn là 32 byte CSPRNG,
URL-safe Base64 không padding và chỉ đi qua child environment, nhưng launcher
dùng `RandomNumberGenerator.Create().GetBytes(...)` tương thích .NET Framework
và dispose generator trong `finally`. Regression test thực thi đúng helper bằng
`powershell.exe`, kiểm decoded length mà không log secret. Desktop build/67 tests
và same-launcher Electron smoke xanh.

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

## Artifact hygiene (owner policy, 2026-07-28)

- Sau mỗi test/smoke/benchmark, primary phải xóa cache model thử nghiệm, ảnh/audio
  sinh tạm, script one-off, fixture, debug dump và generated artifact mà không
  còn là runtime source, unit test bảo vệ hành vi, tài liệu/provenance bắt buộc
  hoặc evidence release được owner yêu cầu.
- Không giữ “just in case” code hay file demo sau khi đã lấy số đo. Lưu lại kết
  luận và metric gọn trong module doc/manifest; không lưu raw input, screenshot,
  OCR text hay log khổng lồ chỉ để chứng minh benchmark.
- Trước khi dọn, phân biệt agent-created artifact với dữ liệu/model/voice/avatar
  do owner cung cấp; không xóa tài sản owner hoặc thay đổi user-owned files.
  `.gitignore` không thay thế cho việc dọn dẹp thực tế.
- Nếu platform chặn thao tác xóa đã được kiểm tra scope, ghi rõ target còn lại và
  lý do trong handoff; không cố lách cơ chế an toàn bằng shell khác.

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
- Owner override 2026-07-29: trần admission Hina là 15.872 MiB; `memory.free`
  NVIDIA là hard cap đã phản ánh Windows/app GPU khác, không trừ headroom cố
  định lần thứ hai.

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

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **ai-hina** (5768 symbols, 11044 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "module/M00-governance"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/ai-hina/context` | Codebase overview, check index freshness |
| `gitnexus://repo/ai-hina/clusters` | All functional areas |
| `gitnexus://repo/ai-hina/processes` | All execution flows |
| `gitnexus://repo/ai-hina/process/{name}` | Step-by-step execution trace |

## Codex skills

Use the installed `gitnexus:*` Codex skills for exploring, impact analysis,
debugging, refactoring, review and CLI index maintenance. Query/context should
replace broad repository rereads; impact must precede symbol edits and
`detect_changes` must precede each commit. Generated `.gitnexus` indexes and
tool-specific skill caches are not product source artifacts.

<!-- gitnexus:end -->
