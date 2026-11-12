# Thiết kế truy vấn cho rewrite

Cập nhật 2026-11-12. [Workspace resources](workspace-service-redesign.md)/[schema](schema.md) là boundary đã chốt; [API contract](api-contract.md) đã chốt. Các inventories cũ 20/31/6 không còn authority. Đây là target budgets, chưa measurements.

[Platform](platform-queries.md), [LetFS](letfs-queries.md), [processing](processing-queries.md). Role/ownership/grants canonical SpiceDB, PostgreSQL domain data; không personal mapping hoặc SQL membership mirrors.

## 1. Budget được tính thế nào

`S` là số SQL business statements ở success path, tính trên toàn request, gồm resolve/hydrate nhưng chưa gồm `BEGIN`, `COMMIT`, idempotency helper. `I` là hai statements claim/finalize khi RPC dùng persisted request key. Duplicate path là claim + đọc receipt, không chạy domain mutation. `BEGIN`/`COMMIT` thêm hai protocol operations vào transaction.

`R` là một SQL statement resolve tất cả locators cần cho request; CTE của R có thể nằm trong SELECT/DML chính. Mỗi tài liệu nói rõ R được gộp hay thực thi riêng. Đây là budget mục tiêu để implementation đối chiếu, chưa phải số đo query của source mới.

Số statements không đồng nghĩa số lượt mạng: native `pgx.Batch` gom các statements không cần kết quả trung gian từ Go; statements có phụ thuộc giữ tuần tự. Không gọi `SendBatch` rồi ngầm coi mọi query là một database operation. Report riêng statements, round trips, returned rows/bytes và thời gian transaction.

Graph/provider calls được ghi riêng. Một SpiceDB RPC có thể chạy nhiều datastore queries; tài liệu không giả định 1 RPC = 1 SQL trong SpiceDB. Idempotency table cũng là query thật, không loại khỏi số đo request.

## 2. Quy tắc thực hiện

1. Native authentication và một lần resource authorization admission trước transaction. Khi cần nhiều storage/actions, dùng một `CheckBulkPermissions`, deduplicate exact tuples trong request. Read và mutation mặc định `minimize_latency`; dùng optional ZedToken khi cần read-after-write, không ép `fully_consistent`.
2. Storage đã biết từ request: SQL join `storages -> workspace_storage` cùng resolver, xác minh actual workspace_id và row existence. Không thêm GetStorage/header query trước mỗi thao tác chỉ để xác minh lại cùng parent.
3. Resolver trả target, parent/root provenance, artifact source/readonly và file header khi cần. Không resolve lại, walk ancestors lại để tìm ownership, hoặc đọc file lần hai để lấy size/version đã có.
4. Read không dùng row/advisory lock. Một SELECT dùng snapshot mặc định; không mở transaction chỉ để Stat/List. Network S3/graph/model/Temporal không nằm trong SQL transaction đang giữ lock.
5. Mutations dùng short `READ COMMITTED` transaction, trừ native `SERIALIZABLE` riêng cho MoveNode để bảo vệ cycle check. Serialization failure rollback và trả conflict; không thêm retry engine/lock manager.
6. Mutation response lấy từ `RETURNING` và input đã xác minh. CTE DML đọc kết quả qua `RETURNING`, không SELECT base table trong cùng statement rồi giả định thấy row vừa INSERT. Không gọi Stat/readback sau commit.
7. Batch theo tập: `ANY(uuid[])`, `unnest`, `jsonb_to_recordset`, INSERT SELECT, UPDATE FROM. Không SQL, RPC metadata hoặc authorization call trong vòng lặp nodes/artifacts/members.
8. Project đúng fields: Stat/List không SELECT text_content; đọc bytes không kéo toàn bộ metadata JSON. Không `SELECT *` trên files hoặc node/file joins ở hot path.
9. Không count toàn bộ để paginate. Dùng keyset + `LIMIT page_size+1`; total count chỉ khi sản phẩm thực sự yêu cầu. Không OFFSET cho page tăng dần.
10. Không ép mọi endpoint thành một CTE khổng lồ. Mục tiêu là làm đúng lượng việc cần thiết, ít round trips và ít lock time; 2 query có index có thể tốt hơn 1 query materialize cả workspace.

## 3. Lock budget

| Tình huống | Lock cần thiết | Thời gian |
|---|---|---|
| Read/list/search/download manifest | Không explicit row lock | Một statement/snapshot |
| Text read-modify-write | `FOR UPDATE OF files` đúng một target file | Từ đọc text đến content/quota/receipt commit; xử lý text nhỏ ở Go |
| Blob replace và processing commit | Cùng source `files` row | Chỉ SQL publication/version/stage; không parse/upload/model |
| Upload complete | Đúng upload row; thêm source file khi replace | Sau S3 metadata verification |
| Trash restore/purge | `DELETE trash_entries ... RETURNING` tự claim đúng occurrence | Trong short local transaction |
| Quota | Row lock tự nhiên từ conditional UPDATE một workspace storage | Ở cuối write phase; không SELECT FOR UPDATE workspace storage từ đầu |
| Duplicate request | Native unique-key/row contention của đúng receipt | Cùng transaction mutation |
| Move | Native SERIALIZABLE, DML locks trên rows được move | Resolve/cycle check + set-based update; không workspace storage/ancestor advisory lock |

Không `FOR UPDATE`/`FOR SHARE` toàn cây để đọc copy/archive; không lock ancestors theo từng cấp. Bulk DELETE/UPDATE đương nhiên khóa các row nó thực sự đổi; đây không phải lý do thêm vòng SELECT FOR UPDATE trước nó.

Content flows cùng tuân thứ tự khi có nhiều loại row: source `files` trước, upload handles sau, workspace storage quota cuối. Không giữ quota row trong lúc hydrate tree, đọc text hoặc dựng response. Native deadlock/serialization error làm rollback; không catch rồi tiếp tục transaction đã lỗi.

Move là ngoại lệ có chủ đích: ancestor check và parent update phải giữ cây không cycle giữa các move đồng thời. Dùng isolation native cho transaction này, thay vì mua correctness bằng lock cả workspace storage. Không đổi toàn hệ thống sang SERIALIZABLE.

Danh sách trên là giới hạn locking của phần viết lại. Không thêm application mutex, distributed/advisory lock, lock table, lock manager hoặc polling chờ unlock. Platform không SELECT FOR UPDATE workspace/member để serialize graph calls; native SQL uniqueness/conditional DML và SpiceDB writes xử lý đúng phạm vi của chúng. Muốn thêm loại khóa ngoài budget này phải có invariant cụ thể bị vi phạm và bằng chứng, rồi thảo luận thay đổi thiết kế.

Không application lease cho worker, processing, upload, quota hoặc maintenance; không owner/lease_until, renewer hoặc fencing epoch/generation. uploads.expires_at là hạn sử dụng transfer/receipt để cleanup, không giữ độc quyền file hoặc reserve quota. Temporal dùng timeout/heartbeat/retry/Schedule native; không dùng activity heartbeat như bằng chứng chỉ có một worker đang thực thi.

Chống kết quả ingest cũ chỉ dùng files.version hiện có: activity mang file_id/version; publication khóa đúng source row rồi kiểm tra version và processing stage trong cùng transaction. Version sai thì không publish; stage đã commit thì replay/no-op. Đây là version guard, không token fencing độc lập và không giữ khóa suốt lúc parse/model/upload. Qdrant points mang source/version, SQL lọc dữ liệu stale khi search; không khóa xuyên SQL/S3/Qdrant.

Quota atomic tạo một điểm tuần tự hóa thật: các write có delta bytes trong cùng workspace cùng UPDATE một counter row. Khóa này chỉ ở cuối SQL phase; rename/move/trash/restore và delta=0 không chạm counter. Đây là trade-off của quota chính xác đã chọn, không thể hứa không contention. Phải đo lock wait/transaction duration trên workload bình thường trước acceptance; không tự thêm reservation/sharding/counter framework để xử lý tải giả định.

## 4. Index và constraint tối thiểu

Tên field dưới đây là tên SQL dự kiến. Mọi index phải có query owner. PK đã là index; không tạo thêm index trùng PK/unique.

### Platform

| Index/constraint | Query owner |
|---|---|
| users PK(id), UNIQUE(clerk_subject) | GetMe, Onboard, batch member profiles |
| workspaces PK(id) | LookupResources hydrate, detail/update/lifecycle |
| invitations PK(id), UNIQUE(token_hash) | Revoke/accept token |
| invitations(workspace_id,id) | ListInvitations keyset |
| workspaces(state,id) WHERE state <> 'active' | Provisioning/deletion recovery batch |
| idempotency_keys PK(caller,method,key), INDEX(expires_at) | Claim/replay/cleanup |

Không personal mapping/index: storage ownership ở graph, IDs UUID thông thường; nhiều storage/owner.

Không index workspaces.name, user email/profile JSON hoặc mọi invitation flag khi không có query tương ứng. Không workspace_members/role mirror index vì role nằm ở graph.

### LetFS

| Index/constraint | Query owner |
|---|---|
| workspace_storage PK(workspace_id) | Header/quota/lifecycle |
| storages PK(id), INDEX(workspace_id,id), UNIQUE(root_node_id) | Batch storage list và root lookup |
| nodes PK(id), UNIQUE(storage_id,id) | ID resolve, composite parent FK |
| nodes UNIQUE(storage_id,parent_id,name) WHERE parent_id IS NOT NULL | Sibling lookup/name conflict/list by name; detached trash roots không tranh tên live |
| files PK(node_id) | One-to-one metadata/text joins |
| files(object_key) WHERE object_key IS NOT NULL | GC reference existence; không unique vì copy share object |
| file_metadata PK(node_id) | Batch metadata joins |
| processing PK(file_id) | Stage CAS/publication |
| processing(stage,file_id) WHERE stage <> 'ready' | Pending/recovery sweep |
| trash_entries PK(id), UNIQUE(node_id) | Restore/purge exactly one occurrence |
| trash_entries(trashed_at DESC,id DESC) | Trash keyset trước join storage/live workspace storage |
| uploads PK(id), INDEX(expires_at) | Transfer expiry và completed receipt cleanup |
| uploads(object_key) WHERE result IS NULL | GC active reference check, thêm expiry predicate khi đọc |
| idempotency_keys PK(caller,method,key), INDEX(expires_at) | Claim/replay/cleanup |
| GIN nodes.name gin_trgm_ops | Filename substring search |
| GIN files.text_content gin_trgm_ops WHERE text_content IS NOT NULL | Literal text search |

`pg_trgm` là native PostgreSQL extension. Không tạo cả GIN full text, trigram và vector SQL index cho cùng text khi MVP chỉ cần literal search. Không thêm metadata.title index trước khi SearchFiles thật sự hỗ trợ search title và đo nhu cầu.

Sibling index cũng phục vụ `WHERE storage_id=? AND parent_id=? ORDER BY name`; không thêm index parent_id riêng khi mọi child query đã mang storage_id. Composite parent FK `(storage_id,parent_id)` tham chiếu `(storage_id,id)`, deferred NO ACTION để cross-storage subtree move/purge làm một transaction. `files`, `file_metadata`, `processing` dùng native FK cascade theo node/file; quota phải lấy từ rows node thực sự DELETE trước khi payload cascade mất.

Trash page chỉ theo storage không có denormalized storage column trong trash_entries: index time để page chung, join nodes(storage_id) và filter. Nếu EXPLAIN thực tế cho thấy storage trash lớn bị lọc nhiều thì đổi query/index theo kết quả đó; chưa thêm storage mirror chỉ để tránh một join. Live child list không cần anti-join mọi descendant với trash table: chỉ có trash root bị detach.

Processing dispatch index không chứng minh node live. Recovery vẫn batch-validate root connectivity, không chạy riêng Stat cho mỗi file.

## 5. Idempotency SQL

Hai statements ở first execution là claim và finalize. Domain SQL ở giữa. `result` chỉ NULL trong transaction chưa commit; không có durable pending state/status/poller.

```sql
INSERT INTO idempotency_keys(caller, method, key, request_hash, result, expires_at)
VALUES ($1,$2,$3,$4,NULL,now()+$5::interval)
ON CONFLICT (caller,method,key) DO UPDATE
SET request_hash=EXCLUDED.request_hash, result=NULL, expires_at=EXCLUDED.expires_at
WHERE idempotency_keys.expires_at <= now()
RETURNING caller;
```

Nếu không có row RETURNING: SELECT request_hash,result của đúng PK ở statement kế tiếp; so hash và replay. PostgreSQL READ COMMITTED nhận snapshot mới sau khi unique conflict chờ transaction đầu commit. Không dùng CTE `INSERT DO NOTHING UNION SELECT` rồi giả định SELECT luôn thấy row concurrent vừa thắng.

```sql
UPDATE idempotency_keys SET result=$4
WHERE caller=$1 AND method=$2 AND key=$3;
```

Finalize lưu protobuf response nhỏ. Authorization/claim vẫn xảy ra trước expected_version lần đầu; duplicate không chạy content precondition lần nữa. Cleanup TTL DELETE theo batch có limit qua CTE PK, không full-table DELETE không giới hạn.

## 6. Quota SQL

Quota chỉ update khi delta khác 0. Directory/rename/trash/restore/move không chạm workspace storage counter. Copy/parse tính delta từ inserted files; purge từ node rows thực sự bị xóa; replace trừ artifacts cũ cùng transaction.

```sql
UPDATE workspace_storage
SET used_bytes=used_bytes+$2
WHERE workspace_id=$1
  AND used_bytes+$2 >= 0
  AND ($2 <= 0 OR used_bytes+$2 <= quota_bytes)
RETURNING used_bytes,quota_bytes;
```

Cho phép shrinking nếu operator từng hạ limit dưới used; không chặn người dùng giải phóng dung lượng. Zero updated row làm rollback toàn mutation; không commit row/file rồi báo quota error. Không SELECT used_bytes rồi so bằng Go và ghi absolute counter. Không tính lại SUM toàn workspace storage trên mỗi write.

## 7. Kiểm tra performance trước acceptance

Instrumentation dùng pgx tracer/OTel sẵn có để đếm SQL và duration; native EXPLAIN (ANALYZE,BUFFERS), pg_stat_statements và pg_locks cho điều tra khi cần. Không port framework inventory/probe/SQL rewriting cũ.

Một fixture thường dùng gồm nhiều storage, root/nested/trash/artifact nodes và cả text/blob; payload realistic. Chạy vài case đại diện: Stat/ReadText, page ListNodes, selective search, BatchStat, copy, text append, artifact commit và purge. So page 10 với 100 và copy/artifacts nhỏ với lớn: số statements/network calls không tăng theo số items; rows/work được tăng theo dữ liệu thực sự đọc/đổi.

Kiểm tra plan không scan toàn workspace storage để Stat một ID hoặc list một parent; không SELECT text khi chỉ list; không UPDATE ancestors trên append. Không ép planner dùng index khi seq scan thực sự rẻ hơn trên fixture nhỏ. `LIMIT` ngoài recursive CTE không tự bảo đảm recursion/sort chỉ làm page_size rows.

Concurrency proof chỉ cho invariants có thật: duplicate append không ghi đôi; quota growth cạnh tranh không vượt limit; processing cũ không publish; move không tạo cycle. Ghi lock wait/transaction duration. Đây là vài integration cases, không matrix mọi interleaving.

Chỉ ghi latency/p95 hoặc tốc độ cải thiện khi có thực thi thật trên workload/env nêu rõ. SQL mẫu chưa được EXPLAIN/benchmark, không chứng minh gRPC/auth/provider/CI performance. Kết quả thực nghiệm sau implementation phải ghi workload/env và không thay thế test source mới.
