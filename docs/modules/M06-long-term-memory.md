# M06 — Long-term memory có consent và chống poisoning

- Status: runnable candidate; fast unit/startup/browser verification passed
- Branch: `codex/M06-memory-dashboard`
- Base: `37d4121f52f400ca8fcafbfce07783ac2e2cf232`
- Active slices: authoritative SQLite store, derived Qdrant index, safe chat retrieval và owner dashboard

## Runnable target

Owner có thể tự tạo một memory candidate, xem provenance/trust/sensitivity,
duyệt hoặc từ chối, tìm lại, sửa, pin, export và xóa. Không có input nào được
tự động biến thành ký ức. SQLite là nguồn sự thật; Qdrant local chỉ là index có
thể rebuild.

Memory được đưa vào chat chỉ cho `owner.console`, dưới một user-role block có
delimiter và nhãn dữ liệu không đáng tin cậy. Public/viewer/authenticated input
không được đọc owner memory và memory text không thể thay persona/system policy.

Dev Console được tổ chức lại thành dashboard có các trang Tổng quan, Companion,
Memory, Safety và Runtime. Mỗi nhóm chức năng có giải thích mục đích và cách
dùng bằng tiếng Việt phổ thông.

## Deferred promotion evidence

Recall@5/nDCG labeled benchmark, Qdrant server deployment, production embedding
model, backup/restore rehearsal, fault injection toàn outbox và deep delete
lineage vẫn được hoãn tới khi owner yêu cầu promotion/deep verification.

## Implemented

- `packages/memory`: SQLite schema, audit trail, candidate/record lifecycle,
  optimistic versioning, expiry/pin, transactional outbox và deletion receipt.
- `QdrantLocalMemoryIndex`: persistent local-mode index, payload không chứa raw
  memory content, orphan cleanup và full rebuild từ SQLite.
- Text brain: retrieval chỉ cho `owner.console`; memory vào user-role block
  `[UNTRUSTED_LONG_TERM_MEMORY_DATA]`.
- Control API: status, candidates, decision, records, search, correct, pin,
  export, delete và rebuild.
- Dashboard: 5 hash route responsive, chú thích tiếng Việt, memory workflow thật.
- WebSocket keepalive: server ping/pong giữ dashboard kết nối khi người dùng chỉ
  đọc, và đóng peer không phản hồi sau hai idle windows.

## Fast evidence

- `tools/dev/Invoke-FastUnit.ps1`: 116 tests passed after memory hardening and
  keepalive fix.
- Startup check: Dev Console opened isolated temporary SQLite + Qdrant while the
  real app was already running, closed cleanly and removed its temporary data.
- In-app browser: navigation/group isolation verified on desktop and 390 px
  viewport; real candidate → promote → search → delete receipt passed; temporary
  browser-test memory was deleted; no browser console error.
