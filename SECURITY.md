# Security Policy

## Supported state

Hina AI đang ở giai đoạn bootstrap. Không có release production nào được hỗ trợ cho tới khi M12 Public Release Gate đạt yêu cầu.

## Báo cáo lỗ hổng

Không mở issue công khai nếu báo cáo chứa secret, dữ liệu cá nhân hoặc hướng khai thác hoạt động. Hãy dùng GitHub Private Vulnerability Reporting/Security Advisory của repository.

Kèm theo:

- Commit SHA và môi trường.
- Cách tái hiện tối thiểu.
- Tác động và capability bị ảnh hưởng.
- Log đã redaction.
- Đề xuất mitigation nếu có.

## Invariant

- Local endpoints mặc định bind `127.0.0.1`.
- Unknown capability fail closed.
- Secret không đi vào Git, prompt, memory, log hoặc artifact.
- External input được coi là untrusted cho tới khi qua schema/trust/policy boundary.
- Không thực thi shell/JavaScript/Python do model sinh.
- Public stream, voice cloning, license waiver và model promotion cần owner approval.
