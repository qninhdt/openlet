# Agent tools: agent chọn ý định, system quản lý cơ chế

Ngày 2026-11-13. Giữ 28 root tools/22 Leti tools và input contracts đã duyệt; bổ sung description có ích cho từng tool/tham số trong [TypeScript draft](tool-contracts.ts), đồng bộ [JSON schemas](tool-schemas.json) và đo lại tokens. Version/timeouts/page sizes/native form và schedule structures vẫn thuộc system. Đây là thiết kế cho app viết mới, chưa runtime implementation. [Plan](plan.md), [HITL](hitl.md), [scheduler](scheduler.md), [filesystem](filesystem.md).

## 1. Ranh giới input đã sửa

Agent chọn việc cần làm: ai nhận, nội dung, path, đoạn cần thay, đồ thị Leti, thời điểm/chu kỳ chạy và filters cần đọc. System quản lý actor/tenant, identities kỹ thuật, versions, time/resource budgets, page size và native normalization. Exposing một field trong backend API không làm field đó trở thành agent argument.

| Field/cơ chế | Quyết định |
|---|---|
| expected_version, file.version | Bỏ khỏi model inputs/outputs; LetFS và native adapter sở hữu concurrency/versioning |
| timeout_seconds của shell/Python/HITL | Bỏ khỏi cả bốn tool schemas; runtime/product policy quản lý |
| limit, max_lines | Bỏ khỏi toàn bộ tool schemas; system chọn page/window/hit budgets |
| Question/option IDs và native form type | System sinh/suy ra; model chỉ gửi text/options/multiple |
| Schedule type/spec/native ranges | System dựng từ ý định timing; giữ type/spec canonical trong SQL/Temporal |
| Actor/workspace/root/grantee/request IDs mới | Runtime inject/cấp; model không tự sinh hoặc chọn invocation actor |
| Existing recipient/resource IDs | Giữ: đây là đối tượng agent muốn thao tác, phải lấy từ context/list và authorize |
| cursor, start_line | Giữ để đọc tiếp/chọn vị trí; system cấp continuation thật và kiểm input |
| Filters, depth, include_prompts | Giữ vì chọn dữ liệu cần xem; hard walk/output budgets vẫn thuộc system |
| overwrite, replace_all | Giữ vì thay đổi ý nghĩa thao tác ghi, default false |
| role, reason, questions, calendar values | Giữ vì là nội dung/quyền/thời gian nghiệp vụ cần người/agent quyết định |
| timezone, starts_at, ends_at | Optional business intent của lịch, không execution timeout hoặc native retry setting |
| title | Ask/schedule_create có thể bỏ; system lấy label ngắn từ câu hỏi/nội dung, không gọi thêm model |

Giữ catalog tĩnh 28/22; root có thêm inbox_list/inbox_read/box_create/box_list/box_get/box_delete. Không thêm version registry, deadline manager, cursor state table, generic action dispatcher hoặc tool discovery để thực hiện những thay đổi này.

Implementation dùng `@tool` và `ToolRuntime` của LangChain/LangGraph: schema sinh
từ Python type hints/Pydantic và docstring, execution qua native ToolNode trong
graph. Không runtime JSON catalog, JSON Schema validator hoặc dispatch theo tên.
JSON snapshot dưới đây chỉ là proposal/token measurement cũ; không được load
vào application. Python declarations là nguồn schema runtime duy nhất.

### Naming

Tên tool theo quyết định người dùng: `<resource_or_namespace>_<action>`, snake_case và resource dùng số ít. Namespaces: inbox, workspace, workspace_member, box, hitl, schedule, history, file, exec. Giữ cách viết file_semantic_search; exec_shell và exec_python dùng chung namespace exec. workspace_member_list có resource workspace_member và action list. inbox_send gửi tới các recipient được phép như trước; hitl_request nhận user_id để xin viewer/editor vào Personal storage duy nhất của user trong workspace; system resolve storage.

Đổi tên model-visible tools trong cả catalog, contracts và examples, không aliases tên cũ. Giữ nguyên activity/workflow IDs, native API method names và archive source; implementation mới đăng ký trực tiếp tên mới bằng native LangChain. Counts hiện tại đã đo lại theo tên mới. Historical baseline trong JSON report giữ literal tên/count cũ để không sửa bằng chứng đo, không là compatibility registry.

## 2. Toàn bộ input contracts

[tool-contracts.ts](tool-contracts.ts) trình bày toàn bộ input types: `LetiTools` có 22 methods, `LetaTools` kế thừa và thêm sáu tools cùng ba phần mở rộng input dành riêng cho root. Method JSDoc là tool description, field JSDoc là parameter description; nội dung được đồng bộ vào JSON snapshot để review đúng payload. Đây là declaration draft, không tool implementation hoặc runtime schema generator. Return type `unknown` không đổi output contracts ở mục 3; output schemas không bind vào model. UUID formats, numeric bounds/defaults và việc chọn timing vẫn theo JSON/owning contracts, không giả TypeScript tự kiểm mọi điều kiện nghiệp vụ.

ID = UUID của resource/user đã biết; TS = ISO 8601 có offset; P = cursor?: string. Optional nghĩa là bỏ field, không tự truyền null; riêng ends_at:null có nghĩa clear recurring cutoff.

### Messaging, workspace, inbox và box

| Tool | Ai có | Input |
|---|---|---|
| inbox_send | Cả hai | to: ID, content: string, in_reply_to?: ID |
| workspace_get | Cả hai | P; page trên allowed messaging roster |
| workspace_member_list | Cả hai | P |
| inbox_list | Root | source_id?: ID, unread_only?: bool=true, P |
| inbox_read | Root | conversation_id: ID, unread_only?: bool=true, P |
| box_create | Root | name, description?="", letis: LetiDefinition[], edges: [name,name][], representative: name |
| box_list | Root | P |
| box_get | Root | box: ID hoặc live name, include_prompts?: bool=false |
| box_delete | Root | box_id: ID |

LetiDefinition={name,description?="",system_prompt}. Agent mới inherit model/effort; overrides vẫn thuộc product configuration API. Local names trong create graph mô tả topology trước khi system cấp IDs. Mutation targets dùng stable IDs. [Box/Leti đã chốt](boxes.md) giữ topology bất biến, home-first rồi atomic active graph; box_create chờ resource sẵn sàng, không start children hoặc gửi việc. Root/Leti messaging graph, direct-human routing và permissions giữ owning design; nhận HITL không mở direct Leti-human chat.

workspace_get trả identity/model/home và bounded roster, không toàn bộ graphs/storages. Mounts xem bằng file_list('/mnt') hoặc ls /mnt. workspace_member_list đọc workspace human owner/member relationships rồi BatchGetUsers lấy display names; không mượn human owner identity gọi Platform public ListMembers. Runtime cố định đúng workspace, không nhận arbitrary workspace ID từ model.

### HITL

| Tool | Ai có | Input |
|---|---|---|
| hitl_ask | Cả hai | recipient_user_id: ID, questions: Question[], title?: string |
| hitl_request | Cả hai | user_id: ID, role?: viewer/editor=viewer, reason?: string="" |
| hitl_list | Cả hai | status?: HitlStatus, box_id?: ID chỉ root, P |
| hitl_get | Cả hai | request_id: ID |
| hitl_cancel | Cả hai | request_id: ID, reason?: string="" |

```text
Question = {text: string, options?: string[], multiple?: bool=false}
```

Không options → text; options + multiple false/omitted → single choice; options + multiple true → multiple choice. multiple=true cần options không rỗng. Đây là lựa chọn UX thật; không yêu cầu model sinh IDs hoặc lặp discriminator. System cấp q1/q2 và o1/o2 theo thứ tự trong request, tạo typed canonical form một lần rồi giữ immutable. Human response validation vẫn dùng IDs đó; empty answers và free-text notes giữ nguyên. Không thêm table hoặc translation framework.

Ask tới bất kỳ current human workspace owner/member; không agent.use hoặc owner routing. HitlStatus=pending/answered/accepted/denied/cancelled/expired. Approval chỉ viewer/editor cho root, current human manage_access và recipient exact vẫn kiểm như [HITL](hitl.md).

Shell execution deadline và thời gian chờ human khác policy. HITL không có model-selectable timeout hoặc expires_at. Default request không deadline như thiết kế đã chốt; nếu trusted product policy cấu hình expiry thì workflow tính/lưu expires_at một lần bằng workflow.now(), không refresh theo retry. Cancel/cleanup/decision races giữ nguyên. Không tự đặt một TTL mới hoặc cho model chọn thời gian chờ cả năm.

### Scheduler

| Tool | Ai có | Input |
|---|---|---|
| schedule_create | Cả hai | content, title?, at?, after_seconds?, every_seconds?, calendar?, starts_at?, ends_at?, timezone?, target_box_id? chỉ root |
| schedule_list | Cả hai | box_id?: ID chỉ root, P |
| schedule_get | Cả hai | schedule_id: ID |
| schedule_update | Cả hai | schedule_id, title?, content?, at?, after_seconds?, every_seconds?, calendar?, starts_at?, ends_at?, timezone?, paused? |
| schedule_delete | Cả hai | schedule_id: ID |

Create chọn đúng một timing selector: at:TS / after_seconds:int>=0 / every_seconds:int>0 / calendar:CalendarValues. Update chọn tối đa một selector; có thể chỉ sửa metadata/paused hoặc timing bounds hiện có. System suy ra at/interval/calendar và giữ type ngoài spec trong SQL; model không gửi type/spec hoặc native ScheduleRange objects.

```text
CalendarValues = map key → integer[]
Keys: second, minute, hour, day_of_month, month, year, day_of_week
Ví dụ 09:00 thứ Hai tới thứ Sáu:
  calendar = {hour:[9], day_of_week:[1,2,3,4,5]}
```

Mỗi field có một shape, không '*'/int/range/list union. Omitted fields dùng native defaults. Range/cadence hữu hạn biểu diễn bằng các giá trị muốn chạy, ví dụ minute:[0,20,40]; system map mỗi value sang native range đơn. Native canonical field/range support vẫn giữ cho owning API và persistence; không bắt agent serialize backend grammar. Không cron parser, natural-language date parser hoặc mini DSL mới.

System kiểm native bounds và timezone. timezone mặc định từ trusted business context, fallback UTC; hiệu lực được lưu một lần trong durable command. Explicit timezone để thực hiện yêu cầu ở múi giờ khác. starts_at là mốc bắt đầu/neo interval khi người dùng cần; bỏ thì workflow chọn accepted time. ends_at là business cutoff của recurring schedule; null để clear. Đây là yêu cầu lịch, không timeout của tool/workflow.

Khi có timing selector mới thì thay pattern; defaults/mốc được normalize một lần trong serialized change. Không selector thì starts_at/ends_at/timezone chỉ cập nhật scalar tương ứng của current canonical pattern dưới existing change lock; không bắt model đọc rồi gửi lại full spec. Không generic deep merge. Bounds không phù hợp pattern bị từ chối; transient retry không normalize lại relative time. Root target self hoặc box representative; Leti chỉ self và không expose target_box_id.

Tool mapping không thêm workflows/activities; inventory hiện sáu workflows/22 activities/ba queues sau workspace cleanup. Giữ SQL definitions/native Temporal timing, one-shot/backfill, finalized receipts và occurrence dedupe. Đây là input mapping, không redesign scheduler engine. User intent chọn pattern vẫn cần validation tại owning boundary; bớt schema không có nghĩa chấp nhận arbitrary dict không kiểm.

### History và filesystem/compute

| Tool | Ai có | Input |
|---|---|---|
| history_search | Cả hai | query?: string, P; omit query để recent summaries |
| history_read | Cả hai | entry_id: ID, start_line?: int=1 |
| file_list | Cả hai | path?: string="~", depth?: int=1, P |
| file_read | Cả hai | path: string, start_line?: int=1 |
| file_write | Cả hai | path, content, overwrite?: bool=false |
| file_edit | Cả hai | path, old_text, new_text, replace_all?: bool=false |
| exec_shell | Cả hai | command, cwd?: string="~" |
| exec_python | Cả hai | code |
| file_semantic_search | Cả hai | query, paths?: string[]=home |

Mọi file_* và exec_* dùng chung Mirage VFS/dispatcher/cache; gRPC chỉ trong LetFS adapter, không convert file tools thành shell commands. Native Redis content/index cache BOUNDED dùng default Mirage 600 giây; warm reads không remote Stat/auth/version. file_edit dispatch custom WRITE hook để LetFS sửa literal atomically rồi Mirage invalidate cache; không dùng high-level read-modify-write edit làm thay đổi contract. Mount discovery refresh lazily hoặc sau grant. Chi tiết [VFS/cache đã chốt](filesystem.md#5-cache-bounded-native-đã-chốt).

Versions không nằm trong model contract. file_edit dùng native atomic literal replacement: old_text phải khớp và default unique, giữ các phần khác của file; conflict thì đọc lại. Low-level adapter hooks cần read-modify-write bên trong một operation tự truyền native version của chính read đó. Không lưu lâu dài map path→version cho model hoặc yêu cầu agent nhớ/copy số version qua activity retries/restarts.

Nơi giữ version đã chốt: current version persist ở PostgreSQL LetFS.files.version; ReadText trả version cùng content cho adapter. expected_version của adapter read-modify-write là local variable/RAM giữ từ read tới native mutation trong cùng operation; LetFS so sánh dưới mutation transaction. Conflict yêu cầu đọc lại, không refresh version để ép write cũ. Không có expected-version column/table/cache hoặc checkpoint baseline giữa tool calls. file_edit kiểm old_text; explicit file_write(overwrite=true) vẫn là full replace không có snapshot guard xuyên lượt. Không thêm registry hoặc đưa version cho model.

file_write mặc định create, existing file cần overwrite=true. Full overwrite/shell redirection vẫn là explicit replacement; không hứa merge mọi concurrent edit như Google Docs hoặc dựng collaboration engine. Native transactions/version increments/permissions/quota/receipts vẫn giữ. Không dùng một fresh Stat để giả rằng đã bảo vệ snapshot model đọc từ lâu.

Runtime tự chọn timeout shell/Python, điểm khởi đầu 30s được cap bởi runtime cancellation budget. Native timeout/memory/output budgets luôn áp dụng; model không thể tăng ceiling bằng arguments. Cancel đóng execution/settle writes trước release writer lock. Request duration không là tuổi đời agent 24/7.

System chọn page/window/hit sizes, khởi điểm lists 20, file metadata 100, text 200 lines và semantic hits 10/path, thêm native byte/output limits. Model dùng cursor/next_start_line để đọc tiếp; không auto-fetch cả dataset. Long line không đảm bảo ít tokens; trả truncation/limit thật và dùng shell/Python chọn/biến đổi nội dung cần đọc. Không tự chế continuation registry hoặc cắt JSON string.

file_list depth=1 dùng native pagination; depth>1 bounded ReadTree với truncated, không flat cursor. Paths ~/... và /mnt/... giữ containment. file_semantic_search default home, selected paths là query scope; native ordering per path, không cross-mount ranking. System giới hạn path count và tổng result budget, không thêm knob cho model. Không hứa native SemanticSearch có pagination khi API không có.

## 3. Output contracts

Page<T>={items:T[],next_cursor:string|null}. Chỉ trả dữ liệu cần cho agent; errors ngắn với owning code/detail, không fake success. Output schemas không được bind thêm vào mọi model request.

Hai output inbox dưới đây theo [JSON input schema đã chốt](inbox-input.schema.json), cùng [field audit](prompting.md#item-schemas-và-field-audit); chưa runtime implementation. Root nhận notifications và dùng inbox_read; Leti nhận bounded full message batches trực tiếp. Dùng chung item shapes cho input và tool results, source={kind,id,name?}; không đổi tool inputs/names hoặc SQL. JSON trước mắt được serialize thành content text; English text renderer có thể thêm sau.

| Tool | Output |
|---|---|
| inbox_send | {message_id,status:sent}, không echo content |
| workspace_get | {workspace_id,leta_id,agent_id,box_id,home,model_id,reasoning_effort?,recipients:Route[],next_cursor} |
| workspace_member_list | Page<{user_id,name,role}> |
| inbox_list | Page<InboxNotification={conversation_id,source,preview}>; đã chốt |
| inbox_read | Page<InboxMessage={message_id,source,content,created_at,in_reply_to?,scheduled_at?}>; đã chốt, mark chỉ returned items |
| box_create | {box_id,state,home,representative_agent_id,letis:{id,name}[]} |
| box_list | Page<{id,name,description,state,agent_count,pending_request_count,schedule_count}> |
| box_get | Graph/agent summaries/counts; prompts chỉ include_prompts, không full nested requests/schedules/runs |
| box_delete | {box_id,state} |
| hitl_ask | {request_id,status,expires_at}; expiry chỉ phản ánh system policy |
| hitl_request | Pending/canonical request hoặc {status:already_granted} |
| hitl_list | Page<{id,type,title,status,requester_agent_id,recipient_user_id,expires_at?,outcome_status?}> |
| hitl_get | Canonical request/form/decision/outcome theo [schema](schema.md#11-hitl_requests); IDs do system cấp |
| hitl_cancel | {request_id,status} |
| schedule_create | {schedule_id,paused}; không echo instruction/spec |
| schedule_list | Page<{id,title,type,target_agent_id,paused}> |
| schedule_get | Identity/content/paused + flat timing intent như input, tối đa 10 upcoming times/forecast_status; không type/spec/compiled range objects |
| schedule_update | {schedule_id,paused} |
| schedule_delete | {schedule_id,deleted:true} |
| history_search | Page<{id,seq,kind,created_at,preview}> |
| history_read | {entry:{id,seq,kind,created_at},content,start_line,total_lines,truncated,next_start_line} |
| file_list | {items:{path,kind,size_bytes?,write?}[],next_cursor,truncated}; không file.version |
| file_read | Text window/path/position/truncation; image native preview; blob processing/artifact references; không file.version |
| file_write | {path}; native version chỉ nội bộ |
| file_edit | {path}; không echo old/new content hoặc version |
| exec_shell | {exit_code,stdout,stderr,truncated}, native timeout indicator khi có |
| exec_python | Cùng native execution-result shape |
| file_semantic_search | {results:{path,hits:{path,text}[]}[]}, bounded per-path results |

Route={id,type:user/box/agent,name}. Mutations không echo form/spec/prompts/content. Result delivery có stable IDs/canonical states; duplicate không reopen requests hoặc apply cũ. Underlying SQL/API có native fields không đồng nghĩa model cần nhìn hoặc gửi lại chúng.

## 4. Token counts đã đo lại

[tool-schemas.json](tool-schemas.json) là full proposed model-visible payload cho root/Leti, gồm tool/parameter descriptions từ [TypeScript draft](tool-contracts.ts); không là runtime registry loader. [tool-token-estimates.json](tool-token-estimates.json) có từng definition, exact synthetic examples và baseline đề xuất cũ để so sánh. Không lấy production data hoặc gọi paid model.

Method: compact UTF-8 JSON qua o200k_base/cl100k_base. Counts gồm function name/description/parameters/envelope; không system prompt, messages, provider framing/normalization hoặc images. Không output schema trong model binding. Đây là reference count, không provider-billed usage hoặc savings so với production. Khoảng giữa hai tokenizer không là confidence interval cho mọi provider.

Bảng từng tool dưới đây dùng o200k_base; JSON report giữ cả hai tokenizer. Descriptions trong catalog bao gồm method và field comments của bản TypeScript, không tính header/comments dành riêng cho người review hoặc syntax TypeScript như thể gửi nguyên file cho model.

| Tool | Schema root | Schema Leti | Input ví dụ | Result ví dụ |
|---|---:|---:|---:|---:|
| inbox_send | 100 | 100 | 36 | 28 |
| workspace_get | 48 | 48 | 1 | 145 |
| workspace_member_list | 50 | 50 | 1 | 114 |
| inbox_list | 70 | — | 1 | 222 |
| inbox_read | 82 | — | 27 | 329 |
| box_create | 218 | — | 54 | 157 |
| box_list | 44 | — | 1 | 181 |
| box_get | 79 | — | 27 | 244 |
| box_delete | 66 | — | 28 | 33 |
| hitl_ask | 172 | 172 | 60 | 38 |
| hitl_request | 111 | 111 | 62 | 38 |
| hitl_list | 89 | 74 | 5 | 295 |
| hitl_get | 60 | 60 | 29 | 198 |
| hitl_cancel | 70 | 70 | 29 | 34 |
| schedule_create | 297 | 273 | 19 | 33 |
| schedule_list | 63 | 42 | 1 | 211 |
| schedule_get | 56 | 56 | 29 | 154 |
| schedule_update | 286 | 286 | 33 | 33 |
| schedule_delete | 57 | 57 | 29 | 33 |
| history_search | 62 | 62 | 7 | 183 |
| history_read | 74 | 74 | 29 | 106 |
| file_list | 96 | 96 | 1 | 69 |
| file_read | 77 | 77 | 7 | 61 |
| file_write | 81 | 81 | 37 | 7 |
| file_edit | 101 | 101 | 19 | 7 |
| exec_shell | 71 | 71 | 10 | 21 |
| exec_python | 61 | 61 | 15 | 18 |
| file_semantic_search | 93 | 93 | 13 | 127 |

| Catalog | Bản descriptions dài o200k | Hiện tại o200k | Bản descriptions dài cl100k | Hiện tại cl100k |
|---|---:|---:|---:|---:|
| Root, 28 | 5086 | 2708 | 5063 | 2661 |
| Leti, 22 | 3991 | 2095 | 3975 | 2064 |

Input/result examples: lists có 3 rows, text có paragraph 23 từ, box có hai prompts rất ngắn. Counts là JSON examples, không averages hoặc worst-case. Whole-catalog count có separators nên không bằng cộng item counts tuyệt đối. Native LangChain/Pydantic export và provider strict mode có thể đổi wire representation; cần đo actual usage khi bind model thật.

Đã loại bản descriptions dài theo phản hồi người dùng: bỏ luật đã có trong system prompt, comments lặp tên/type/default và lời khuyên chung ở từng tool. Mỗi tool giữ mô tả chọn/dùng cần thiết; chỉ tham số dễ hiểu sai mới có description riêng. Theo cl100k_base, schema không descriptions là 1.968/1.529 tokens; mô tả bổ sung còn 693/535 tokens thay vì 3.095/2.446. Không đổi tools, parameter shapes, numeric bounds/defaults hoặc capability. `before_description_compaction` giữ mốc bản dài; các mốc trước đó trong report là lịch sử.

Schema gửi ở mỗi model request có tools; không append một bản schema vào saved history mỗi tool call. Arguments là generated output; results là input và có thể được tính nhiều lần khi còn trong working context. Business rules chung có một chỗ trong system prompt, tool descriptions chỉ giữ điều cần để chọn và gọi đúng tool. Giữ catalog/order ổn định, small list previews/ACKs và provider-native caching khi usage xác nhận support. System prompt tính riêng: common + role giữ 3.141/2.960 tokens theo cl100k_base; cộng catalog hiện tại thành 5.802/5.024, chưa gồm configured prompt, clock/role context, summary/tail, provider framing hoặc images.

## 5. Verification và giới hạn

Draft descriptions đã rút gọn 2026-11-13: TypeScript 5.9.3 strict/noEmit pass; compiler kiểm 28 root/22 Leti và property names/required fields. Giữ 31 parameter description occurrences qua hai catalogs; tham số rõ nghĩa không cần description. JSON khớp JSDoc, không đổi parameter shapes, numeric bounds/defaults, outputs hoặc backend contracts. Đo lại schema/examples và system prompt riêng; không thêm compiler/dependency vào app hoặc giữ generator/test harness trong project. Bản 149 parameter descriptions trước đó đã bị thay thế.

Đã rà inputs/outputs cả 28 tools, các owning docs và current native behavior đã kiểm: LetFS atomic literal edit/version condition và Platform human-only ListMembers/BatchGetUsers. JSON Schema/format checks và token counts/examples được kiểm lại, không port archive code/tests.

Implementation cần focused checks cho system-owned args không expose, runtime deadline/page budget, normalized forms sinh IDs, flat timing mapping/relative-time retry, role/scope và atomic edit conflict. Không per-wrapper test matrix hoặc kiểm lại native Temporal calendar engine. Đã thử introspect temporalio trong interpreter hiện tại nhưng package không có; không install hoặc bypass môi trường. Runtime/native smoke chưa chạy.

Giới hạn: full overwrite là explicit replace, không auto-merge; result examples không phải hard token caps; provider billing/image usage chưa đo. Không thay SQL/Zed/proto/config/dependencies, không background process hoặc app implementation trong lượt này.
