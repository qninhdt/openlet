# Leta: checkpoint hội thoại, bằng chứng và các đề xuất đang bàn

Ngày khảo sát: 2026-11-07. Đây là checkpoint brainstorm, chưa phải plan triển khai. Phân biệt các quyết định user đã chốt bên dưới với các đề xuất còn đang bàn.

## Tiếp tục từ đây

Current continuation (2026-11-08): use the detailed English [implementation plan](../261108-0001-leta-agent-engine/plan.md) and its design/tool contracts for execution. The user accepted the architecture, compaction/custom input UI and RAM/checkpoint behavior and requested planning. Historical proposals below remain evidence, not current authority. Source-backed final review corrections and implementation experiments are recorded in that plan; no production code, database or deployment has changed.

**Quyết định hiện hành đã được user chốt — ưu tiên hơn ghi chép lịch sử bên dưới:**

- Runner dùng LangChain `create_agent` (trả LangGraph), tools/middleware Openlet, async PostgreSQL checkpointer và durability="sync". Đây là tên factory của runner, không phải tool tạo account/Leti.
- Server cấu hình sẵn nhiều model và reasoning modes hợp lệ; owner chọn model/reasoning cho Leta và có thể cấu hình Leti. Leti mặc định kế thừa Leta; không giới hạn MVP vào một model chung, không thêm BYOK/routing service.
- Owner sửa name/system prompt (áp ở boundary kế tiếp, giữ context), pause/resume toàn Leta và boxes; inbox/HITL/lịch vẫn tiếp nhận. Xóa dừng runtime, hủy lịch/pending HITL, thu hồi grants; giữ history/files archived, chưa tự purge.
- Bỏ đề xuất giới hạn số model calls/steps mỗi run và runtime budget mới. Không sao chép recursion_limit=100 của lab thành product policy; xử lý cấu hình kỹ thuật upstream ở bước plan để không tạo giới hạn ngầm trái quyết định này.
- Chốt native Temporal BUFFER_ONE cho recurring schedule delivery, catchup mặc định Temporal. Đây là overlap của delivery workflow, không đợi agent hoàn tất việc; không cam kết latest-only hoặc bù mọi occurrence.
- Approval là xin quyền tài nguyên, MVP xin personal scope của bất kỳ human active member cùng workspace; ask_user giữ nguyên nhiều câu hỏi và gửi owner.
- request_access nhận personal-scope user, reason, viewer/editor (mặc định viewer) và timeout. Runtime xác định đúng scope owner làm approver, account Leta làm grantee. Leti kế thừa quyền Leta; card ghi rõ Leta, owner và phạm vi hưởng quyền.
- Accept cấp scope relation hiện có rồi gửi kết quả vào inbox; không giữ/chạy lại một tool call cũ. Bỏ test_approval và dangerous-tool approval policy. Bốn trạng thái HITL giữ nguyên.
- Grant có hiệu lực tới khi thu hồi; timeout là hạn trả lời request. Owner Leta không tự được duyệt thay scope owner khác. Owner có thể thấy dữ liệu đã đọc qua transcript/kết quả; thu hồi quyền không xóa dữ liệu đã đọc.
- Mount foreign personal ở /users/<user-account-id>/, nhiều user cùng tồn tại; viewer=READ, editor=WRITE. Leti vẫn chỉ có box home trong Leta personal, ngoài ra kế thừa shared và foreign personal mounts đã được cấp.
- Mirage 0.0.8 hỗ trợ dynamic add_mount/unmount/set_mount_mode. Dựng view đầu invocation, refresh ở boundary sau grant hoặc get_workspace; mỗi agent một workspace view, backend authz/fresh cache vẫn là bắt buộc.
- Bổ sung aggregate filesystem-view API tại workspace service: membership query và BulkCheck theo batch, không query cây filesystem hoặc đọc lại HITL history để suy ra quyền. Không thêm bảng grants song song SpiceDB.
- history là public LLM transcript (inputs/steering, assistant/tool calls/arguments/results, final notes), không chỉ chat owner. PostgreSQL giữ history; LangGraph giữ context đang dùng sau compaction. Không lưu hidden chain-of-thought.
- Tool delta: bỏ test_approval; thêm request_access/list_workspace_members; get_workspace trả mounts, semantic_search mặc định dùng readable roots đang mount. Contract chi tiết ở hai phần cuối.

Các ngưỡng context, cấu hình Redis và chi tiết API/schema có thể điều chỉnh ở plan/implement như user đã cho phép. Không dùng ghi chép tool approval cũ làm baseline mới.

- Đang brainstorm bằng tiếng Việt, chưa triển khai `leta`. Yêu cầu gốc bao phủ inbox, box, HITL, lịch/calendar, hai lớp durability, streaming/UI, permission và Mirage–LetFS.
- User cần một agent engine thống nhất bằng PostgreSQL, LangGraph, Temporal và Redis, kèm đường đọc dữ liệu cho mọi màn hình UI. Không tiếp tục trả lời rời rạc từng tính năng. Phần thiết kế bên dưới được viết lại cho lượt này, chưa phải approval triển khai.
- User đã chốt mỗi Leta chỉ thuộc một workspace. Không hỏi lại. Leti thuộc box trong cùng workspace, không có account.
- Quyết định mới: Leta dùng permission shared/personal theo role như human member. Approval là request cấp quyền tài nguyên, không phải giữ tool call để duyệt. Bỏ test_approval. Cả Leta/Leti có thể xin human user cùng workspace cấp quyền personal scope cho Leta account; user đã chốt Leti kế thừa quyền Leta. Không có grant mặc định lên personal của owner; sau khi owner hoặc user khác đồng ý mới mount personal tương ứng.
- Một inbox item tổng quát cho các nguồn đầu vào. Không hardcode ba loại nguồn vào lõi điều phối. “Quota đầy” chỉ là ví dụ tương lai, không phải feature cần triển khai.
- Bỏ trạng thái inbox “đã đóng”, outbox/wake-intent dispatcher/reconciliation poller, replay worker, operation/delivery entities, leasing/fencing/revision mới và câu hỏi nhiều-workspace. Đây là các đề xuất trước đã bị bác bỏ, không được mang trở lại như quyết định đã chốt.
- ID tin nhắn, ID box, ID lịch và ID request HITL là định danh của đối tượng thật. Tận dụng `tool_call_id` đã lưu khi retry; không tạo thêm hệ khái niệm operation/delivery ID.
- HITL chốt hai loại request: approval và ask_user. Ask_user chứa nhiều question; từng question là single choice, multiple choice hoặc text input. Phải có payload cụ thể và hành vi accept/deny.
- Cơ chế tool approval/accept thực thi tool call cũ đã bị user thay thế ở lượt 21:18: accept nay chỉ cấp resource access, không tự chạy lại tool cũ. Giữ lifecycle pending/resolved/cancelled/expired; decision accept/deny và outcome cấp quyền riêng. Ask_user nhiều câu hỏi giữ nguyên và MVP vẫn hỏi owner; resource approval gửi tới chủ personal scope được xin, bất kỳ human active member cùng workspace.
- Quiz mới nhất: bỏ Other. Single choice cho option_id=null, multiple choice cho option_ids=[]; cả hai có note, được submit mà không chọn option. Text question chỉ có text, không thêm note. Quy tắc này thay thế toàn bộ đề xuất Other trước đó.
- User bác bỏ tool send_box riêng. Dùng một send_message hỗ trợ ID/name, runtime resolve và áp dụng quyền/representative routing. Không lưu field slug; suy ra từ box.name, kiểm tra collision.
- Mirage không được đọc raw blob hoặc sửa payload blob. Blob hiện metadata, nội dung đi qua artifact. Ảnh vẫn đọc bằng cùng tool read_file dưới dạng multimodal qua artifact/preview, không mở bytes blob cho shell/Monty.
- User cho phép thiết kế lại toàn bộ LetFS để phục vụ Mirage; không được mặc định chỉ fallback tải toàn bộ content. Cần đầy đủ API path/text/lines/search/tree và hook tương ứng. Đây là quyền thiết kế, chưa phải lệnh triển khai/migrate.
- User đã đồng ý bộ API LetFS đề xuất, Redis cache và LangGraph durability="sync". Graph và AsyncPostgresSaver vẫn async I/O. User chấp nhận các giới hạn riêng Mirage, yêu cầu cung cấp đầy đủ hooks/API LetFS trong khả năng Mirage, không fork để ép hỗ trợ ngoài thư viện.
- Read blob phải trả metadata kèm artifact tree. Không phải chỉ một danh sách URL hoặc metadata không có cây.
- User đã chốt tạm cả bảy mục engine chi tiết trong câu trả lời trước: đơn vị thực thi, inbox envelope, receive/wake/cursor, LangGraph boundaries, messaging/HITL, retry và box lifecycle/UI. Đây là baseline để lập plan về sau, được phép điều chỉnh khi plan/implement; chưa yêu cầu bắt đầu plan hoặc implement ngay.
- User đã đồng ý scheduler at/interval/calendar để hỗ trợ sau 5 giây, sau 1 giờ, mỗi giờ, mỗi 5 ngày và hằng tháng; daily/weekly chỉ là UI presets. UI vẫn "Lịch", domain/API/tool "schedule", một model PostgreSQL và một executor Temporal. Có at cho mốc chạy cụ thể và bổ sung end_at tùy chọn cho mốc dừng lịch lặp; native ScheduleSpec 1.35.0 đã hỗ trợ end_at. Sau end_at không sinh thêm mốc, không hủy job/message đã sinh trước đó.
- User xác nhận Mirage: làm LetFS APIs + VFS adapter/hooks, mount/auth/cache/representations; phần mapping command/flags thuộc Mirage và chấp nhận giới hạn thư viện đã nêu.
- Trigram: user đã đồng ý hướng dùng GIN cho candidate substring search và giải thích lựa chọn planner. Benchmark default planner chưa được cải thiện; forced-index numbers chỉ là diagnostic, không chứng minh production query đã được tối ưu. Không tắt seqscan toàn hệ thống, không thêm search service/chunk table chỉ từ kết quả này.
- Nguồn mới đã đọc: https://docs.mirage.strukto.ai/home/integration và các trang Search/Lines/Walks/Checksums/Custom VFS/File cache; https://www.mintlify.com/blog/how-we-built-a-virtual-filesystem-for-our-assistant. Web tool không tải được Mirage nhưng HTTPS trực tiếp và bản .md tải thành công, lưu .txt trong /tmp/leta-research/.
- Đã đọc/áp dụng `ak-brainstorm`, `ak-databases` và `find-docs`; không spawn subagent. Lượt này đọc thêm OpenClaw schedules, n8n Schedule Trigger, APScheduler 3.x triggers qua Context7 và Temporal docs + SDK 1.35.0. Không chờ approval để đọc/ghi checkpoint hoặc chạy benchmark đã được yêu cầu; chưa có approval triển khai.
- Workspace branch `dev`; thay đổi giới hạn ở checkpoint, script benchmark và JSON kết quả trong plans/reports. Không sửa production code/config/schema, không truy cập DB Openlet, không chạy paid inference. Benchmark tạo PostgreSQL container riêng, không publish port và tự stop/remove trong finally. Thư mục `/tmp/leta-research/` chứa source release và tài liệu đã tải; tránh đọc lại toàn bộ HTML dài hoặc `.venv` đã bị hook chặn.

## Outcome và giới hạn

- Owner có thể tạo Leta như một member có account và personal scope; Leti không có account.
- Agent sống qua nhiều lượt xử lý, có inbox, trao đổi có địa chỉ, lịch và HITL; chờ một việc không khóa các việc độc lập.
- MVP chỉ chat với owner; exception mới đã chốt là resource access requests có thể gửi tới human user khác cùng workspace. Không mở chat trực tiếp với họ. Không thêm chat service, graph editor đầy đủ, task model hoặc job queue riêng.
- Acceptance của thiết kế: giải thích được lưu đầu vào, đánh thức, steering, reply routing, recovery và permission trong luồng owner → Leta → box → HITL → nhắc việc khác → trả lời → tiếp tục.
- Chưa triển khai, migrate, chạy model trả phí, hay thay đổi dịch vụ Openlet đang chạy. Chỉ chạy benchmark PostgreSQL tạm trên synthetic data theo yêu cầu.

## Hiện trạng Openlet đã đối chiếu source

Nguồn điều hướng: [README](../../README.md), [architecture](../../docs/architecture.md), [docs index](../../docs/README.md).

1. [Plan account/scope](../261106-1517-account-scope-temporal-redesign/plan.md) ghi completed. [Design contract](../261106-1517-account-scope-temporal-redesign/design-contract.md) có một số mô tả đã được thay bằng thay đổi sau đó: move/restore hiện có thể cross-scope trong cùng filesystem; copy/purge chạy trực tiếp trong request. [Plan direct operations](../261107-1114-direct-cross-scope-file-operations/plan.md) và code hiện hành là bằng chứng cho phần này. Không dùng số workflow trong plan cũ như catalogue hiện tại.
2. [Account migration](../../apps/account/migrations/0001_initial.sql): một bảng `accounts`, `type=user|agent`, agent có immutable owner và không có Clerk identity. [Service.CreateManaged](../../apps/account/internal/account/service.go) tạo managed account nhưng không tạo runtime, credential, membership hay personal scope.
3. Code gọi nhóm thành viên là `workspace`: [Workspace migration](../../apps/workspace/migrations/0001_initial.sql) có `workspace_members`, role `owner|admin|member`, personal scope cho từng cặp workspace/account. Schema account dùng chung cho phép nhiều membership; sản phẩm `leta` đã được user chốt một Leta chỉ gắn một workspace. Áp dụng ràng buộc này cho Leta, không hỏi lại và không mặc nhiên thay đổi membership của mọi user account.
4. [WorkspaceChanges](../../apps/workspace/internal/temporal/relationships.go) tạo scope trước AddMember; [WriteMemberRelationships](../../apps/workspace/internal/workspace/relations.go) cấp manager cho chính member trên personal scope. Shared scope cấp manager cho workspace owner/admin, editor cho active members.
5. [SpiceDB schema](../../packages/contracts/authz/schema.zed): owner đọc/sửa account không kế thừa tài nguyên của account. Scope có viewer/editor/manager; LetFS không biết owner, agent hay workspace role. Quyền owner xem mọi thứ thuộc Leta phải được bổ sung có chủ đích. Shared data của workspace không tự trở thành tài sản riêng của Leta.
6. Không thấy runtime `leta`/`leti`, LangGraph, Mirage, Monty hay Redis trong stack ứng dụng Openlet đang khảo sát. Python platform pin Temporal SDK 1.35.0. Không có phiên bản Mirage/Monty “đang dùng” để kế thừa.

## LetFS có thể tái sử dụng

Nguồn: [Python client](../../packages/python/src/openlet/clients/letfs.py), [node operations](../../apps/letfs/internal/filesystem/node_writes.go), [paths](../../apps/letfs/internal/filesystem/paths.go), [download](../../apps/letfs/internal/filesystem/download.go), [HTTP content](../../apps/letfs/internal/transport/http/content.go), [search](../../apps/letfs/internal/filesystem/search.go), [semantic search](../../apps/letfs/internal/filesystem/semantic_search.go).

- Có ResolveNode/GetNode/ListNodes/BatchStat, create/update/replace, copy/move, trash/restore/purge, uploads/downloads và semantic search. Mọi request chỉ rõ filesystem/scope. `/` là root của scope, không phải virtual root toàn account.
- `ReplaceContent` và thay đổi node dùng revision guards. Adapter phải giữ các precondition này khi read-modify-write; không biến append hoặc sửa file đồng thời thành silent last-write-wins.
- `GetDownload` trả inline bytes hoặc signed URL tới immutable object. HTTP `singleRange`/`writeDownload` hỗ trợ một byte range. Với inline, Store vẫn đọc toàn bộ bytes từ PostgreSQL trước khi HTTP cắt range. gRPC GetDownload/Python client không có offset/size, vẫn trả inline body đầy đủ hoặc URL.
- Default inline limit 262144 bytes, max configurable 1048576; default max file 104857600 bytes trong config hiện tại. Đọc toàn bộ inline file nhỏ khác đáng kể với grep hàng loạt object file lớn.
- `SearchFiles` tìm substring trên name/title; không tìm nội dung file. Không dùng nó để trả candidate set hoàn chỉnh cho grep.
- `SemanticSearch` kiểm tra read_content trước provider call, giới hạn một scope, hydrate theo ancestry và generation hiện hành, rồi reauthorize/hydrate sau rerank. Có parent filter có thể ép về box root. Không thay parent filter bằng gợi ý trong prompt.
- Scope `allow_indexing=false` trả semantic result rỗng. Search không bao phủ một cách mặc định mọi file chưa được index. Semantic search không thay grep chính xác.
- Scope là authorization boundary hiện tại; box home là thư mục bên trong personal scope. Leti chạy dưới quyền Leta nên cần thêm runtime restriction theo box root/mount. LetFS không tự phân biệt hai Leti dùng cùng Leta account.

## Agent lab: khả năng và giới hạn

Nguồn chính: [integration audit](../../../agent-lab/docs/integration-audit.md), [inbox contract](../../../agent-lab/docs/agent-inbox-design.md), [worker](../../../agent-lab/labs/durable-chat/chat/worker.py), [workflow](../../../agent-lab/labs/durable-chat/chat/workflows.py), [middleware](../../../agent-lab/labs/durable-chat/chat/inbox.py), [API](../../../agent-lab/labs/durable-chat/chat/api.py).

- Chat lab pin Deep Agents 0.7.32, LangGraph 1.2.19, postgres checkpointer 3.2.0, ag-ui-langgraph 0.0.47, Temporal SDK 1.35.0. Benchmark `temporalio-deepagents==0.0.3` là đường riêng, không phải engine của chat lab.
- Chat lab chạy whole-graph Activity, AsyncPostgresSaver, Redis stream và SSE proxy qua FastAPI; AG-UI adapter chuyển graph events. Có một LangGraph thread cho mỗi agent.
- Active inbox nằm trong Temporal Workflow state/Signals, có query read_inbox và middleware đọc trước model boundary. PostgreSQL giữ conversations/runs/receipts/checkpoints; không có inbox domain table riêng.
- Code `AgentWorkflow.run` chờ approval khi `self.interrupts` còn tồn tại. Input mới vẫn vào inbox nhưng không được agent đó xử lý trước approval. Parent/child độc lập không chứng minh một agent đang chờ HITL có thể làm việc khác.
- Lab hỗ trợ explicit send_message/send_result, create-only child và idle parent. Final text không tự forward. Policy same-root trong lab khác graph edge policy và box representative của Openlet.
- [Inbox verification](../../../agent-lab/plans/reports/test-261104-1023-agent-inbox-and-redesign.md) và [subagent verification](../../../agent-lab/plans/reports/test-261104-0845-temporal-subagents.md) ghi nhận busy steering, dedup, worker kill, explicit results, HITL/browser/reconnect trên hạ tầng thật. Đây là bằng chứng lịch sử, không phải một lần chạy mới trong khảo sát này.
- Lab không có auth production và Python tool không sandbox. Không tái sử dụng security boundary đó cho Openlet. Model-selected collaboration có case không hội tụ dù tin đã giao đúng.
- `DurableAgent.get_stream_kwargs` đặt `durability="async"`. AsyncPostgresSaver/graph async là lựa chọn I/O, khác chính sách checkpoint durability. Source distribution LangGraph 1.2.19 `Pregel.astream` mô tả sync là chờ persist trước step kế, async là persist song song với step kế.
- PostgreSQL advisory lock giữ checkpoint writers không chồng nhau khi session còn sống; không fence side effect bên ngoài khi session mất hoặc attempt cũ còn chạy.

### Ba nghĩa của replay

1. Temporal history replay phục hồi deterministic orchestration; không tự chạy lại LLM đã hoàn tất Activity. Activity chưa được ghi completion vẫn có thể retry.
2. LangGraph checkpoint recovery phục hồi message list/node state; step chưa được persist có thể chạy lại, nhất là durability async.
3. Client event replay đọc Redis cursor để dựng UI. Mất token event không đồng nghĩa mất inbox hay workflow, và checkpoint không tái tạo toàn bộ token đã stream.

### Gộp event đã đo trên đúng đường

[Verification](../../../agent-lab/plans/reports/261104-streaming-replay-verification.md), `chat/api.py:events` và `chat/streaming.py:coalesce_events` xác nhận gộp ở API khi đọc Redis để phát SSE; worker vẫn publish từng event vào Redis.

- Chỉ nối delta liền kề có envelope tương đương, cùng message/tool identity và metadata; cursor lấy từ event cuối. Không gộp qua start/end, snapshot hay event khác. Có ceiling 65536 ký tự.
- Captured log: 4681 → 438 events (giảm 90.6%); 4146779 → 3773283 bytes (giảm 9.0%). Snapshots vẫn chiếm phần lớn bytes.
- Không suy ra Redis writes, checkpoint hay Temporal history giảm theo tỷ lệ đó.
- [Capacity follow-up](../../../agent-lab/plans/reports/test-261104-1824-capacity-fix-gains.md) còn ghi workload fanout nhanh hơn coalesce được ít hơn, làm frame/byte tăng. Tối ưu phụ thuộc workload; không hứa tỷ lệ cố định.

## Thư viện bên ngoài đã kiểm tra

### Temporal, lịch và AG-UI

- [Python message passing](https://docs.temporal.io/develop/python/workflows/message-passing): Temporal Signal là async input của Workflow; Signal-With-Start khởi động nếu chưa chạy. Đây không thay thế PostgreSQL transaction cho domain inbox nếu chọn PostgreSQL làm authority.
- [Python Schedules](https://docs.temporal.io/develop/python/workflows/schedules): ScheduleActionStartWorkflow khởi động workflow, không trực tiếp là Signal vào một agent. Có thể dùng delivery workflow ngắn để đi qua cùng inbox ingress. Timer là durable wait bên trong workflow; không cần giữ Python process thức chờ tới ngày mai.
- [APScheduler 3.x](https://apscheduler.readthedocs.io/en/3.x/userguide.html): date/interval/cron là ba dạng trigger; persistence/misfire/coalescing là cấu hình của scheduler. Thêm APScheduler lúc đã có Temporal tạo thêm một scheduler cần vận hành.
- [dateutil rrule](https://dateutil.readthedocs.io/en/stable/rrule.html): biểu diễn/tính recurrence theo iCalendar; không tự lưu job hay đánh thức worker. Không phải mọi RRULE chuyển nguyên vẹn sang Temporal ScheduleSpec. Trang stable hiện hiển thị dateutil 4.0.0, không phải một dependency đã pin của Openlet.
- [AG-UI events](https://github.com/ag-ui-protocol/ag-ui/blob/main/docs/concepts/events.mdx) có run/text/tool/state/custom events; không cung cấp domain inbox, notification service hay durable scheduler. Nhật ký owner cần application records/metadata bên cạnh protocol.
- [Always-On Agent](https://rubriclabs.com/blog/always-on-agents) hữu ích về một dòng làm việc liên tục, quản lý context và chủ động thức dậy; không phải bằng chứng cho exactly-once delivery hay implementation Openlet.

### Mirage/Monty: mốc khảo sát, chưa chốt dependency

Openlet và lab chưa pin cả hai. Đã đọc source distribution PyPI `mirage-ai==0.0.8`, đối chiếu [tag v0.0.8](https://github.com/strukto-ai/mirage/tree/v0.0.8) tại commit `d7e56211a2f09531718510edde4baba216f2439f`. Main đang ghi `0.0.9a1`, không dùng main để khẳng định API của bản cài. Extra Monty trong [pyproject v0.0.8](https://github.com/strukto-ai/mirage/blob/v0.0.8/python/pyproject.toml) pin `pydantic-monty==1.4.0`; PyPI Monty latest lúc khảo sát là 1.5.0, không tự nâng theo latest.

- [Files](https://github.com/strukto-ai/mirage/blob/v0.0.8/python/mirage/workspace/files.py) có read(offset,size,stream,session_id), write, append, pwrite, stat, readdir, mkdir, unlink, rename và các thao tác khác. Không cần ép mọi file operation thành shell command. Các API này đi qua dispatcher/mount/cache/session checks.
- [BaseVFS](https://github.com/strukto-ai/mirage/blob/v0.0.8/python/mirage/vfs/base.py) yêu cầu read/readdir/stat; có read range capability và các extension point first_lines, last_lines, files_containing, lines_containing. Không cần thay parser grep/head/tail để viết adapter.
- Head/tail có thể dùng range trên object backend rồi tìm newline; một dòng rất dài vẫn có thể buộc đọc toàn file. Với inline, LetFS GetDownload vẫn tải toàn bytes. Chưa có backend API đọc N dòng hoặc grep raw content; fallback đọc/stream bytes rồi lọc là đúng semantics. Native filename/title search hoặc semantic top-k không đủ làm bộ lọc loại trừ cho grep.
- [MontyFs](https://github.com/strukto-ai/mirage/blob/v0.0.8/python/mirage/runtime/python/monty/fs.py) đưa file access qua RuntimeFiles và announced mounts của workspace. Không tự nhìn thấy host filesystem. Callback hiện nhận whole-file reads; việc Files.read có range không có nghĩa Python guest tận dụng range cho mọi file read. Callback sync đợi backend I/O có thể giữ Monty worker thread; cần đo với adapter async thật.
- [CacheConfig](https://github.com/strukto-ai/mirage/blob/v0.0.8/python/mirage/cache/file/config.py) có RAM và Redis stores. Default file cache RAM 32MB, Redis config 512MB; BaseVFS.caches_reads mặc định false, index_ttl mặc định 600s. Có cache nội dung và index/listing, không chỉ một cache.
- [RedisFileCacheStore](https://github.com/strukto-ai/mirage/blob/v0.0.8/python/mirage/cache/file/redis.py) là cache store, khác RedisVFS mount làm nguồn dữ liệu. [Invalidation](https://github.com/strukto-ai/mirage/blob/v0.0.8/python/mirage/cache/file/invalidation.py) ghi rõ fill guard chỉ theo local invalidations, không theo mọi Redis client khác. Redis chung không tự bảo đảm coherence với LetFS writer/worker khác.
- BaseVFS có fingerprint/read_revalidatable và fresh-read policy; adapter phải thực sự đóng dấu cùng kiểu revision ở stat/read mới được khai báo hỗ trợ. Tính tươi của listing cũng cần kiểm tra riêng. Không lấy cache làm permission authority.
- Có Workspace.close/load, SessionManager.create/close và session state serialization. Không cần giữ một live object xuyên Temporal retry. Đề xuất để thử: workspace/session gắn với một invocation, giữ trong invocation để tái sử dụng, đóng khi hết; mount được dựng từ agent identity/grants hiện hành. Persist cwd cần thì lưu riêng; không giữ coroutine, pool hay toàn bộ RAM cache trong checkpoint.
- Box chung home là chia sẻ dữ liệu có chủ ý. Giữ precondition hiện có của LetFS; không thêm hệ revision mới. Đề xuất trước tắt cache/RAM đã được thay bằng Redis cache + FRESH trong thiết kế lượt mới bên dưới. Source `CacheManager.listing_trusted` cho thấy một shell command có thể dùng listing đã lấy trong command đó; programmatic calls có trust window ngắn. Chưa chạy hai worker để kiểm chứng adapter thật.

## Đề xuất engine thống nhất — thay thế các đề xuất cũ

Các mục từ đây là thiết kế đang đề xuất theo lượt 18:38. Quyết định mới của user ở phần đầu có ưu tiên cao hơn; chưa có lệnh triển khai.

### Thành phần và dữ liệu UI

Service `leta` có hai process: API và worker. API đọc dữ liệu UI từ PostgreSQL, nhận command và proxy SSE. Worker chạy Temporal workflows/activities, LangGraph và Mirage adapter. Không có service Leti riêng.

- PostgreSQL là nguồn dữ liệu lâu dài của inbox/messages, agent/box graph, lịch, HITL và activity log. UI không duyệt Temporal histories để dựng màn hình.
- Temporal giữ tiến độ điều phối: nhận input, agent có cần chạy, Activity đang chạy, retry/cancel, timeout request và execution của lịch. Không giữ bản inbox/UI graph/history đầy đủ làm authority.
- LangGraph dùng AsyncPostgresSaver trong cùng PostgreSQL deployment nhưng bảng riêng của checkpointer; giữ working message list và trạng thái node/tools. Không dùng working message list làm lịch sử chat của owner.
- Redis có hai namespace/trách nhiệm: AG-UI stream và Mirage content/index cache. Không giữ bản duy nhất của inbox hoặc history.

Các bảng đề xuất: agents (Leta có account_id, Leti không có), boxes, box_edges, messages, runs, activity_log, hitl_requests, schedules, cộng các bảng checkpoint upstream. Inbox là truy vấn messages nhận bởi agent, không chép thêm một bảng inbox tương tự.

UI queries:

| Màn hình | Nguồn đọc |
| --- | --- |
| Inbox | messages theo recipient và nhóm trao đổi |
| Canvas/box | boxes + agents + box_edges; runs và pending HITL để hiển thị trạng thái |
| Lịch | schedules; các mốc tương lai do API lấy từ Temporal matching-times trong khoảng yêu cầu |
| Chat history | messages owner ↔ Leta |
| Nhật ký | messages liên quan + activity_log + runs |
| Agent context inspect | LangGraph checkpoint qua backend, không parse nó thành chat owner |

`activity_log` lưu ghi chú có chủ đích và tool activity; chỉ tham chiếu message đã có, không copy nội dung message thành một bản sự thật thứ hai. Token deltas không ghi mỗi token vào PostgreSQL.

### Luồng engine chung

1. API/tool/source adapter gọi AgentWorkflow.receive qua Update-with-Start.
2. Handler chạy Activity ghi messages, trả xác nhận khi đã lưu rồi đánh dấu có input. Cùng ID được nhận lại thì trả item đã có.
3. Agent idle bắt đầu graph Activity; đang chạy thì input vẫn được tiếp nhận.
4. Trước mỗi model call, middleware đọc messages mới: Leta nhận digest và có list/read inbox; Leti nhận toàn bộ nội dung chờ. Checkpoint giữ vị trí đã đưa vào context.
5. LangGraph gọi model, checkpoint model output, chạy tools rồi lặp. Mỗi agent chỉ có một invocation đang hoạt động; nhiều agent chạy độc lập.
6. Tool runtime chung quản lý send_message, HITL, schedules và Mirage. Final text trở thành note; chỉ send_message tạo message cho người nhận.
7. Kết thúc graph Activity, Workflow chạy tiếp nếu còn input chưa được đưa vào lượt vừa rồi; nếu không thì chờ. Chờ request không giữ graph invocation mở.

Đề xuất giữ Update-with-Start để Temporal điều phối lưu → kích hoạt, không thêm outbox/poller. Trade-off đã nêu: worker cần hoạt động để API xác nhận PostgreSQL đã lưu. Python SDK 1.35.0 đã có API; Openlet Workspace.Mutate đã dùng cùng pattern bằng Go.

Tool gửi owner ghi messages hướng owner và phát UI event. Tool gửi agent/box gọi receive của workflow đích. Đều dùng cùng message model và nhận diện retry theo ID/tool_call_id đã lưu; không có operation/delivery entities.

### Messaging và box

Một tool `send_message(to, content)`. `to` hỗ trợ ID hoặc name tra trong roster được phép. Khi name không rõ thì trả lỗi kèm các ID phù hợp. Không có send_box/send_result riêng.

- Roster Leta gồm owner và các box thuộc Leta; Leta không nhắn từng Leti.
- Roster Leti gồm peer có edge. Representative còn có đích Leta/parent; runtime gửi với nguồn box ID.
- Gửi tới box ID/name được runtime route vào representative. Box một Leti dùng đúng cùng cơ chế.
- Edge là quyền giao tiếp hai chiều, không phải DAG execution. Agent không tự forward final text.
- create_box nhận nguyên graph, name/description/prompts/edges/representative. create và send là hai thao tác.
- Box name và Leti name unique trong Leta. Không lưu slug; tính slug(name). Tạo box kiểm tra derived path chưa trùng. MVP không rename box nên không có bài toán di chuyển home khi đổi name.
- Canvas đọc cấu hình và trạng thái từ PostgreSQL, có badges lịch/HITL; MVP chỉ create/delete nguyên box.
- Delete dừng nhận input mới, hủy lịch và pending request, dừng agent rồi trash home; giữ history. Late input không làm box sống lại.

### HITL: đúng hai loại request

**Lịch sử thiết kế:** phần tool approval/auto-execute call dưới đây đã bị thay thế bởi resource access ở lượt 21:18, xem cuối checkpoint. Không khôi phục policy chặn dangerous tools hoặc test_approval từ phần này.

Hai type là approval và ask_user. Đề xuất `ask_user` của Leta/Leti hướng owner qua app; Leti không có chat tool tới owner. Card ghi rõ box/Leti. Hỏi parent dùng send_message theo representative routing. Structured HITL không tạo quyền chat owner trực tiếp cho Leti.

Đề xuất mới theo phản hồi user: agent gọi tool bình thường; runtime validate arguments và permission, đánh giá approval policy được cấu hình trong code/runtime theo tool và arguments. Không dựa vào model tự biết nguy hiểm. Không đủ permission thì trả forbidden, approval không mở rộng quyền. Được phép nhưng cần duyệt thì tạo request trước effect. Không expose request_approval như yêu cầu bắt buộc cho model.

Request approval do runtime tạo, không phải payload model phải tự soạn:

```json
{
  "id": "hitl-42",
  "type": "approval",
  "status": "pending",
  "agent_id": "leti-research",
  "tool_call_id": "call-17",
  "title": "Ghi báo cáo vào shared",
  "action": {
    "tool": "write_file",
    "arguments": {"path": "/shared/report.md", "content": "# Báo cáo\n..."}
  },
  "expires_at": "2026-11-08T03:00:00Z",
  "response": null
}
```

Runtime gắn request ID và agent từ identity đang chạy. Tool runtime trả ToolMessage `approval_pending` cùng request ID, hoàn tất protocol của call nhưng chưa thực hiện action. Không giữ unresolved tool call trong working message list. Agent biết phải chờ kết quả cho phần phụ thuộc, vẫn xử lý input/việc độc lập trong cùng LangGraph thread. Không dùng native whole-thread interrupt làm cơ chế chờ approval trong engine này.

Owner submit `{"decision":"accept"}` hoặc `{"decision":"deny","comment":"..."}`. Accept thì HITL workflow thực thi đúng tool/args đã giữ rồi đưa kết quả vào inbox requester. Deny không thực thi, chỉ đưa quyết định vào inbox. Expire/cancel cũng vậy. Quyết định có hiệu lực không phụ thuộc một lượt model gọi lại. Approval và execution progress/result cùng gắn một request, không thêm action/operation object. Một request approval gắn một call; một business tool có thể tự thực hiện các bước nội bộ của nó. Chưa thêm batch-of-arbitrary-tools.

Lý do: không bắt model tái tạo args hay gọi execute_approved, không chặn cả agent đang chờ. Runtime vẫn kiểm tra permission/mount hiện hành khi thực hiện. Decision chỉ dùng cho đúng call đang giữ, do server xác thực; model không thể truyền `approved=true` để bypass. Retry dùng tool_call_id đã checkpoint và request cũ; side effect vẫn cần idempotency/precondition API đích, không hứa exactly-once cho arbitrary shell.

Policy phải bao phủ các đường vào cùng effect: không chỉ chặn write_file rồi cho shell/Python ghi tự do vào cùng mount. Phương án MVP ít phức tạp: shell/Monty làm việc trên home được phép như thường; nếu cấp ghi vào vùng có yêu cầu approval, gate cả invocation và thực thi nguyên invocation sau accept, hoặc cấu hình vùng đó readonly với shell/Monty và dùng file tool có gate. Chưa chốt bảng policy nào là always/conditional approval, không tự coi mọi write là dangerous. Không thiết kế suspend/resume từng syscall giữa shell command.

Đối chiếu [LangChain HITL](https://docs.langchain.com/oss/python/langchain/human-in-the-loop) kiểm tra `interrupt_on` trước tool và [OpenAI Agents HITL](https://openai.github.io/openai-agents-python/human_in_the_loop/) dùng `needs_approval`, kể cả nested agent tools. Openlet tái sử dụng hướng runtime policy, thay cách chờ cả run bằng request độc lập + inbox để đáp ứng always-on agent. Chưa chạy engine mới trong lab.

Lifecycle chung: `pending -> resolved | cancelled | expired`. `resolved` lưu `response.decision=accept|deny` cho approval hoặc `response.answers` cho ask_user. Execution result nằm riêng trong request; request đã được duyệt vẫn resolved nếu action thực thi bị lỗi. Timer và owner response tranh cùng pending record, server deadline quyết định; update có điều kiện bảo đảm chỉ một terminal outcome. Response đến sau cancel/expire trả trạng thái hiện có, không đánh thức action cũ.

Ask_user payload đề xuất:

```json
{
  "type": "ask_user",
  "title": "Thông tin cho báo cáo",
  "questions": [
    {"id": "market", "text": "Thị trường nào?", "type": "single_choice", "options": [{"id": "vn", "label": "Việt Nam"}, {"id": "us", "label": "Mỹ"}]},
    {"id": "metrics", "text": "Chỉ số nào?", "type": "multiple_choice", "options": [{"id": "price", "label": "Giá"}, {"id": "volume", "label": "Khối lượng"}]},
    {"id": "notes", "text": "Yêu cầu bổ sung?", "type": "text", "required": false}
  ],
  "expires_at": "2026-11-08T03:00:00Z"
}
```

Theo thay đổi mới nhất của user, bỏ Other. Answer single: `{"option_id":null,"note":"Tôi chưa chọn, cần thêm dữ liệu"}`; tối đa một option, được để null. Answer multiple: `{"option_ids":[],"note":"Tạm chưa chọn chỉ số nào"}`; được để mảng rỗng, có thể chọn nhiều option. Note có thể rỗng; không tự bắt chọn ít nhất một option hoặc phải nhập note. Text answer chỉ `{"text":"..."}`, không thêm note. Response là map answers theo question ID, submit cả form; submit câu choice rỗng vẫn là câu trả lời hợp lệ, khác request chưa được submit. Backend validate option IDs, loại và số lượng lựa chọn, lưu một lần rồi giao answers vào inbox requester. Không tự thực hiện action cho ask_user.

Tools: ask_user, list/get/cancel requests; approval tự sinh ở tool runtime. Deadline theo server; request đã có quyết định/hủy/hết hạn không nhận đáp án mới.

### Graph execution: phạm vi engine

Đề xuất giữ engine chạy agent độc lập. Box graph là communication graph, không phải DAG. Chuyển sang Dify/n8n sẽ thêm node loại trigger/action/branch/join, data edges và execution semantics không tương ứng edge vô hướng user đã định nghĩa. Các hệ đó phù hợp pipeline khai báo bước chạy, không đem lại lợi ích cần thiết cho MVP này.

Phần general cần có ngay là ingress item chung, tool runtime/policy, vòng thực thi mỗi agent và routing kiểm tra edge. Message, schedule và external adapter đều vào receive, có envelope/payload riêng ở biên. Source-specific parse/auth không ở vòng LangGraph. Lịch gắn vào agent và hiện badge/chi tiết trên canvas, không thêm scheduler node. Canvas đọc PostgreSQL; trạng thái hoạt động từ runs/HITL. Không thêm generic node plugin framework.

### Engine chi tiết: baseline tạm đã được user chốt

**Đơn vị thực thi.** Mỗi Leta/Leti có một AgentWorkflow cùng implementation, một LangGraph thread_id ổn định theo agent ID và nhiều runs nối tiếp. Một run là một lần graph xử lý đến khi kết thúc lượt, không phải một đầu việc hay một cuộc chat. Các agent chạy song song; một agent chỉ có một graph writer. Box graph ở PostgreSQL chỉ quy định roster/routing, không được compile thành LangGraph chứa tất cả Leti. Graph bên trong mỗi agent là vòng collect_inbox -> model -> tools -> collect_inbox, hoặc model -> kết thúc/note.

**Envelope chung.** Đề xuất các trường nghiệp vụ: id, seq, recipient, source={type,id,label}, conversation_key nullable, reply_to nullable, content, data JSON, created_at; read_at cho việc Leta chủ động đọc chi tiết. `source.type` là chuỗi được adapter validate, không enum ba nguồn trong engine. Source mô tả nguồn phát; reply_to mới là địa chỉ được phản hồi. Schedule/HITL event không tự được đối xử như chat message chỉ vì cùng nằm trong inbox. conversation_key là khóa nhóm owner/Leta hoặc box, không thêm lifecycle đóng thread. seq là số thứ tự để phân trang/steering/UI, không thêm operation/delivery entity.

**Nhận input.** API/tool/adapter gọi AgentWorkflow.receive bằng Update-with-Start. Handler kiểm tra agent còn hoạt động, chạy Activity lưu message vào PostgreSQL, cập nhật latest_seq rồi mới xác nhận message đã lưu. Cùng message ID retry trả cùng item, khác payload thì conflict. Các receive cùng agent tuần tự hóa phần ghi ngắn này để sequence không vượt qua một transaction chưa commit; không khóa graph Activity đang chạy. Source parse/auth và render human-readable content nằm ở adapter, engine chỉ nhận envelope đã validate. Hệ quả đã chấp nhận trong đề xuất: worker không hoạt động thì API chưa thể xác nhận input đã lưu PostgreSQL; Temporal đã nhận command không đồng nghĩa UI được báo message persisted. Không có PG-write-then-best-effort-signal/outbox/poller.

**Workflow loop.** Temporal chỉ giữ latest_seq, run đang chờ Activity và vị trí graph đã nhận; không copy message bodies. Pseudocode mô tả trách nhiệm, không phải code SDK copy/paste:

```text
receive(item):
    saved = await persist_inbox(item)       # Activity, short transaction
    latest_seq = max(latest_seq, saved.seq)
    return saved

run():
    while agent còn hoạt động:
        await có latest_seq > graph_cursor
        result = await run_agent(agent_id, run_id)  # Activity
        graph_cursor = max(graph_cursor, result.inbox_cursor)
```

Receive handler vẫn chạy trong lúc run() đang await graph Activity. Không reset một wake flag lúc Activity kết thúc: latest_seq được so với cursor trả về nên tin tới giữa lúc kết thúc lượt không bị mất. Continue-As-New chỉ khi không có Activity/handler đang dở; giữ ID agent/thread và các counters cần thiết, không mang toàn bộ inbox/history.

Bootstrap/restart đọc latest inbox sequence từ PostgreSQL và cursor/run checkpoint hiện có qua Activity; cập nhật max với các receive đã tới trong lúc bootstrap, không ghi đè bằng snapshot cũ. Đây là khôi phục lúc start, không phải một reconciliation poller chạy nền.

**LangGraph boundary.** collect_inbox query seq > inbox_cursor, gom snapshot input, trả đồng thời phần thêm vào working messages và cursor mới rồi checkpoint sync trước model. Với Leta, phần thêm là digest nhóm theo conversation/source, kèm ID/count/preview ngắn; detail còn trong PostgreSQL, list/read inbox tools lấy khi cần. Với Leti, đưa toàn bộ nội dung pending vào working messages, không expose inbox tool. Model output/tool_call_id checkpoint sync trước tools. Tools results checkpoint rồi quay lại collect_inbox trước model tiếp theo. Tin commit sau snapshot, giữa model call hoặc tool call sẽ vào boundary kế tiếp; không sửa input của model call đang streaming. Các tool calls của một model response có thể chạy theo policy runtime, nhưng không chèn một user message vào giữa unresolved tool-call protocol.

**Đã thông báo/đã đọc.** Inbox cursor trong LangGraph nghĩa item đã được đưa vào steering/context bền vững. Leta read_inbox đánh dấu read_at sau khi lấy chi tiết; đọc lại ID vẫn trả nội dung kể cả đã đọc. Không thêm generic processed/closed status vì không có task model để biết một item nghiệp vụ đã hoàn thành. Với Leti, cursor đồng nghĩa runtime đã giao nội dung, không có thao tác agent đánh dấu đọc. UI có thể hiển thị đã vào inbox, đã thông báo, đã đọc từ những dữ liệu đó; không tự suy ra hoàn thành công việc.

**Tool runtime và routing.** Một send_message(to,content) resolve ID/name chỉ trong roster được phép. Leta -> box ID route vào representative. Peer Leti -> Leti kiểm tra edge hai chiều. Representative -> Leta đặt source/reply route là box ID; Leti khác muốn gửi về Leta thì nhờ representative. Gửi tool trả sau khi inbox đích đã lưu, không đợi người nhận chạy xong; vì thế hai agent nhắn qua lại không giữ call chờ run của nhau. Tin gửi owner lưu messages cho UI, không start một owner workflow. Message ID được giữ ổn định theo call đã checkpoint để receiver dedup retry. Các tool thực hiện effect qua cùng validation/permission/approval gate; filesystem chỉ đi Mirage -> LetFS.

**HITL và việc khác (đã cập nhật).** request_access hoặc ask_user tạo hitl_requests + request workflow độc lập. Tool trả pending để đóng protocol của call; graph không bị interrupt chờ owner. Request workflow chờ response/timeout; approval accept cấp scope access cho Leta, ask_user giao answers, đều qua receive về đúng requester. Không giữ/chạy lại tool call cũ. Nếu agent đang chạy việc khác, kết quả HITL vào steering kế tiếp. Nếu agent rảnh, kết quả bắt đầu run mới trên cùng thread; không khôi phục stack Python hoặc giữ graph invocation đang chờ. Agent tự chọn tiếp tục đầu việc bằng context/request ID, chưa có deterministic task DAG.

**Box lifecycle.** Create validate tên, derived home path collision, ít nhất một Leti, representative và edge endpoints; save nguyên config bằng transaction rồi start AgentWorkflows qua Temporal. Creation có thể thể hiện initializing cho UI cho tới khi khởi tạo xong; retry dùng cùng box/agent IDs. Send work là thao tác riêng. Delete trước hết chặn input mới trên box record, hủy schedules/pending HITL và dừng agents; đợi activity dừng trước khi trash home. Inbox chưa xử lý giữ trong history của box đã xóa, không chuyển sang agent khác; late response/input không được Update-with-Start làm box sống lại. Không xóa audit/history cùng runtime.

**Retry khớp hai lớp.** run_agent dùng runs.id có sẵn và graph metadata run_id. Activity retry đọc runs: có final result thì trả lại; chưa có thì load checkpoint cùng thread. Snapshot thuộc cùng run thì tiếp tục pending nodes, không thêm input như một run mới. Model step chưa checkpoint có thể gọi lại; model step đã checkpoint giữ đúng tool_call_id. send_message/HITL effects dựa call/message/request identity đã lưu để không nhân đôi. Tool backend vẫn phải thực hiện idempotency/precondition đúng contract, checkpoint sync không tự tạo exactly-once cho arbitrary shell. Lab đã có chọn recovery input ở worker.py:choose_input, run metadata và PostgreSQL advisory lock cho một checkpoint writer; cần tái dùng phần hữu ích thay vì tự chế leasing/fencing. Openlet thay durability async bằng sync, PG inbox thay Temporal inbox, và bỏ nhánh whole-agent waiting_approval của lab.

**Đường UI.** API đọc messages/boxes/agents/box_edges/runs/hitl_requests/schedules/activity_log từ PostgreSQL. Worker phát AG-UI text/tool/run events vào Redis, API proxy SSE. App events cho message/HITL/lịch chỉ tham chiếu records đã lưu; final model text là note hoạt động, không phải owner reply. Reconnect lấy snapshot/history PostgreSQL rồi theo Redis cursor còn hiệu lực; không dựng inbox/canvas từ checkpoint hoặc Temporal history. Không lưu mỗi token vào PostgreSQL.

**Luồng chuẩn.** Owner gửi việc -> Leta send_message(box) -> representative/peer làm việc -> Leti ask_user(owner) -> request pending, Leti/Leta vẫn nhận input -> lịch khác vào inbox Leta -> Leta send_message(owner) nhắc việc -> owner submit form -> request workflow receive answers vào Leti đã hỏi -> Leti tiếp tục -> peer/representative gửi kết quả dưới box ID -> Leta send_message(owner). Owner thấy card ghi requester thật nhưng Leti không có chat route tới owner.

**Thêm nguồn mới.** Adapter webhook mới về sau xác thực payload, resolve agent và xây envelope/source/reply_to phù hợp rồi gọi receive; không thêm nhánh trong Workflow loop hoặc node model. Nếu kênh mới hỗ trợ trả lời ra ngoài thì bổ sung adapter gửi ở messaging boundary, không lẫn channel HTTP SDK vào LangGraph hay Temporal orchestration. Đây là kiểm tra khả năng mở rộng, không triển khai connector ở MVP.

### Scheduler/calendar trong cùng engine

Thuật ngữ đề xuất cuối: UI **Lịch**; model/API/tool **schedule**. Reminder là mục đích/nội dung một schedule, calendar là cách xem các schedule theo thời gian. Một hệ thống, không hai schema hoặc hai scheduler.

UI có trải nghiệm giống phần lịch ngày/tuần/tháng của Google Calendar: xem các mốc, mở chi tiết, sửa/xóa, chọn recurrence và agent đích. Chưa phải đầy đủ Google Calendar với meeting attendees, invitation, calendar sync hay exceptions từng occurrence.

**Khảo sát thực tế bổ sung.** [OpenClaw schedule types](https://docs.openclaw.ai/automation/cron-jobs/schedules) có at (absolute/relative), every (fixed duration), cron (calendar expression); bản hiện tại còn có event-trigger types nhưng không đưa chúng vào MVP này. [APScheduler 3.x](https://apscheduler.readthedocs.io/en/3.x/userguide.html) phân biệt date/interval/cron; [IntervalTrigger](https://apscheduler.readthedocs.io/en/3.x/modules/triggers/interval.html) hỗ trợ seconds/minutes/hours/days/weeks và [CalendarIntervalTrigger](https://apscheduler.readthedocs.io/en/3.x/modules/triggers/calendarinterval.html) có months/years theo calendar. [n8n Schedule Trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.scheduletrigger/) có seconds tới months và custom cron. Đây là tham khảo representation, không thêm những scheduler đó vào Openlet.

**Model thay thế daily/weekly.** schedules gồm id, agent_id, title, content, spec JSONB (tagged union), paused và timestamps. Ba dạng spec: at, interval, calendar. Không hardcode daily/weekly/monthly thành engine variants; chúng là presets của UI/tool input.

**Mốc chạy/kết thúc.** at nhận timestamp cụ thể, chẳng hạn `{"type":"at","at":"2026-11-08T09:00:00+07:00"}`. Với interval/calendar, thêm end_at tùy chọn, map thẳng ScheduleSpec.end_at đã kiểm tra trong SDK 1.35.0; các mốc sau end_at bị bỏ qua. End_at không hủy run đang chạy hoặc inbox item đã được tạo. Đây là contract thiết kế, chưa có scheduler production code.

| Nhu cầu | Spec |
| --- | --- |
| 5 giây nữa nhắc | Tool input at + after_seconds=5, normalize một lần thành timestamp |
| 1 giờ nữa nhắc | at + after_seconds=3600 |
| Ngày mai 09:00 | at + timestamp có timezone rõ |
| Mỗi giờ tính từ mốc đã chọn | interval, every_seconds=3600, anchor_at |
| Mỗi 5 ngày, thời lượng 120 giờ | interval, every_seconds=432000, anchor_at |
| Ngày 1 mỗi tháng lúc 09:00 | calendar, day_of_month=[1], hour=[9], minute=[0], second=[0], timezone |
| 08:00 thứ Hai và thứ Sáu | calendar, day_of_week=[1,5], hour=[8], minute=[0], second=[0], timezone |

At input chỉ nhận đúng một trong at/after_seconds. Normalize timestamp ở lần tạo đầu và lưu lại; retry cùng call không tính lại now+duration. Với native CalendarSpec độ phân giải giây, relative deadline làm tròn lên giây để không sớm hơn thời lượng yêu cầu. at/interval/calendar là ba nghĩa thời gian, không phải ba hệ thống.

Calendar example: `{"type":"calendar","timezone":"Asia/Ho_Chi_Minh","fields":{"day_of_month":[1],"hour":[9],"minute":[0],"second":[0]}}`. Các field calendar dùng semantics/ranges của Temporal ScheduleCalendarSpec, có thể chỉ định month/year/day_of_week; không viết parser RRULE mới. Nếu nhận cron shorthand thì chuyển qua native Temporal cron_expressions thay vì dùng một thư viện khác để preview. Không khẳng định hỗ trợ mọi RRULE.

**Compiler sang Temporal 1.35.0.** at -> ScheduleCalendarSpec có đầy đủ year/month/day/hour/minute/second UTC và ScheduleState(limited_actions=True, remaining_actions=1). interval -> ScheduleIntervalSpec(every,offset), với offset tính từ anchor timestamp modulo interval; chỉ đặt ScheduleSpec.start_at mà không offset sẽ bị align Unix epoch, không đúng "mỗi N giờ tính từ lúc đặt". calendar -> ScheduleCalendarSpec + time_zone_name. ID schedule dùng luôn cho Temporal schedule ID, không thêm delivery/operation ID. Ba dạng đều chạy cùng ScheduleActionStartWorkflow của delivery workflow ngắn -> receive; không thêm APScheduler/process/queue riêng.

Tài liệu [Temporal Schedule hiện tại](https://docs.temporal.io/schedule) khuyến nghị Start Delay cho one-off workflow; [Timers and Start Delays](https://docs.temporal.io/workflow-execution/timers-delays) giải thích Update/Update-with-Start có thể bypass start delay. SDK 1.35.0 thực sự có start_delay trên start_workflow, nhưng đây là alternative, không bắt buộc đổi cách đã đề xuất. MVP nghiêng giữ one-action Schedule cho at để CRUD/pause/preview dùng cùng đường với recurring; giá là một native schedule resource cho một reminder. Đã kiểm tra CalendarSpec year và limited_actions/remaining_actions trong source 1.35.0; vẫn cần lab round trip tạo/sửa/xóa/đến hạn, không gọi source support là runtime verification.

**Semantics.** Interval là fixed duration, không quy tháng thành 30 ngày. Calendar là wall-clock; hằng tháng ngày 31 bỏ qua tháng không có ngày 31 theo native semantics, không tự chuyển thành cuối tháng. "Mỗi 5 ngày" không được encode thành cron day_of_month=*/5 vì nó reset qua tháng. UI preview phải thể hiện chính lịch đã lưu. 5 giây nữa là thời điểm input đến hạn; actual inbox/LLM/reply còn phụ thuộc queue và model latency, không là hard real-time guarantee. Nếu provisioning xong mà at đã quá hạn, delivery một lần ngay với scheduled_at gốc thay vì tạo lịch không bao giờ match.

FE không truy cập Temporal: GET schedules đọc definition từ PostgreSQL, GET occurrences(from,to) trả các mốc start_at/title/target_agent/schedule_id để render ngày/tuần/tháng. at có timestamp sẵn; recurring preview gọi `Client.workflow_service.list_schedule_matching_times` với `ListScheduleMatchingTimesRequest(namespace,schedule_id,start_time,end_time)` trong khoảng hữu hạn. Method/types đã kiểm tra trong source SDK 1.35.0, không bịa method ScheduleHandle. History đã chạy lấy từ scheduled_at trên inbox/run, không coi matching-times là lịch sử thực thi. Nếu Temporal unavailable, vẫn đọc được definitions trong PostgreSQL; recurrence preview phụ thuộc Temporal theo phương án này. Không materialize vô hạn occurrence rows.

Quyết định hiện hành: BUFFER_ONE áp dụng cho delivery workflows; giữ tối đa một start chờ trong khi delivery trước chưa hoàn tất, không giữ mọi mốc bị chồng. Agent vẫn chạy tuần tự; delivery kết thúc ngay sau khi input đã vào inbox. Worker trở lại có thể giao trễ kèm giờ hẹn gốc; Temporal server outage có catchup_window riêng theo mặc định server. Không diễn giải BUFFER_ONE thành latest-only hoặc bù đủ mọi occurrence.

Tools create/list/update/delete_schedule; update gồm pause/resume. Lịch/signal hiển thị gắn với agent trên canvas. API mutation được Temporal điều phối, cập nhật product record và native resource bằng cùng schedule ID, retry theo command đã có. Delivery kiểm tra agent/box/schedule vẫn hoạt động trước khi đưa vào inbox. dateutil RRULE chỉ tính recurrence, không đánh thức worker; không cần thêm dependency chỉ để biểu diễn những lịch native Temporal đã làm được.

### LetFS redesign cho agent filesystem

User cho phép thiết kế lại, chưa triển khai. Đề xuất giữ filesystem/scope/nodes/quota/trash/artifact pipeline và authz hiện có; thiết kế lại API nội dung và text storage để backend đáp ứng Mirage.

Correction đã xác minh: `FilesystemClient.resolve_node(path)` trả đầy đủ Node trong một RPC. Stat không cần ResolveNode rồi GetNode. Backend ListNodes đã nhận Locator, nhưng Python wrapper còn chỉ nhận parent_id. GetDownload hiện còn ID-based. Đây là thiếu ở wrapper/read-content contract, không phải toàn hệ thống thiếu path resolution.

Quy tắc agent view:

- Editable text dùng inline UTF-8 content trong PostgreSQL.
- Original blob trả metadata, processing state và **artifact tree**: node con có kind/name/path/readonly, thư mục chứa children. Không SignedURL/object_key, không raw bytes. Mirage stat và read phải cùng metadata representation; original blob size nằm trong metadata, không dùng làm size của file view JSON.
- Parsed markdown/text artifacts readable và readonly. Image đọc bằng read_file qua image artifact/preview, kết quả multimodal; shell/Monty không được đọc image/blob raw bytes.
- Ảnh gốc có thể được read_file chọn preview artifact; nếu chưa có thì trả processing state. Không âm thầm tải blob gốc trong adapter.
- Mount giữ đúng các root đã chốt. Backend VFS queries nhận root đã cấp và enforce subtree; scope auth vẫn thực hiện ở LetFS.

Đề xuất storage text: thay inline byte payload của text bằng `text_content TEXT` làm nguồn duy nhất cho text; blob vẫn object storage. Không tự chuyển text thành blob chỉ vì vượt inline threshold cũ, nếu agent cần đọc nó. Giữ quota và giới hạn kích thước có chủ đích. Bổ sung newline_count/checksum phục vụ metadata hooks. Binary luôn đi blob/preview path, không cố decode thành text.

Thêm pg_trgm GIN index cho contains/ILIKE trên text_content. Index này phục vụ exact text/substring, không dùng similarity operator làm grep và không dùng vector top-k. Chi phí là index space và write cost; không thêm search service. Pattern quá ngắn có thể vẫn scan. User đã đồng ý API redesign; migration hiện chưa có pg_trgm. Kết quả benchmark riêng được bổ sung bên dưới, không khẳng định planner tự chọn index cho mọi query.

API đề xuất (tên chưa phải contract đã triển khai):

| API | Contract |
| --- | --- |
| Stat(Locator) | Metadata một lần theo path hoặc ID, storage/readonly/representation/artifact info |
| ListNodes(Locator,cursor) | Metadata của con; SDK path đầy đủ |
| ReadTree(root,limit) | Một recursive query trả paths + metadata; báo incomplete khi quá giới hạn |
| ReadText(Locator,selection) | Byte range, line range, head/tail; trả metadata/fingerprint cùng đoạn để không preflight stat |
| TextSearch(root,text,options) | Files hoặc matching lines, line numbers/context khi được yêu cầu; đủ pagination, không top-k |
| WriteText/AppendText/PatchText/TruncateText | Thao tác inline text tại backend, không download/merge/upload ở worker |
| Copy/Move/Trash theo Locator | Native backend, tôn trọng readonly/blob policy |
| ReadArtifactImage(Locator) | Image artifact/preview cho multimodal tool, không mở raw blob endpoint |

Artifact paths cần ánh xạ thành cây hợp lệ của Mirage vì LetFS hiện có artifact con dưới node file. Đề xuất namespace readonly `.artifacts/<source-id>/...` bên trong mỗi mount, được adapter dựng từ artifact tree hiện có; không copy dữ liệu. Original blob path là metadata view. Chốt namespace cụ thể khi thiết kế contract, không hứa Mirage tự hỗ trợ file-as-directory.

Text mutations cập nhật content, node metadata/quota và text index cùng transaction, dùng precondition/idempotency có sẵn. VFS endpoint phải từ chối sửa payload blob; không tái dùng ReplaceContent để âm thầm biến object thành inline. API tải blob cho owner vẫn riêng, không cấp cho engine tool credential.

ReadText/TextSearch xử lý ở LetFS/PostgreSQL và chỉ gửi phần kết quả về worker. Line extraction vẫn có thể phải quét nội dung tại backend; pg_trgm giúp lọc file trên corpus chứ không làm mọi phép đọc thành O(1). Chưa cần file_lines/chunk index mới chỉ để làm head/tail.

### Toàn bộ hook Mirage liên quan

Đã đối chiếu docs integration và BaseVFS v0.0.8. Override dùng đúng extension points, không fork parser.

| Hook/capability | Backend đề xuất |
| --- | --- |
| stat/readdir | Stat/ListNodes theo Locator |
| read + reads_ranges=True | ReadText byte range; blob trả metadata view |
| read_tree | ReadTree bulk paths/metadata |
| files_containing | TextSearch files, complete/superset candidates |
| lines_containing | TextSearch lines giữ byte/newline order |
| first_lines/last_lines | ReadText head/tail selectors |
| line_count | newline_count, đúng nghĩa wc -l |
| follow | Poll revision và đọc phần thay đổi qua API; không thêm changefeed service |
| checksum | Hash đúng bytes của representation đang đọc |
| search/search_many | SemanticSearch scoped, map hit sang readable artifact path |
| write/append/pwrite/truncate | Backend text mutations; giữ conditional writes |
| copy/dir_copy/rename/unlink/rmdir/rm_r | Native node operations thay từng file fallback |
| _replace + condition_support | Ánh xạ điều kiện Mirage vào expected node/revision có sẵn |
| custom @vfs_call read_image | Qua session dispatcher, gọi ReadArtifactImage; tool read_file dựng image block |
| vfs_md | Mô tả mounts, readonly artifacts/blob metadata và khả năng tool thực tế |

Mirage 0.0.8 vẫn có giới hạn pushdown: `grep -n/-C` phải đọc nội dung file đã lọc để giữ vị trí/context; `-v` và một số flags không gọi search hook. Không quảng cáo API mới làm mọi câu grep pushdown hoàn toàn. Endpoint TextSearch có thể trả line/context trực tiếp qua search_text operation nếu cần; không tự fork grep ngay.

### Pattern search đã đối chiếu thêm ở release 0.0.8

- Có grep/rg regex, find -name/-iname/-path và shell glob. Nguồn tag v0.0.8: `python/mirage/commands/builtin/generic/{grep,rg,find}.py`, `workspace/expand/globs.py`, `utils/glob_walk.py`.
- `BaseVFS.files_containing` nhận plain text every match contains, **không nhận regex**; Mirage trích literal thích hợp rồi tự match regex. `lines_containing` tương tự, chỉ trả các dòng có thể match, giữ bytes/newlines/order.
- `BaseVFS.read_tree` phục vụ find/grep/rg/ls-R/tree bằng bulk metadata; không cần đọc body chỉ để tìm tên. Glob có thể đi qua `readdir` với `PathSpec.pattern`. Hook `readdir` lọc theo pattern phải trả `DirListing(partial=True)` đúng thư viện; có thể dùng safe prefix ở backend, để Mirage match chính xác.
- LetFS SearchFiles hiện chỉ name/title substring ở `apps/letfs/internal/filesystem/search.go:172`, không có content search hoặc đầy đủ glob semantics. Vì vậy bổ sung TextSearch và bulk tree, hỗ trợ name/prefix filter khi đi qua ListNodes là thay đổi backend thực sự cần. Không gắn semantic search vào grep. Không tạo parser regex Bash trong LetFS để lặp chức năng Mirage.
- Chấp nhận các flag/pattern khiến Mirage fallback; cung cấp hooks đầy đủ để thực hiện tối đa khả năng v0.0.8, không fork Mirage hoặc ép mọi regex sang PostgreSQL.

`files_containing` phải trả đủ hoặc superset; nếu không lấy đủ pagination thì decline, không trả partial như đầy đủ. Semantic search hiện có không đáp ứng yêu cầu này. `lines_containing` giữ nguyên newline, không dùng splitlines rồi nối làm đổi bytes. Khi matching/case semantics không tương thích, trả tập rộng hơn hoặc fallback đúng semantics.

### Redis cache và workspace lifetime

Đề xuất dùng Redis cache, được Mirage 0.0.8 hỗ trợ trực tiếp bằng RedisCacheConfig; RedisIndexConfig cho metadata nếu cần. Không phải dựng RedisVFS làm dữ liệu chính.

- workspace_id ổn định theo agent, namespace không trộn các mount/root khác nhau. Rebuild Python object theo invocation nhưng cache tồn tại trong Redis.
- `caches_reads=True`, ReadPolicy.FRESH; FileStat.fingerprint và record của read dùng cùng token từ node identity/revision hiện có. Source thật dùng mirage.observe.context.record(...fingerprint=...), không bịa API stamp.
- Cache read phải revalidate và check access trước trả; cache không là nguồn quyền. Listing FRESH với ListingVersion.NONE relist theo command/trust window; không giả định Redis tự invalidates external writers.
- Writes qua Mirage invalidate cache của workspace như thư viện hỗ trợ. Worker khác/backend writer được phát hiện bằng fresh validation; không thêm invalidation bus.
- Redis cache limit ở SDK không tự eviction. Có thể dùng cùng Redis cho stream và cache vì cả hai đều dữ liệu tạm, namespace/TTL riêng và server có memory bound; khi stream bị eviction/mất cursor, client phải lấy lại snapshot/history từ PostgreSQL. Không hứa replay đủ mọi token sau eviction và không cần thêm Redis instance ngay. Cấu hình eviction cụ thể chốt cùng stream reconnect contract.
- Một workspace/session object mỗi invocation, session.vfs và session.shell dùng chung mount/cache/policy trong lượt; đóng khi hết. Cache không phải lý do giữ process/session sống nhiều ngày.

Monty dùng đúng filesystem view này. Không tự có host FS/network/third-party packages. Mirage 0.0.8 pin Monty 1.4.0; callback Monty hiện whole-file, có thể tối ưu shell/direct API nhưng không hứa mọi Python read dùng range.

### Permission cho member tạo Leta

Không tách Leta khỏi workspace member. Thêm quyền `workspace.create_agent = owner + admin + member`, khác manage_members. Chỉ human account active member được dùng create-Leta flow.

Workspace membership boundary chỉ cho nhánh này thêm account type=agent do caller sở hữu, fixed role=member và chưa thuộc workspace khác; vẫn chạy cơ chế tạo personal scope của member. Caller không được dùng quyền này thêm người khác, thêm agent người khác hoặc tự cấp admin. AddAccount chung cho các trường hợp khác giữ manage_members.

Leta mặc định member, shared scope theo role đó; Leti bị thu hẹp thêm bởi mount/tools. Owner có viewer grant cho Leta personal scope và quyền quản lý resources thuộc Leta; không mount owner personal scope. Owner rời workspace cần thu hồi hoạt động/access của Leta thuộc đó. Đây là đề xuất policy rõ, chưa sửa schema.zed.

### Vì sao durability sync

Graph async/AsyncPostgresSaver và durability policy là hai lựa chọn khác nhau. Ở LangGraph 1.2.19, async cho step sau chạy trong khi checkpoint step trước đang ghi; sync await checkpoint rồi mới sang step sau (source Pregel.astream).

Với model → send_message tool, sync làm model output/tool_call_id bền trước khi gửi; retry có cùng call để nhận diện. Async có thể gửi trước khi checkpoint output model xong, crash khiến model chạy lại sinh call ID khác. Temporal không nhìn thấy ranh giới model/tool bên trong whole-graph Activity.

Sync vẫn dùng await và streaming; không chặn event loop. Giá là đợi một checkpoint DB mỗi step, cần đo latency thực tế. Nó không tự bảo đảm exactly-once cho effect đã chạy nhưng tool-result chưa checkpoint; receiver/backend vẫn dùng ID/precondition hiện có. Alternative async phù hợp khi effect được durable riêng, nhưng thêm sự phối hợp không cần thiết cho engine MVP này.

## Luồng xuyên suốt của engine

Owner gửi → message trong PostgreSQL → AgentWorkflow Leta → graph middleware/model → send_message(box ID/name) → receive representative → peer theo edge → Leti ask_user hoặc gọi tool bị runtime giữ để approval → request workflow chờ độc lập → lịch khác receive Leta và Leta nhắc owner → owner submit form/approval → ask_user đưa answers vào inbox, approval thực thi call rồi đưa result/denial vào inbox → Leti tiếp tục → send_message về representative → send_message về Leta mang box identity → Leta send_message(owner). Final notes và tool activity đi activity_log; UI read PostgreSQL và theo dõi Redis SSE.

## Benchmark pg_trgm theo yêu cầu ngày 2026-11-07

Script: [benchmark-261107-1919-letfs-trigram.py](benchmark-261107-1919-letfs-trigram.py). Kết quả đầy đủ gồm EXPLAIN JSON: [benchmark-261107-leta-trigram-results.json](benchmark-261107-leta-trigram-results.json).

Chạy PostgreSQL 18.6 đúng image/digest của benchmark project, pg_trgm 1.6, container riêng `--network none`, không publish port, 2 CPU, 1536 MiB limit, shared_buffers 128 MiB, PGDATA tmpfs. Dữ liệu tổng hợp hoàn toàn, seed 20261107; không đọc DB Openlet/blob hay dữ liệu người dùng. Một warmup, median 5 EXPLAIN ANALYZE samples, warm single-client. Đây là relation/index sizes, không phải yêu cầu resident RAM production. Không đo query root/scope join hoặc writes cạnh tranh.

| Corpus | Số file × kích thước | Text logical | Table gồm TOAST | GIN | GIN / logical text |
| --- | --- | --- | --- | --- | --- |
| Từ vựng tài liệu tổng hợp | 4096 × 8 KiB | 32 MiB | 16.47 MiB | 5.13 MiB | 16.0% |
| Từ vựng tài liệu tổng hợp | 512 × 64 KiB | 32 MiB | 10.91 MiB | 0.67 MiB | 2.1% |
| JSON log với chuỗi hex ngẫu nhiên | 4096 × 8 KiB | 32 MiB | 33.73 MiB | 45.98 MiB | 143.7% |

Tài liệu dùng một tập từ hữu hạn lặp lại, không phải corpus production representative cho mọi loại văn bản. GIN lưu posting theo trigram/file nên hai corpus có cùng tổng bytes không có cùng index size. Original blobs không được index; artifact text được index vẫn tính vào tổng text. Không suy ra overhead chỉ 2–16% trong mọi trường hợp; log đo được lớn hơn text.

Kết quả truy vấn substring hiếm (0.78125% file match):

| Corpus | Chưa index | Có index, planner mặc định | Diagnostic ép đường index |
| --- | --- | --- | --- |
| docs_8k | 233.216 ms | 241.152 ms, Seq Scan | 1.945 ms |
| docs_64k | 249.047 ms | 251.342 ms, Seq Scan | 1.964 ms |
| logs_8k | 149.745 ms | 153.164 ms, Seq Scan | 1.632 ms |

Regex hiếm `needleopenlet-[0-9]{6}`: mặc định sau index 174.348 / 144.715 / 118.016 ms; forced index diagnostic 1.252 / 0.980 / 0.943 ms. Từ phổ biến xuất hiện mọi file hoặc pattern hai ký tự không có lợi đáng kể trong default plans. Không set enable_seqscan=off production; settings đó chỉ ở các EXPLAIN diagnostic được gắn tên riêng. Cả before/after default vẫn giữ nguyên.

EXPLAIN và pg_stats ghi heap chỉ 27 / 4 / 27 pages, avg_content_width=18, trong khi nội dung ngoài dòng nằm ở TOAST. Default planner chọn Seq Scan cho rare pattern dù đường GIN nhanh hơn nhiều khi đo. Vì vậy khi triển khai TextSearch phải kiểm tra đúng query scope/subtree trên dữ liệu thực; chưa được hứa cứ thêm index là nhanh. Chưa đủ bằng chứng để thiết kế line table/chunk index hoặc thêm search service.

**Kết luận giải thích lại theo câu hỏi user.** Tiếp tục đề xuất dùng pg_trgm GIN cho text candidate search, không dùng similarity thay grep. Nhưng benchmark default hiện tại đúng là chưa cải thiện performance: scan là thực tế, forced-index chỉ chứng minh đường index có tiềm năng. EXPLAIN ước tính cost docs_8k SeqScan 78.20 < BitmapHeapScan 116.02; docs_64k 10.40 < 103.65; logs_8k 78.20 < 187.63. Có index không bắt planner chọn nó. Case pattern phổ biến/quá ngắn/scope nhỏ có thể scan đúng; case rare đã đo là query-plan issue cần xử lý bằng workload đúng lúc triển khai. Không lấy 1-2 ms diagnostic làm acceptance production. Acceptance TextSearch phải dùng query scope/subtree thật, default-plan EXPLAIN và so latency/equality trước/sau; index được chọn ở case selective đủ lớn, không ép mọi truy vấn dùng index và không SET enable_seqscan=off toàn hệ thống. Nguồn hỗ trợ operator/short-pattern limitation: https://www.postgresql.org/docs/18/pgtrgm.html.

**Nguyên nhân cost chọn scan, kiểm tra thêm lúc 20:04.** Đã đọc đúng source PostgreSQL 18.6 [cost_seqscan](https://github.com/postgres/postgres/blob/REL_18_6/src/backend/optimizer/path/costsize.c): disk_run_cost = seq_page_cost * baserel->pages; CPU cost = (cpu_tuple_cost + qpqual_cost.per_tuple) * tuples. Với phép scan hiện tại, mô hình này không tính theo số bytes text/chi phí detoast thực tế của mỗi ILIKE. docs_8k main heap chỉ 27 pages; seq cost 78.2 trong khi table+TOAST 16.47 MiB. Actual EXPLAIN ghi 12338 shared buffer hits cho scan so với 170 hits ở bitmap GIN, tất cả shared read blocks=0: đây là cache hits, không phải 12338 disk reads. Text nằm ngoài row/được nén khiến main heap nhỏ, nhưng thực thi ILIKE vẫn phải fetch/detoast và kiểm tra nội dung; planner định giá quá thấp đường scan trong workload này. PostgreSQL không thử cả hai plan rồi chọn theo thời gian đo. Đây giải thích số đo cụ thể, không khẳng định mọi seqscan khi có GIN đều là lỗi hoặc đề xuất ép index toàn hệ thống.

Mọi assertion UTF-8 bytes, row count, rare match count định trước, before/after equality và forced-plan dùng đúng GIN đều pass. Lần chạy đầu phát hiện readiness probe thấy temporary init server rồi nó dừng; script đã sửa probe TCP 127.0.0.1 và chạy hoàn tất sau đó. Container benchmark đã tự stop/remove; không còn process benchmark chạy nền. Synthetic dump preimages nằm ở đường /tmp được ghi trong JSON, không phải bản sao dữ liệu production.

## Thứ tự triển khai đang đề xuất

1. Chốt schema/contract của engine và LetFS text/agent view cùng permission create_agent.
2. Implement messages + receive + AgentWorkflow + LangGraph loop + send_message và read APIs cho UI.
3. Box graph/routing, HITL hai loại và calendar/Schedules trong cùng engine.
4. LetFS path/text/search/tree/mutations + Mirage hooks/Redis cache/image artifacts.
5. AG-UI journal/history/canvas/calendar endpoints và kiểm chứng luồng xuyên suốt trước frontend.

Đây là thứ tự triển khai đề xuất, chưa tạo implementation plan hay sửa production code.

## Chủ động hoãn

Chat nhiều người/bot/group và connector ngoài; quota notification; service chat riêng; graph editor đầy đủ; sửa/xóa từng Leti; task/job engine; Google Calendar sync/meeting attendees/recurrence exceptions tùy ý; search service mới; custom fork grep và file_lines index khi chưa có bằng chứng cần.

## Kiểm chứng thực sự và giới hạn

- Đã đọc source Openlet, lab và release source Mirage 0.0.8, Temporal 1.35.0, LangGraph 1.2.19. Mirage PyPI vẫn 0.0.8 trong lượt khảo sát mới.
- Đã đọc Mirage Integration/Search/Lines/Walks/Checksums/Custom VFS/File cache qua HTTPS .md, source hooks ở v0.0.8 và bài Mintlify. Mintlify minh họa coarse text filtering + Redis cache + shell fine matching; không copy hệ read-only Chroma sang writable LetFS.
- pg_trgm supports LIKE/ILIKE/regex index theo docs chính thức; chưa có extension/index trong migration hiện hành. Đã benchmark isolated PostgreSQL 18.6 ở trên; giữ riêng planner mặc định và diagnostic ép index.
- Chưa chạy engine/Temporal ingress mới, approval auto-execution, calendar hay adapter Mirage–LetFS. Không gọi source inspection là integration test.
- Chưa thay production code/config/schema/DB. Chỉ cập nhật checkpoint và thêm script/JSON benchmark. Đã khởi động PostgreSQL tạm cho benchmark và dọn xong; không có process benchmark còn chạy, không chạy paid inference.

## Baseline đã chốt và phần cần hoàn thiện

1. Engine chi tiết gồm các mục 1–7 đã được user chốt tạm làm baseline, có thể điều chỉnh ở bước plan/implement sau. Chưa có lệnh lập plan hay implement trong lượt này.
2. Approval hiện hành là resource access (user chốt lúc 21:35); accept cấp scope relation, không execute tool call cũ. Ask_user/quiz bỏ Other, selection nullable/empty + note và text một field giữ nguyên.
3. Scheduler at/interval/calendar cũng đã được user đồng ý. Có mốc at cụ thể, bổ sung end_at cho lịch lặp. Lab còn cần verify scheduling round trip/anchor/one-shot/end_at/missed delivery.
4. LetFS APIs, GIN text search, Redis cache và durability sync đã được user đồng ý. Storage/migration text và namespace artifact cụ thể hóa ở plan. Không còn mục chốt policy tool approval. Benchmark chưa thay thế integration query scope/subtree hoặc cache/mount tests.
5. Cấu hình Redis eviction/cache TTL và chính sách bù lịch sau Temporal server outage dài cần chốt ở contract/triển khai, không thêm hệ thống riêng để giải quyết trước.

## Xác nhận phạm vi Mirage theo lượt mới nhất

Đúng với giới hạn các command/flag Mirage 0.0.8 hỗ trợ: Openlet implement LetFS APIs + BaseVFS adapter/hooks đã liệt kê, mount/permission, cache freshness và blob/artifact/image representation; Mirage lo parser, pipeline, glob/regex matching và dispatch từ command tới VFS. Không viết lại lớp Bash command adapter trong Openlet. Mirage có thể vẫn walk/read khi không dùng được pushdown; đó là giới hạn được user chấp nhận. Hooks không tự làm auth/quota hoặc đảm bảo complete candidate set thay backend. Source chính: https://github.com/strukto-ai/mirage/blob/v0.0.8/python/mirage/vfs/base.py và các generic command files đã khảo sát.

## Rà soát draft gốc: còn gì chưa bàn/chốt (20:17)

**Bản rà soát lịch sử lúc 20:17:** các mục quyền, resource approval và history đã được bàn/chốt ở các lượt sau. Không xem danh sách "còn mở" bên dưới là backlog hiện hành; xem đầu file và rà soát 21:35 cuối file.

Phạm vi đối chiếu là mười phần trong prompt brainstorm Leta hiện tại. Không khôi phục các quyết định của report Leti ngày 01/11 đã bị thay thế: conversation riêng, /chat, caller identity, no approval, không queue input. "Chốt 1–7" là bảy mục engine trong câu trả lời gần đây, không phải xác nhận mọi policy còn thiếu của draft gốc.

| Phần draft gốc | Trạng thái |
| --- | --- |
| 1. Product/MVP, thuật ngữ | Đã chốt Leta/Leti/box, một Leta một workspace, chỉ owner, phạm vi hoãn |
| 2. Account/scope/LetFS/lab | Đã khảo sát và lưu nguồn; không coi plan/code/lab là cùng trạng thái |
| 3. Inbox/wake/steering | Đã chốt engine/envelope/cursor/receive/behavior Leta–Leti và retry baseline |
| 4. Giao tiếp/nhật ký/AG-UI | Đã chốt explicit send, final note, PG history/Redis stream; presentation/subscription contracts có thể hoàn thiện ở plan/frontend |
| 5. Box/communication graph | Đã chốt create/delete nguyên graph, name/ID/routing/representative, edge permission, independent agents |
| 6. HITL | Đã chốt cơ chế, hai type/status, quiz answers, timeout/cancel và Leti owner routing; thiếu policy cụ thể tool nào cần approval |
| 7. Lịch | Đã chốt at/interval/calendar/end_at và UI/Temporal split; còn lựa chọn xử lý nhiều mốc bị lỡ |
| 8. State/retry/streaming | Đã chốt boundaries, sync async-I/O distinction, ba replay và coalescing evidence; context LLM khi vượt window chưa bàn riêng |
| 9. Permission/workspace/Mirage/search | Mount/adapter/Redis/hooks/blob/search direction đã chốt; cần hoàn thiện ma trận quyền, quyền owner thao tác, workspace discovery và search contracts |
| 10. Đầu ra/triển khai | Đã có checkpoint và đề xuất thứ tự; chưa tổng hợp design MVP cuối/implementation plan. User cho phép refine ở plan, không cần mọi field API thành câu hỏi brainstorm |

**Các quyết định sản phẩm/policy còn mở:**

1. Quyền chi tiết (draft §9): đã chốt account/member/mount và owner xem mọi resource thuộc Leta, nhưng chưa có ma trận owner được sửa/xóa/quản lý những gì, quyền Leta mặc định theo member/shared scopes và khả năng thu hẹp Leti theo box/mount. Đã đề xuất workspace.create_agent cho human member và viewer grant owner trên Leta personal scope, chưa có phần xác nhận riêng đầy đủ. Cần giải quyết owner rời workspace/quyền thay đổi mà không biến owner-of-Leta thành bypass shared-scope access. Không hỏi lại việc Leta là member hay chỉ một workspace.
2. Approval policy (draft §6/§9): cơ chế runtime gate đã chốt, chưa định rõ read/write/delete/external action nào always/conditional/no approval và áp dụng với shell/Monty trên mount nào. Không tự mặc định mọi write nguy hiểm. Đây là bảng policy, không thêm subsystem.
3. Missed schedule policy (draft §7): đã mô tả native queue/catchup, chưa chọn recurring khi lỡ nhiều mốc sẽ bù tất cả, bù gần nhất hay bỏ qua. One-off reminder giao trễ cũng cần thể hiện rõ. Không khẳng định Temporal catchup_window hoặc overlap tự gộp mọi delivery đã queue khi worker dừng; phải map policy đúng native semantics khi plan/lab.

**Phần chưa bàn riêng, cần bổ sung để đáp ứng agent lâu dài:** quản lý LLM context khi vượt context window. Working message list bền vững không có nghĩa gửi vô hạn toàn bộ lịch sử vào mỗi model call; cần chọn trim/summarize và giữ pending HITL/box/request references. UI history vẫn ở PostgreSQL, không bị xóa cùng context. Đây là hệ quả của requirement chạy lâu dài, không đưa thêm memory service/RAG subsystem vào MVP. Có thể tận dụng middleware thư viện thay tự xây engine tóm tắt.

**Các contract có thể hoàn thiện ở plan, không cần mở thêm vòng duyệt mọi chi tiết:** bộ tools tối thiểu để Leta xem workspace/list-get box/inspect status và Leti xem phạm vi được cấp; semantic_search tìm trong mount được chọn hay fanout các mount được cấp, luôn enforce scope/root và trả artifact paths đọc được; event metadata/subscriptions cho nhật ký nhiều agent và fallback khi Redis cursor hết hạn. Chức năng semantic search cho cả hai agent, quyền xem/đọc và mount đã là yêu cầu, không hỏi có làm hay không.

**Các việc kỹ thuật/kiểm chứng còn lại:** text migration/storage contract, artifact namespace, Redis TTL/eviction/limits, timeout/concurrency defaults và dependency pins; integration tests receive/crash/HITL/box deletion/scheduling/Mirage cache/LetFS search. Đây không phải các quyết định kiến trúc chưa bàn cần giữ user ở brainstorm. Không mở lại quyết định GIN vì query plan chưa tune, cũng không coi benchmark là production validation.

Đề nghị thứ tự thảo luận tiếp: ma trận quyền -> approval policy (dựa trên ma trận quyền) -> lịch bị lỡ -> context dài hạn. Sau đó tổng hợp design MVP và plan; không tự bắt đầu implement trong lượt coverage này.

## Quyền, lịch, context và bộ tool đề xuất theo lượt 20:40

Phần thử tool approval dưới đây là lịch sử đã bị thay thế bằng resource access; tool catalog đã cập nhật delta hiện hành. Các default kỹ thuật là baseline có thể chỉnh lúc plan.

### User đã quyết định và phạm vi lượt này

- Leta có quyền trên shared/personal đúng role member như human user. Không tạo policy duyệt mọi write/delete. Shared member vẫn là editor, không tự trở thành manager/admin.
- Leti không có account; dùng delegated Leta identity với box home và shared mounts đã chốt. Quyền personal của Leta không cho Leti đi ra khỏi box home, không mount personal của owner.
- Cần một tool thử approval vì phần lớn tools hiện được phép. Ask_user nhiều câu hỏi và choice rỗng + note giữ nguyên.
- User yêu cầu khuyến nghị lịch đơn giản, tham khảo coding agents xử lý context, rồi đề xuất bộ tools/args đầy đủ. Các proposal dưới đây chưa được coi là user đã chốt hoặc cho phép implement.

### Approval test

Tool đề xuất `test_approval(message: string)`, có cho cả Leta/Leti. Runtime policy luôn yêu cầu approval cho tool này; body chưa chạy khi request pending. Accept chạy đúng call đã giữ, ghi một activity event thực `approval_test_executed` cùng message rồi đưa kết quả vào inbox requester. Deny/cancel/expire không ghi event thực thi, chỉ giao outcome. Retry dùng request/tool_call_id hiện có để không nhân đôi event thử.

Đây là action thử có effect quan sát được trong journal, không phải agent tự gọi request_approval hoặc giả lập một tool nghiệp vụ nguy hiểm. Các tool thật vẫn dùng permission Openlet; chưa thêm chặn filesystem theo path. Owner trả lời bằng UI/API, không cấp respond_hitl tool cho agent.

### Đề xuất lịch đơn giản

- Một lần: khi worker trở lại, giao trễ một lần với scheduled_at gốc.
- Lặp: đề xuất đổi riêng overlap từ ALLOW_ALL đã nêu sang native BUFFER_ONE. Khi delivery workflow trước còn mở, buffer tối đa một start kế tiếp; các starts chồng thêm bị bỏ. Buffer giữ lần chờ đầu tiên, không cam kết latest-only.
- Delivery workflow chỉ sống tới khi receive đã ghi inbox; không kéo dài theo thời gian model làm báo cáo/HITL. BUFFER_ONE không giới hạn số công việc agent đang chờ và không xóa item đã vào inbox.
- Dùng catchup_window mặc định của Temporal (SDK 1.35.0 để None, server hiện một năm); không thêm scheduler chạy bù, latest-occurrence query, policy table hoặc tham số policy cho model. Không diễn giải BUFFER_ONE thành bảo đảm gộp mọi mốc sau mọi loại server outage.
- So với ALLOW_ALL: giảm tích tụ delivery trong worker outage, đổi lại có thể bỏ mốc lặp. Với MVP nhắc việc/đánh thức viết báo cáo, nghiêng BUFFER_ONE; đây là đề xuất mới cần user xác nhận, không đảo baseline ngầm.

Nguồn: [Temporal policies](https://docs.temporal.io/schedule#policies) và source [ScheduleOverlapPolicy/SchedulePolicy 1.35.0](https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/client/_schedule.py). Bản release đã tải xác nhận BUFFER_ONE giữ first buffered start; SKIP là default SDK, không gọi BUFFER_ONE là default thư viện.

### Context: khảo sát và đề xuất

Nguồn đọc:

- [Claude Code context](https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code): auto compact gần giới hạn; /compact tóm tắt để tiếp tục, tham chiếu file thay vì dán nội dung lớn.
- [OpenCode V2 compaction](https://opencode.ai/docs/compaction/): summary + recent context, mặc định keep khoảng 15k tokens, giữ original history trong storage. Long tool output/attachments được rút gọn trong context. Context7 có snippets V1 lẫn V2 dù đã query v2.1.2; dùng trang V2 hiện hành, không gộp config prune/reserved V1 với keep.tokens/buffer V2.
- Lab durable-chat uv.lock: langchain 1.4.8, deepagents 0.7.32. Đã tải wheels PyPI, đọc `langchain/agents/middleware/summarization.py` và `deepagents/middleware/summarization.py`, không cài/chạy dependencies. Source nằm /tmp/leta-research/{langchain-1.4.8,deepagents-0.7.32}-summarization.py.txt.
- LangChain 1.4.8 có SummarizationMiddleware.abefore_model, trigger/keep theo tokens/fraction, giữ cặp AI/Tool qua _find_safe_cutoff. trim_tokens_to_summarize mặc định 4000: chỉ lấy phần cuối của older history để tóm tắt; không mặc định đó là tóm tắt đủ toàn bộ history. Deep Agents 0.7.32 có wrapper offload và compact tool, nhưng PostgreSQL history của Openlet đã có nên không tự thêm file backend của Deep Agents.

Đề xuất cùng một policy cho Leta/Leti:

1. Trước model call, tính budget gồm system/tools, steering và working history; mốc khởi đầu auto compact khoảng 80% input budget sau reserve output.
2. Giữ system prompt/current identity/mount/roster và recent messages theo khoảng 20% budget, nguyên cặp tool calls/results. Tóm tắt older messages thành một continuation summary: mục tiêu, quyết định, việc đã xong, đang làm, đang chờ, next steps và IDs/paths có ích.
3. Dùng SummarizationMiddleware async của LangChain trong runner; cấu hình model/profile/counter đúng và trim_tokens_to_summarize để không âm thầm bỏ hết older history ngoài 4k cuối. Với cùng model/budget phù hợp có thể để None; pin/check cấu hình khi plan. Không chọn provider-native opaque compaction cho MVP multi-provider.
4. Pending HITL/schedules/box references là trạng thái có nguồn thật trong PostgreSQL; refresh digest cần thiết, không chỉ dựa vào summary. Không thêm task model để suy ra box đang chờ gì.
5. Working summary/recent list checkpoint sync cùng LangGraph; inbox cursor không reset khi compact. History/UI không bị xóa theo working context. Chỉ compact sau khi tool-call protocol đã đóng, trước model, rồi collect input mới theo boundary hiện có. Input tới trong khi summary call cũng vẫn ở inbox.
6. Tool results có limit/pagination, file đọc theo đoạn. Model có thể tìm/đọc lại own public history qua hai tools bên dưới; không cần memory service hoặc RAG index mới. Summary có thể mất chi tiết nên không dùng làm nguồn duy nhất của approval/action args.

### Bộ tool cuối đang đề xuất

Quy ước: `?` tùy chọn, Ref là ID hoặc tên duy nhất trong roster được phép. Runtime tự gắn agent/Leta/workspace/owner/authority; model không truyền actor_id, scope_id hoặc credential. Pages trả next_cursor khi còn dữ liệu; defaults dưới đây là proposal, có thể điều chỉnh khi plan. Datetime dùng RFC3339, timezone dùng IANA.

#### Workspace và phục hồi context — cả hai agent

| Tool | Args | Contract |
| --- | --- | --- |
| get_workspace | () | Workspace Openlet hiện tại, role/effective permissions, identity, mounts và các đích giao tiếp được phép; Leti biết peers/representative. Không lộ personal scopes ngoài mount. |
| list_workspace_members | (limit: int=20, cursor?: string) | Tra human users cùng workspace để chọn người xin personal scope; trả account ID/name, không trả nội dung scope hoặc mở chat route. |
| search_history | (query?: string, limit: int=20, cursor?: string) | Tìm notes, delivered messages và public tool activity trong history của chính agent; không query pending inbox. Bỏ query để xem gần đây; trả excerpts và entry IDs. |
| read_history | (entry_id: string, start_line: int=1, max_lines: int=200) | Đọc chi tiết public activity đã lưu, có paging line/truncated marker; không truy xuất chain-of-thought. |

#### Messaging/inbox

| Tool | Args | Ai dùng/contract |
| --- | --- | --- |
| send_message | (to: Ref, content: string, in_reply_to?: string) | Cả hai. Resolve chỉ trong roster; in_reply_to là message ID và phải khớp nguồn/đích được phép. Leta → owner/box; Leti → edge peers; representative → parent Leta dưới box ID. |
| list_inbox | (from?: Ref, unread_only: bool=true, limit: int=20, cursor?: string) | Chỉ Leta. Trả grouped conversations với source/reply target/count/preview, không nhét toàn bộ body. |
| read_inbox | (conversation_id: string, unread_only: bool=true, limit: int=20, cursor?: string) | Chỉ Leta. Đọc nội dung, đánh read_at cho items thực sự trả về. Không có processed/closed flag. |

Leti vẫn nhận toàn bộ pending message contents qua steering; hai history tools chỉ đọc quá khứ đã giao, không thay đổi cơ chế Leti inbox. Conversation grouping là luồng trao đổi theo nguồn/địa chỉ, không thêm task model.

#### Box — chỉ Leta

| Tool | Args | Contract |
| --- | --- | --- |
| list_boxes | (limit: int=20, cursor?: string) | Box ID/name/description/status và counts. |
| get_box | (box: Ref) | Graph/names/descriptions/prompts/representative, derived home và trạng thái agent/HITL/lịch để quản lý canvas. |
| create_box | (name: string, description: string, letis: LetiSpec[], edges: [string,string][], representative: string) | Một transaction config nguyên graph; không tự gửi việc. LetiSpec = {name,description,system_prompt}; edges/representative tham chiếu Leti name trong payload. |
| delete_box | (box: Ref) | Lifecycle xóa đã chốt, không xóa history. |

Tên Leti unique trong toàn Leta; tên box unique trong Leta. Slug suy từ name; validate derived home collision. Không có field slug, update_agent, edit_graph hoặc send_box.

#### HITL — cả hai

| Tool | Args | Contract |
| --- | --- | --- |
| ask_user | (title: string, questions: Question[], timeout_seconds?: int) | Luôn owner của Leta; trả pending ngay, không khóa agent. Không truyền user_id/to. |
| list_hitl | (status?: pending/resolved/cancelled/expired, box?: Ref, limit: int=20, cursor?: string) | Default own requests; Leta có thể chọn box để xem requests bên trong, Leti chỉ own. |
| get_hitl | (request_id: string) | Request, deadline, answers/decision và execution outcome nếu có. Leta được inspect/manage requests thuộc mình/box của mình. |
| cancel_hitl | (request_id: string, reason?: string) | Chỉ pending; không undo action đã accept/thực thi. Leti chỉ own; Leta có thể quản lý requests trong boxes thuộc mình. |
| request_access | (resource:{type:"personal_scope",user_account_id:string}, role:viewer/editor="viewer", reason:string, timeout_seconds?:int) | Thay test_approval theo lượt 21:18. Approver là user sở hữu scope, grant target luôn Leta account. |

Question = {id:string, text:string, type:single_choice|multiple_choice|text, options?: {id:string,label:string}[]}; options bắt buộc cho hai choice types, không dùng cho text. Question IDs unique trong form. Một ask_user nhận nhiều questions.

Owner responses: single `{option_id:null|ID,note:string}`; multiple `{option_ids:ID[],note:string}`; text `{text:string}`. Selection rỗng và note rỗng đều hợp lệ. Không có Other. Responses map theo question ID. Agent không có tool tự submit owner response. Resource approval tạo qua request_access; không còn dangerous-tool gate hoặc tool request_approval.

#### Lịch — cả hai

| Tool | Args | Contract |
| --- | --- | --- |
| create_schedule | (title:string, content:string, spec:ScheduleSpec, target:Ref="self", end_at?:datetime) | Leta: self hoặc box (route representative); Leti: self. Relative at/anchor normalize một lần. |
| list_schedules | (box?:Ref, limit:int=20, cursor?:string) | Default own; Leta có thể xem mọi schedules của Leti trong box đã chọn, Leti chỉ own. Trả definitions và next time nếu có. |
| get_schedule | (schedule_id:string) | Definition/state và một số mốc tiếp theo qua backend/native matching times. |
| update_schedule | (schedule_id:string, title?:string, content?:string, spec?:ScheduleSpec, end_at?:datetime|null, paused?:bool) | Chỉ đổi các field được truyền; null xóa end_at. Pause/resume qua paused. |
| delete_schedule | (schedule_id:string) | Dừng nguồn kích hoạt tương lai; không thu hồi inbox đã được tạo. |

Leta quản lý schedules của mình và Leti thuộc mình; Leti chỉ schedules target chính nó. Không tạo API Leta nhắn trực tiếp Leti. Backend tự lưu agent target/box relation đã resolve.

ScheduleSpec (tagged union, không có daily/weekly hardcode):

```text
{type:"at", at:datetime}
{type:"at", after_seconds:int}
{type:"interval", every_seconds:int, anchor_at?:datetime}
{type:"calendar", timezone:string, fields:CalendarFields}
CalendarFields = {second?,minute?,hour?,day_of_month?,month?,day_of_week?,year?}
CalendarField = "*" | Array<int | {start:int,end:int,step?:int}>
```

Mỗi CalendarFields value theo CalendarField. Ví dụ hour:[9], minute:[0], second:[0], day_of_month:[1] là 09:00 ngày 1 hằng tháng trong timezone đã chọn. Second/minute/hour mặc định [0], date fields mặc định "*"; day_of_week dùng 0=Sunday đến 6=Saturday. Range step mặc định 1. Map sang Temporal ranges, không viết RRULE engine.

At chỉ nhận một trong at/after_seconds, relative và intervals dương theo độ phân giải giây của scheduler. Anchor mặc định thời điểm tạo đã persist; một tháng là calendar, không đổi thành 30 ngày. End_at chỉ cho recurring. No-op update/invalid combinations trả validation error.

#### Filesystem, execution, RAG — cả hai, luôn qua Mirage

| Tool | Args | Contract |
| --- | --- | --- |
| list_files | (path:string="~", depth:int=1, limit:int=100, cursor?:string) | Metadata/tree trong mount, không body. |
| read_file | (path:string, start_line:int=1, max_lines:int=200) | Text theo dòng; blob metadata+artifact tree; image artifact/preview trả multimodal. Line selection chỉ có nghĩa với text. |
| write_file | (path:string, content:string, overwrite:bool=false) | Tạo/ghi inline text; không sửa payload blob hoặc readonly artifacts. |
| edit_file | (path:string, old_text:string, new_text:string, replace_all:bool=false) | Exact text edit; mặc định yêu cầu một match, không có/ambiguous match trả lỗi. |
| run_shell | (command:string, cwd:string="~", timeout_seconds:int=30) | Shell ảo Mirage, hỗ trợ command/flags của bản thư viện; không chạy host Bash/subprocess. |
| run_python | (code:string, timeout_seconds:int=30) | Monty qua Mirage cùng filesystem mounts/permissions; không host Python interpreter. |
| semantic_search | (query:string, paths?:string[], limit:int=10) | Bỏ paths thì dùng các readable roots hiện đang mount, gồm foreign personals đã được cấp; nếu có paths thì thu hẹp vào chúng. Trả readable artifact paths/snippets và degraded/indexing state nếu có. |

Mkdir/copy/move/trash/append/range/head/tail/find/grep/rg qua run_shell và hooks đã chốt. Không expose từng backend hook thành một model tool. SemanticSearch tái dùng LetFS parent/root filtering, reauth và generation validation; map artifact hits về path đọc được. Không index raw blob, không dùng semantic top-k làm grep candidate completeness.

Các signatures trên là tool contract đề xuất, không phải tuyên bố SDK Mirage có đúng các Python methods/args cùng tên. Tool wrappers dùng session dispatcher/VFS của bản đã khảo sát và runtime áp limit/timeout. Owner tạo/sửa Leta, trả lời HITL, xem calendar occurrences/streams qua app APIs; không biến các thao tác owner thành tools của agent.

### Kiểm chứng lượt này

Chỉ đọc source/docs/wheels và cập nhật checkpoint; chưa chạy model, engine, native schedule outage test hoặc Mirage adapter. Context7 hai lệnh đều thành công. Web fetch Claude context-window.md gặp unsupported markdown/403; dùng bài chính thức Claude Help Center đã đọc thành công. Không sửa skill code. Hai đường file thử ban đầu không tồn tại (lab pyproject ở lab con, schema ở packages/contracts/authz), đã tìm và đọc đúng owning files; không suy ra repo/API bị thiếu.

Chưa thêm web/data connector: nếu cần báo cáo giá chứng khoán từ thị trường thật thì cần nguồn dữ liệu riêng; scheduler/engine chỉ đảm bảo kích hoạt và giao input. Không tự thêm capability này vào bộ tools MVP đã bàn.

## Resource access approval và dynamic mounts — lượt 21:18

### Quyết định user mới, thay thế các đề xuất trước

- Approval xin quyền tài nguyên; MVP chỉ xin personal scope của human user active cùng workspace, không chỉ owner. Sau chấp thuận Leta account được cấp relation trên scope đó. Không còn tool approval hoặc test_approval.
- User đã chốt Leti kế thừa quyền Leta. Leti không có account nên không nhận scope membership độc lập. Requester có thể là Leti, grantee luôn account Leta; grant áp dụng cho Leta và Leti của nó.
- Chat owner-only vẫn giữ; request cấp tài nguyên là exception có UI nhận/duyệt cho user khác. Không tự mở send_message/ask_user tới mọi member. Ask_user hiện vẫn owner trừ khi có yêu cầu đổi riêng.
- User đã chốt các chi tiết dưới ở lượt 21:35: role default, tool/payload/path/API refresh và history. Đây là chốt thiết kế, chưa phải lệnh implement.

### History nghĩa là LLM transcript

Khi nói history cho search_history/read_history, nghĩa chính là lịch sử làm việc model-facing của từng agent: input/steering thực sự đã đưa vào context, assistant messages, tool calls/IDs/arguments, ToolMessages/results và final notes. Không chỉ là chat owner–Leta, không gồm hidden chain-of-thought. Dùng public transcript để render tool history/journal.

Working messages trong checkpoint chỉ là phần context đang dùng (summary + recent sau compact); PostgreSQL giữ transcript lâu dài. Lưu các message mới một lần, không snapshot lặp toàn bộ prompt cho mỗi model call và không ghép vô hạn checkpoint snapshots để dựng history. activity_log/messages có thể làm owning storage/views khi plan; không tự thêm memory service. Hai history tools đã đề xuất cần đọc transcript này, không chỉ text notes hoặc một bản activity summary đã mất tool arguments/results.

### Contract và luồng xin quyền

Tool đã chốt: request_access(resource:{type:"personal_scope",user_account_id:string}, role:"viewer"|"editor"="viewer", reason:string, timeout_seconds?:int). Model chọn user từ list_workspace_members; runtime resolve personal scope trong workspace hiện tại, xác thực user/agent active membership và gắn requester/grantee/approver. Không để model truyền tùy ý approver hoặc grantee. Nếu đã có đủ quyền thì trả already_granted/current mount thay vì tạo request thừa.

Role dùng đúng schema hiện có: viewer đọc; editor đọc/ghi/trash/restore. Chưa cho xin manager/manage_access. Cấp quyền có hiệu lực tới lúc bị thu hồi; expires_at là deadline trả lời request, không phải hạn của grant. Không thêm hệ thống grant expiration trong MVP.

Payload server-owned ví dụ:

```json
{
  "id": "hitl-42", "type": "approval", "status": "pending",
  "requester_agent_id": "leti-research",
  "grantee_account_id": "leta-account",
  "approver_account_id": "user-a",
  "resource": {"type": "personal_scope", "id": "scope-a"},
  "role": "viewer", "reason": "Đọc tài liệu để tổng hợp báo cáo",
  "expires_at": "2026-11-07T15:00:00Z"
}
```

Không còn action.tool/action.arguments. Approver derive từ chủ personal scope, không phải owner Leta. Card ghi tên Leta, owner Leta, Leti yêu cầu nếu có, scope/role/reason và phạm vi thụ hưởng gồm Leta + Leti. API response xác thực đúng người duyệt; owner Leta không được duyệt thay chủ scope khác.

1. Request persist trong PostgreSQL; request workflow chờ độc lập; tool trả pending. Người có scope thấy card trong danh sách requests gửi cho mình, không cần chat service.
2. Accept resolve decision rồi gọi cơ chế cấp scope access hiện có dưới authority của người đã xác thực/duyệt. User này phải còn quyền manage_access; validate cùng workspace/active membership theo rule sản phẩm mới. Idempotent relationship TOUCH phù hợp retry.
3. Sau khi quyền có hiệu lực, refresh mount view requester tại boundary và receive result {request_id,granted:true,role,mount_path} vào inbox. Nếu grant thất bại thì báo outcome lỗi, không nói đã truy cập được chỉ vì owner đã click accept.
4. Deny/cancel/expire không cấp grant, giao outcome về requester. Giữ bốn status đã chốt; câu trả lời deadline race như trước.
5. Accept không execute lại một tool cũ; agent chọn read/search/write bình thường sau khi nhận quyền. Lỗi thiếu quyền trả access_required để agent có thể xin; không tự tạo request cho mọi lệnh ls/read bị từ chối.

Grant thật thuộc workspace/authz, không thuộc HITL record. Cancel/delete request hoặc delete box không tự revoke quyền của Leta; resource owner thu hồi qua scope access API/UI. Xóa cả Leta phải dọn grants theo lifecycle account/resource, chi tiết khi plan. Future computer có resource kind/handler cụ thể riêng, không cần generic arbitrary-action executor trong MVP.

### Mount đã chốt

| Prefix agent nhìn thấy | Đích |
| --- | --- |
| ~/ của Leta | Leta personal scope |
| ~/ của Leti | Leta ~/.leti/<derived-box-slug>/ |
| /shared/ | Shared scope của workspace |
| /users/<user-account-id>/ | Personal scope human user đó trong workspace hiện tại, chỉ khi đã có grant |

ID trong path ổn định, không phụ thuộc display name; get_workspace trả user name và mount path để agent chọn. Mỗi user một prefix nên nhiều grants cùng tồn tại. Scope owner có thể chính là owner Leta nhưng cũng phải grant riêng. Viewer map MountMode.READ; editor map WRITE (bao gồm đọc), backend vẫn check permissions.

Mỗi agent giữ Mirage workspace riêng theo invocation như baseline; không dùng một global workspace cho mọi agent. Mỗi scope/root mount là một adapter instance nhẹ dùng chung network client; không load nội dung hoặc dựng lại toàn bộ cây file khi mount. Leti nhận cùng foreign personal mounts như Leta, nhưng home vẫn box root, không lộ toàn bộ Leta personal.

### Mirage 0.0.8 thực sự hỗ trợ dynamic mount

Đã đọc source v0.0.8, không suy từ docs TS/phiên bản khác:

- Workspace.add_mount(prefix,vfs,mode,read,...) thêm vào workspace đang chạy, refuses duplicate prefix; kiểm tra read/write capabilities.
- await Workspace.unmount(prefix) gỡ, dọn cache và đóng VFS; calls/streams đã được admit phải hoàn tất/close.
- Workspace.set_mount_mode(prefix,mode) đổi ceiling; không tự nâng session caps nếu đã cấu hình caps riêng.
- prepare_added_mount gắn clear_mount_cache trước lần dùng đầu; namespace rows_changed cập nhật view. Không tự viết invalidation bus.
- Sources: https://github.com/strukto-ai/mirage/blob/v0.0.8/python/mirage/workspace/workspace/workspace.py (add_mount:1059, unmount:1130, set_mount_mode:1141), cùng thư mục mounts.py (prepare_added_mount:280, unmount_prefix:293); mirage/types.py MountMode:467. Source đã lưu .txt ở /tmp/leta-research/mirage-0.0.8/.

MVP load mount view đầu invocation; sau access_granted hoặc get_workspace refresh, diff và add/unmount/set mode ở boundary giữa các tool calls, không thay mount khi shell/Monty còn đang chạy. Session kế thừa view của workspace riêng, tránh cài thêm một allowlist cố định làm duplicate ACL; nếu có session caps riêng phải refresh cùng mount. Không cần giữ object sống qua worker restart; invocation mới dựng lại từ quyền hiện tại, Redis cache vẫn theo namespace/freshness đã chốt.

### Tạo mount view không cần query cây phức tạp

Thiết kế đã chốt: bổ sung endpoint nội bộ ở workspace service trả filesystem view cho account Leta; service leta không join thẳng DB của workspace service. Endpoint lấy own/shared scopes và danh sách personal_scope_id của human members active bằng SQL theo workspace_members, rồi BulkCheck quyền read_content/write cho account Leta. Trả mapping prefix → filesystem_id/scope_id/root/mode; leta layer thay home bằng box root khi requester là Leti.

Đây là một query membership đơn giản cộng batch authorization, không quét filesystem, không N+1 request theo user/file và không quét lịch sử HITL để dựng grants. Chi phí tuyến tính theo số members; helper hiện giới hạn 100 resources/batch nên chia batch khi vượt 100, không hứa một RPC với số scope vô hạn. Names có thể lấy từ member summaries đã có theo batch. Chưa cần thêm một bảng grants song song với SpiceDB.

Nguồn hiện có: apps/workspace/internal/workspace/relations.go ChangeScopeAccess:166, UpdateScopeAccess:189 và WriteMemberRelationships:28 (rebuild giữ direct grants); transport/http/server.go:57 có PUT/DELETE /workspaces/:ws/scopes/:scope/access/:account. Schema scope có viewer/editor/manager; không có scope member role/bảng membership riêng cần thêm chỉ để cấp quyền này. packages/go/authz/client.go BulkCheck:43 fully-consistent và max 100. Hiện chưa có endpoint aggregate filesystem view nói trên; đó là phần cần bổ sung, không gọi là API đang có.

LetFS/backend vẫn kiểm quyền cho truy cập mới, kể cả qua cache FRESH. Mount view không phải nguồn authority; khi revoke, backend phải từ chối đọc mới trước cả khi UI/runtime kịp gỡ prefix. semantic_search dùng các mounted roots đã cấp, hydrate/reauthorize như trước.

### Hệ quả owner visibility phải nói rõ

Grant cấp cho Leta không tự cấp direct relation cho owner Leta. Tuy nhiên owner đã được quyền xem hoạt động/transcript/kết quả Leta, nên dữ liệu user khác cho Leta đọc có thể xuất hiện trong history hoặc tin gửi owner. Người cấp quyền cần thấy điều này trên card. Thu hồi quyền chặn truy cập mới, không xóa nội dung đã đọc khỏi context/history. Không hứa bảo mật dữ liệu khỏi owner sau khi đã chia sẻ cho Leta.

### Kiểm chứng và phần còn mở

Đã đọc đúng source/version và hai lệnh Context7 cho Mirage thành công. Context7 trả lẫn docs TypeScript/MEMFS và Python API cũ; kết luận dynamic mount/cache dựa source Python v0.0.8. Chưa chạy end-to-end cấp/revoke scope → refresh mounts → cache/search. Chỉ cập nhật checkpoint, chưa sửa schema/code/DB hoặc tài nguyên thật.

User đã xác nhận các điểm này ở lượt 21:35: viewer mặc định/editor tùy chọn, namespace /users/<account-id>, request_access và aggregate filesystem view; không hỏi lại. Leti kế thừa quyền Leta cũng đã chốt.

## Rà soát sau chốt — 21:35

Đã đối chiếu lại mười phần draft gốc với quyết định hiện hành. Không phát hiện cần thêm subsystem hoặc mở lại quyết định kiến trúc lớn để tiếp tục lập design MVP/plan. Các gap lúc 20:17 về quyền/approval/history đã được xử lý bằng quyết định sau đó; scheduler/context có baseline đã trình bày, defaults vẫn có thể điều chỉnh khi plan như user cho phép.

Các phần cần hoàn thiện ở bước thiết kế triển khai, không yêu cầu một vòng chốt feature mới:

1. Nối owner tạo/quản lý Leta: account → workspace membership/personal scope → runtime; enforce quyền owner xem/quản lý resources. APIs nhận resource requests cho user khác chỉ mở đúng request của họ, không mở chat hoặc cho họ xem toàn bộ Leta history.
2. Chốt owning contracts: lưu public LLM transcript theo message/tool-call identity và renderer journal; API inbox/canvas/calendar/requests, AG-UI metadata/subscriptions/reconnect. Những phần này chưa có implementation; UI không lấy dữ liệu từ Temporal history/checkpoint snapshots để dựng lại.
3. Hoàn thiện LetFS text/artifact migration và filesystem-view API; cache freshness/authz, lifecycle grant/revoke và account/agent deletion. Không dùng permission bị thu hồi từ mount/cache cũ và không nhầm xóa box với revoke grant của Leta.
4. Pin dependencies, bounds/TTL/concurrency và chạy kiểm chứng: ingress/retry không nhân đôi tin, HITL không khóa việc khác, deadline/cancel, lịch/worker outage, box deletion, compact không mất cursor/tool protocol, mount refresh/revoke/search/cache. GIN acceptance dùng default-plan query scope/subtree thật, không forced-index diagnostic.

Phạm vi vẫn chủ động hoãn: group/multi-user chat, bot-to-bot chat, external connectors, quota/system notifications, graph editor đầy đủ, sửa từng Leti, task/job engine riêng, full Google Calendar, computer resource cấp phát thật và search service mới. Việc resource request gửi user khác không làm các mục chat trên thành MVP.

Lượt này chỉ cập nhật/check tính nhất quán checkpoint; chưa sửa production code, schema, DB hay chạy integration mới. Bước tiếp theo khi user yêu cầu là tổng hợp design MVP từ baseline hiện hành, không khởi động lại brainstorm hoặc tự triển khai.

## Năm contract cuối — user đã trả lời

| Contract | Quyết định hiện hành |
| --- | --- |
| LangGraph runner | `create_agent` + Openlet middleware/tools, không dùng Deep Agents runtime mặc định. |
| Model configuration | Nhiều model và reasoning modes cấu hình sẵn; owner chọn; Leti mặc định kế thừa Leta. |
| Owner lifecycle | Đồng ý đề xuất sửa name/prompt, pause/resume, archive files/history khi xóa runtime. |
| Runtime budget | User bác bỏ giới hạn model calls/steps mỗi run và các cơ chế budget mới. |
| Missed schedules | Chốt BUFFER_ONE và catchup mặc định Temporal, semantics như phần lịch. |

User yêu cầu sau cập nhật trình bày engine thống nhất và cách dùng Temporal cụ thể. [Bản tổng hợp hiện hành](brainstorm-261107-2159-leta-engine-design.md) tách quyết định đã chốt, bố trí Workflow/Activity đề xuất và các integration checks chưa chạy. Chưa có yêu cầu triển khai.
