# Rà soát toàn bộ Leta: I/O, runtime và phần nên bỏ

Ngày 2026-11-14. Review baseline hiện tại, chưa sửa application code hoặc commit.
Owning implementation: [inference/runtime plan](../261114-0035-inference-prompts-compaction/plan.md).

## Phạm vi và cách đọc kết quả

Đã đọc toàn bộ `apps/leta/`: 23 Python source files/6.529 dòng, ba Python test
files/265 dòng, migration, Dockerfile và pyproject; tổng cộng 29 tracked files.
Đối chiếu các owning plans, selected shared SDK/LetFS handlers và pinned Mirage
0.0.8 public source khi cần xác minh boundary. Không đọc secrets hoặc archive
để copy implementation. Không sửa app, thêm dependency hoặc bật service.

P1: ưu tiên vì nằm trên đường chạy thường xuyên hoặc có thể retry vô ích.
P2: sửa gọn trong owning code khi có lợi rõ. F04/F07/F18 ban đầu cần review,
đã được người dùng chốt sau report; xem decision ledger §8. Số RPC/SQL dưới đây
được xác định từ source/probe, không phải benchmark latency hoặc throughput.

## Những điểm cần sửa

### F01 — P1: dựng runtime lại sau mỗi bước

[`runtime/agent.py:379`](../../apps/leta/src/leta/runtime/agent.py#L379): mỗi
boundary lại đọc config/profile, tạo client, tool list, prompt, budget,
SummarizationMiddleware và create_agent. Bước chỉ chạy tools cũng trả giá setup.
Current time thay system prefix mỗi bước; summary thay system và flatten XML.

Giữ các sửa đã duyệt ở [design §11](../261114-0035-inference-prompts-compaction/design.md#11-runtime-optimization-và-box-context):
graph/catalog/hooks một lần/activity; client và static overhead reuse; settings
đổi đồng bộ qua native request hooks; box snapshot; LF variables/composition;
cache-friendly native compaction. Giữ native routing, guards, checkpoint và
outer boundary loop. Không đặt mục tiêu giảm file xuống một số LoC tùy ý.

### F02 — P1: projection có I/O theo từng entry

[`agents.record:161`](../../apps/leta/src/leta/agents.py#L161),
[`project:103`](../../apps/leta/src/leta/runtime/agent.py#L103),
[`events.publish:49`](../../apps/leta/src/leta/events.py#L49).

Mỗi entry mới: lock agent, SELECT ID, UPDATE counter, INSERT; thêm BEGIN/COMMIT
riêng. Mỗi event Redis lại mở pipeline XADD+EXPIRE rồi execute. Ba tool results
mới là 3 history transactions/12 data statements và 6 Redis pipeline executions.
Hai vòng lặp chuyển message thành entries không phải thuật toán N²; lỗi là I/O
nằm trong vòng lặp entry. Startup recovery còn gặp lại IDs đã có.

Thay writer bằng batch thật: ordered entries/dedupe trong RAM; một transaction,
một lock, lookup IDs theo batch, tăng counter một lần, multi-row INSERT. Sau
commit gửi ordered individual events bằng một Redis pipeline, EXPIRE một lần.
Giữ canonical IDs/sequence/notifications/recovery. Sửa Live text ID namespace
mismatch đã chứng minh; không thêm outbox, ledger hoặc joint saver transaction.

### F03 — P1: lỗi nghiệp vụ qua Temporal có thể rơi vào retry infrastructure

[`ToolEffects:57`](../../apps/leta/src/leta/runtime/agent.py#L57) chỉ đổi trực tiếp
ValueError/LookupError/PermissionError/OSError thành ToolMessage error. Các tools
gửi inbox, tạo box, HITL và schedule có thể nhận WorkflowUpdateFailedError từ
Temporal; generic exception path hiện re-raise. RETRY không liệt kê wrapper này.

Probe native failure converter xác nhận wrapper có type WorkflowUpdateFailedError,
non_retryable=false, dù inner ApplicationError(ValueError) non_retryable=true.
Không được suy wrapper tự có cùng retry classification như lỗi bên trong. Có
nguy cơ activity retry lại pending tool thay vì cho model sửa yêu cầu.

Map đúng các known domain rejections ở native Temporal boundary vào existing
tool error feedback; infrastructure failures vẫn raise. Kiểm actual nested
ActivityError/ApplicationError shape trong focused integration. Không catch-all
success, custom retry framework hoặc workaround cho LangChain issue33504.
Đồng thời sửa tool metric khi handler trả ToolMessage(status=error).

### F04 — đã chốt: EXISTS chưa loại hết activity rỗng

[`jobs/agent.py:46`](../../apps/leta/src/leta/jobs/agent.py#L46) đặt wake=true khi
admit input; workflow chỉ clear trước khi bắt đầu activity ở line117. Inbox
middleware có thể đã consume input đó trong activity, nhưng không clear được
workflow wake flag. Sau completion workflow vẫn có thể khởi động activity mới.
Runtime mới lại setup run/checkpoint/prompts/trace trước khi thấy inbox đã rỗng.

Đính chính: EXISTS giúp xử lý input mới ngay trong current activity; không bảo
đảm không còn follow-up activity. Không được clear wake vô điều kiện vì input
có thể tới giữa lần kiểm tra cuối và activity completion.

Hướng sửa đã chốt: dùng seq đã có trong admit response và inbox_cursor
đã có trong graph state, trả consumed cursor cùng activity result để workflow
phân biệt input đã xử lý với wake mới. Không thêm DB column, polling hoặc
recovery cursor table. Đây là thay đổi activity/workflow result contract;
chưa triển khai hoặc tự quyết rollout với workflow histories đang tồn tại.

### F05 — P2: DSN đọc YAML lại dù process đã có config

[`db.dsn:22`](../../apps/leta/src/leta/db.py#L22) gọi shared load(), mà shared
load mở/parse YAML thật. pool và mỗi runtime saver gọi đường này, trong khi
Services đã giữ startup config. Ngoài file I/O, sửa YAML khi process chạy có
thể làm saver resolve DSN mới nhưng pool vẫn trỏ database cũ.

Truyền startup config vào dsn/pool; CLI setup load một lần ở entrypoint. Không
thêm global config cache, hot reload hoặc cấu hình DB authority thứ hai.

### F06 — P1: filesystem setup phụ thuộc graph node và giữ session trùng

[`agent.py:494`](../../apps/leta/src/leta/runtime/agent.py#L494),
[`tools.Context:35`](../../apps/leta/src/leta/runtime/tools.py#L35),
[`Filesystem.open:105`](../../apps/leta/src/leta/filesystem/workspace.py#L105).

Pending node phải tên tools mới mở FS; thêm native after_model hook có thể làm
assumption này sai. Session nằm cả ở Context lẫn Filesystem. Parallel first use
có thể cùng initialize/refresh. open còn loop qua mount map dù discovery chưa
cần refresh; skip mount diff khi map không đổi, giữ HITL invalidation/TTL.

File tools gọi lazy session từ owning Filesystem, một initialization/refresh
lock đơn giản; bỏ Context.session và graph-node/tool-name scan. Giữ một
Workspace/Session mỗi activity và cleanup tại exit. Không session manager mới.

### F07 — boundary đã chốt: search dựng path bằng các request phụ

[`LetFS.semantic_search:613`](../../apps/leta/src/leta/filesystem/letfs.py#L613)
walk parents và Stat tuần tự; parents cache chỉ sống trong một call. Với top10,
latency phụ thuộc số distinct ancestor nodes; không chỉ một search RPC.
[`files_containing:207`](../../apps/leta/src/leta/filesystem/letfs.py#L207) lại
ReadTree tới 1.000 nodes trước TextSearch chỉ để map hit IDs sang paths; tree
truncated thì bỏ fast path, để Mirage fallback.

TextHit/SemanticHit hiện chỉ có node/snippet và line_number/score, không relative
path. Hướng ít code tổng thể đã chốt: LetFS trả relative path trong chính
search hits; adapter dùng path đó, bỏ parent-walk/prewalk. Cần sửa public proto,
Go owner và generated SDK; chưa triển khai thay đổi boundary này vào code. Không
thay N+1 bằng tự duyệt toàn storage hoặc path-cache service trong Leta.

### F08 — P2: semantic search nhiều paths chạy tuần tự

[`tools.file_semantic_search:797`](../../apps/leta/src/leta/runtime/tools.py#L797)
có tối đa năm paths nhưng await từng dispatch. Sau khi có session, các read-only
search độc lập có thể chạy song song trong bound năm paths hiện có, giữ result
order và lỗi hiện tại; không mở unbounded tasks hoặc partial-success protocol.

Parallel chỉ giảm chờ, không giảm paid calls: mỗi SemanticSearch ở LetFS vẫn có
query embedding và optional rerank riêng. Không claim concurrency tiết kiệm
embedding cost; không thêm query cache hoặc multi-storage ranking engine.

### F09 — P2: root notification lấy full body rồi bỏ phần lớn

[`messages.pending:166`](../../apps/leta/src/leta/messages.py#L166) fetch tối đa
20 complete contents, sau đó input_batch(root=true) chỉ lấy preview240 chars
và dedupe conversations. DB transfer có thể lớn hơn nhiều model-facing payload.
Lần idle check lại gọi cùng pending chỉ để biết có rows hay không.

EXISTS cho idle đã chốt. Root notification query nên project đúng preview và
các routing fields cần thiết; nếu cần giữ byte budget hiện tại thì lấy computed
content size, không thêm field/table. Leti vẫn nhận full bounded batch. Giữ
cursor advancement, conversation grouping, schema và HITL invalidation.

### F10 — P2: internal inbox route làm nhiều lookup không cần thiết

[`inbox_send:63`](../../apps/leta/src/leta/runtime/tools.py#L63) của root kiểm
workspace permission cho to như một user trước cả khi biết đó là box/agent.
Sau đó query box, get_agent recipient, rồi admission activity query lại domain
facts. [`messages.admit:35`](../../apps/leta/src/leta/messages.py#L35) còn gate
cùng root lần hai khi sender/recipient thuộc cùng Leta.

Resolve internal box/agent bằng narrow lookup/snapshot đã có trước khi kiểm
user recipient; share exact routing result trong tool code. Admission vẫn phải
validate durable scope/current state ở transaction boundary. Khi đã lock root
và xác nhận cùng Leta thì reuse gate đó, kiểm riêng các box cần thiết. Không bỏ
permission check cho user, cross-Leta/edge/reply checks hoặc mutation locks.

### F11 — P1: list APIs tạo N+1 permission RPCs

[`api.list_letas:199`](../../apps/leta/src/leta/api.py#L199) gọi allowed tuần tự
cho tối đa20 resources. incoming_requests line558 có thể check cùng workspace
20 lần trong một page. Đây là nhiều round trips, không phải JSON loop đắt.

Dùng native SpiceDB CheckBulkPermissions cho page; dedupe workspace IDs trước
batch. Installed protobuf đã có request/response. Giữ fully_consistent và filter
denied; per-item service errors vẫn hiện đúng, không coi lỗi là grant. Không
Redis permission cache, invalidation bus hoặc TTL policy mới.

### F12 — P2: helpers trả full presentation cho chỗ chỉ cần identity

[`boxes.get:110`](../../apps/leta/src/leta/boxes.py#L110) chạy ba queries lấy box,
members và edges. API/tool schedule_create chỉ cần representative, delete_box
API chỉ cần scoped existence. own_hitl/own_schedule và API detail endpoints
thường lấy resource rồi full get_agent chỉ để kiểm leta_id/ownership.

Use scoped SQL lookup/JOIN cho đúng intent; giữ rich get cho box_get/UI.
RETURNING cho configure_agent sau update thay get_agent toàn bộ lần nữa khi
response fields đã có. Không generic repository, universal loader hoặc bỏ
containment vì muốn bớt query. FastAPI dependency cache hiện hữu vẫn reuse root
trong một request; không tính nhầm dependency đó là query trùng mỗi Depends.

### F13 — P2: schedule mutation lấy forecast và SELECT readback thừa

[`api.update_schedule:792`](../../apps/leta/src/leta/api.py#L792) và DELETE gọi
get_schedule, mà get_schedule gọi Temporal Describe để lấy upcoming. Mutation
không dùng forecast, có thể chờ tới timeout10s của một RPC không phục vụ nó.
[`schedules.save:195`](../../apps/leta/src/leta/schedules.py#L195) SELECT lại row
sau INSERT/UPDATE trong đường thông thường.

Mutation chỉ dùng scoped definition/ownership read; forecast chỉ ở GET/calendar.
Dùng INSERT/UPDATE RETURNING để tránh normal readback. Giữ receipt check,
native save/apply stages và retry canonicalization; không gộp external schedule
operation vào transaction SQL hoặc bỏ gate vì thấy nhiều statements.

### F14 — P2: tạo box insert từng member và từng edge

[`boxes.prepare:75`](../../apps/leta/src/leta/boxes.py#L75) await INSERT cho mỗi
Leti và mỗi edge. Giới hạn20 members/190 edges cho phép210 insert executions,
dù tất cả đã chuẩn bị được trước transaction và FK representative đã deferred.

Giữ transaction/gate/receipt, bulk insert agents và edges theo hai batches bằng
driver hiện có. Không workflow/activity cho mỗi member, graph builder service
hoặc migration schema chỉ để batch.

### F15 — P2: worker/HITL đọc lại facts qua nhiều connections

[`load_agent_control:155`](../../apps/leta/src/leta/worker.py#L155) get_agent rồi
query unfinished run riêng. finish_run UPDATE rồi SELECT owner/root riêng để
phát event. [`hitl.apply:264`](../../apps/leta/src/leta/hitl.py#L264) lấy request/
agent trước lock rồi đọc lại cả hai dưới lock.

Scoped JOIN cho control/run; update-returning/owner projection cho finish event.
HITL cần re-read dưới effect lock nhưng có thể JOIN request+agent tại mỗi phase;
không reuse stale permission/state trước lock. Không bỏ effect barrier hoặc đổi
accepted approval thành granted trước actual SetStorageAccess.

### F16 — P2: fanout/lifecycle đi qua cả archived agents và lặp root reads

[`refresh_leta_agents:314`](../../apps/leta/src/leta/worker.py#L314) query mọi
agent, gồm Leti của archived boxes, rồi update workflows tuần tự. Cleanup root
lấy list box IDs rồi archive_box lại query từng box và get_agent root mỗi lần.
settle_agents tuần tự qua producers, HITL và agents.

Filter agents còn thuộc live scope khi pause/resume; load shared root facts một
lần và truyền selected box rows vào existing archive helper. Các operations độc
lập có thể fanout hữu hạn trong từng phase nếu cần; không đổi thứ tự settle
producers → HITL effects → agent writers → archive/grant barrier. Không thêm
distributed cleanup scheduler; không song song hóa bừa giữa các phases.

### F17 — P2: Redis read/write round trips quanh streaming

[`events.suffix:114`](../../apps/leta/src/leta/events.py#L114) chạy XRANGE trước
và sau mỗi XREAD. Post-read check đã kiểm việc trim trong lúc block. Có thể bỏ
pre-check sau khi verify initial missing stream/cursor-gap detection vẫn đúng;
không xóa resync behavior hoặc âm thầm replay thiếu data.

Live.close gửi từng terminal event bằng pipeline riêng. Reuse batch publisher
để gửi các terminal events cùng boundary; nhiều events đã có trong một provider
chunk cũng có thể gửi cùng một pipeline. Giữ real-time chunk delivery, individual
event IDs/order và bounded replay. Không timer/coalescing worker hoặc delayed
token flush để lấy số benchmark đẹp.

### F18 — P2/đã chốt: response nhỏ chưa đồng nghĩa ít xử lý/RAM

[`file_read:725`](../../apps/leta/src/leta/runtime/tools.py#L725) split whole
cached text rồi enumerate mọi line để chọn200 lines. Giữ approved whole-file
Redis caching, chỉ slice trước khi format; không đổi default sang range RPC.
history.read serialize/split toàn payload dù trả200 lines; đây là chi phí có
thật nhưng chưa đo lớn tới mức cần reader/pagination protocol khác. Không cap
mất dữ liệu rồi tuyên bố client vẫn đọc toàn history được.

[`filesystem.shell:179`](../../apps/leta/src/leta/filesystem/workspace.py#L179)
thu toàn stdout/stderr rồi mới cắt16k/4k. Native probe seq100000 tạo588.895 chars
trước application slice. Native IO queue size không là total capture cap.

Mirage Limit có per-command max_bytes/max_lines, nhưng @line chỉ nhận timeout.
Probe @line(max_bytes=16000) bị native API reject. Không tự cấu hình @all cap:
có thể cắt producer đang ghi file qua redirection, đổi nội dung bền vững. Native
stream=True/ShellExecution.events có sẵn nhưng bounded collect/drain sẽ thay
capture code và cần giữ write settlement. Hướng native streaming bounded capture
đã chốt, cần proof đầy đủ drain/settlement và full file writes; không tự thêm
runner/watchdog/collector layer nếu API không đáp ứng.

### F19 — P2: duplicate glue và code không có caller

API ask/tool open_hitl, API submit_schedule/tool change_schedule lặp cùng native
Update-With-Start wiring. Hoist mỗi operation về owning existing module/helper
để API/tool cùng gọi; không gateway façade hoặc framework điều phối thứ hai.
operation(wait=true) còn gọi handle.result sau open update trong khi BoxLifecycle
chỉ publish result sau actual prepare/cleanup; bỏ wait flag/RPC nếu xác nhận
domain readiness hoàn toàn ở chính published result, giữ closed-workflow result
fallback phục vụ idempotent duplicate commands.

Code không có caller cần xóa cùng owning changes:

- Services.platform/PlatformServiceStub và async type imports; chỉ internal
  Platform client đang dùng. Shared channel vẫn cần cho internal client.
- config.settings = load alias; không caller trong repo.
- LetFS.read_text_lines custom hook: không caller Leta và không native Mirage
  reference trong toàn bộ pinned public Python source. Native head/tail hooks
  vẫn có consumer, không xóa theo số lượng method.
- Direct httpx dependency nếu sau migration vẫn không có direct caller và shared
  SDK đã khai báo own dependency. Giữ native SDK/transitive needs thực sự.
- Local model catalog/direct ChatOpenAI/XML/session field đã nằm trong F01/F06.
- Exact tool-count assertions28/22 khi chúng chỉ chặn thêm/bớt tool; giữ actual
  root-vs-Leti permission split và schema/runtime injection assertions.

## Những chỗ giữ nguyên

Không coi mọi query hoặc loop là lỗi. Giữ root/box admission gates, authorization
tại durable mutation owner, atomic literal replace, scoped paths, receipts,
counter ordering, idempotency conflicts và native pagination. API authorization
và activity admission có thể cần kiểm ở hai thời điểm khác nhau; không gộp qua
trust boundary chỉ vì nhìn thấy cùng tên permission.

Giữ cached whole-file read/default TTL600s, mount discovery TTL30s và bounded
stale cache policy đã duyệt. Explicit overwrite không có snapshot guard qua
nhiều tool calls; shell nhiều effects không atomic/exactly-once là giới hạn đã
chốt trong filesystem plan §8. Không biến hai giới hạn đó thành version registry,
shell journal hoặc saga mới. Invalid-tool-call issue33504 vẫn chỉ TODO.

Giữ native create_agent/SummarizationMiddleware/saver, Temporal orchestration,
heartbeat, cancellation settlement/writer barriers, public history retention,
LF prompt pinning/callback batching và stream snapshot/replay contracts.
Không thêm service/module chỉ để gom hai heartbeat helpers hoặc giảm LoC.

## SQL/index cần đo, chưa quyết định thêm

Chat queries filter actor nhưng current chat indexes không chứa source_id/
recipient_user_id trong equality prefix. HITL list order by UUID khác với một
số indexes đang order created_at. Có khả năng filter/sort dư khi history lớn.
Chạy EXPLAIN trên representative data trước khi đổi indexes; chưa có execution
plan, cardinality hoặc latency để khẳng định bottleneck. Không thêm index cho
mọi optional filter hoặc sửa initial migration đã áp dụng.

## Verification và mức độ chắc chắn

- `pytest apps/leta/tests -q`: **6 passed**, 13 upstream deprecation warnings.
- Strict Pyright với explicit project Python: **26 files, 0 errors/warnings**.
  Direct CLI lần đầu chọn sai interpreter và báo missing imports; rerun đúng
  `.venv/bin/python` đã pass, không disable strict hoặc sửa source để né lỗi.
- Native SpiceDB protobuf có CheckBulkPermissions; confirmed TextHit/SemanticHit
  hiện chưa có path field. Chưa live-test bulk permission server behavior.
- Native schema estimate hiện tại: root28 tools khoảng3.273 tokens, Leti22 tools
  khoảng2.475 tokens, dùng count_tokens_approximately; không actual provider usage.
  Giữ native schemas và stable prefix, không tạo schema serializer/filter mới.
- Native Temporal failure converter proof cho F03; chưa chạy activity retry trên
  server thật để claim full failure-handling acceptance.
- Native Mirage buffered-output probe và rejected @line cap cho F18; workspace
  đã close. Không coi per-command cap là safe aggregate capture implementation.
- Graph/native-summary replacement, canonical ID mismatch và prompt-link probes
  trước đó vẫn là evidence của owning runtime review; không phải perf benchmark.

Current tests kiểm native tools, basic adapter search paths, stream folding,
schedule normalization và cancellation shield. Chưa chứng minh batch I/O, graph
reuse, actual PostgreSQL crash gap/compaction recovery, empty-wake handoff hoặc
large output settlement. Implementation thêm focused cases vào suites hiện có;
không test từng query/command hoặc dựng paid benchmark trong CI.

Chưa chạy full stack/E2E, production EXPLAIN, paid inference, load/memory
benchmark hoặc Cloud telemetry acceptance. Không suy static query reduction
thành một tỷ lệ tăng tốc cụ thể.

## Cách đưa vào plan

Thực hiện F01/F02/F06 theo approved runtime refactor trước; F03/F05/F08–F17/F19
đi cùng owning functions khi scope liên quan, ưu tiên frequent paths rồi đến
create/cleanup. Không refactor toàn repo chỉ để gom helpers. Batch/shape changes
phải giữ errors, security và public output; obsolete code/test structure xóa
cùng caller migration.

F04 workflow consumed-cursor handoff, F07 LetFS search hit paths và F18 bounded
aggregate shell output đã được chốt. Implementation giữ đúng guarantees nêu
trên; history cutover và native capture cần proof, không mở rộng framework.
Index tuning chỉ khi có số đo.

## Manifest đã đọc

| Nhóm         | Files                                                                                                                                                               |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| API/domain   | `__init__.py`, `agents.py`, `api.py`, `auth.py`, `boxes.py`, `config.py`, `db.py`, `events.py`, `history.py`, `hitl.py`, `messages.py`, `schedules.py`, `worker.py` |
| Runtime      | `runtime/agent.py`, `runtime/inbox.py`, `runtime/tools.py`                                                                                                          |
| Filesystem   | `filesystem/letfs.py`, `filesystem/workspace.py`                                                                                                                    |
| Workflows    | `jobs/agent.py`, `jobs/hitl.py`, `jobs/resources.py`, `jobs/retry.py`, `jobs/schedules.py`                                                                          |
| Tests        | `test_filesystem.py`, `test_runtime.py`, `test_tools.py`                                                                                                            |
| Build/schema | `migrations/0001_initial.sql`, `Dockerfile`, `pyproject.toml`                                                                                                       |

Research source/diagnostics chỉ ở `/tmp/openlet-leta-audit-261114`; không thêm
benchmark script hoặc third-party source vào repo.
