# Schema Leta đã chốt lại

Cập nhật 2026-11-12 theo thiết kế 11 bảng và constraint đã được người dùng chấp thuận. Thay thế bản 9 bảng/81 cột: tách root resource khỏi executable fields, tách agent/user delivery, đổi source human thành hitl, đưa HITL/schedule discriminator ra columns và dùng receipt schema chung của core.

[DDL review](schema.sql), [kiến trúc](design.md), [Temporal](temporal.md), [rà soát boundary](boundaries.md). Artifact cho database mới, chưa migration/implementation; không thay database, runtime/tests hoặc chạy Zed.

## 1. Phạm vi và authority

| Bảng | Trách nhiệm |
|---|---|
| letas | Workspace/storage binding, root lifecycle và desired pause |
| agents | Executable identity/profile/config, inbox/history counters cho root và Leti |
| boxes | Immutable graph container/representative, home locator và lifecycle |
| box_edges | Allowed undirected communication pairs |
| agent_messages | Delivery tới agent, sequence/provenance/read state |
| user_messages | Explicit root-to-user delivery |
| runs | Logical execution status/cancel/correlation |
| history | Committed public transcript, độc lập recovery |
| hitl_requests | Ask/approval, addressed human, response và external outcome |
| schedules | Product definition/desired control; native Temporal giữ timing/execution |
| idempotency_keys | Response receipts theo owning method contract |

SpiceDB canonical owner/operator/membership và resource workspace binding. Leta ghi/dọn agent.workspace và workspace.agent trong cùng native graph batch với agent owner/operators; Platform workspace/membership và generic active check; LetFS storage/grants. Đổi registered_agent thành agent và xóa hai Platform registration RPC theo quyết định 2026-11-12. Agent độc lập membership human owner; RemoveMember chỉ thu hồi human membership, không owned_agent hoặc registration state mới. Box/Leti IO dùng root subject, không workspace.agent riêng. Không đổi 11 bảng/DDL vì quyết định graph này; không SQL ownership/grant mirror, principal registry, personal-storage mapping hoặc quota/visibility cache. Native LangGraph saver sở hữu checkpoint schema/migrations riêng; không application checkpoint/tool replay/pending-command/occurrence/jobs/outbox tables.

## 2. Quy ước

- UUID stable identity; mutation không resolve lại tên sau retry. Timestamps timestamptz, UTC ở boundary; counters bigint.
- Audit ghi NULL khi nullable; default chính xác ở DDL. Không mặc định mọi bảng có updated_at/deleted_at/version/status.
- Root resource ID cũng là root executable agent ID; create ghi letas + agents cùng transaction. Root phải có model, child phải có box; validate tại owning operation, không subtype registry/trigger.
- PK/FK/UNIQUE/CHECK bảo vệ invariant thật vẫn giữ; không quota giảm constraint. Composite FK đúng root/box/run đáng giữ cùng supporting UNIQUE.
- JSON/form/catalog/ScheduleSpec validate tại owning boundary bằng Pydantic/native types. SQL giữ scalar discriminator, lifecycle consistency và relational integrity; không viết lại toàn bộ JSON schema.
- Không cross-database FK. Local archive giữ transcript, không cascade lịch sử theo user delete. External cleanup theo owning API, không suy ownership từ binding.

## 3. letas

| Field | Type / NULL | Vì sao giữ |
|---|---|---|
| id | uuid PK | Resource/root agent/SpiceDB subject identity |
| workspace_id | uuid | Actual tenant, authorization parent và core RPC context |
| storage_id | uuid | Một storage binding; ordinary UUID giữ nguyên qua provisioning retry |
| state | text | provisioning/active/deleting/archived cho setup, admission, retained history |
| paused | boolean, default false | Desired control sống qua rollover/restart, không copy xuống child |

Index workspace/id phục vụ list rồi bulk-filter quyền. Không UNIQUE storage_id hoặc owner fields; profile/creation time lấy root agents row. Binding không chứng minh exclusive ownership hoặc cho phép cascade storage delete.

## 4. agents

| Field | Type / NULL | Vì sao giữ |
|---|---|---|
| id | uuid PK | Inbox/runtime/thread/history target |
| leta_id | uuid FK letas | Root scope, listing và same-root box FK |
| box_id | uuid NULL | Immutable Leti membership; root NULL |
| name | text | Roster/UI label, mutations dùng ID |
| description | text, default empty | Capability description, khác full prompt |
| system_prompt | text | Behavior configuration |
| model_id | text NULL | Root chọn model; child NULL kế thừa |
| reasoning_effort | text NULL | Override độc lập; root NULL dùng catalog default |
| inbox_seq | bigint, default 0 | Cấp committed recipient order cùng INSERT |
| history_seq | bigint, default 0 | Cấp committed public append order |
| created_at | timestamptz | Resource metadata, không đổi theo activity attempt |

UNIQUE box/name; UNIQUE leta/id và box/id hỗ trợ composite FK. FK (leta_id,box_id) bảo đảm child đúng root. Không root-only bindings/state/pause, resolved model hoặc execution cursor.

## 5. boxes

| Field | Type / NULL | Vì sao giữ |
|---|---|---|
| id | uuid PK | Stable create/delete identity dù tên dùng lại |
| leta_id | uuid FK letas | Root list/lifecycle, same-root membership |
| name | text | Roster label, unique khi chưa archived |
| description | text, default empty | Nhiệm vụ toàn box |
| representative_agent_id | uuid | Immutable endpoint giao tiếp root |
| home_node_id | uuid UNIQUE | Stable directory locator/mount/trash target |
| state | text | active/deleting/archived độc lập root; pending create ở Temporal |
| created_at | timestamptz | Resource metadata |

Composite representative FK tới agents(box_id,id) deferred đến commit. Insert box trước children; child-to-box FK không cần deferred. Không child state/provision step/graph count/version mirrors.

**Home-first đã chốt:** provision_box gọi native LetFS CreateDirectories với stable .boxes/<box_id> path trước; prepare_box dùng home_node_id thật để ghi active box + children + edges + finalized receipt atomically. Giữ home_node_id NOT NULL, không preallocated directory ID hoặc sửa core proto. Pending create thuộc Temporal, không boxes.provisioning row. [Box/Leti](boxes.md#4-home-first-provisioning) và [boundary](boundaries.md#81-box-directory-id--home-first-đã-chốt) sở hữu ordering.

## 6. box_edges

| Field | Type / NULL | Vì sao giữ |
|---|---|---|
| box_id | uuid FK boxes | Owner graph, prefix load graph |
| agent_low_id | uuid | Endpoint UUID nhỏ hơn |
| agent_high_id | uuid | Endpoint UUID lớn hơn |

PK ba fields, CHECK low < high, hai same-box endpoint FKs. Không edge ID/reverse row/direction/enabled/timestamps. Graph immutable, không adjacency cache.

## 7. agent_messages

| Field | Type / NULL | Vì sao giữ |
|---|---|---|
| id | uuid PK | Stable delivery identity/dedupe |
| recipient_agent_id | uuid FK agents | Inbox target; root scope lấy qua agent |
| seq | bigint | Committed positive recipient order |
| source_kind | text | user/agent/box/hitl/schedule discriminator |
| source_id | uuid | User/sender agent/box/HITL request/schedule identity |
| conversation_id | uuid | Giữ cuộc trao đổi qua reply/source |
| in_reply_to_message_id | uuid NULL | Exact causal reply, khác grouping |
| scheduled_at | timestamptz NULL | Native nominal occurrence time, chỉ schedule |
| content | text | Bounded immutable delivery body |
| created_at | timestamptz | Actual delivery time |
| read_at | timestamptz NULL | Đã đọc chi tiết/notification, không processed cursor |

Mọi row có agent recipient + seq, không XOR. Sender nguồn agent là source_id; nguồn box suy từ representative bất biến, không sender_agent_id thứ hai. Không copy root ID/current source labels; hydrate theo batch, labels không authorize.

Nguồn user là direct chat; hitl là request result. Result body render canonical response/outcome, structured request đọc theo source_id; không generic data bag.

Admission khóa root → box phù hợp → recipient counter trong transaction ngắn, kiểm stable ID trước counter, cấp seq + INSERT cùng commit. Duplicate đúng scope/intent trả row cũ; input mới qua current route/source/liveness. Runtime đọc seq > checkpoint cursor, không filter read_at; cursor checkpoint cùng batch.

UNIQUE recipient/seq, conversation index, partial unread index và partial recipient/time/id cho user inputs trong human-chat UNION; CHECK scheduled_at iff schedule source. Chat input index tránh sort toàn bộ inbox khi agent sống lâu. Polymorphic source và reply xuyên delivery tables kiểm đúng root/conversation tại owning operation; không fake FK/registry. Authorized parent scope phải kiểm trước duplicate/global ID lookup.

## 8. user_messages

| Field | Type / NULL | Vì sao giữ |
|---|---|---|
| id | uuid PK | Stable explicit human delivery identity |
| leta_id | uuid FK letas | Root sender và authorization scope |
| recipient_user_id | uuid | Addressed human event identity, không owner snapshot |
| conversation_id | uuid | Human conversation với input inbox |
| in_reply_to_message_id | uuid NULL | Exact reply có thể trỏ sang agent_messages |
| content | text | Immutable nội dung root thực sự gửi |
| created_at | timestamptz | Human-chat keyset/order |

Sender luôn root, Leti không human chat. Index leta/time/id; không inbox seq/read cursor/sender/type/direction. Không auto-forward final output. Chat query UNION ALL root user inputs với user_messages, keyset created_at/id; một delivery một body. Transfer không retarget old delivery; access vẫn kiểm current rights theo API contract được chốt sau.

## 9. runs

| Field | Type / NULL | Vì sao giữ |
|---|---|---|
| id | uuid PK | Logical run/cancel identity, khác Temporal Run ID |
| agent_id | uuid FK agents | Owner và unfinished-run scope |
| status | text | running/paused/completed/failed/cancelled cho UI |
| started_at | timestamptz | Logical start, không technical attempt |
| finished_at | timestamptz NULL | Terminal time, không activity-attempt/CAN time |
| error_code | text NULL | Terminal machine-readable failure; details ở logs |

Partial UNIQUE một running/paused run/agent; terminal iff finished_at, failed iff error_code. UNIQUE agent/id hỗ trợ history FK; timeline agent/time/id. Không run rỗng, checkpoint/cursor/attempt/continuation/result mirror.

## 10. history

| Field | Type / NULL | Vì sao giữ |
|---|---|---|
| id | uuid PK | Stable append/client upsert identity |
| agent_id | uuid FK agents | Timeline/order/authorization scope |
| run_id | uuid | Logical run, same-agent composite FK |
| seq | bigint | Committed public order |
| kind | text | Public rendering discriminator |
| payload | jsonb | Public text/tool association/args/results/file references |
| created_at | timestamptz | Event timestamp; seq là append order |

```text
inbox_input  {"message_ids":["<uuid>"]}
assistant    {"text":"Nội dung public"}
tool_call    {"tool_call_id":"<id>","name":"<tool>","args":{}}
tool_result  {"tool_call_id":"<id>","result":<public JSON value>}
final_note   {"text":"Kết quả public"}
compaction   {"text":"Ghi chú compaction public"}
```

Input bodies hydrate từ immutable messages. Không kind lặp trong JSON/raw provider/hidden reasoning/base64. Append stable-ID lookup + history_seq increment + INSERT cùng transaction. UNIQUE agent/seq, agent/run/seq và expression GIN native full-text. Prune/compaction không xóa transcript; không replay ledger/search_text copy.

## 11. hitl_requests

| Field | Type / NULL | Vì sao giữ |
|---|---|---|
| id | uuid PK | Request/workflow identity, namespace result message |
| requester_agent_id | uuid FK agents | Exact result recipient/root scope |
| recipient_user_id | uuid | Addressed human, incoming list/exact response recipient |
| type | text | ask/approval, ngoài JSON |
| title | text | Nhãn thẻ UI/notification |
| payload | jsonb | Immutable form hoặc storage/role/reason |
| status | text, default pending | Authority pending/answered/accepted/denied/cancelled/expired |
| response | jsonb NULL | Actor/answers/cancel reason, không lặp status/action |
| outcome | jsonb NULL | Actual accepted-approval effect, khác human decision |
| expires_at | timestamptz NULL | Absolute UI/native timer deadline; NULL không deadline |
| created_at | timestamptz | Incoming/requester timeline |
| resolved_at | timestamptz NULL | Terminal decision time, khác grant completion |

```text
type=ask payload: {"questions":[{"id":"q1","type":"text","text":"..."}]}
type=approval payload: {"storage_id":"<uuid>","role":"viewer","reason":"..."}
status=answered response: {"actor":"user:<uuid>","answers":{"q1":{"text":""}}}
status=accepted/denied response: {"actor":"user:<uuid>"}
status=cancelled response: {"actor":"agent:<uuid>","reason":"..."}
status=expired response: NULL
outcome: {"status":"granted"}
outcome: {"status":"skipped","reason":"permission_revoked"}
```

Questions text/single_choice/multiple_choice; choice options id/label. Answers text / nullable option_id + note / option_ids + note; empty answers hợp lệ. Cancel actor có thể authorized human/agent. Không question/options tables hoặc required/default/answered flags.

Đây là canonical stored payload, không agent tool schema. Model gửi text/options labels/multiple; system cấp IDs và suy type. expires_at là trusted product policy, không timeout argument của model. Xem [tool ownership audit](tools.md#hitl); không đổi SQL fields/constraints.

CHECK pending iff resolved_at NULL; outcome chỉ accepted approval. CAS WHERE status='pending' chọn một winner answer/expiry/cancel. Accepted + outcome NULL là pending effect; rights chưa được suy là granted. Native workflow clock quyết định expiry.

Recipient là event fact, không permanent authority. Ask nhận explicit recipient_user_id là bất kỳ human owner/member hiện tại cùng workspace; open/read/answer kiểm current workspace.participate và exact recipient, không agent.use hoặc agent owner. Approval chỉ rõ storage_id/recipient_user_id rồi kiểm current accepting-human storage.manage_access, target root suy qua requester. Lost rights/resource → skipped; transient → retry. Outcome granted dẫn tới native dynamic mount refresh tại safe boundary, không đổi home storage_id hoặc giữ mount registry. Index recipient/time/id và requester/time/id. Không root/grantee/result-message/grant-key/phase/attempt/delivery_sent mirrors. [HITL detail](hitl.md) mô tả form, quyền và workflow; schema/DDL không đổi.

## 12. schedules

| Field | Type / NULL | Vì sao giữ |
|---|---|---|
| id | uuid PK | Definition/native schedule/coordinator identity |
| creator_agent_id | uuid FK agents | Immutable actual creator, local control/root scope |
| target_agent_id | uuid FK agents | Exact recipient, có thể khác creator |
| title | text | Calendar/list label |
| content | text | Occurrence instruction |
| type | text | at/interval/calendar ngoài JSON |
| spec | jsonb | Timing parameters, không discriminator/native compiled mirror |
| paused | boolean, default false | Desired source pause, khác root execution pause |
| deleted_at | timestamptz NULL | Tombstone/closure time, chặn late delivery/recreate |
| created_at | timestamptz | Resource metadata |

```text
type=at       {"at":"2026-11-13T02:00:00Z"}
type=interval {"every_seconds":3600,"anchor_at":"2026-11-12T00:00:00Z"}
type=calendar {"timezone":"Asia/Ho_Chi_Minh","calendar":{"hour":[{"start":9}],"minute":[{"start":0}]}}
```

Native ScheduleCalendarSpec/ScheduleRange; interval/calendar optional end_at UTC. Relative after_seconds normalize một lần bằng accepted workflow time. Không JSON type key/CHECK validator, end_at column thứ hai, cron engine hoặc occurrence table.

Model tool chọn flat timing intent và calendar values; system dựng type/spec/ranges/defaults theo [tool audit](tools.md#scheduler). Các canonical examples trên không bị bind nguyên dạng làm input của model; DDL không đổi.

Thiết kế execution/commands/preview và so sánh với archive tại [scheduler](scheduler.md). Type/spec edit thay timing của cùng schedule, không đổi creator/target; native exact-calendar one-shot không cần action counter trong SQL hoặc native limited-actions state.

Creator/target immutable, same-root/allowed routing kiểm tại create; Leti schedule chính nó, root schedule root/representative. Target box suy agents.box_id. Index creator/id và target/id gồm tombstones cho cleanup. Metadata-only edit không rearm; nominal time + schedule ID dedupe delivery. Không copied root/native IDs/next-last tick/counters/version/progress.

## 13. idempotency_keys

| Field | Type / NULL | Vì sao giữ |
|---|---|---|
| caller | text, PK part | Canonical user:<id>/agent:<id>, không workload credential |
| method | text, PK part | Owning operation namespace |
| key | uuid, PK part | Stable request identity |
| request_hash | bytea | Cùng key khác input phải conflict |
| result | bytea NULL | Small serialized response; NULL chỉ trong transaction chưa commit |
| expires_at | timestamptz | Receipt retention/cleanup theo owning contract |

Đúng sáu fields/types/nullability/PK của migrations Platform/LetFS hiện tại; index expires_at. Transport HTTP JSON + SSE đã chốt tại [streaming](streaming.md); receipt result serialization theo complete DTO/error contract còn review, không tự thêm public envelope.

Pure-SQL mutation và finalized receipt commit cùng transaction. Create lifecycle có thể receipt admitted identity vì method ACK admission. Schedule method ACK applied outcome: canonical pending command ở native Temporal history; SQL definition → native ACK → finalized receipt trước khi nhả ordering. Không result pending-intent bag/completed_at hoặc SQL transaction qua RPC.

Old completed retry trả receipt, không apply definition cũ. Crash trước final receipt replay cùng canonical command; next command và CAN chờ handlers settle. Native SQL/effects phải idempotent; receipt không distributed transaction. Temporal input giữ normalized times dù Local Activity marker mất.

Chỉ mutation cần receipts mới dùng; message/HITL/history có stable IDs, file effects dùng LetFS receipt. Không receipt mọi read/tool/heartbeat. Durable agent receipts phải sống qua required retry horizon; native infinity được đề xuất khi resource retained, không bảng retention riêng. Core file receipt hữu hạn là integration limit, không tự suy thành dedupe nhiều năm; xem boundaries.md.

## 14. Constraints, query và verification

Giữ PK/FK/NOT NULL, same-root child/same-box representative/edges, live names/home uniqueness, positive committed sequences/counters, one unfinished run, same-agent history/run, scalar lifecycle/type/status, schedule timestamp và HITL outcome/decision consistency.

Reply xuyên hai delivery tables/polymorphic source, root create/inheritance, schedule creator-target rule và JSON union validate tại owning boundary. Không bỏ relational constraint để giảm số lượng; không thêm trigger/RLS framework/generated discriminator.

Queries kiểm authorized parent, batch hydrate/native graph bulk checks, keyset/bounded bodies. HITL/schedule root list join indexed agents thay copy root. No RPC/model/SpiceDB trong SQL transaction. Counter cùng INSERT, không MAX(seq)+1/global high-water. Current rights không suy từ event actors/owner cũ.

DDL là syntax/structural artifact. Native PostgreSQL concurrency/constraints/EXPLAIN và journeys rollover/restart thuộc implementation: atomic graph/cross-box rejection, concurrent inbox dedupe, same-agent history FK, HITL race/empty answers/current permissions, schedule retry sau CAN và transcript qua prune. Không port old suites/failure matrix.

Validation tĩnh lượt này: field audit khớp 11 bảng/86 cột; 15 FK đều có declared PK/UNIQUE đích. Receipt signature khớp fields/types/nullability/PK với cả hai active migrations Platform/LetFS. Doc links/fences/whitespace/line limits và inventory 6 workflows/21 activities/3 queues đã kiểm; đây không phải PostgreSQL execution hoặc integration proof.

Không apply DDL, sửa runtime/tests hoặc khởi động process. Database cũ nguyên vẹn; backup trước schema/data change thật. Home-first contract đã chốt và DDL design bỏ boxes.provisioning; chưa claim provisioning/schema chạy end-to-end.
