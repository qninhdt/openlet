# Thiết kế hiện tại: Platform, LetFS và workspace resources

Cập nhật 2026-11-12. Người dùng đã chốt architecture/authorization/storage; [workspace resources](workspace-service-redesign.md) là owning design. [API Platform/LetFS](api-contract.md) và [Temporal](design.md#10-temporal-tối-thiểu) đã chốt qua trao đổi. Core đã implementation và local E2E pass; [plan](plan.md) và [feature audit](../reports/feature-parity-261112-platform-letfs-rewrite.md) ghi phần chưa đóng. API/transport và multiple storage của Leta hoãn; Computer chỉ design trước.

## Architecture đã chốt

Workspace là tenant chứa nhiều storage/agent/Computer. Platform sở hữu user/workspace/membership/invitations; LetFS sở hữu storage/quota/content/processing; Leta sở hữu agent/runtime; Computer tương lai sở hữu sandbox. Resource parent là workspace_id tại owning SQL, không cross-service SQL/FK.

SpiceDB canonical membership/ownership/grants. Workspace owner/member, agent owner/operator, storage owner/editor/viewer, Computer manager/operator. Agent là subject độc lập, không human member hoặc impersonation. Không owner/role/grant SQL mirrors, personal mapping hoặc generic registry.

Storages dùng visibility private/public, public mặc định viewer cho mọi actor hợp lệ của workspace; ghi cần owner/editor. Personal/shared là FE grouping. Nhiều storage/workspace/owner; UUID thông thường, không UUIDv5 hoặc unique owner→storage. MVP chỉ system provision workspace/storage. Root Leta giữ workspace_id/storage_id; multiple storage/switch hoãn.

Quota/usage canonical ở LetFS workspace_storage(workspace_id PK, quota_bytes, used_bytes). Platform không giữ storage IDs/list/quota mirror. [Schema](schema.md) giữ full file/transfer/processing design và boundary mới.

## API và transport

[Contract](api-contract.md) định nghĩa wire schema, từng public/internal RPC và HTTP binding. URL đề xuất /v1/workspaces/{workspace_id}/storages/{storage_id}/...; Envoy transcode và route trực tiếp owning gRPC service, không Platform proxy.

Platform/LetFS chỉ application gRPC + standard health; Envoy JSON/HttpBody; S3 signed transfers. Không Gin/grpc-gateway/app HTTP listener. ProtoJSON success và google.rpc.Status/ErrorInfo application errors; không RFC9457 mapper/common envelope. Empty thường HTTP200 {}. [HTTP details](http-json.md).

Leta public HTTP/SSE và concrete cleanup RPC review sau; không thêm listener/proto/config bắt buộc trong lượt này. Được phép async business cleanup khi xóa resource/workspace; RemoveMember chỉ thu hồi human membership, không dọn/dừng agent. Không stop-ACK barrier, readiness hoặc authorization hot-path dependency.

## Data, lifecycle và query giữ đúng boundary

Provisioning/visibility/deletion chạm SQL+graph dùng native durable retries, không transaction giữ lock qua RPC hoặc outbox/permission-sync framework. Graph-only membership/grant writes không replicate về từng service.

Remove user chỉ revoke human membership; human direct grants còn giữ bị workspace gate vô hiệu, rejoin phục hồi quyền human. Agent độc lập owner, tiếp tục bằng identity/grants riêng; không agent scan, stop/cleanup fanout hoặc cạnh user.owned_agent. Leta ghi/dọn agent.workspace và workspace.agent trong cùng native SpiceDB batch theo agent lifecycle; eligible_actor = participate + agent. Đổi tên registered_agent thành agent, bỏ RegisterAgent/UnregisterAgent ở Platform, dùng generic CheckWorkspaceActive. Không đăng ký/trạng thái riêng hoặc Register<Resource> RPC cho service mới. Transfer owner qua API riêng không đổi workspace binding/quyền agent. Personal storage agent dùng agent#owner userset, không snapshot human owner.

Text PostgreSQL/blob S3; user text không ingest. Blob content changes trigger CPU ParseBlob/IO EnrichAndIndex. Một files.version, readonly artifacts, source-version publication, stage SQL/native retries. Copy SQL + immutable object refs; quota logical bytes gồm artifacts/trash/copies. Không reservation/refcount/object-copy saga.

[Query principles](query-design.md), [Platform](platform-queries.md), [LetFS](letfs-queries.md), [processing](processing-queries.md) là targets, chưa số đo. Inventories cũ 20/31/6 không còn API authority. Bulk graph/SQL, RETURNING, không N+1/Stat readback/owner read từng card/count toàn bộ. Lists bulk capabilities; access screen đọc direct relationships.

Permission checks mặc định minimize_latency, optional ZedToken read-after-write, chấp nhận stale window; không local permission cache hoặc forced fully_consistent mọi mutation. Native generated clients và pgx/Clerk/Authzed/Temporal/AWS/Qdrant/OTel, không SDK/repository/DTO/command framework tự viết.

## Config, infra và execution limits

Một YAML/environment; non-secret trực tiếp, secrets dotenv/ENV qua ${ENV_VARIABLE}. [Config](configuration.md), [sample](openlet.example.yaml), [telemetry](telemetry.md). Native infra render cùng YAML, không merge/hot reload/secret-file framework. Owning process chỉ resolve settings/credentials cần thật; core startup không đòi Leta running.

[Infra/E2E/CI/CD](infra-testing-ci-cd.md): VPS/Compose, TypeScript Playwright api/browser, sáu scripts/two workflows. Source/tests/packages/infra legacy đã archive; [report](../reports/implementation-261111-1948-archive.md). Fresh DB, không import; archive handwritten code/tests chỉ context, viết mới.

[Knee point và rules](design.md#17-giới-hạn-implementation) tiếp tục bắt buộc: không rare-case mechanisms, compatibility để cứu tests, aggressive locks/fencing/leasing, N+1 hoặc unnecessary integration matrix. Nếu phát sinh thay đổi thiết kế có ảnh hưởng thật trong implementation thì hỏi trước khi đổi.

Contracts/migrations/infra và native runtime đã triển khai; focused checks, 4 API E2E journeys và PostgreSQL backup/restore drill pass. Feature parity đã đóng sau hybrid search và full API E2E cuối 4/4 pass; [review và LoC](../reports/readiness-loc-261112-platform-letfs-rewrite.md) đã hoàn tất; chưa GitHub/VPS/cutover hoặc benchmark; không validate lại Zed theo yêu cầu user.
