# Hina AI

Hina AI là dự án local-first xây một AI VTuber tiếng Việt theo kiến trúc mô-đun: hội thoại, speech, memory, avatar, perception, Minecraft và livestream được tách bằng contract rõ ràng.

Trạng thái hiện tại: **M00 — governance và scaffolding**. Chưa có model, speech service, avatar runtime hoặc game agent nào được coi là đã triển khai.

## Tài liệu chính

- Kế hoạch đã duyệt: [`HINA_AI_MASTER_PLAN_VI.md`](HINA_AI_MASTER_PLAN_VI.md)
- Báo cáo nghiên cứu: [`deep-research-report.md`](deep-research-report.md)
- Luật agent: [`AGENTS.md`](AGENTS.md)
- Trạng thái M00: [`docs/modules/M00-governance.md`](docs/modules/M00-governance.md)

## Yêu cầu bootstrap

- Windows 11 là nền tảng CI chính.
- Python 3.12–3.14.
- Node.js 22–24.
- `uv`.
- `pnpm`.
- Git.

## Kiểm tra M00

```powershell
uv lock --check
pnpm install --lockfile-only --frozen-lockfile
python tools/dev/validate_m00.py
python -m unittest discover -s tests -p "test_*.py"
node tools/dev/check-node-workspace.mjs
python tools/sbom/generate_sbom.py
```

Hoặc:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/dev/Invoke-M00Gate.ps1
```

## Nguyên tắc an toàn

- Service cục bộ chỉ bind `127.0.0.1` nếu chưa có threat model và xác thực mới.
- Không commit secret, audio thật, transcript riêng tư, model weight hoặc runtime cache.
- Không chạy code do LLM sinh như một production skill.
- Không dùng public chat làm memory/training data tự động.
- Không promote model/adapter hoặc bật public livestream nếu chưa có owner approval.

## License

Source code do dự án Hina AI tạo mới được phát hành theo MIT License. Code, model, dataset, voice và avatar lấy từ bên thứ ba có license/provenance riêng.
