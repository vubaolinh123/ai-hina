# Thu thập lỗi khi owner test thủ công

Tài liệu này là contract vận hành cho các tính năng tương tác từ M01-S6 trở đi.
M01-S1 chưa có UI/runtime service; validator hiện trả `ErrorCode` ổn định và
`detail` cho caller.

## Bản ghi lỗi bắt buộc

Mỗi lỗi runtime đã bắt phải tạo đúng một record JSON có tối thiểu:

- `timestamp`: RFC3339 UTC.
- `level`: `error` hoặc `fatal`.
- `component` và `operation`.
- `errorCode`: mã ổn định, dùng được để tìm kiếm và viết regression test.
- `message`: mô tả ngắn đã redaction.
- `correlationId`; thêm `sessionId`, `turnId` khi có.
- `exceptionType` và stack trace chỉ trong local debug.
- `buildCommit`, phiên bản contract và runtime profile.

Không ghi secret, access token, raw PII, hidden reasoning, raw audio, screenshot
hoặc nội dung public chat chưa redaction.

## Gói thông tin owner gửi khi báo lỗi

1. Thời điểm xảy ra lỗi và thao tác ngay trước đó.
2. `errorCode` hiển thị hoặc tìm thấy trong log.
3. `correlationId`/`turnId` nếu có.
4. Commit/build đang chạy.
5. Đoạn log redacted từ record lỗi tương ứng.

## Đường dẫn và lệnh thực tế

- Runtime mặc định ghi lỗi tại `var/logs/hina-runtime.jsonl`.
- Demo từng slice ghi file riêng dưới `var/logs/` để dễ phân biệt.
- Trace M01-S6 nằm tại `var/logs/m01-s6-traces.jsonl`; trace không chứa prompt,
  raw audio hoặc hidden reasoning.
- Report mặc định được tạo tại `var/reports/hina-error-report.json`.

Từ thư mục gốc dự án, chạy:

```powershell
pnpm report:errors
```

Có thể chọn output khác:

```powershell
pnpm report:errors -- --output var/reports/bao-cao-loi.json
```

Report chỉ lấy tối đa 100 record `error`/`fatal` gần nhất, bỏ dòng JSON hỏng,
redact lại một lần nữa và ghi `buildCommit`. Nếu chính việc ghi log thất bại,
logger trả cờ `loggingFailed` nhưng không thay thế lỗi runtime ban đầu.
