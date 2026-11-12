# Platform, LetFS và ingest: rewrite

Cập nhật 2026-11-12. Architecture, schema, API Platform/LetFS và Temporal đã được người dùng chấp thuận; Core và hybrid search đã kiểm chứng local; đối chiếu chức năng và review trước push dev đã hoàn tất. API/transport và multiple storage của Leta hoãn; Computer chỉ thiết kế boundary.

- [Tổng hợp hiện tại](final-proposal.md).
- [Workspace resources và SpiceDB đã chốt](workspace-service-redesign.md).
- [API gRPC/HTTP JSON Platform/LetFS](api-contract.md).
- [Schema/service trust](schema.md).
- [Leta schema đã reconcile](../261111-2010-leta-rewrite/schema.md), [DDL review](../261111-2010-leta-rewrite/schema.sql): schema 11 bảng đã được duyệt; [boundary review Leta](../261111-2010-leta-rewrite/boundaries.md) ghi integration gaps, không tự đổi SQL/API core.
- [Query principles](query-design.md), [Platform](platform-queries.md), [LetFS](letfs-queries.md), [processing](processing-queries.md).
- [File/ingest design và implementation rules](design.md).
- [Configuration](configuration.md), [YAML mẫu](openlet.example.yaml), [telemetry](telemetry.md), [HTTP JSON](http-json.md).
- [Infra/E2E/CI/CD](infra-testing-ci-cd.md), [archive report](../reports/implementation-261111-1948-archive.md), [đối chiếu chức năng](../reports/feature-parity-261112-platform-letfs-rewrite.md).
- [Review trước push dev và LoC](../reports/readiness-loc-261112-platform-letfs-rewrite.md).
- [Benchmark LetFS: đủ 43 RPC, query plans và các điểm cần tối ưu](../reports/benchmark-261112-1212-letfs.md).
- [Sửa hiệu năng LetFS và audit idempotency](../reports/implementation-261112-1249-letfs-performance-idempotency.md).
- [Role/UI research](../reports/research-261111-1834-spicedb-role-ownership.md), [consistency research](../reports/research-261111-1746-spicedb-consistency.md): historical evidence; policy hiện tại lấy từ design đã chốt.

## Kết quả và giới hạn

Viết mới Platform thay Account/Workspace, LetFS, ingest CPU/IO và active shared packages. Archive đã hoàn tất source/tests/infra legacy theo inventory dưới; archive chỉ context, không copy handwritten implementation/tests. Fresh DB, không import dữ liệu cũ.

Leta chỉ boundary/config/client changes trong plan này; API/runtime và multiple storage/switch hoãn. Root agent giữ workspace_id/storage_id. Không tự sửa nội bộ plan Leta hoặc tạo Computer runtime/database/manifests.

## Các quyết định đã chốt

- Workspace tenant; Storage/Agent/Computer ngang hàng, owning service quản lý resource.
- PostgreSQL domain metadata; SpiceDB canonical membership/ownership/grants. Không SQL membership/grant/owner mirror.
- Workspace owner/member, agent owner/operator, storage owner/editor/viewer; Computer manager/operator tương lai.
- Nhiều storages/workspace/owner, visibility private/public. Public mặc định viewer cho actor hợp lệ trong workspace; editor/owner mới ghi.
- Không filesystem/scope/drive entity, personal mapping table, unique owner→storage hoặc UUIDv5.
- Quota/usage LetFS workspace_storage dùng workspace_id PK; Platform không giữ quota/storage IDs/list.
- MVP chỉ system provision workspace/storage. Agent một storage_id, multiple/switch hoãn; FE personal/shared grouping.
- Native SpiceDB checks/bulk + SQL; không Platform membership RPC/N+1. minimize_latency, optional ZedToken; không forced fully_consistent mọi mutation.
- Async cleanup owning business API được phép; không Leta stop-ACK barrier/readiness/hot-path dependency. Concrete Leta API hoãn.
- Text PostgreSQL/blob S3; blob-only ingest CPU ParseBlob/IO EnrichAndIndex, files.version duy nhất, readonly artifacts.
- Platform/LetFS gRPC; Envoy ProtoJSON/HttpBody; signed S3. Không app HTTP/Gin/grpc-gateway hoặc RFC9457 mapper.
- Một YAML, secrets dotenv/ENV references, native outbound telemetry; VPS/Compose và TypeScript Playwright api/browser.
- Không validate lại Zed theo yêu cầu; local build/integration/E2E đã pass, chưa production cutover.

## Phạm vi archive bắt buộc

| Nguồn | Đích dưới archive/2026-11-11/ | Nội dung |
|---|---|---|
| apps/account, apps/workspace, apps/letfs | apps/ tương ứng | Toàn bộ source, migrations, tests, fixtures, replay assets và local runner/config |
| apps/letfs-ingest | apps/letfs-ingest | Toàn bộ code CPU/IO/parser, tests, fixtures/model-test harness; không giữ parser implementation cũ làm fallback |
| Mọi thư mục con packages/ hiện tại | packages/ tương ứng | Contracts/generated code, handwritten SDK/helpers và toàn bộ tests |
| e2e/ | e2e/ | Toàn bộ specs, setup, fixtures, helpers, Playwright/TypeScript/package config, cả cross-service journeys |
| Test/performance/recovery harness phụ thuộc contract cũ ở scripts/ và infra/ | Cùng relative path | Test files, fixture/history/snapshot assets và runner/config riêng của bộ test cũ; inventory trước khi move |
| Toàn bộ Leta tests/fixtures/replay assets | apps/leta/tests/ tương ứng | Scope mới: archive cả domain/runtime suites; owner Leta viết tests cho code refactor |
| Toàn bộ infra/ và scripts/ còn lại | Cùng relative path | Compose/native templates/bootstrap/generation/recovery cũ; mẫu YAML thiết kế chuyển về plan |
| Leta deployment/task config và root orchestration | Cùng relative path | Leta Dockerfile/models.example.json/package.json; root Makefile/package.json/pnpm files/turbo.json và legacy dotenv example |

Theo yêu cầu mở rộng sau đó, cả Leta src/, migrations/ và native dependencies cũng đã archive; không còn active Leta runtime trong đợt core này. Owner Leta đang brainstorm refactor riêng, chưa sửa files lúc archive; infra không tự sửa domain Leta. Root commands/CI/test discovery được viết mới, không dùng archive hoặc lệnh luôn thành công. Build artifacts/caches/secrets không đưa vào Git. Inventory/hash và local dirty patch được giữ trước move; không reset hoặc copy handwritten implementation/tests từ archive vào active tree.

## Các bước và trạng thái

| Bước | Trạng thái | Acceptance |
|---|---|---|
| Archive source/tests/infra legacy | Hoàn tất | Inventory/hash ở archive report; không đụng DB/secrets |
| Architecture/resource/authorization | Đã chốt 2026-11-12 | Storage visibility, graph authority, no personal mapping |
| API Platform/LetFS | Đã chốt | RPC/message/HTTP mapping ở api-contract.md |
| Temporal core | Đã chốt | Inventory/ownership/retry ở design.md mục 10 |
| API/runtime Leta, agent multiple storage | Hoãn | Chỉ giữ workspace_id/storage_id và actor contract |
| Computer | Chỉ thiết kế | Chưa service/database/manifests |
| Contracts/config/build/handlers | Local checks pass | Theo API đã chốt, generated clients và affected callers đồng bộ |
| Đối chiếu chức năng ngoài Leta | Hoàn tất, hybrid E2E pass | Platform (gộp Account/Workspace), LetFS, ingest và packages: mỗi hành vi archived có owner mới, bằng chứng giữ hoặc quyết định thay đổi đã duyệt; thiếu sót phải sửa trước acceptance |
| Infra/E2E/CI/CD | Local verified | Native checks + 4 API journeys + PostgreSQL backup/restore drill; workflows đã viết/lint, chưa chạy GitHub/VPS |
| Production cutover | Chưa thực hiện | Giữ DB cũ; credentials/domain/TLS/S3 recovery cấu hình khi triển khai thật |

## Todo hiện tại

- [x] Archive source/packages/tests/E2E/infra/scripts/CI legacy, bảo toàn dirty tree và hashes.
- [x] Chốt config YAML + dotenv ENV refs, native telemetry và HTTP status contract.
- [x] Chốt fresh DB, VPS/Compose, Playwright TypeScript api/browser và knee-point rules.
- [x] Chốt workspace resource ownership, SpiceDB source of truth, roles rút gọn.
- [x] Chốt storage private/public, multi-storage schema, workspace quota tại LetFS; bỏ personal mapping/UUIDv5.
- [x] Hoãn Leta API/multiple storage, giữ một storage_id; Computer design-only.
- [x] Reconcile owning docs và đề xuất API gRPC/HTTP JSON trong cùng plan.
- [x] Chốt API Platform/LetFS, public/internal inventory và workspace-nested URL.
- [x] Chốt Temporal inventory/ownership, hai ingest activities, schedules và retry boundaries.
- [x] Chốt agent độc lập human owner; workspace.agent thay tên cũ, Leta ghi hai chiều cùng batch và RemoveMember chỉ thu hồi human membership.
- [x] Đồng bộ core Zed/readers/writers/fixtures, bỏ registration RPC/owned-agent scan, thêm CheckWorkspaceActive và generated consumers; không chạy lại Zed validation. Leta implementation hoãn.
- [x] Generate proto/clients/descriptor và dựng Platform/LetFS/ingest theo thiết kế đã chốt.
- [x] Rebuild manifests/runners/CI, focused validations và PostgreSQL backup/restore drill. Remote CI/deploy/cutover chưa thực hiện.
- [x] Ingest khôi phục layout/Office/Excel, enrichment/index context và offline models bằng implementation mới; 15 focused tests và full XLSX pipeline pass. Hybrid search/index setup đã bổ sung theo quyết định sau audit; full API E2E cuối pass.
- [x] Đóng [đối chiếu archived ngoài Leta](../reports/feature-parity-261112-platform-letfs-rewrite.md): người dùng chốt chỉ thêm hybrid search; filters/sort, cross-storage restore và mkdir/empty-trash options được chấp nhận cắt. Hybrid đã implementation và full API E2E pass 4/4, 32.7s phần Playwright.

- [x] Rà soát active project trước push dev, sửa upload receipt/member-limit gaps, kiểm generated drift/candidate secrets và đo LoC trước/sau; [evidence](../reports/readiness-loc-261112-platform-letfs-rewrite.md). Chưa commit/push hoặc remote CI.

- [x] Áp dụng benchmark fixes/idempotency audit đã duyệt: single resolver, batch tree/processing, rename direct SQL, bỏ receipts mkdir/visibility, multipart checksums; checks/SQL/E2E 4/4 và 3.045 targeted benchmark requests không lỗi. ReadTree 1000 c32 còn tail khoảng 457 ms; [evidence và audit matrix](../reports/implementation-261112-1249-letfs-performance-idempotency.md).

## Sẵn sàng implementation và làm song song với Leta

Phạm vi implementation đã chốt đã có local proof. Đối chiếu archive đã có quyết định: chỉ bổ sung hybrid search, không thêm search filters/sort, cross-storage restore hoặc mkdir/empty-trash options. Hybrid không đổi public API; đã kiểm chứng, xem báo cáo chức năng và review trước push dev. API/Temporal nội dung đã được chấp thuận; protobuf field numbers, pinned dependency versions, native SDK options và chi tiết SQL là công việc implementation, không mở thêm vòng brainstorm. Nếu bằng chứng thực thi buộc đổi public semantics/schema/permission/boundary hoặc thêm cơ chế ngoài plan thì hỏi user trước khi đổi. Không hỏi lại routine coding choices đã nằm trong thiết kế.

Phần core triển khai apps/platform, apps/letfs, apps/letfs-ingest, shared contracts/SDKs, core infra/E2E/CI. User và Codex khác thảo luận Leta trong apps/leta và plan Leta riêng; core không sửa hai vùng đó khi chưa đồng bộ. Shared contracts/authz/YAML/infra do core quản lý để tránh sửa chồng; thay đổi từ thiết kế Leta ảnh hưởng những contract này phải được đồng bộ trước khi code, không tự mở callback/queue hoặc dependency core mới.

Agent subject, một workspace_id/storage_id, owner/operator và core resource contracts là điểm tích hợp đã chốt. Concrete Leta APIs/runtime/multiple storage/switch và physical cleanup Leta vẫn hoãn, không chặn implementation hoặc validation core. Computer runtime chưa triển khai. Domain/TLS/VPS credentials và provider thật được cấu hình lúc deploy; không chặn local/CI bằng cấu hình test đã thiết kế.

Đã đối chiếu schema Leta ngày 2026-11-12: root giữ workspace_id/storage_id, bỏ created_by_user_id và unique storage binding; Leta quản lý agent relations và hai chiều agent.workspace/workspace.agent, Platform workspace/membership, LetFS storage/grants. Pending human recipient là event fact, không current owner authority; accepted storage approval gọi LetFS theo current human manage_access. Quota/visibility/membership không mirror sang Leta. Physical cleanup/API/transport và multiple storage của Leta vẫn cần review riêng trước implementation boundary.

Quyết định boundary cùng ngày, đã triển khai phía core: xóa Platform RegisterAgent/UnregisterAgent và AgentRegistrationRequest, thêm generic CheckWorkspaceActive(workspace_id); Leta tự ghi/dọn agent.workspace và workspace.agent trong cùng native SpiceDB batch với owner/operators. Đổi registered_agent → agent trong Zed/readers/writers/fixtures/bootstrap; eligible_actor = participate + agent. Không registration step/state riêng, owned_agent hoặc runtime gate phụ thuộc membership owner. RemoveMember chỉ thu hồi human membership với owner guard, bỏ agent-owner scan/loop và mọi resource/stop fanout; agent tiếp tục bằng identity/grants riêng. [Boundary đã chốt](../261111-2010-leta-rewrite/boundaries.md#71-removemember-và-agent-độc-lập) thay proposal cũ; rejoin không ảnh hưởng agent. Đồng bộ [API contract](api-contract.md), handlers, generated clients/descriptor và Leta consumer cùng đợt; không wrapper/backward compatibility hoặc Register<Resource> mới. Không thay SQL schema hoặc sáu workflow types Leta vì quyết định này; core Zed/runtime/generated đã đồng bộ; Leta implementation vẫn hoãn.

## An toàn và verification

Không reset/ghi đè code user, không import archived handwritten implementation/tests, không đọc/sửa dotenv thật hoặc database cũ; kiểm chứng chỉ dùng databases mới tách biệt. Database cũ giữ nguyên đến cutover riêng; backup trước schema/data change. Chưa push/deploy/cutover production.

Không validate lại Zed theo yêu cầu. Native bootstrap áp dụng schema vào test datastore mới; không khôi phục Zed validation suite. Local Envoy/Compose/E2E đã pass; benchmark LetFS local đã có báo cáo riêng, chưa chứng minh môi trường production.

## Tiến độ implementation 2026-11-12

- Contracts, generated Go/Python clients/public descriptor, SDK helpers, baseline SQL, Platform/LetFS handlers, native gRPC health và hai ingest workers đã có. Platform không phụ thuộc Leta startup/ACK. Các application không có HTTP/Gin server.
- Temporal thật: ProvisionWorkspace, ProvisionMemberStorage, UpdateStorageVisibility (kể cả replay), DeleteWorkspace, Platform/LetFS Maintenance và ProcessBlob qua cả CPU/IO đã chạy trên fresh PostgreSQL. Native Schedules dùng overlap Skip. Không chỉ có workflow declarations.
- Ingest giữ Office/layout/Excel/images/OCR offline, structured enrichment và full-body index/ancestor context; IO không load Docling/OCR. Fifteen focused tests pass, gồm exception causes và signed-URL privacy. PDF scan offline đã smoke chủ động, không đưa model-quality suite nặng vào PR mặc định.
- S3 local/E2E dùng RustFS 1.0.5 pinned digest, native AWS SDK/checksum/multipart; bỏ MinIO/Moto/SeaweedFS khỏi active topology. So sánh nhỏ với SeaweedFS trước đó: RustFS idle/sau smoke khoảng 21/26 MiB, SeaweedFS 126/171 MiB; không load benchmark. Evidence ignored `.local/s3-provider-comparison.json`.
- Common YAML + dotenv ENV refs render private native Envoy/Temporal/Compose config. Sáu scripts và hai GitHub workflows đã viết. Deploy bundle pin đúng images được E2E trước push; chưa thực sự push/SSH/deploy. Go/Python/dependencies/images pin resolved stable versions; Python toàn bộ 3.14.
- Go tests/vet, Ruff, Buf lint, E2E TypeScript, ShellCheck/actionlint pass. Native migrated PostgreSQL invariant check pass, gồm blob move vào storage text-only bị rollback. Text MIME không được gửi qua public/artifact S3 upload; dùng PostgreSQL APIs/manifest.
- Final fresh Compose pass **4/4 API journeys, 32.7s phần Playwright**: gateway auth/internal isolation; collaboration/invite/grant/revoke/delete không Leta; text/idempotency/quota/copy/ZIP/trash/restore; XLSX CPU+IO/artifacts/search/download. Không publish host ports. Runner đã teardown containers/networks/volumes. Evidence ignored `.local/e2e/results/` và `.local/e2e-final.log`.
- PostgreSQL backup/restore drill hoàn tất trên hai projects riêng: sáu inventory databases/sáu checksummed dumps, domain data trước/sau khớp, nonempty restore bị từ chối, native SpiceDB repair và restored authorization pass. Sửa stdin-drain khiến vòng dump/preflight bỏ qua database, rồi chạy lại drill đầy đủ. Evidence ignored `.local/drill/snapshot-complete/` và logs; không dùng snapshot thất bại trước đó. Chưa full S3/Qdrant disaster recovery.
- ZedToken từ native writes được truyền qua onboarding/member-storage provisioning để read-after-write có căn cứ; default checks vẫn minimize_latency, không fully_consistent polling.
- [Feature audit](../reports/feature-parity-261112-platform-letfs-rewrite.md) đã ghi retained/approved-change/missing matrix từ archived Account/Workspace/LetFS/ingest/packages. **Đã đóng acceptance:** người dùng chọn chỉ thêm hybrid search; bốn hành vi còn lại được chấp nhận cắt. Native BM25 + dense/RRF đã implementation và full E2E pass. Review trước push dev không còn blocker trong scope MVP; chưa commit/push. Production services/workers (không Leta) giảm 16,947 → 5,093 LoC (69.9%); xem báo cáo LoC cho tests/generated/shared packages. Leta/Computer, frontend/browser execution, real-provider quality, load benchmark, GitHub/VPS/cutover chưa thực hiện.
