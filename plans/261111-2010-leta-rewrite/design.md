# Leta viết mới: kiến trúc đề xuất cuối

Đã reconcile boundary/schema ngày 2026-11-12 theo [workspace resources đã chốt](../261111-1727-platform-letfs-rewrite/workspace-service-redesign.md) và [API Platform/LetFS](../261111-1727-platform-letfs-rewrite/api-contract.md). Root resource là agent subject độc lập; letas giữ workspace_id/storage_id/state/paused, agents giữ executable fields chung. Schema 11 bảng và constraint đã được duyệt; owner/operator ở SpiceDB. Runtime 24/7 giữ thiết kế đã chốt. Giữ dynamic mounts cho public/shared và private được cấp quyền; một storage_id là home binding. Concrete Leta API/transport, đổi home storage và physical cleanup integration tiếp tục hoãn.

Ngày 2026-11-11. Đây là đề xuất cho toàn bộ Leta; chưa thực hiện archive/implementation. Không dùng skill, subagent hoặc sửa legacy code trong khảo sát. [Plan thực hiện và acceptance](plan.md). [Rà soát API/boundary active](boundaries.md) ghi current proto/handlers, missing integration và decisions còn mở.


[Thiết kế Temporal cuối](temporal.md) chốt sáu workflow types, 21 activities và ba native queues trong một worker process; mô tả admission, retry/cancel, state ownership và cleanup ordering.

## 1. Quyết định chính

Viết mới Leta thành một Python service với API role và một worker deployment. Giữ LangChain/LangGraph, Temporal, Mirage, PostgreSQL, Redis và native SpiceDB client. Leta quản lý/check agent relations, ghi/dọn hai chiều agent.workspace và workspace.agent trong cùng native graph batch; Platform quản lý workspace/membership và generic CheckWorkspaceActive; LetFS quản lý storage/grants. Bỏ RegisterAgent/UnregisterAgent và đổi tên relation registered_agent thành agent theo quyết định 2026-11-12. Agent độc lập với membership của human owner; RemoveMember chỉ thu hồi human membership, không quét/dừng agent. Không SQL owner/grant mirror hoặc direct writes vào relations service khác sở hữu. Chi tiết tại [boundary](boundaries.md#71-removemember-và-agent-độc-lập).

Platform/LetFS vẫn application gRPC và Envoy JSON. HTTP/SSE là phương án Leta trước đây, không còn là transport đã chốt sau boundary review mới nhất; concrete API/transport để lượt riêng. Async owning business cleanup được phép khi đã có contract, không stop-ACK barrier/readiness hoặc permission hot-path dependency.

Không lấy ít bảng, ít workflow types hoặc một con số LoC làm tiêu chí duy nhất. Giảm cơ chế cần hiểu để thay đổi một tính năng. Một constraint/lock ngắn ngăn mất dữ liệu đáng giữ hơn hàng trăm dòng phục hồi hậu quả của việc bỏ nó.

Leta/Leti phải hoạt động liên tục 24/7 nhiều tháng, nhiều năm, kể cả không bao giờ hết việc. Logical agent/context không phụ thuộc tuổi đời một workflow run, activity attempt hoặc worker process; rollover/restart không yêu cầu người dùng tạo lại agent.

## 2. Bằng chứng và plan song song

Đã đọc root README/docs navigation, Leta design/tool contracts, schema, API, runtime/middleware/history, filesystem/cache policy và Temporal workflows/bridges. CodeGraph được dùng trước khi đọc source. Đã đọc plan rewrite Platform/LetFS mới nhất, final proposal, schema/config/query contracts, transport notes và archive report.

Snapshot khảo sát trước đợt archive tests/tooling mới nhất, đếm physical Python lines gồm blank/comment, không tính generated/dependencies/migrations:

| Phần active của Leta | Files | Lines |
|---|---:|---:|
| Production Python | 57 | 11.211 |
| Tests Python còn active lúc khảo sát, nay đã archive | 28 | 6.339 |
| Boundary tests đã archive trước đó | 16 | 4.402 |

Trong snapshot production cũ: HTTP 1.728 lines, runtime 2.294, Temporal 2.308, filesystem 998. `store.py` là 1.699 lines. Đây là kích thước source lúc khảo sát, không phải active tree mới, số đo chi phí chạy hoặc bằng chứng mọi dòng đều thừa.

Các nguyên nhân phức tạp quan sát được:

- `runs` lưu inbox cursor, checkpoint ID/namespace, continuation, result, attempt và yield state ngoài native saver; AgentWorkflow lại giữ cursor/run/continuation/paused/latest_seq.
- Cấu hình agent đi qua validate, lifecycle bridge, lifetime workflow, activity rồi SQL; caller đọc lại row để tạo response.
- Root/box lifecycle coordinators sống sau provisioning để nhận cả các lệnh mà một SQL transaction đã xử lý được.
- Runtime tự kiểm tra nhiều chi tiết model/tool protocol, tạo summary orchestration quanh native middleware và dùng public history như một phần replay mechanism.
- SSE có snapshot materialization, FreshReplay, started-block filtering và server-side coalescing ngoài Redis replay và UI reducer.
- Leta có FastAPI cùng một application gRPC server chỉ phục vụ binding/list/stop callbacks.

Nguồn kiểm chứng: `apps/leta/migrations/0001_agent_domain.sql`; `runtime/{runner,state,middleware,history}.py`; `temporal/{agent,lifecycle,box,schedules,bridges}.py`; `http/{agents,events}.py`; `transport/grpc.py`.

[Plan 261111-1727](../261111-1727-platform-letfs-rewrite/plan.md) mới hơn và có archive report thực tế, được dùng làm boundary hiện hành. Plan 261111-1649 còn mô tả Account/Workspace tách riêng và migrate Leta public sang gRPC; phần đó không phù hợp scope mới. Không tiếp tục theo nó.

Archive report core 261111-1727 lúc trước ghi archive Leta tests/tooling và giữ source/migrations/dependency files. Snapshot active tree 2026-11-12 không còn apps/leta; tiến độ mới trong core plan đã báo archive nốt source/migrations/native dependencies, 60 files đối chiếu hash. Lượt này không chạy lại hash audit. Core hiện đã có proto/generated Go/selected handlers mới; không dùng trạng thái implementation cũ trong plan làm bằng chứng runtime. Rewrite nội bộ Leta thuộc plan này; shared contracts/authz/config/infra do core owner quản lý, cần đồng bộ trước code. Chưa runtime mới được triển khai.

## 3. Khả năng sản phẩm giữ lại

- Root Leta là workspace resource và subject agent độc lập; current owner/operator và workspace gate quyết định quyền, không creator. Workspace owner có administrative delete, không tự động dùng agent/đọc private data.
- Root Leta và mỗi Leti có context/inbox độc lập. Whole-box graph bất biến, representative và các cạnh giao tiếp giữ nguyên; create box không tự gửi việc.
- Root nhận digest theo nguồn/cuộc trao đổi; Leti nhận đầy đủ batch mới. `read_at` chỉ là đã đọc chi tiết, không phải đã xử lý xong.
- Chỉ `send_message` chuyển lời. Không auto-forward final text, không child-human chat, không cross-box routing mới.
- Checkpoint, model selection/inheritance, public history/search, compaction, pause/resume và cancel current run vẫn có.
- Ask/approval không chặn toàn agent. Form giữ single/multiple/text và empty answer hợp lệ. Approval nhắm storage cụ thể, human có current manage_access cấp quyền root agent qua LetFS; không cấp cho creator hoặc từng Leti.
- Native at/interval/calendar schedules, timezone, recurring end, calendar view và nominal scheduled time giữ lại.
- Mirage shell/Monty, text operations, image reads, literal/semantic search, artifacts và per-box home restriction giữ lại. Một root home binding; external storages public/shared/private được cấp quyền truy cập bằng native dynamic mounts. Đổi home storage hoãn.
- Một AG-UI/SSE connection cho root và children; reconnect replay và committed history giữ lại. Cleanup do người dùng yêu cầu tại Leta thuộc nội bộ Leta; core workspace deletion không chờ agent cleanup.

Không thêm task engine, mutable graph editor, external channels, scheduler service, agent framework hoặc compatibility API.

## 4. Topology và transport

```mermaid
flowchart LR
    UI[Client] --> E[Envoy: Clerk JWT]
    E -->|transport Leta review riêng| A[Leta API]
    E -->|JSON transcoder| P[Platform gRPC]
    E -->|JSON transcoder| F[LetFS gRPC]
    A --> T[Temporal]
    W[Leta worker] <--> T
    W -->|native gRPC| P
    W -->|native gRPC| F
    W --> M[OpenRouter]
    A --> DB[(Leta PostgreSQL)]
    W --> DB
    W --> R[(Redis)]
    A --> R
```

Hai process roles: `python -m leta.api` và `python -m leta.worker`. Worker chạy ba native Worker instances: orchestration/effects, runtime, bridge activities chờ workflow Updates/results. Phân tách slot ngăn runtime/cleanup chiếm hết pool cần để xử lý chính Updates đang chờ; vẫn một worker process/deployment. Native activity concurrency giới hạn model/remote work. Không mở health webserver riêng trong worker.

Leta là gRPC client của Platform/LetFS, dùng generated stubs trực tiếp. Native Authzed quản lý/check agent owner/operator và hai chiều agent.workspace/workspace.agent. Platform quản lý workspace/membership; LetFS quản lý storage grants qua owning gRPC APIs. Leta không tự ghi workspace membership/owner hoặc storage grants. Không truy cập SQL/Qdrant service khác; S3 bytes chỉ qua signed URLs LetFS cấp. Core startup/readiness không cần Leta; async business cleanup không bị cấm nhưng API cụ thể chưa thiết kế.

Concrete Leta routes, transport, responses và cleanup methods review riêng. Schema/runtime không yêu cầu dual HTTP/gRPC server hoặc wrapper framework; không thêm proto/listener/deployment chỉ để phục vụ một contract chưa chốt.

Envoy giữ JWT validation và strip trusted actor headers. Leta lấy human identity từ trusted ingress; runtime inject root Leta actor vào native calls, model không chọn actor. Chỉ Envoy public; internal routes không có public route. Giữ MVP private-network trust đã chốt; không thêm service-token registry/caller-name authentication. Các process trong mạng trusted có quyền gọi internal methods, cùng giới hạn của plan song song.

Core giữ native ProtoJSON/HttpBody/google.rpc.Status; không ép Leta/schema nội bộ theo một shared HTTP error envelope. Error/stream contract riêng của Leta thuộc API review sau.

Schema này không mở lại lựa chọn HTTP/gRPC của Leta hoặc tự chốt API đang hoãn. Consumer contract Platform/LetFS hiện đủ rõ để sửa workspace/storage/authorization fields mà không quyết định transport Leta.

## 5. Một owner cho mỗi loại state

| State | Owner | Các nơi khác được giữ gì |
|---|---|---|
| Agents, boxes, messages, product history, HITL, schedule definitions | Leta PostgreSQL | IDs và response projections |
| Working messages, summary, inbox cursor, graph continuation | Native LangGraph PostgreSQL saver | `runs` không mirror checkpoint/progress |
| Wakeups, activity retry/cancel, timer, lifecycle execution | Temporal | Workflow giữ handles/flags để điều phối, không giữ bản progress thứ hai |
| Membership, agent/storage ownership và grants | SpiceDB theo owning service | Platform workspace/membership; Leta agent relations và hai chiều workspace binding; LetFS storage relations. Không SQL owner/grant mirror |
| File tree/bytes/version/quota | LetFS | Root giữ một storage_id, boxes giữ directory IDs; không scope/personal mapping |
| Provisional events và Mirage cache | Redis | Không canonical history hoặc execution state |

Một public history khác working context là cần thiết: compaction không được xóa lịch sử mà người dùng xem. Tuy nhiên history không trở thành một workflow journal để dựng lại agent bằng code tự viết.

## 6. Inbox và agent execution

1. Caller có stable message ID. Native Temporal Update-with-Start gọi admission SQL activity; message chỉ được ACK sau commit. Không thay bằng SQL INSERT rồi best-effort signal vì sẽ tạo khoảng mất wakeup.
2. SQL transaction kiểm route/liveness và cấp `seq` bằng counter của recipient. Counter được serialize trên đúng agent row, cùng transaction INSERT; không dùng global sequence làm committed high-water vì concurrent commit có thể đảo thứ tự.
3. Workflow `Agent` duy nhất theo agent ID đánh dấu có việc và chạy runtime activity slices hữu hạn. Workflow không giữ notified cursor hoặc graph continuation. Nhận thêm input trong khi activity chạy chỉ wake vòng tiếp theo.
4. Activity mở stable LangGraph thread theo agent ID, lấy checkpoint native và đọc inbox sau cursor đó. Root dựng digest, Leti dựng full batch. Cursor và batch vào cùng checkpoint. Không cursor advancement trước khi batch hợp lệ/đủ context.
5. LangChain `create_agent` chạy model/tools. Giữa model/tool boundaries mới nhận input/control và refresh mounts/config. Không poll PostgreSQL từng token.
6. Khi graph idle, activity hoàn tất và Workflow chờ input. Khi vẫn còn việc nhưng hết soft slice budget, activity return yielded tại native checkpoint boundary và Workflow tiếp tục cùng logical run. Một wakeup trùng có thể tạo lượt kiểm tra rỗng, chấp nhận được; không xây scheduler protocol để tối ưu nó.

Giữ session advisory lock theo agent trong activity để ngăn hai Temporal attempts cùng ghi một thread. Đây là nguy cơ ghi đè context/effect thật, không phải edge case chỉ để tăng coverage. Không lock toàn Leta/workspace, không lease/epoch/fencing framework.

`runs` phục vụ UI/history/cancel, không resume agent. Bỏ `checkpoint_id`, `checkpoint_ns`, `continuation`, `inbox_cursor`, `attempt`, `yield_requested` và result snapshot khỏi bảng này. Native saver quyết định resume.

Pause/resume toàn Leta dùng finite lifecycle operation để lưu desired root pause rồi fanout control refresh bền vững; runtime dùng native interrupt tại safe boundary. Cancel current run dùng native activity cancellation để trả quyền điều khiển và giữ checkpoint; node chưa checkpoint có thể chạy lại khi resume. Không tuyên bố rollback effect đã commit. Delete dùng stop/cancel rồi đợi runtime thực sự thoát và nhả writer lock. Không tạo riêng interrupt kind cho history rotation.

Agent workflow dùng native Continue-As-New sau slice và handlers đã xong; không chờ inbox rỗng hoặc graph hết việc. Runtime dùng native breakpoints sau model/tools, sync checkpoint và soft slice budget khởi điểm 5 phút; resume cùng thread bằng None. Slice là technical handoff, không tạo UI run mới hoặc product step limit, không cancel model đang chạy chỉ để rollover. Model/tool calls có deadline; hard attempt timeout là 30 phút, không giới hạn tuổi đời agent.

Rollover đóng admission trên run cũ trước khi drain handlers; caller retry cùng message/request key vào workflow ID, không pin Run ID. Không lifetime timeout cho Agent/ScheduleChanges. Transient runtime errors dùng native backoff đến khi dependency phục hồi; permanent config/context errors vẫn cần xử lý. Deploy workflow changes dùng native Temporal patch/versioning.

Model/effort resolve một lần mỗi safe boundary; inherit từ root nếu child không override. Validate catalog tại startup và configuration write; không scan mọi agent rồi revalidate toàn bộ catalog mỗi startup. Sai persisted model config báo lỗi đúng agent khi chạy.

Compaction dùng native SummarizationMiddleware và native saver; cấu hình budget theo catalog. Một boundary check từ chối input thật sự không vừa, không tự viết vòng summary/re-summary/protocol repair. Không dump hidden reasoning ra summary/history. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [native summarization](https://docs.langchain.com/oss/python/langchain/middleware/built-in).

Cuối slice, dưới writer lock, dùng native AsyncPostgresSaver.aprune(strategy="keep_latest") để giữ latest recovery checkpoint cùng pending writes và bỏ snapshots cũ. checkpoint-postgres 3.2.0 đã có API này; không custom saver, SQL xóa bảng nội bộ hoặc retention service. Không bật DeltaChannel/time travel. Working context và inbox batches có token/byte/count budgets; Redis và closed Temporal history dùng native retention. Public history/inbox/receipts vẫn là dữ liệu lưu lâu dài, cần dung lượng tương ứng và không bị tự xóa bởi compaction/pruning.

## 7. Tools, side effects và history

Feature functions là code nghiệp vụ thật; HTTP routes, tools và activities gọi cùng functions. Feature function nhận concrete pool/clients và trusted actor/context, không repository/usecase/interface factories.

Tool đọc có thể nhận ID hoặc tên để tiện tìm; tool gây thay đổi phải xác định stable target ID trước effect. Ví dụ delete box dùng ID lấy từ roster/list, không resolve lại tên sau crash rồi xóa một box khác vừa tái sử dụng tên đó. Đây là thay đổi tool schema có chủ ý, không giữ name-write adapter.

Business effects dùng ID ổn định từ agent/message/tool-call identity. Message/HITL/box dùng unique domain ID; LetFS non-idempotent mutation dùng request key native của LetFS; permission grant dùng native idempotent write/owner contract. Không bọc mọi tool bằng permanent exactly-once ledger.

Native checkpoints giữ completed tool outputs. Bỏ SavedToolResults replay layer riêng và việc serialize toàn bộ ToolMessage vào public activity row để phục vụ replay. Crash trước checkpoint có thể gọi lại tool; owner idempotency bảo vệ durable mutations. Một Mirage shell/Monty command có nhiều effects có thể chạy lại; từng domain mutation vẫn có boundary bảo vệ, không hứa exactly-once cho toàn command.

History ghi input, assistant/tool calls/results, final note và compaction theo stable entry IDs. Dùng một normalization boundary chỉ expose public text/tool args/results/file references; không raw provider payload, hidden reasoning hoặc image base64 ở UI history. `INSERT ... ON CONFLICT` theo event identity xử lý retry; không protocol identity registry riêng.

History search dùng PostgreSQL text search đơn giản theo agent, không embedding/memory service. Pagination keyset; list không trả toàn bộ bodies/tool output. Không duplicate mỗi business check trong route, mapper, store và activity.

## 8. Lifecycle, HITL và schedules

### Lifecycle

Agent config, metadata/list/history và immutable graph creation SQL không đi qua lifetime root/box mutex. Root/box create/delete đi qua workflow hữu hạn vì thật sự có graph/storage/worker effects. `LetaLifecycle` chạy đúng một create/delete/pause/resume operation rồi kết thúc; pause/resume cần durable fanout để không bỏ sót paused children. `BoxLifecycle` chỉ create/delete.

Create: durable Temporal admission và local SQL transaction; root gọi Platform CheckWorkspaceActive, kiểm quyền tạo tại admission và ghi agent.workspace/workspace.agent cùng owner/operators trong một native graph batch, rồi CreateStorage qua LetFS; box tạo home directory trong storage của root. Không bước/trạng thái registration riêng; quyền chạy không phụ thuộc membership owner về sau. SQL và graph không chung transaction. Sau external ACK mới chuyển active. Delete: đóng admission trước, settle provisioning, schedules/HITL effects và agents, xác nhận producer/writer barriers, trash box home và xóa hai chiều workspace binding trong cùng graph batch; physical graph/storage cleanup theo contract còn hoãn, cuối cùng archive rows để giữ history. Root cleanup gọi concrete box cleanup function inline; không chờ BoxDelete workflow đang xếp hàng trên cùng bridge pool. RemoveMember không đi vào lifecycle này.

API lifecycle chỉ báo đã nhận sau durable admission; API timeout không hủy workflow. Retry dùng operation identity cũ, không tạo root/box mới. Không SQL commit rồi đợi một best-effort workflow start mà không có retry path.

Có hai lifecycle workflow types cụ thể, không generic ResourceChanges/command dispatcher. Không cần giảm tổng số workflow types bằng cách gom các luồng khác nhau vào một engine.

### HITL

Một HitlRequest workflow sống đúng đời request: pending, answer/expiry/cancel, grant nếu có, inbox delivery rồi kết thúc. Tool trả pending ngay, không giữ stack hoặc pause toàn agent. Không dùng native dangerous-tool approval để thay async product HITL vì semantics khác nhau.

SQL conditional transition bảo vệ answer-vs-expiry và duplicate responses. Decision và grant outcome phải phân biệt: người dùng chấp nhận chưa có nghĩa grant đã thành công. Trước grant kiểm root/resource còn active và current storage.manage_access của addressed human. Native retry, không receipt/journal grant thứ hai.

Kết quả vào đúng requester bằng stable outcome message ID. Khi người dùng xóa Leta/box, cleanup nội bộ đợi grant effect đã settle trước khi báo xong thao tác của Leta; không đợi result delivery vào inbox đã đóng. Admission gate khiến queued delivery trả skipped. Storage grant/revoke qua LetFS theo current approver rights/native graph semantics, không globally exactly-once. Đây không phải barrier hoặc ACK để Platform xóa workspace storage.

### Schedules

Giữ `schedules` PostgreSQL vì UI/calendar cần definitions và history ngay cả khi Temporal preview unavailable; native Temporal sở hữu timing/execution. Không chuyển definition authority hoàn toàn sang Temporal rồi mất SQL product view hoặc dựng cache/reconciler mới.

Giữ một ScheduleChanges workflow nhỏ theo schedule để serialize SQL definition và native Schedule API. Đây là coordinator có lý do cụ thể, khác việc bắt mọi agent metadata edit qua lifecycle workflow. Không xóa nó để thay bằng dual-write best effort hoặc application lock giữ qua remote I/O.

Actor cũng Continue-As-New theo native suggestion để hoạt động nhiều năm edits. Canonical pending command/normalized timing ở native Temporal history. Receipt dùng đúng schema core và chỉ finalize applied outcome sau native ACK; next command/CAN chờ accepted handler settle. Retry completed command qua rollover trả receipt, không apply definition cũ. Không result-pending bag/completed_at, processed-ID set hoặc journal riêng; pure-SQL metadata edit finalize receipt cùng transaction.

Native schedule action khởi ScheduleDelivery ngắn, dùng nominal scheduled time tạo occurrence message ID, kiểm current source/target rồi giao inbox. BUFFER_ONE chỉ bao delivery, không bao thời gian LLM chạy. Không custom cron/parser/calendar engine, occurrence table hoặc exactly-once timer machinery.

Pause cho phép occurrence đã được admit; delete đóng source để chặn delivery muộn, không retract message đã commit. Metadata-only edit không rearm one-shot đã chạy. Calendar query dùng native matching-times trong range hữu hạn, trả đủ kết quả hoặc yêu cầu hẹp range; không silently truncate.

## 9. Schema mới đã duyệt

[Field audit](schema.md) và [DDL review](schema.sql) sở hữu schema 11 bảng cho database mới. Không lấy số bảng/cột/constraint làm target tối ưu. [Boundary review](boundaries.md) ghi box home-ID provisioning chưa khớp native LetFS API; chưa đổi nullability/core contract đã duyệt.

| Bảng | Nội dung |
|---|---|
| letas | Root resource workspace/storage binding, lifecycle và desired pause |
| agents | Common executable identity/profile/prompt/model/inheritance và inbox/history counters |
| boxes | Immutable graph container, representative, home directory và lifecycle |
| box_edges | Allowed undirected pairs |
| agent_messages | Agent-only delivery, committed seq/source/conversation/reply/body/nominal time/read state |
| user_messages | Explicit root-to-human delivery; chat UNION với user inputs, không duplicate body |
| runs | Logical status/cancel/correlation; không runtime progress |
| history | Public transcript/search, không checkpoint/replay authority |
| hitl_requests | Scalar type/status, typed payload/response và actual external outcome |
| schedules | Creator/target/title/content, scalar type, timing spec và desired pause/delete |
| idempotency_keys | Cùng caller/method/key/request_hash/result bytea/expires_at của Platform/LetFS |

Root resource ID đồng thời root executable agent ID; root create ghi hai rows cùng transaction. Leti state/control suy từ letas + box. Source hitl là request result, khác direct user chat; source box suy actual sender từ immutable representative. Schedule/HITL discriminators không giấu/lặp trong JSON. Không owner/creator mirror, personal mapping hoặc arbitrary lifecycle/progress columns.

Giữ PK/FK/UNIQUE/CHECK thật: same-root membership, same-box representative/edges, naming/home isolation, positive committed order/counters, one unfinished run, same-agent history/run, status/timestamp/outcome consistency. Không đẩy relational checks sang application chỉ để giảm constraint count. Polymorphic source/cross-table reply và typed JSON validate tại owning boundary.

Pure-SQL effects/receipts atomic local; lifecycle admission receipt chỉ ACK admitted identity. Schedule pending work thuộc Temporal, SQL desired definition → native ACK → finalized receipt trước nhả ordering. Không SQL transaction qua RPC hoặc distributed atomicity claim. Native saver quản lý checkpoints, public history độc lập. Concrete cross-service retry horizon và Leta transport/cleanup vẫn review riêng.

## 10. Filesystem và cache

[Đề xuất chi tiết](filesystem.md) đối chiếu archive và native contracts, gồm một thay đổi đề xuất thêm: không dùng persistent file cache ở bản đầu. Phần cache và policy.py dưới đây là baseline trước đề xuất đó, chưa tự sửa thành quyết định đã duyệt.

Mirage vẫn là command/VFS engine; Monty vẫn là sandbox. Viết adapter LetFS mới theo proto/stat/version của plan song song, không port LetFSVFS/fingerprint/observed-ID implementation cũ.

- Agent dùng `~`/`~/...`; Mirage expand qua virtual HOME=/home. Root home dùng root.storage_id/root node từ GetStorage; Leti home dùng box.home_node_id trong cùng storage. Locators/raw IDs và cả hai đầu copy/move mang containment root theo mount tới LetFS.
- Giữ dynamic external mounts `/mnt/<storage_id>` từ LetFS ListStorages bằng root actor, gồm public/shared và private được grant trực tiếp/HITL. Refresh ở safe tool boundaries bằng native Mirage mount APIs; native LetFS kiểm quyền mỗi operation. Không external alias cho home storage_id, không Platform ListAccessibleScopes/per-user resolver hoặc `/shared`/`/users` mapping. Không đổi home binding hoặc thêm SQL mount/grant mirror.
- LetFS kiểm quyền/tree/mount containment/readonly artifacts/quota/version. Leta không lặp tree validation trong SDK; cache hit vẫn phải đi qua native admission trước khi expose bytes.
- Mirage FRESH/cache hook so current native metadata/version với cached representation. Nếu pinned dependency không cung cấp fingerprint cần thiết thì adapter tính đúng representation token nhỏ từ fields hiện có, không thêm persistent revision hoặc global invalidation bus.
- Text nằm PostgreSQL, blob nằm S3, chỉ LetFS expose bytes/metadata/artifact tree/image preview. Không lấy lại thuật ngữ revision/generation cũ để ép LetFS thay schema `files.version`.
- TextSearch/ReadTree/ReadImage là native APIs đã có trong plan; adapter không dựng grep/image/parser engine thứ hai. SemanticSearch giữ riêng literal search.
- `rm` là trash. Sandbox không host filesystem/environment/network; chỉ native cache connection được runtime cho phép. Giới hạn text/image/command output giữ budget cần thiết cho memory/context.

Workspace/session tạo theo invocation rồi đóng. Refresh ở safe boundaries; quyền mới dùng cho request mới, không cố thu hồi bytes đã nằm trong transcript. Không optional cache bypass hoặc RAM permission authority.

## 11. Redis/public events, transport review riêng

Phần replay/bootstrap dưới đây giữ như phương án nội bộ cho API review sau; không chốt lại HTTP/SSE transport đã được người dùng hoãn. Không thêm schema fields vì transport.

Một Redis Stream theo root Leta. Envelope chỉ có root/agent/run IDs và AG-UI event; Redis ID làm SSE cursor. Dùng native XADD/MAXLEN/expiry để giữ replay hữu hạn, không custom byte-accounting Lua hoặc stream per run.

`events.py` làm ba việc: public normalization/AG-UI events đang dùng, Redis append/read, HTTP SSE framing. Không server-side UI reducer, FreshReplay state machine hoặc coalescing/reordering engine. Coalescing render thuộc UI; có thể batch network writes mà không đổi event IDs.

Kết nối mới: chụp stream tail, lấy bounded committed PG snapshot, rồi đọc suffix sau tail. Client upsert committed entries bằng stable message/entry ID để xử lý snapshot trùng live event. Committed entry hoàn chỉnh thay provisional entry cùng identity.

Reconnect có Last-Event-ID hợp lệ: replay đúng suffix rồi live, không reset chỉ vì worker attempt đổi. Cursor đã trim/log mất: gửi `resync_required`, lấy lại committed snapshot rồi tiếp tục live. Native heartbeat, send timeout và periodic permission check giữ connection hữu hạn/đúng quyền.

**Đánh đổi có chủ ý:** kết nối mới không tái dựng token prefix chưa commit đã sinh trước lúc kết nối. Có thể thấy phần output đang chạy bị thiếu đầu cho đến lúc committed entry thay thế. Reconnect với cursor còn hợp lệ vẫn giữ suffix. Đây là thay đổi so với FreshReplay hiện tại, phải ghi vào UI contract; không nói toàn bộ semantics cũ được giữ nguyên.

Redis outage không được làm rerun effect đã commit. Log publication failure và cho client resync về PostgreSQL; không thêm durable event outbox chỉ để replay mọi provisional token. Redis vẫn là dependency bắt buộc cho startup/cache, không có execution mode riêng khi bỏ Redis.

## 12. Cấu trúc thư mục hoàn chỉnh

```text
apps/leta/
  pyproject.toml
  package.json
  Dockerfile
  migrations/
    0001_initial.sql
  src/leta/
    __init__.py
    api.py                    # API/lifespan wiring; transport review còn hoãn
    worker.py                 # Temporal registrations và graceful shutdown
    config.py                 # owning YAML settings và model catalog
    db.py                     # concrete pool/transaction + SQL error boundary
    auth.py                   # trusted actor + current native agent permissions
    agents.py                 # models/functions/SQL/routes của Leta
    boxes.py                  # immutable graphs + functions/SQL/routes
    messages.py               # inbox/routing/delivery + functions/SQL/routes
    history.py                # public types/projection/search + SQL/routes
    hitl.py                   # type/status/forms/response/outcome + SQL/routes
    schedules.py              # product definitions/native Schedule API/routes
    events.py                 # AG-UI normalization/Redis; SSE còn review
    runtime/
      agent.py                # create_agent, model, native saver, runner activity
      inbox.py                # native middleware cho input/control boundaries
      tools.py                # tool schemas + calls tới feature functions
      history.py              # native middleware cho public records/compaction
    filesystem/
      workspace.py            # home/box binding, dynamic mounts, session và Monty
      letfs.py                # concrete Mirage VFS implementation
      policy.py               # authorization/version trước cache hit
    jobs/
      agent.py                # inbox/update/control và activity scheduling
      resources.py            # finite Leta/Box create/delete workflows
      hitl.py                 # request timer/grant/outcome delivery
      schedules.py            # definition changes và occurrence delivery
  tests/
    conftest.py               # một dependency environment mỗi run
    test_rules.py
    test_runtime.py
    test_filesystem.py
    test_api.py
    integration/
      test_agent_journey.py
      test_cleanup.py
```

Không tạo empty files cho đủ tree. Modules là boundaries cụ thể; không một file per RPC/tool/DTO. Pydantic types đặt cạnh feature, functions/SQL cùng feature, transport handler gọi trực tiếp functions. `runtime` chứa integration với agent library; `jobs` chứa deterministic orchestration; chúng không giữ bản domain service thứ hai. API entrypoint/routes cụ thể sẽ theo transport được review sau.

Bỏ nguyên các cây cũ `http/`, `temporal/`, `transport/` và `store.py`, `domain.py`, `lifespan.py`, `rebuild.py` trong active implementation. Không di chuyển chúng rồi đổi tên và gọi là rewrite. Migrations dùng native migration tooling chung; native saver setup tại migration task, không tự viết migration engine hoặc chạy schema setup mỗi request.

## 13. Contract với các service viết song song

[Boundary review](boundaries.md) là inventory hiện hành: native actor headers, provisioning input, file/mount/grant APIs, inbound API còn hoãn, cleanup independence và các gaps đã tìm từ active code. Chưa có Python gRPC consumer hoặc new Leta app trong active tree.

| Boundary | Chốt cho implementation |
|---|---|
| Platform/LetFS → Leta | Async owning business cleanup được phép khi có API; không stop-ACK barrier/readiness/authorization hot path. Concrete API chưa chốt |
| Leta → Platform | Generic CheckWorkspaceActive và BatchGetUsers/workspace APIs qua native gRPC; bỏ RegisterAgent/UnregisterAgent, không storage discovery/grants proxy |
| Leta → LetFS | CreateStorage/GetStorage/ListStorages/SetStorageAccess và native file operations, locator + containment root, text/blob/files.version/request key |
| Rights | SpiceDB canonical; Leta quản lý agent owner/operator và hai chiều agent.workspace/workspace.agent, Platform workspace/membership, LetFS storage ownership/grants. eligible_actor = participate + agent; RemoveMember chỉ tác động human. Không SQL owner mirror; native checks/bulk theo minimize_latency/optional ZedToken |
| Shared config | Cùng OPENLET_CONFIG/YAML và role-scoped ENV references, models.leta; không model JSON hoặc app service tokens cũ |
| Telemetry | Native OTEL outbound + JSON stdout, không metrics HTTP server/telemetry framework mới |

Ba callback binding/list/stop và barrier cũ đã bỏ. Core được phép dispatch cleanup business operation về Leta sau khi API được review; không chờ runner ACK trước core storage delete. RemoveMember không đọc agent ownership hoặc thu hồi workspace.agent, không SQL/thread/queue Leta. In-flight signed transfers giữ expiry semantics core; physical cleanup/history retention Leta chưa được tự chốt.

Actor/storage model và core APIs đã chốt. Schema này đã bỏ creator/scope fields, dùng agent subject và một storage_id làm home binding; dynamic access mounts không cần SQL mới. Còn concrete Leta public/access/cleanup APIs, transport và đổi home storage hoãn; không thêm registry/table/endpoint để bù phần đang hoãn. Shared contracts/authz/YAML/infra thay đổi phải đồng bộ core owner trước code.

Worker queues là settings của Leta, core không đọc hoặc validate chúng. Leta-only queue như `leta_bridge` không là điều kiện chạy Platform/LetFS/ingest. Chưa thêm Leta client/listener vào core khi cleanup API/transport chưa được review. Native Compose profile `leta` cho phép deploy/test tích hợp khi chọn; core startup/readiness/permission hot path không phụ thuộc Leta.

## 14. Test và CI ở knee point

Archive toàn bộ Leta tests/fixtures/replay/crash harness hiện tại. Không dùng test đỏ làm lý do phục hồi old code. Tests mới viết từ invariant và journey; deterministic model stub chỉ để điều khiển model/tool sequence trong test, production không có fake provider.

| Check | Bằng chứng cần có |
|---|---|
| Fast rules | Allowed messaging graph/actor; mixed HITL forms; model inheritance; schedule normalization |
| Runtime | Inbox không mất/không duplicate; luôn có việc vẫn qua slices/rollovers; worker restart phục hồi cùng logical run; native prune/compaction giữ resume và public history |
| Filesystem | Native pinned Mirage read/write/search; cache hit sau revoke; raw ID/copy endpoints không thoát box mount; readonly artifacts |
| API/events sau transport review | Một mutation với current owner/operator permissions, transfer/revoke; live event + replay/resync theo contract được chốt, không lộ internal route hoặc hidden reasoning |
| Agent integration | Owner → Leta → box/Leti → question + schedule → human answer → đúng requester → owner result, gồm retry một durable mutation |
| Cleanup integration | Người dùng xóa Leta/box thì settle công việc của Leta; resource core bị revoke/xóa được xử lý ở consumer; async business cleanup nếu có theo API đã review, không core stop barrier |

Không lập matrix mỗi method × HTTP/gRPC/SDK/store/activity × mọi failure boundary. Không snapshot exact graph/middleware order, exact file count, every config key, library parser/protocol internals hoặc tất cả Continue-As-New timing permutations. Mount/permission/data-loss checks được ưu tiên vì hậu quả thực.

Chứng minh long-lived execution bằng forced rollover sớm, graph/model fixture luôn có việc, retry command cũ qua rollover và một worker restart. Đây là integration check ngắn trong môi trường chung, không chờ test chạy hàng tháng hoặc thêm một soak stack vào mỗi PR.

PR Leta chạy lint/import/build, fast behavior checks và focused integration khi runtime/domain/boundary đổi. Dùng một shared disposable dependency environment; không Docker stack từng test. Contract/SDK đổi chạy affected consumers. Cross-service journey gộp vào journey đã có ở plan Platform/LetFS; không tạo E2E suite trùng.

Real-provider quality, full restore và long-running soak chạy trước release/theo lịch phù hợp. Không trả chi phí inference/OCR toàn stack trong mọi PR. Một resume check thật cần hơn hàng chục fake crash-worker scripts.

## 15. Archive, viết mới và cutover

1. Dùng archive/progress record mới của core: apps/leta absent sau batch archive source/migrations/native dependencies đã báo hash-check 60 files. Kiểm actual inventory/dirty tree trước tạo app mới. Nếu còn source cần archive thì giữ dirty diff/hash và snapshot riêng, không ghi đè archive trước. Không recreate/restore old source/tests để thực hiện lại archive hoặc copy sang app mới.
2. Tạo `apps/leta` mới từ contracts/design. Archive chỉ để tra ngữ cảnh; không copy/paste handwritten implementation, SQL implementation hoặc tests. Generate native stubs còn cần từ active contracts mới.
3. Viết từng feature bằng concrete libraries/SQL. Không tạo adapter/re-export/legacy route để pass tests cũ. Cập nhật callers/config/exports/manifests/build/test discovery cùng scope.
4. Dùng database mới theo quyết định plan song song, không import domain data/checkpoints/HITL/schedules cũ. Temporal namespace mới cho bộ database mới; dừng old writers/native schedules trước cutover, không để jobs cũ phát việc vào database mới hoặc replay histories cũ bằng worker mới.
5. Giữ nguyên database cũ tới cutover riêng; backup/restore path trước thay đổi vận hành. Không viết importer, checkpoint converter, compatibility migration hoặc tự reset môi trường đang dùng. Baseline schema chỉ tạo trong database mới.
6. Cutover consumer Leta theo gRPC contract core được hỗ trợ; không phục hồi callbacks binding/list/stop hoặc buộc core chờ deploy/health Leta. Async business cleanup theo API được review riêng. Không dual write/dual serve. Nếu cần rollback, dừng new writers và restore/deploy bộ cũ phù hợp snapshot; không merge hai lịch sử ghi.

## 16. Giới hạn và định nghĩa hoàn thành

Chấp nhận provisional tokens mất khi replay hết hạn, partial output trên kết nối hoàn toàn mới, shell multi-effect có thể chạy lại sau crash, native dependency outages và ordinary-read revoke freshness theo chính sách SpiceDB đã chốt. Các giới hạn này không cho phép lộ quyền, mất committed inbox hoặc nhân đôi non-idempotent mutation. Core có thể xóa workspace/storage khi Leta còn chạy hoặc đang tắt; consumer xử lý lỗi API, không có stop barrier xuyên hệ thống. Cleanup do người dùng yêu cầu trong Leta vẫn phải bảo vệ công việc/dữ liệu do Leta sở hữu.

Không cam kết LoC/latency/CI savings trước implementation. Đo handwritten production/tests/generated riêng; exclude archive/dependencies/build. Đo CI elapsed/container starts và các journey thường dùng; không thêm benchmark framework trong đợt rewrite chỉ để chứng minh một con số.

Hoàn thành khi toàn bộ khả năng ở mục 3 và behavior checks mục 14 chạy qua active implementation mới, parallel boundaries khớp, archive không nằm trong build/import/tests, và các giới hạn đã công bố đúng implementation. Ít code hơn nhưng bỏ mất capability hoặc thay bằng cơ chế tự chế lớn hơn không đạt.

Khảo sát hiện tại chỉ xác minh source/docs và upstream capabilities. Lượt này chỉ cập nhật plan/schema artifacts và rà soát selected active core contracts/code; chưa archive thêm, chạy build/tests/Envoy/provider, đo performance hoặc thay database. Không có owned background process.
