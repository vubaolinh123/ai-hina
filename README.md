# Hina AI

Hina AI là dự án local-first xây dựng AI VTuber tiếng Việt theo kiến trúc
mô-đun. Hội thoại, speech, memory, avatar, perception, Minecraft và livestream
được tách bằng contract rõ ràng để có thể phát triển và rollback độc lập.

Trạng thái hiện tại: **M07 — avatar stage và desktop đang có vertical slice chạy thật để
owner test**. M01 runtime spine, M02 safety, M03 text brain, M04 speech input,
M05 speech output và M06 memory đã qua fast gate; M06 cũng đã qua independent
review không có P0/P1. Hina Dev Console hiện là dashboard nhiều
trang có chat text thật qua Ollama/OpenAI-compatible local, microphone/WAV tiếng
Việt qua faster-whisper, giọng Việt qua VieNeu-TTS ONNX int8 và ký ức dài hạn
SQLite + Qdrant local. Trang Avatar Stage đọc turn state thật và mở miệng theo
biên độ WAV TTS đang phát; không dùng câu trả lời, transcript, audio, memory hay
backend state giả.

## Chạy ứng dụng hiện có

Yêu cầu: Windows 11, Python 3.12–3.14, Node.js 22–24, `uv` và `pnpm`.

```powershell
pnpm install --frozen-lockfile
pnpm start:dev-console
```

Trình duyệt sẽ mở `http://127.0.0.1:8765/`. Đây là ứng dụng local chạy liên tục
cho tới khi bạn bấm `Ctrl+C`, không phải output dựng sẵn. Navbar chia chức năng
thành Tổng quan, Trò chuyện & giọng nói, Avatar Stage, Ký ức, An toàn và Runtime
& chẩn đoán.
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
- xem miệng chuyển động theo Web Audio amplitude của WAV TTS thật, kiểm tra cue
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

M04 dùng `faster-whisper==1.2.1` và model
`Systran/faster-whisper-small` tại revision đã pin. CPU `int8` là mặc định an
toàn trên Windows. Lần đầu một đoạn có speech đi qua VAD, provider có thể tải
model khoảng 484 MB vào `var/cache/models/faster-whisper`; cache này không nằm
trong Git.

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

M05 dùng `vieneu==3.2.3`, model
`pnnbao-ump/VieNeu-TTS-v3-Turbo` và codec
`OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX` tại các revision đã pin. Backend
mặc định chạy CPU ONNX `int8`, xuất WAV mono 48 kHz với preset `Trúc Ly`.

Trong Dev Console, nhập nội dung ở panel **Hina nói tiếng Việt**, sau đó bấm
**Tạo và phát giọng thật**. Toàn bộ câu phải qua `pre_tts` moderation trước khi
model chạy. Nút **Dừng / barge-in** dừng audio ngay; bắt đầu thu mic cũng tự dừng
audio. Voice cloning và lưu text/audio sinh ra đều bị tắt.

Lần đầu có thể tải model/codec vào `var/cache/models/vieneu`. Có thể kiểm tra
provider thật và tạo WAV nghe thử trong thư mục ignored:

```powershell
pnpm smoke:m05-tts
```

Smoke CPU hiện chỉ xác nhận luồng thật hoạt động, chưa phải quality/performance
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

## Dùng Avatar Stage

Mở navbar **Avatar Stage** để xem state renderer-safe do control plane cung cấp.
Khi chat đang chạy, stage nhận trực tiếp state của turn FSM. Khi WAV TTS phát,
browser đo biên độ audio thật bằng Web Audio API và điều khiển độ mở miệng; backend
nhận cue `speech.output` cho vòng đời speaking/idle.

Visual hiện tại là SVG/CSS gốc của repository và được ghi provenance tại
`assets/manifests/hina-code-avatar.v1.json`. UI luôn báo `VRM chưa tải`; đây
không phải VRM/Live2D và lip-sync hiện chưa nhận dạng nguyên âm. Three-vrm,
licensed avatar asset và performance/soak gate thuộc slice M07 kế tiếp.

### Mở ứng dụng desktop

Giữ Dev Console/control plane chạy ở terminal thứ nhất, rồi mở terminal thứ hai:

```powershell
pnpm start:desktop
```

Đây là ứng dụng Electron/Vue thật, không phải ảnh hoặc demo giả. Desktop đọc
avatar và safety state qua typed preload IPC; renderer không có Node, filesystem,
database, model hay quyền gọi network trực tiếp. Nếu control plane chưa chạy,
ứng dụng hiện lỗi offline và chỉ dẫn `pnpm start:dev-console`.

## Vòng lặp phát triển nhanh

```powershell
pnpm test:fast
pnpm test:safety
pnpm test:text-brain
pnpm test:speech
pnpm test:memory
pnpm test:avatar
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
