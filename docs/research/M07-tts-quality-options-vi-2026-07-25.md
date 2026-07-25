# M07 — Lựa chọn TTS tiếng Việt chất lượng cao cho Hina

Ngày đánh giá: 2026-07-25  
Máy mục tiêu: Windows, RTX 5070 Ti 16 GB, cần giữ tối thiểu khoảng 2 GB VRAM headroom.

## Kết luận ngắn

Không có model local nào được chứng minh cho tiếng Việt đạt đồng thời cả bốn
điểm: chất lượng/biểu cảm như ElevenLabs, clone đúng giọng anime, phản hồi
khoảng hai giây và chạy chung an toàn với LLM/STT trên 16 GB VRAM.

Thứ tự hợp lý:

1. Giữ VieNeu làm local/fallback nhưng dùng reference 44.1 kHz và benchmark
   bằng tai trên đúng câu hội thoại Hina.
2. Nếu chấp nhận cloud, thêm provider ElevenLabs Flash v2.5 cho hội thoại
   realtime và Eleven v3 cho câu biểu cảm/nội dung đặc biệt. Đây là đường ngắn
   nhất để giữ đúng chất giọng đã tạo trên ElevenLabs.
3. Nếu bắt buộc local và chấp nhận license phi thương mại, benchmark VietTTS
   trong WSL2/Docker GPU sau khi môi trường Linux được owner phê duyệt.
4. Chỉ benchmark Fish Audio S2 Pro trong tiến trình GPU cô lập; không chạy
   đồng thời với toàn bộ Hina trước khi đo VRAM.

## So sánh candidate

| Candidate | Tiếng Việt | Voice clone / biểu cảm | Khả thi hiện tại | License/rủi ro | Quyết định |
|---|---|---|---|---|---|
| VieNeu-TTS v3 Turbo | Có, chuyên Việt/Anh | Zero-shot reference; cue biểu cảm giới hạn | Đang chạy CUDA trên Hina | Apache-2.0 cho code; cần giữ provenance riêng cho weight/voice | Giữ làm local baseline |
| ElevenLabs Flash v2.5 | Có | Dùng đúng ElevenLabs voice ID; realtime streaming | Cần API key, internet và chi phí | Cloud/privacy; không được commit secret | Candidate chất lượng realtime số 1 |
| ElevenLabs v3 | Có, 70+ ngôn ngữ | Audio tag và dải cảm xúc mạnh | Chậm hơn, không phù hợp mọi lượt realtime | Cloud/privacy/cost | Chỉ dùng câu biểu cảm hoặc manual quality mode |
| VietTTS | Có, chuyên Việt; clone bằng prompt audio | Dựa trên CosyVoice, có OpenAI-compatible API | Upstream hiện ghi Linux-only; máy chưa có WSL/Docker | Code Apache-2.0, pretrained weight/audio CC BY-NC | Local quality benchmark số 1 sau khi có Linux |
| Fish Audio S2 Pro | 80+ ngôn ngữ | 10–30 giây reference; tag như `[whisper]`, `[excited]` | Model khoảng 4B + codec; rủi ro vượt ngân sách VRAM khi chạy cùng LLM | Fish Audio Research License | Benchmark cô lập, không mặc định |
| Chatterbox Multilingual V3 | Không có `vi` trong danh sách 23 ngôn ngữ | Clone tốt, V3 tự nhiên; tag native chỉ nổi bật ở Turbo tiếng Anh | Không phù hợp nội dung Việt | MIT code nhưng thiếu hỗ trợ Việt | Loại |
| Qwen3-TTS | Không có tiếng Việt trong 10 ngôn ngữ công bố | Streaming, voice clone, instruction emotion | Có thể chạy CUDA nhưng phát âm Việt không được support | Apache-2.0 | Loại cho Hina tiếng Việt |

## Vì sao reference trước đây làm giọng xấu

Pipeline profile từng chuyển MP3 44.1 kHz xuống WAV 16 kHz trước khi VieNeu
enroll. Bước này loại bỏ phần phổ cao của chất giọng anime trước khi codec tạo
reference codes. M07-S12 đổi anchor thành mono 44.1 kHz; speaker encoder vẫn tự
resample bản sao riêng khi cần, còn reference codec nhận được nguồn đầy đủ hơn.

VieNeu chỉ dùng một reference ngắn; 31 MP3 không tự động biến thành fine-tuning.
Gần bốn phút audio hiện tại đủ để chọn reference/instant clone, nhưng chưa đủ để
cam kết một model fine-tune ổn định. Với pipeline fine-tune thật, cần tối thiểu
khoảng 30 phút audio sạch, transcript chính xác từng file, thống nhất loudness,
không nhạc nền và chia train/validation.

## Benchmark tiếp theo đề xuất

Tạo cùng một bộ 12 câu tiếng Việt gồm:

- câu chào ngắn;
- câu có số, ngày, URL;
- câu hội thoại 20–40 từ;
- câu dài 100–180 từ;
- ba trạng thái vui, buồn, ngạc nhiên;
- cue cười/thở dài;
- từ tiếng Anh xen tiếng Việt.

Đo time-to-first-audio, real-time factor, peak VRAM, lỗi phát âm bằng STT
round-trip và chấm MOS thủ công 1–5 cho độ tự nhiên, đúng giọng, cảm xúc. Chỉ
promote provider mới khi owner nghe blind A/B và chọn nó.

## Evidence trên máy owner

- `pnpm prepare:voice`: 31 MP3 được audit, 30 clip phù hợp cửa sổ reference.
- `ffprobe hina-profile-anchor.wav`: mono, 44.1 kHz.
- VieNeu CUDA smoke với profile mới: sinh WAV 48 kHz thành công; time-to-first
  chunk khoảng 5.0 giây và tổng xử lý khoảng 6.9 giây cho câu smoke. Vì vậy
  VieNeu hiện chưa đạt mục tiêu phản hồi khoảng hai giây.
- Desktop Electron smoke: widget trong suốt, always-on-top, drag được; ba control
  Mic/Auto nghe/Voice hiện đúng khi hover/focus.

## Nguồn chính thức

- VieNeu-TTS: https://github.com/pnnbao97/VieNeu-TTS
- VieNeu documentation: https://docs.vieneu.io/
- ElevenLabs models: https://elevenlabs.io/docs/overview/models
- ElevenLabs latency: https://elevenlabs.io/docs/eleven-api/concepts/latency
- ElevenLabs voice cloning: https://elevenlabs.io/docs/eleven-api/concepts/voice-cloning
- ElevenLabs v3 prompting: https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices
- VietTTS: https://github.com/dangvansam/viet-tts
- Fish Speech: https://github.com/fishaudio/fish-speech
- Chatterbox: https://github.com/resemble-ai/chatterbox
- Qwen3-TTS: https://github.com/QwenLM/Qwen3-TTS
