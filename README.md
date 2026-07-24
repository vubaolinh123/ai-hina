# Hina AI

Hina AI là dự án local-first xây dựng AI VTuber tiếng Việt theo kiến trúc
mô-đun. Hội thoại, speech, memory, avatar, perception, Minecraft và livestream
được tách bằng contract rõ ràng để có thể phát triển và rollback độc lập.

Trạng thái hiện tại: **M01 — runtime spine đang hoàn thiện**. HTTP control plane,
WebSocket realtime, SQLite journal, lifecycle, structured error logs, metrics,
resource leases và Hina Dev Console đã có mã chạy thật. Model hội thoại, speech
engine và avatar thật chưa được tích hợp; các phần đó thuộc các module sau.

## Chạy ứng dụng hiện có

Yêu cầu: Windows 11, Python 3.12–3.14, Node.js 22–24, `uv` và `pnpm`.

```powershell
pnpm install --frozen-lockfile
pnpm start:dev-console
```

Trình duyệt sẽ mở `http://127.0.0.1:8765/`. Đây là ứng dụng local chạy liên tục
cho tới khi bạn bấm `Ctrl+C`, không phải output dựng sẵn. Giao diện cho phép:

- kiểm tra health, version, config và metrics của runtime;
- kết nối WebSocket `hina.realtime.v1`;
- gửi durable event vào SQLite, thử dedupe và replay stream;
- round-trip binary frame opcode 2;
- chủ động tạo lỗi và đọc JSONL error log đã che secret.

Ứng dụng này kiểm thử hạ tầng M01 thật và không giả lập câu trả lời AI.

## Vòng lặp phát triển nhanh

```powershell
pnpm test:fast
pnpm report:errors
```

Các lệnh `smoke:m01-s2` đến `smoke:m01-s6` là harness kiểm tra kỹ thuật, không
được coi là demo sản phẩm. Workflow repeat/soak/deep chỉ chạy khi owner yêu cầu.

## Tài liệu chính

- [Kế hoạch tổng thể](HINA_AI_MASTER_PLAN_VI.md)
- [Báo cáo nghiên cứu](deep-research-report.md)
- [Quy tắc vận hành](AGENTS.md)
- [Trạng thái M01](docs/modules/M01-contracts-spine.md)
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
