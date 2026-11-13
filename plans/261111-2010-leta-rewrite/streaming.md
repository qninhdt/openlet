# Leta API, streaming và replay đã chốt

Ngày 2026-11-12. Người dùng đã chốt sau khi đối chiếu archive và source LangGraph API/Agno. Đây là contract cho rewrite, chưa implementation. Giữ 11 application tables; Temporal hiện 6 workflows/22 activities/3 queues sau workspace cleanup, streaming không thêm activities. Generative UI ngoài phạm vi.

## 1. Transport và execution

Leta phục vụ HTTP JSON và SSE trực tiếp sau Envoy. Platform/LetFS vẫn native gRPC + Envoy JSON; Leta dùng generated native gRPC clients để gọi hai service đó. Không thêm application gRPC listener hoặc dual server cho Leta chỉ để phục vụ public API.

Một SSE connection theo root Leta multiplex root và children. Subscription không sở hữu execution: đóng tab, mất mạng, slow-client timeout hoặc reconnect không cancel agent. Message mới có thể vào logical run đang chạy; không tạo run theo connection hoặc mỗi input. Technical retry/Continue-As-New giữ logical run, không phát RUN_ERROR/cancel chỉ vì worker attempt đổi.

Base path: `/v1/workspaces/{workspace_id}/letas/{leta_id}`.

| Method/path tương đối | Contract chính |
|---|---|
| POST /messages | Human gửi input tới root bằng stable message ID; ACK sau durable inbox admission |
| GET /messages | Một trang chat deliveries thực tế, không tự chuyển assistant activity thành chat |
| GET /events | SSE root/children, Last-Event-ID cho reconnect có retained client state |
| GET /agents/{agent_id}/history | Public committed history, keyset theo seq và giới hạn entries/bytes |
| GET /agents/{agent_id}/history/{entry_id} | Body đầy đủ của một authorized entry |
| GET /agents/{agent_id}/runs/{run_id} | Canonical logical run status |
| PATCH /agents/{agent_id} | Model/effort/config; áp dụng ở safe boundary tiếp theo |
| POST /pause; POST /resume | Durable desired pause của Leta, không cắt ngang model/tool call |
| POST /agents/{agent_id}/runs/{run_id}/cancel | Cancel logical run cụ thể, khác đóng SSE |

Các feature APIs còn lại dùng HTTP cùng owning functions/tools. Operator access và workspace cleanup đã chốt, transfer hoãn; complete DTO/errors/pagination cần cụ thể hóa trước code API từng feature. Retention MVP không auto-purge durable inbox/public history/archived records đã duyệt; native checkpoint pruning và Redis stream trimming giữ policy riêng, future purge/expiry hoãn. Không tự thêm callback binding/list/stop hoặc public internal routes.

## 2. State ownership và thời điểm ghi SQL

| Nơi giữ | Nội dung |
|---|---|
| RAM runtime | Native LangChain/LangGraph ghép response đang sinh và giữ bounded working context |
| Native LangGraph saver | Working messages/summary/inbox cursor/continuation phục vụ recovery |
| PostgreSQL history | Public committed text/tool calls/results, độc lập checkpoint pruning |
| PostgreSQL messages/runs | Durable deliveries và logical run status |
| Redis Stream | Recent public events để live/reconnect, không canonical context hoặc whole-run history |

Không UPDATE PostgreSQL assistant text theo mỗi provider token/chunk. Trước model call, middleware lấy bounded inbox batch/config tại safe boundary. Model/tool steps hoàn tất thì lưu public projection và native checkpoint theo runtime contract; tools có thể gọi SQL/owning service cho chính operation của chúng. Run state chỉ ghi khi chuyển trạng thái; compaction/checkpoint/prune theo boundary riêng.

RAM accumulation là hành vi native của model/graph, không RAM cache tự xây. Không đọc ngược Redis để dựng response hoặc checkpoint. Redis có thể trim/hết hạn mà agent vẫn phục hồi từ native saver. UI refetch, inbox admission hoặc actors khác vẫn có thể gọi SQL trong lúc model đang stream; không đánh đồng với ghi từng chunk. Heartbeat gửi Temporal, không mỗi nhịp ghi application PostgreSQL.

## 3. AG-UI và public projection

SSE data chứa trực tiếp một AG-UI JSON event, không outer Envelope. Root scope lấy từ URL; metadata.openlet chỉ mang agentId và runId khi applicable. Chuẩn hóa messageId/toolCallId có scope ổn định và khớp canonical entry identity, không identity-registry table.

Giữ RUN_STARTED/RUN_FINISHED/RUN_ERROR, TEXT_MESSAGE_START/CONTENT/END, TOOL_CALL_START/ARGS/END/RESULT. Run terminal chỉ theo domain outcome; paused chưa đóng logical run. Stream/Redis lỗi không giả thành model failure. HITL vẫn async resource + inbox result, không đổi thành interrupt dừng cả agent.

| CUSTOM name | Mục đích |
|---|---|
| openlet.snapshot | Bounded canonical bootstrap, previews/references và page cursors |
| openlet.history | Canonical entry upsert hoặc reference, cùng stable identity |
| openlet.resource_changed | Resource type/ID để invalidate owning query |
| openlet.resync_required | Coverage không còn đủ; client bootstrap lại |

Đây là Leta subscription dùng AG-UI event schema, không tuyên bố end-to-end AG-UI HTTP binding. Binding chuẩn POST RunAgentInput không có Last-Event-ID resumption; root feed có bootstrap, suffix và nhiều independent runs. Một client adapter cụ thể đọc SSE/cursor, demultiplex agent/run và áp dụng snapshot/upsert. Không cắm raw feed vào stock HttpAgent hoặc ép Leti thành subagent có lifecycle giả để khớp protocol.

Public normalization chỉ expose authorized public text/args/results/file references; không raw provider payload, hidden reasoning, image base64 hoặc credentials. Shared root stream không bypass exact-recipient HITL rights. Người nhận HITL không cần agent.read để dùng incoming-card/answer APIs của mình.

### Tool result và body lớn

LLM sinh text/tool arguments có thể thành delta events. Tool thực thi trả một result hoàn chỉnh; result 1.000 tokens không tự bị băm thành 1.000 token events.

Public TOOL_CALL_RESULT chứa bounded preview và reference tới history entry; body đầy đủ đọc từ GET entry khi mở chi tiết. Preview/truncation được thể hiện rõ, không báo preview là full result. Canonical public result vẫn ở history; model nhận own tool result trong tool/context budgets, không nhận preview của UI thay cho dữ liệu đó.

Không gửi full result một lần qua TOOL_CALL_RESULT rồi lặp full body qua openlet.history. Canonical notification dùng cùng identity và preview/reference; preview được dựng từ public projection, không gọi thêm model để tóm tắt từng result. Large bodies không tự hydrate khi nhận notification hoặc render một list row.

## 4. Người mới mở agent đã chạy nhiều tháng

Fresh connection luôn bootstrap hiện tại, kể cả logical run chưa kết thúc:

1. Chụp Redis tail B trước SQL snapshot.
2. Đọc current agent/control/run state và một trang recent public history previews/references. Entries và tổng bytes đều có budget; roster/chat/box lists cũng phân trang theo view.
3. Gửi openlet.snapshot, thiết lập baseline cursor B.
4. XREAD suffix sau B rồi tiếp tục cùng read iterator để nhận live events.

Agent chạy 90 ngày/50.000 tools không làm browser tải 50.000 results, toàn Redis log, toàn logical run hoặc LangGraph checkpoints. Ví dụ một trang 20 entries là cửa sổ UI hữu hạn, không cam kết mọi entry body vừa trong cùng byte budget. Cuộn lên lấy trang cũ hơn; mở result lấy một entry đầy đủ; mở chat lấy một trang deliveries riêng. Không hydrate mọi child history khi mở root.

Thay đổi commit trong lúc snapshot có thể xuất hiện cả SQL và suffix. Client upsert theo stable entry/message ID, canonical entry thay provisional entry; bỏ late provisional deltas cho entry đã canonical. Không dựng global SQL sequence hoặc phụ thuộc run đã terminal mới phân trang được.

Không scan retained Redis prefix để tái dựng người mới như FreshReplay. Nếu vào giữa một response, prefix chưa commit có thể không có. Adapter không đưa orphan CONTENT/END vào AG-UI reducer hoặc render text mất đầu: hiển thị agent đang trả lời, chờ committed entry đầy đủ. Message bắt đầu sau subscription vẫn stream bình thường; tool call đã commit có thể hiển thị từ canonical history.

Browser chỉ giữ bounded activity window/query pages và render theo batch; không append DOM/RAM vô hạn theo tuổi đời agent. Working context/checkpoints không đi xuống browser.

## 5. Reconnect, replay và retention

Last-Event-ID chỉ gửi khi client còn state tương ứng. Full reload chỉ giữ cursor mà mất partial state phải bootstrap mới.

| Trạng thái | Hành vi |
|---|---|
| Fresh/no retained state | SQL bootstrap, suffix sau B |
| Retained state + covered cursor | XREAD đúng suffix sau cursor rồi live, giữ partial state |
| Cursor bị trim/log mất hoặc coverage mất trong lúc đọc | openlet.resync_required; đóng subscription; client bỏ provisional state và mở fresh connection |

Malformed cursor là input error. Redis outage không giả thành empty history hoặc completed run; subscription lỗi/đóng và reconnect. Kiểm coverage khi bắt đầu và trong read path, không chỉ lúc connect. Native Redis IDs là public cursor; không event_index riêng, full XRANGE scan rồi Python filter hoặc Pub/Sub replay/live handoff.

Một stream theo root, native XADD/MAXLEN/idle expiry. Không stream per run, custom byte-accounting Lua, run-status/generation mirrors hoặc TTL refresher chỉ để giữ replay qua tool im lặng. Retention là lượng log còn dùng được, không hứa một khoảng thời gian replay cố định dưới mọi tốc độ root/children. Native caps và event payload budgets được cấu hình khi implementation, chưa có số đo để gọi 1.000/10.000 entries là tối ưu.

Reconnect có thể phải đọc nhiều records bị lỡ nếu còn coverage; không hứa suffix luôn nhỏ. Fresh/history reads dùng SQL nên không cần replay tokens của cả run. Khi log mất, canonical data vẫn đọc được mà không gọi lại model.

## 6. Batch folding khi đọc, không timed coalescer

Producer append public provider chunks; không thêm timer/queue merge 25/50 ms. Trong batch XREAD đã có, API chỉ nối delta liền nhau nếu cùng agent/run, messageId hoặc toolCallId, type và mọi non-delta metadata. Chỉ TEXT_MESSAGE_CONTENT/TOOL_CALL_ARGS tương thích; không đổi thứ tự, gộp qua START/END/custom/resource/agent khác hoặc vượt frame payload budget.

Merged SSE frame dùng ID cuối cùng đã tiêu thụ. Client chỉ lưu cursor sau khi áp dụng frame, bỏ duplicate IDs khi reconnect. Không còn per-connection merge timer hoặc chờ đủ cửa sổ trước khi gửi batch.

Folding giảm outgoing frames/client processing khi catchup; không giảm số XADD hoặc số missing records phải đọc. Provider chunk có thể chứa nhiều tokens, không đồng nhất một token với một event. Không dùng compactEvents reorder toàn log hoặc server UI reducer. Render batching nằm ở client.

## 7. Canonical refresh và publication failure

SQL mutation/history commit trước thông báo Redis. Publication failure không rerun durable effect. Không retry mù provisional delta sau ambiguous XADD ACK; dừng delta publication của message bị lỗi và phục hồi UI từ canonical state. Không vô hiệu publication theo toàn tuổi đời long activity hoặc agent; canonical notifications và các message tiếp theo vẫn có thể publish khi Redis phục hồi. Không thêm SQL event outbox/publisher worker chỉ để giữ mọi provisional token.

Client refetch canonical queries đang hiển thị khi mount/reconnect/tab focus, khi nhận notification và khoảng 30 giây khi tab visible. Đây là initial operational policy chưa benchmark. History fetch chỉ committed suffix theo agent seq; statuses/lists theo view và page budgets, không tải lại toàn transcript hoặc scan tất cả agents. Cách này sửa SQL-commit/Redis-notification gap kể cả subscriber không trực tiếp gặp Redis error.

Refetch không reset partial state còn hợp lệ; canonical upsert thay phần đã commit. Nó không gửi Temporal Update, không thêm inbox polling từng token hoặc tạo workflow history theo UI refresh. Chấp nhận live notifications có thể chậm/mất tạm; không tuyên bố distributed atomicity/exactly-once cho SQL + Redis.

## 8. Authorization, scope và verification

Envoy validate JWT/strip actor headers; Leta kiểm current root/agent rights và scope child từ owning root. SSE authorize trước response và định kỳ cả lúc idle. Mất quyền thì đóng. Bounded send timeout đóng slow subscriber, không chặn model hoặc tạo unbounded queues. Snapshot/detail APIs cũng authorize; notification không cấp quyền đọc body.

Chỉ inbox_send tạo human delivery; assistant activity không tự xuất hiện thành addressed chat bubble. Core workspace deletion/RemoveMember và ownership/grants giữ [boundary](boundaries.md); không stop-ACK/readiness dependency mới.

Implementation dùng events.py cho normalization/Redis/SSE và một client adapter. Các feature modules giữ SQL/routes/functions như [folder structure](design.md#12-cấu-trúc-thư-mục-hoàn-chỉnh); không event-bus interface, replay framework, backend abstraction hoặc backward compatibility layer.

Focused checks dùng chung dependency environment: fresh bootstrap giữa concurrent commits không duplicate/mất canonical data; suffix/live handoff và trim resync; preview/detail không hydrate full history; publication failure + canonical refresh không rerun effect; unauthorized/slow subscriber không ảnh hưởng agent. Không port archive suites hoặc test every transport/failure permutation.

Đã đọc archive streaming/http/events/runtime events và [source review](../reports/research-261112-1855-streaming-replay-langgraph-agno.md). AG-UI [metadata](https://docs.ag-ui.com/concepts/metadata) và [HTTP binding](https://docs.ag-ui.com/spec/1.0/basic/transports/http-sse) được đối chiếu. Chưa implementation/provider/Redis/DB/Envoy integration hoặc benchmark; không thay SQL DDL, runtime, core contracts/config hoặc dữ liệu trong lượt chốt plan.
