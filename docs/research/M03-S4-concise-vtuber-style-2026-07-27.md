# M03-S4 — Hina trả lời ngắn, đúng trọng tâm

Ngày: 2026-07-27

## Vấn đề

Model local 4B có thể trả lời đúng nhưng thêm tự giới thiệu, diễn giải lại câu
hỏi hoặc lời mời hỗ trợ không cần thiết. Điều này làm lượt hội thoại chậm, TTS
dài và kém cảm giác phản xạ của một AI VTuber.

## Thay đổi inference hiện tại

- Persona bump từ `hina.prompt.v1` lên `hina.prompt.v2`.
- Mặc định 1–2 câu và thường ≤45 từ.
- Khi cần ngữ cảnh: tối đa 3 câu/khoảng 80 từ.
- Không lặp câu hỏi, tự giới thiệu ngoài ngữ cảnh, thêm disclaimer chung chung
  hoặc câu kết “cần gì cứ hỏi”.
- Yêu cầu code/chi tiết/danh sách/từng bước được quyền mở rộng.
- Thiếu dữ kiện thì hỏi đúng một câu làm rõ.
- Default provider budget giảm 512 → 192 token và vẫn override được bằng
  `HINA_MODEL_MAX_TOKENS`.

Không có hậu xử lý cắt chuỗi; model phải học/tuân prompt để kết thúc câu tự
nhiên.

Live smoke với Ollama `qwen3.5:4b`:

- input: `Bạn là ai? Trả lời tự nhiên nhé.`
- prompt: `hina.prompt.v2`
- outcome: completed, không lỗi;
- output: 1 câu, 22 từ, không có lời mời hỗ trợ thừa.

## Training trong tương lai (M11)

Mục tiêu là đặc tính chung “brief, reactive, lightly playful”, không sao chép
identity hoặc câu chữ của Neuro-sama. Dataset gồm các lane:

1. Direct answer: 1–2 câu, ≤45 từ.
2. Playful answer: tối đa một điểm dí dỏm nhưng vẫn có câu trả lời.
3. Clarification: đúng một câu hỏi khi thiếu dữ kiện.
4. Expand on request: câu trả lời dài đầy đủ khi owner yêu cầu.
5. Negative preference pairs: loại tự giới thiệu, lặp câu hỏi, disclaimer và
   closing offer thừa.
6. Safety pairs: giữ refusal/uncertainty/capability boundary dù phải dài hơn.

Nguồn hợp lệ là nội dung repository/owner tự viết, synthetic đã human-review
hoặc interaction có consent và curation. Không scrape stream, copy transcript,
catchphrase, private model hay dataset của Neuro-sama; raw public chat không
được dùng để train.

Gate dự kiến: direct-answer pass ≥90%, median ≤45 từ, p90 ≤80 từ,
expand-on-request completeness ≥95%, safety regression = 0 và owner blind A/B
trên ít nhất 100 cặp trước promotion.
