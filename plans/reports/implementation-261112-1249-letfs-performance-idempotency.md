# LetFS: sửa hiệu năng và audit idempotency

Ngày 2026-11-12, từ baseline `222902e`. Thuộc [plan core](../261111-1727-platform-letfs-rewrite/plan.md), tiếp nối [benchmark 43 RPC](benchmark-261112-1212-letfs.md). Không sửa runtime/plan Leta của agent khác.

## Thay đổi đã duyệt

- Single locator dùng `jsonb_to_record` thay cardinality mặc định 100 rows của `jsonb_to_recordset`. BatchStat và ZIP nhiều target giữ recordset; không tách query mỗi target.
- ReadTree traverse ID/kind/path/depth/readonly, sort/limit trước rồi hydrate headers theo batch. Hai SELECT cố định; không còn hydrate cả subtree trước limit. Vẫn traverse/sort các ID cần thiết để giữ path ordering.
- GetProcessingInput traverse IDs/path với storage-parent index hiện có, rồi hydrate headers/text/object keys một batch. Hai SELECT cố định; không index/config/cache mới.
- Rename-only: check permission và một UPDATE RETURNING; không Temporal, request ID hay PostgreSQL receipt.
- CreateDirectories: bỏ request ID và receipt; mkdir-p chỉ INSERT missing suffix, retry trả directory hiện tại. Giữ transaction cho atomic chain insertion.
- Visibility: giữ request ID/workflow dedup, bỏ SQL receipt/transaction/SELECT readback. Activity UPDATE RETURNING rồi TOUCH/DELETE native graph. User chấp nhận không kiểm cùng request ID khác payload bằng SQL.
- SignParts nhận batch `{part_number, checksum}` CRC32C base64 (4 byte), validate số part/duplicates và ký checksum qua AWS SDK. Trả actual signed headers cùng URL, dùng chung header extraction với single PUT. CompleteUpload vẫn verify checksum/size, không đổi provider hay tắt integrity checks.

API fields bỏ được reserve number/name; generated Go/Python/descriptor được regenerate. Callers và owning API/query docs đồng bộ, không compatibility wrapper. Các client cũ phải regenerate và gửi payload SignParts mới.

## Audit toàn bộ cơ chế idempotency active

Đã rà source apps Platform/LetFS/ingest và handwritten SDKs; loại archive và runtime Leta đang hoãn. Không áp dụng receipt cho mọi mutation theo hình thức.

| Owner / operation | Kết luận | Lý do thực tế |
|---|---|---|
| LetFS rename | Bỏ receipt và request ID requirement | SET name lặp được; một UPDATE đủ |
| LetFS CreateDirectories | Bỏ receipt và request ID | mkdir-p đọc/tạo missing directories, reuse existing IDs |
| LetFS visibility activity | Bỏ PostgreSQL receipt | SET desired state + graph TOUCH/DELETE lặp được; workflow giữ command identity |
| LetFS CreateNode | Giữ Claim/Finish | Allocate ID và content/quota, cần replay response |
| LetFS MutateText | Giữ Claim/Finish | RPC có append/patch và version/quota effects; expected_version không replay kết quả |
| LetFS MoveNode | Giữ Claim/Finish | Path/cross-storage locator cũ không còn resolve sau move; retry cần original response |
| LetFS CopyNode | Giữ Claim/Finish | Allocate subtree/IDs, cộng usage và dispatch blob processing |
| LetFS TrashNode | Giữ Claim/Finish | Detach khỏi live root và tạo trash occurrence; locator cũ không còn live |
| LetFS CreateUpload | Giữ Replay rồi Claim/Finish | Tạo session/object key/multipart ngoài SQL; replay không cấp session mới |
| LetFS CompleteUpload | Giữ uploads.result | Upload ID là identity, atomic publication/quota + response; không general receipt thứ hai |
| LetFS internal storage provisioning | Giữ resource PK và ON CONFLICT | IDs cấp một lần trong workflow input, retry không tạo storage/root khác |
| LetFS ProcessBlob | Giữ workflow file_id/version + SQL stage/version | Tránh publish artifacts/quota lặp khi activity retry; không request-key receipt |
| Ingest ParseBlob / EnrichAndIndex | Giữ native Temporal retries và publication stage checks tại LetFS | Ingest không DB, không local receipt ledger |
| Ingest vector indexing | Giữ deterministic point IDs / upsert | Retry không nhân đôi vectors; không SQL ledger |
| Platform CreateInvitation | Giữ Claim/Finish | Tạo invitation/token mới; replay invitation identity, plaintext token chỉ response đầu |
| Platform internal CreateWorkspace | Giữ SQL admission receipt + stable workflow ID | Bind generated workspace identity và payload qua activity retries |
| Platform Onboard | Giữ workflow subject identity + unique clerk_subject | Retry không tạo user/workspace mới; không generic request ID |
| Platform member-storage provisioning | Giữ workflow workspace/user/request identity | Hoạt động tạo storage có generated ID trong workflow input, cần tránh cấp lặp |
| Platform invite acceptance | Giữ consume invitation identity | Retry không regrant membership đã revoke; không receipt mới |
| Platform workspace deletion | Giữ native workflow identity + deleting phase | Retry cleanup cùng resource, absent là done |
| Native desired-state setters | Không receipt | Profile/workspace name/quota, graph access/grants/revoke/ownership, deletes dùng UPDATE hoặc native graph set/delete/preconditions |
| LetFS restore/purge/abort | Giữ domain identity / desired state hiện có | Trash occurrence/upload ID ràng buộc thao tác; không thêm request ledger |
| Maintenance / schedules | Giữ native overlap Skip và bounded cleanup | Không parallel application lease/fencing/dedup tables |
| Shared receipt SDK | Giữ helper nhỏ + expiry cleanup | Vẫn có các caller cần Claim/Replay/Finish; không middleware tự áp receipt |

Không thêm locking/leasing/fencing, distributed transaction, outbox hay idempotency cache. Retention receipt/workflow vẫn hữu hạn; đây không phải global exactly-once. Hai thay đổi visibility ngược chiều đồng thời vẫn theo accepted async desired-state semantics, không thêm serialization cho rare races.

## Verification

- `make check test`: Go tests/vet/gofmt, Ruff, Buf lint, TypeScript và shell syntax pass; ingest 15 tests pass. Có 13 deprecation warnings từ dependency LangSmith như baseline.
- `make generate` chạy lại: không generated drift.
- Existing `TestStorageSQLInvariants` pass trên DB mới đã backup trước fixtures; thêm assertion cho batch processing text/path/readonly.
- Final full API E2E **4/4, 40,9s phần Playwright**. Existing journeys thêm rename không request ID, mkdir-p reuse, visibility workflow/replay, multi-target ZIP và multipart 20 MiB qua actual signed URLs/headers, complete và download bytes. Không thêm suite/integration harness vào CI.
- Lượt E2E đầu bắt multi-target ZIP vẫn dùng single resolver trong image đã build; caller đã chuyển về batch resolver, build mới và full E2E cuối pass. Không bỏ assertion hoặc che lần fail.
- Targeted benchmark **21 nhóm / 3.045 timed native gRPC requests / 0 lỗi**, thêm ba warm-up mỗi nhóm. 8 RPC được đo timing; baseline 43 RPC vẫn là report trước, không tuyên bố đã benchmark lại tất cả. BatchStat kiểm 1/10/100 và giữ 1 SQL/request; ReadTree/GetProcessingInput 2 SQL/request, rename 1 SQL/request. CreateDirectories reuse có 2 business SELECT/DML + BEGIN/COMMIT, không ledger.
- Không sửa DB cũ hoặc dotenv thật. E2E và benchmark dùng hai Compose projects/volumes mới, backup trước fixtures; đã teardown cả containers/networks/volumes. Không commit/push/deploy trong task này.

Benchmark executable/raw data chỉ ở ignored `.local/bench-letfs/`, không source/CI. Evidence sau sửa: `after/summary.json`, `after/results.jsonl`, `after/explain.json`, `after/integration.log`; logs `.local/letfs-fixes-{check,final-check,e2e-final,generate,benchmark}.log`. Full stack dùng PostgreSQL/SpiceDB/Temporal/RustFS/Qdrant thật, E2E dùng model/JWKS fixtures. Benchmark chỉ start core services như baseline, không ingest CPU/IO. Không đổi PostgreSQL config/index, default permission consistency hoặc quota/version guards.

## Kết quả trước/sau

P95 native gRPC, ms; cùng máy local và fixture shape tương đương, đây là hai lượt độc lập trên máy dùng chung, không capacity/SLA production. Nhóm 10k có flat 10.000 files; follow-up thêm 15.000 unrelated files như targeted baseline. n=80/320 cho 10k c1/c32; n=40 follow-up/rename.

| Case | c | Trước p95 | Sau p95 |
|---|---:|---:|---:|
| Stat ID, 10k | 1 | 8,98 | 5,80 |
| Stat ID, 10k | 32 | 60,42 | 31,53 |
| ListNodes 100, 10k | 32 | 70,46 | 32,96 |
| BatchStat 100, 10k | 32 | 100,64 | 59,26 |
| ReadTree 1000, 10k | 1 | 54,96 | 60,35 |
| ReadTree 1000, 10k | 32 | 454,91 | 457,43 |
| ReadTree 10, larger follow-up | 1 | 69,01 | 16,16 |
| ReadTree 1000, larger follow-up | 1 | 81,49 | 37,20 |
| GetProcessingInput 100 artifacts, larger follow-up | 1 | 91,37 | 8,04 |
| UpdateStorage rename | 1 | 48,47 | 2,70 |

GetProcessingInput 500 artifacts sau sửa p95 17,08 ms; không so trực tiếp baseline 500 vì tổng dataset khác. EXPLAIN sau sửa: source/artifact traversal 100 có 0 temp blocks và không JIT (baseline query có 1.682 temp blocks, JIT khoảng 36 ms), batch hydrate cũng không temp/JIT. Single-ID Stat query EXPLAIN 0,663 ms execution; planning mới 3,423 ms không được cộng/trộn với warm RPC timing.

ReadTree larger follow-up giảm rõ, nhưng 10k/1000-node c32 vẫn khoảng 457 ms, c1 tail chưa giảm. Traversal/sort/path order và serialize response lớn vẫn còn chi phí; không tuyên bố đã giải quyết toàn bộ tail latency hoặc tự đổi API/add cache. Không thêm index/locking/fencing để theo đuổi số này trong scope đã duyệt.

## Multipart diagnosis và giới hạn

Contract trước không nhận checksum khi ký UploadPart và không trả signed headers; thêm checksum header ngoài chữ ký bị RustFS từ chối. Ký checksum bằng native SDK và gửi đúng URL/headers đã complete thành công trên RustFS 1.0.5: E2E download đúng 20 MiB và benchmark upload/complete 8 objects (3 warm-up, 5 timed completes). Timed CompleteUpload p50 85,30 / max 108,20 ms; không tính upload bytes vào thời gian RPC, n=5 không đủ ước lượng p99. Không quy mọi HTTP 500 của RustFS cho cùng một internal cause; đã chứng minh luồng contract mới hoạt động và giữ integrity checks.

Chưa benchmark WAN/provider production, soak dài hạn hoặc SLA/VPS. Client cũ cần regenerate: CreateDirectories bỏ request_id; SignParts đổi part_numbers sang parts có checksum và dùng returned headers. Visibility không còn SQL same-key/different-payload conflict detection theo quyết định user.
