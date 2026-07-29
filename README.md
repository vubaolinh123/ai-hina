# Hina AI

Hina AI là dự án local-first xây dựng AI VTuber tiếng Việt theo kiến trúc
mô-đun. Hội thoại, speech, memory, avatar, perception, Minecraft và livestream
được tách bằng contract rõ ràng để có thể phát triển và rollback độc lập.

Trạng thái hiện tại: **M08 — perception đang mở, các slice S1–S6 có candidate
chạy thật để owner test; M07 avatar/desktop giữ trạng thái runnable candidate**. M01
runtime spine, M02 safety, M03 text brain, M04 speech input, M05 speech
output và M06 memory đã qua fast gate; M06 cũng đã qua independent review
không có P0/P1. Hina Dev Console hiện là dashboard nhiều
trang có chat text thật qua Ollama/OpenAI-compatible local, microphone/WAV tiếng
Việt qua Faster-Whisper large-v3 trên GPU ở desktop, giọng Việt qua OmniVoice
0.6B trên CUDA/FP16 và ký ức dài hạn
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
[`qwen3.5:4b-q8_0`](https://ollama.com/library/qwen3.5:4b-q8_0).
Đây là checkpoint Q8_0 duy nhất của **bộ não text**; Hina không nạp thêm model
khác cho fast chat hay thinking. Đọc ảnh màn hình được tách sang provider
vision cấu hình trong Dashboard desktop nên không buộc bộ não local phải đổi
vai trò hoặc reload. Sau khi cài Ollama:

```powershell
ollama pull qwen3.5:4b-q8_0
ollama serve
pnpm start:dev-console
```

`pnpm start:desktop` tự tìm Ollama ở PATH hoặc thư mục cài Windows, khởi động
server loopback ẩn nếu cần và kiểm tra model trước khi mở Electron. Nếu thiếu
model, launcher tự chạy `ollama pull qwen3.5:4b-q8_0`; log provider nằm ở
`var/logs/ollama.*.log`. Chat viewer, hội thoại cảm xúc và phân tích game dùng
các ngân sách reasoning/output khác nhau nhưng vẫn trên đúng checkpoint này.
Reasoning không được gửi ra UI. Admission tối đa 1 giây cộng inference
tối đa 9 giây tạo deadline mặc định 10 giây.

Persona `hina.prompt.v4` mặc định đi thẳng vào câu trả lời trong 1–2 câu,
thường không quá 45 từ. Hina là companion giao tiếp/cảm xúc, còn yêu cầu
code/tutorial được chuyển hướng ngắn trước provider. Trần output theo lượt nằm
trong khoảng 96–192 token; reasoning riêng chỉ được bật khi loại lượt cần nó.

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

M05 desktop mặc định dùng `omnivoice==0.2.1` với checkpoint
`k2-fsa/OmniVoice` 0.6B tại revision đã pin. Backend chạy CUDA/FP16, xuất WAV
mono 24 kHz và condition profile `Hina Anime AI v1` từ reference tổng hợp do
owner tạo bằng ElevenLabs. Đây là zero-shot voice conditioning, không phải
fine-tune model weights; provenance, transcript và SHA-256 nằm trong
`assets/manifests/hina-anime-elevenlabs-voice.v1.json`.

F5-TTS Vietnamese ZaloPay vẫn được giữ làm provider thử nghiệm. Cả checkpoint
`model_960000.pt` được model card hướng dẫn và checkpoint `model_1290000.pt`
hiện tại đều không qua quality smoke với reference Hina: WAV sinh ra là
nonsense/noise và nhận dạng ngược không khớp câu nguồn. Vì vậy launcher không
chọn F5 theo mặc định.

VieNeu v3 Turbo vẫn là rollback provider. OmniVoice được chọn vì upstream công
bố hỗ trợ 646 ngôn ngữ gồm tiếng Việt, zero-shot voice cloning và code
Apache-2.0. Checkpoint pretrained được model card ghi CC-BY-NC do ràng buộc dữ
liệu huấn luyện, nên candidate này chỉ dành cho owner test local phi thương mại
và chưa được production-promote. Real smoke ngắn/dài được Faster-Whisper
large-v3 CUDA nhận lại với similarity lần lượt 0,9733 và 0,9285. Đây vẫn là
candidate chờ owner nghe A/B, không phải tuyên bố chất lượng tương đương
ElevenLabs.

Trong Dev Console, nhập nội dung ở panel **Hina nói tiếng Việt**, sau đó bấm
**Tạo và phát giọng thật**. Toàn bộ câu phải qua `pre_tts` moderation trước khi
model chạy. Nút **Dừng / barge-in** dừng audio ngay; bắt đầu thu mic cũng tự dừng
audio. Arbitrary voice cloning và lưu text/audio sinh ra đều bị tắt. Câu dài
được chia tối đa 110 ký tự, ưu tiên ngắt ở dấu câu/dấu phẩy, kiểm tra
silence/NaN theo từng đoạn và tiếp tục được giới hạn theo độ dài audio bên
trong OmniVoice. Profile chất lượng dùng 32 diffusion steps; 16 steps nhanh hơn
nhưng từng làm rơi phần cuối câu dài. Tốc độ model được cap ở 1,02× và giữ cố
định trong cả lượt để tránh rush/nuốt chữ. Không time-stretch hậu kỳ.

Lần đầu tải khoảng 3,04 GiB artifact vào `var/cache/models/omnivoice`. Trên RTX
5070 Ti của owner, provider đo peak reserved khoảng 2270 MiB, scheduler giữ
reservation 3072 MiB, cold first-audio khoảng 6,0 giây và warm first-audio câu
ngắn khoảng 0,56 giây. Prompt giọng được tạo một lần và giữ trên CPU, optional
ASR của OmniVoice bị tắt, batch size là 1 và cache CUDA không dùng được giải
phóng sau mỗi request. Có thể kiểm tra provider thật và tạo WAV nghe thử trong
thư mục ignored:

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

M08 thêm trang **Quan sát** trong Dashboard desktop. Owner bấm đọc danh sách,
chọn một màn hình/cửa sổ từ preview rồi gửi đúng một khung hình đầy đủ.
Electron main giữ source ID thật sau grant 60 giây dùng một lần; renderer chỉ
nhận token. Ảnh giữ nguyên toàn bộ bố cục, không crop/che, nhưng cạnh dài được
hạ xuống 640/960/1.280 px (mặc định 960) để giảm payload, thời gian xử lý và
token ảnh. Evidence hiện tại chỉ sống tối đa 15 giây trong RAM.

Dev Console trên trình duyệt vẫn giữ hộp thoại `getDisplayMedia` làm đường kiểm
thử/fallback. Owner có thể chủ động bắt đầu một phiên lưu ảnh game có quota;
ảnh lịch sử được giữ để phân tích lại nhưng không bao giờ làm mới TTL, đi vào
memory hoặc tự kích hoạt công cụ.

Đọc ảnh không dùng checkpoint 8B của bộ não text. Trong Dashboard desktop:

1. Mở **Quan sát**, bật quyền quan sát, bấm **Đọc màn hình / cửa sổ hiện có**,
   chọn source và giữ preset 960 px nếu không cần chữ rất nhỏ.
2. Chọn OCR GPU hoặc model vision nếu cần, rồi bấm
   **Chụp toàn bộ nguồn đã chọn và gửi Hina**.
   Khi có kết quả, bấm **Hỏi Hina ngay về ảnh vừa chụp** để chuyển sang Chat và
   hỏi trong cùng phiên trước khi TTL 15 giây kết thúc.
3. Để cấu hình model vision, chọn `Ollama Cloud` hoặc `Ollama local`.
4. Với Cloud ở lần đầu, dán API key rồi bấm **Đọc danh sách model**. Dashboard
   chỉ liệt kê model khai báo capability vision; chọn model và bấm lưu.
5. Những lần mở sau, Dashboard báo **API key đã được lưu**, tự khôi phục model
   và mặc định bật phân tích vision. Để trống ô key để dùng lại; dán key mới và
   bấm **Ghi đè API key và giữ model này** để thay key mà không discovery hoặc
   chọn model lại.

Desktop lưu provider/model và ciphertext do Electron `safeStorage` mã hóa trong
`userData`; khóa rõ chỉ tồn tại trong Electron main và bộ nhớ runtime loopback.
Khóa tự được khôi phục sau restart và giữ nguyên cho tới khi owner thay hoặc
bấm **Xóa khóa đã lưu**. Renderer, status, log và Git không đọc được khóa đã
lưu. Ollama Cloud không chiếm VRAM model cục bộ nhưng ảnh được gửi tới provider
Cloud đã chọn; Ollama local giữ ảnh trên máy và Dashboard chỉ cho chọn model
vision nhẹ trong profile tối đa khoảng 5 GB/5B.

Kết quả capture luôn tách hai trạng thái: “runtime đã nhận snapshot evidence”
không đồng nghĩa model đã phân tích. Dashboard hiện summary khi vision/OCR
thành công; nếu chưa chọn phân tích hoặc provider lỗi, nó hiện đúng trạng thái,
mã lỗi và correlation ID thay vì chỉ báo chung “Hina đã nhận ảnh”. Với model
Ollama có thinking, screen analysis chủ động đặt `think=false` để giới hạn
256 token được dùng cho câu mô tả cuối, không phát hidden reasoning. Nếu
provider vẫn trả final rỗng hoặc báo đã hết output budget, Hina thử lại đúng
một lần với chỉ thị trả lời trực tiếp và ceiling 768 token; partial text bị cắt
không được hiển thị như kết quả hoàn chỉnh. Lỗi key, mạng, timeout hoặc protocol
không bị gửi lặp.

Capture mặc định tắt: nút bật/tắt quyền nằm ngay trên trang **Quan sát**, và
safety policy (`perception.observe`, decision `ask`) yêu cầu đúng hành động xác
nhận của owner cho từng snapshot; policy lỗi thì capture fail closed. Widget
không có quyền list/chụp source và không có capture tự động.
Trong đúng phiên `owner.console`, Hina có thể dùng tối đa một vision/OCR summary
của ảnh vừa chụp khi nó còn hạn. Summary được đặt trong user-role block có nhãn
untrusted; ảnh thô, hash, OCR box, key và provider payload không đi vào prompt.
Hina được yêu cầu nói “ảnh vừa chụp”, không giả vờ đang nhìn live. Sau TTL,
khác session hoặc khác lane, context bị loại 100%; nó không đi vào memory, tool
hay bộ điều khiển game.

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

Cửa sổ operator là dashboard gồm Tổng quan, Chat với Hina, Mic/STT/TTS, Quan
sát, Tài nguyên AI, Avatar Stage, Live2D và Runtime & Safety. Trang Chat gửi
turn thật tới local LLM, hiển thị text trả lời và có thể phát cùng câu trả lời
bằng OmniVoice TTS; voice vẫn tuân theo global mute.

Trang **Tài nguyên AI** cập nhật khoảng 1,5 giây một lần nhưng chỉ khi đang mở.
Nó hiển thị RAM/VRAM vật lý, tải/nhiệt độ/công suất GPU, RSS của core và
desktop, lease scheduler, model nào đang load/unload và timeline thay đổi trong
 RAM. Trần admission của Hina là 15,5 GiB VRAM; `nvidia-smi memory.free` đã
 loại phần Windows và ứng dụng GPU khác nên là giới hạn vật lý cứng, không bị
 trừ thêm một lần bởi scheduler. Page cảnh báo khi chạm trần hoặc VRAM trống
 thực tế quá thấp. “Reservation” là ngân sách scheduler dùng để cấp quyền chạy,
 không phải một phần VRAM phải cộng thêm lần nữa vào số đo vật lý. Model Cloud
 được ghi rõ là không giữ trọng số trong VRAM local.

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
Faster-Whisper chép lời, gửi transcript vào chat thật và phát câu trả lời
OmniVoice thật; không có wake-word hay ghi âm nền. Nhấn `Esc` để bỏ focus và ẩn
panel.

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
