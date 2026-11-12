# Temporal cho Leta viết mới — thiết kế cuối

Đã reconcile boundary/schema ngày 2026-11-12 theo [workspace resources](../261111-1727-platform-letfs-rewrite/workspace-service-redesign.md) và [API core](../261111-1727-platform-letfs-rewrite/api-contract.md). Root là agent subject, giữ workspace_id/storage_id, ownership ở graph. Sáu workflow types/21 activities/ba queues giữ nguyên; SQL đã đổi sang 11 bảng. HITL type/status là columns, pending schedule command thuộc Temporal và finalized receipt theo schema core. Concrete Leta API/transport/multiple storage và physical cleanup integration hoãn, không core stop/readiness/hot-path dependency.

Ngày 2026-11-11. Đề xuất kiến trúc, chưa implementation. Thay thế bản Temporal trước trong cùng plan. Không dùng skill/subagent, không sửa runtime hoặc copy implementation/tests cũ. [Kiến trúc Leta](design.md), [plan và acceptance](plan.md).


Yêu cầu đã chốt thêm: Leta/Leti có thể hoạt động liên tục 24/7 nhiều tháng, nhiều năm, kể cả luôn có việc. Không cần manual restart/reset để tránh history/context tăng. Logical agent giữ identity và context qua nhiều workflow runs và runtime activities.

[Schema chi tiết](schema.md) và [DDL review](schema.sql) xác định physical fields. Các state snapshots/status trong workflow/API bên dưới có thể là SQL projections, không mặc định là columns riêng.

## 1. Quyết định

Giữ Temporal và sáu workflow types. Phân chia nghiệp vụ cấp cao còn giống hệ thống hiện tại; phần viết lại là state ownership, đường admission, lifecycle hữu hạn và cách thực thi effects. Không gọi việc giữ nguyên sáu tên workflow là một kiến trúc hoàn toàn khác.

Vấn đề đã xác minh là nhiều nơi cùng giữ execution progress, ordinary CRUD đi vòng qua lifecycle coordinator, và application tự dựng replay/recovery ngoài thư viện. Temporal cùng LangGraph không tự nó là overengineering. Không bỏ một coordinator đang giải quyết ordering thật rồi thay bằng lock/outbox/scheduler tự chế.

| Type | ID | Vòng đời và trách nhiệm |
|---|---|---|
| `Agent` | `agent/{agent_id}` | Lazy, sống khi agent còn hoạt động; admission, wake, dispatch runtime và control |
| `LetaLifecycle` | `leta/{id}/create`, `leta/{id}/delete`, `leta/{id}/control/{request_id}` | Một create/delete/pause/resume operation rồi kết thúc |
| `BoxLifecycle` | `box/{id}/create`, `box/{id}/delete` | Một create/delete operation rồi kết thúc |
| `HitlRequest` | `hitl/{request_id}` | Open → decision/deadline → effect → result delivery rồi kết thúc |
| `ScheduleChanges` | `schedule-changes/{schedule_id}` | Serialize edits của một schedule; kết thúc khi delete |
| `ScheduleDelivery` | Native Schedule sinh execution ID | Một occurrence, giao input rồi kết thúc; không đợi inference |

Native Schedule ID: `schedule/{schedule_id}`. Không có workflow cho từng message, model call, tool, file mutation, agent metadata PATCH hoặc SSE event.

## 2. State thuộc về đâu

| Owner | State |
|---|---|
| PostgreSQL | Resource lifecycle, desired pause, inbox, public history, UI run status, HITL decision/outcome, schedule definitions, mutation receipts |
| Native LangGraph saver | Working messages/summary, inbox cursor, pending tasks/interrupts và continuation |
| Temporal | Command ordering, wake/dispatch, activity/timer progress, durable retries |
| Native Schedule | Timing, timezone, overlap/catchup và occurrence start |
| Redis | Provisional events và cache; không recovery authority |
| SpiceDB theo owning service | Agent owner/operator và hai chiều agent.workspace/workspace.agent do Leta; workspace/membership do Platform; storage/grants do LetFS. Không SQL owner/binding mirror |
| LetFS | Storage/tree/content/version/workspace quota và native mutation idempotency |

Xóa khỏi SQL `runs` và Agent workflow: checkpoint ID/namespace, cursor, continuation, runtime attempt, yield flag, result snapshot và latest-sequence mirror. `runs` chỉ là product status/correlation; runtime đọc checkpoint để biết việc cần làm. Không custom tool-result replay journal hoặc heartbeat chứa transcript.

## 3. Activity inventory và worker

`L` = native Local Activity, chỉ SQL ngắn. `E` = regular effect Activity, không chờ Leta workflow khác. `B` = regular bridge Activity, được gọi Temporal Client để chờ Updates/results. `R` = runtime Activity.

| # | Activity | Loại | Trách nhiệm |
|---|---|---|---|
| 1 | `admit_input` | L | Validate route/source/liveness; transaction dedupe, cấp recipient seq, INSERT inbox |
| 2 | `load_agent_control` | L | Đọc active/desired pause và unfinished UI run ID; không checkpoint |
| 3 | `finish_run` | L | Ghi terminal/pause UI status nếu runtime đã mở run; không kết thúc logical run khi slice yield |
| 4 | `run_agent` | R | Một slice native graph hữu hạn, giữ writer lock; model/tools/checkpoints/history/events và native checkpoint pruning |
| 5 | `deliver_input` | B | Update-with-Start recipient; trả committed receipt hoặc inactive skip |
| 6 | `prepare_leta` | L | Canonical root/storage/storage-root IDs, letas + root agents rows và admitted creation receipt |
| 7 | `provision_leta` | E | Generic Platform CheckWorkspaceActive, native agent graph batch gồm hai chiều workspace binding, LetFS CreateStorage với saved ordinary UUID rồi conditional activate; không EnsureLetaHome |
| 8 | `close_leta` | L | Đóng root admission bằng SQL trước teardown |
| 9 | `cleanup_leta` | B | Settle producers/grants/runners, trash box homes, cleanup access, archive |
| 10 | `set_leta_paused` | L | Desired pause assignment có request receipt |
| 11 | `refresh_leta_agents` | B | Notify existing agents đọc current control; không chờ inference |
| 12 | `prepare_box` | L | Atomic box/Leti/edges và creation receipt; home-ID provisioning contract còn mở, xem boundaries.md |
| 13 | `provision_box` | E | Ensure ordinary box directory rồi conditional activate |
| 14 | `close_box` | L | Đóng admission của box |
| 15 | `cleanup_box` | B | Settle box producers/grants/runners, trash home, archive |
| 16 | `open_hitl_request` | E | Chọn addressed user/current graph quyền khi cần, canonical storage target, persist pending hoặc already_granted |
| 17 | `resolve_hitl_request` | L | Authorized CAS status=pending, ghi terminal status/response/resolved_at cùng transaction |
| 18 | `apply_hitl_outcome` | E | Grant nếu cần, persist actual outcome; không inbox delivery |
| 19 | `save_schedule_change` | L | Check finalized receipt/hash; lưu canonical desired definition; metadata-only finalize receipt cùng SQL |
| 20 | `apply_native_schedule` | E | Apply canonical native effect, sau ACK ghi finalized bytea receipt trong transaction ngắn |
| 21 | `load_schedule_occurrence` | L | Current SQL source/target/content → bounded input hoặc skip |

Activities đặt cạnh owning feature functions; đăng ký trực tiếp. Feature function dùng concrete clients/pool, không repository interface hoặc dispatcher framework. SQL lookup nhỏ bên trong một effect không cần activity riêng.

Ba native task queues, ba Worker instances trong **một worker process/deployment**:

| Queue | Chạy gì |
|---|---|
| `openlet-leta` | Tất cả workflows, Local SQL và E activities |
| `openlet-leta-runtime` | `run_agent` |
| `openlet-leta-bridge` | B activities |

Đây là phân tách slot để tránh vòng đợi thật: runtime tool có thể đợi lifecycle cleanup; cleanup có thể đợi Agent/HITL/Schedule Updates; các Updates đó cần effect activities chạy được. E activities không chờ Leta workflows. B activities không đợi một B activity khác phải chạy để mình hoàn tất. Không slot-reservation framework hoặc service/container mới.

Cross-workflow Updates dùng native Client **trong activity**; workflow Python không gửi Update trực tiếp sang workflow khác. Tool đang ở runtime activity gọi cùng feature/client function, không tạo thêm activity lồng nhau.

## 4. Admission chung

HTTP/tool cung cấp stable operation/message identity. SQL resource IDs và mutation receipts quyết định business idempotency; Temporal retention không thay thế chúng. Payloads trong history chỉ IDs, bounded command/message fields và results nhỏ; không file bytes, secrets hoặc transcript.

`Agent.receive`, lifecycle `open`, HITL `open`, schedule `change` dùng native Update-with-Start. Update **COMPLETED sau activity SQL commit** mới là domain ACK; ACCEPTED chưa phải message/resource đã lưu.

Lifecycle `open` chỉ prepare/close/control SQL rồi cho main tiếp tục. Public API có thể trả provisioning/deleting sau admission; tool cần resource sẵn sàng thì chờ workflow result. Không private stop callback cho Platform. HTTP disconnect không cancel durable operation.

Finite operation IDs gắn canonical resource và operation; duplicate completed operation đọc result/state, không tạo resource mới. Lifetime Agent/ScheduleChanges dùng existing execution khi đang chạy. Root/box gates và tombstones chặn tái tạo resource đã đóng.

Liveness và mutation phải nằm cùng transaction có khóa gate phù hợp: root → box → recipient/resource. Close lấy cùng gate, để không có admission mới commit qua điểm đóng. Inbox seq cấp theo recipient trong transaction INSERT; không dùng global sequence làm committed high-water.

## 5. Agent

### State và Updates

Chỉ giữ `wake`, cached `paused`, `stopping`, `rotating`, active runtime handle/run ID, và completion của lượt đang cancel. Đây là scheduling state, không native graph state.

| Update | Xử lý | ACK |
|---|---|---|
| `receive` | `admit_input`; sau commit đặt wake=true | Input đã lưu, không đợi model |
| `refresh_control` | Lock ngắn quanh `load_agent_control` và cập nhật cache; resume đặt wake=true | Đã đọc desired control mới nhất |
| `cancel_current(run_id)` | Chỉ cancel đúng active invocation, bỏ wake cũ, chờ lượt đó settle | Cancellation của lượt đã được xử lý; không rollback effects |
| `stop` | Latch stopping, cancel active invocation, chờ stopped | Workflow không dispatch thêm; cleanup còn xác nhận writer barrier |

Không giữ handler lock qua inference, fanout, stop hoặc inbox delivery. Cancel chờ đúng invocation được nhắm tới, không chờ mọi lượt về idle.

### Main loop

```text
bootstrap control; wake = true
lặp:
  chờ stopping hoặc (wake và không paused) hoặc native rotation suggestion
  nếu stopping: break
  nếu rotate và không active invocation:
    đóng receive admission trên run cũ; chờ all_handlers_finished
    nếu stopping: break
    Continue-As-New chỉ với IDs

  wake = false
  trong control lock ngắn: đọc control/cập nhật cache trước dispatch
  nếu inactive: stopping = true; continue
  nếu paused: cache paused; continue

  chọn unfinished UI run ID hoặc candidate ID mới
  result = await run_agent slice trên runtime queue
  nếu result là yielded: wake = true; giữ logical UI run đang chạy
  nếu completed/paused/cancelled/failed: finish_run

stopped = true
chờ all_handlers_finished
return
```

Đặt stopped trước khi đợi handlers, vì stop handler đang đợi stopped. Đặt wake=false **trước dispatch**: receive khi activity chạy sẽ đặt lại true, không mất wake khi activity return. Chấp nhận thêm một invocation kiểm tra rỗng; không wake-sequence protocol.

Bootstrap, pre-dispatch và refresh handler dùng cùng control lock quanh read/cache update; không để một read cũ ghi đè resume vừa được notify. Nhả lock trước runtime hoặc stop wait.

Transient runtime/dependency errors dùng native retry có backoff cho đến khi phục hồi; không làm agent chết sau vài attempts. Permanent model/config/context errors mark lượt failed và cần input/resume hoặc sửa cấu hình; không spin trên lỗi permanent. Input đến sau cancel vẫn đánh thức; input đã lưu trước cancel còn nguyên và sẽ được đọc khi có input/resume tiếp theo.

### Bên trong run_agent

1. Heartbeat và giữ PostgreSQL session advisory writer lock theo agent suốt invocation. Lock bận trả retryable cho native backoff; không tự poll. Một agent chỉ có một graph writer.
2. Đọc liveness và native saver snapshot. Cursor chỉ ở checkpoint. Không có graph work/input mới thì trả idle, không mở SQL run rỗng.
3. Mark UI run running khi thật sự có việc. Native graph thread cố định theo agent; failed UI run không khiến checkpoint hợp lệ bị loại.
4. Tại safe boundaries, lấy committed inbox sau cursor và refresh control/model/mounts. Batch và cursor cùng checkpoint. Root dùng digest, Leti dùng full batch.
5. Native create_agent/saver/summarization chạy model/tools. Dùng `interrupt_after=["model", "tools"]` và `durability="sync"` để có boundary đã checkpoint giữa các bước. Resume static breakpoint bằng input `None` trên cùng thread; native snapshot quyết định pending work. Durable mutations dùng stable IDs/owning idempotency; public history upsert stable entry ID, Redis nhận provisional events.
6. Mỗi slice có soft budget khởi điểm 5 phút, kiểm tại native boundaries. Hết budget và còn pending work thì return yielded; pause thì return paused. Đây là technical handoff, không kết thúc công việc hoặc giới hạn tổng số bước của agent. Không timeout/cancel model giữa chừng chỉ để hết slice; model/tool calls vẫn có deadline riêng. Không SQL interrupt/continuation mirror.
7. Cancel: hủy invocation, đóng model/workspace resources và nhả writer lock trong finally, re-raise cancellation. Checkpoint cuối giữ lại; node/effect chưa checkpoint có thể replay.

Trước khi nhả writer lock ở cuối slice, gọi native `AsyncPostgresSaver.aprune([thread_id], strategy="keep_latest")`. Giữ latest checkpoint cùng pending writes/blobs cần resume; xóa snapshots cũ. Không bật DeltaChannel hoặc arbitrary checkpoint time travel. Public history nằm ở bảng riêng, không bị prune. Không viết SQL xóa nội bộ saver, custom saver hoặc retention service.

Không workflow từng tool/model call hoặc SavedToolResults replay layer. Slice không tạo UI run mới, không reset retry budget cho tuổi đời agent, không mang continuation blob qua Temporal. Shell nhiều effects có thể chạy lại; không hứa exactly-once toàn shell command.

### Rollover khi agent luôn bận

Agent lazy-start khi receive đầu tiên. Provision không start agent. Fanout refresh/stop bỏ qua workflow chưa từng tồn tại. Khi native suggestion xuất hiện, Continue-As-New sau slice và handlers hiện tại; **không chờ inbox rỗng hoặc graph hoàn thành toàn bộ công việc**. Run mới bootstrap wake=true, đọc desired control và cùng graph thread; logical run/context/inbox tiếp tục.

Khi native suggestion đã xuất hiện hoặc rotating=true, receive validator từ chối Updates mới bằng retryable rollover response trước ACCEPTED. Caller gọi lại cùng message ID vào workflow ID hiện tại; không pin Run ID. Handlers đã accepted được drain, stop vẫn được xử lý. Gate ngắn này ngăn dòng input liên tục làm history tiếp tục tăng hoặc không bao giờ hết handlers. Không ACK message chưa commit và không copy danh sách processed IDs qua rollover.

Không đặt WorkflowExecutionTimeout hoặc WorkflowRunTimeout thành giới hạn tuổi đời của Agent/ScheduleChanges. Activity timeouts chỉ giới hạn technical attempts. Restart worker tự replay orchestration và tiếp tục checkpoint; deploy workflow logic thay đổi dùng native Temporal patch/versioning. Operator terminate vẫn cần native recovery, không poller tự dựng.

## 6. LetaLifecycle

Mỗi execution chỉ nhận một command qua `open`; SQL admission result nhỏ cho main chạy tiếp.

| Operation | Admission | Sau admission |
|---|---|---|
| create | `prepare_leta` | `provision_leta`, return active/superseded |
| delete | `close_leta` | `cleanup_leta`, return archived |
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
6. Trash box directories khi còn tồn tại/được phép; giữ SQL history theo local archive đã chốt. Leta xóa agent.workspace và workspace.agent trong cùng native SpiceDB batch khi xóa root, không UnregisterAgent RPC; box delete không sửa binding root. Graph/access/storage physical cleanup phải theo owning business contract được review sau; không suy storage exclusive ownership từ binding, không blanket revoke quyền human operator, không CleanupLetaAccess hoặc Platform scope grants cũ.
7. Archive root/boxes rồi return cho thao tác xóa Leta do người dùng yêu cầu. Không có Platform stop callback; core workspace deletion không đợi luồng này.

Provision giữ session advisory effect lock theo root/box resource quanh critical section; grant dùng cùng root effect lock. Cleanup qua cùng barriers trước trash/access cleanup. Runtime giữ writer lock theo agent. Locks bảo vệ actual producers kể cả activity attempt đã timeout nhưng còn chạy; lock bận dùng native retry, không tự poll. Không SQL phase table/cleanup journal hoặc transaction qua RPC.

Một standalone BoxDelete có thể đang chạy đồng thời. Root cleanup không join nó: cả hai chỉ lặp native idempotent deletions sau gate closure; không bên nào còn được provision. Tránh root cleanup chiếm bridge slot rồi chờ box cleanup đang xếp hàng trên chính pool đó.

Các loops dùng domain state để chạy lại idempotently, heartbeat khi chờ/theo batch; không per-file/agent child workflow, progress cursor hoặc compensation engine. Model tools chỉ root được quản lý boxes; không cho Leti gọi deletion của chính box rồi đợi stop chính invocation đó.

## 7. BoxLifecycle

`open(create)` → `prepare_box` atomic box/children/edges → `provision_box` directory → conditional active → return. Bước cấp/lưu home_node_id chưa khớp LetFS CreateNode hiện tại: DDL vẫn giữ NOT NULL theo schema đã duyệt, không được triển khai giả định caller-chosen node ID. Chốt lựa chọn ở [boundary review](boundaries.md) trước khi code hai activities này. Root phải active khi prepare và activate. Graph bất biến, create không gửi việc hoặc start Agent.

`open(delete)` → `close_box` → `cleanup_box`:

1. Settle box provisioning và qua provision barrier.
2. Delete schedules có creator/target trong box, kể cả root-created schedules target box.
3. Settle HITL effects của children, stop children và qua writer barriers.
4. Native trash home, archive box rồi return.

Root Agent/boxes khác tiếp tục hoạt động. Không revoke root grants đã được duyệt chỉ vì requester box bị xóa; grantee là root Leta. In-flight grant phải settle trước ACK, grant chưa bắt đầu kiểm requester/root liveness và skip nếu đóng.

## 8. HitlRequest

### State và Updates

State: request snapshot nhỏ, decision lock, `effects_settled` và `done`. Open/resolve/cleanup decision dùng cùng lock, tránh open snapshot ghi đè resolved decision.

| Update | Xử lý |
|---|---|
| `open` | Trong decision lock: `open_hitl_request`, nhận persisted pending/already_granted; tool trả ngay sau ACK |
| `resolve` | Trong lock: kiểm actor/action/deadline và `resolve_hitl_request`; trả committed decision |
| `settle_effects` | Trong lock: cancel nếu pending; nhả lock rồi đợi effects_settled; dùng cho teardown |

Không giữ lock qua grant, delivery hoặc settle wait. Ask/approval không giữ Python tool stack chờ người dùng và không pause toàn agent.

### Main flow

```text
chờ open
nếu already_granted: effects_settled = true; kết thúc
chờ decision hoặc native deadline timer
nếu hết hạn: trong decision lock, conditional resolve_hitl_request(expire)
await apply_hitl_outcome
effects_settled = true
await deliver_input với stable result message ID, hoặc skip recipient đã đóng
done = true
chờ all_handlers_finished
return saved outcome
```

Đặt effects_settled trước delivery: teardown chỉ cần grant đã xong, không cần đợi bridge delivery vào inbox đã đóng. Đây cũng là cách tránh cleanup activities đợi delivery activities trên cùng bridge pool. Các flags được set trước all_handlers_finished để handler chờ chúng có thể return.

Deadline có một authority: `workflow.now()`. Lưu expires_at cho UI; resolve xét Temporal workflow time khi handler xử lý. SQL CAS WHERE status='pending' và ghi terminal status/response/resolved_at cùng transaction. Timer/answer/cancel có một terminal decision, không worker-vs-SQL clock reconciliation.

Apply outcome phân biệt **accepted decision** và **actual grant**. Accepted approval kiểm exact addressed human, current storage.manage_access và root/requester liveness. Gọi LetFS SetStorageAccess với authenticated accepting human và target agent root, không dùng creator hoặc root subject để tự cấp quyền. LetFS kiểm quyền lại tại RPC; mất quyền/resource thì persist skipped outcome, transient failure retry. Không transaction qua RPC. Đã có outcome thì trả lại; source đóng trước grant thì skip grant mới, in-flight grant settle trước cleanup nội bộ.

Physical schema hitl_requests có type/status columns; payload không lặp type, response không lặp action/status. Pending là status=pending, terminal decision ghi response/resolved_at atomically. Outcome chỉ accepted approval; ask/deny/cancel/expire không copy response vào outcome. Result delivery dùng source_kind=hitl và request-derived message ID. Workflow effects_settled giữ cùng semantics.

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
- At dùng exact UTC calendar. Create/timing edit/resume có mốc đã qua dùng native backfill khoảng chứa mốc đó. Tick/backfill trùng được inbox dedupe theo nominal time.
- Interval/calendar/timezone/end dùng native ScheduleSpec; không tự viết cron, next-tick hoặc catchup engine. BUFFER_ONE bao delivery, không inference; giữ native recurring catchup policy.
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

Không wait inference, không occurrence ledger, không timer workflow tự chạy cron. Native schedules chỉ start workflow, vì vậy delivery workflow nhỏ này có trách nhiệm thật.

## 11. Retry, cancellation và liveness

Các giá trị sau là cấu hình khởi điểm, chưa đo:

| Nhóm | Native options và behavior |
|---|---|
| Local SQL | Start-to-close 5s; retry transient DB; business validation/conflict không retry |
| Effects/delivery | Bounded RPC deadlines, activity 1–2 phút; transient backoff; inactive là domain outcome |
| Cleanup/fanout | Activity 30 phút, heartbeat 15s và pulse khi chờ/theo batch; retry idempotently từ SQL |
| Runtime | Slice soft budget 5 phút tại checkpoint boundary; technical attempt start-to-close 30 phút, heartbeat timeout 10s/pulse khoảng 2s; transient retries native backoff không giới hạn attempts, không total schedule-to-close timeout; WAIT_CANCELLATION_COMPLETED |
| Workflows | Không whole-workflow retry policy; activity retries giữ effects. Agent/ScheduleChanges rotation theo native suggestion; không lifetime timeout |

Technical runtime timeout không xóa checkpoint hoặc kết thúc tuổi đời agent. Soft budget chỉ handoff ở boundary; hard timeout xử lý attempt treo. Tắt model SDK retry layer khi Temporal đã retry invocation; giữ native transport retry phù hợp. Permanent model/context/config lỗi hiện rõ, không catch-all success hoặc repair loop.

Working messages/summary và inbox batches phải có token/byte/count budgets. Native compaction giữ context hữu hạn, native pruning giữ recovery snapshots hữu hạn, Redis stream/cache và closed Temporal histories dùng native retention. Committed inbox/public history và receipts còn trong retention là dữ liệu bền vững, vẫn tăng theo sử dụng và cần dung lượng DB tương ứng; không tuyên bố chạy vô hạn với ổ đĩa cố định hoặc tự xóa product history.

Cancellation là cooperative; timeout không chứng minh code/RPC vật lý đã dừng. Cancel-current không rollback committed effects. Cleanup do Leta sở hữu chỉ báo xong sau producer/writer barriers và external effect settlement cần cho thao tác đó; không là ACK để core xóa workspace. LetFS authorization/mount/quota/version vẫn là boundary cuối. Không dùng terminate/ABANDON thay stop nội bộ Leta.

Provisioning lỗi terminal để resource provisioning và lỗi vận hành rõ; operator dùng native recovery hoặc delete. Không reconciliation service, orphan sweeper hoặc retry scheduler mới.

## 12. Platform và plan song song

```text
Leta → Platform: generic CheckWorkspaceActive, workspace/profile APIs
Leta → LetFS: storage discovery/provisioning, grants, file operations
Leta → SpiceDB: agent relations + agent.workspace/workspace.agent cùng batch, không workspace membership/storage writes

Platform mark workspace deleting
→ Platform gọi LetFS DeleteWorkspaceStorage
→ Platform hoàn tất resource graph/SQL cleanup

Leta gọi API tới resource đã xóa → nhận lỗi và xử lý phía consumer
Leta tắt/không được deploy → core vẫn startup/CRUD/delete bình thường
```

Không binding/list/stop callbacks hoặc stop-ACK barrier cũ. Async business cleanup về Leta được phép khi API đã chốt, không core readiness/hot-path dependency. RemoveMember chỉ thu hồi human membership; không đọc agent ownership, sửa workspace.agent hoặc stop/cleanup agent. Agent giữ identity/grants riêng dù human owner rời workspace; việc này không thêm workflow/activity. Không SQL/thread/queue Leta từ core; không schedule business activities vào queue service khác.

Rà soát active proto/handlers/config mới nhất ở [boundary review](boundaries.md). Đã đối chiếu [plan Platform/LetFS](../261111-1727-platform-letfs-rewrite/plan.md), [infra/CI](../261111-1727-platform-letfs-rewrite/infra-testing-ci-cd.md) và [YAML mẫu](../261111-1727-platform-letfs-rewrite/openlet.example.yaml). Archive report cũ ghi giữ source; tiến độ mới trong core plan báo archive nốt source/migrations/native dependencies và hash-check 60 files, đúng active apps/leta hiện absent. Lượt này không chạy lại hash audit. Không restore source/tests cũ hoặc sửa core-owned runtime/config trong lượt tài liệu này.

Actor subject/workspace/storage và core APIs đã chốt; schema đã reconcile. Concrete Leta API/transport/cleanup và multiple storage tiếp tục hoãn. Queues như `leta_bridge` chỉ thuộc worker/config Leta; ba queues vẫn một worker deployment/image, không core dependency. Database/Temporal namespace mới, không import data/checkpoint/HITL/schedule histories cũ hoặc jobs cũ vào database mới; database cũ giữ tới cutover riêng. Không tự chạy cutover trong bước thiết kế.

Idempotency table dùng đúng caller/method/key/request_hash/result bytea/expires_at của core. Leta durable receipts cần retention đủ dài; core file receipts mặc định 24h không tự trở thành dedupe nhiều năm. Phải chốt retry horizon/retention liên service trước khi hứa mutation không lặp sau outage dài; không thay core policy hoặc thêm ledger trong lượt này.

## 13. Files và verification tối thiểu

`jobs/agent.py`, `jobs/resources.py`, `jobs/hitl.py`, `jobs/schedules.py` chỉ chứa deterministic orchestration. Activities cạnh owning `agents.py`, `boxes.py`, `hitl.py`, `schedules.py`, `messages.py`, `runtime/agent.py`; worker đăng ký trực tiếp. Không bridges/commands/repositories framework mới.

| Check | Invariant cần chứng minh |
|---|---|
| Agent | Receive khi runtime đang chạy không mất wake; luôn có pending work vẫn qua nhiều slice/Continue-As-New; restart giữa chừng tiếp tục cùng logical run/checkpoint |
| Lifecycle | Xóa Leta/box do người dùng yêu cầu không tạo home muộn; cleanup nội bộ không tự đợi cùng bridge pool. Core workspace delete không đợi agent ACK |
| HITL | Answer-vs-expiry một winner; tool trả pending; đúng requester; teardown đợi grant nhưng không đợi delivery |
| Schedule | Native at/interval/calendar smoke; past-at dedupe; metadata không rearm; old command retry sau rollover không ghi đè edit mới; delete chặn late admission |
| Long-lived state | Native prune giữ pending tool/resume và public history; repeated slices giữ working context/checkpoint footprint hữu hạn; pause/cancel và transient recovery không mất inbox |
| System | Một journey chung với Platform/LetFS và workspace cleanup trong cùng dependency environment |

Không cần chạy test một năm: ép rollover sớm, dùng graph/model fixture luôn còn việc và restart worker trong một integration check ngắn. Không port tests/replay histories cũ, exact activity order hoặc mọi failure permutation. Native time-skipping cho workflow logic; native Schedule cần smoke thật. Không stack từng test hoặc E2E suite trùng infra plan.

## 14. Nguồn và giới hạn xác minh

SDK lock khảo sát: Temporal Python 1.35.0, LangGraph 1.2.20, checkpoint-postgres 3.2.0. Đã đối chiếu native semantics với tài liệu chính thức:

- [Updates, Update-with-Start và async handlers](https://docs.temporal.io/develop/python/workflows/message-passing).
- [Continue-As-New và handlers](https://docs.temporal.io/develop/python/workflows/continue-as-new).
- [Cancellation và activity heartbeat](https://docs.temporal.io/develop/python/workflows/cancellation).
- [Native schedules, backfill và delete](https://docs.temporal.io/develop/python/workflows/schedules).
- [Entity workflows và Update dedupe chỉ trong một execution](https://docs.temporal.io/design-patterns/entity-workflow).
- [Native graph breakpoints và resume bằng None](https://docs.langchain.com/oss/python/langgraph/interrupts#debugging-with-interrupts).
- [AsyncPostgresSaver.aprune](https://reference.langchain.com/python/langgraph.checkpoint.postgres/aio/AsyncPostgresSaver/aprune) và [keep_latest semantics](https://reference.langchain.com/python/langgraph.checkpoint.postgres/PostgresSaver/prune).

Đây là thiết kế mới, chưa SDK smoke/integration/replay tests, chưa benchmark LoC/CI/latency hoặc long-running workload. Chưa sửa runtime, archive source, đổi database hoặc khởi động process. Không hứa exactly-once cho model/shell/RPC; giữ idempotency ở durable mutation owners. Hoạt động nhiều năm cần hạ tầng/storage còn phục vụ và phục hồi dependency sau outage; permanent configuration errors vẫn cần sửa.
