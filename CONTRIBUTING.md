# Contributing

## Luồng thay đổi

1. Đọc `AGENTS.md` và module brief đang active.
2. Chỉ sửa `owned_paths`.
3. Viết test cùng thay đổi.
4. Ghi provenance cho code hoặc asset lấy từ upstream.
5. Chạy gate hẹp nhất, sau đó chạy M00/full gate liên quan.
6. Không tự merge hoặc tự duyệt thay đổi của chính mình.

## Branch

- `main`: chỉ chứa module đã qua gate.
- `module/MNN-<slug>`: implementation.
- `integration/MNN-<slug>`: validation/integration nếu cần.

## Commit

Dùng commit nhỏ, mô tả mục đích, ví dụ:

```text
feat(memory): add candidate promotion contract
test(speech): add silence hallucination regression
docs(m00): record governance gate evidence
```

## Open-source provenance

Mọi file/snippet copy hoặc adapt phải có:

- Upstream URL.
- Exact revision.
- Original path.
- License/SPDX.
- Hash và modifications.

Không copy code không có license rõ.
