# Workspace cleanup qua owning Temporal activities

Đã được người dùng duyệt ngày 2026-11-12; **chưa implementation**. Đây là thay đổi cần làm ở backend Platform/LetFS đang có và [Leta viết mới](../261111-2010-leta-rewrite/temporal.md). Thay đường Platform activity → LetFS gRPC trong DeleteWorkspace; không đổi public DeleteWorkspace admission hoặc schema.

## Ownership và thứ tự

Platform giữ workflow `DeleteWorkspace`, ID `delete-workspace/{workspace_id}`. Public API vẫn authorize, ghi `state=deleting`, start/attach workflow rồi trả admission. Workflow gọi regular activities trực tiếp trên owning queues:

| Activity wire name | Worker / queue mapping | Công việc thật |
|---|---|---|
| `RevokeWorkspaceAccess` | Platform / `platform` | Xóa workspace graph relationships như teardown hiện tại |
| `DeleteWorkspaceStorage` | LetFS / `letfs` | Dọn storage graph và workspace_storage; native SQL cascades dọn metadata |
| `DeleteWorkspaceAgents` | Leta / `leta_bridge` | Đóng gates, settle producers/HITL/runners, dọn schedules/agent relations và archive local roots/boxes |
| `DeleteWorkspaceRecord` | Platform / `platform` | DELETE workspace SQL khi storage cleanup đã ACK |

```text
RevokeWorkspaceAccess
  ├─ start DeleteWorkspaceStorage trên LetFS queue
  └─ start DeleteWorkspaceAgents trên Leta bridge queue

khi storage activity thành công → DeleteWorkspaceRecord
workflow tiếp tục đợi agents activity → kết thúc sau khi các futures đã settle
```

Hai cleanup activities được schedule trước khi await. Xóa Platform SQL **không đợi Leta**. Không return workflow khi còn bỏ rơi một cleanup future; nếu activity có terminal error, lưu lỗi, vẫn observe nhánh còn lại và chỉ trả lỗi sau khi nhánh đó settle. Khi LetFS lỗi thì không xóa workspace SQL. Không coi ACCEPTED/queued là resource cleanup đã xong.

Leta tắt hoặc chưa deploy: activity ở queue, không giữ RPC connection hoặc block quyền/storage/Platform SQL. Workflow vẫn RUNNING chờ cleanup Leta; đây là lifecycle đã chọn, khác thời điểm workspace biến mất khỏi API/SQL. Không thêm feature flag, polling, resource registry hoặc deadline làm mất cleanup đã enqueue. Core startup/readiness/CRUD không cần Leta process/Redis/provider credentials.

## Shared contract tối thiểu

- Cùng Temporal namespace và native JSON data converter. Mỗi activity trên nhận **một JSON object** `{"workspace_id":"<uuid>"}`; Go struct có JSON tag `workspace_id`, Python nhận cùng shape. Result là JSON null sau completion, không DTO/protobuf generated object xuyên Go/Python.
- Chỉ các activity wire names/input/queue mappings ở đây là shared contract. Platform không gọi private Leta workflows, đọc SQL/thread/box hoặc import implementation Python. Queue không là API discovery hoặc security boundary.
- Thêm `dependencies.temporal.queues.leta_bridge` cùng các queue mappings hiện có; đồng bộ Go Queues struct, Python owner và YAML mẫu/test/deploy. Platform lấy routing names trước khi start workflow, đưa queue names tối thiểu vào immutable workflow input. Workflow không đọc config/ENV.
- Bridge name là non-secret routing config của Platform; core không validate toàn bộ services.leta/models.leta hoặc đòi Leta chạy. Không thêm application gRPC listener/cleanup proxy chỉ cho đường này.
- Shared names/payload phải được registration/startup và một Go → Go/Python smoke kiểm; không codegen protocol hoặc compatibility aliases mới.

## LetFS thực thi

Đăng ký regular activity trên LetFS worker hiện có. Activity gọi **cùng concrete cleanup function trong process** với internal DeleteWorkspaceStorage handler nếu RPC còn caller; không gọi gRPC vào chính mình. Rà callers rồi xóa RPC nếu không còn nhu cầu, không giữ wrapper chỉ để giữ test cũ.

Giữ semantics hiện tại: tất cả storages có workspace_id, kể cả agent-owned, được dọn graph; DELETE workspace_storage cascade storages/nodes/files/processing/trash/uploads. S3/Qdrant physical GC do maintenance sẵn có; activity ACK không đồng nghĩa mọi bytes/vectors đã biến mất. Object grace hiện dựa LastModified của object, không cam kết chờ đủ 24h kể từ lúc xóa workspace.

## Leta thực thi

Thêm đúng **một regular bridge activity**, Python function `delete_workspace_agents` đăng ký wire name `DeleteWorkspaceAgents`. Inventory Leta thành **6 workflows / 22 activities / 3 queues**; không workspace workflow hoặc housekeeping mới.

Activity query roots theo workspace_id theo batches, đóng root gates rồi dùng concrete root/box cleanup functions **inline**. Settle đã-admit provisioning, schedules, HITL effects và runtime writers như root delete; dọn hai chiều agent.workspace/workspace.agent bằng native graph operations; archive rows theo policy đã có. Không schedule cleanup B activity khác hoặc join BoxDelete trên cùng bridge pool.

Workspace/storage đã bị core thu hồi/xóa là outcome dự kiến của đường teardown này. Home đã mất hoặc không còn quyền trash thì bỏ bước LetFS đó; HITL grant không thể áp dụng phải lưu actual failed/skipped outcome thay vì retry permission denied mãi. Vẫn settle producer/writer barriers và local graph/schedule cleanup; không skip mọi lỗi dependency. Không tạo lại home, grant hoặc workspace relationships trong cleanup. Không chờ core SQL còn tồn tại để dọn local data.

Retention Leta MVP đã chốt: giữ durable inbox/public history/archived resource records, không auto-purge hoặc thêm purge job. Delete vẫn teardown/archive, native checkpoint keep_latest tiếp tục; future physical purge/expiry hoãn. Quyết định này không đổi LetFS trash/blob GC hoặc native Redis/Temporal/receipt retention.

## Retry, timeout và rollout

Cleanup là idempotent deletion; transient DB/graph/Temporal errors dùng native backoff, **không MaximumAttempts=10 hoặc total ScheduleToClose/lifetime timeout** làm hỏng trường hợp Leta offline dài. StartToClose hữu hạn theo attempt; cleanup dài heartbeat theo batch/khi chờ, activity cancellation cooperative. Missing resource là successful deletion; invalid shared input là nonretryable và phải hiện lỗi vận hành. Không custom retry loop/lease/ledger.

DeleteWorkspace hiện dùng retry tối đa 10 lần trong activityContext, rồi maintenance start cùng ID với REJECT_DUPLICATE. Workflow đã FAILED không được policy đó mở lại. Đổi riêng cleanup sang transient retry dài; không tự đổi mọi provisioning/ingest thành retry vô hạn. Workflow đã FAILED trước rollout cần operator native reset/recovery; SQL maintenance không là recovery guarantee cho failed history hiện tại.

Đổi command sequence của DeleteWorkspace phải tương thích histories còn mở: trước deploy kiểm open executions, dùng native workflow.GetVersion cho nhánh mới nếu còn histories cũ; nếu xác minh không còn open histories thì triển khai trực tiếp. Fresh namespace chỉ áp dụng cutover đã duyệt, không tự reset Temporal đang dùng. Không xây worker-versioning platform riêng.

## Phạm vi backend cần sửa

| Owner | Files/surfaces | Thay đổi |
|---|---|---|
| Platform | `internal/platform/provisioning.go`, `workspaces.go`, `server.go`, `cmd/platform/main.go` | Tách combined deletion activity, hai futures/queue routing, cleanup retry và replay-compatible rollout; public admission giữ nguyên |
| LetFS | `internal/storage/jobs.go`, `administration.go` | Đăng ký owning activity, dùng concrete cleanup function, rà heartbeat/idempotent deletion |
| Shared config | `packages/sdk-go/connections.go`, owning Python settings, plan/active YAML/test config | Đồng bộ leta_bridge và minimal workflow input; không credentials/readiness mới |
| Leta | New feature cleanup function + `jobs`/worker registration theo design | Một workspace bridge activity, reuse root/box cleanup inline |
| Validation | Affected workflow tests + shared integration journey | Thay assertions gắn forwarding RPC; không giữ old tests bằng wrapper |

Focused acceptance: (1) queue names/JSON Go-Python khớp; (2) Leta offline, access/storage/Platform SQL vẫn bị xóa còn workflow pending; bật worker lại thì agents cleanup hoàn tất; (3) retry sau partial cleanup không tạo lại resource/duplicate effects; (4) terminal error một nhánh không bỏ pending future, LetFS failure không xóa SQL; (5) một replay history nếu rollout giữ open workflows. Reuse một shared dependency environment, không spin stack cho từng case.

Chưa sửa backend/config/DB hoặc chạy các acceptance trên ở lượt cập nhật plan này. [Audit Temporal toàn hệ thống](../reports/audit-261112-temporal-workflows-activities.md) phân biệt approved change với các đề xuất khác.
