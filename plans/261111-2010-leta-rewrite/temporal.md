# Temporal cho Leta viết mới — thiết kế cuối

Đã reconcile boundary/schema ngày 2026-11-12 theo [workspace resources](../261111-1727-platform-letfs-rewrite/workspace-service-redesign.md) và [API core](../261111-1727-platform-letfs-rewrite/api-contract.md). Root là agent subject, giữ workspace_id/storage_id, ownership ở graph. Sáu workflow types/22 activities/ba queues; thêm duy nhất workspace cleanup activity đã chốt. SQL 11 bảng không đổi. HITL type/status là columns, pending schedule command thuộc Temporal và finalized receipt theo schema core. [HTTP JSON/SSE](streaming.md) đã chốt; dynamic external mounts giữ lại. [Workspace cleanup](../261111-1727-platform-letfs-rewrite/workspace-cleanup.md) thay phần integration còn mở trước đây; không core stop/readiness/hot-path dependency.

Ngày 2026-11-11. Đề xuất kiến trúc, chưa implementation. Thay thế bản Temporal trước trong cùng plan. Không dùng skill/subagent, không sửa runtime hoặc copy implementation/tests cũ. [Kiến trúc Leta](design.md), [plan và acceptance](plan.md).

Yêu cầu đã chốt thêm: Leta/Leti có thể hoạt động liên tục 24/7 nhiều tháng, nhiều năm, kể cả luôn có việc. Không cần manual restart/reset để tránh history/context tăng. Logical agent giữ identity và context qua nhiều workflow runs và runtime activities.

[Schema chi tiết](schema.md) và [DDL review](schema.sql) xác định physical fields. Các state snapshots/status trong workflow/API bên dưới có thể là SQL projections, không mặc định là columns riêng.

## 1. Quyết định

Giữ Temporal và sáu workflow types. Phân chia nghiệp vụ cấp cao còn giống hệ thống hiện tại; phần viết lại là state ownership, đường admission, lifecycle hữu hạn và cách thực thi effects. Không gọi việc giữ nguyên sáu tên workflow là một kiến trúc hoàn toàn khác.

Vấn đề đã xác minh là nhiều nơi cùng giữ execution progress, ordinary CRUD đi vòng qua lifecycle coordinator, và application tự dựng replay/recovery ngoài thư viện. Temporal cùng LangGraph không tự nó là overengineering. Không bỏ một coordinator đang giải quyết ordering thật rồi thay bằng lock/outbox/scheduler tự chế.

| Type               | ID                                                                       | Vòng đời và trách nhiệm                                                          |
| ------------------ | ------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| `Agent`            | `agent/{agent_id}`                                                       | Lazy, sống khi agent còn hoạt động; admission, wake, dispatch runtime và control |
| `LetaLifecycle`    | `leta/{id}/create`, `leta/{id}/delete`, `leta/{id}/control/{request_id}` | Một create/delete/pause/resume operation rồi kết thúc                            |
| `BoxLifecycle`     | `box/{id}/create`, `box/{id}/delete`                                     | Một create/delete operation rồi kết thúc                                         |
| `HitlRequest`      | `hitl/{request_id}`                                                      | Open → decision/deadline → effect → result delivery rồi kết thúc                 |
| `ScheduleChanges`  | `schedule-changes/{schedule_id}`                                         | Serialize edits của một schedule; kết thúc khi delete                            |
| `ScheduleDelivery` | Native Schedule sinh execution ID                                        | Một occurrence, giao input rồi kết thúc; không đợi inference                     |

Native Schedule ID: `schedule/{schedule_id}`. Không có workflow cho từng message, model call, tool, file mutation, agent metadata PATCH hoặc SSE event.

## 2. State thuộc về đâu

| Owner                       | State                                                                                                                                                                |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PostgreSQL                  | Resource lifecycle, desired pause, inbox, public history, UI run status, HITL decision/outcome, schedule definitions, mutation receipts                              |
| Native LangGraph saver      | Working messages/summary, inbox cursor, pending tasks/interrupts và continuation                                                                                     |
| Temporal                    | Command ordering, wake/dispatch, activity/timer progress, durable retries                                                                                            |
| Native Schedule             | Timing, timezone, overlap/catchup và occurrence start                                                                                                                |
| Redis                       | Provisional events và cache; không recovery authority                                                                                                                |
| SpiceDB theo owning service | Agent owner/operator và hai chiều agent.workspace/workspace.agent do Leta; workspace/membership do Platform; storage/grants do LetFS. Không SQL owner/binding mirror |
| LetFS                       | Storage/tree/content/version/workspace quota và native mutation idempotency                                                                                          |

Xóa khỏi SQL `runs` và Agent workflow: checkpoint ID/namespace, continuation,
runtime attempt, yield flag và result snapshot. Checkpoint sở hữu inbox cursor;
F04 đã chốt cho workflow giữ admitted seq/returned cursor chỉ để reconcile inbox
wake, không runtime continuation mirror. `runs` chỉ là product status/correlation;
runtime đọc checkpoint để biết việc cần làm. Không custom tool-result replay
journal hoặc heartbeat chứa transcript.

## 3. Activity inventory và worker

`L` = native Local Activity, chỉ SQL ngắn. `E` = regular effect Activity, không chờ Leta workflow khác. `B` = regular bridge Activity, được gọi Temporal Client để chờ Updates/results. `R` = runtime Activity.

| #   | Activity                                                 | Loại | Trách nhiệm                                                                                                                                                                                 |
| --- | -------------------------------------------------------- | ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `admit_input`                                            | L    | Validate route/source/liveness; transaction dedupe, cấp recipient seq, INSERT inbox                                                                                                         |
| 2   | `load_agent_control`                                     | L    | Đọc active/desired pause và unfinished UI run ID; không checkpoint                                                                                                                          |
| 3   | `finish_run`                                             | L    | Ghi terminal/pause UI status nếu runtime đã mở run; technical rollover không kết thúc logical run                                                                                           |
| 4   | `run_agent`                                              | R    | Activity chạy dài, heartbeat/writer lock; model/tools/inbox middleware/checkpoints/history và native pruning                                                                                |
| 5   | `deliver_input`                                          | B    | Update-with-Start recipient; trả committed receipt hoặc inactive skip                                                                                                                       |
| 6   | `prepare_leta`                                           | L    | Canonical root/storage/storage-root IDs, letas + root agents rows và admitted creation receipt                                                                                              |
| 7   | `provision_leta`                                         | E    | Generic Platform CheckWorkspaceActive, native agent graph batch gồm hai chiều workspace binding, LetFS CreateStorage với saved ordinary UUID rồi conditional activate; không EnsureLetaHome |
| 8   | `close_leta`                                             | L    | Đóng root admission bằng SQL trước teardown                                                                                                                                                 |
| 9   | `cleanup_leta`                                           | B    | Settle producers/grants/runners, trash box homes, cleanup access, archive                                                                                                                   |
| 10  | `set_leta_paused`                                        | L    | Desired pause assignment có request receipt                                                                                                                                                 |
| 11  | `refresh_leta_agents`                                    | B    | Notify existing agents đọc current control; không chờ inference                                                                                                                             |
| 12  | `prepare_box`                                            | L    | Sau home provision: atomic active box/Leti/edges và finalized creation receipt với home_node_id thật                                                                                        |
| 13  | `provision_box`                                          | E    | Chạy trước prepare_box: native CreateDirectories stable path, trả home_node_id; không ghi SQL box placeholder                                                                               |
| 14  | `close_box`                                              | L    | Đóng admission của box                                                                                                                                                                      |
| 15  | `cleanup_box`                                            | B    | Settle box producers/grants/runners, trash home, archive                                                                                                                                    |
| 16  | `open_hitl_request`                                      | E    | Kiểm explicit addressed user/current workspace participation, approval thêm storage rights; persist canonical pending hoặc already_granted                                                  |
| 17  | `resolve_hitl_request`                                   | L    | Authorized CAS status=pending, ghi terminal status/response/resolved_at cùng transaction                                                                                                    |
| 18  | `apply_hitl_outcome`                                     | E    | Grant nếu cần, persist actual outcome; không inbox delivery                                                                                                                                 |
| 19  | `save_schedule_change`                                   | L    | Check finalized receipt/hash; lưu canonical desired definition; metadata-only finalize receipt cùng SQL                                                                                     |
| 20  | `apply_native_schedule`                                  | E    | Apply canonical native effect, sau ACK ghi finalized bytea receipt trong transaction ngắn                                                                                                   |
| 21  | `load_schedule_occurrence`                               | L    | Current SQL source/target/content → bounded input hoặc skip                                                                                                                                 |
| 22  | `delete_workspace_agents` / wire `DeleteWorkspaceAgents` | B    | Platform dispatch; đóng gates và cleanup roots/boxes inline theo workspace, không đợi queued B activity                                                                                     |

Activities đặt cạnh owning feature functions; đăng ký trực tiếp. Feature function dùng concrete clients/pool, không repository interface hoặc dispatcher framework. SQL lookup nhỏ bên trong một effect không cần activity riêng.

Ba native task queues, ba Worker instances trong **một worker process/deployment**:

| Queue                  | Chạy gì                                     |
| ---------------------- | ------------------------------------------- |
| `openlet-leta`         | Tất cả workflows, Local SQL và E activities |
| `openlet-leta-runtime` | `run_agent`                                 |
| `openlet-leta-bridge`  | B activities                                |

Đây là phân tách slot để tránh vòng đợi thật: runtime tool có thể đợi lifecycle cleanup; cleanup có thể đợi Agent/HITL/Schedule Updates; các Updates đó cần effect activities chạy được. E activities không chờ Leta workflows. B activities không đợi một B activity khác phải chạy để mình hoàn tất. Không slot-reservation framework hoặc service/container mới.

Cross-workflow Updates dùng native Client **trong activity**; workflow Python không gửi Update trực tiếp sang workflow khác. Tool đang ở runtime activity gọi cùng feature/client function, không tạo thêm activity lồng nhau.

## 4. Admission chung

HTTP/tool cung cấp stable operation/message identity. SQL resource IDs và mutation receipts quyết định business idempotency; Temporal retention không thay thế chúng. Payloads trong history chỉ IDs, bounded command/message fields và results nhỏ; không file bytes, secrets hoặc transcript.

`Agent.receive`, lifecycle `open`, HITL `open`, schedule `change` dùng native Update-with-Start. Update **COMPLETED sau activity SQL commit** mới là domain ACK; ACCEPTED chưa phải message/resource đã lưu.

Lifecycle `open` thông thường chỉ prepare/close/control SQL rồi cho main tiếp tục. Box create là ngoại lệ home-first: open chờ provision_box E rồi prepare_box L, trả active sau SQL commit; pending creation chỉ ở Temporal, không SQL box placeholder. Root create/delete API vẫn có thể trả provisioning/deleting sau admission; tool cần resource sẵn sàng thì chờ workflow result. Không private stop callback cho Platform. HTTP disconnect không cancel durable operation.

Finite operation IDs gắn canonical resource và operation; duplicate completed operation đọc result/state, không tạo resource mới. Lifetime Agent/ScheduleChanges dùng existing execution khi đang chạy. Root/box gates và tombstones chặn tái tạo resource đã đóng.

Liveness và mutation phải nằm cùng transaction có khóa gate phù hợp: root → box → recipient/resource. Close lấy cùng gate, để không có admission mới commit qua điểm đóng. Inbox seq cấp theo recipient trong transaction INSERT; không dùng global sequence làm committed high-water.

## 5. Agent

### State và Updates

Giữ control wake, admitted seq/returned cursor cho inbox wake, cached paused,
stopping, rotating, active runtime handle/run ID và completion của lượt đang
cancel. Đây là scheduling state, không native graph state.

| Update                 | Xử lý                                                                                                                | ACK                                                      |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| receive                | admit_input; cập nhật admitted seq bằng max, wake inbox nếu mới hơn returned cursor; kiểm native rollover suggestion | Input đã lưu, không đợi model                            |
| refresh_control        | Lock ngắn quanh load_agent_control/cache; resume đặt wake=true; kiểm native suggestion                               | Đã đọc desired control mới nhất                          |
| cancel_current(run_id) | Cancel đúng invocation được nhắm tới, bỏ wake cũ, chờ settle                                                         | User cancellation đã xử lý; không rollback effects       |
| stop                   | Latch stopping, main settle active invocation bằng native cancellation, chờ stopped                                  | Không dispatch thêm; cleanup còn xác nhận writer barrier |

Không giữ handler lock qua inference, fanout, stop hoặc inbox delivery. Cancellation chỉ gửi một lần cho active handle; concurrent controls chờ cùng completion. Explicit user cancel/stop giữ ý nghĩa domain; technical rotation không tự ghi UI run cancelled.

### Main loop

```text
bootstrap control; wake = true
lặp:
  chờ stopping hoặc ((control wake hoặc inbox wake) và không paused) hoặc native rotation suggestion
  nếu native suggestion: rotating = true
  nếu rotating:
    đóng receive admission; settle active invocation nếu có
    chờ all_handlers_finished
    nếu stopping: break
    Continue-As-New chỉ với IDs
  nếu stopping: break

  clear control wake và đánh dấu dispatch inbox wake hiện tại
  trong control lock ngắn: đọc control/cập nhật cache trước dispatch
  nếu inactive: stopping = true; continue
  nếu paused: cache paused; continue

  chọn unfinished UI run ID hoặc candidate ID mới
  active = start run_agent trên runtime queue
  chờ active.done hoặc stopping hoặc rotating/native suggestion
  nếu native suggestion: rotating = true
  nếu stopping hoặc rotating:
    native cancel active đúng một lần; chờ cancellation/completion thực sự
    bỏ active handle; không finish_run(cancelled) chỉ vì rotation
    nếu stopping: break
    continue
  xử lý status + returned inbox cursor; reconcile inbox wake đã được current activity nhận
  xử lý explicit user cancellation và finish_run tương ứng
  bỏ active handle

stopped = true
chờ all_handlers_finished
return
```

Các điều kiện được đánh thức bởi workflow task/message/activity events, không timer polling. Kiểm native suggestion tại receive/control và activity completion; workflow đang await activity vẫn xử lý Updates và quan sát suggestion mới. Không Continue-As-New trong Update handler; main thực hiện sau khi handlers đã xong. Mọi receive Update có thể tăng history dù runtime đang chạy; các vòng model/tools và từng heartbeat không tạo workflow-history event riêng cho từng vòng/nhịp.

Đặt stopped trước khi đợi handlers vì stop handler đang đợi stopped. F04 thay
quyết định chấp nhận empty inbox invocation: admission seq so với durable cursor
trả từ activity, gồm late/out-of-order admission handlers. Không clear inbox wake
vô điều kiện khi activity xong hoặc dùng comparison để xóa control wake. Cancel
vẫn bỏ wake cũ; không tự chạy lại chỉ vì backlog chưa consume. Bootstrap/pre-
dispatch/refresh dùng cùng control lock ngắn để read cũ không ghi đè resume mới;
nhả lock trước runtime/stop wait. Chi tiết ở
[runtime plan](../261114-0035-inference-prompts-compaction/design.md#inbox-wake-handoff-đã-chốt).

Transient runtime/dependency errors dùng native retry/backoff; không làm agent chết sau vài attempts. Permanent model/config/context errors mark lượt failed và cần input/resume hoặc sửa cấu hình; không spin. Input sau cancel đánh thức; input đã lưu còn nguyên tới lần input/resume sau.

### Bên trong run_agent

1. Heartbeat độc lập và giữ PostgreSQL session advisory writer lock theo agent suốt activity. Lock bận trả retryable cho native backoff; không tự poll. Một agent chỉ có một graph writer.
2. Đọc liveness và native saver snapshot. Cursor authority ở checkpoint; activity result trả durable cursor để workflow reconcile wake. Không có graph work/input mới thì return idle, không mở SQL run rỗng. UI run cũ còn mở nhưng checkpoint đã END được finalize, không gọi lại model.
3. Mark UI run running khi thực sự có việc. Thread cố định theo agent; failed UI run không khiến checkpoint hợp lệ bị loại.
4. Middleware abefore_model lấy bounded inbox batch sau checkpoint cursor trước mỗi model call chính. Batch và cursor cùng state update/checkpoint; root nhận inbox notifications, Leti nhận full batch. Inbox mới không cancel bước model/tool hoặc kết thúc activity. Control/model refresh tại safe boundaries; mount discovery refresh lazily theo filesystem.md, không ListStorages trước mỗi file call. Mirage bounded Redis cache/WRITE invalidation không thêm workflow/activity.
5. Native create_agent/saver/summarization chạy model/tools với interrupt_after=["model", "tools"] và durability="sync". Graph/middleware dựng một lần/activity, client reuse; vòng ngoài chỉ điều phối control/resume/durable boundary, không compile lại từng bước. Mỗi boundary: sync checkpoint → hoàn tất public-history projection → native keep_latest prune dưới writer lock → mới resume pending static breakpoint bằng None trên cùng thread. Durable mutations dùng stable IDs/owning receipts; public history upsert stable IDs trong một transaction/boundary, Redis chỉ provisional events. [Optimization/benchmark](../261114-0035-inference-prompts-compaction/design.md#11-runtime-optimization-và-box-context) không thay guarantees này.
6. Activity tiếp tục khi graph còn việc, heartbeat kể cả lúc chờ model/tool. Graph idle thì return; desired pause thì return paused tại boundary. Không soft slice 5 phút, step cap hoặc kiểm Temporal history trong LangGraph. Model/tool calls có deadline riêng.
7. Native cancellation được xử lý cooperative: dùng asyncio.shield bảo vệ bước graph đang chạy; bắt cancellation ở activity boundary và đợi task đó tới sync checkpoint/public projection, không để shield thành orphan task. Không bắt đầu bước mới sau yêu cầu cancel. Settle executions/writes, đóng workspace và nhả writer lock trong finally rồi mới re-raise cancellation. WAIT_CANCELLATION_COMPLETED giữ workflow chờ activity ACK thực sự; không TRY_CANCEL/ABANDON. Không thêm yield RPC/Update, SQL flag hoặc notification service. Bước lỗi trước checkpoint vẫn có thể replay theo guarantee đã chốt; cancellation không rollback effects.

Sau mỗi model/tools boundary đã sync checkpoint và hoàn tất public-history projection, gọi native AsyncPostgresSaver.aprune([thread_id], strategy="keep_latest") trước bước graph tiếp theo; không đợi compaction hoặc activity kết thúc. Pause/idle/cancel cũng settle cùng boundary trước nhả writer lock. Không prune boundary có checkpoint/projection chưa thành công. Giữ latest checkpoint của mỗi namespace cùng pending writes/blobs và native recovery dependencies; graph một namespace thường còn một snapshot ngay sau prune, không phải giới hạn một snapshot toàn thread có subgraphs hoặc một database row. Native saver mặc định vẫn tạo nhiều checkpoints giữa hai lần prune. Không DeltaChannel/time travel, custom saver, SQL xóa bảng nội bộ hoặc retention service. Public history độc lập, không bị prune.

Working messages đã gồm rolling summary + bounded recent tail và được native saver khôi phục cùng cursor/continuation trên stable thread_id; không load toàn public transcript, bảng summary hoặc summary_until để dựng lại context. Native messages channel lưu cả current list khi đổi, channel version không đổi có thể tái dùng blob. Compaction giảm kích thước current context, pruning bỏ snapshots cũ; hai việc không thay thế nhau. Chi tiết tại [kiến trúc runtime](design.md#6-inbox-và-agent-execution); compaction đã chốt, token thresholds là cấu hình/tuning khi implementation, không cần duyệt lại kiến trúc.

Không workflow từng model/tool hoặc SavedToolResults replay layer. Rotation không tạo UI run mới, reset tuổi đời agent hoặc mang continuation blob qua Temporal. Workspace/session tạo lazily và tái sử dụng trong một lần thực thi run_agent, đóng khi activity thoát; không ghi command history hoặc persist shell env qua retry/CAN. Shared clients/pools thuộc worker process. Shell nhiều effects có thể replay; không hứa exactly-once toàn command.

### Rollover khi agent luôn bận

Lazy-start khi receive đầu tiên; provision không start Agent. Fanout refresh/stop bỏ qua workflow chưa tồn tại. Native suggestion xuất hiện: idle thì drain handlers và Continue-As-New; đang chạy thì settle bằng native cancellation theo checkpoint boundary ở trên rồi drain handlers. Không chờ inbox rỗng/graph hết việc, cancel model/tool giữa chừng chỉ vì rotation hoặc chuyển activity còn chạy sang execution mới. Run mới bootstrap wake=true và cùng thread/unfinished logical run.

Plan dùng native suggestion, không counter/threshold engine riêng. Compose pin Temporal Server 1.32.2; repo không override các defaults: history count 4.096 events, history size 4 MiB, hoặc tổng Updates đạt 90% giới hạn 2.000 (khoảng 1.800). Đây là defaults theo source, không xác nhận live server không override. Một message có thể tạo nhiều events. Native flag cũng có thể phản ánh worker-versioning suggestion khi feature đó bật.

Khi native suggestion hoặc rotating=true, receive validator từ chối Updates mới trước ACCEPTED bằng retryable rollover response; caller retry cùng message ID vào workflow ID, không pin Run ID. Accepted handlers drain trước rollover; stop vẫn được xử lý. Không ACK message chưa commit hoặc copy processed-ID set qua CAN.

Không WorkflowExecutionTimeout/WorkflowRunTimeout giới hạn tuổi đời Agent/ScheduleChanges. Technical activity timeout chỉ kết thúc một attempt và native retry phục hồi checkpoint. Worker restart replay orchestration; workflow deploy dùng native patch/versioning. Operator terminate cần native recovery, không poller tự dựng.

## 6. LetaLifecycle

Mỗi execution chỉ nhận một command qua `open`; SQL admission result nhỏ cho main chạy tiếp.

| Operation    | Admission         | Sau admission                                         |
| ------------ | ----------------- | ----------------------------------------------------- |
| create       | `prepare_leta`    | `provision_leta`, return active/superseded            |
| delete       | `close_leta`      | `cleanup_leta`, return archived                       |
| pause/resume | `set_leta_paused` | `refresh_leta_agents`, return current desired control |

### Create

Prepare cấp root/storage/storage-root ordinary UUIDs một lần trong canonical workflow input, lưu letas workspace_id/storage_id/state và root agents profile cùng admitted receipt trong transaction. Storage-root UUID là input LetFS CreateStorage hiện yêu cầu; không thêm SQL root-node mirror. Initial owner là accepted provisioning input, không created_by/owner SQL field. Quyền workspace.create_agent và human role assignment được kiểm tại admission; không đặt membership owner làm điều kiện chạy về sau. Provision gọi generic Platform CheckWorkspaceActive(workspace_id); tự ghi agent.workspace@workspace:W, workspace.agent@agent:A và agent.owner/operators đã được chấp nhận trong cùng native Authzed WriteRelationships batch từ immutable workspace_id. Không RPC/bước/trạng thái registration riêng, không gọi RegisterAgent. Gọi LetFS CreateStorage với same workspace, saved storage ID và StorageOwnership.agent_id=root, visibility private. LetFS materialize owner@agent và agent#owner userset. Sau ACK conditional activate; deleting/archived trả superseded. Không ghi workspace membership/owner hoặc storage relations trực tiếp, không UUIDv5 storage ID hoặc owner snapshots. Workspace check không khóa lifecycle. Concrete public create API vẫn review riêng.

### Pause/resume

Finite operation cần thiết vì SQL rồi best-effort notify có thể bỏ sót child đang paused. Receipt chặn activity retry cũ gán lại pause sau một resume mới. Fanout chỉ gọi existing Agent.refresh_control; handler đọc **current SQL state**, không áp boolean cũ từ notification. Không chờ model kết thúc; pause có hiệu lực tại safe boundary. Metadata/prompt/model PATCH vẫn SQL trực tiếp.

### Delete

Sau khi root gate đã đóng, cleanup chạy concrete feature functions theo thứ tự:

1. Settle root/box provisioning đã admit, để không tạo home sau teardown. Mỗi provision attempt kiểm gate; terminal create failure không cản dọn phần đã tạo. Không coi timeout là bằng chứng producer đã dừng; xác nhận provision critical section đã nhả trước trash.
2. Liệt kê SQL schedules thuộc root, gồm tombstones có thể còn native delete pending; gọi cùng schedule delete path và đợi native ACK. Native delete không hủy delivery workflows đã start, nên admission còn kiểm source gate.
3. Settle HITL effects: cancel pending, đợi accepted/in-flight grant có actual outcome và qua root effect barrier. Không đợi result inbox delivery.
4. Stop existing Agent workflows; xác nhận các runtime writer locks đã nhả. Không dùng activity timeout/ABANDON làm proof writer stopped.
5. Cleanup từng box bằng **cùng concrete cleanup function**, chạy inline trong activity hiện tại. Function chạy deletion-only/idempotent; không schedule B activity mới hoặc đợi BoxDelete workflow.
6. Trash box directories khi còn tồn tại/được phép; giữ SQL history theo local archive đã chốt. Leta xóa agent.workspace và workspace.agent trong cùng native SpiceDB batch khi xóa root, không UnregisterAgent RPC; box delete không sửa binding root. Physical graph/storage purge và transfer ngoài MVP; không tự DeleteStorage từ binding, không blanket revoke quyền human operator, không CleanupLetaAccess hoặc Platform scope grants cũ. Workspace deletion vẫn dọn storages theo shared contract.
7. Archive root/boxes rồi return cho thao tác xóa Leta do người dùng yêu cầu. Shared DeleteWorkspaceAgents cũng dùng concrete cleanup này inline; storage/Platform SQL không đợi Leta, nhưng DeleteWorkspace workflow vẫn observe cleanup future theo mục 12.

Provision giữ session advisory effect lock theo root/box resource quanh critical section; grant dùng cùng root effect lock. Cleanup qua cùng barriers trước trash/access cleanup. Runtime giữ writer lock theo agent. Locks bảo vệ actual producers kể cả activity attempt đã timeout nhưng còn chạy; lock bận dùng native retry, không tự poll. Không SQL phase table/cleanup journal hoặc transaction qua RPC.

Một standalone BoxDelete có thể đang chạy đồng thời. Root cleanup không join nó: cả hai chỉ lặp native idempotent deletions sau gate closure; không bên nào còn được provision. Tránh root cleanup chiếm bridge slot rồi chờ box cleanup đang xếp hàng trên chính pool đó.

Các loops dùng domain state để chạy lại idempotently, heartbeat khi chờ/theo batch; không per-file/agent child workflow, progress cursor hoặc compensation engine. Model tools chỉ root được quản lý boxes; không cho Leti gọi deletion của chính box rồi đợi stop chính invocation đó.

## 7. BoxLifecycle

Home-first đã chốt trong [Box/Leti](boxes.md): native Temporal lưu canonical input/stable IDs trước external effects. open(create) chạy provision_box E bằng LetFS CreateDirectories tại .boxes/<box_id>, nhận home_node_id thật, rồi prepare_box L khóa root gate và ghi active box/children/edges/finalized receipt trong một transaction. Root phải active; không insert nếu gate đã đóng. Giữ home_node_id NOT NULL; box SQL chỉ active/deleting/archived, pending create ở Temporal. Update COMPLETED/resource ACK sau SQL commit; API/tool chờ resource sẵn sàng, disconnect không cancel operation. Graph bất biến, create không gửi việc hoặc start Agent. Crash gap có thể để lại directory rỗng, không thêm orphan ledger/sweeper/compensation framework. Không thêm activity type, core RPC hoặc caller-supplied node ID.

`open(delete)` → `close_box` → `cleanup_box`:

1. Settle box provisioning và qua provision barrier.
2. Delete schedules có creator/target trong box, kể cả root-created schedules target box.
3. Settle HITL effects của children, stop children và qua writer barriers.
4. Native trash home, archive box rồi return.

Root Agent/boxes khác tiếp tục hoạt động. Không revoke root grants đã được duyệt chỉ vì requester box bị xóa; grantee là root Leta. In-flight grant phải settle trước ACK, grant chưa bắt đầu kiểm requester/root liveness và skip nếu đóng.

## 8. HitlRequest

[HITL detail](hitl.md) ghi tool inputs, recipient selection, form/decision permissions và khác biệt với archive. Giữ ba activities E/L/E; native human-rights admission ngoài Local SQL transaction, apply grant kiểm current rights lần nữa.

### State và Updates

State: request snapshot nhỏ, decision lock, `effects_settled` và `done`. Open/resolve/cleanup decision dùng cùng lock, tránh open snapshot ghi đè resolved decision.

| Update           | Xử lý                                                                                                   |
| ---------------- | ------------------------------------------------------------------------------------------------------- |
| `open`           | Trong decision lock: `open_hitl_request`, nhận persisted pending/already_granted; tool trả ngay sau ACK |
| `resolve`        | Trong lock: kiểm actor/action/deadline và `resolve_hitl_request`; trả committed decision                |
| `settle_effects` | Trong lock: cancel nếu pending; nhả lock rồi đợi effects_settled; dùng cho teardown                     |

Không giữ lock qua grant, delivery hoặc settle wait. Ask/approval không giữ Python tool stack chờ người dùng và không pause toàn agent.

### Main flow

```text
chờ open
nếu already_granted: effects_settled = done = true; chờ all_handlers_finished; return
chờ decision hoặc native deadline timer
nếu hết hạn: trong decision lock, conditional resolve_hitl_request(expire)
nếu accepted approval: await apply_hitl_outcome
effects_settled = true
await deliver_input với stable result message ID, hoặc skip recipient đã đóng
done = true
chờ all_handlers_finished
return saved outcome
```

Đặt effects_settled trước delivery: teardown chỉ cần grant đã xong, không cần đợi bridge delivery vào inbox đã đóng. Đây cũng là cách tránh cleanup activities đợi delivery activities trên cùng bridge pool. Các flags được set trước all_handlers_finished để handler chờ chúng có thể return.

Deadline có một authority: `workflow.now()`. Lưu expires_at cho UI; resolve xét Temporal workflow time khi handler xử lý. SQL CAS WHERE status='pending' và ghi terminal status/response/resolved_at cùng transaction. Timer/answer/cancel có một terminal decision, không worker-vs-SQL clock reconciliation.

Request expiry do trusted system/product policy, không agent timeout argument. Form IDs/type được system normalize một lần từ text/options/multiple trước persisted open; pending snapshot giữ nguyên qua retry. Không thêm workflow/activity cho input mapping.

Apply outcome phân biệt **accepted decision** và **actual grant**. Accepted approval kiểm exact addressed human, current storage.manage_access và root/requester liveness. Gọi LetFS SetStorageAccess với authenticated accepting human và target agent root, không dùng creator hoặc root subject để tự cấp quyền. LetFS kiểm quyền lại tại RPC; mất quyền/resource thì persist skipped outcome, transient failure retry. Không transaction qua RPC. Đã có outcome thì trả lại; source đóng trước grant thì skip grant mới, in-flight grant settle trước cleanup nội bộ.

Physical schema hitl_requests có type/status columns; payload không lặp type, response không lặp action/status. Pending là status=pending, terminal decision ghi response/resolved_at atomically. Outcome chỉ accepted approval; ask/deny/cancel/expire không copy response vào outcome. Result delivery dùng source_kind=hitl và request-derived message ID. Workflow effects_settled giữ cùng semantics.

Ask input chỉ rõ recipient_user_id là bất kỳ human owner/member cùng workspace. Open/read/answer kiểm current workspace.participate, resolve kiểm exact addressed user; không agent.use, agent.owner routing hoặc creator SQL. Recipient được giữ cố định; rời workspace không tự retarget request và không dừng agent. Approval input nhận user_id; admission tự resolve Personal storage duy nhất trong workspace bằng ListStorages private/owned_only của recipient, lưu storage_id vào payload và kiểm current manage_access. Không expose danh sách private storages cho agent hoặc thêm resolver RPC. Đã đủ read/write thì return already_granted không request row/result delivery mới. Accepted effect kiểm quyền đã đủ trước setter để không gán viewer lại cho editor hiện có. Sau granted, runtime native mount refresh thấy /mnt/<storage_id>; không đổi home binding hoặc đợi sandbox ACK.

Activity giữ root effect lock qua liveness check, grant và outcome save. Retry phải qua lock rồi mới quyết định skip/apply: không được thấy root đã đóng, báo settled trong khi attempt trước còn đang grant. Cleanup dùng cùng barrier; không cần grant receipt registry mới.

Không giả định LetFS có permanent graph-grant receipt. Retry graph write là idempotent, không globally exactly-once: concurrent revoke trong lúc grant còn pending có thể bị grant write sau đó ghi đè. Revoke sau settlement mới có ordering rõ. Không thêm grant/revoke saga trong rewrite này. Owner transfer không sửa SQL recipient/approver lịch sử hoặc tự gửi pending request cho owner mới; quyền hiện tại vẫn phải kiểm.

Result dùng stable request-derived message ID, vào đúng requester. Inactive source/recipient là skipped, không retry vô hạn hoặc start lại archived agent. Delivery đang xếp hàng không ngăn storage teardown vì admission đã đóng.

## 9. ScheduleChanges

Giữ SQL definitions và native Temporal timing: SQL phục vụ product list/calendar/history; native Schedule điều khiển execution. Một coordinator nhỏ theo schedule serialize hai hệ thống này. Không chuyển schedule mutations vào Agent hoặc giữ DB transaction qua native API.

State chỉ một change lock, `deleted` và `rotating`. Canonical command cùng normalized timing được giữ trong Temporal history, không pending receipt SQL. `change(command)` Update-with-Start:

```text
trong change lock:
  canonical = normalize(command, workflow.now())
  saved = await save_schedule_change(canonical)
  nếu receipt đã finalized: return saved outcome, không apply lại
  nếu cần native effect: await apply_native_schedule(canonical, saved response)
  nếu delete: deleted = true
  return saved definition

main: chờ deleted hoặc native rotation suggestion
đóng change admission trên run cũ; chờ all_handlers_finished
nếu deleted: return
Continue-As-New chỉ với root/schedule IDs
```

Giữ lock qua native apply vì đây chính là ordering cần bảo vệ. Chỉ schedule đó bị block khi dependency lỗi, không serialize các schedule khác hoặc inference.

SQL là desired definition. Trước native ACK, hai hệ thống có thể tạm lệch và operation còn pending; API không báo đã áp dụng thành công hoặc giả vờ có cross-system transaction.

- SQL definition là desired state. Canonical command/accepted time nằm trong native Temporal history; Local Activity retry ghi lại cùng absolute values nếu receipt chưa finalized. Metadata-only change ghi definition + finalized receipt cùng transaction. Native change chưa ghi receipt pending; effect ACK xong mới INSERT finalized response receipt trong transaction ngắn, không network trong SQL transaction.
- Native apply kiểm source liveness trước create/update, conditional delete không recreate. Inactive trả superseded/skip; transient native lỗi retry. ACK success chỉ sau native effect hoàn tất.
- Metadata-only title/content edit chỉ SQL; không rearm native schedule. Action chỉ mang root/schedule IDs; occurrence đọc current body/target.
- At dùng exact UTC calendar, đầy đủ year/month/day/hour/minute/second nên tự chỉ match một instant; không limited_actions/remaining_actions, spec_key comparator hoặc direct-start delivery branch. Create/timing edit/resume có mốc đã qua dùng native backfill khoảng (at-1s,at]; kiểm due sau native ACK bằng activity wall clock, không dùng wall clock làm occurrence identity. Tick/backfill trùng được inbox dedupe theo nominal time, gồm retry sau khi consumed. Metadata edit không backfill.
- Interval/calendar/timezone/end dùng native ScheduleSpec; không tự viết cron, next-tick hoặc catchup engine. BUFFER_ONE bao delivery, không inference: trong khi một delivery chưa xong chỉ giữ thêm một start, các tick thêm có thể bị bỏ. Giữ server-configured native recurring catchup window; không hứa giữ mọi tick hoặc replay mọi lịch bị pause.
- Pause/delete chặn occurrence chưa commit qua source check tại recipient admission. Delete ghi SQL tombstone trước native delete. Occurrence đã admit vẫn được xử lý; không retract committed message.

Native Update identity dựa caller/method/key/request hash: identical retries được SDK dedupe trong một run; khác payload vẫn vào serialized hash check và conflict, không nhận nhầm cached outcome. Finalized SQL receipt dedupe qua Continue-As-New trong retention đã cam kết. Save kiểm receipt trước mutation; old completed command trả outcome cũ. Nếu crash sau SQL/native effect nhưng trước receipt, workflow replay cùng canonical command, apply idempotently và finalize receipt trước khi nhả change lock. Next command/CAN không vượt pending handler. Transient errors retry bằng Temporal, không result-pending bag/completed_at/journal hoặc distributed-transaction claim.

ScheduleChanges cũng Continue-As-New theo native suggestion. Change validator đóng admission ở run đang rollover; caller retry cùng request key vào workflow ID hiện tại. Drain handlers trước rollover, không truyền processed-ID set hoặc toàn bộ definition history. Ticks vốn nằm ở delivery executions khác; actor vẫn chạy được qua nhiều năm edits.

Delete kết thúc actor. Retry delete sau completion lấy result/tombstone; sau retention native delete vẫn idempotent và tombstone chặn create/update. Không nhận lại histories/actors cũ vào database mới hoặc tự khôi phục actor bị operator terminate.

## 10. ScheduleDelivery

```text
lấy schedule_id và nominal scheduled_at từ native Schedule start metadata
snapshot = await load_schedule_occurrence
nếu inactive: return skipped
message_id = stable UUID(schedule_id, nominal scheduled_at)
await deliver_input(snapshot, message_id)
return receipt/skip
```

Không dùng worker wall clock/random attempt UUID làm occurrence identity. `admit_input` kiểm source/root/box/recipient lần nữa trong transaction INSERT, chặn delete giữa snapshot và commit. Duplicate tick/backfill/retry không tạo input mới.

Với source schedule, duplicate identity là authorized scope + schedule_id + nominal UTC scheduled_at + immutable target. Nếu inbox đã có occurrence thì trả delivery cũ trước khi đọc lại title/content đã edit; không báo hash conflict chỉ vì definition hiện tại có body mới. Input chưa admit dùng bounded content snapshot của delivery; snapshot không là durable occurrence ledger. Timing/content edit không retract delivery đã start; pause/delete chỉ chặn occurrence chưa commit.

Không wait inference, không occurrence ledger, không timer workflow tự chạy cron. Native schedules chỉ start workflow, vì vậy delivery workflow nhỏ này có trách nhiệm thật.

## 11. Retry, cancellation và liveness

Các giá trị sau là cấu hình khởi điểm, chưa đo:

| Nhóm             | Native options và behavior                                                                                                                                                                                                                                                                                   |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Local SQL        | Start-to-close 5s; retry transient DB; business validation/conflict không retry                                                                                                                                                                                                                              |
| Effects/delivery | Bounded RPC deadlines, activity 1–2 phút; transient backoff; inactive là domain outcome                                                                                                                                                                                                                      |
| Cleanup/fanout   | Activity 30 phút, heartbeat 15s và pulse khi chờ/theo batch; retry idempotently từ SQL                                                                                                                                                                                                                       |
| Runtime          | Activity chạy dài, không timer slice; technical start-to-close khởi điểm 365 ngày, heartbeat timeout 10s/pulse khoảng 2s, deadline model/tool riêng; transient retries không giới hạn attempts, không total schedule-to-close timeout; WAIT_CANCELLATION_COMPLETED và protected checkpoint/cleanup trước ACK |
| Workflows        | Không whole-workflow retry policy; activity retries giữ effects. Agent/ScheduleChanges rotation theo native suggestion; không lifetime timeout                                                                                                                                                               |

Technical runtime timeout không xóa checkpoint hoặc kết thúc tuổi đời agent. Start-to-close hữu hạn là cấu hình attempt, không timer rollover; 365 ngày là guard dài khởi điểm. Bỏ cặp soft slice 5 phút/hard attempt 30 phút cũ; liveness dựa heartbeat và thao tác treo bị deadline model/tool giới hạn. Tắt model SDK retry layer khi Temporal đã retry invocation; giữ native transport retry phù hợp. Permanent model/context/config lỗi hiện rõ, không catch-all success hoặc repair loop.

Working messages/summary và inbox batches phải có token/byte/count budgets. Native compaction giữ context hữu hạn, native pruning giữ recovery snapshots hữu hạn, Redis stream/cache và closed Temporal histories dùng native retention. Committed inbox/public history và receipts còn trong retention là dữ liệu bền vững, vẫn tăng theo sử dụng và cần dung lượng DB tương ứng; không tuyên bố chạy vô hạn với ổ đĩa cố định hoặc tự xóa product history.

Cancellation là cooperative; timeout không chứng minh code/RPC vật lý đã dừng. Cancel-current không rollback committed effects. Cleanup do Leta sở hữu chỉ báo xong sau producer/writer barriers và external effect settlement cần cho thao tác đó; không là ACK để core xóa workspace. LetFS authorization/mount/quota/version vẫn là boundary cuối. Không dùng terminate/ABANDON thay stop nội bộ Leta.

Provisioning lỗi terminal để resource provisioning và lỗi vận hành rõ; operator dùng native recovery hoặc delete. Không reconciliation service, orphan sweeper hoặc retry scheduler mới.

## 12. Platform và plan song song

```text
Leta → Platform: generic CheckWorkspaceActive, workspace/profile APIs
Leta → LetFS: storage discovery/provisioning, grants, file operations
Leta → SpiceDB: agent relations + agent.workspace/workspace.agent cùng batch, không workspace membership/storage writes

Platform mark workspace deleting
→ Platform activity revoke workspace graph
→ schedule DeleteWorkspaceStorage (LetFS) và DeleteWorkspaceAgents (Leta bridge) song song
→ storage ACK: xóa Platform workspace SQL ngay
→ workflow tiếp tục chờ Leta cleanup

Leta tắt/chưa deploy → cleanup activity queued; core startup/CRUD và storage/SQL deletion vẫn tiến hành
```

Contract đã chốt tại [workspace-cleanup.md](../261111-1727-platform-letfs-rewrite/workspace-cleanup.md): một JSON object workspace_id, native shared queue mapping và owning regular activities. DeleteWorkspaceAgents chạy bridge, close gates/query batches và gọi root/box cleanup inline; không workflow/poller mới. Storage mất/permission revoked là expected teardown outcome, không grant/trash retry vô hạn. Archive không physical purge history/checkpoints. Không binding/list/stop callbacks hoặc stop-ACK barrier trước storage deletion, không core readiness/hot-path dependency. RemoveMember chỉ thu hồi human membership; không đọc agent ownership, sửa workspace.agent hoặc stop/cleanup agent. Agent giữ identity/grants riêng dù human owner rời workspace; việc này không thêm workflow/activity. Core không đọc SQL/thread hoặc gọi private workflows/activities Leta. Shared DeleteWorkspaceAgents trên bridge queue là contract được công bố, không quyền dispatch tùy ý.

Rà soát active proto/handlers/config mới nhất ở [boundary review](boundaries.md). Đã đối chiếu [plan Platform/LetFS](../261111-1727-platform-letfs-rewrite/plan.md), [infra/CI](../261111-1727-platform-letfs-rewrite/infra-testing-ci-cd.md) và [YAML mẫu](../261111-1727-platform-letfs-rewrite/openlet.example.yaml). Archive report cũ ghi giữ source; tiến độ mới trong core plan báo archive nốt source/migrations/native dependencies và hash-check 60 files, đúng active apps/leta hiện absent. Lượt này không chạy lại hash audit. Không restore source/tests cũ hoặc sửa core-owned runtime/config trong lượt tài liệu này.

Actor subject/workspace/storage và core APIs đã chốt; schema đã reconcile. [Leta API/streaming](streaming.md) đã chốt HTTP JSON + SSE; publication/refetch không thêm workflow/activity/queue hoặc ghi SQL theo token. Workspace cleanup đã chốt; complete DTO/errors và product-data retention còn review riêng, transfer ownership và đổi home storage hoãn; external dynamic mounts vẫn giữ theo filesystem.md. Shared dependencies.temporal.queues.leta_bridge phải đồng bộ Go/Python/YAML để Platform route cleanup; ba queues vẫn một worker deployment/image, core không cần Leta provider/Redis/startup ACK. Database/Temporal namespace mới, không import data/checkpoint/HITL/schedule histories cũ hoặc jobs cũ vào database mới; database cũ giữ tới cutover riêng. Không tự chạy cutover trong bước thiết kế.

Idempotency table dùng đúng caller/method/key/request_hash/result bytea/expires_at của core. Leta durable receipts cần retention đủ dài; core file receipts mặc định 24h không tự trở thành dedupe nhiều năm. Đã chốt giữ finite horizon: retry canonical key/payload trong guarantee; recovery pending mutation quá guarantee báo kết quả chưa xác định, không tự phát lại. Kiểm tuổi conservative từ checkpoint chứa pending tool khi recovery; không dùng tuổi runtime activity/agent, không thêm ledger/background job hoặc đổi core retention. Chi tiết tại [boundary 8.2](boundaries.md#82-dedupe-horizon-của-file-effects).

## 13. Files và verification tối thiểu

`jobs/agent.py`, `jobs/resources.py`, `jobs/hitl.py`, `jobs/schedules.py` chỉ chứa deterministic orchestration. Activities cạnh owning `agents.py`, `boxes.py`, `hitl.py`, `schedules.py`, `messages.py`, `runtime/agent.py`; worker đăng ký trực tiếp. Không bridges/commands/repositories framework mới.

| Check            | Invariant cần chứng minh                                                                                                                                                                                                                                   |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent            | Receive khi runtime chạy không mất wake/không cancel model; ép rollover khi graph luôn bận, checkpoint/cleanup xong trước cancellation ACK/CAN; cùng logical run/thread, không hai writer                                                                  |
| Lifecycle        | Xóa Leta/box do người dùng yêu cầu không tạo home muộn; cleanup nội bộ không tự đợi cùng bridge pool. Core workspace delete không đợi agent ACK                                                                                                            |
| HITL             | Answer-vs-expiry một winner; tool trả pending; đúng requester; teardown đợi grant nhưng không đợi delivery                                                                                                                                                 |
| Schedule         | Native at/interval/calendar smoke; past-at dedupe; metadata không rearm; old command retry sau rollover không ghi đè edit mới; delete chặn late admission                                                                                                  |
| Long-lived state | Nhiều model/tools boundaries không cần compaction vẫn prune snapshots cũ sau checkpoint/projection; restart từ latest giữ summary/tail, inbox cursor và pending tool/resume, public history còn nguyên; pause/cancel và transient recovery không mất inbox |
| System           | Một journey chung với Platform/LetFS và workspace cleanup trong cùng dependency environment                                                                                                                                                                |

Không cần chạy test một năm: ép rollover sớm, dùng graph/model fixture luôn còn việc và restart worker trong một integration check ngắn. Không port tests/replay histories cũ, exact activity order hoặc mọi failure permutation. Native time-skipping cho workflow logic; native Schedule cần smoke thật. Không stack từng test hoặc E2E suite trùng infra plan.

## 14. Nguồn và giới hạn xác minh

SDK lock khảo sát: Temporal Python 1.35.0, LangGraph 1.2.20, checkpoint-postgres 3.2.0. Đã đối chiếu native semantics với tài liệu chính thức:

- [Updates, Update-with-Start và async handlers](https://docs.temporal.io/develop/python/workflows/message-passing).
- [Continue-As-New và handlers](https://docs.temporal.io/develop/python/workflows/continue-as-new).
- [Cancellation và activity heartbeat](https://docs.temporal.io/develop/python/workflows/cancellation).
- [Native schedules, backfill và delete](https://docs.temporal.io/develop/python/workflows/schedules).
- [Entity workflows và Update dedupe chỉ trong một execution](https://docs.temporal.io/design-patterns/entity-workflow).
- [Server 1.32.2 native rollover defaults](https://github.com/temporalio/temporal/blob/v1.32.2/common/dynamicconfig/constants.go) và [server history/Update suggestion](https://github.com/temporalio/temporal/blob/v1.32.2/service/history/workflow/workflow_task_state_machine.go).
- [Python SDK 1.35.0 cancellation](https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/worker/_activity.py) và [native activity test environment](https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/testing/_activity.py).
- [Native graph breakpoints và resume bằng None](https://docs.langchain.com/oss/python/langgraph/interrupts#debugging-with-interrupts).
- [AsyncPostgresSaver.aprune](https://reference.langchain.com/python/langgraph.checkpoint.postgres/aio/AsyncPostgresSaver/aprune) và [keep_latest semantics](https://reference.langchain.com/python/langgraph.checkpoint.postgres/PostgresSaver/prune).

Đây là thiết kế mới, chưa full SDK/server/LangGraph integration hoặc replay tests, chưa benchmark LoC/CI/latency hoặc long-running workload. Native cancellation check nhỏ được ghi riêng bên dưới. Chưa sửa runtime, archive source, đổi database hoặc khởi động process. Không hứa exactly-once cho model/shell/RPC; giữ idempotency ở durable mutation owners. Hoạt động nhiều năm cần hạ tầng/storage còn phục vụ và phục hồi dependency sau outage; permanent configuration errors vẫn cần sửa.

Lượt chốt runtime chạy dài đã kiểm native ActivityEnvironment của temporalio 1.35.0 trong uv isolated: cancellation đợi protected asyncio task tới boundary, heartbeat vẫn dùng được, cleanup hoàn tất trước propagate cancellation. Check này không chạy LangGraph, PostgreSQL, server-side WAIT_CANCELLATION_COMPLETED/CAN hoặc provider; shared integration vẫn phải chứng minh đầy đủ chuỗi checkpoint/cleanup/ACK trước rollover. Không đổi runtime/core/dependencies của repo.
