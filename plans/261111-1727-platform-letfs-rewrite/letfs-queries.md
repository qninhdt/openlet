# LetFS: query targets theo storage/workspace

Cập nhật 2026-11-12. [API contract](api-contract.md) là inventory đã chốt; [schema](schema.md) và [workspace resources](workspace-service-redesign.md) đã chốt. Không dùng matrix 31 workspace/admin cũ. SQL examples dưới là query shapes sau đổi tên, chưa chạy EXPLAIN hoặc implementation.

## 1. API ownership và read targets

GetWorkspaceStorage/UpdateStorageQuota đọc/đổi workspace_storage theo workspace_id. List/Get/UpdateStorages và access management thuộc LetFS, không Platform proxy. List lookup/candidate + bulk permissions rồi SQL metadata batch; bulk capabilities cho cards, không per-storage owner reads. Access screen mới đọc direct owner/grants.

Node/content/search/trash/upload methods và bounds giữ [API proposal](api-contract.md). Một resolver cho tất cả locators cần request; one storage check hoặc native bulk cho distinct storages/actions, không per-node checks/SQL. Mutation RETURNING/receipt, không Stat readback.

## 2. ID resolver

ID lookup dùng ancestor CTE chỉ đọc PK links. CTE dưới là shape SQL với named placeholders để giải thích; implementation dùng positional pgx parameters. `parent_id` NULL không tự nghĩa là live root.

```sql
WITH RECURSIVE chain AS (
  SELECT n.id,n.parent_id,n.kind,0 AS depth
  FROM nodes n
  JOIN storages s ON s.id=n.storage_id
  JOIN workspace_storage fs ON fs.workspace_id=s.workspace_id
  WHERE n.id=:node_id AND n.storage_id=:storage_id
    AND fs.workspace_id=:workspace_id
  UNION ALL
  SELECT p.id,p.parent_id,p.kind,c.depth+1
  FROM chain c JOIN nodes p ON p.id=c.parent_id
  WHERE p.storage_id=:storage_id
), valid AS (
  SELECT bool_or(c.id=s.root_node_id) AS storage_live,
         bool_or(c.id=coalesce(:mount_root,s.root_node_id)) AS within_mount,
         bool_or(c.depth>0 AND c.kind='file') AS readonly
  FROM chain c JOIN storages s ON s.id=:storage_id
)
SELECT n.id,n.parent_id,n.name,n.kind,n.created_at,n.updated_at,
       f.version,f.size_bytes,f.media_type,
       (f.text_content IS NOT NULL) AS is_text,
       m.title,m.description,m.semantic_type,p.stage,p.error_code,v.readonly
FROM valid v
JOIN nodes n ON n.id=:node_id AND n.storage_id=:storage_id
LEFT JOIN files f ON f.node_id=n.id
LEFT JOIN file_metadata m ON m.node_id=n.id
LEFT JOIN processing p ON p.file_id=n.id
WHERE v.storage_live AND v.within_mount;
```

Nếu method không cần metadata/processing thì bỏ joins đó; ReadText thêm text_content vào đúng target projection. Đừng chuyển header SELECT thành helper load toàn bộ payload để mọi API dùng chung.

BatchStat dùng input `unnest(ids) WITH ORDINALITY`, chain mang input ordinal/target/root. Một statement; công việc O(batch × ancestor depth), không giả vờ O(1). Row không đạt live/mount không trả metadata, không chỉ gắn readonly=false rồi vẫn trả nó.

Path lookup có statement riêng để planner dùng sibling index. Absolute path bắt đầu từ mount root đã xác minh; relative path xác minh cwd/root trong cùng statement rồi recursive walk từng component. `..` không được vượt root rồi quay lại. Trả provenance trong cùng R, không SELECT theo từng segment ở Go. Không đưa OR id/path vào mọi branch của một query khổng lồ.

## 3. ListNodes

R xác minh parent là directory hoặc source blob được phép browse artifacts. Carry readonly flag vào children: child readonly nếu parent đã readonly hoặc parent.kind=file. Không ancestor query riêng cho mỗi child.

```sql
SELECT r.id AS resolved_parent,c.id,c.name,c.kind,c.updated_at,
       f.version,f.size_bytes,f.media_type,(f.text_content IS NOT NULL) AS is_text
FROM resolved_parent r
LEFT JOIN LATERAL (
  SELECT n.id,n.name,n.kind,n.updated_at
  FROM nodes n
  WHERE n.storage_id=:storage AND n.parent_id=r.id
    AND (n.name,n.id)>(:after_name,:after_id)
  ORDER BY n.name,n.id LIMIT :limit_plus_one
) c ON true
LEFT JOIN files f ON f.node_id=c.id;
```

Sibling name unique nên `(name,id)` stable tie-break; index cover name order. First page bỏ cursor predicate. Empty directory vẫn có resolved_parent row nhờ LEFT LATERAL, phân biệt empty và invalid locator mà không query nữa. Không recursive size/count cho từng item; response không có embedded artifact trees mặc định.

ReadTree dựng relative paths và readonly từ traversal nhẹ chỉ ID/kind/path/depth. ORDER BY/LIMIT max_nodes+1 trước, rồi hydrate headers của tối đa max_nodes bằng một SELECT batch. Hai statements cố định, không N+1. Nếu response có limit, báo truncated/continuation theo contract; outer LIMIT không đủ để hứa sort/recursive work là O(page_size). Không xây tree toàn workspace cho Stat/ListNodes.

## 4. Content mutation

R của MutateText JOIN files và `FOR UPDATE OF f` đúng target. Một lần đọc text; Go validate/apply patch/append/truncate và tính new bytes. Với expected_version, check trên locked row. Không đọc text để đếm/hash rồi đọc lại để patch.

```sql
WITH changed AS (
  UPDATE files SET text_content=$2,size_bytes=$3,version=version+1
  WHERE node_id=$1 AND text_content IS NOT NULL AND version=$4
  RETURNING node_id,version,size_bytes
), touched AS (
  UPDATE nodes SET updated_at=now()
  WHERE id IN (SELECT node_id FROM changed)
  RETURNING id,name,updated_at
)
SELECT c.node_id,c.version,c.size_bytes,t.name,t.updated_at
FROM changed c JOIN touched t ON t.id=c.node_id;
```

Quota conditional UPDATE có thể đặt cùng write CTE, lấy delta từ old size đã đọc trong R. Không row changed/quota thì rollback cả transaction/receipt. Unchanged bytes trả header đã có, không tăng version hay update counter. SQL statements của quota được tính nếu implementation tách nó; không che vào helper rồi giữ budget 2.

Blob replace lock cùng files row với processing commit. Trong write phase: xóa old generated subtree/metadata, set immutable object_key mới, tăng source version, reset processing, cập nhật quota bằng new source size − old source/artifact bytes. Không phát workflow trong transaction; native Start sau commit và recovery sweep lo admission bị lỡ.

## 5. CreateDirectories, MoveNode, CopyNode

CreateDirectories không request_id/receipt: mkdir-p tự lặp được. Resolve longest existing prefix bằng một recursive indexed query. Tạo UUIDs cho missing suffix, bulk INSERT toàn chain bằng unnest/recordset với parent mapping. Existing final directory thì trả ngay. Unique conflict do concurrent mkdir làm rollback; retry ordinary operation sẽ resolve prefix mới. Không per-component round trip hoặc no-op UPSERT toàn existing chain.

MoveNode batch-resolve source/destination trong một R. Cycle check dùng destination ancestor chain đã đọc, không một query DFS source subtree chỉ để tìm destination. Same-storage move chỉ UPDATE root parent/name. Cross-storage move recursive UPDATE storage_id của subtree, giữ IDs/bytes; deferred composite parent FK kiểm tra cuối transaction. File version/quota/processing không đổi. Native SERIALIZABLE chỉ cho transaction này; serialization failure trả conflict.

CopyNode resolve endpoints một lần; one recursive copy DML:

1. `tree`: source rows, recurse khi parent.kind=directory để bỏ generated descendants trong ordinary copy.
2. `mapping AS MATERIALIZED`: mỗi old ID -> một UUID mới, parent map được tính đúng một lần.
3. `inserted_nodes`: INSERT SELECT mapped tree, RETURNING nodes.
4. `inserted_files`: INSERT SELECT payload/version=1, tham chiếu inserted_nodes RETURNING để dependency rõ; text ở database, object_key share.
5. `new_processing`: eligible source blobs của copy nhận stage, không stage clone từ source.
6. `quota`: cộng SUM(size_bytes) từ inserted_files RETURNING; nếu zero-row rollback.
7. Response root từ inserted_nodes/files RETURNING và input đã biết; save I result rồi commit.

Không `SELECT * FROM nodes WHERE new_id=...` trong cùng DML CTE vì snapshot không thấy INSERT qua base table. Không object copy/HEAD theo node, SELECT metadata từng item hoặc RETURNING tất cả text về app. SQL tự copy payload; response chỉ root header. File metadata của artifacts copy-out có thể copy set-based; source processing outputs không clone rồi lại xóa để parse.

## 6. Search và index

SearchFiles dùng `name LIKE/ILIKE :escaped_literal_pattern` + pg_trgm, storage filter và keyset ID trên candidate page. `%`, `_`, escape character của user được escape để giữ literal semantics. Candidate batch walk ancestors kiểm tra storage/mount/live và file ancestor, rồi hydrate một query. Không preload cây rồi grep Go.

TextSearch files mode tương tự, `files.text_content LIKE/ILIKE` với partial GIN predicate `text_content IS NOT NULL`, join nodes storage; SELECT chỉ snippet/headers cần trả. Lines mode đọc một file một lần rồi Go chọn literal matching lines, không cần GIN hoặc query metrics riêng.

Candidate LIMIT trước ancestry có thể cho short/empty page. Cursor đi theo last candidate examined; không báo complete chỉ vì filtered results ít hơn limit. Dùng ordinary keyset cursor, không server-side cursor table/state. Không lặp SQL theo từng candidate để lấp page. Term dưới 3 ký tự có thể không được trigram giúp nhiều: storaged bounded scan là giới hạn MVP, không viết search engine mới hoặc hứa mọi literal đều index seek.

SemanticSearch: Qdrant trả candidate batches gồm file ID, source ID và source version. Một SQL nhận arrays/recordset, JOIN files source current version, nodes/storages và tagged ancestry. Chỉ trả artifact thực sự thuộc source, còn live và trong requested mount/storage; ready/enriched policy theo indexing setting. Point stale/deleted/moved storage bị lọc trước reranking. Payload text của point không được trả chỉ vì vector match. Không SQL mỗi point, không ancestor walk hai lần để xác minh cùng provenance.

Embedding/model/Qdrant ngoài SQL. Nếu filter làm thiếu results, có thể trả ít hơn requested top_k; không thêm unbounded fetch/refill vòng lặp ở MVP.

## 7. Trash/purge và accounting

TrashNode R chặn root/artifact writes. Một DML CTE UPDATE root parent=NULL RETURNING old parent từ resolved input rồi INSERT trash entry. Không đánh dấu descendants, đổi name hoặc chạm quota.

Restore/Purge dùng `DELETE trash_entries ... USING nodes/storages ... RETURNING` để claim occurrence. Không SELECT FOR UPDATE rồi DELETE cùng row. Restore destination lỗi thì rollback trả lại entry. Occurrence đã hết trả NOT_FOUND; không tác động lần trash mới hoặc tự tìm node theo tên.

Purge DELETE đúng node set và tính byte từ chính rows DELETE thành công. Payload FK cascade không được khiến accounting đọc SUM sau khi files đã biến mất:

```sql
WITH RECURSIVE doomed AS (
  SELECT id,storage_id FROM nodes WHERE id=$1 AND storage_id=$2
  UNION ALL
  SELECT n.id,n.storage_id FROM nodes n JOIN doomed d
    ON n.parent_id=d.id AND n.storage_id=d.storage_id
), deleted AS (
  DELETE FROM nodes n
  USING doomed d LEFT JOIN files f ON f.node_id=d.id
  WHERE n.id=d.id
  RETURNING coalesce(f.size_bytes,0) AS size_bytes
)
UPDATE workspace_storage
SET used_bytes=used_bytes-(SELECT coalesce(sum(size_bytes),0) FROM deleted)
WHERE workspace_id=$3
RETURNING used_bytes;
```

Node parent FK deferred NO ACTION, payload FK cascades. Original-parent restore hint không cascade nên separately trashed child không bị purge theo parent cũ. Shared objects không DELETE S3 tại purge; GC kiểm tra actual references sau grace.

## 8. Storage administration

ProvisionWorkspaceStorage INSERT budget theo workspace_id. CreateStorage dùng ordinary ID được giữ trong provisioning input; local INSERT storage/root và graph writes idempotently, không personal mapping/UUIDv5/owner uniqueness. DeleteStorage/DeleteWorkspaceStorage cleanup local rows/graph, native S3/Qdrant maintenance dọn physical leftovers. Không chờ Leta stop ACK.

Visibility canonical SQL, public_workspace relation ở graph; UpdateStorage native durable retry cho đúng cross-store operation. Quota/ordinary metadata mutation local SQL; role mutation native graph. Không transaction giữ SQL locks qua graph/gRPC/provider.

Current public/internal matrix ở API contract, không GetFilesystem/EnsureScopes/ListScopes hoặc Platform scope grants. Native VFS gửi locator trực tiếp, không pre-Stat hoặc response readback.
