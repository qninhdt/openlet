# Audit Temporal: Platform, LetFS, ingest và Leta

Ngày 2026-11-12. Read-only source audit + cập nhật plans; không sửa backend/config/dependencies/DB, không chạy server/tests hoặc dùng skills/subagents. Active source được tìm qua CodeGraph trước, đối chiếu registrations/call sites và owning plans; archive không được tính là implementation hiện tại.

## Kết luận

Giữ Temporal và phần lớn thiết kế Leta đã chốt. Không có lý do thay long-running activity bằng workflow từng model/tool, dựng scheduler/recovery framework, hoặc chuyển mọi RPC thành owning activity. RPC trong activity là cách dùng bình thường; vấn đề là owner, retry boundary và việc activity có làm công việc thật hay chỉ chuyển tiếp.

Cần thực hiện [workspace cleanup đã duyệt](../261111-1727-platform-letfs-rewrite/workspace-cleanup.md), sửa retry/recovery cleanup và hoàn thiện maintenance/native core slots. Sau audit, người dùng đã duyệt chuyển cả hai provisioning sites còn lại về LetFS activities theo [design mục 10](../261111-1727-platform-letfs-rewrite/design.md#10-temporal-tối-thiểu), gọi functions trong process, không gRPC chính nó; đồng thời **cắt visibility update**, giữ private/public cố định từ provisioning. Rút đề xuất serialized visibility actor; không còn decision Temporal đang chờ. Active-source inventory bên dưới là snapshot trước implementation, không target sau scope cut.

## 1. Phạm vi đã đọc

- Active Platform: [provisioning.go](../../apps/platform/internal/platform/provisioning.go), [workspaces.go](../../apps/platform/internal/platform/workspaces.go), [main.go](../../apps/platform/cmd/platform/main.go), selected member/onboarding callers.
- Active LetFS: [jobs.go](../../apps/letfs/internal/storage/jobs.go), [access.go](../../apps/letfs/internal/storage/access.go), [administration.go](../../apps/letfs/internal/storage/administration.go), [maintenance.go](../../apps/letfs/internal/storage/maintenance.go), processing stage RPCs và [main.go](../../apps/letfs/cmd/letfs/main.go).
- Ingest: [worker.py](../../apps/letfs-ingest/src/letfs_ingest/worker.py), [parse.py](../../apps/letfs-ingest/src/letfs_ingest/parse.py), [process.py](../../apps/letfs-ingest/src/letfs_ingest/process.py), [artifacts.py](../../apps/letfs-ingest/src/letfs_ingest/artifacts.py).
- Shared: [queue struct](../../packages/sdk-go/connections.go), [bootstrap schedules](../../scripts/bootstrap.py), config plans và dependency pins. Go SDK v1.51.0/API v1.64.3, root uv.lock Python SDK 1.36.0; source audit không phải interoperability test trên những pins này.
- Proposed Leta: [Temporal](../261111-2010-leta-rewrite/temporal.md), [runtime/design](../261111-2010-leta-rewrite/design.md), [system](../261111-2010-leta-rewrite/system.md), [scheduler](../261111-2010-leta-rewrite/scheduler.md), [HITL](../261111-2010-leta-rewrite/hitl.md), [boxes](../261111-2010-leta-rewrite/boxes.md), [boundaries](../261111-2010-leta-rewrite/boundaries.md). apps/leta chưa có implementation mới.

## 2. Toàn bộ workflow/activity inventory

### Active core

| Workflow definition / queue | Registered activities và boundary | Đánh giá |
|---|---|---|
| Platform ProvisionWorkspace / platform | AdmitWorkspace → ProvisionWorkspaceResources → ActivateWorkspace | SQL admission/activate và graph/storage effects có trách nhiệm thật; mixed storage RPC xem mục 3 |
| Platform ProvisionMemberStorage / platform | ProvisionMemberStorageResources | Check current participation, discover owned storage, create nếu cần; ownership có thể chuyển LetFS |
| Platform DeleteWorkspace / platform | DeleteWorkspaceResources | Combined graph + LetFS gRPC + Platform SQL; thay bằng shared direct activities đã duyệt |
| Platform Maintenance / platform | PlatformMaintenance | Expire SQL receipts/invites, dispatch deleting workspace; không recovery failed provisioning tự động |
| LetFS UpdateStorageVisibility / letfs | UpdateStorageVisibilityResources | SQL desired + graph effect, hiện chưa serialize theo storage; finding quyền truy cập ở mục 4 |
| LetFS ProcessBlob / letfs | ParseBlob trên ingest_cpu khi cần → EnrichAndIndex trên ingest_io → ReportProcessingFailure trên letfs nếu lỗi | Orchestration nhỏ, owning stages/idempotency đúng; bounded retries phù hợp expensive model work |
| LetFS Maintenance / letfs | LetFSMaintenance | Expire/recover + S3/Qdrant GC; scan lớn dưới timeout cố định cần hoàn thiện |

Tổng current core: **7 workflow definitions, 11 regular activities** (Platform 6, LetFS Go 3, ingest Python 2), 4 queues. Hai definitions Maintenance dùng cùng wire type name trên queues khác nhau; số trên đếm definitions, không khẳng định 7 unique type names trong namespace. Không có native Local Activity trong Go code hiện tại.

Sau cleanup: Platform thay một combined activity bằng RevokeWorkspaceAccess + DeleteWorkspaceRecord; LetFS thêm DeleteWorkspaceStorage. Bổ sung hai provisioning owner moves: mixed workspace activity thành Platform graph activity + một LetFS storage-batch activity; member-storage activity chuyển worker. Sau đó xóa UpdateStorageVisibility/UpdateStorageVisibilityResources theo quyết định cắt feature. **Target cuối core 6 workflow definitions/13 activities** (Platform 6, LetFS Go 5, ingest Python 2), vẫn 4 queues. Current source 7 definitions/11 activities chưa được sửa ở lượt plan này.

### Target Leta

| Workflow | Activities sử dụng | Giữ/thay đổi |
|---|---|---|
| Agent | admit_input, load_agent_control, finish_run, run_agent | Giữ lazy entity orchestration, long runtime + event-driven CAN |
| LetaLifecycle | prepare_leta, provision_leta, close_leta, cleanup_leta, set_leta_paused, refresh_leta_agents | Giữ finite operations; cleanup functions cũng dùng inline bởi workspace cleanup |
| BoxLifecycle | provision_box → prepare_box; close_box → cleanup_box | Giữ home-first, không placeholder nullable/compensation framework |
| HitlRequest | open_hitl_request, resolve_hitl_request, apply_hitl_outcome, deliver_input | Giữ async decision/effect/delivery, deadline một authority |
| ScheduleChanges | save_schedule_change, apply_native_schedule | Giữ serialized commands, native schedule effect, finalized SQL receipts và CAN |
| ScheduleDelivery | load_schedule_occurrence, deliver_input | Giữ finite occurrence, stable scheduled identity, không đợi inference |
| Platform DeleteWorkspace gọi Leta | delete_workspace_agents, wire DeleteWorkspaceAgents | **Thêm đúng một B activity**, không workflow thứ bảy |

Leta target **6 workflows / 22 activities / 3 queues**. deliver_input là một registered activity dùng chung, không đếm lại theo callers. Local SQL chỉ I/O ngắn trong process, không gRPC/fanout/đợi workflow; E effects, R runtime và B bridges dùng regular activities. Giữ native retries thay custom dispatch/replay.

## 3. Các activity gọi gRPC: cái nào thừa?

Không tìm thấy active business activity chỉ có một dòng forwarding sang service khác rồi trả result. Có **ba mixed sites Platform → LetFS** đáng xem; không gọi sai tất cả là proxy thuần túy:

| Site | Công việc hiện tại | Hướng xử lý |
|---|---|---|
| provisioning.go:116 provisionWorkspaceResources | Ghi workspace.owner; ProvisionWorkspaceStorage; CreateStorage shared/private; trả consistency token | Đã duyệt: Platform graph activity riêng, một LetFS ProvisionInitialStorages activity cho budget + cả storage batch; gọi native functions trực tiếp, không gRPC chính nó hoặc activity từng RPC |
| provisioning.go:140 provisionMemberStorage | Current participation check; public ListStorages theo user, owned-only; internal CreateStorage | Đã duyệt chuyển implementation ProvisionMemberStorageResources sang LetFS worker, gồm checks/discover/create bằng functions trong process. Platform giữ workflow sau membership admission; không forwarding wrapper, unique owner→storage hoặc personal mapping |
| provisioning.go:172 deleteWorkspaceResources | Revoke workspace graph; gRPC DeleteWorkspaceStorage; DELETE workspace SQL | **Đã duyệt thay**: Platform giữ hai local owning effects, trực tiếp dispatch owning LetFS/Leta cleanup activities |

Các RPC nên giữ:

- ParseBlob download/parse subprocess/publish artifacts; EnrichAndIndex chạy model/embedding/index rồi commit qua LetFS. RPC là datastore-authority boundary, activity làm công việc thật. Chuyển commits thành activities khác làm pipeline dài hơn và chia mất stage boundary.
- ReportProcessingFailure gọi s.FailProcessing **cùng process**, không network gRPC proxy. Không cần tách hoặc nhân đôi failure reporter.
- Planned provision_leta cần check workspace, agent graph writes, create home storage rồi activate local root. apply_hitl_outcome kiểm current rights/liveness, gọi owning grant API và lưu actual outcome. Đây là multi-store effect có domain semantics, không forwarding dư thừa.
- File/model/tool effects ở runtime không tự tạo activity/workflow cho từng RPC. Long runtime + native saver + owner receipts đã giải quyết recovery ở granularity đã chốt.

[Temporal versioning guidance](https://docs.temporal.io/develop/go/workflows/versioning) đặt network/DB work trong activities. Direct cross-owner activities là lựa chọn hợp lý cho cleanup trong cùng namespace; nó tạo shared payload/name/queue contract, không tự động tốt hơn gRPC ở mọi boundary. Chưa cần Nexus hoặc activity protocol framework.

## 4. Findings cần xử lý

### Visibility ordering: đã chốt cắt feature, không triển khai cơ chế mới

Evidence: access.go:125 đặt workflow ID theo request_id/hash, không theo storage; jobs.go:49–60 ghi SQL rồi gọi graph bằng giá trị snapshot riêng của mỗi activity. Hai executions cùng storage có thể xen kẽ:

```text
A: SQL visibility=public
B: SQL visibility=private
B: graph DELETE public_workspace, thành công
A: graph TOUCH public_workspace, thành công
=> SQL private, graph public
```

Đây là permission exposure trong workspace, không rare cosmetic edge. Nếu graph lỗi đủ 10 retries, SQL/graph cũng có thể lệch lâu dài mà workflow đã FAILED. Native retry **không serialize các workflows khác nhau** và không biến SQL+graph atomic.

Quyết định mới của người dùng: chưa cần API đổi visibility, **xóa feature trong thiết kế đích**. UpdateStorage chỉ rename; xóa request fields/CEL, workflow/activity/registrations/generated/callers và tests chỉ phục vụ mutation này. Giữ visibility lúc provisioning, read/list filter và direct grants. Đề xuất native Updates actor hoặc revision/CAS đã rút, không còn decision mở về ordering. Source hiện tại còn code lỗi cho đến khi thực hiện removal.

Verification cho removal: contract/handler không còn nhận đổi visibility, workflow/activity không còn đăng ký; public/private provisioning và direct grants vẫn đúng. Không giữ concurrency tests của feature đã cắt hoặc thêm compatibility wrapper để giữ test xanh.

### Vừa: cleanup retry hết nhưng maintenance không restart được failed workflow

Evidence: provisioning.go:49–50 dùng MaximumAttempts=10; DeleteWorkspace trả activity error; maintenance:208 start cùng ID với USE_EXISTING + REJECT_DUPLICATE, không workflow retry policy. USE_EXISTING xử lý execution đang mở; REJECT_DUPLICATE chặn ID của closed execution, kể cả FAILED, theo [API enums đúng version đang dùng](https://github.com/temporalio/api/blob/v1.64.3/temporal/api/enums/v1/workflow.proto).

Hậu quả: workspace có thể kẹt deleting sau dependency outage, scheduled recovery chỉ gặp duplicate; không tự hồi phục khi dependency quay lại. Cleanup mới giữ transient activity retry dài, không dùng low attempt cap hoặc total lifetime timeout. Invalid input/permanent failures vẫn phải hiện lỗi; operator recovery cho histories đã failed. Đây đã ghi trong approved cleanup implementation work, không thêm retry scheduler.

Failed provisioning hiện cũng không được maintenance tự recovery. Source plan cũ nói recover provisioning là quá lời; đã sửa description. Giữ provisioning failure rõ + native operator retry/delete theo quyết định cũ, không tự đổi thành retry vô hạn cho mọi flow.

### Vừa: maintenance scan có thể hết 5 phút trước khi tới phần cuối

Evidence: jobs.go:95–96 đặt LetFSMaintenance StartToClose=5 phút, attempts=1; maintenance.go:79–173 scan toàn S3 objects rồi toàn Qdrant collection theo pages, chưa RecordHeartbeat. Native Schedule SKIP ngăn overlap executions bình thường; không giúp scan hoàn tất nếu mỗi lượt đều timeout ở nửa đầu. Timeout cũng không chứng minh old attempt đã ngừng side effects.

Chưa có đo thực tế vượt 5 phút: đây là growth limit từ source, không claim incident đang xảy ra. Bước nhỏ trước: heartbeat/cancellation checks theo pages và đặt attempt timeout hợp workload/maintenance cadence; giữ provider pagination và native Schedule. Đo đủ một scan ở dữ liệu dự kiến trước deploy. Chỉ thêm continuation cursor/break thành activities khi phép đo chứng minh cần; không tự tạo GC framework/table hoặc workflow từng object/vector.

### Vừa: Go workers chưa giới hạn activity concurrency theo host/DB

Evidence: Platform main và LetFS main tạo worker.Options chỉ với WorkerStopTimeout; không có native max activity slots. Ingest đã đặt max_concurrent_activities từ config; Leta target có ba pools nhưng chưa concrete budgets. Khi burst uploads/visibility/cleanup, default core slots có thể dồn áp lực lên SQL/graph/provider dù số replicas nhỏ.

Hướng nhỏ: đặt native activity concurrency ở owning Go workers phù hợp pool/host, đo queue latency/pool wait; không tự thêm queues, autoscaler hoặc distributed semaphore. Không cần override mọi SDK option. Đây là tuning implementation, không thay service model. [Worker guidance](https://docs.temporal.io/best-practices/worker) hỗ trợ giới hạn/tách workload theo tài nguyên thật.

### Deployment gate: thay command sequence phải tôn trọng open histories

Chuyển DeleteWorkspace từ một activity thành nhiều activities làm đổi replay command sequence. Trước rollout kiểm open histories; native GetVersion/patch + một replay check nếu còn executions cũ, hoặc deploy thẳng khi đã xác minh không còn. Không tự reset namespace đang dùng. Native patch bảo vệ jobs thật đang chạy; không compatibility wrapper giữ test cũ.

Leta fresh namespace giải quyết cutover lần đầu, **không** giải quyết mọi deployment trong các năm agent tiếp tục chạy. Những lần sau cần cùng native patch discipline; CAN không làm code changes tự an toàn cho run đang mở. [Official Go versioning](https://docs.temporal.io/develop/go/workflows/versioning).

## 5. Thiết kế nào đã đúng và nên giữ?

| Tiêu chí | Evidence / kết luận |
|---|---|
| Workflow determinism | Active workflows chỉ ExecuteActivity/branch theo input; queues/timeouts đã đưa vào ProcessInput, không direct DB/provider calls. Proposed Leta giữ cùng boundary |
| Long-running agent | Model/tool loop bên trong activity, heartbeat độc lập; inbox/cancel/control tạo workflow events. Không model/token/heartbeat history event mỗi vòng; giữ rollover tại workflow events |
| Continue-As-New | Agent/ScheduleChanges dùng native suggestion, main drain handlers trước CAN; không CAN trong Update handler. Phù hợp [entity workflow pattern](https://docs.temporal.io/design-patterns/entity-workflow) |
| Cancellation | Leta WAIT_CANCELLATION_COMPLETED + shield bước tới durable boundary, await task thực sự/nhả writer lock. Không TRY_CANCEL/ABANDON làm proof writer đã dừng; cần integration test khi viết app |
| Slots và deadlock | Target orchestration/runtime/bridge tách native pools; B không chờ queued B. Workspace cleanup gọi concrete root/box functions inline; không thêm một service |
| Activity timeouts | Runtime heartbeat + per-model/tool deadlines, attempt timeout riêng; không lifetime timeout của logical agent. Long activities cần heartbeat để nhận cancellation theo [failure detection](https://docs.temporal.io/encyclopedia/detecting-activity-failures) |
| Native Local Activities | Leta chỉ dùng cho short SQL, regular E/B/R cho remote/long work. Không máy móc đổi mọi Go SQL activity thành Local chỉ để giảm history hữu hạn |
| Idempotency | Stable workflow/resource/message IDs; core receipts/stage commits; cross-CAN receipt không dùng processed-ID bag. Không global exactly-once claim |
| Retry/cost | Ingest attempts=3 và manual native failed-run recovery là giới hạn có chủ ý. Runtime transient retry dài nhưng permanent model/config lỗi dừng lượt; file effects quá receipt horizon không blindly replay |
| Payload sizes | Core processing IDs/version/queue/options nhỏ; artifacts/signed URLs/body qua owning APIs, không history. Leta bounded commands/results, không transcript/file bytes/secrets |
| Schedules | Native maintenance SKIP; Leta BUFFER_ONE cho finite delivery, không inference. Stable nominal occurrence identity/dedupe; không polling scheduler |
| Python async worker | Parser chạy subprocess có deadline/terminate/kill; heartbeat riêng, async network. Không thấy CPU parse trực tiếp block worker event loop trong path đã đọc |
| Shutdown | Native worker stop/graceful_shutdown_timeout, signal handling và client close hiện có. Grace must fit bounded tool/model settlement; một VPS không HA là scope đã chốt |
| State ownership | SQL domain/UI, native saver context/progress, Temporal ordering/retries, Redis provisional; không thêm run progress mirrors/replay journals |

## 6. Thứ tự làm tối thiểu

1. Implement approved workspace cleanup end-to-end ở core + Leta + shared queues/JSON, sửa cleanup retry cùng lượt. Reuse một shared integration environment; kiểm offline/restart và partial failure, không toàn CI suite lặp theo case.
2. Xóa visibility update theo quyết định đã chốt; giữ provisioning/read/filter/grants. Không thay bằng actor/lock/revision mới.
3. Add heartbeat/timeout phù hợp maintenance và native core activity slots; đo một scan và burst nhỏ. Chưa thêm cursor/sharding/platform HA khi chưa có evidence.
4. Khi viết Leta, một focused integration kiểm busy Agent CAN + inbox/control + checkpoint/writer release; một shared journey phủ root/box/HITL/schedule/delete. Compaction đã chốt, không đòi duyệt lại hoặc dựng suite cho mỗi helper.

Không cần mở lại toàn bộ Temporal architecture. Cả hai provisioning owner moves và cắt visibility mutation đã được người dùng duyệt; triển khai cùng lifecycle changes tại design mục 10, không gọi gRPC chính owning service. Không blanket cấm gRPC trong activity; không còn Temporal decision phải chốt trước implementation.

## 7. Giới hạn bằng chứng

Đã audit tất cả active workflow/activity registration sites trong Platform/LetFS/ingest và toàn target Leta inventory. Kết luận lỗi ordering/retry dựa source và Temporal semantics; **chưa runtime-reproduce** race/outage, replay open histories, đo scan/slots hoặc chạy Go↔Python cleanup smoke. Không khởi động background processes hay sửa dữ liệu. Existing E2E/telemetry proofs trong core plan là bằng chứng lịch sử, không proof cho cleanup contract mới.
