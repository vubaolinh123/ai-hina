# M07-S14 — VoxCPM2 và vòng đời VRAM cho chat/TTS

Ngày đánh giá: 2026-07-27
Máy kiểm thử: Windows 11, RTX 5070 Ti 16 GB, CUDA/BF16.

## Quyết định

Chọn `openbmb/VoxCPM2` 2B làm TTS mặc định mới cho desktop owner-test:

- upstream công bố hỗ trợ tiếng Việt, zero-shot voice cloning và WAV 48 kHz;
- code/package và weight đều khai báo Apache-2.0;
- model khoảng 8 GB VRAM, chạy được bằng CUDA/BF16 trên RTX 5070 Ti;
- mẫu ngắn và dài bằng giọng Hina đều qua kiểm tra nhận dạng ngược tiếng Việt;
- F5-TTS ZaloPay tiếp tục bị loại vì sinh noise/nonsense;
- VieNeu v3 Turbo được giữ làm rollback, không còn là desktop default.

Đây là **runnable candidate**, chưa phải tuyên bố chất lượng tương đương
ElevenLabs. Owner vẫn cần nghe A/B để quyết định chất giọng.

## Vì sao xảy ra `E_RESOURCE_CAPACITY`

Ba allocation từng không khớp với sổ ResourceLease:

1. launcher warm-up VieNeu ngay khi khởi động, khiến khoảng 8–9 GB VRAM resident;
2. lease TTS đã hết nhưng weight/CUDA cache vẫn còn trong process;
3. Ollama giữ model chat sau khi stream hoàn tất.

Scheduler sau đó nhận một yêu cầu chat 4096 MiB trong khi phải giữ 2048 MiB
headroom, nên từ chối đúng bằng `E_RESOURCE_CAPACITY`.

M07-S14 sửa bằng một vòng đời thống nhất:

- TTS giữ đúng một lease dài hạn, priority 60, có callback unload khi bị
  workload priority cao hơn preempt;
- Faster-Whisper unload weight trước khi trả lease;
- Ollama nhận `keep_alive: 0`, nên model chat được dỡ sau stream;
- launcher không warm-up TTS lúc startup;
- mọi admission vẫn giữ nguyên tối thiểu 2048 MiB headroom.

Không hạ headroom và không chuyển sang CPU để che lỗi.

## Ổn định câu dài

VoxCPM2 nhận từng đoạn tối đa 180 ký tự. Mỗi đoạn phải:

- có sample hữu hạn, không im lặng và không quá ngắn;
- qua bad-case retry của provider tối đa ba lần;
- được ghép bằng khoảng nghỉ 120 ms và fade ngắn ở biên;
- fail toàn bộ lượt nếu một đoạn lỗi, không trả một WAV nửa đúng nửa hỏng.

Pipeline mới không còn dùng WSOLA để kéo nhanh audio diffusion. Đây là bước từng
làm một số đoạn của câu dài bị méo hoặc mất tiếng.

## Evidence thật trên máy owner

- Short WAV: 48 kHz mono, 4,32 giây; Faster-Whisper large-v3 CUDA nhận lại đúng
  toàn bộ câu, similarity `1.0`.
- Long WAV: 48 kHz mono, 19,28 giây, ba chunk; nhận dạng ngược đúng toàn bộ câu,
  similarity `1.0`.
- Cold process: khoảng 29,3 giây do tải model lần đầu.
- Khi model đã resident: khoảng 3,5–5,3 giây/request trong resource smoke.
- Chuỗi thật `TTS resident → Ollama chat → TTS` pass, chat `completed`, còn
  khoảng 7,4 GB VRAM free sau chat và headroom cấu hình vẫn là 2 GB.

## Candidate khác

| Model | Tiếng Việt | Quy mô / VRAM | License | Kết luận |
|---|---|---:|---|---|
| VoxCPM2 | Upstream liệt kê rõ | 2B / khoảng 8 GB | Apache-2.0 | Chọn cho owner-test |
| MOSS-TTS family | v1.5 có tiếng Việt | 1.7B realtime/local hoặc 8B v1.5 | Apache-2.0 code; cần audit từng weight | Candidate sau nếu Vox không đạt MOS |
| Chatterbox Multilingual | Danh sách chính thức không có `vi` | Nhẹ hơn | MIT | Không chọn cho tiếng Việt |
| Fish Audio S2 | Có đa ngôn ngữ | Khoảng 4B | Fish Audio Research License | Không chọn làm default |
| F5-TTS ZaloPay | Có | checkpoint khoảng 5,4 GB | MIT code / CC-BY-4.0 weight | Đã reject bằng real smoke |

## Nguồn chính

- VoxCPM repository: https://github.com/OpenBMB/VoxCPM
- VoxCPM2 model card: https://huggingface.co/openbmb/VoxCPM2
- MOSS-TTS repository: https://github.com/OpenMOSS/MOSS-TTS
- Chatterbox repository: https://github.com/resemble-ai/chatterbox
