# Audit chặng 1: Leta persistence

Đây là audit trước sửa tại `043f4e5`. Các findings đã được xử lý trong working tree theo phạm vi người dùng chấp thuận; xem [implementation và benchmark](refactor-261109-leta-persistence.md) để biết kết quả và các phần giữ nguyên có chủ đích.

Openlet là backend lưu trữ file và thực thi agent bền vững. Chặng này scout persistence của Leta cùng callers và tests, với giả định nhiều request/agent đồng thời và lịch sử tăng theo vòng đời; chưa đặt giả định tải cực lớn.

Phạm vi: 64 method của `Store`, helpers, hai migrations, domain inputs; trace các boundary HTTP/gRPC, schedule activities, lifecycle, runtime và tests liên quan. Đây không phải audit toàn bộ các chặng 2–7. Không sửa implementation, schema hoặc hợp đồng.

Native baseline đạt 32/32 tasks; API/recovery đạt 45/45; ba audit probes trên PostgreSQL thật đều pass. Replay và các gate bổ sung cũng hoàn tất, chi tiết ở [baseline report](baseline-261109-2054-source.md). Các finding dưới đây được phân biệt với ý tưởng cấu trúc và giả thuyết cần đo.

## Coverage ledger chặng 1

Inventory AST ghi 64 method tại revision `043f4e5`; bảng nhóm theo trách nhiệm để thể hiện phần đã scout, không dùng số method làm thước đo chất lượng. Helpers ngoài class, schema/domain và callers được đối chiếu theo boundary liên quan.

| Nhóm methods | Số lượng | Kết luận audit |
| --- | --- | --- |
| Pool, model checks, transaction và admission helpers | 6 | Giữ guards/lock order; timeout setup là đề xuất nhỏ cần đo tác động |
| Root identity, configuration, activation và pause | 10 | Bỏ `list_roots` sau khi chuyển tests; giảm snapshot pause |
| Box graph, activation, deletion và archive | 8 | Giảm metadata overfetch và insert output không dùng; giữ deletion snapshot |
| Routing, receive và inbox/conversation reads | 6 | Bỏ `list_conversation` và write-on-read cũ sau khi chuyển assertions; giữ receive recheck |
| Activity, history reads/search và bootstrap history | 5 | Giữ atomic publication/read markers; chưa xác nhận dead path khác |
| Runs, tool results và runtime bootstrap/yield | 8 | Giữ recovery invariants; `list_runs` là test observation có chủ đích |
| HITL requests/outcomes và actor-facing reads | 7 | Giữ ownership, completion/rollback và race semantics; chưa có cleanup đủ bằng chứng |
| Schedule CRUD, actors, occurrences và calendar reads | 8 | Bỏ admission trùng khi self-target; cân nhắc boundary validation/compiler sau cleanup |
| API reservations và read models | 6 | Sửa reservation retention khi rejected schedule; chuyển tests sang active read models |

Runtime, HTTP và Temporal ở chặng này được trace để kiểm chứng persistence callers; chưa thay thế audit sâu các module đó ở chặng 2.

## Phạm vi theo loại vấn đề

| Nhóm yêu cầu | Kết luận |
| --- | --- |
| Overengineering | Hai cách đánh dấu inbox read; `get_box` bắt metadata callers tải graph; pause dùng toàn bộ deletion snapshot. |
| Dead code | `list_roots`, `list_conversation` chỉ còn callers trong tests. `list_runs` cũng chỉ phục vụ tests nhưng có giá trị kiểm tra recovery, không gán là vô dụng. |
| Backward compatibility thừa | Chưa xác nhận shim tương thích ứng dụng cũ cần xóa. SDK normalization, patch serialization và replay đều có mục đích hiện tại. |
| Useless/misdirected testing | Một số assertions kiểm tra query API không còn dùng và read-marker path khác production tool; thay đúng assertions, không xóa cả recovery/security suites. |
| Unoptimized | Overfetch box, snapshot pause không dùng, repeated schedule admission, timeout setup calls và per-row graph inserts trả dữ liệu không dùng. |
| Dirty code / khó bảo trì | Store gom nhiều nhóm nghiệp vụ; `fault` đặt trong persistence kéo callers nhiều tầng phụ thuộc ngược; schedule validation phụ thuộc compiler của Temporal. |
| Bug / retention | Đã tái hiện bằng HTTP + SQL thật: hai request sai timezone để lại hai reservation không TTL, không có schedule nào. |

## Bằng chứng thực nghiệm

Audit-only probes chạy implementation thật với PostgreSQL disposable; chỉ instrument `AsyncCursor.execute` để đếm calls. Authz ở request test là external-boundary fake theo fixture sẵn có, không phải phép thử SpiceDB.

| Probe | Kết quả |
| --- | --- |
| `get_box(details=False)` với hai Leti, một edge | 5 cursor execute calls: 2 timeout setup + 3 SELECT; graph vẫn tải đầy đủ. |
| `set_paused` trên root đó | 9 cursor execute calls; 4 query trong `_snapshot` không cần cho consumer pause/resume. |
| Root tự tạo schedule | 2 lần root admission lock trong cùng transaction. |
| Hai HTTP requests calendar với `Invalid/Zone` và hai keys khác nhau | Cả hai trả 400; SQL còn 2 rows `expires_at=NULL`, 0 schedules. |
| Gộp hai fixed `SET LOCAL` bằng `prepare=False` | PostgreSQL có hai setting `2s` bên trong transaction và khôi phục đúng setting cũ sau commit. |

Counts không gồm BEGIN/COMMIT nội bộ hoặc protocol bookkeeping; không phải số round trip đo trên network. Không có phép đo p95/throughput hay tuyên bố tốc độ tăng. Log/probe source nằm trong ignored `.local/audit-261109-2054/`.

## Must fix

### 1. Schedule bị từ chối giữ reservation không bao giờ hết hạn

- **Vị trí:** [HTTP create/update](../../apps/leta/src/leta/http/schedules.py:73), [reserve/complete](../../apps/leta/src/leta/store.py:1564).
- **Hiện tại:** create gọi `context.command()` trước `validate_spec()`. Reservation bắt đầu với `expires_at=NULL`; chỉ success của `Context.execute()` mới gọi complete để đặt TTL.
- **Case:** calendar có timezone không tồn tại vượt qua schema parsing, được reserve, rồi bị semantic validation từ chối. Không có schedule/workflow để reconcile nhưng cleanup `expires_at<=clock_timestamp()` không bao giờ chọn row này.
- **Đề xuất:** validate các điều kiện xác định được trước reservation; sau admission vẫn canonicalize theo thời điểm request đã lưu để retry relative time ổn định. Không tự đặt TTL ngắn hoặc xóa reservation khi Temporal outcome còn chưa rõ. Audit riêng các terminal failure sau reservation bằng cùng nguyên tắc.
- **Nếu giữ:** request sai hợp lệ về schema có thể tích lũy receipt vĩnh viễn. Cần regression HTTP+SQL cho rejected request không để lại pending reservation, đồng thời giữ ambiguous-timeout retry.

## Should fix

### 2. Đọc metadata box luôn tải toàn bộ agents và edges

- **Vị trí:** [Store.get_box](../../apps/leta/src/leta/store.py:444); metadata callers ở [schedule targets](../../apps/leta/src/leta/http/schedules.py:20), [workspace factory](../../apps/leta/src/leta/filesystem/workspace.py:135), [box home](../../apps/leta/src/leta/temporal/lifecycle_activities.py:198).
- **Hiện tại:** cả `details=False` vẫn chạy ba SELECT, lấy toàn bộ child agent rows, gồm prompts, và edges. Flag chỉ điều khiển việc lấy thêm runs/requests/schedules.
- **Case:** kiểm tra box có tồn tại, status hoặc home-node ID cũng trả giá theo kích thước graph. `save_box_change` ở nhánh archived còn tải cùng graph lần nữa khi `box["letis"]` đã có sẵn.
- **Đề xuất:** làm thao tác đọc metadata thực sự nhẹ, graph/detail loading là thao tác có tên rõ ràng cho callers cần nó; tái sử dụng dữ liệu đã đọc trong cùng activity. Migrate tất cả callers, tránh thêm nhiều flag kết hợp.
- **Nếu giữ:** extra SQL và bytes theo số Leti/edges trên nhiều boundary. Test metadata query count không phụ thuộc graph size và giữ detail view/recovery acceptance.

### 3. Pause/resume tải deletion snapshot rồi bỏ kết quả

- **Vị trí:** [Store.set_paused](../../apps/leta/src/leta/store.py:357), [_snapshot](../../apps/leta/src/leta/store.py:538), [workflow pause/resume](../../apps/leta/src/leta/temporal/lifecycle.py:117).
- **Hiện tại:** `_snapshot` đọc agents, boxes, schedules và requests. `set_paused` ghi đè `agent_ids` bằng một SELECT khác; consumer pause/resume chỉ dùng danh sách agents này.
- **Case:** pause agent có nhiều schedules/HITL/history phải dựng danh sách phục vụ deletion dù không thực hiện deletion.
- **Đề xuất:** giữ root lock/update và query active agents; trả snapshot với default empty lists cho phần không dùng. Không đổi `_snapshot` của deletion/archive.
- **Nếu giữ:** bốn query và nhiều UUID thừa cho mỗi pause/resume; chúng còn làm payload Local Activity lớn hơn. Giữ tests paused root, new box, resume, archive và replay.

### 4. Schedule self-target kiểm tra cùng admission hai lần

- **Vị trí:** [create_schedule](../../apps/leta/src/leta/store.py:1378), [update_schedule](../../apps/leta/src/leta/store.py:1457), [_agent_gate](../../apps/leta/src/leta/store.py:148).
- **Hiện tại:** creator/requester và target đều gọi `_agent_gate` dù cùng agent và cùng transaction.
- **Case:** root tự đặt reminder khóa/đọc cùng root hai lần. Leti tự đặt reminder lặp cả root, child/box lookup và child lock; không có mutation giữa hai gate làm điều kiện thay đổi.
- **Đề xuất:** gate actor một lần; gate target riêng khi target khác actor. Giữ schedule ownership checks, root-first lock order và teardown exception.
- **Nếu giữ:** thêm SQL trong các thao tác schedule thông thường. Kiểm tra cả self-target, parent→representative, denied peer, concurrent deletion và retry.

### 5. Hai query API chỉ còn sống nhờ tests

- **Vị trí:** [list_roots](../../apps/leta/src/leta/store.py:332), [list_conversation](../../apps/leta/src/leta/store.py:874); [test pagination](../../apps/leta/tests/test_store_integration.py:706), [messaging recovery assertion](../../apps/leta/tests/test_messaging.py:183).
- **Hiện tại:** rà AST bằng Python 3.14 và search cả production/tests/fixtures/config không thấy production caller. Public reads đã dùng `api_roots` và `api_messages` với actor filtering khác.
- **Case:** `test_keyset_reads_do_not_fetch_lifetime_history` vẫn kiểm tra pagination của hai method đã nghỉ thay vì các đường API thực tế; assertion hiện tại cũng không đo số row đọc hay query cost.
- **Đề xuất:** bỏ hai methods sau khi chuyển assertions sang active read paths và bổ sung đúng actor/cursor conditions. Giữ mục tiêu recovery của messaging test; chỉ đổi cách quan sát stored output.
- **Nếu giữ:** phải bảo trì 33 dòng method body cùng các assertions không bảo vệ production reads. `list_runs` có ba test callers phục vụ recovery/counting; có thể chuyển thành test utility hoặc giữ có chủ đích, không xóa assertions chỉ để giảm source.

### 6. Hai cơ chế mark-read đang kiểm thử semantics khác nhau

- **Vị trí:** [Store.list_inbox](../../apps/leta/src/leta/store.py:789), [runtime helper](../../apps/leta/src/leta/runtime/messaging.py:240), [tool wrapper](../../apps/leta/src/leta/runtime/tools.py:303), [atomic publication](../../apps/leta/src/leta/store.py:898).
- **Hiện tại:** helper mặc định `mark_read=True` và Store có nhánh write-on-read. Production tool luôn truyền `False`; IDs được đánh dấu cùng transaction lưu tool result qua `append_activity`.
- **Case:** một số assertions trong `test_messaging` và `test_store_integration` xác nhận side effect ngay khi helper read, còn hành vi production chủ ý chờ tool result được lưu để tránh mất unread input khi crash.
- **Đề xuất:** bỏ option/nhánh write-on-read không có production consumer; reads thuần đọc. Chuyển assertions sang actual tool-result persistence boundary, giữ foreign-agent rollback và lost-result recovery tests.
- **Nếu giữ:** hai cơ chế cùng ownership cho `read_at`, và tests tiếp tục củng cố đường cũ. Không được xóa atomic marker implementation đang bảo vệ recovery.

## Nice to have

### 7. Hai timeout setup calls trong mọi transaction có thể gộp

- **Vị trí:** [Store.transaction](../../apps/leta/src/leta/store.py:119).
- **Hiện tại:** mỗi read hoặc mutation gửi riêng hai `SET LOCAL` trước business query. Đây là chi phí cố định, không phải bằng chứng API đang chậm.
- **Đề xuất:** kiểm chứng một execute chứa hai lệnh cố định với `prepare=False` trên psycopg đang pin; giữ transaction-local semantics. Không chuyển timeout thành global setting hoặc thêm config/cache.
- **Nếu giữ:** thêm một cursor execute mỗi transaction. Chỉ ưu tiên sau các query thừa rõ ràng phía trên; chưa có end-to-end latency benchmark để hứa mức tăng tốc.

### 8. Tạo graph dùng per-row INSERT RETURNING dù bỏ kết quả

- **Vị trí:** [create_box child/edge loops](../../apps/leta/src/leta/store.py:421), [insert helper](../../apps/leta/src/leta/store.py:63).
- **Hiện tại:** mỗi Leti và edge gọi `insert`, helper luôn `RETURNING *` rồi `fetchone`; cả hai loops bỏ returned row. Với V agents và E edges có V+E execute/fetch pairs ngoài việc tạo box.
- **Case:** tạo box nhiều Leti/edges phải nhận lại child rows gồm prompts vừa gửi và edge rows không dùng. Đây là xử lý thừa xác định từ source; chưa có latency/load measurement cho graph lớn.
- **Đề xuất:** benchmark hai nhóm `AsyncCursor.executemany(..., returning=False)` trong cùng transaction cho child agents và edges, giữ deferred foreign keys, identity conflict và whole-graph rollback. psycopg 3.3.8 đang cài hỗ trợ API này; không cần dependency hoặc bulk-repository abstraction.
- **Nếu giữ:** thừa payload/fetch và send overhead theo V+E. Không hứa loại bỏ O(V+E) database work; batch vẫn phải ghi từng row. Chỉ chọn implementation sau khi đo và kiểm chứng collision rollback.

## Ý tưởng refactor cấu trúc sau cleanup

`Store` giữ một connection pool nhưng đang sở hữu lifecycle/configuration, graph, messaging, transcript, runs, HITL, schedules và API reservations/read models. Đổi một quy tắc schedules phải hiểu cả SQL locking, `NewSchedule`, HTTP admission và Temporal compiler. `fault` ở đầu file lại được import từ nhiều tầng không cần persistence; `schedules.py` import nó cục bộ trong khi Store import compiler ngược lại.

Đề xuất nhỏ trước: chuyển helper lỗi thuần nghiệp vụ sang owning module trung lập hiện có, migrate callers cùng lúc; giữ validation thuần và native Temporal compilation có trách nhiệm rõ. Sau findings 2–6 mới quyết định tách persistence schedules/HITL theo nghiệp vụ nếu vẫn giảm reader load. Không tạo BaseRepository, generic service, dependency-injection framework, mixins hoặc lớp forwarding để chia file.

Không gộp tất cả Schedule DTO chỉ vì giống field: public input hỗ trợ relative time và typed spec; stored definition phải canonical; public view có forecast fields. Có thể dùng một canonical definition/projection chung khi giữ đúng ba hợp đồng này, nhưng chưa có bằng chứng cần thêm abstraction.

## Các đề xuất bị loại sau kiểm tra

| Nghi ngờ | Bằng chứng giữ nguyên |
| --- | --- |
| Xóa `spec_key` như backward-compat | Nó so sánh native Temporal range/default normalization hiện tại, không duy trì app schema cũ; tests native schedule dùng nó để giữ consumed one-shot state. |
| Bỏ patch serializers | Chúng giữ omitted khác explicit null qua Pydantic/Temporal round trip; tests schedule end_at/configuration bảo vệ semantics này. |
| Xóa compatibility tests | Các test kiểm tra LangGraph saver, Mirage/Monty/Redis và SDK đang dùng; tên compatibility không có nghĩa legacy. |
| Xóa double-read trong `receive` | Query thứ hai nằm sau admission locks và là recheck cho concurrent identical delivery; có real concurrency regression. |
| Gộp create/update/delete admission | Delete phải cleanup được resource đang deleting; create/update vẫn cần active guards. |
| Xóa checkpoint continuation columns | Runtime không dùng tất cả như resume authority, nhưng owning docs chủ ý giữ continuation/checkpoint metadata. Đây là quyết định hợp đồng dữ liệu, không phải dead field được phép xóa tự động. |
| Xóa tests không có `assert` | Các negative tests dùng `pytest.raises`; contract-ref traversal thất bại bằng KeyError khi ref dangling. Chúng có assertion behavior thực. |
| Bỏ generic `insert`/`one`/`rows` | Helpers nhỏ đang dùng thật, giữ parameterized SQL/identifier handling và error semantics; chưa thấy abstraction thừa ở đây. |

## Trình tự đề xuất

1. Sửa finding 1 bằng regression HTTP+SQL riêng.
2. Cleanup 5 và 6 cùng các assertions/callers tương ứng.
3. Giảm overfetch/query thừa ở 2, 3 và 4; thêm focused query-count checks, giữ integration và replay.
4. Cân nhắc 7 sau đó, benchmark 8 nếu graph creation đáng ưu tiên; chỉ thực hiện extraction cấu trúc nếu vẫn có lợi ích cụ thể sau cleanup.

Mỗi PR giữ API/schema và toàn bộ behavior hiện hữu, ngoại trừ lỗi retention được sửa rõ ràng. Không migration, dependency mới hoặc compatibility shim được đề xuất trong batch đầu.

Verdict: ưu tiên bỏ đường xử lý thừa và đưa tests về đúng production boundary trước khi chia Store.

Lean: có thể bỏ 33 dòng method body của hai API hết consumer, cộng nhánh mark-read cũ sau khi migrate tests; chưa ước lượng net diff. Không cần bỏ hoặc thêm dependency.

Not checked: audit sâu runtime engine, toàn bộ LetFS/Workspace/Account/ingest và operational source thuộc các chặng tiếp theo; chưa đo tải production hoặc paid-provider quality.
