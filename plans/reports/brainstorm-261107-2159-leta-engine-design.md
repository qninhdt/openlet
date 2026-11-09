# Leta: thiết kế engine MVP và cách dùng Temporal

Latest accepted direction (2026-11-08): [human users and workspace-owned Leta resources](design-261108-0148-leta-workspace-resource.md). All ten redesign points and the zero-padding limitation are accepted. Use model_id/reasoning_effort everywhere. The old account-based plan below remains historical and not executable. Original review items 27–34 are next; 35–42 remain parked. No implementation has started.

Current continuation: the accepted brainstorm is now translated into the detailed English [Leta implementation plan](../261108-0001-leta-agent-engine/plan.md), created on 2026-11-08. The plan includes the accepted compaction/input UI decisions and supersedes stale proposal labels below. Planning only: production implementation and integration acceptance have not started. Approval always addresses the resource owner, not automatically the Leta owner.

Final design-addition review requested by the user: [comparison report](../261108-0001-leta-agent-engine/reports/design-additions-review.md). Assistant-added policy/detail and proposed drift corrections are awaiting review; the implementation plan does not make them accepted by itself. No implementation has started.

Latest continuation: [items 1–18 decisions](checkpoint-261108-0118-leta-review-decisions.md) are now settled and reflected in owning phases. Ordinary Temporal retry and existing idempotency_keys remain; remove permanent command journals/receipt extensions, shell replay suppression, failure-wake bookkeeping and forced invocation segmentation. Leta has no standalone workspace leave/transfer and no special post-owner-departure access. Next review: 19–26; 27–42 remain parked. Historical text below cannot override these newer choices.

## 1. Outcome và giới hạn đã chốt

- Owner tạo Leta có account, active membership trong đúng một workspace và personal scope theo cơ chế member hiện có. Leti thuộc box, không có account; kế thừa quyền Leta nhưng home giới hạn trong box.
- Agent có dòng làm việc liên tục, inbox bền vững, chủ động nhắn, lịch và HITL. Một việc đang chờ phản hồi không khóa việc độc lập.
- Stack: Temporal điều phối; LangChain `create_agent` tạo graph LangGraph cho từng agent; AsyncPostgresSaver + durability="sync"; PostgreSQL giữ dữ liệu sản phẩm/history; Redis phục vụ streaming và Mirage cache.
- Server cấu hình nhiều model và reasoning modes hợp lệ. Owner chọn cho Leta, có thể cấu hình Leti; Leti mặc định kế thừa Leta. `create_agent` là factory runner, không phải tool tạo tài khoản/box. Không thêm budget số model calls mỗi run.
- MVP chat với owner. Leti hỏi owner qua HITL form, không có chat trực tiếp với owner. Resource approval có thể gửi human user khác cùng workspace, không mở chat với họ.
- Acceptance của thiết kế: giải thích đủ owner → Leta → box → Leti hỏi owner → Leta xử lý lịch khác → owner trả lời → Leti tiếp tục → kết quả về Leta → owner; chỉ rõ lưu dữ liệu, steering, routing, retry và quyền.

## 2. Thành phần và nơi lưu dữ liệu

Service `leta` có API process và worker process, không có service `leti` riêng. API nhận commands, trả dữ liệu UI và proxy SSE. Worker chạy Temporal Workflows/Activities, runner LangGraph và Mirage. Hai process có thể dùng cùng codebase/deployment image.

| Thành phần | Sở hữu |
| --- | --- |
| PostgreSQL của leta | agents, boxes, box_edges, messages, runs, activity_log/public transcript, hitl_requests, schedules |
| Temporal | Vòng điều phối từng agent, các command nhiều bước, chờ Activity, retry/cancel, timeout HITL và thực thi lịch |
| LangGraph checkpoint trong PostgreSQL | Working messages/summary, inbox_cursor, tool calls/results và vị trí tiếp tục của graph |
| Redis Streams | AG-UI events đang phát và replay có giới hạn cho client |
| Mirage Redis cache | Cache content/metadata theo workspace/mount, không là filesystem authority hoặc permission authority |
| Account / Workspace / LetFS / SpiceDB hiện có | Identity; membership/scope mapping; files/artifacts/text; authorization |

Inbox là các rows trong `messages` nhận bởi agent. Không tạo thêm bản inbox domain table sao chép cùng dữ liệu. `activity_log` giữ public LLM transcript theo agent: input/steering thực sự đã đưa cho model, assistant/tool calls/arguments/results, final notes; liên kết tới domain message khi có. Không ghi hidden chain-of-thought, không snapshot lại toàn bộ prompt cho mỗi model call.

LangGraph checkpoint giữ context đang dùng; sau compact có thể chỉ còn summary + recent messages. History lâu dài không bị compact theo context. UI đọc PostgreSQL, không lục Temporal history hoặc ghép checkpoint snapshots để dựng chat/canvas.

| Màn hình | Nguồn |
| --- | --- |
| Chat owner–Leta | messages gửi thực sự giữa owner và Leta |
| Inbox | messages theo recipient/conversation/source, cursor và read_at |
| Canvas/box | boxes + agents + box_edges, runs, pending HITL, schedules |
| Nhật ký hoạt động | Public transcript/tool events/final notes và references tới messages |
| Lịch | schedules và occurrence preview từ backend |
| Yêu cầu HITL | hitl_requests; backend lọc owner/requester hoặc đúng resource approver |

## 3. Hai graph khác nhau

**Box graph** là communication graph lưu PostgreSQL: các Leti và edge vô hướng cho phép gửi tin. Không có thứ tự chạy, dependency, branch/join hoặc tự forward final text. Mỗi agent chạy khi có input của chính mình. Canvas hiển thị graph này.

**LangGraph của một agent** là vòng model/tools do `create_agent` tạo, bổ sung middleware Openlet:

```text
boundary: kiểm tra pause/config/mounts và compact nếu cần
    → collect_inbox
    → checkpoint working messages + inbox_cursor
    → model
    → checkpoint assistant output/tool_call_id
    → tools, nếu có
    → checkpoint tool results
    → quay lại boundary trước model tiếp theo

model không gọi tool → final note → kết thúc run
```

Một agent có một `thread_id` ổn định theo agent ID và nhiều runs nối tiếp. Một run là một lần runner xử lý tới khi kết thúc lượt; không đồng nghĩa task, conversation hoặc cả đời agent. Một agent chỉ có một graph invocation đang chạy; các agent khác chạy độc lập.

Model/reasoning lấy từ cấu hình server hợp lệ và lựa chọn owner; Leti chưa override thì dùng cấu hình Leta. Thay prompt/model áp tại boundary an toàn trước model call kế tiếp, không đổi input của call đang streaming hoặc chen vào giữa assistant tool calls chưa đủ results. Giữ context khi owner sửa cấu hình.

### Working state trong RAM và đọc checkpoint

Đối chiếu LangGraph 1.2.19 đã khảo sát: pregel/_loop.py::AsyncPregelLoop.__aenter__ gọi checkpointer.aget_tuple khi bắt đầu invocation/recovery, rồi dựng checkpoint/channels trong RAM. pregel/main.py::astream giữ cùng AsyncPregelLoop qua các loop.tick/runner.atick và chờ checkpoint write trước bước kế nếu durability="sync". Không fetch lại toàn bộ checkpoint ở mỗi model/tools iteration chỉ vì dùng PostgreSQL saver.

Trong một invocation run_agent, working messages/state nằm trong RAM, cập nhật theo graph steps và checkpoint xuống PostgreSQL. Khi invocation kết thúc/idle, không thiết kế giữ context RAM riêng vô hạn cho agent; invocation mới hoặc Temporal Activity retry load checkpoint hiện hành của cùng thread. Reuse compiled graph không đồng nghĩa nó cache state của thread giữa các lần ainvoke/astream. Latest checkpoint/state và dữ liệu nó tham chiếu khác với toàn bộ checkpoint history.

Messages được serializer phục hồi thành LangChain message objects, không biến toàn checkpoint thành string hoặc một HumanMessage mới. Chỉ batch inbox mới được render template + tạo runtime HumanMessage một lần và lưu vào state. Mỗi LLM call vẫn serialize working message list sang request format provider, có thể gửi lại phần context đang giữ; đó là bước khác với fetch/deserialization checkpoint. collect_inbox vẫn query messages mới ở trước model call như yêu cầu steering, không phải reload checkpoint. Không thêm RAM cache state xuyên invocation để thay authority checkpoint.

### Compaction, checkpoint và hiển thị — đề xuất cho lượt 23:34

Dùng SummarizationMiddleware async của LangChain trong run_agent. Source khảo sát [langchain 1.4.8](https://pypi.org/project/langchain/1.4.8/), langchain/agents/middleware/summarization.py::abefore_model thay prefix cũ bằng RemoveMessage(REMOVE_ALL_MESSAGES) + summary + recent messages. _build_new_messages trả HumanMessage có additional_kwargs.lc_source="summarization"; thao tác này cập nhật working state, không chỉ trim prompt. [Context engineering](https://docs.langchain.com/oss/python/langchain/context-engineering) cũng mô tả summary được persist trong state. Dependency production vẫn phải pin khi plan.

Checkpoint tiếp theo giữ messages=[summary mới, recent messages], inbox_cursor và state khác không đổi. Summary có message ID ổn định sau khi lưu; wrapper abefore_model có thể thêm metadata Openlet trước checkpoint qua public hook. Chỉ compact tại boundary không còn tool calls thiếu results. Lần compact sau tóm tắt cả summary trước và older messages mới, giữ một summary hiện hành; summary cũ vẫn nằm trong history/journal. Chưa xóa checkpoint hoặc transcript cũ.

Ghi activity_log(kind="compaction") bằng summary message ID, agent_id/run_id, thời điểm và đúng nội dung summary agent dùng tiếp; token estimates/range là metadata tùy chọn. Đây là public context summary có chủ đích, không phải hidden chain-of-thought hoặc message gửi owner. Dùng journal hiện có, không thêm bảng/service/Temporal Workflow/Activity compaction riêng.

Để journal phản ánh state đã lưu: step summarization checkpoint sync xong rồi step/middleware ghi transcript kế tiếp upsert summary vào activity_log, trước model call. create_agent factory 1.4.8 tạo before_model middleware thành nodes nối tiếp nên có boundary phù hợp. Publisher nhận summary đã checkpoint, nhận diện bằng metadata/ID; có thể dùng refs tới messages đã lưu cho inbox input, không snapshot cả context vào journal mỗi call. Không ghi card "đã compact" trước khi summary checkpoint thành công.

- Crash trước checkpoint summary: dùng state cũ, summary call có thể chạy lại; chưa báo UI đã compact thành công.
- Crash sau checkpoint nhưng trước journal: resume tiếp step publisher bằng summary đã lưu, không tóm tắt lại chỉ để ghi log.
- Crash sau journal: retry upsert theo cùng message ID; Redis event có thể lặp, UI dedup theo journal ID. Redis mất event thì reload journal PostgreSQL.
- Temporal replay/Continue-As-New giữ pointers, không tự compact lại. LangGraph resume dùng latest state sau compact; Redis replay chỉ phát events UI, không sửa context hoặc gọi summarizer.

UI conversation hiển thị một dòng/card "Đã rút gọn context" có thể mở rộng đọc đúng summary; lịch sử cũ vẫn có thể xem và tải thêm. Khi có nhiều compactions, mỗi lần là một journal entry riêng. Không coi HumanMessage của middleware là tin owner chỉ vì role=user. Event AG-UI có thể dùng CUSTOM(name="activity", value={id,kind:"compaction",...}) sau journal commit; reconnect dùng cùng typed entry từ PostgreSQL.

## 4. Inbox: lưu, đánh thức và steering

Envelope chung:

```text
id, seq, recipient_agent_id
source: {type, id, label}
conversation_key?, reply_to?
content, data, created_at, read_at?
```

`source.type` là chuỗi do adapter validate, không enum hardcode một số nguồn trong engine. `source` cho biết ai/cái gì phát; `reply_to` mới cho biết có địa chỉ để trả lời. Content là phần agent đọc, data giữ cấu trúc cần thiết như request_id/schedule_id/answers/scheduled_at. Schedule/HITL không tự biến thành chat dù cùng biểu diễn inbox item.

Conversation grouping dùng owner thread, box hoặc nguồn phù hợp. Leta được digest ngắn theo nhóm, có nguồn, ID, số mục mới và preview để chọn đọc. Không thêm lifecycle đóng thread hoặc task state.

### Nhận input

1. API/tool/adapter xác thực, resolve recipient và tạo envelope. Cùng một lần gửi phải giữ cùng message ID khi retry.
2. Gọi `AgentWorkflow.receive` bằng Temporal Update-with-Start, định danh Workflow bằng agent ID.
3. Handler tuần tự hóa đoạn nhận ngắn, gọi Activity `persist_inbox`. Activity kiểm tra agent/box/Leta chưa bị xóa rồi commit message trong PostgreSQL; retry cùng ID trả item cũ, khác payload thì conflict.
4. Sau commit, handler cập nhật `latest_seq` rồi trả xác nhận. Không chờ LLM xử lý hoặc chờ người nhận trả lời.
5. Main loop thấy có input chưa đưa vào context thì chạy `run_agent`. Khi Activity này đang chạy, handler vẫn nhận input mới.

Đây là Temporal Update, không phải Temporal Signal. Temporal Signal có thể nhận input bất đồng bộ vào Workflow nhưng bản thân nó không trả kết quả commit PostgreSQL. MVP không cần dùng cả Update lẫn Signal cho cùng lần gửi. Một business event gọi là signal vẫn được adapter chuyển thành inbox item và đi qua `receive`.

**Giá đã chấp nhận:** khi worker không chạy, API chưa thể báo “đã vào inbox PostgreSQL”. Client giữ pending, lấy kết quả/đọc lại theo cùng message ID; request timeout không chứng minh message thất bại. Không thêm outbox, replay worker hoặc reconciliation poller.

Temporal vẫn ghi Update payload vào history: nếu truyền text thì text đó xuất hiện trong history của command. Không giữ thêm inbox bodies trong mutable Workflow state; không đưa toàn bộ transcript, file bytes, token events hoặc tool results lớn qua Temporal.

### Đưa vào model

Trước model call, `collect_inbox` lấy snapshot `seq > inbox_cursor` và cập nhật cả messages lẫn cursor trong cùng graph step, checkpoint sync trước khi gọi model.

- Leta nhận digest; đọc body qua `list_inbox`/`read_inbox`.
- Leti nhận toàn bộ pending message contents; không có inbox tool.
- Tin đến trong LLM call/tool call vào boundary kế tiếp. Không sửa prompt của LLM call đang chạy và không làm hỏng cặp assistant-tool protocol.
- Cursor nghĩa đã giao thông báo/nội dung vào context bền vững. `read_at` nghĩa Leta đã đọc chi tiết qua tool. Không tự suy ra công việc hoàn tất từ hai dữ liệu này.
- Không có processed/closed status chung. Nếu agent muốn quay lại một việc ở một thời điểm khác, dùng schedule; việc ghi note không tự tạo lịch.

### Format input cho LLM và custom input UI

Yêu cầu user đã xác nhận: ngay trong chat conversation, inbox input phải render bằng component riêng, không render raw template/JSON như text bubble. LLM role không quyết định UI component. Tin owner gửi và message agent thực sự gửi vẫn là chat messages; runtime input/compaction là entries riêng trong cùng timeline.

Đề xuất một payload có cấu trúc cho mỗi batch collect, render thành một HumanMessage runtime-generated với header/template cố định và JSON đã serialize. Metadata đánh dấu Openlet kind=inbox_input và mode=digest/full; không cần provider hỗ trợ custom role hoặc custom content block. Template chỉ là model input nội bộ; UI nhận typed journal data, không parse text để đoán source/type.

- Leta: mode=digest. Payload groups theo conversation/source, gồm source{type,id,label}, conversation_id (projection của conversation_key, dùng trực tiếp với read_inbox), new_count, message IDs/refs, preview và reply_to nếu có. Chi tiết còn trong inbox. Agent chọn read_inbox; digest không tự đánh read_at.
- Leti: mode=full. Payload items chứa toàn bộ messages pending: id/source/conversation_key/reply_to/content/data cần thiết. HITL giữ request_id/answers hoặc outcome, schedule giữ schedule_id/scheduled_at. Leti không gọi inbox tools.
- source.type vẫn do adapter validate, không hardcode các nguồn tương lai trong core. reply_to=null nghĩa item không có địa chỉ phản hồi; message/notification cùng envelope không có nghĩa cùng hành vi chat.
- Runtime message/cursor được checkpoint cùng nhau như đã chốt. Ghi typed activity_log entry sau checkpoint bằng cùng LLM message ID để retry không nhân đôi. Structured journal payload giữ projection/refs cần render; body gốc đã có trong messages thì hydrate bằng IDs, không tạo thêm delivery/operation entity.

Contract render trong conversation:

| Entry | UI |
| --- | --- |
| owner gửi message | Chat bubble owner; trạng thái đã vào inbox khi backend ack commit. |
| kind=inbox_input, mode=digest | Custom input component: source badges, số mục mới, grouped previews, mở rộng xem items. |
| kind=inbox_input, mode=full | Cùng custom input component, mở rộng xem đầy đủ input đã đưa cho Leti. |
| agent send_message tới owner | Chat bubble thực sự nhận được từ Leta. |
| kind=compaction | Dòng/card rút gọn context, mở rộng xem summary. |
| tool call/result hoặc final note | Tool component hoặc note component theo journal kind. |

Một message owner có thể được tham chiếu trong input card, nhưng không render lại nó thành một owner bubble thứ hai. Typed entries dùng cùng contract khi live qua AG-UI CUSTOM và khi reload history từ PostgreSQL; không phụ thuộc Redis còn giữ event. Không expose template trong giao diện conversation thông thường. Chi tiết source/permission vẫn kiểm tra backend, không lấy labels/role hiển thị làm authority.

## 5. Sáu Workflow và Activity mapping đã chốt

User đã chốt sáu loại Workflow và bảng Local/regular bên dưới. Đây là baseline cho plan, vẫn có thể điều chỉnh bằng bằng chứng khi triển khai như đã thống nhất. Chỉ AgentWorkflow thực thi vòng agent; không tạo Workflow cho mỗi LLM call, tool call hoặc edge canvas.

| Workflow | Lifetime và lý do dùng Workflow |
| --- | --- |
| AgentWorkflow(agent_id) | Sống dài theo Leta/Leti: nhận input lúc rảnh/bận, tuần tự hóa runs, phục hồi qua restart. |
| LetaLifecycleWorkflow(leta_id) | Coordinator create/config/pause/resume/archive, giữ tiến độ qua Account, Workspace và runtimes. |
| BoxLifecycleWorkflow(box_id) | Coordinator create/delete nguyên box: SQL graph, LetFS home và nhiều runtimes. |
| HumanRequestWorkflow(request_id) | Một execution/request: chờ human/timeout, grant nếu accept, giao outcome; không khóa agent. |
| ScheduleChangesWorkflow(schedule_id) | Coordinator CRUD/pause/resume, tuần tự hóa và hoàn tất thay đổi PostgreSQL + native Schedule. |
| ScheduleDeliveryWorkflow | Một execution/occurrence: tới hạn → commit inbox; không chờ LLM hoàn tất. |

Các lifecycle/schedule coordinators dùng Update handlers tuần tự, theo pattern WorkspaceChanges. Khi không có command thì Workflow chờ, không giữ Python thread thức chờ. Continue-As-New giữa commands, khi handlers đã xong. HumanRequestWorkflow kết thúc sau outcome/delivery hoặc skip.

### Ranh giới Activity và Local/regular

Nguồn: [How many Activities should I use?](https://temporal.io/blog/how-many-activities-should-i-use-in-my-temporal-workflow), [Activity Definition](https://docs.temporal.io/activity-definition), [Local Activity](https://github.com/temporalio/documentation/blob/main/docs/encyclopedia/activities/local-activity.mdx), [Python SDK 1.35.0](https://github.com/temporalio/sdk-python/blob/1.35.0/README.md). Đã đọc bài gốc/source docs và SDK pin của repo.

- Activity là retry boundary, không phải mỗi function/query. Một SQL transaction cùng reads/validation của nó ở trong một Activity. Tách side effects độc lập cần retry/timeout/queue khác nhau; pure helpers và fan-out/wait nằm trong Workflow.
- Đề xuất Local cho I/O PostgreSQL leta ngắn, bounded và retry-safe bằng IDs/preconditions đã có. Không đưa remote provisioning hoặc chờ Workflow khác vào Local. Lookup/authz remote ở ingress/service boundary hoặc trong regular Activity tương ứng; một Activity được ghi Local không ngầm ôm thêm những RPC đó.
- Regular cho run_agent, Account/Workspace/LetFS mutation, native Schedule và bridge gọi Workflow khác. Cùng service/process không phải lý do chọn Local: regular Activity cũng có thể chạy ngay process đó.
- Local result chỉ bền khi Workflow Task ghi marker. Crash trước marker có thể chạy lại; không có Activity heartbeat. SQL deadline ngắn để không kéo chậm receive/control. Nếu thao tác đo được thường kéo dài nhiều giây, chuyển chính Activity đó sang regular; không tăng Workflow Task timeout để che vấn đề.
- Regular là default trong hướng dẫn Temporal. Mixed Local/regular ở đây là tối ưu có giới hạn cho inbox/control path; chưa có benchmark Openlet để khẳng định mức giảm latency. Không có exactly-once cho side effect chỉ nhờ chọn một loại Activity.

**L = Local Activity; R = regular Activity.** Các tên sau là Activity definitions; mỗi command chỉ gọi tập con liên quan.

### AgentWorkflow

| Activity | Loại | Công việc |
| --- | --- | --- |
| bootstrap_agent(agent_id) | L | Đọc trạng thái root/agent, latest inbox seq và recovery pointers của run/checkpoint. Không tải toàn transcript vào Workflow. |
| persist_inbox(agent_id, envelope) | L | Transaction kiểm tra recipient/routing/root state và commit message; cùng message ID trả lại row đã lưu. Chạy trong receive Update handler. |
| run_agent(agent_id, run_id) | R | Một invocation create_agent/LangGraph: steering, model/tools, sync checkpoint, transcript/Redis stream, Mirage session; heartbeat và cancellation. |

Bootstrap → chờ input/control → run_agent → kiểm tra còn input/continuation → chạy tiếp hoặc chờ. Receive handler vẫn nhận input trong lúc run_agent chạy. Không giữ lock receive suốt graph invocation.

run_agent lớn có chủ đích: retry phục hồi cùng run/checkpoint, không chạy lại cả transcript. Model/tool steps không trở thành Temporal Activities riêng. Pause/stop/config áp ở boundary như đã chốt.

### Activity dùng chung giữa các Workflow

| Activity | Loại | Công việc |
| --- | --- | --- |
| start_agent(agent_id) | R | Start/use-existing AgentWorkflow top-level với ID ổn định. |
| control_agent(agent_id, action) | R | Gửi pause/resume/stop bằng Client; stop đợi runtime và run_agent dừng, có heartbeat nếu phải chờ. |
| change_schedule(schedule_id, change) | R | Gọi command của ScheduleChangesWorkflow và đợi command hoàn tất. Lifecycle dùng để delete lịch. |
| settle_hitl(request_id, reason) | R | Hủy request còn pending; nếu decision đã accept thì đợi grant/outcome đang thực hiện xong. Không đổi accept thành cancel. |
| deliver_agent_input(agent_id, envelope) | R | Dùng Client gọi AgentWorkflow.receive Update-with-Start; trả sau commit inbox. Target đã xóa trả skipped, không retry mãi hoặc làm sống lại resource. |

Workflow giữ vòng lặp/fan-out từng ID, concurrency hữu hạn. Không có batch Activity tự điều phối tất cả agents/requests/schedules; vì vậy retry một target không làm lại targets đã xong. Không có Activity list_owned_resources riêng: các save lifecycle trả luôn snapshot IDs cần điều phối trong cùng transaction đổi state. Các lệnh tạo mới cũng kiểm tra parent state tại transaction boundary, nên deleting chặn tài nguyên mới lọt ngoài snapshot.

Client RPC là I/O nên đặt trong regular bridge Activities khi caller là Workflow. API/tool đang chạy ngoài Workflow code có thể dùng Client trực tiếp; không buộc mọi send_message qua một Activity delivery khác ở bên trong run_agent. Đây không là tool send_box hay dispatcher service mới.

### LetaLifecycleWorkflow

| Activity riêng | Loại | Công việc |
| --- | --- | --- |
| save_leta_change(leta_id, change) | L | Validate/lưu initializing, config, active, pause/resume, deleting, archived; trả root/config và IDs cần fan-out. |
| ensure_leta_account(leta_id) | R | Account tạo/lấy managed account theo ID ổn định đã lưu; đồng bộ account name nếu đổi tên. |
| ensure_leta_membership(leta_id) | R | Workspace thêm member, tạo personal scope/default relationships; gồm viewer cho owner trên Leta personal theo mục 10. |
| leave_leta_workspace(leta_id) | R | Workspace cho owner thay Leta leave: gỡ role/default access và direct grants của Leta trong workspace; giữ account/personal files/history và owner visibility. |

- Create: save(initializing) → ensure account → ensure membership/personal → save(active) → start_agent(Leta).
- Config: save(config), ensure account chỉ nếu cần đồng bộ name. Runner áp config tại boundary; không reset context.
- Pause/resume: save(state + agent IDs) → control_agent từng Leta/Leti. Inbox/HITL/lịch vẫn hoạt động.
- Archive: save(deleting + resource IDs) → change_schedule(delete) từng lịch → settle_hitl từng request → control_agent(stop) từng agent → leave_leta_workspace → save(archived).

Grant đã accept phải settle trước leave để không cấp lại sau cleanup. Archive dùng leave-workspace theo thiết kế đã chốt; không hard-delete account/scope hoặc trash toàn personal. Không có Activity grant_owner_visibility riêng: viewer mặc định được Workspace ghi cùng bước membership relationships. Không để leta viết thẳng DB/SpiceDB của service khác.

Account CreateManaged hiện tự sinh ID ở entrypoint; cần internal contract nhận ID ổn định khi retry provisioning. Workspace membership/access calls cũng phải giữ command identity đã có thay vì sinh command mới cho mỗi lần retry; không thêm operation/delivery domain entity.

### BoxLifecycleWorkflow

| Activity riêng | Loại | Công việc |
| --- | --- | --- |
| save_box_change(box_id, change) | L | Transaction tạo nguyên graph/IDs sau validate tên/derived path collision/representative/edges; hoặc lưu active/deleting/archived và resource IDs. |
| ensure_box_home(box_id) | R | LetFS tạo/lấy .leti/<derived-box-slug> trong personal scope Leta. |
| trash_box_home(box_id) | R | LetFS trash home sau khi runtimes đã dừng; không purge history. |

Create: save(initializing graph) → ensure home → save(active) → start_agent từng Leti. Tạo box không tự gửi việc, không tạo account/scope Leti.

Delete: save(deleting + resource IDs) → change_schedule(delete) từng lịch → settle_hitl từng request → control_agent(stop) từng Leti → trash home → save(archived). Không revoke grant đã cấp cho Leta chỉ vì xóa box. Không có Workflow chạy thứ tự các edges.

Leti không tự bị xóa khi hoàn thành một việc hoặc gửi kết quả. Chỉ run_agent hiện tại kết thúc; agent/box/context/home giữ nguyên để nhận message, lịch hoặc HITL outcome tiếp theo. Leta chủ động gọi delete_box để xóa nguyên box/team khi không còn cần; MVP không có delete_leti riêng. Owner cũng có thể quản lý lifecycle qua API/UI. Archive Leta dừng cả runtimes thuộc Leta và giữ dữ liệu theo chính sách archive đã chốt.

### HumanRequestWorkflow

| Activity riêng | Loại | Công việc |
| --- | --- | --- |
| open_hitl_request(request_id, payload) | L | Persist request/deadline sau ingress đã resolve/validate resource/approver. Cùng ID trả request đã có. |
| resolve_hitl_request(request_id, response) | L | Transaction validate responder/status/deadline và lưu answers/accept/deny/cancel/expire; ghi luôn outcome nếu không cần grant. Retry trả decision đã lưu. |
| grant_requested_access(request_id) | R | Chỉ approval accept: revalidate resource owner/membership và gọi Workspace grant viewer/editor cho account Leta dưới authority người duyệt đã xác thực. |
| save_hitl_outcome(request_id, outcome) | L | Ghi kết quả grant thực tế, thành công hoặc permanent failure; không thêm status HITL thứ năm. |

- Open Update → open request → trả pending ngay. Workflow dùng condition/timer chờ response/timeout. Không có wait_for_human Activity.
- Ask: resolve(answers) → deliver_agent_input về đúng requester Leta/Leti.
- Approval accept: resolve(accept) → grant_requested_access → save_hitl_outcome → deliver_agent_input.
- Deny/cancel/expire: resolve(outcome) → deliver_agent_input. Requester bị xóa thì delivery skipped.

Ask hỏi owner Leta; approval gửi OWNER RESOURCE, không phải owner Leta trừ khi hai người là một. Approver/resource/grantee lấy từ dữ liệu backend đã xác thực, không nhận actor/approved=true từ model. Accept chỉ cấp quyền, không chạy lại tool cũ. Temporary dependency errors retry đúng Activity; permanent grant failure được lưu và báo requester.

### ScheduleChangesWorkflow

| Activity riêng | Loại | Công việc |
| --- | --- | --- |
| save_schedule_change(schedule_id, change) | L | Validate/lưu definition hoặc pause/delete; normalize relative at/anchor một lần, trả definition cố định cho bước apply. |
| apply_temporal_schedule(schedule_id, definition) | R | Create/update/pause/delete native Schedule cùng ID, spec at/interval/calendar và BUFFER_ONE. |

Save SQL → apply native Schedule → trả thành công. Không thêm finalize Activity chỉ để trả response. PostgreSQL giữ dữ liệu sản phẩm, Temporal là executor; Workflow giữ tiến độ giữa hai bước. Không hứa distributed transaction hoặc thêm poller/outbox.

### ScheduleDeliveryWorkflow

| Activity | Loại | Công việc |
| --- | --- | --- |
| load_schedule_occurrence(schedule_id, scheduled_at) | L | Đọc schedule/target còn hợp lệ, tạo snapshot target/content/scheduled_at/message ID ổn định; trả skipped nếu đã xóa/paused/target đã xóa. |
| deliver_agent_input(agent_id, envelope) | R | Dùng Activity chung ở trên, kết thúc sau commit inbox hoặc skipped. |

Load snapshot → deliver. Giữ read này riêng để thay đổi schedule sau đó không đổi payload retry dưới cùng message ID. Native Schedule là resource Temporal, không phải Workflow thứ bảy tự viết. BUFFER_ONE áp cho delivery, không đợi LLM.

### Worker topology

Đề xuất một task queue điều phối và một task queue cho run_agent dài; hai SDK Worker objects có thể ở cùng process/deployment. Local chạy tại Workflow Worker; regular bridges/provisioning không phải đẩy sang service mới. Chừa slots cho inbox/HITL/control khi LLM bận. Chưa cần scheduler service/worker riêng.

AgentWorkflow có ID độc lập agent/<id>, start top-level qua Client trong start_agent. Box ownership/representative/edges thuộc SQL, không dựa vào Temporal child hierarchy. Lifecycle lưu IDs để Workflow fan-out; không giữ child Activity sống để biểu diễn một box.

### Tài nguyên khi agent hoặc HITL đang chờ

Agent idle chờ bằng workflow.wait_condition, HITL chờ condition/timer. Không dùng polling loop hoặc Activity đứng chờ human; không giữ thread hay Activity slot riêng cho mỗi Workflow đang chờ. run_agent đã kết thúc thì đóng Mirage session và giải phóng connections/tài nguyên invocation.

Workflow đang chờ không liên tục chạy code/LLM. Worker có thể giữ state/coroutines trong workflow cache nên vẫn tốn RAM, được giới hạn bằng max_cached_workflows; cache eviction phục hồi state qua Temporal history replay khi có task mới. Temporal server giữ history và durable timers; worker/server vẫn có CPU/RAM nền và công việc khi có event, timer tới hạn hoặc replay. Không gọi idle là hoàn toàn miễn phí hoặc hứa CPU bằng 0.

Đối chiếu [Worker 1.35.0](https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/worker/_worker.py): max_cached_workflows mặc định 1000; [workflow_wait_condition](https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/worker/_workflow_instance.py) đăng ký condition/future để await. Đây là bằng chứng cơ chế, chưa đo RAM/CPU cho Openlet và chưa chọn cache limit production.

### AgentWorkflow cụ thể

State điều phối nhỏ: agent ID, latest input seq, inbox cursor graph đã nhận, active run ID và còn continuation hay không, pause/stop. Graph messages không nằm trong state này.

```text
receive(item):
    trong lock ngắn chỉ dành cho receive:
        saved = await LocalActivity.persist_inbox(item)
        latest_seq = max(latest_seq, saved.seq)
        return saved

run(agent_id):
    bootstrap = await LocalActivity.bootstrap_agent(agent_id)
    merge bootstrap với receive đã tới; không ghi đè latest_seq mới hơn

    while chưa đóng runtime:
        await điều kiện (không paused và (có continuation hoặc latest_seq > inbox_cursor)) hoặc stop
        nếu stop: kết thúc theo lifecycle
        result = await Activity.run_agent(agent_id, stable_run_id)
        inbox_cursor = max(inbox_cursor, result.inbox_cursor)
        nếu có input chưa được collect: chạy lượt kế
        nếu không: chờ input/control
```

Pseudocode chỉ minh họa scheduling. Initial bootstrap còn phục hồi run/checkpoint dở; transient Activity retry giữ cùng run, không tạo run mới. Pause tại boundary giữ continuation để resume được cả khi input đã collect hết, không đợi một message mới. Lỗi terminal phải lưu lý do và tránh tự lặp vô hạn chỉ vì cursor chưa tiến; không thêm product budget số model calls.

`run_agent` là Activity dài async: mở đúng LangGraph checkpoint/thread, lấy config/mounts hiện hành, tạo Mirage workspace/session cho invocation, chạy graph streaming, lưu transcript/outcome, đóng tài nguyên. Activity heartbeat định kỳ, cancellation hợp tác; không dùng Workflow code để gọi LLM/HTTP/Redis/PostgreSQL.

Workflow chờ `run_agent` không khóa async Update handlers. Lock receive không ôm toàn graph. Việc một Leti bận không khiến AgentWorkflow của Leta hoặc Leti khác chờ.

### Workflow gọi Workflow như thế nào

API và tools đang chạy trong Activity có Temporal Client nên gọi Update-with-Start trực tiếp. `HumanRequestWorkflow` và `ScheduleDeliveryWorkflow` giao kết quả qua Activity `deliver_agent_input`; Activity này dùng Client gọi `AgentWorkflow.receive`, trả sau commit inbox.

Không viết `external_handle.execute_update(...)` trong Workflow: Python SDK external workflow handle hỗ trợ signal/cancel, không phải Client update API. Boundary Activity ở đây là kết nối thực tế được retry; không phải một dispatcher service hoặc queue mới.

### Continue-As-New và dừng

- AgentWorkflow rotate history theo event count/bytes và server suggestion, ưu tiên giữa các agent runs. Nếu run_agent kéo dài, cần cooperative yield tại checkpoint boundary để rotate mà giữ continuation/cùng run ID nghiệp vụ; xem review mục 9. Chờ Activity kết thúc/yield và `workflow.all_handlers_finished` trước khi Continue-As-New/return, kể cả khi paused/idle và history đã tới ngưỡng.
- Giữ agent/thread identity và counters cần thiết; không mang transcript/inbox bodies sang execution mới. SQL bootstrap + checkpoint dùng để khôi phục, không có background reconciliation.
- Pause toàn Leta chặn bắt đầu model call mới, áp cho các Leti trong boxes. LLM/tool call đang chạy hoàn tất boundary hiện tại; inbox, HITL và lịch vẫn nhận. Resume đọc tiếp dữ liệu đang chờ; không compact/xóa history vì pause.
- Delete đánh dấu resource ngừng nhận mới trước; hủy schedules/pending requests, dừng runtimes và chờ Activity dừng trước khi trash home. Late input không làm box sống lại. Giữ history/files archived theo lifecycle đã chốt; không gọi destructive account/scope purge rồi hứa vẫn giữ files.

## 6. HITL: hai loại, cùng bốn status

`pending → resolved | cancelled | expired`. Status dùng chung; decision/outcome phụ thuộc loại. Request workflow chờ độc lập, agent không có trạng thái whole-agent waiting-for-human.

### Ask user

`ask_user(title, questions[], timeout_seconds?)` luôn hỏi owner của Leta. Leta và Leti đều gọi được. Card hiện requester thật và box nếu có; Leti không vì vậy có quyền send_message(owner).

Mỗi form có nhiều question: single_choice, multiple_choice hoặc text. Hai choice types không có Other; single nhận `{option_id:null|id,note:string}`, multiple nhận `{option_ids:[],note:string}`; chọn rỗng/note rỗng hợp lệ. Text chỉ `{text:string}`. Backend validate map answers theo question IDs; submit là một lần trả lời form, khác chưa submit.

Tool trả pending ngay và đóng tool-call protocol. Khi owner submit, request workflow gửi answers vào inbox chính requester; agent tiếp tục bằng context/history và request ID ở một model call sau. Không giữ stack Python hoặc LangGraph interrupt chờ owner, không tự chạy lại tool call cũ.

### Approval xin personal scope

Tool `request_access(resource:{type:"personal_scope",user_account_id}, role:"viewer"|"editor"="viewer", reason, timeout_seconds?)`. Runtime xác định personal scope/approver từ user trong workspace; grantee luôn account Leta, kể cả requester là Leti.

```json
{
  "id": "request-42",
  "type": "approval",
  "status": "pending",
  "requester_agent_id": "leti-research",
  "grantee_account_id": "leta-account",
  "approver_account_id": "user-a",
  "resource": {"type": "personal_scope", "id": "scope-a"},
  "role": "viewer",
  "reason": "Đọc tài liệu để tổng hợp báo cáo",
  "expires_at": "2026-11-08T09:00:00+07:00"
}
```

Accept ghi decision, gọi Workspace scope access dưới authority người duyệt, rồi giao `{request_id, granted:true, role, mount_path}` về inbox sau khi cấp thành công. UI phân biệt đã chấp nhận và kết quả cấp quyền; nếu đang retry cấp quyền thì chưa báo agent đã đọc được. Deny/cancel/expire không cấp quyền, vẫn giao outcome đúng requester. Quyền thật thuộc Workspace/SpiceDB, không thuộc HITL row.

Accept không chạy tool bị giữ, không có dangerous-tool approval policy hoặc test_approval. Agent nhận quyền rồi chọn read/search/write như bình thường. Leti hưởng quyền qua Leta; resource owner phải thấy điều đó trên card. Owner Leta không tự được duyệt thay user sở hữu scope.

Timeout là hạn trả lời request, không là hạn của grant. Quyền giữ tới khi resource owner thu hồi. Xóa box/cancel request không thu hồi grant đã cấp cho Leta. Thu hồi chặn đọc mới, không xóa nội dung đã đọc khỏi context/history; owner Leta có thể xem transcript/kết quả đó.

### Response/timeout/retry

Activity resolve kiểm tra người trả lời, status pending và deadline theo server trong transaction. Một kết quả terminal được chấp nhận; đáp án tới sau deadline/cancel/resolve bị từ chối kèm trạng thái hiện hành. Timer expiry cập nhật có điều kiện nên không ghi đè response đã lưu. Không dựa vào thời điểm browser click hoặc việc worker xử lý timer sớm hơn response.

Nếu đã accept rồi worker dừng khi cấp quyền, Workflow retry bước grant với cùng request/scope/grantee; dùng relation update idempotent hiện có. Sau đó deliver result với cùng message ID. Không tạo lại request hoặc cấp thêm role khác.

## 7. Lịch: một model sản phẩm và một scheduler

UI gọi **Lịch**; domain/tool/API gọi **schedule**. Calendar là cách xem, reminder là nội dung/mục đích. Không có hai scheduler, không thêm APScheduler/dateutil executor.

PostgreSQL lưu title/content/target/spec/paused/end_at. Native Temporal Schedule sinh các lần tới hạn; delivery workflow đưa input vào inbox. FE lấy definitions và occurrences từ API rồi render ngày/tuần/tháng.

| Spec | Ví dụ | Native Temporal |
| --- | --- | --- |
| at | 5s nữa, 1h nữa, ngày mai 09:00 hoặc timestamp cụ thể | CalendarSpec đủ date/time, giới hạn một action |
| interval | mỗi giờ hoặc mỗi 5 ngày tính từ anchor | ScheduleIntervalSpec every + offset |
| calendar | ngày 1 hằng tháng, thứ Hai/thứ Sáu 08:00 | CalendarSpec + IANA timezone |

Relative at/anchor normalize và persist một lần, không tính lại now+duration khi retry. Interval tính theo thời lượng; một tháng dùng calendar. end_at tùy chọn cho recurring ngừng sinh mốc mới, không hủy input đã giao. Daily/weekly là UI presets, không hardcoded engine variants; không hứa hỗ trợ mọi RRULE/Google Calendar feature.

`ScheduleChangesWorkflow` nhận command → lưu definition/state → apply native Schedule bằng schedule ID ổn định → báo đồng bộ xong. Các bước retry trong cùng workflow, không outbox/poller. Delete/pause product record được delivery kiểm tra trước khi gửi, kể cả native start đã nằm trong queue.

`ScheduleDeliveryWorkflow` đọc schedule ID và mốc scheduled gốc từ metadata của execution do Schedule start; không lấy giờ worker tỉnh lại làm giờ hẹn. Temporal scheduler có search attributes `TemporalScheduledById` và `TemporalScheduledStartTime`; cần lab xác nhận đọc các attrs này với server/SDK pin của Openlet. Message ID của occurrence giữ ổn định qua retry, không tạo entity delivery/operation mới.

Chốt `BUFFER_ONE` cho native schedule overlap: khi delivery trước chưa xong, giữ tối đa một start chờ. Delivery kết thúc sau commit inbox, không chờ LLM hoàn tất; agent bận vẫn có thể nhận nhiều mốc đã được giao. BUFFER_ONE không làm inbox latest-only và không gộp các input đã commit.

Worker tắt: durable delivery/timer chờ worker, tới lại giao trễ theo chính sách đã chốt. Temporal server outage khác worker outage, còn chịu catchup window mặc định. Không hứa bù vô hạn mọi occurrence. One-off đã quá hạn khi provision thì giao một lần ngay với scheduled_at gốc.

GET occurrences trong khoảng hữu hạn dùng timestamp đã lưu cho at và `ListScheduleMatchingTimes` qua backend cho recurring. Native matching-times là preview, không là execution history; lịch sử thực tế lấy messages/runs có schedule_id/scheduled_at. Nếu Temporal tạm lỗi, definitions PostgreSQL vẫn đọc được, preview recurring có thể chưa có.

## 8. Messaging, box và luồng xuyên suốt

Dùng một `send_message(to, content, in_reply_to?)`, resolve ID/name trong roster được phép:

- Leta → owner hoặc box ID; gửi box route vào representative.
- Leti → peer có edge vô hướng.
- Representative → parent Leta, source/reply route mang box ID.
- Leti khác gửi kết quả qua peers tới representative; không tự gửi thẳng Leta/owner.

Box một Leti vẫn đi cùng đường representative. Tên Leti unique trong toàn Leta, immutable. Box name unique trong Leta; slug suy ra từ name cho đường dẫn, kiểm tra collision; không field slug riêng. Box ID là địa chỉ ổn định, không dùng path làm identity.

Create box khai báo nguyên graph, tạo config/home/runtimes; không tự giao việc. Delete nguyên box theo lifecycle, không sửa/xóa từng Leti trong MVP. get_box/canvas cho xem prompts/roster/state/schedules/HITL, không đồng nghĩa được sửa mọi cấu hình.

Luồng chuẩn:

1. Owner gửi việc; receive commit inbox Leta, UI xác nhận đã gửi.
2. Leta nhận digest, đọc, `send_message(box)`; inbox representative được commit, tool trả ngay.
3. Leti xử lý; cần thông tin thì `ask_user` tạo card cho owner và trả pending. Nó có thể làm việc khác hoặc kết thúc lượt bằng note.
4. Lịch khác tới hạn → inbox Leta; Leta gửi lời nhắc qua send_message(owner). Không chờ request của Leti.
5. Owner submit form → inbox đúng Leti đã hỏi. Không đi qua chat Leti–owner, không nhầm owner approval cho resource scope user khác.
6. Leti tiếp tục; peers/representative gửi kết quả dưới box ID → inbox Leta → Leta send_message(owner).

Final model text chỉ là note có chủ đích, không tự tạo câu trả lời hoặc chuyển node. Không chép lại toàn câu đã gửi qua send_message.

## 9. Retry và hai lớp durability

Temporal retry `run_agent` giữ cùng run ID. Activity đọc run đã hoàn tất thì trả kết quả cũ; nếu dở, load cùng LangGraph thread/checkpoint và tiếp tục nodes đang pending. Không thêm lại input thành một run mới hoặc gọi model lại từ đầu vô điều kiện.

Checkpoint sync trước tools giữ assistant output/tool_call_id bền. Tool send_message/HITL dùng ID đã lưu để retry không nhân đôi message/request. Tool result đã lưu trong transcript/checkpoint được dùng lại. LetFS mutations giữ precondition/idempotency tương ứng; arbitrary shell không tự có exactly-once chỉ nhờ checkpoint. Không tự lặp một ghi có kết quả chưa xác định mà bỏ qua kiểm tra backend.

Một Activity graph writer cho một agent; dùng PostgreSQL advisory lock cùng checkpoint connection như phần lab hữu ích. Heartbeat/cancellation để dừng Activity và giải phóng workspace/session/connection; không thêm leasing/fencing/revision engine riêng. Precondition node revision hiện có của LetFS vẫn giữ.

Crash sau commit inbox nhưng trước update completion: persist retry trả row cũ và cập nhật latest_seq. Crash sau checkpoint steering: cursor và input cùng tồn tại, không nuốt message. Crash sau gửi reply nhưng trước tool-result checkpoint: cùng call/message ID trả reply cũ, không gửi thêm. Temporal replay không tái gọi LLM của Activity đã hoàn tất; Activity chưa ghi completion phục hồi qua run/checkpoint.

Ba replay khác nhau: Temporal history replay; LangGraph checkpoint recovery; Redis client event replay. Không coi giảm SSE frames là giảm Temporal history hoặc checkpoint writes.

### Review lifetime nhiều tháng/năm và chi phí phục hồi

Agent identity/thread có thể sống lâu; không đồng nghĩa giữ một Temporal Execution hoặc một graph invocation chạy mãi. Số pending inbox <=100 không giới hạn tổng Temporal events đã tích lũy, tổng transcript hoặc kích thước working state. Cần phân biệt số checkpoint cũ tăng với nội dung checkpoint hiện tại tăng.

| Cơ chế | Phạm vi dữ liệu cần đọc/phát lại | Tăng theo tuổi agent? |
| --- | --- | --- |
| Temporal cold replay | History của Workflow Execution hiện tại, từ lần Continue-As-New gần nhất. Một Execution có thể chứa nhiều agent runs. Sticky cache có thể chỉ nhận phần history mới. | Không buộc tăng theo tuổi agent nếu rotate history; có thể tăng nếu bỏ rotate. |
| LangGraph recovery | Latest checkpoint của thread + channel blobs/pending writes nó tham chiếu; không fold tất cả checkpoint từ lúc tạo agent. | Chi phí theo working state hiện tại và DB/index health; không tuyến tính số checkpoint cũ. |
| Redis client replay | Những events sau cursor trong stream của agent run hiện tại, thuộc replay log còn giữ. | Theo lượng events/bytes cần gửi lại trong cửa sổ còn giữ, không theo toàn đời agent. |

**Temporal:** Python SDK 1.35.0 có Info.is_continue_as_new_suggested(), get_current_history_length() và get_current_history_size(), xác minh tại [workflow/_context.py](https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/workflow/_context.py). Continue-As-New tạo Run ID Temporal mới, giữ Workflow ID, history mới; không xóa agent/context/box và không replay lại các Executions đã đóng. Không nhầm Temporal Run ID với run_id nghiệp vụ trong bảng runs/Redis.

Điểm cần siết so với draft: chỉ rotate sau khi agent run tự hoàn tất chưa đủ cho một run làm việc liên tục trong thời gian dài. Khi history gần ngưỡng, runner cần yield tại checkpoint boundary bằng continuation path như pause/resume; sau đó Workflow drain handlers, Continue-As-New với IDs/counters/continuation nhỏ, tiếp tục cùng thread/run nghiệp vụ. Không tạo run/message/tool effects mới chỉ vì rotate, không đặt budget số model calls. Control path báo nhu cầu yield cho runner; transport/threshold cụ thể được kiểm chứng trong plan. Main wait condition cũng phải xét nhu cầu rotate khi idle/paused. Nếu chỉ nằm chờ lâu mà không có event thì không cần rotate theo lịch ngày/tháng.

Áp dụng rotate cho ba coordinator lâu dài LetaLifecycle/BoxLifecycle/ScheduleChanges sau commands hoàn tất. HumanRequest và ScheduleDelivery là executions riêng mỗi request/occurrence, không gộp history cả đời agent. Các nhận tin/HITL/timer tạo events; token deltas và từng LLM/tool step bên trong run_agent không được đưa toàn bộ vào Temporal history. History cũ còn lưu theo namespace retention khác với chi phí runtime replay hiện tại.

**LangGraph/PostgreSQL:** đối chiếu wheel [langgraph-checkpoint-postgres 3.2.0](https://pypi.org/project/langgraph-checkpoint-postgres/3.2.0/) đã tải ở lượt review: aio.py::AsyncPostgresSaver.aget_tuple dùng WHERE thread_id/checkpoint_ns ORDER BY checkpoint_id DESC LIMIT 1 khi không chỉ checkpoint ID. base.py::SELECT_SQL join blobs theo channel_versions và pending writes theo checkpoint_id; các primary keys bao gồm những keys này. Vì vậy đường recovery thường không phải list toàn bộ checkpoint history. Các API time-travel/history listing là đường đọc riêng.

Cho phép giữ checkpoint cũ lâu dài không đòi runtime deserialize tất cả chúng. Tuy nhiên phải persist working state đã compact (summary + recent messages), không chỉ trim prompt tạm thời. Nếu messages trong latest checkpoint vẫn tăng vô hạn, deserialize/serialize/RAM, snapshot streaming và LLM input vẫn ngày càng nặng. Database/index/backup/disk tăng theo dữ liệu lưu; không hứa latency tuyệt đối bất biến khi DB vượt khả năng phần cứng. Việc prune checkpoint cũ không là điều kiện bắt buộc chỉ để tránh replay toàn lịch sử theo giả định user cho phép storage tăng.

**Redis:** stream dùng run_id nghiệp vụ, có TTL và giới hạn dung lượng độc lập; reconnect đọc suffix sau cursor. Khi cursor/log không còn hợp lệ thì API trả trạng thái reset và client lấy snapshot/history phân trang PostgreSQL, tiếp tục từ live stream hiện tại; không phát lại toàn transcript nhiều năm. TTL được gia hạn khi stream đang chạy nên riêng TTL không chặn một run liên tục phình lớn; cần byte/event cap. Snapshot chứa working state/UI page có giới hạn, không chép cả activity_log vào MESSAGES_SNAPSHOT.

Bằng chứng [lab streaming.py](../../../agent-lab/labs/durable-chat/chat/streaming.py): event_keys(run_id) dùng run:<id>:events; STREAM_TTL=3600, STREAM_BYTES=64MiB là cấu hình LAB, chưa chốt cho production. read_events đọc suffix XRANGE sau cursor; _APPEND đánh dấu log invalid khi vượt byte cap, không tự trim tùy ý rồi giả vờ reducer vẫn hợp lệ. touch gia hạn TTL trong lúc run đang sống. [API events](../../../agent-lab/labs/durable-chat/chat/api.py) chỉ gọi open_events quét prefix cho nhánh compatibility không có stream generation; không copy nhánh hỗ trợ log cũ này vào engine mới. SSE coalescing giảm frames phía client, không xóa chi phí đọc/parse Redis events đã lưu.

**Bổ sung kiểm chứng trong plan:** nhiều agent runs qua nhiều lần Continue-As-New; run chưa tự kết thúc nhưng cần yield/rotate; receive lúc chuyển Execution; cold replay sau cache eviction; checkpoint history lớn nhưng latest state có giới hạn; reconnect đầu/cuối stream, expired cursor và một run vượt stream cap. Đo warm/cold latency theo history/state/stream bytes, không suy từ số tháng giả lập. Inbox/transcript UI dùng indexed cursor pagination, không tải toàn lịch sử hoặc OFFSET sâu cho mỗi lượt.

## 10. Permission, Mirage và LetFS

Leta có role/shared/personal như member thường. Bổ sung `workspace.create_agent` cho human active owner/admin/member: chỉ tạo agent do chính caller sở hữu, role member, trong workspace đó; không dùng quyền này để thêm human/agent của người khác hoặc cấp admin. Personal scope vẫn tạo theo luồng membership hiện có. Owner được viewer grant trên Leta personal và xem/quản lý resources Leta; owner-of-account không tự cho phép đọc shared scopes mà owner đã mất quyền. Personal scope owner human không tự mount vào Leta; dùng resource approval.

### SpiceDB: schema delta và relationships đã chốt cho plan

**Schema delta đã chốt chỉ thêm một permission vào workspace:**

```zed
permission create_agent = owner + admin + member
```

Không đổi account.self/owner hoặc scope.viewer/editor/manager; không thêm definition Leta/Leti/box/schedule/HITL. account.read/update hiện có đủ kiểm tra owner đối với metadata/quản lý Leta; letfs tiếp tục check scope permissions. Graph edges và box-home restriction là policy runtime SQL/Mirage, không tạo account/tuple cho Leti.

create_agent không thay manage_members. Service kiểm tra caller là human active member, target là agent do chính caller sở hữu, role mặc định member và đúng một workspace. Quyền này không thêm human/agent của người khác, không nâng agent thành admin. Workspace AddAccount cần nhánh authorization này, không chỉ kiểm tra ở API leta rồi để Workspace vẫn từ chối member thường.

**Relationships (ví dụ W=workspace, L=Leta account, O=owner Leta, P_L=Leta personal, U=resource owner, P_U=personal của U):**

| Thời điểm | Relationships | Service ghi |
| --- | --- | --- |
| Tạo account Leta | account:L#self@account:L; account:L#owner@account:O | Account, tái dùng SyncRelationships. |
| Join workspace | workspace:W#member@account:L; scope:P_L#manager@account:L | Workspace, membership/default grants hiện có. |
| Owner xem files Leta | scope:P_L#viewer@account:O | Workspace ghi cùng batch default relationships khi tạo managed membership; giữ khi archive để owner xem files. |
| Shared scope | scope:shared#editor@workspace:W#member; manager theo W#owner/W#admin | Quan hệ shared hiện có, không tạo bản copy direct grant cho mỗi Leta. |
| HITL accept viewer/editor | scope:P_U#viewer hoặc editor @account:L | Workspace, theo quyết định đúng owner U đã xác thực. |
| Deny/cancel/expire | Không ghi grant | HumanRequestWorkflow chỉ lưu outcome/giao inbox. |
| Từ bỏ một foreign scope | DELETE direct viewer/editor/manager của L trên scope đó; thao tác theo role API hiện có | Workspace, cho L tự bỏ hoặc O thay L bỏ. Không xóa grants của account khác. |
| Archive/leave workspace | Gỡ workspace roles/default manager của L và direct scope grants mà L nhận trong W | Workspace; giữ account ownership, files/history và viewer O trên P_L. Không xóa grants của L ở workspace khác bằng filter global account. |
| Xóa một box | Không đổi scope grants của L | Chỉ lifecycle box/runtime/home; Leti không có tuple riêng. |

Owner O có thể quản lý Leta từ bỏ quyền, nhưng không tự có manage_access trên P_U và không tự được duyệt request thay U. Không thêm traversal từ scope tới account.owner để khiến owner Leta đọc mọi scope mà Leta được cấp. Dữ liệu đã vào transcript/kết quả vẫn thuộc khả năng owner xem đã chốt; revoke chặn truy cập mới.

Owner resource lấy từ Workspace personal-scope mapping, không coi mọi scope manager là người nhận HITL. Card approval cấp quyền cho L và các Leti kế thừa; Leti requester không thành grantee/account riêng. Owner resource chỉ xem/trả lời request nhắm tới mình, không vì thế được xem cả engine của Leta.

**Các thay đổi code/contracts cần có khi lập implementation plan:**

1. Sửa [schema.zed](../../packages/contracts/authz/schema.zed), chạy contracts generator để cập nhật Go actions, Python _authz_actions và action-resource-matrix; không sửa tay generated files. Generator thực tế: [action_bindings](../../scripts/contracts/generate.py); package contracts đã có generate/check scripts.
2. Bổ sung type/owner_id vào [AccountSummary proto](../../packages/contracts/proto/openlet_api/account/v1/account.proto), handler và Go/Python clients để Workspace kiểm tra managed account/owner và cấp owner viewer. Store.Profile/Summaries đã có hai fields này, nhưng proto/clients hiện chỉ có id/name/avatar. Lookup ownership phục vụ authorization dùng dữ liệu Account, không tin owner_id từ client.
3. Workspace AddAccount thêm nhánh create_agent ở trên; membership default relationship write thêm owner viewer. Recovery giữ direct grants như hiện có và phải giữ/tái lập owner viewer theo Account ownership + personal-scope mapping, kể cả retained archived files; không dựng lại grants từ lịch sử HITL. Cần giữ riêng quyền mặc định với grants người dùng có thể chủ động từ bỏ.
4. ChangeScopeAccess mở nhánh revoke nếu actor là subject hoặc verified owner của subject agent. Grant/quản lý grants account khác vẫn scope.manage_access. ChangeMember mở nhánh owner thay managed agent leave; membership removal cleanup direct grants trong đúng workspace, hiện code chưa làm. Giữ cùng retry identity qua internal calls; Mutate hiện tự sinh Key mỗi lần nên không được mặc định đã dedup cross-service retries. Tái dùng cơ chế receipt/command ID sẵn có khi cần, không thêm operation/outbox domain.
5. Accessible-scope/filesystem-view ở Workspace: candidate scope IDs trong workspace + BulkCheck read_metadata/read_content/write theo batch tối đa 100; trả effective rights và mapping mounts. Không thêm ACL table hoặc coi request resolved đồng nghĩa quyền vẫn còn. Backend thực thi quyền hiện hành trên mỗi thao tác, cache không là authority.
6. Kiểm tra authorization với SpiceDB thật: member được tạo own Leta nhưng không thêm human/agent khác/admin; owner xem Leta personal nhưng không tự đọc P_U; accept chỉ resource owner, Leti dùng account L; revoke self/owner-agent không cần manage_access của P_U; archive cleanup đúng W, giữ owner viewer/history; rebuild không phục hồi discretionary grants đã bỏ. Kiểm tra retry grant/leave qua service boundary, không chỉ mock client.

Account và Workspace tiếp tục sở hữu relationship writes của mình. Worker leta có thể CheckPermission để authorize API/tool nhưng không trở thành writer tổng của SpiceDB. Account provisioning internal contract mới phải giới hạn caller/actor đúng service identity; GetAccountSummaries hiện chỉ cho Workspace service gọi, không mặc định Leta đã có quyền gọi RPC đó.

**Rollout:** explicit schema migration trước writers mới. [VerifySchema/InitializeSchema](../../packages/go/authz/schema.go) hiện so sánh chính xác expected schema; startup/readiness không được overwrite policy đã tồn tại. Vì vậy phối hợp migration và triển khai binaries/contracts đồng bộ; không coi thêm permission là có thể rolling tùy ý với binaries đang verify schema cũ. Không cần backfill workspace.member tuples chỉ để permission mới có hiệu lực; owner viewer cần bổ sung cho managed memberships cũ nếu có, không đọc HITL để cấp lại foreign grants.

### Leave/list scopes: hiện trạng đã xác minh và đề xuất bổ sung 22:34

- Có DELETE /v1/workspaces/:ws/members/:account. ChangeMember tại apps/workspace/internal/workspace/service.go:162 cho self-remove không cần manage_members, nhưng workspace owner không được leave bằng flow này. Actor khác target vẫn phải manage_members; chưa có nhánh owner thay managed agent leave chỉ dựa trên account ownership.
- Có DELETE /v1/workspaces/:ws/scopes/:scope/access/:account với role trong body. ChangeScopeAccess tại relations.go:166 luôn check scope.manage_access, kể cả revoke và actor==target; chưa có self-leave/owner-of-agent branch. Đây là giới hạn implementation hiện tại, không phải lý do thiết kế phải cấm owner từ bỏ grant của Leta.
- Scope access hiện là direct relations viewer/editor/manager trong SpiceDB, không có bảng scope_members riêng. account.update=self+owner là quyền account hiện có để tái sử dụng khi xác minh owner của managed agent.
- Chưa có API liệt kê đầy đủ accessible scopes theo account trong workspace. GET workspace chỉ trả shared_scope_id và personal_scope_id của caller; GET members trả membership/personal IDs, không lọc thành danh sách scopes đọc được. Workspace HTTP router, LetFS HTTP router và FilesystemService proto không có endpoint này. Aggregate filesystem-view đã chốt ở phần mount là API CẦN BỔ SUNG, chưa có code.

Đề xuất sửa quyền cho revoke/leave trên existing access API: actor là subject hoặc owner đã xác minh của subject agent được từ bỏ direct grants của subject; grant và việc quản lý grants của account khác vẫn dùng scope.manage_access. Scope owner vẫn là approver duy nhất cho request_access. Quyền default từ workspace membership không thể bỏ chỉ bằng xóa một direct viewer/editor tuple; không tạo thêm deny ACL để giả lập leave shared scope.

Đề xuất mở nhánh tương tự cho owner thay agent leave workspace tại ChangeMember; không thêm một leave-workspace endpoint khác. Không tự bổ sung agent tool leave_workspace vào MVP chỉ từ câu hỏi khảo sát API này.

List accessible scopes nên nằm ở Workspace service, tái dùng aggregate filesystem-view logic đã chốt: candidate scopes trong workspace + batch authorization cho target account, trả scope/owner/effective permissions và có thể leave direct grant hay không. Caller phải được xem target (self hoặc owner managed agent); không suy ra access từ HITL history. Public path/payload cụ thể chưa chốt, không mở hai nguồn authority cho scopes và mounts.

Nguồn: [Workspace router](../../apps/workspace/internal/transport/http/server.go), [ChangeMember](../../apps/workspace/internal/workspace/service.go), [ChangeScopeAccess](../../apps/workspace/internal/workspace/relations.go), [authz schema](../../packages/contracts/authz/schema.zed), [LetFS router](../../apps/letfs/internal/transport/http/router.go), [LetFS proto](../../packages/contracts/proto/openlet_api/letfs/v1/letfs.proto). ApplyMembership + WriteMemberRelationships hiện cập nhật membership/default grants; không thấy bước xóa tất cả foreign direct grants trong flow leave. Không coi leave-workspace hiện tại là cleanup hoàn chỉnh mọi scope grant.

| Mount | Đích |
| --- | --- |
| ~/ của Leta | Leta personal scope |
| ~/ của Leti | Leta ~/.leti/<derived-box-slug>/, mọi Leti trong box dùng chung |
| /shared/ | Shared scope hiện có quyền |
| /users/<human-account-id>/ | Personal scope đã grant cho Leta; viewer READ, editor WRITE |

Workspace service bổ sung aggregate filesystem-view API: đọc membership/scopes theo workspace rồi BulkCheck theo batch, không query cây file hoặc dựng grants từ HITL history. Không có bảng grant song song SpiceDB. Mỗi agent có Mirage workspace/session riêng theo invocation, Redis cache theo namespace ổn định.

Mirage 0.0.8 hỗ trợ add_mount/unmount/set_mount_mode. Dựng view đầu invocation, refresh tại boundary sau access result/get_workspace; không đổi mount giữa shell/Monty đang chạy. Cache FRESH/fingerprint và backend authz vẫn áp cho truy cập mới; mount view/cache không thể vượt quyền đã bị revoke.

LetFS redesign đã được đồng ý: inline UTF-8 TEXT, native Stat/List/Tree/ReadText range-lines-head-tail/TextSearch/Write-Append-Patch-Truncate, node operations và artifact image. Blob đọc metadata + artifact tree; không raw blob hoặc sửa blob. Image vẫn qua read_file trả multimodal artifact/preview. Filesystem tools luôn qua Mirage/session dispatcher; Monty dùng cùng view, không host Python/host Bash.

Adapter triển khai BaseVFS hooks: stat/readdir/read/read_tree; files_containing/lines_containing; first_lines/last_lines/line_count/follow/checksum; write/append/pwrite/truncate; copy/dir_copy/rename/unlink/rmdir/rm_r/_replace; semantic search/search_many; read_image qua vfs_call. Mirage tự mapping commands/flags trong khả năng thư viện, chấp nhận fallback/giới hạn của nó; không fork grep parser. Backend không dùng semantic top-k thay exact text search.

GIN pg_trgm phục vụ candidate substring search trên text. Benchmark trước chưa chứng minh default planner query production đã tối ưu; không tắt seqscan toàn cục. Ưu tiên inline text/artifacts, không index bytes blob. Full hook/API evidence nằm trong checkpoint.

## 11. Streaming/UI và tools

Worker emit AG-UI run/text/tool events vào Redis, API proxy SSE theo subscriptions. Metadata phân biệt note/public assistant transcript với message thật gửi owner. send_message xong phát domain message event tham chiếu row đã commit; hỏi user phát request card. Tool calls/results hiện trong journal có thể collapse; hidden reasoning không là dữ liệu UI.

Reconnect lấy snapshot/history PostgreSQL, sau đó tiếp tục Redis cursor khi còn hiệu lực; nếu stream đã hết TTL/evict thì lấy snapshot lại. Không cần chat realtime service. Có thể gộp adjacent deltas tại SSE proxy cùng message/tool identity, không vượt start/end/tool boundary. Bằng chứng lab 4681→438 events chỉ cho workload đó và không giảm Redis writes vì gộp sau Redis.

Tools tối thiểu theo nhóm (args đã ghi trong checkpoint):

- Workspace/context: get_workspace, list_workspace_members, search_history, read_history.
- Messaging: send_message; riêng Leta thêm list_inbox/read_inbox.
- Boxes, riêng Leta: list_boxes/get_box/create_box/delete_box.
- HITL: ask_user/request_access/list_hitl/get_hitl/cancel_hitl.
- Lịch: create/list/get/update/delete_schedule; paused cho pause/resume.
- Filesystem/compute/RAG: list_files/read_file/write_file/edit_file/run_shell/run_python/semantic_search.

Owner tạo/quản lý Leta, model/reasoning, trả lời request, xem calendar và stream qua app APIs, không biến các thao tác owner thành agent tools. Không có send_box, test_approval, tool approve executor, graph-edit tools hoặc operation/delivery entities.

## 12. Bằng chứng và phần còn cần kiểm chứng

Đây là thiết kế, không phải tuyên bố production engine đã chạy. Nguồn hiện trạng và khảo sát đầy đủ ở checkpoint; các điểm có ảnh hưởng trực tiếp:

- [WorkspaceChanges](../../apps/workspace/internal/temporal/relationships.go): Update-with-Start, lock ngắn cho mutations, Activity và Continue-As-New/AllHandlersFinished đã là pattern Openlet.
- [CreateManaged](../../apps/account/internal/account/service.go) và [account Store](../../apps/account/internal/account/store.go): managed account tạo được, entrypoint hiện tự sinh ID, chưa tạo runtime/member/scope.
- [Lab worker](../../../agent-lab/labs/durable-chat/chat/worker.py), [lab workflow](../../../agent-lab/labs/durable-chat/chat/workflows.py), [lab audit](../../../agent-lab/docs/integration-audit.md): whole-graph Activity, async saver, Redis/SSE chạy được; lab giữ inbox Temporal và chặn same-agent ở pending interrupt, cần thay như thiết kế này.
- [Temporal Python SDK 1.35.0 README](https://github.com/temporalio/sdk-python/blob/1.35.0/README.md): async update handlers, activities, external handle signal/cancel, heartbeat và all_handlers_finished. Context7 lượt này chỉ có bản 1.34.0; đã đọc thêm source 1.35.0, không coi 1.34 là bản repo đang pin.
- [Client 1.35.0](https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/client/_client.py): execute_update_with_start_workflow chờ update hoàn tất; RPC timeout không đồng nghĩa update bị hủy. [Schedule source](https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/client/_schedule.py) xác nhận CalendarSpec/IntervalSpec/BUFFER_ONE.
- [Temporal scheduler v1.29.0](https://github.com/temporalio/temporal/blob/v1.29.0/service/worker/scheduler/workflow.go): addStartWorkflowSearchAttributes gắn nominal scheduled time và schedule ID. Đây là đối chiếu source metadata, chưa xác nhận version server thực tế của Openlet qua integration.
- [LangChain 1.4.8 distribution](https://pypi.org/project/langchain/1.4.8/) (`langchain/agents/factory.py`, `create_agent`) và [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence): source wheel đã đọc xác nhận create_agent trả CompiledStateGraph, middleware/checkpointer; sync durability khác async I/O. Bản LangChain/LangGraph lấy từ lab là mốc thử, chưa là dependency pin của leta production.
- [Mirage integration](https://docs.mirage.strukto.ai/home/integration) và [Mirage v0.0.8 workspace source](https://github.com/strukto-ai/mirage/blob/v0.0.8/python/mirage/workspace/workspace/workspace.py): VFS hooks, dynamic mounts/cache; cần chạy adapter thật trước khi kết luận end-to-end.

Kiểm chứng lúc plan/implement: receive retry/crash và commit ack; same-agent steering/HITL không chặn việc khác; sync checkpoint + transcript; tool effects không nhân đôi; pause/delete lúc có Activity/HITL/lịch; schedule CRUD/at đã quá hạn/BUFFER_ONE/worker outage/scheduled_at; đổi model/reasoning và compaction; mount grant/revoke/cache/search; LetFS hooks và GIN query plan trên workload thật. Không thêm default model-call limit từ lab vào product policy.

Thứ tự triển khai đề xuất: contracts/permission + LetFS view/text APIs; inbox/AgentWorkflow/create_agent/durable history; messaging/boxes; HITL/resource grants; schedule/calendar APIs; streaming/journal; integration và failure checks trước frontend.

Chủ động hoãn: multi-user/group/bot chat, external connectors, quota/system notifications, Dify/n8n generic node execution, full graph editor/sửa từng Leti, task/job engine riêng, full Google Calendar/RRULE/sync, computer provisioning, search service mới và purge archive tự động.
