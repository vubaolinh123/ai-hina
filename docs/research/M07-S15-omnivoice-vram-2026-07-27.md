# M07-S15 — OmniVoice CUDA và tối ưu VRAM

Ngày đo: 2026-07-27  
Máy: NVIDIA GeForce RTX 5070 Ti 16 GB  
Quyết định: thay hoàn toàn VoxCPM2 trong active runtime bằng OmniVoice; giữ
VieNeu làm rollback và F5-TTS chỉ làm thí nghiệm đã bị quality-reject.

## Artifact được pin

- Package: `omnivoice==0.2.1`
- Source commit: `5ba967c4d5b0f08244ae856b033eea583d1e4517`
- Wheel SHA-256:
  `23f113ef51116a16308b55c4c2ac9c08efca7dfb594802f5c8adfb7523313ccc`
- Checkpoint: `k2-fsa/OmniVoice`
- Revision: `c5fdb5ccb189668d56333f77ba2629f4cd7535f4`
- Runtime: CUDA, FP16, SDPA, batch size 1, 24 kHz, Transformers 5.3.0.
- Optional Whisper ASR: tắt; Hina đã có STT riêng.
- Voice prompt: tạo một lần từ reference Hina tám giây có transcript khớp và
  SHA-256, sau đó giữ token prompt trên CPU.

File hash đầy đủ nằm ở
`ml/models/manifests/omnivoice-0.6b.v1.json`.

## Profile chất lượng

Thử nghiệm 16 diffusion steps nhanh nhưng câu dài chỉ đạt reverse-STT
similarity 0.6963 và mất một phần cuối câu. Profile được nâng lên 32 steps:

| Mẫu | Reverse-STT similarity | First audio | Processing | Audio |
| --- | ---: | ---: | ---: | ---: |
| Ngắn, warm | 0.9733 | 0.562 s | 0.672 s | — |
| Dài, warm, 32 steps | 0.9285 | 0.969 s | 3.594 s | 16.73 s |
| Đoạn owner báo rush, pacing mới, cold | 0.9463 | 6.609 s | 8.422 s | 12.76 s |

Cold process đã có cache cần khoảng 6.016 giây đến first audio. Reverse-STT chỉ
là regression signal; owner listening vẫn là authority để promotion chất lượng.
WAV pacing mới nằm tại
`var/tmp/m05-real-tts/hina-omnivoice-stable-owner-sample.wav`.

## VRAM đo thật

| Chỉ số | MiB |
| --- | ---: |
| Resident allocated sau load | 1946.3 |
| Peak allocated mẫu ngắn | 2099.2 |
| Peak allocated mẫu dài 32 steps | 2118.9 |
| Peak reserved mẫu dài | 2270.0 |
| Allocated sau request | 1946.3 |
| Tăng allocated sau vòng 12 request | 0.0 |
| Scheduler reservation | 3072 |
| Headroom contract | 2048 |

Reservation 3072 MiB cao hơn peak reserved đo thật khoảng 802 MiB nhưng thấp
hơn đáng kể so với profile VoxCPM2 cũ. Scheduler vẫn fail closed nếu reservation
làm vi phạm headroom toàn GPU.

## Kỹ thuật giảm VRAM được giữ

1. Dùng FP16 chính thức; không dùng community quantization chưa được kiểm chứng.
2. Không load optional ASR.
3. Batch size 1; chunk câu ngoài tối đa 110 ký tự và ưu tiên ngắt ở dấu
   câu/dấu phẩy.
4. Audio chunk tám giây khi dự đoán dài hơn 12 giây.
5. Giữ reusable voice prompt trên CPU.
6. Gọi `gc.collect()` và `torch.cuda.empty_cache()` sau request để trả allocator
   blocks không dùng; tensor model resident vẫn được giữ cho latency warm.
7. Recycle model nếu allocated tăng quá 512 MiB so với baseline hoặc sau 32
   request warm; scheduler preemption/shutdown vẫn unload toàn bộ.
8. Không bật `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`: PyTorch Windows
   hiện cảnh báo cấu hình này không được hỗ trợ trên runtime đã kiểm tra.
9. Giữ một speaking rate cho toàn lượt ở 1.0× tự nhiên. Profile cũ tăng rate
   theo tổng độ dài khiến một số đoạn rush và nuốt chữ trong owner listening
   test; bản sửa tách aside trong ngoặc thành chunk riêng và chèn 160 ms pause.

## License và giới hạn

Code OmniVoice là Apache-2.0. Model card upstream ghi pretrained weights
CC-BY-NC do ràng buộc training data (gồm Emilia) nhưng không nêu version đầy đủ.
Vì vậy Hina chỉ cho phép local non-commercial owner testing; commercial,
public-service và production promotion bị chặn cho tới khi có clearance.

Nguồn:

- https://github.com/k2-fsa/OmniVoice
- https://huggingface.co/k2-fsa/OmniVoice
- https://pypi.org/project/omnivoice/0.2.1/
