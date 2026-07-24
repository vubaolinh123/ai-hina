# Hina core runtime

M01-S2 đến M01-S7 và M02-S1 cung cấp runtime nền tảng cho các module sau:

- bounded async queues, deadline, cancellation và idempotency;
- SQLite journal/outbox/inbox với lease, ACK/NACK và ordered replay;
- control plane loopback-only và WebSocket realtime;
- binary media frame không nhét byte vào base64 JSON;
- lifecycle dependency ordering, startup rollback và graceful shutdown;
- JSONL traces, low-cardinality metrics và error report đã che secret;
- resource lease giữ tối thiểu 2048 MiB VRAM headroom;
- deterministic test providers và idempotent turn replay harness;
- Hina Dev Console chạy lâu dài để owner thao tác với runtime thật.
- capability policy, emergency controls và hash-chained safety audit.

## Chạy ứng dụng

Từ repository root:

```powershell
pnpm start:dev-console
```

Runtime dùng mặc định:

- Console: `http://127.0.0.1:8765/`
- Database: `var/data/hina-runtime.sqlite3`
- Error log: `var/logs/hina-runtime.jsonl`
- Safety audit: `var/audit/hina-safety.jsonl`

Dừng bằng `Ctrl+C`. Chỉ chạy control plane không có giao diện bằng:

```powershell
pnpm start:control
```

## Kiểm tra nhanh

```powershell
pnpm test:fast
pnpm test:safety
pnpm smoke:m01-s2
pnpm smoke:m01-s3
pnpm smoke:m01-s4
pnpm smoke:m01-s5
pnpm smoke:m01-s6
```

Các lệnh `smoke:*` là harness kỹ thuật và không phải demo sản phẩm. Lệnh deep
`pnpm test:lifecycle:100` chỉ chạy khi owner yêu cầu.
