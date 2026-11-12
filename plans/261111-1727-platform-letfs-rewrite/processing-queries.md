# Processing, transfer và maintenance SQL

Dùng [schema](schema.md), [S/I budget](query-design.md) và [LetFS RPC matrix](letfs-queries.md). Ingest không có database. RPC signatures/workspace-storage fields theo [API contract](api-contract.md); sáu processing operations giữ nguyên và không có HTTP binding. Signed S3 transfer/model/embedding/Qdrant calls nằm ngoài transactions.

## 1. Sáu processing RPC

| RPC | S business SQL | Set-based query | Lock/atomicity |
|---|---:|---|---|
| `GetProcessingInput` | 1 | Source R + current stage/version + recursive artifact text/blob inventory | Read only; sign source/artifact URLs từ object keys đã có |
| `PrepareArtifactUploads` | 2 | Source R; bulk INSERT upload handles bằng recordset | Version admission; không SQL mỗi output, không upload trong transaction |
| `CommitParse` | 2 | R + source files row lock; bulk handles validation/consume + node/file INSERT + quota/stage DML | Current source/version + stage pending; retry parsed-or-later no-op |
| `CommitEnrichment` | 2 | R + source files row lock; bulk artifact text/metadata UPDATE/UPSERT + quota/stage DML | Stage parsed -> enriched; retry enriched-or-later no-op |
| `CompleteIndex` | 1 | Conditional processing UPDATE FROM source/version/live-root resolver | Stage enriched -> ready; no file version bump |
| `FailProcessing` | 1 | Conditional error UPDATE FROM source/version/live-root resolver | Không làm ready lùi lại hoặc reset last successful stage |

Rows/bytes xử lý tăng theo số artifacts, số statements không tăng. DML shapes có thể tách khi code dễ đọc hơn, nhưng phải tính lại budget thật; không ẩn N statements sau method tên BatchCommit.

## 2. Input/publication

GetProcessingInput dùng source current version và stage để chỉ trả dữ liệu activity cần: pending cần source descriptor; parsed/enriched cần current artifact inventory để enrich/index. Stage ready trả done, không serialize toàn tree. Chỉ lấy text_content khi CPU/IO cần bytes, không mỗi node một GET/ReadText.

PrepareArtifactUploads nhận batch expected bytes/media/checksum. INSERT SELECT từ một source/version admission; object keys do LetFS cấp. Source thay đổi sau admission thì old handles hết admissible ở CommitParse; chúng expire/GC, không lease giữ source trong lúc worker upload.

CommitParse first query khóa đúng source files row và xác minh live source/version. DML tiếp theo nhận manifest recordset và handle IDs; một join uploads kiểm tra source_file_id/source_version, storage, expiry, object key/size/checksum của toàn batch. Ingest là trusted internal writer và đã nhận S3 PUT acknowledgement; không HEAD từng output lại tại service. Source upload từ user vẫn verify S3 metadata ở CompleteUpload vì đó là trust boundary khác.

Node IDs cấp một lần và parent IDs map theo manifest trong memory; validate paths/parent structure tại boundary. INSERT all nodes/files bằng recordsets, không per-path mkdir. Text vào PostgreSQL; blob vào issued object references. Stage và quota cập nhật cùng transaction. Consume đúng upload IDs bằng DELETE trong transaction đó.

CommitEnrichment chỉ cần source lock một lần. Join batch artifact IDs với current source ancestry ở SQL; UPDATE text/version/size và UPSERT file_metadata theo tập. Source metadata copy từ root README trong cùng input/DML, không fetch README qua RPC rồi SELECT source một lần nữa. Delta lấy old/new sizes của chính rows đổi. Source version không tăng.

SQL publication error rollback stage/artifacts/quota cùng nhau; source retained. Error summary ghi bằng FailProcessing sau native activity retry policy; không fail/report/abort từ nhiều wrapper layers. Không jobs/attempt/checkpoint-per-chunk tables.

## 3. CompleteIndex / FailProcessing

Shape (live resolver là CTE cùng statement):

```sql
UPDATE processing p SET stage='ready',error_code=NULL
FROM files f,live_source s
WHERE p.file_id=f.node_id AND f.node_id=s.id
  AND f.node_id=$1 AND f.version=$2 AND p.stage='enriched'
RETURNING p.file_id,p.stage;
```

Để stage write và replace cùng serialize đúng source, statement khóa source files row trong live_source trước UPDATE processing. CTE dùng SELECT FOR UPDATE OF source file, không entire artifact tree. FailProcessing tương tự chỉ ghi error_code khi version còn đúng và stage <> ready. Wrong version/missing/deleted là obsolete, không requeue source cũ.

Ready duplicate có thể trả done từ stage đọc trong cùng CTE; không cần second lookup trên every success. No index-ready flag/version thứ hai.

## 4. Source upload

CreateUpload R(target/parent) một lần; nếu multipart thì gọi native create ngoài SQL; INSERT descriptor sau đó. Blob chưa publish không debit quota. Abort provider failure chỉ để lại garbage sẽ được native lifecycle/GC dọn; không durable abort journal.

CompleteUpload first SELECT đúng upload ID kiểm tra actor/storage/expiry; nếu result đã có trả stored publication, không Stat node hiện tại. Với open upload: native multipart finalize/HEAD/checksum/size trước transaction. Sau đó source file lock nếu replace, hoặc parent R nếu tạo mới; lock upload row, recheck result/expiry; publish content/quota/result cùng một DML phase. Thứ tự source -> upload -> quota tránh invert với processing.

result là receipt thật; hoàn thành upload rồi node bị edit/delete vẫn trả publication identity đã lưu. `expires_at` khi open là admission deadline, sau complete là receipt retention deadline. Không completed node ID/status/complete timestamp trùng trong bảng. Completed row không phải active GC reference; files.object_key mới là reference lâu dài.

SignParts đọc transfer một lần rồi native presign list parts trong memory. Không transaction, HTTP S3 request hoặc DB row cho từng part. Parts receipts do CompleteUpload gửi một batch cho native multipart complete.

## 5. Maintenance queries

| Việc | SQL/page | Network | Cách giới hạn |
|---|---:|---|---|
| Recover workspace provisioning/deletion | 1 batch SELECT state/IDs | Native Start workflow mỗi admitted workspace cần recover | Index lifecycle nếu sweep sử dụng; không re-read từng row |
| Recover blob processing | 1 batch stage/version/live-ancestry SELECT | Native Start ProcessBlob theo stable ID | Partial processing index; không Stat/file_content per file |
| Expire open uploads/receipts | 1 DELETE batch RETURNING multipart descriptors | Best-effort native abort ngoài SQL | expires_at index; result NULL phân biệt open |
| Expire idempotency keys | 1 DELETE batch theo expiry PKs | Không | LIMIT qua CTE; không table-wide sweep giữ lock lâu |
| Object GC reference check | 1 SELECT cho batch S3 keys | Native ListObjectsV2 + DeleteObjects batch | Chỉ keys đủ grace; files và live open uploads indexed EXISTS |
| Qdrant stale/storage cleanup | 1 batch SQL hydrate source/file IDs/versions/live storage | Native Qdrant scroll/delete/set-payload batch | Không point SQL loop; không reparse/re-embed khi chỉ move |

Object GC không chỉ kiểm tra files mà bỏ active uploads:

```sql
SELECT k.object_key
FROM unnest($1::text[]) k(object_key)
WHERE NOT EXISTS (SELECT 1 FROM files f WHERE f.object_key=k.object_key)
  AND NOT EXISTS (
    SELECT 1 FROM uploads u WHERE u.object_key=k.object_key
      AND u.result IS NULL AND u.expires_at>now()
  );
```

Native S3 listing đã lọc LastModified đủ grace trước khi gửi batch SQL. Không bảng refcount hoặc object deletion state. GC không debit quota; quota chỉ thay đổi khi SQL publication/purge thay logical files. Error một page thì lần schedule sau thử lại, không checkpoint framework.

Workspaces provisioning/deleting recovery không cần user onboarding fields. Artifact dispatch chỉ source processing rows; unsupported/text/artifact blobs không có row nên không mở workflow con.
