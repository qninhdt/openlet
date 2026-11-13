# Hệ thống và hạ tầng Leta đã chốt

Người dùng đã duyệt ngày 2026-11-12. Đây là thiết kế đích, chưa phải trạng thái deploy. [Plan và trạng thái quyết định](plan.md), [component/folder structure](design.md), [Temporal](temporal.md) và [streaming](streaming.md) sở hữu chi tiết tương ứng.

## 1. Đơn vị triển khai

Một Python service, một Docker image, hai process roles thường trực:

| Process | Command | Trách nhiệm |
|---|---|---|
| Leta API | `python -m leta.api` | HTTP JSON/SSE, trusted identity/current authorization, commands/queries, Temporal admission, snapshot/reconnect/live |
| Leta worker | `python -m leta.worker` | Workflows/activities, LangGraph model/tools, lifecycle, HITL và schedules |

Worker mở ba native Temporal Worker instances trong cùng process:

| Queue | Công việc |
|---|---|
| `openlet-leta` | Sáu workflow types, Local SQL và E effect activities |
| `openlet-leta-runtime` | Activity `run_agent` chạy dài |
| `openlet-leta-bridge` | B activities chờ workflow Updates/results |

Giữ inventory **6 workflows / 22 activities / 3 queues**; thêm DeleteWorkspaceAgents trên bridge theo [cleanup contract](../261111-1727-platform-letfs-rewrite/workspace-cleanup.md). Phân tách native slots xử lý vòng đợi runtime → lifecycle → workflow/effect; không tạo process/container theo agent, box hoặc Leti. Scheduler, sandbox và LangGraph chạy trong worker; không thêm service hoặc supervisor framework riêng.

## 2. Components trong app

| Component | Nhiệm vụ | Owning design |
|---|---|---|
| Resources | Root/box/Leti, profile/model, lifecycle và immutable graph | [Kiến trúc](design.md), [Box/Leti](boxes.md) |
| Messaging | Admission, routing, durable inbox và explicit user delivery | [Schema](schema.md), [Temporal](temporal.md) |
| Runtime | Native agent loop, bounded inbox middleware, checkpoints/compaction/prune | [Runtime](design.md#6-inbox-và-agent-execution) |
| Filesystem | Mirage/Monty, LetFS adapter, home containment và dynamic mounts | [VFS](filesystem.md) |
| HITL | Async ask/approval, recipient rights, outcome/delivery | [HITL](hitl.md) |
| Schedules | SQL definitions, serialized changes, native timing và delivery | [Scheduler](scheduler.md) |
| History/events | Public projection/search, previews/detail, Redis suffix và SSE | [Streaming](streaming.md) |
| Authorization | Native current checks và owning agent relationships | [Boundaries](boundaries.md) |

HTTP routes, agent tools và activities gọi trực tiếp owning feature functions. Giữ folder structure tại [design mục 12](design.md#12-cấu-trúc-thư-mục-hoàn-chỉnh); không thêm repository/usecase/event-bus layers. Mirage/cache đã chốt 2026-11-13: mọi file_*/exec_* qua dispatcher, native Redis content/index cache BOUNDED/default TTL 600 giây; bỏ filesystem/policy.py, không remote check trước cache hit.

## 3. Datastores và authority

| Hệ thống | Authority và cách dùng |
|---|---|
| Leta PostgreSQL | 11 application tables đã duyệt; database/user riêng trên PostgreSQL instance chung |
| Native LangGraph saver | Native checkpoint tables trong cùng logical database Leta; native migrations, không app checkpoint/progress mirror |
| Temporal | Orchestration, retries, Updates/wake/control, timers và native schedules; không model/tool transcript |
| Redis | Recent public stream/reconnect hữu hạn và native Mirage content/index cache; mất stream thì resync SQL, mất cache thì đọc LetFS; không recovery authority |
| SpiceDB | Current permissions và agent relationships; ownership theo từng service |
| LetFS | Files/tree/bytes/version/quota và storage access; Leta dùng native gRPC, bytes qua signed URLs được cấp |

Leta không đọc SQL/Qdrant của LetFS, không gọi ingest trực tiếp và không có permanent S3 credentials. Public history tách working context để compaction/prune không xóa transcript của sản phẩm. Retention MVP đã chốt: không auto-purge durable inbox/public history/archived resource records; delete vẫn teardown/archive và native checkpoint keep_latest tiếp tục. Không thêm purge worker/cron/job. SQL/index/backup tăng theo sử dụng, cần dung lượng tương ứng; future physical purge/expiry hoãn. Quyết định này không đổi native Redis stream trimming, closed Temporal history retention, finite core receipts hoặc LetFS trash/blob GC.

## 4. Compose, migrations và ingress

Theo [infra core đã chốt](../261111-1727-platform-letfs-rewrite/infra-testing-ci-cd.md), thêm trong native Compose profile `leta`:

- `leta-api` và `leta-worker`: cùng image, khác command.
- `leta-migrate`: one-off job chạy domain migrations và native saver setup trước khi API/worker nhận việc.
- Redis: dependency riêng của tích hợp Leta; reuse PostgreSQL, Temporal và SpiceDB hiện có.

Không tạo thêm Compose variants hoặc migration engine. Image Leta không mang Docling/OCR/GPU dependencies của ingest. Migrations/setup không chạy theo request hoặc trên mỗi runtime start.

Envoy xác minh JWT, strip trusted actor headers và route trực tiếp HTTP JSON/SSE tới Leta; configure streaming/timeout tương ứng SSE. Platform/LetFS tiếp tục native gRPC + JSON transcoding. Backend/datastore ports private, chỉ ingress public; chi tiết identity/trust theo [boundary mục 3](boundaries.md#3-wire-actor-và-trust).

Core startup/readiness/tests không cần Leta, Redis hoặc model-provider config của Leta. [Cleanup liên service đã chốt](../261111-1727-platform-letfs-rewrite/workspace-cleanup.md): Platform dispatch owning activities, storage/Platform SQL không đợi Leta; workflow vẫn pending khi Leta activity chưa xong. Backend integration đã có code; không thêm cleanup service/workflow mới.

Active [Compose](../../infra/compose.yaml) đã có các additions trên; shared API E2E chạy cả core và Leta. Một VPS/VM chạy Docker Compose là target ban đầu; topology này không HA. DNS/TLS/host sizing cụ thể xử lý khi deploy, không mở thêm platform orchestration.

## 5. Config và secrets

Một `OPENLET_CONFIG` YAML, non-secrets trong YAML và secrets qua ENV references; theo [config core](../261111-1727-platform-letfs-rewrite/configuration.md). Role chỉ nhận credentials cần dùng: model-provider key thuộc worker, API không cần quyền gọi model. Migration job nhận database credentials cần cho migration.

Current implementation còn catalog/default ở `models.leta`; target thay bằng LiteLLM metadata và Langfuse Prompt Config theo [inference đã chốt](inference.md) và [plan triển khai tiếp theo](../261114-0035-inference-prompts-compaction/plan.md). Không triển khai lại local catalog này. Dùng native generated Python clients của [SDK](../../packages/sdk-python/pyproject.toml), không copy SDK archive hoặc thêm HTTP wrapper cho core. [Make generate](../../Makefile) đã có generation Python từ active contracts.

Shared YAML hiện có leta/leta_runtime mappings. Thêm dependencies.temporal.queues.leta_bridge cùng Go Queues/Python/YAML mẫu/test/deploy để Platform route shared cleanup; không thêm key làm strict loader lỗi hoặc đòi services.leta/models.leta/Redis secrets. Bridge routing name không đòi worker healthy.

## 6. Concurrency và lifecycle process

Bắt đầu một API replica và một worker replica. API có thể nhân bản không cần session stickiness: current snapshot ở PostgreSQL, reconnect cursor ở Redis. Worker replicas cùng consume ba queues; dùng native concurrency/backpressure, chưa thêm autoscaler hoặc sharding controller.

Mỗi agent có session advisory writer lock đã chốt để ngăn hai attempts ghi cùng thread. Runtime slots và PostgreSQL pool phải tính cả connection giữ lock lâu dài lẫn saver/domain queries; không đồng nhất số runtime slots với số connections rảnh cho SQL. Các queue/pool budgets cụ thể chọn khi implementation theo năng lực host/provider, rồi đo focused workload.

SIGTERM ngừng nhận việc mới và dùng native graceful shutdown/cancellation. Runtime tới safe model/tools boundary, sync checkpoint → public projection → prune → đóng workspace/nhả lock; không đợi agent hết việc. Grace period phải phù hợp deadline model/tool. Nếu process chết trước boundary, native retry dùng checkpoint và owning effect idempotency với giới hạn receipt horizon đã công bố; không hứa exactly-once toàn shell.

## 7. Backup và khôi phục

Mở rộng [backup/restore route hiện có](../../docs/operations.md) cho database Leta gồm cả domain và native checkpoint tables. Restore phải dùng bộ state phù hợp giữa Leta, Temporal và SpiceDB; backup S3 thuộc LetFS. Redis không là nguồn recovery và có thể bỏ rồi bootstrap lại public views.

Giữ cutover fresh database/Temporal namespace và stop old writers/schedules theo [design mục 15](design.md#15-archive-viết-mới-và-cutover). Không import old histories/checkpoints hoặc merge hai lịch sử ghi. Chưa chạy Leta restore drill; thiết kế này không hứa distributed snapshot atomic giữa mọi datastore.

## 8. Telemetry và checks

JSON stdout + native optional OTEL theo [telemetry core](../261111-1727-platform-letfs-rewrite/telemetry.md). Theo dõi các tín hiệu trực tiếp phục vụ vận hành:

[Thiết kế observability toàn hệ thống đã chốt](../261113-1335-system-observability/plan.md) chạy Alloy, Grafana Cloud Free Mimir/Tempo/Loki/Grafana và Langfuse Cloud Free; không local monitoring backends: native callback mỗi lượt graph, prompt management theo docs; evaluation deferred. Chưa implementation, không tự đổi approved Temporal/runtime.

- Runtime slots, queue/inbox backlog, activity failures/retries.
- Model latency, token/cache usage và cost khi provider trả usage.
- PostgreSQL pool wait, checkpoint/projection/prune latency/failures.
- SSE reconnect/resync/slow clients và Redis memory/retention.

Không log mặc định raw prompts/file bodies hoặc từng token. Không thêm metrics HTTP server trong worker hoặc monitoring stack riêng. API có health/readiness theo dependency contract; worker dùng native startup/fatal exit và process supervisor, running status không chứng minh queues đã được xử lý.

Focused Python lint/import/build/behavior checks và shared integration environment theo [test design](design.md#14-test-và-ci-ở-knee-point). Cross-service Leta journey nằm trong suite được chọn riêng, reuse runner/stack core; core suite vẫn chạy khi Leta tắt. Không paid-provider CI, stack mỗi case hoặc duplicate E2E matrix.

## 9. Công việc triển khai còn lại

Topology/components/state ownership/config/deploy approach ở trên đã duyệt. [Coverage audit trong plan](plan.md#rà-soát-nội-dung-thảo-luận) phân biệt quyết định mở với việc chưa code/verify; không dùng trạng thái chưa implementation để mở lại kiến trúc đã duyệt.

Các phần domain/runtime/infra ở trên đã duyệt theo [readiness](plan.md#sẵn-sàng-bắt-đầu-sau-lượt-rà-soát). Theo scope mới 2026-11-13, [prompting](prompting.md) có draft để review; OTel/Alloy + Grafana Cloud Free và Langfuse observability/prompt management đã được chốt; evaluation deferred. Thiết kế chi tiết theo owning observability plan; runtime integration đã có code và local export proof. Mirage/cache và retention MVP đã duyệt, future purge/expiry hoãn. Complete HTTP DTO/errors là deliverable trước API từng feature, không blocker cho schema/core/Temporal. Workspace cleanup và owner moves đã chốt, storage visibility mutation đã cắt; backend/shared config integration đã có code và shared API E2E pass. File conflict/retry-horizon policy, operator access và compaction đã chốt; transfer ownership hoãn, không thêm worker housekeeping. Capacity/page/output/compaction thresholds, cache/mount TTLs và Redis suffix caps là defaults/tuning khi implementation, không kiến trúc cần duyệt lại.

Lượt này chỉ ghi thiết kế; không sửa app/core/infra/config/dependencies hoặc dữ liệu. Chưa có Leta integration, load/cost measurements, restore drill hoặc deployment để xác nhận thiết kế vận hành thực tế.
