# Hina AI

Hina AI là dự án local-first xây dựng AI VTuber tiếng Việt theo kiến trúc
mô-đun. Hội thoại, speech, memory, avatar, perception, Minecraft và livestream
được tách bằng contract rõ ràng để có thể phát triển và rollback độc lập.

Trạng thái hiện tại: **M08 — perception đang mở với slice S1 chạy thật để
owner test; M07 avatar/desktop giữ trạng thái runnable candidate**. M01
runtime spine, M02 safety, M03 text brain, M04 speech input, M05 speech
output và M06 memory đã qua fast gate; M06 cũng đã qua independent review
không có P0/P1. Hina Dev Console hiện là dashboard nhiều
trang có chat text thật qua Ollama/OpenAI-compatible local, microphone/WAV tiếng
Việt qua Faster-Whisper large-v3 trên GPU ở desktop, giọng Việt qua VoxCPM2 2B
trên CUDA/BF16 và ký ức dài hạn
SQLite + Qdrant local. Trang Avatar Stage đọc turn state thật và suy ra khẩu hình
`A/I/U/E/O` từ chính phổ WAV TTS đang phát; không dùng câu trả lời, transcript,
audio, memory hay backend state giả.

## Chạy ứng dụng hiện có

Yêu cầu: Windows 11, Python 3.12–3.14, Node.js 22–24, `uv` và `pnpm`.

```powershell
pnpm install --frozen-lockfile
pnpm start:dev-console
```

Trình duyệt sẽ mở `http://127.0.0.1:8765/`. Đây là ứng dụng local chạy liên tục
cho tới khi bạn bấm `Ctrl+C`, không phải output dựng sẵn. Navbar chia chức năng
thành Tổng quan, Trò chuyện & giọng nói, Avatar Stage, Ký ức, Quan sát, An toàn
và Runtime & chẩn đoán.
Giao diện cho phép:

- kiểm tra health, version, config và metrics của runtime;
- kết nối WebSocket `hina.realtime.v1`;
- gửi durable event vào SQLite, thử dedupe và replay stream;
- round-trip binary frame opcode 2;
- chủ động tạo lỗi và đọc JSONL error log đã che secret.
- kiểm tra capability `allow | ask | deny`, rate/budget và revocation;
- bật/tắt emergency stop, mute và feature flags;
- đọc safety audit được nối hash SHA-256.
- sanitize input, tạo ContextBundle có evidence và thử moderation bốn bề mặt.
- xem provider/model/VRAM thật và chat với Hina qua local model;
- interrupt turn, replay hoặc clear short-term memory và xem correlation khi lỗi.
- thu microphone hoặc chọn WAV, chạy VAD và transcribe tiếng Việt thật;
- chép transcript vào ô chat khi owner bấm, không tự gửi vào LLM hay memory.
- nhập text để tạo/phát WAV tiếng Việt thật, dừng phát hoặc barge-in bằng mic;
- tùy chọn tự đọc câu trả lời chat sau khi toàn bộ output đã qua moderation.
- tạo memory candidate đã lọc, rồi tự tay duyệt hoặc từ chối;
- tìm, sửa, pin, export hoặc xóa ký ức với biên nhận sau khi SQLite và Qdrant
  đã đồng bộ.
- xem avatar code-native phản ứng theo `idle | listening | thinking | speaking |
  interrupted | error` từ runtime thật;
- xem miệng chuyển động theo viseme phổ âm thanh của WAV TTS thật, kiểm tra cue
  thủ công có nhãn `manual-preview`, mute hoặc emergency stop từ cùng safety backend.

Ứng dụng không có câu trả lời AI dựng sẵn. Nếu provider/model chưa sẵn sàng,
chat turn trả lỗi thật và ghi vào `var/logs/hina-runtime.jsonl`.

## Bật local model cho chat

Gateway mặc định dùng Ollama tại `127.0.0.1:11434` với model
[`qwen3.5:4b`](https://ollama.com/library/qwen3.5). Sau khi cài Ollama:

```powershell
ollama pull qwen3.5:4b
ollama serve
pnpm start:dev-console
```

`pnpm start:desktop` tự tìm Ollama ở PATH hoặc thư mục cài Windows, khởi động
server loopback ẩn nếu cần và kiểm tra model trước khi mở Electron. Nếu thiếu
model, launcher tự chạy `ollama pull qwen3.5:4b`; log provider nằm ở
`var/logs/ollama.*.log`. Qwen 3.5 mặc định tắt thinking nội bộ trên chat UI để
stream trả nội dung trong giới hạn token, tránh lỗi do reasoning chiếm hết
`num_predict`.

Nếu Ollama app đã chạy nền thì không cần chạy thêm `ollama serve`. Có thể đổi
provider/model trước khi start:

```powershell
$env:HINA_MODEL_PROVIDER = "openai_compatible"
$env:HINA_MODEL_BASE_URL = "http://127.0.0.1:1234/v1"
$env:HINA_MODEL_NAME = "ten-model-local"
$env:HINA_MODEL_API_KEY = "local-key-neu-provider-can"
pnpm start:dev-console
```

Gateway từ chối endpoint ngoài loopback và không trả API key qua status/log.

## Bật speech input tiếng Việt

M04 dùng mặc định `moonshine-voice==0.0.73` với Vietnamese Base trên CPU.
Lần đầu một đoạn có speech đi qua VAD, provider có thể tải model vào
`var/cache/models/moonshine`; cache này không nằm trong Git. Faster-Whisper
vẫn được giữ làm đường lui bằng `HINA_STT_PROVIDER=faster-whisper`.
Thư viện Moonshine là MIT nhưng weight tiếng Việt dùng Moonshine Community
License phi thương mại; candidate này chưa được phép promote cho mục đích
thương mại/public nếu chưa xử lý license riêng.

Riêng `pnpm start:desktop` dùng profile GPU-only:
`Systran/faster-whisper-large-v3` CUDA/float16, không fallback CPU. Vì vậy
widget và trang test Mic của desktop không dùng Moonshine CPU.

```powershell
pnpm start:dev-console
```

Trong Dev Console, bấm **Bắt đầu thu mic** hoặc chọn file `.wav`, sau đó bấm
**Transcribe tiếng Việt**. Raw audio chỉ nằm trong RAM và không được ghi vào
log/database. Để chạy offline nghiêm ngặt sau khi model đã được cache:

```powershell
$env:HINA_STT_ALLOW_DOWNLOAD = "false"
pnpm start:dev-console
```

## Bật speech output tiếng Việt

M05 desktop mặc định dùng VoxCPM2 2B tại revision đã pin. Backend chạy
CUDA/BF16, xuất WAV mono 48 kHz và condition profile `Hina Anime AI v1` từ
reference tổng hợp do owner tạo bằng ElevenLabs. Đây là zero-shot voice
conditioning, không phải fine-tune model weights; provenance và SHA-256 nằm trong
`assets/manifests/hina-anime-elevenlabs-voice.v1.json`.

F5-TTS Vietnamese ZaloPay vẫn được giữ làm provider thử nghiệm. Cả checkpoint
`model_960000.pt` được model card hướng dẫn và checkpoint `model_1290000.pt`
hiện tại đều không qua quality smoke với reference Hina: WAV sinh ra là
nonsense/noise và nhận dạng ngược không khớp câu nguồn. Vì vậy launcher không
chọn F5 theo mặc định.

VieNeu v3 Turbo vẫn là rollback provider. VoxCPM2 được chọn vì upstream công bố
hỗ trợ tiếng Việt, model 2B/48 kHz, zero-shot voice cloning và Apache-2.0 cho
code/weight. Hai real smoke ngắn/dài đều được Faster-Whisper large-v3 CUDA nhận
lại đúng câu nguồn. Đây vẫn là candidate chờ owner nghe A/B, không phải tuyên bố
chất lượng tương đương ElevenLabs.

Trong Dev Console, nhập nội dung ở panel **Hina nói tiếng Việt**, sau đó bấm
**Tạo và phát giọng thật**. Toàn bộ câu phải qua `pre_tts` moderation trước khi
model chạy. Nút **Dừng / barge-in** dừng audio ngay; bắt đầu thu mic cũng tự dừng
audio. Arbitrary voice cloning và lưu text/audio sinh ra đều bị tắt. Câu dài
được chia tối đa 180 ký tự, kiểm tra silence/NaN và retry bad-case theo từng
đoạn. VoxCPM2 không time-stretch hậu kỳ vì bước này từng làm hỏng một phần audio
câu dài.

Lần đầu có thể tải khoảng 5 GB artifact vào `var/cache/models/voxcpm2` và mất
khoảng 20–30 giây để load trên máy owner. Khi đã resident, smoke thật đo khoảng
3,5–5,3 giây/request. Có thể kiểm tra
provider thật và tạo WAV nghe thử trong thư mục ignored:

```powershell
pnpm smoke:m05-tts
```

Smoke CUDA hiện chỉ xác nhận luồng thật hoạt động, chưa phải quality/performance
promotion. Chạy offline nghiêm ngặt sau khi cache xong:

```powershell
$env:HINA_TTS_ALLOW_DOWNLOAD = "false"
pnpm start:dev-console
```

## Dùng ký ức dài hạn có consent

M06 lưu dữ liệu gốc trong SQLite và chỉ dùng Qdrant local làm chỉ mục tìm kiếm
có thể dựng lại. Mở navbar **Ký ức**, nhập nguồn, loại, chủ đề và nội dung rồi
bấm **Tạo đề xuất**. Hina chỉ được dùng dữ kiện sau khi owner bấm **Duyệt**.
Input có dấu hiệu prompt injection bị cách ly và raw text không được lưu.

Ký ức chỉ được truy hồi cho lượt chat `owner.console`, nằm trong một user-role
block có nhãn untrusted data và không thể sửa persona/system prompt. Public hoặc
viewer chat không được đọc owner memory. Nút **Xóa có biên nhận** chỉ báo thành
công sau khi SQLite và Qdrant đã đối soát; biên nhận không tuyên bố xóa dữ liệu
khỏi model weights đã train.

## Cho Hina quan sát màn hình theo yêu cầu

M08-S1 thêm trang **Quan sát**: owner bấm chụp, trình duyệt mở hộp thoại chọn
màn hình/cửa sổ (đây là consent cho từng lần chụp), một khung hình được thu
nhỏ và gửi PNG tới control plane loopback. Runtime chỉ giữ evidence trong RAM
— kích thước, SHA-256, perceptual hash và độ sáng — không lưu ảnh và chưa có
OCR/VLM; OCR provider mới ở trạng thái contract-ready cho tới khi dependency
qua review license. Mỗi quan sát có `trustLevel=untrusted` và TTL tối đa
15 giây theo monotonic clock; hết hạn là biến mất khỏi danh sách và không thể
được coi là ngữ cảnh hiện tại.

Capture mặc định tắt: cần bật cờ **Quan sát màn hình** ở trang An toàn trước,
và safety policy (`perception.observe`, decision `ask`) yêu cầu đúng hành động
xác nhận của owner cho từng snapshot; policy lỗi thì capture fail closed.
Quan sát ở slice này chỉ hiển thị cho owner — chưa được đưa vào chat context,
memory hay tool nào.

```powershell
pnpm test:perception
```

## Dùng Avatar Stage

Mở navbar **Avatar Stage** để xem state renderer-safe do control plane cung cấp.
Khi chat đang chạy, stage nhận trực tiếp state của turn FSM. Khi WAV TTS phát,
browser dùng Web Audio API để suy ra viseme `A/I/U/E/O` và cường độ từ tín hiệu
thật; backend nhận cue `speech.output` trong toàn bộ vòng đời speaking/idle.

Dev Console dùng SVG/CSS gốc của repository và được ghi provenance tại
`assets/manifests/hina-code-avatar.v1.json`. Classifier là heuristic phổ âm thanh,
không phải forced alignment hoặc căn phoneme chính xác và không lưu analyser/audio.

### Mở ứng dụng desktop

Chạy một lệnh duy nhất:

```powershell
pnpm start:desktop
```

Đây là ứng dụng Electron/Vue thật, không phải ảnh hoặc demo giả. Desktop đọc
avatar và safety state qua typed preload IPC; renderer không có Node, filesystem,
database, model hay quyền gọi network trực tiếp. Nếu control plane chưa chạy,
launcher tự mở service loopback ở nền và dừng service đó khi desktop đóng.
Nếu service tạm offline, renderer retry theo backoff tối đa 30 giây thay vì
gọi status mỗi 250 ms và spam lỗi.

Cửa sổ operator là dashboard gồm Tổng quan, Chat với Hina, Avatar Stage và
Runtime & Safety. Trang Chat gửi turn thật tới local LLM, hiển thị text trả lời
và có thể phát cùng câu trả lời bằng VoxCPM2 TTS; voice vẫn tuân theo global mute.

Desktop tải real VRM 1.0 bằng Three.js/`@pixiv/three-vrm`. Base hiện tại là
`VRM1_Constraint_Twist_Sample` chính thức của pixiv/VRM Consortium, được bundle
local với SHA-256 và embedded VRM Public License 1.0 đã kiểm tra. Profile
**Hina Kawaii · Pastel Sakura** khôi phục 20 texture nhúng, phối 13 material,
hạ tay khỏi T-pose, thêm blink/chuyển động state, nơ, má hồng và váy pastel bằng
code original của repository. Base VRM vẫn là model phát triển chứ chưa phải
artwork độc quyền/final do owner duyệt; UI ghi rõ ranh giới đó. Nếu VRM lỗi,
desktop tự giữ SVG fallback.
Các expression vowel của VRM đọc cùng viseme/intensity đã được backend kiểm tra,
không còn dùng khẩu hình giả cố định theo state `speaking`.
Shell operator được tải trước, còn chunk Three/VRM được lazy-load local sau để
JS khởi động giảm từ khoảng 814 KB xuống khoảng 78 KB. Thẻ **Hiệu năng renderer
thật** hiển thị FPS, frame-time p95/p99 và tỷ lệ drop ước tính theo cửa sổ hai
giây. Nếu WebGL/VRM lỗi, SVG vẫn hoạt động và nút **Thử tải lại VRM local** chỉ
remount fixed asset đã bundle; desktop cũng tự thử nối lại control plane sau
khi service restart.

Fast Electron smoke hiện đo khoảng 60 FPS, drop 0% trên cửa sổ 120+ frame, xác
nhận `hina-kawaii-v0.1`, 20 texture/13 material và đã
fault-inject WebGL context loss → SVG fallback → VRM reload thành công. Đây chỉ
là development sample ngắn; frozen OBS benchmark và soak voice/avatar tám giờ
vẫn được hoãn cho tới khi owner yêu cầu deep gate.

Khi chạy desktop, ngoài cửa sổ **Hina Avatar Stage** dành cho operator, app mở
thêm một **Hina Desktop Widget** trong suốt. Widget không có khung hoặc nền
chữ nhật, luôn nổi trên desktop và có thể kéo trực tiếp trên vùng avatar để
di chuyển sang vị trí khác. Khi không rê chuột (hoặc không focus bằng bàn
phím), widget không hiện control nào; khi hover/focus hiện panel **Voice** và
**Mic · Nói với Hina**. Voice bật/tắt tiếng đầu ra qua safety authority. Mic
chỉ thu tối đa 30 giây vào RAM, gửi WAV loopback qua typed preload IPC để
Faster-Whisper chép lời, gửi transcript vào chat thật và phát câu trả lời VoxCPM2
thật; không có wake-word hay ghi âm nền. Nhấn `Esc` để bỏ focus và ẩn panel.

Trong panel Operator, nhóm **Quản lý widget avatar** giải thích ba thao tác
**Ẩn widget / Hiện widget / Đặt lại vị trí**. Sau khi bạn kéo nhân vật sang
màn hình hoặc vị trí khác, desktop ghi lại chỉ hai tọa độ số cùng version schema
trong `userData`; khi đổi màn hình hoặc tháo màn hình cũ, vị trí được tự clamp
vào work area còn lại. Không có nội dung chat, audio hay memory nào được lưu ở
file này.

## Vòng lặp phát triển nhanh

```powershell
pnpm test:fast
pnpm test:safety
pnpm test:text-brain
pnpm test:speech
pnpm test:memory
pnpm test:avatar
pnpm test:perception
pnpm report:errors
```

Các lệnh `smoke:m01-s2` đến `smoke:m01-s6` là harness kiểm tra kỹ thuật, không
được coi là demo sản phẩm. Workflow repeat/soak/deep chỉ chạy khi owner yêu cầu.

## Tài liệu chính

- [Kế hoạch tổng thể](HINA_AI_MASTER_PLAN_VI.md)
- [Báo cáo nghiên cứu](deep-research-report.md)
- [Quy tắc vận hành](AGENTS.md)
- [Trạng thái M01](docs/modules/M01-contracts-spine.md)
- [Trạng thái M02](docs/modules/M02-safety.md)
- [Trạng thái M03](docs/modules/M03-text-brain.md)
- [Trạng thái M04](docs/modules/M04-speech-input.md)
- [Trạng thái M05](docs/modules/M05-speech-output.md)
- [Trạng thái M06](docs/modules/M06-long-term-memory.md)
- [Trạng thái M07](docs/modules/M07-avatar-stage.md)
- [Trạng thái M08](docs/modules/M08-perception.md)
- [Hướng dẫn Dev Console](apps/dev-console/README.md)

## Nguyên tắc an toàn

- Service cục bộ chỉ bind `127.0.0.1` nếu chưa có threat model mới.
- Không commit secret, audio riêng tư, transcript, model weight hoặc runtime cache.
- Không chạy shell, JavaScript hay Python do model sinh như production skill.
- Không tự động dùng public chat làm memory hoặc training data.
- Không promote model/adapter hay bật livestream công khai nếu chưa có owner duyệt.

## License

Source code mới của Hina AI dùng MIT License. Code, model, dataset, voice và
avatar bên thứ ba phải có license và provenance riêng.
