# Source review: LangGraph API và Agno streaming/replay

Ngày 2026-11-12. Theo yêu cầu tải source từ PyPI, đọc streaming/replay trước khi tiếp tục thiết kế Leta. Không dùng skill/subagent, không đổi plan đã duyệt hoặc runtime/dependencies/database. Generative UI ngoài phạm vi lượt này.

## 1. Artifacts và phạm vi chứng minh

Tải sdist bằng PyPI JSON API, đối chiếu SHA-256 artifact trước extract; không install hoặc chạy build hooks. Latest non-prerelease tại thời điểm tải:

| Package | Version | Vai trò |
|---|---|---|
| [langgraph-api](https://pypi.org/project/langgraph-api/0.17.1/) | 0.17.1 | HTTP/SSE, Protocol v2, normalization, publish/join clients |
| [langgraph-runtime-inmem](https://pypi.org/project/langgraph-runtime-inmem/0.37.1/) | 0.37.1 | Actual development in-memory stream backend; khớp dependency range API |
| [agno](https://pypi.org/project/agno/3.1.12/) | 3.1.12 | Native AgentOS streaming, RAM/Redis buffers, DB fallback, AG-UI interface |

Source/extraction root: `/tmp/openlet-streaming-source-review-261112/`. Mỗi package có JSON metadata cạnh artifact, ghi version, URL, hash và extraction directory. Các links `/tmp` bên dưới có thể mất khi dọn temporary files.

LangGraph production postgres backend ở phiên bản này đi qua Go core API bằng gRPC. Public PyPI `langgraph-runtime-postgres` lookup trả HTTP 404; source backend đó không nằm trong ba sdists đã đọc. Không kết luận actual Redis commands, retention enforcement hoặc batching bên trong Go chỉ từ Python client. Python config có default `RESUMABLE_STREAM_TTL_SECONDS=120` và export setting đó cho runtime; đây là source default, không là observed deployment retention.

## 2. LangGraph API: legacy run stream

### Publish

Graph stream phát `(mode,payload)`; `consume` serialize từng item rồi gọi `Runs.Stream.publish`. Default inline path đợi publish trước khi lấy event tiếp. Optional `FF_ASYNC_PUBLISH_QUEUE` dùng bounded queue, default capacity 512, để tách producer khỏi publisher; vẫn publish từng item, không nối text deltas thành một event.

`stream_resumable` mặc định false cho legacy run create. Khi true, chỉ modes nằm trong configured stream modes được đánh dấu resumable; metadata luôn nằm trong set. Không coi streaming tự động đồng nghĩa replay-enabled.

Sources:

- [consume/inline/async queue](/tmp/openlet-streaming-source-review-261112/langgraph-api-0.17.1/langgraph_api-0.17.1/langgraph_api/stream.py:693).
- [run request normalization](/tmp/openlet-streaming-source-review-261112/langgraph-api-0.17.1/langgraph_api-0.17.1/langgraph_api/models/run.py:220).
- [production publish client](/tmp/openlet-streaming-source-review-261112/langgraph-api-0.17.1/langgraph_api-0.17.1/langgraph_api/grpc/ops/runs.py:1006).

### Connect và reconnect

POST run-stream đăng ký subscription trước khi tạo run, rồi stream kết quả. Disconnect default `continue`; opt-in `cancel` là control khác. Response có Location trỏ tới run stream có thể join lại.

`GET /threads/{thread_id}/runs/{run_id}/stream` nhận `Last-Event-ID` và optional stream mode filter. Python gửi cursor vào backend join; từng output giữ event/frame identity. Không có bước server biến toàn suffix thành final message trong các đường Python đã đọc.

Development backend giữ từng resumable frame trong RAM theo thread/run; restore duyệt stored messages sau cursor. Đây không phải cross-replica/durable backend. Không suy ra production có cùng giới hạn hoặc thuật toán từ implementation in-memory này.

Sources:

- [create + stream](/tmp/openlet-streaming-source-review-261112/langgraph-api-0.17.1/langgraph_api-0.17.1/langgraph_api/api/runs.py:322).
- [join with Last-Event-ID](/tmp/openlet-streaming-source-review-261112/langgraph-api-0.17.1/langgraph_api-0.17.1/langgraph_api/api/runs.py:610).
- [development put/restore](/tmp/openlet-streaming-source-review-261112/langgraph-runtime-inmem-0.37.1/langgraph_runtime_inmem-0.37.1/langgraph_runtime_inmem/inmem_stream.py:99).

### Cumulative content không đồng nghĩa giảm event count

Legacy `messages` mode có đường cộng chunk vào accumulated message rồi phát `messages/partial` chứa nội dung cộng dồn, cùng metadata/complete events. `messages-tuple` giữ chunk + metadata. Việc tích lũy text ở đây vẫn phát trên từng input chunk; không phải timed coalescing. Không mặc định chọn cumulative partials cho Leta vì nó lặp lại content trên wire.

Source: [legacy messages shaping](/tmp/openlet-streaming-source-review-261112/langgraph-api-0.17.1/langgraph_api-0.17.1/langgraph_api/stream.py:605).

## 3. LangGraph API: Protocol v2 thread stream

Package có đường mới `POST /threads/{thread_id}/stream/events`, JSON commands riêng và WebSocket. SSE body chọn channels/namespaces/depth và `since`; client reconnect chủ động bằng body, không native EventSource Last-Event-ID. Feature flag default on, nhưng graph/framework phải có required v2/v3 symbols; không suy ra mọi installed LangGraph version đều chạy được.

Wire là protocol riêng với `method`, `params`, `event_id`, `seq`, không phải AG-UI event schema.

Điểm quan trọng: `ThreadRunManager.start_thread_stream` luôn đọc source từ đầu retained thread stream (`last_event_id="-"`) để dựng projections cho observers/subgraphs. Route lọc outbound events bằng `since`; event_id ổn định cho client dedupe. Vì vậy client nhận suffix không có nghĩa backend chỉ đọc suffix. Source comments gọi tên tradeoff này để hỗ trợ observers mở muộn.

WebSocket session có replay buffer normalized events, default 10.000 entries/run. Quá trần thì evict oldest; cursor không còn đủ coverage trả `resume_gap`. Replay subscription drain snapshot và arrivals mới trước khi activate live. SSE tắt session replay buffer này và dùng thread source replay, không có hai buffer cùng phục vụ SSE.

SSE route drain pending output thành từng frame. Đây là queue draining, không nối nhiều text deltas thành một logical event. Không thấy built-in timed coalescing trong API publish/SSE paths đã đọc; custom graph transformers hoặc private backend không thuộc kết luận này.

Sources:

- [thread SSE contract and implementation](/tmp/openlet-streaming-source-review-261112/langgraph-api-0.17.1/langgraph_api-0.17.1/langgraph_api/api/event_streaming.py:123).
- [source replay from beginning](/tmp/openlet-streaming-source-review-261112/langgraph-api-0.17.1/langgraph_api-0.17.1/langgraph_api/event_streaming/service.py:299).
- [session buffer + replay/gap](/tmp/openlet-streaming-source-review-261112/langgraph-api-0.17.1/langgraph_api-0.17.1/langgraph_api/event_streaming/session.py:974).
- [v2 defaults](/tmp/openlet-streaming-source-review-261112/langgraph-api-0.17.1/langgraph_api-0.17.1/langgraph_api/event_streaming/constants.py:5).

## 4. Agno: native resumable AgentOS stream

### Producer và storage

Plain-text `handle_model_response_chunk` cộng text vào final RunOutput nhưng phát RunContent event chứa delta hiện tại. Background producer/queue worker đưa từng event tới event stream; không thấy timed content coalescer trong các đường này.

Default event stream là InMemoryEventStream. Singleton buffer được cấu hình 10.000 events/run và cleanup interval 1.800 giây; không nhầm với constructor defaults 1.000/3.600. Mỗi event có monotonic `event_index`, giữ continuity qua buffer trims; subscriber queue phục vụ live delivery.

Optional RedisEventStream mặc định MAXLEN xấp xỉ 10.000 entries/run, TTL 1.800 giây, XREAD block 15 giây. Mỗi event cấp index rồi append một Redis record chứa index và SSE payload. Redis IDs là implementation detail, cursor công khai là event_index trong JSON; formatter không emit SSE id field.

TTL không chỉ refresh lúc có token. Background refresher giữ keys active runs sống trong thời gian tool chạy im lặng. Tail kiểm status khi idle và terminal markers để không chờ vĩnh viễn producer đã mất. Queue attempts có generation fencing riêng; không nên port nó sang Leta vốn đã có Temporal/writer barrier.

Sources:

- [content chunk mapping](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/agent/_response.py:1359).
- [background stream publisher](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/run/background.py:90).
- [default buffer configuration](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/os/managers.py:503).
- [Redis defaults](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/os/event_streams/redis.py:110).
- [Redis append](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/os/event_streams/redis.py:520).

### Resume và chi phí replay

`POST /agents/{agent_id}/runs/{run_id}/resume` nhận form fields last_event_index và session_id. Ba đường:

1. Run active: replay buffered events sau floor, rồi tail live.
2. Run terminal nhưng buffer còn: replay phần thiếu rồi đóng.
3. Buffer không biết run: thử DB RunOutput.events nếu có session và stored events; không tự sinh lại tokens bằng model.

In-memory tail subscribe trước, replay sau rồi dedupe live queue bằng index. Redis tail XRANGE retained prefix, ghi nhớ exact Redis ID cuối đã đọc, rồi XREAD sau ID đó. Đây là cách nối replay/live không bỏ events trong khoảng chuyển tiếp.

Redis `replay` gọi XRANGE toàn retained stream rồi lọc idx > floor ở Python: O(retained entries), không phải Redis range seek theo public cursor. `get_event_count` cũng scan; active resume gọi replay trước rồi tail có initial scan của chính nó. Vì MAXLEN hữu hạn, chi phí bị chặn nhưng không là đường đọc tối thiểu cho reconnect gần tail.

Buffer head đã trim: in-memory get_events trả phần đang còn, không phát một resync protocol tương đương LangGraph WS resume_gap tại function này. Không suy ra complete replay khi cursor cũ hơn retention.

Sources:

- [resume three paths](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/os/routers/agents/router.py:496).
- [Redis replay scan](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/os/event_streams/redis.py:569).
- [Redis prefix then tail](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/os/event_streams/redis.py:620).
- [RAM subscribe first](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/os/event_streams/in_memory.py:156).
- [trim behavior](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/os/managers.py:270).

### Database fallback không mặc định lưu token stream

Agent default store_events=False. Khi bật, events_to_skip mặc định vẫn có RunContent; handle_event chỉ append events được cấu hình lưu vào RunOutput.events. Skip ở đây là skip persistence, không skip live streaming/buffer. Vì vậy DB fallback có thể replay stored lifecycle/tool events nhưng không hứa từng text delta. Complete output vẫn là dữ liệu riêng trên RunOutput.

Stored events đã được stamp index giữ original event_index; DB fallback lọc sau floor, không renumber các event đó. DB save không phải synchronous event log append cho mỗi token; fallback không phải universal active-run recovery khi buffer mất.

Sources:

- [Agent defaults](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/agent/agent.py:354).
- [default skipped content](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/agent/agent.py:701).
- [storage filter](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/utils/events.py:1160).
- [DB replay](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/os/utils.py:534).

## 5. Agno AG-UI là interface riêng

AG-UI router nhận RunAgentInput, gọi entity.arun(stream=True, stream_events=True), map native events sang AG-UI rồi encode SSE. Text handler tạo START khi cần rồi CONTENT delta cho từng native content event. Native /resume buffer/index path không được tự gắn vào router này. Các hàm resume_paused_run ở AG-UI là tiếp tục execution sau tool/HITL, khác reconnect stream.

Không kết luận Agno không thể tích hợp resumable AG-UI; kết luận hẹp là router này không cung cấp nó tự động. AG-UI normalization và replay transport là hai trách nhiệm riêng.

Sources: [run_entity](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/os/interfaces/agui/router.py:40), [stream mapping](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/os/interfaces/agui/stream.py:41), [text events](/tmp/openlet-streaming-source-review-261112/agno-3.1.12/agno-3.1.12/agno/os/interfaces/agui/handlers.py:131).

## 6. Hệ quả cho proposal Leta, chưa thay quyết định

- Không có bằng chứng từ source vừa đọc rằng một token tương đương một event, hoặc coalescing 50 ms là bắt buộc. Source events ở cấp provider/framework chunks; có thể có nhiều protocol events cho một source item.
- Cả hai chọn recent event replay có giới hạn và canonical state/output riêng. Không đọc token log cả năm để dựng UI năm đó.
- Client nhận suffix và server chỉ đọc suffix là hai claims khác nhau. Leta đã định dùng Redis ID cursor nên có thể native seek suffix, không cần thêm Agno-style public counter chỉ để giống thư viện.
- Source không chứng minh ngưỡng 50 ms/16 KiB/1.000 replay events vừa đề xuất là tối ưu. Các số đó là proposal của trợ lý, chưa benchmark/được người dùng chốt. Không đưa vào plan như findings của thư viện.
- Nếu chọn delta coalescer, đặt trước Redis mới giảm record/XADD count; sau Redis chỉ giảm outgoing frames. Đây là suy luận từ vị trí append, không claim đã thấy hai thư viện làm như vậy.
- Giữ ordering, stable identity, replay/live handoff và explicit resync khi mất coverage. Không bê subsystem WS sessions/generations/queue/status mirrors từ upstream sang Leta.
- Không mất whole logical run/agent chỉ vì stream mất hoặc subscription đóng. Execution retry, HITL resume và stream reconnect phải được gọi tên riêng.

## 7. Verification và giới hạn

Đã kiểm artifact SHA-256, đọc actual source theo paths trên và AST-parse owning files để kiểm symbol/line references. Link paths/fences/whitespace của report được kiểm riêng. Không chạy provider, Redis/DB/server integration hoặc benchmark; không thực thi sdists/build hooks. Không download được production postgres backend từ public PyPI và không có Go server source để chứng minh nội bộ. Không đổi approved Leta plan, app source/config/dependencies/data hoặc khởi động background server.
