# Archive source và testing của đợt rewrite

Ngày 2026-11-11. Đã thực hiện theo yêu cầu archive code/services/packages/ingest và testing liên quan. Không schema/data change, commit hoặc deployment.

## Kết quả đã kiểm

Đích: archive/2026-11-11/, giữ relative paths. Đã di chuyển 29 source roots/test assets, gồm 473 files được kiểm SHA-256, size và mode trước/sau. 17 tracked files đã bị xóa trước đó vẫn absent; không lấy HEAD để làm sống lại code đã xóa. Không copy handwritten implementation/tests vào active tree mới.

- Toàn bộ apps/account, apps/workspace, apps/letfs và apps/letfs-ingest, gồm CPU/IO/parser/tests/fixtures.
- Toàn bộ packages/ cũ, gồm contracts/generated/shared source/tests.
- Toàn bộ e2e/ gồm specs, setup, fixtures, helpers và runner/config.
- scripts/performance/, các legacy tests ở scripts/contracts, scripts/operations, scripts/bootstrap; infra/compose/e2e.yaml.
- .github/workflows/check.yaml cũ, tránh tiếp tục chạy bộ CI đã archive.
- Lượt đầu: 16 Leta old-boundary/mixed tests, gồm VFS, resource binding, workspace/HITL integration, config/lifespan/HTTP contracts và các suites dùng shared clients cũ. Domain/runtime suites lúc đó được giữ; scope mới bên dưới đã archive nốt tests, vẫn giữ Leta domain source.

Ignored caches, virtualenvs, node_modules và binaries đi cùng directory rename để không xóa dữ liệu local; không được stage/commit. Binary server cũ có ignore path cụ thể. Docker context loại archive. Không chạy archived tests hoặc dùng chúng làm fallback.

## Bảo toàn dirty work

Local ignored backup ở .local/rewrite-archive-261111-1948/: dirty.patch, status-before.txt, head.txt, manifest.json và result.json. Dirty patch lấy trước move, manifest ghi source files/hash/modes và deletions. Không print raw source/secret data từ backup. Restore dùng archived files kết hợp snapshot; không reset worktree hoặc tự áp lại patch lên lịch sử mới.

## Trạng thái chưa hoàn thành

Archive là bước đầu của rewrite. Chưa viết contracts/SDK/services mới, chưa rewire active go/uv/pnpm manifests, imports, Compose hoặc build commands. Vì vậy stack cũ không còn build/run từ active paths; CI cũ đã archive và bộ CI mới chưa có. Không chạy test/build rồi báo xanh giả, không thêm compatibility/re-export từ archive.

Các bước tiếp theo nằm trong [plan](../261111-1727-platform-letfs-rewrite/plan.md): dựng contract/config/SDK, Platform/LetFS/ingest, Leta boundaries và affected consumer builds, rồi essential checks/cheap CI mới. Chưa benchmark, chạy provider/Envoy smoke hoặc migration. Không có owned background process cần giữ sau bước archive.

## Mở rộng infra/tooling và toàn bộ Leta tests

Người dùng yêu cầu archive cả infra/scripts/E2E/CI của Leta vì owner khác đang brainstorm refactor; đã xác nhận owner đó chưa sửa files. Target deploy mới là VPS/Compose. Thiết kế tiếp tục ở [cùng plan](../261111-1727-platform-letfs-rewrite/infra-testing-ci-cd.md), không plan độc lập.

Di chuyển thêm 177 files, trong đó 59 source/config/fixtures và 118 ignored Python cache files, vào cùng archive/2026-11-11/ theo relative path. Không đè file của lượt archive trước. Kiểm SHA-256/size/mode cho tất cả files sau move; 65 protected Leta source/migration/native dependency files giữ nguyên.

- Toàn bộ infra/ còn lại: dev Compose, bootstrap/MinIO Dockerfiles, native Envoy/Temporal templates.
- Toàn bộ scripts/ còn lại: legacy configure/generate/recovery và caches.
- Toàn bộ apps/leta/tests/ còn lại: domain/runtime/integration/replay fixtures và local crash workers.
- Leta Dockerfile, models.example.json, package.json; root Makefile, package.json, pnpm-lock.yaml, pnpm-workspace.yaml, turbo.json và legacy dotenv example.
- CI workflow và root E2E đã archive từ lượt trước; không khôi phục chúng để chạy xanh.

Mẫu YAML application vừa chốt không phải legacy implementation: đã rename nguyên bytes từ infra/config/openlet.example.yaml sang [design reference trong plan](../261111-1727-platform-letfs-rewrite/openlet.example.yaml), kiểm hash và cập nhật links. Không tạo active infra thay thế trong lượt đề xuất.

Snapshot riêng của batch nằm ở .local/rewrite-infra-261111-2041/: dirty.patch, status-before.txt, head.txt, manifest.json, result.json. Real dotenv chỉ kiểm inode/size/mtime không đổi; không đọc/copy nội dung. Không đụng database/volumes hoặc start/stop deployment processes. Giữ nguyên Leta src/, migrations/, pyproject.toml và root Go/uv dependency files cho implementation sau.

Active Make/pnpm/Turbo/Compose/scripts/Leta tests hiện đã archive; chưa có bộ mới và native manifests/imports chưa rewire. Không có build/test/runtime/CI/deploy pass của thiết kế mới. Caches trong archive không được commit; archive không được discover bởi tools mới.
