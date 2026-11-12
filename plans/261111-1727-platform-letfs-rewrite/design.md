# Kiến trúc rewrite: Platform và LetFS

Cập nhật 2026-11-12. [Workspace resources](workspace-service-redesign.md) là authority đã chốt cho ownership/storage/roles/SpiceDB; [schema](schema.md) đã reconcile. [API Platform/LetFS](api-contract.md) và Temporal mục 10 đã chốt qua trao đổi; API/runtime/multiple storage Leta hoãn, Computer design-only. Đang implementation; [plan](plan.md) ghi validation và phần chưa hoàn thành.

[Tổng hợp](final-proposal.md), [plan](plan.md), [config](configuration.md), [telemetry](telemetry.md). Không còn phương án SQL-only hoặc owner/membership mirror trong application SQL.

## 1. Kết quả cần đạt

Viết mới `apps/platform` thay Account + Workspace, viết mới `apps/letfs`, `apps/letfs-ingest`, và toàn bộ phần đang hoạt động trong `packages/`. Archive nguyên trạng Account, Workspace, LetFS, ingest và các thư mục con hiện tại của `packages/`, gồm cả thay đổi chưa commit. Archive chỉ để tham khảo ngữ cảnh; không lấy implementation hay test từ đó sang code mới.

Leta giữ domain, model, agent runtime, lưu trữ và cơ chế thực thi hiện tại; chỉ sửa boundary và shared dependencies. Letfs-ingest được đưa vào phạm vi viết lại: giữ hai loại worker CPU/IO, khả năng parse Office/PDF, artifact hierarchy, enrichment và semantic indexing, nhưng thay orchestration, transfers và cấu trúc module.

Chọn thiết kế ít cơ chế nhưng hoàn thành các thao tác sản phẩm đang có. Chi phí cho authorization, tính toàn vẹn dữ liệu, quota và bí mật vẫn cần thiết. Không mua thêm độ hoàn thiện bằng cơ chế xử lý mọi lịch sử retry, mọi interleaving hoặc mọi kích thước cây.

Không làm: backward compatibility; adapter cho API cũ; operation framework; event bus/outbox tổng quát; repository interfaces; command bus; distributed locks; per-node workflows cho CRUD/copy/delete; snapshot/epoch/lease; tự chế transport; tối ưu nội bộ Leta; billing/frontend mới.

## 2. Bằng chứng khảo sát

- Account gọi workflow tạo Workspace rồi mới publish Clerk identity. Workspace lại gọi Account để lấy profile/email. Gộp hai service xóa được hai vòng giao tiếp này.
- API public Account/Workspace đang ở HTTP; native proto của chúng chỉ bao phủ vài API nội bộ. Viết lại phải định nghĩa đủ public RPC, không chỉ đổi listener.
- LetFS có đồng thời gRPC và grpc-gateway trong process, nhiều API đọc cùng locator, nhiều lớp upload/publication, receipt và cleanup.
- SQL đang giữ membership role/status trong khi SpiceDB cũng giữ role relationships. Đây là nguồn của projection, receipt, rebuild và workflow serialize quyền.
- Ingest thực sự đang gọi prepare/output-upload/complete theo từng output. Không thể giữ consumer đó rồi tuyên bố đã xóa API cũ.
- Go workflow đang truyền parse/enrich output lồng nhau, Python activities vẫn nhận `{file_id,generation}`. Boundary hiện tại chưa đồng nhất.
- Leta cần discovery mounts, creator/home identity, personal-storage approval, cleanup và native storage operations. HTTP/SSE của Leta nằm ngoài đợt viết lại.
- Không thấy webhook nhận vào trong HTTP routers Account/Workspace hiện tại. Clerk được gọi như một API phía ngoài.

Nguồn: [kiến trúc hiện tại](../../docs/architecture.md), [hợp đồng hiện tại](../../docs/api-contracts.md), [RPC cũ đã archive](../../archive/2026-11-11/packages/contracts/rpc-surface.md), migrations và source cũ. Đây là bằng chứng về chức năng cần giữ, không phải chỉ thị giữ implementation cũ.

## 3. Topology và ownership

Workspace tenant ở Platform chứa nhiều storage (LetFS), agent (Leta), Computer (tương lai). Platform quản lý user/workspace/membership/invitations; LetFS tự quản storage discovery/access/quota/content. Không Platform storage proxy/mapping hoặc cross-service SQL/FK.

SpiceDB canonical membership/ownership/grants; PostgreSQL owning service giữ domain metadata. Root agent là subject độc lập, không human member; Computer giữ subject của invocation khi đọc/ghi file. Ingest CPU/IO là processing workers không ACL database.

Platform/LetFS startup/readiness và permission hot path không phụ thuộc Leta. Resource cleanup business calls bất đồng bộ được phép, không chờ Leta stop ACK trước storage deletion. Concrete Leta API/transport vẫn hoãn; không scaffold listener/config/Computer runtime trong lượt này.

Redis/agent runtime nội bộ Leta không thành dependency của Platform/LetFS. Parent workspace_id là metadata, không biểu diễn chiều bắt buộc gọi API.

## 4. Transport cuối cùng

Platform và LetFS chỉ có gRPC listener cho application API, kèm standard gRPC health. Public JSON/HTTP được Envoy transcode từ `google.api.http`; không có Gin, grpc-gateway hay HTTP business handler trong hai service.

Proto là nguồn contract. Generate Go/Python stubs và descriptor cho Envoy. Public HTTP dùng ProtoJSON: int64 là decimal string, bytes là base64, enum theo proto, lỗi là `google.rpc.Status` với một `ErrorInfo.reason` khi cần. Bật native `convert_grpc_status`; body Status trực tiếp, HTTP status map từ gRPC code, không outer error envelope. Không tái tạo RFC9457, ETag/If-Match và response DTO của API cũ. Content version precondition là field của request. [HTTP examples và giới hạn gateway/stream](http-json.md) ghi rõ application/json không phải application/problem+json, cùng local replies không được normalize tự động.

| Luồng | Thiết kế |
|---|---|
| Account/workspace/node CRUD | Unary gRPC; Envoy JSON transcoding |
| Text read/write | Unary protobuf string/bytes theo thao tác; PostgreSQL TEXT là storage duy nhất |
| Blob upload/download, Range | Signed S3 transfer; LetFS chỉ cấp descriptor và complete upload |
| ZIP | `DownloadArchive -> stream google.api.HttpBody`; HTTP nhận ZIP bytes trực tiếp qua Envoy |
| Browser SDK tương lai | Generated HTTP client hoặc gRPC-Web qua Envoy khi có consumer; không tạo thêm transport backend |
| Health | Standard gRPC health; Envoy kiểm tra upstream |
| Metrics/tracing | OTLP outbound và Envoy telemetry; không dựng app HTTP listener chỉ cho probe |
| Leta HTTP/SSE | Giữ nguyên, route riêng không đi qua transcoder của Platform/LetFS |
| Clerk/S3/model/Qdrant protocol | Dùng protocol SDK/provider hiện tại; không bọc lại thành service mới |

ZIP không cần materialize vào S3 hay tạo job. Chụp danh sách entry cần đọc bằng một query/transaction ngắn, đóng transaction, rồi stream bytes. Rename trong lúc tải không làm restart hoặc khóa cây. Nếu đọc bytes thất bại, stream lỗi/ZIP không hoàn chỉnh và người dùng tải lại. Không hứa snapshot archive xuyên suốt một cây đang bị sửa. Service giữ object immutable và GC grace để phần lớn download đang chạy hoàn tất tự nhiên.

Envoy chính thức hỗ trợ server-streaming HttpBody: <https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/grpc_json_transcoder_filter#sending-arbitrary-content>. Cần một smoke trên image Envoy được pin khi triển khai; chưa chạy ở lượt đề xuất này.

### Authentication

- Envoy xác minh Clerk JWT, xóa trusted headers do client gửi, gắn subject và user ID đã xác minh.
- MVP application services tin cậy private network, không service Bearer credential. Gateway-header/typed actor contract giữ danh tính người dùng đã được Envoy verify; không coi metadata là service authentication.
- Bootstrap RPC chỉ nhận verified Clerk subject, chưa yêu cầu application user ID. Các RPC human khác yêu cầu user ID.
- Native callers nằm trong mạng private, không có caller credential registry/allowlist hoặc TLS wiring ở MVP. Production thêm native mTLS và restrictions dựa trên verified workload identity khi cần; không đổi business schema/proto.
- Actor mang identity để kiểm tra resource authorization, tách biệt với caller process. Actor user/agent theo workspace-service-redesign.md; API/transport Leta còn hoãn; không lấy lifecycle/creator của Leta làm authority tại core. Private processes được tin cậy; MVP không thể xác minh process nào đã gửi actor hoặc chặn nó gọi internal administration. Không đưa untrusted workloads/client vào mạng này. Tích hợp bên ngoài ở đây là boundary ứng dụng, không phải cho phép workload không tin cậy vào private network.
- Internal administration/processing không có public HTTP annotation; Envoy không route native internal service paths từ Internet. `auto_mapping` tắt.
- User authentication ở Envoy; typed metadata parsing ở boundary, resource permission ở method xử lý. Validation input tại boundary, constraint tại database. Không lặp lại cùng validation trong SDK, handler, service, store và response parser. Native dependency credentials vẫn được giữ.

## 5. Platform

[Schema](schema.md) có users/workspaces/invitations/idempotency_keys. Không storage/shared/personal-storage IDs, personal mapping, workspace_members role table, quota/usage hoặc agent metadata SQL.

Workspace có owner/member, owner chuyển được bằng graph mutation; invitation chỉ member. MVP CreateWorkspace là system/internal provisioning qua Onboard, không client self-service create workspace. Membership/grant authority SpiceDB; no onboarding flags hoặc special initial workspace ID.

API inventory hiện tại lấy từ [API contract](api-contract.md), không từ matrix cũ. Resource listing/access ở LetFS; Platform chỉ identity/workspace/members/invitations và generic CheckWorkspaceActive. Bỏ RegisterAgent/UnregisterAgent; Leta tự quản lý agent.workspace/workspace.agent. Add/accept member có thể provision storage qua owning service, không cấp deterministic owner-derived ID hoặc giữ personal mapping.

Create/delete workspace dùng native lifecycle state/workflow đã có. Revoke quyền trước cleanup. Async Leta/Computer cleanup không chặn storage deletion hoặc hot path; API Leta vẫn hoãn.

## 6. SpiceDB

[Owning authorization design và full Zed](workspace-service-redesign.md#5-schema-spicedb-dự-kiến) đã chốt user/workspace/storage/agent/computer types. Workspace owner/member; storage owner/editor/viewer; agent owner/operator; Computer manager/operator. Không generic role/grant/principal entity.

Public storage mặc định read cho human owner/member và agents thuộc cùng W qua public_workspace và workspace.agent; private theo direct/inherited owner/editor/viewer. Không SQL visibility read từ SpiceDB hoặc per-member grant fan-out. Parent/public projection writes do owning service thực hiện.

Native Check/BulkCheck cho authorization, ReadRelationships khi UI cần assigned roles, LookupResources/candidate+bulk cho lists; không local permission cache hoặc N+1 owner reads. Authority SQL+graph không atomic, native durable retries cho multi-store lifecycle. Permission checks mặc định minimize_latency, optional ZedToken read-after-write; không forced fully_consistent mọi mutation. Không validate lại Zed theo yêu cầu user.

## 7. LetFS: dữ liệu và thao tác

### Tách cây khỏi nội dung và trạng thái xử lý

| Bảng | Nội dung |
|---|---|
| `workspace_storage` | workspace_id PK, quota_bytes/used_bytes; one budget cho workspace |
| `storages` | id, workspace_id, name, visibility private/public, root node ID và blob/index policy |
| `nodes` | chỉ identity/cây: id, storage_id, parent_id, name, kind, created_at, updated_at |
| `files` | node_id, version, size_bytes, media_type, text_content hoặc object_key; API file_type suy từ payload |
| `file_metadata` | node_id, title, description, semantic_type, context; chỉ có row khi đã có enrichment |
| `processing` | source file_id, stage, error; chỉ có row cho source blob được xử lý |
| `trash_entries` | trash occurrence ID, detached root node_id, original parent, actor và timestamp |
| `uploads` | actor, storage, target, immutable object key, expected bytes/checksum, multipart ID nếu có, expiry, publication response để replay |
| `idempotency_keys` | key, caller/method storage, request hash, result và expiry cho SQL mutations |

Không gộp payload, AI metadata và processing vào nodes. `nodes.kind=directory|file`; file có một row files, API expose file_type=text|blob suy từ payload, không cột SQL discriminator trùng. Đúng hai loại:

| File type | Storage | Ingest |
|---|---|---|
| `text` | PostgreSQL `text_content TEXT` | Không chạy pipeline cho file text người dùng tạo/upload |
| `blob` | S3 `object_key` | Chỉ source blob được hỗ trợ, khi tạo mới hoặc replace nội dung |

Không dùng thuật ngữ inline text, object file hoặc office file như loại thứ ba. Office/PDF/image/binary là các media type bên trong loại blob. Không còn inline binary/BYTEA payload, text trên S3 hoặc fallback text sang S3 theo kích thước.

Text upload gửi nội dung tới LetFS qua gRPC rồi ghi PostgreSQL. API có thể nhận explicit file_type; route upload thông thường nhận diện các định dạng text được hỗ trợ, validate UTF-8 không NUL, giữ nguyên BOM/CRLF/trailing bytes. Text vượt giới hạn trả lỗi rõ ràng; không âm thầm đổi loại. Default binary, Office và image đi S3. Không sniff arbitrary binary thành text chỉ vì giải mã UTF-8 được.

Giữ giới hạn text hiện tại ở MVP, bao gồm representation cần cho Mirage. Không xây chunked text-upload engine. Database mới không import dữ liệu cũ; không thêm legacy payload fallback.

Text có filename search và literal text search trực tiếp; không enrichment, embedding hoặc semantic-index pipeline ở MVP. Blob không được parser hỗ trợ vẫn upload/download bình thường và có processing not-supported; không bịa artifact.

Giữ constraints thực: same-storage parent, unique live sibling name, payload exclusivity, positive files.version và nonnegative size/quota. Không custom trigger framework.

Artifact ownership lấy từ cây: ordinary files không nhận user-created children; chỉ CommitParse/CommitEnrichment được tạo children dưới source blob. Node có ancestor file là generated artifact. Resolver vốn đã duyệt ancestors để kiểm tra live root nên trả luôn source owner/readonly, không thêm một pass hoặc cache. Không cần artifact table hay generated_by/source_generation columns trên mọi node. Artifact subtree luôn thuộc current content của source; replace content xóa subtree cũ trong cùng transaction.

Chỉ có một counter `files.version`, tăng khi nội dung file thay đổi. Text edit và blob replacement đều tăng version; rename/move/ACL không tăng. Pipeline nhận source file ID + version; CommitParse/CommitEnrichment chỉ hợp lệ nếu source vẫn có version đó. Cập nhật processing stage, AI metadata hoặc artifact tree không tăng version của source, nên pipeline không tự vô hiệu hóa nó. Artifact text được sửa ở bước enrichment thì version của chính artifact text tăng bình thường.

Không còn nodes.revision hay counter generation riêng. Processing row không có version counter thứ hai; nó thuộc current files.version và reset cùng transaction replace content. `version` dùng cho content concurrency và processing identity; idempotency key dùng nhận diện request lặp, hai mục đích khác nhau.

Trong files chỉ có hai payload columns nullable loại trừ nhau: text_content có giá trị với text, object_key có giá trị với blob; CHECK giữ đúng một payload. Empty text hợp lệ. Không lưu file_type/storage_kind trùng với payload discriminator; API vẫn expose text/blob. Directory không có files row; chưa enrich không có file_metadata row; text không có processing row. Hash/newline metrics tính bằng standard library khi cần. Listing join files/metadata khi cần, không dựng ORM/repository layers cho từng bảng.

Cache representation có thể dùng file version cho bytes và updated_at/processing stage cho metadata; các owning writes cập nhật timestamp trong cùng transaction. Không duy trì thêm global node revision hoặc hash toàn cây.

### CRUD và locators

- Một resolver phục vụ ID hoặc path/cwd; optional mount root phục vụ Leti sandbox.
- ID lookup dùng một ancestor CTE để xác nhận node còn nối tới live storage/mount root. Path lookup đi từ root đó. Đây là kiểm tra cây thực cần có để raw ID không đọc lại trash; không tách thành nhiều pass, cache hoặc observation protocol.
- `Stat` là metadata/resolve chuẩn. `BatchStat` thực sự cần cho consumer thì giữ. Xóa các biến thể GetNode/ResolveNode/TextMetrics độc lập khi đã có cùng thông tin trong Stat/ReadText.
- `ReadText` giữ byte/line/head/tail selection cần cho Mirage; `MutateText` giữ overwrite/append/patch/truncate. Không thêm operation registry hay reusable mutation pipeline.
- Text mutation dùng idempotency key để không áp dụng lặp; expected_version là precondition riêng khi caller chỉnh từ một bản nội dung đã đọc. Overwrite chủ động có thể theo last successful write nếu caller không yêu cầu precondition. Không node revision hoặc observed-ID protocol; semantics cụ thể ở mục 9.
- Giữ `ReadTree`, `TextSearch`, `ReadImage` vì Leta có consumer thật. `TextSearch` chỉ literal search; không xây grep/regex engine. Tận dụng text query/index PostgreSQL đang cần, không có search cursor protocol riêng.
- Permission, live storage, mount root, readonly artifact, no-overwrite name, cycle và quota là các check thật. Không giữ kiểm tra response exact-set/hash/fingerprint lặp lại trong SDK.

| Nhóm RPC LetFS | Các thao tác giữ lại |
|---|---|
| Metadata/tree | `Stat`, `BatchStat`, `ListNodes`, `ReadTree`, `CreateNode`, `CreateDirectories`, `MoveNode`, `CopyNode` |
| Bytes/tools | `ReadText`, `MutateText`, `ReadImage`, `GetDownload`, `DownloadArchive` |
| Search | `SearchFiles`, `TextSearch`, `SemanticSearch` |
| Trash | `TrashNode`, `ListTrash`, `RestoreTrash`, `PurgeTrash` |
| Transfers | `CreateUpload`, `GetUpload`, `SignParts`, `CompleteUpload`, `AbortUpload` |
| Processing control | Status trong `Stat`; automatic trigger chỉ khi source blob được tạo/replace nội dung |
| Storage/access, public | `GetWorkspaceStorage`, `UpdateStorageQuota`, `ListStorages`, `GetStorage`, `UpdateStorage`, `ListStorageAccess`, `SetStorageAccess`, `RevokeStorageAccess` |
| Administration, private | `ProvisionWorkspaceStorage`, `CreateStorage`, `DeleteStorage`, `DeleteWorkspaceStorage` |

`MoveNode` bao gồm rename và move; content replacement đi qua small-payload write hoặc complete upload. Không giữ alias RPC của API cũ chỉ để gọi lại API mới.

### Transactions và quota

Một mutation là một local SQL transaction. Thay đổi quota bằng conditional `UPDATE used_bytes=used_bytes+delta WHERE ...<=quota_bytes`; dùng row lock tự nhiên của UPDATE. Có thể khóa đúng file đang sửa nội dung nếu cần read-modify-write. Không khóa ancestors hoặc cả storage từ đầu request, không giữ transaction trong lúc gọi S3/AI.

Node count tính khi đọc metadata nếu cần; không duy trì thêm hot counter chỉ để tiết kiệm một query hiếm. Quota tính theo logical bytes, kể cả trash và bản copy dùng chung object. Không reservation/lease quota; complete upload có thể bị từ chối quota, và object dư được GC sau.

### Copy: SQL và immutable objects

Object đã publish không bao giờ ghi đè. Copy trong cùng workspace sao chép node rows, text content và object key references; không S3 CopyObject. Copy ordinary tree bỏ qua generated descendants của source blob; blob mới tạo artifacts bằng pipeline của nó. Artifact subtree được copy riêng trở thành ordinary writable tree, bỏ generated ownership.

Toàn cây copy và quota delta commit trong một transaction. Dùng recursive CTE và mapping ID một lần, không transaction/RPC theo từng node. Name conflict/quota/error làm rollback toàn copy. Không job, progress, resume, compensation hoặc distributed commit. Không đặt câu hỏi 200k node để mở rộng thiết kế này. Blob source mới do copy được xem là khởi tạo nội dung: copy không clone generated artifacts rồi lại parse đè; source mới tự chạy pipeline. Artifact được copy riêng thành text thì không ingest; thành blob source được hỗ trợ thì theo rule blob mới.

Shared immutable object không cần refcount: garbage collection kiểm tra actual files.object_key references. Object key không unique trên files. Không dedup theo content hash hoặc shared-content service.

Move/rename là SQL update; cross-storage move cùng workspace đổi storage của subtree. Không tăng files.version hoặc chạy lại parse/enrich chỉ vì đổi tên, storage, ACL hay restore. Nếu Qdrant lưu storage payload, maintenance cập nhật payload theo SQL mà không tái tạo embeddings. Object không di chuyển vật lý. Không bảo đảm serializable outcome cho cây đang bị nhiều caller sửa cùng lúc.

### Trash

Trash detach root và ghi một trash_entries row chứa occurrence ID, original parent, timestamp/actor. Descendants giữ parent links. Resolver chỉ trả node còn nối được tới live storage/mount root, nên raw ID của descendants cũng không vượt trash boundary. Không trash-specific nullable fields trên mọi node hoặc marker trên mọi descendant.

Restore gắn lại root vào parent cũ hoặc destination được chọn và xóa trash entry trong cùng transaction. Parent đã mất/name conflict trả lỗi để người dùng chọn lại. Purge dùng recursive DELETE với RETURNING trong một transaction và debit bytes từ files rows thực sự bị xóa. Parent FK là deferred no-action, không cascade xóa âm thầm các row ngoài tập accounting. Trash table chỉ chứa domain occurrence, không purging state, cleaner hay workflow. Original-parent là restore hint, không có FK cascade làm mất trash khi parent cũ bị purge.

### Upload và download

- Text được tạo/upload/replace trực tiếp vào PostgreSQL. Blob, kể cả binary nhỏ, dùng CreateUpload, SignParts khi multipart, CompleteUpload và AbortUpload.
- Upload ID là identity của transfer, không thêm idempotency key song song. Complete lặp lại trả publication response đã lưu của đúng upload, không đọc lại trạng thái node hiện tại.
- Single PUT dùng checksum đã ký và native conditional create để key không bị ghi đè. Multipart complete do service gọi; không cho client quyền PUT tự do lên published objects.
- Complete kiểm tra thực tế object bytes/checksum bằng S3 metadata theo primitive provider; publish node + quota trong một SQL transaction. Key do LetFS cấp, caller không được đăng ký arbitrary object key.
- Abort/expiry chỉ làm transfer không còn admissible. Bucket lifecycle abort incomplete multipart. Unreferenced completed objects do GC xử lý.
- Download text trả UTF-8 bytes từ PostgreSQL; blob trả signed S3 GET. Range/blob HTTP thuộc S3. Signed capability có TTL ngắn; revoke không thu hồi URL đã cấp hoặc stream đang chạy.

### Garbage collection

Không còn `object_deletions`, `index_deletions`, `open_writes`, `ambiguous_write` hoặc cleanup receipt.

Object GC dùng native S3 listing theo batch, chỉ xét object đủ cũ (đề xuất 24 giờ, dài hơn upload lifetime và request/transfer admission window); query batch keys còn được files hoặc active uploads tham chiếu; xóa phần còn lại. Không reuse expired key. Shared object còn bất kỳ reference nào, kể cả trash, thì được giữ. Transaction/request có thời hạn thông thường; không giữ old SQL snapshot qua GC grace.

Đây là một sweep dựa trên dữ liệu đang có, không phải reference-count manager hay journal mới. Sweep lỗi thì lần sau thử lại; chấp nhận bytes rác tồn tại lâu hơn. Việc xóa logic không chờ storage provider. Bucket lifecycle chỉ tự expire staging nếu có và incomplete multipart; không blind-expire published data prefix.

Semantic result luôn được đối chiếu batch với node, source files.version, storage và trạng thái hiện tại trong SQL. Qdrant có thể còn point cũ nhưng không được trả stale/deleted/foreign-storage content. Maintenance scroll Qdrant theo batch và xóa point không còn source/version hợp lệ. Không durable tombstone cho từng vector.

Giữ grace/validation này vì xóa dữ liệu của object còn được share là rủi ro thật. Không xây per-key state machine để xử lý mọi khả năng late I/O.

## 8. Artifacts và thiết kế lại ingest

### Trigger và loại file

Đơn vị xử lý là một source blob và content version của nó. Tạo blob được hỗ trợ hoặc replace blob content mới kích hoạt pipeline. Đổi tên, move, ACL, text mutation hoặc restore không tăng content version và không tự chạy ingest.

File text do người dùng upload/tạo không parse, enrich hay embed ở MVP. Text sinh ra từ parse là artifact của source blob và được enrich/index trong đúng pipeline blob đó; nó không trở thành source text ingest độc lập. Blob artifact như PNG cũng không tự khởi động pipeline khác.

Office/PDF đi qua CPU parse. Image được IO describe/index trực tiếp; processing row của source được khởi tạo ở stage parsed vì không cần document parser. Arbitrary binary không được hỗ trợ vẫn lưu S3, có trạng thái not-supported, không có workflow giả.

### Artifact storage

Artifacts là node bình thường trong cùng storage, nằm dưới source file; text/blob payload ở files, semantic fields ở file_metadata. Source ownership lấy từ file ancestor, không lặp lại source ID/version trên mỗi node. Không artifact table, artifact database hay mount riêng.

```text
report.pdf                         blob -> S3, source version 7
  README.md                        text -> PostgreSQL
  section-001/
    README.md                      text -> PostgreSQL
    table-001.csv                  text -> PostgreSQL
    figure-001.png                 blob -> S3
```

- Markdown, CSV, JSON và extracted text đều là loại text, lưu PostgreSQL.
- Image/binary artifacts là blob, lưu S3, dù kích thước nhỏ.
- Directory chỉ là structure; summary/semantic metadata của directory ở README của nó.
- Generated nodes readonly qua user API. Copy text artifact ra ordinary directory tạo text writable và không ingest.
- Artifact text không được fallback lên S3 khi lớn. Parser chia document theo layout/section cần thiết; nếu output vượt text/manifest budget thì processing báo lỗi, source blob vẫn tải được, không truncate âm thầm.
- Giữ tên/path ổn định do parser sinh từ heading, sheet hoặc ordinal. AI tạo display title/summary/type/context; đề xuất bỏ AI rename path và vòng rewrite links. Đây là thay đổi sản phẩm có chủ ý để giảm coupling giữa model output và storage structure.

SemanticSearch kết hợp dense vector và BM25 trên Qdrant payload text index bằng native RRF, rồi SQL kiểm source version/live ancestry và rerank. Hai prefetch cùng workspace filter; text index dùng native tokenizer/scoring, không sparse embedding provider hoặc tự viết fusion. Quyết định sau feature audit chỉ bổ sung hybrid; không thêm filters/sort hoặc các tùy chọn restore/mkdir/trash đã được người dùng chấp nhận cắt.

### Hai worker, hai activity chính

```text
ProcessBlob(file_id, version)
  ParseBlob                  CPU queue, chỉ với document cần parse
  EnrichAndIndex          IO queue
```

Worker CPU: concurrency nhỏ, tải source về temporary directory, một converter subprocess cho mỗi document, publish artifact tree. Dùng Docling cho PDF/DOCX/PPTX/XLSX; openpyxl bổ sung cell/formula ngoài vùng bảng XLSX. Export text/CSV/images thành cùng artifact contract. Offline models được chuẩn bị khi build/deploy, không download model trên mỗi job.

Worker IO: không import/load Docling/OCR; lấy artifacts đã commit, gọi model cho metadata/README, commit enrichment, rồi chunk/embed/upsert Qdrant. Hai role là hai process/image target của cùng codebase; không hai backend API.

Giữ subprocess boundary vì native parser/OCR có memory và cancellation khác IO worker. Dùng native parser timeout, container/resource limits và finally terminate child. Bỏ polling quét toàn output mỗi giây, parser diagnostic receipt protocol và exception-string classifier framework. Input/output size, untrusted document/path và model-output validation vẫn được giữ ở đúng boundary.

### Luồng CPU

Yêu cầu bảo toàn chức năng, cập nhật theo quyết định người dùng 2026-11-12: ingest chủ yếu được viết lại cho gọn, không phải cắt tính năng. Giữ các hành vi sau bằng implementation mới và thư viện hiện tại:

- Layout PDF/Word chọn một README, các section Markdown, hoặc hai cấp section/subsection theo nội dung; tính cả bảng, không lấy heading trong bảng làm ranh giới document.
- PowerPoint giữ thứ tự và mốc slide kể cả slide không tiêu đề. Kiểm chứng Word content controls/insertions và PowerPoint compatibility branches bằng converter hiện tại; chỉ thêm xử lý tối thiểu khi upstream còn làm mất nội dung.
- XLSX nhận diện nhiều vùng bảng thường, không chỉ Excel Table; xuất CSV từng bảng, giữ cell/formula ngoài bảng với tọa độ và ảnh trong sheet.
- Bảng document thành link CSV đúng vị trí, giữ caption/footnotes/rich-cell text; ảnh/link tương đối trỏ đúng artifact.
- Enrichment giữ title/description/semantic taxonomy/context, mẫu evidence trải dọc tài liệu và ngân sách cho toàn evidence gồm child summaries. README tổng hợp từ sâu lên nông; source lấy metadata root README.
- Index full body với ancestor context, overview riêng cho file dài và chunks; không embed lặp phần README metadata/child listing do enrichment sinh. CSV/image dùng overview. Giữ batching và deterministic IDs theo source/version/vector space.
- Resize/nén ảnh trước model, giới hạn concurrency bao gồm tải ảnh; validate structured output và embedding indices/count/dimensions/finite tại provider boundary.
- Chuẩn bị model offline bằng downloader native, kiểm tra assets/runtime trước nhận job; giữ giới hạn input/output cần thiết và phân biệt invalid input với lỗi môi trường retryable. Không khôi phục supervisor polling/receipt framework.

Các thay đổi đã chốt vẫn giữ: parser paths ổn định, bỏ AI rename/rewrite-link; không ingest text người dùng ở MVP; CSV dùng header/sample rows thay profiling toàn bộ; hai activities và batch publication theo contract mới. Test tập trung vào hành vi có nguy cơ mất, không phục hồi toàn bộ test harness cũ.

1. GetProcessingInput theo file/version; stage đã parsed thì kết thúc.
2. Download blob qua signed URL vào temporary file; convert sang tree có path ổn định.
3. Gom text payload vào manifest. Gom binary artifacts để xin signed PUT trong một batch.
4. Upload blob artifacts rồi gọi CommitParse một lần.
5. CommitParse kiểm tra version/liveness và issued handles, insert tree + quota + stage parsed trong một transaction.

Blob artifact output dùng single PUT với size/checksum đã khai báo; output có budget nên không xây multipart-output protocol. Upload source blob của người dùng vẫn có multipart khi cần.

### Luồng IO

1. Đọc stage và artifacts. Stage parsed thì enrich leaves, rồi README từ sâu lên nông bằng child summaries.
2. Metadata giữ title, description, semantic type và context. Path không đổi theo model response nên không cần final-path mapping/rewrite links.
3. CommitEnrichment cập nhật text/metadata, quota delta và stage enriched trong một transaction. Source metadata lấy từ root README. Image source có thể tạo README text tại bước này.
4. Chunk full text, không dùng riêng phần sample enrichment làm index. CSV/image dùng overview thích hợp như chức năng hiện tại. Native text user files không có vector points ở MVP.
5. Batch embedding và Qdrant upsert với deterministic point ID theo source/version/artifact/chunk và vector space. Acknowledged writes xong mới CompleteIndex thành ready.

CSV artifact do chính parser xuất có format biết trước: header và sample rows phục vụ model, không generic CSV sniffing, full type-inference scan hoặc reservoir sampler để xử lý mọi CSV người dùng upload. Dữ liệu đầy đủ vẫn được lưu ở artifact text.

Stage nằm trong processing row của source file: pending -> parsed -> enriched -> ready; error field giữ lỗi của lần chạy. Failure không xóa last completed stage. IO retry sau index failure thấy enriched thì bỏ qua model enrichment, chỉ làm index lại. Retry có thể gọi embedding/model lại nếu lần trước chưa commit; chấp nhận chi phí đó thay cho per-chunk checkpoint/cache riêng. Không jobs/attempts database.

### RPC internal LetFS

| RPC | Chức năng |
|---|---|
| `GetProcessingInput` | Source signed URL, artifact text/object descriptors, current stage và options |
| `PrepareArtifactUploads` | Batch issued handles + signed PUT cho blob outputs |
| `CommitParse` | Artifact manifest chứa text và issued blob handles |
| `CommitEnrichment` | Text/metadata updates của cùng source/version; không AI path mutation |
| `CompleteIndex` | Mark version ready sau Qdrant acknowledgement |
| `FailProcessing` | Ghi error cho đúng version chưa ready |

Artifact uploads dùng chính uploads table với source/version ownership. CommitParse verify/consume handles cùng publication, không GetOutputUpload/CompleteOutputUpload/WriteOutputBytes riêng. Empty text hợp lệ. Manifest path escape hoặc missing parent bị từ chối; không tự fallback parent. Boundaries dùng generated protobuf, không thêm DTO mirror.

Workflow và hai activities dùng identity `{file_id,version}`; workflow có thêm parse_required do LetFS quyết định lúc dispatch nếu cần. Không nội dung, manifest, markdown hoặc chunks trong Temporal history. Workflow gọi record-failure activity khi native retries hết; không mỗi Python wrapper tự abort/fail/report cùng một lỗi.

Replace source blob tăng files.version, xóa artifact subtree và source file_metadata cũ, reset processing stage và điều chỉnh quota trong cùng transaction publish content. Late commit khác version bị từ chối. Late index points bị SQL validation lọc và maintenance xóa. Retry là tiếp tục cùng content version, không tạo version vì retry. MVP không có automatic reprocessing khi metadata/config/ACL đổi; operator có thể retry failed Temporal work của version hiện tại.

## 9. Idempotency theo từng thao tác

Bản trước gộp nhầm optimistic concurrency với persisted idempotency. Revision/version precondition chặn ghi lên nội dung đã thay đổi, nhưng không biết request trước đã thành công hay không và không replay được kết quả. Stable resource ID hữu ích nhưng không thay thế receipt cho append hoặc những SQL mutations cần retry rõ ràng.

### Key lưu ở PostgreSQL của service sở hữu mutation

Platform và LetFS mỗi bên có một bảng idempotency_keys, không shared database hoặc Redis cache:

```text
idempotency_keys
  caller          canonical typed actor key (user/leta + UUID)
  method          RPC method
  key             client-generated UUID
  request_hash    SHA-256 của validated request được serialize ổn định
  result          protobuf response nhỏ hoặc admitted resource identity
  expires_at      retention đề xuất 24 giờ

PRIMARY KEY (caller, method, key)
```

Không lưu file bytes, raw invite token hoặc model output trong result. Với token trả một lần, chỉ lưu invitation identity; retry không phát hành lại quyền hay trả plaintext token từ một receipt.

Flow SQL mutation:

1. Authenticate/authorize và validate request.
2. Begin transaction, claim unique key. Nếu đã có completed key, so request hash: cùng hash trả stored result; khác hash trả IdempotencyConflict.
3. Nếu key mới, thực hiện mutation và quota accounting, ghi result rồi commit cùng transaction.
4. Transaction rollback thì mutation và key cùng rollback. Không commit row pending, không sweeper để hồi sinh pending request.

Concurrent duplicate được unique constraint của PostgreSQL điều phối; không distributed lock hoặc custom polling. Row claim/result chỉ có thể chưa hoàn tất bên trong transaction đang mở, không phải durable operation state machine.

Ví dụ append với key K: transaction append một lần, tăng files.version từ 12 lên 13 và lưu response version 13 cho K. Response bị mất thì retry K trả response đã lưu, không append lại và không fail chỉ vì version đã lên 13. Cùng K nhưng text khác bị từ chối. Expected_version, nếu được gửi, chỉ được kiểm tra khi thực hiện request lần đầu.

Expected_version là concurrency precondition độc lập: hai request khác key cùng sửa từ version 12 thì có thể conflict; request trùng key đã thành công được replay. Không lấy version mới để tự apply lại một edit cũ.

### Phạm vi áp dụng

| Thao tác | Identity và retry semantics |
|---|---|
| Onboard | Unique Clerk subject; workspace chỉ INSERT từ user mới RETURNING, retry user cũ không tạo workspace khác |
| SQL node create/copy/text edit/move/trash cần retry | Persist key/hash/result cùng mutation; replay result, không apply lại |
| Create workspace | Persist admission/resource identity cùng provisioning row; workflow ID ổn định; retry không tạo provisioning khác |
| Internal storage provisioning | Ordinary UUID cấp một lần trong workflow input; PK/local receipt cho effect identity, không owner-derived ID |
| Initial storage provisioning | Ordinary UUID giữ trong input/receipt, native ID uniqueness; không actor→storage mapping hoặc invariant một storage/owner |
| Set role/grant/revoke | Native atomic graph set/delete; SDK không blind retry sau một lệnh ngược chiều |
| Blob upload | Stable upload ID; CompleteUpload commit node/quota và publication response trong cùng SQL transaction. Retry replay response, kể cả node đã được sửa/xóa sau đó |
| Restore/purge | Trash occurrence ID; occurrence đã kết thúc không tác động một lần trash mới. Purge lại không debit quota lần hai |
| Blob processing | `(file_id,version)` là workflow identity; stage commit và quota trong cùng SQL transaction. Commit stage đã hoàn tất không chạy lại mutation |
| Vector indexing | Deterministic point IDs; upsert lại không nhân đôi points |
| Delete workspace/storage | Workspace deleting phase rồi DELETE resource; absent là done; native workflow giữ retry history |
| Invite acceptance | Consume một lần; retry chỉ quan sát membership hiện tại, không regrant membership đã revoke |

CommitParse/CommitEnrichment kiểm tra files.version và processing stage trong transaction. Không cần request-key receipt cho từng stage, manifest hash hoặc attempt ID. CompleteIndex và FailProcessing không làm stage ready lùi lại.

Receipt guarantee chỉ trong retention window và owning SQL transaction. Không hứa global exactly-once giữa PostgreSQL, SpiceDB, Temporal, S3 và model provider. Workspace admission có receipt không có nghĩa các graph/storage effects đã commit cùng PostgreSQL; workflow/resource state vẫn ghi nhận tiến độ provisioning. Pure ACL operations giữ native set/delete semantics; một grant in-flight có thể giao nhau với revoke. Không mở SQL transaction xuyên network call để giả lập atomicity.

## 10. Temporal tối thiểu

Đã chốt qua trao đổi ngày 2026-11-12. Temporal chỉ điều phối durable lifecycle, blob processing và maintenance; không là permission authority hoặc database của domain. [API](api-contract.md), [schema](schema.md) và [processing queries](processing-queries.md) giữ owning contracts. Không thêm Temporal framework dùng chung.

### Inventory và ownership

| Workflow/flow | Owner | Công việc và input identity |
|---|---|---|
| ProvisionWorkspace | Platform | Workspace/owner admission, gọi LetFS provision budget và public/private storage ban đầu; workspace ID và các storage UUID được cấp một lần trong admission/workflow input |
| ProvisionMemberStorage | Platform | Sau membership admission, provision private storage khi cần qua LetFS; workspace/user và storage UUID ổn định, rejoin discover storages hiện có, không unique owner→storage |
| DeleteWorkspace | Platform | Workspace deleting, revoke authorization rồi gọi owning cleanup API; LetFS dọn storage/budget, không chờ Leta stop ACK |
| UpdateStorageVisibility | LetFS | Desired visibility và request identity; SQL metadata + public_workspace projection được retry tới ACK, không transaction xuyên SQL/SpiceDB |
| ProcessBlob | LetFS | file_id/version, parse_required và native activity options cần thiết; CPU ParseBlob khi cần rồi IO EnrichAndIndex |
| Maintenance qua native Schedules | Owning service | Platform recover workspace provisioning/deletion và expire local receipts/invites; LetFS recover dispatch, expire uploads/receipts, S3 GC và Qdrant cleanup |

Tên trên là contract triển khai. Platform/LetFS đã có workflow registrations trong source; runtime verification hiện được ghi tại [plan](plan.md). Không bắt buộc tạo wrapper workflow riêng cho từng CreateStorage/DeleteStorage internal RPC khi lifecycle caller đã chịu trách nhiệm retry owning gRPC operation đó.

### Giao tiếp, queues và retry

Platform workflow gọi local activity; activity dùng generated gRPC client gọi LetFS internal API. Platform không gọi workflow/activity private hoặc queue LetFS để thực hiện business operation; LetFS không đọc SQL Platform. Ingest là workers của chính processing boundary LetFS nên ProcessBlob schedule trực tiếp hai Python activities đã chốt.

| Queue trong YAML | Trách nhiệm |
|---|---|
| openlet-platform | Platform lifecycle và maintenance |
| openlet-letfs | LetFS workflow/orchestration và local maintenance activities |
| openlet-ingest-cpu | Python ParseBlob |
| openlet-ingest-io | Python EnrichAndIndex |

Các queue Leta độc lập và tiếp tục hoãn thiết kế; không leta_bridge hoặc callback queue mới. Worker có thể cùng process với owning API theo app layout; queue không đồng nghĩa cần service/container mới.

Dùng native workflow IDs, conflict/reuse policies, activity retry/backoff/timeouts và heartbeat khi có công việc dài. Resource UUID cấp một lần và giữ trong admission/receipt/workflow input; retry tiếp tục cùng resource identity, không UUIDv5 hoặc owner-derived ID. Activity results nhỏ; dùng domain PK/receipt/stage cho idempotency ở datastore. Native retries không làm SQL+graph atomic hoặc hứa global exactly-once. Không custom retry loop, application lease/renewer/fencing hoặc jobs/attempts database.

Add/remove membership, grant/revoke và owner transfer dùng native SpiceDB writes/batch/preconditions. RemoveMember chỉ xóa human membership với owner-protection precondition; không liệt kê agent/resource, sửa workspace.agent hoặc stop/cleanup fanout. Agent có identity/grants độc lập membership của human owner; eligible_actor = participate + agent. Leta ghi/dọn hai chiều agent.workspace/workspace.agent cùng batch theo agent lifecycle, không owned_agent hoặc registration state mới. Temporal chỉ provision/cleanup sau authorization admission; recover member storage không regrant membership đã thu hồi. Public storage kế thừa workspace graph nên không fan-out cập nhật từng storage khi member đổi.

ProcessBlob ID gắn file_id/version, không gắn storage hoặc current owner; move không tăng version hay trigger pipeline mới. LetFS resolve actual source/storage ở processing RPC. Wrong version/deleted source là obsolete outcome, không tạo retry vô hạn. Commit stage/quota/artifacts nằm cùng local SQL transaction. Khi activity retries hết, workflow ghi FailProcessing qua một activity duy nhất; không fail/report lặp ở nhiều wrappers.

CPU/IO trả stage outcome nhỏ, không manifests/text/chunks trong Temporal history. Stage đã commit thì retry bỏ qua; model/embedding call trước commit có thể lặp và đây là giới hạn đã chấp nhận. Recovery dispatch dùng stable workflow ID/native policies, không tạo workflow song song hoặc tự mở lại mọi failed run vô hạn; operator retry theo native Temporal khi cần.

Maintenance dùng native Schedule overlap policy Skip và batch SQL/provider operations. Không workflow theo từng object/vector/upload part hoặc custom scheduler/checkpoint framework. SQL publication ghi processing admission trước khi dispatch; scheduled recovery có thể start workflow bị thiếu sau lỗi dispatch, không outbox mới.

Workflow không đọc YAML/ENV hoặc gọi SQL/network trực tiếp. Settings cần deterministic lấy trước khi start hoặc đóng trong worker registration options; activity dùng owning process settings. Không secrets, JWT, signed URLs hoặc toàn config trong workflow history. Theo [configuration](configuration.md), queue/timeouts/budgets có một nguồn YAML.

### Giới hạn scope

Ordinary file CRUD/copy/move/trash/restore/purge, quota accounting và upload publication vẫn local SQL/provider operations; không per-node workflows hoặc lifetime membership coordinator. Text và artifacts không tự dispatch ingest. Storage roots không có workflow giữ khóa suốt vòng đời.

Delete workspace/storage không chờ Leta runtime dừng trước storage deletion. Async cleanup business API được phép khi contract Leta được chốt; core không dispatch queue/workflow hoặc đọc thread/box/history nội bộ Leta. Core build/test/startup và hot path độc lập với Leta. Chưa đổi Leta runtime/API hoặc tạo Computer service trong phần này.

Go/Python Temporal interoperability, deterministic payload encoding và native OTel propagation được smoke trên pinned SDKs khi implementation. Đây là verification công cụ, không decision sản phẩm còn mở. Nếu capability native không đáp ứng contract buộc đổi semantics/schema thì đưa evidence và hỏi user trước khi thay thiết kế.

## 11. Cấu trúc thư mục

```text
apps/
  platform/
    cmd/platform/main.go
    internal/
      platform/
        server.go           # generated server implementation + concrete dependencies
        identity.go         # profile, onboarding, Clerk calls
        workspaces.go       # workspace SQL/operations
        members.go          # graph membership và owner transfer
        invitations.go
        access.go           # permission checks/relationship writes
      jobs/
        provisioning.go
        deletion.go
    migrations/0001_initial.sql
    tests/integration_test.go
    go.mod
    Dockerfile
    package.json
  letfs/
    cmd/letfs/main.go
    internal/
      storage/
        server.go
        nodes.go            # stat/list/create/move
        paths.go            # single resolver + optional mount root
        text.go             # read/mutate, exact bytes, metrics
        tree.go             # traversal, copy
        trash.go
        uploads.go
        processing.go       # version check + artifact commit
        search.go
        archive.go
        images.go
        administration.go
        access.go
        s3.go               # AWS SDK operations used by this service
      jobs/
        processing.go
        maintenance.go
    migrations/0001_initial.sql
    tests/integration_test.go
    go.mod
    Dockerfile
    package.json
  leta/                     # chỉ boundary/dependency changes
  letfs-ingest/
    src/letfs_ingest/
      worker.py             # cpu/io entrypoint, native Temporal Worker
      config.py
      parse.py              # CPU ParseBlob activity
      process.py            # IO EnrichAndIndex activity
      convert.py            # converter subprocess entrypoint
      export.py             # Docling/openpyxl -> artifact tree
      layout.py             # heading/section layout khi cần
      artifacts.py          # manifest + batch blob transfer/publication
      enrich.py             # metadata và bottom-up README
      index.py              # chunks, batch embeddings, point IDs, upsert
      providers.py          # model API calls thực dùng, không provider framework
    tests/
      test_export.py
      test_enrich.py
      test_index.py
      test_pipeline.py
    pyproject.toml
    Dockerfile              # CPU/IO targets; parser dependencies chỉ CPU
    package.json
packages/
  contracts/
    proto/openlet_api/
      platform/v1/platform.proto      # PlatformService public
      platform/v1/internal.proto      # PlatformInternalService private
      letfs/v1/letfs.proto             # LetFSService public
      letfs/v1/internal.proto          # LetFSInternalService private + processing
    authz/schema.zed
    generated/public.pb     # Envoy public descriptor
    generated/openapi.yaml  # nếu cần HTTP reference, generated-only
    buf.yaml
    buf.gen.yaml
    package.json
  sdk-go/
    gen/openlet_api/...      # generated
    dial.go                 # native channel + tracing; MVP private network
    identity.go             # typed actor metadata/context
    errors.go               # ErrorInfo decoding nếu caller cần
    telemetry.go            # initialization used by both Go apps
    go.mod
    package.json
  sdk-python/
    src/openlet_api/...      # generated
    src/openlet_sdk/
      rpc.py                # channel và actor metadata của API Platform/LetFS
      errors.py             # small shared exception actually consumed
      telemetry.py
      temporal.py           # native connection/tracing used by existing Python workers
    pyproject.toml
    package.json
archive/2026-11-11/
  apps/{account,workspace,letfs,letfs-ingest}/
  apps/leta/tests/           # toàn bộ legacy tests theo storage mới
  packages/{contracts,go,python}/
  e2e/                      # toàn bộ legacy specs/setup/fixtures/config
  scripts/                  # affected legacy test/performance/recovery harness
```

Đây là ranh giới module, không phải quota phải đủ file. Module chưa có logic thật thì chưa tạo file. Unit tests đặt cạnh code khi có logic cần test, không tạo test file cho mỗi file production.

RPC handler làm validation, authorization và SQL orchestration trong owning package. Không thêm `domain/`, `application/`, `ports/`, `repositories/`, `usecases/`, `dto/`, `mappers/` hay `transport/grpc/` chỉ để chuyển request qua nhiều lớp. Dependency concrete dùng `pgxpool`, Authzed, AWS và generated stubs. Interface chỉ xuất hiện khi có hai implementation thực sự cần hoặc một external test seam thật sự nhỏ.

Config loading dùng một YAML chung theo [thiết kế cấu hình](configuration.md); shared helper chỉ đọc YAML/section/secret và owning service giữ settings validation. Process lifecycle ở command entrypoint hoặc một local bootstrap file khi cần; không dựng framework server dùng chung. Standard SDK telemetry/auth helpers được share vì có consumer thực, không share business SQL hay workflow state.

### SDK

Generated request/response là model sử dụng trực tiếp. Go dùng `NewPlatformServiceClient`/`NewLetFSServiceClient`; Python dùng generated stubs. Chỉ thêm config/channel, actor metadata, tracing và error decoding cần thiết. MVP không app service-token plumbing. Không `Client` mirror mọi RPC, không Python dataclass/Go DTO sao chép protobuf, không exact-set response validators hoặc automatic mutation retry.

API/transport Leta còn hoãn; không scaffold server/callback/config. Native SpiceDB client là authorization boundary đã chốt; không custom authz SDK engine. Channel options dùng native gRPC configuration; không tự dựng retry/TLS protocol.

Mirage mapping ở Leta VFS boundary; ingestion manifest/upload mapping ở ingest artifacts module. Không nhét hai implementation này vào SDK. HTTP problem/gateway helpers chỉ Leta dùng thì chuyển vào Leta HTTP boundary; settings Leta lấy từ YAML chung, model catalog nằm trong cùng file. Những import chạm lỗi/config của Leta là dependency migration, không refactor domain Leta.

Ingest không còn generic Processor class + Activities wrapper cùng mirror mỗi method, processing clients với DTO riêng, hoặc temporal/clients/parser package lồng nhau chỉ để chuyển tiếp lời gọi. Hai activity functions tự orchestrate các hàm parse/enrich/index thực sự. Third-party imports nặng chỉ nằm trong CPU/converter path. Một Dockerfile có hai targets giữ IO image không kéo model/OCR dependencies.

## 12. Boundary changes cụ thể

Platform: user/workspace/membership/invitation và generic workspace-active check; không agent-specific registration RPC. Leta sở hữu agent relations và hai chiều agent.workspace/workspace.agent trong cùng native graph batch. LetFS: quota/storage discovery/roles và file/processing APIs. [API contract](api-contract.md) là inventory đã chốt.

Leta root giữ workspace_id/storage_id, native calls dùng agent subject. Root owner/operator ở shared authorization graph; không dùng creator làm current owner hoặc lấy human rights thay agent. Agent personal storage owner@agent và owner@agent#owner; chỉ trên storage đó.

Agent API/transport/multiple storage và switch hoãn; không đổi single thread/domain/checkpoints/box/Leti. HITL request đổi locator storage_id, actual grant đi LetFS. Concrete cleanup gRPC của Leta chờ owning review, không thêm ngay.

Computer chỉ design actor forwarding/manager/operator; chưa code/schema runtime. Ingest giữ sáu typed processing RPC, file_id/version/stage, batch publication. Generated clients và native SDK; không compatibility wrappers.

## 13. Test và CI đúng chi phí

Test theo invariant/đường đi sản phẩm, không test số lớp hoặc defensive branches đã xóa.

Case remove/rejoin agent dùng graph fixtures trong scenario integration hiện có, không thêm suite/container hoặc bắt core khởi động Leta/model provider. Chỉ kiểm actor authorization và quan hệ còn giữ; runtime E2E thuộc journey Leta sau implementation.

| Nhóm | Bằng chứng tối thiểu |
|---|---|
| Fast unit | path/mount escape, text exact bytes và patch behavior, quota delta, artifact manifest validity |
| Platform integration | onboarding lặp không tạo workspace mới; owner/member gate; invite email/consume behavior; remove/rejoin giữ personal storage và chỉ đổi quyền human, agent cùng workspace giữ quyền riêng, agent khác workspace bị chặn; revoke có hiệu lực theo consistency đã công bố |
| LetFS integration | CRUD/copy/move; quota atomicity; text chỉ PostgreSQL/blob chỉ S3; readonly artifacts; trash/restore/purge; duplicate append không ghi đôi; upload complete; shared object còn reference không bị GC |
| Async boundary | text không dispatch; artifact text không khởi pipeline con; wrong version không publish; Go workflow chạy hai Python activities đúng payload; stage retry không debit/insert đôi |
| Envoy smoke | JWT/bootstrap/forged trusted headers; internal methods không public; JSON RPC; ZIP bytes qua pinned Envoy |
| Core journey độc lập | onboard -> invite -> file/upload -> processing/search -> revoke -> delete workspace khi Leta không chạy |
| Tích hợp Leta khi được chọn | Leta gọi gRPC Platform/LetFS, storage approval và xử lý resource bị revoke/xóa; không là prerequisite của core journey |

Một môi trường integration được reuse trong mỗi run; không khởi Docker stack trong từng test. Native gRPC integration là nơi kiểm tra business chính; không lặp lại toàn bộ matrix ở HTTP, SDK và service layer.

PR chạy build/check/unit và integration của owner bị thay đổi. Contract/SDK đổi thì chạy thêm affected consumers và Envoy smoke. Full system/recovery/provider smoke chạy trước release hoặc theo lịch, không mỗi commit không liên quan. Leta tests mới do owner refactor Leta phụ trách; infra giữ cross-service E2E theo [infra design](infra-testing-ci-cd.md). Ingest tests mới tập trung export fixture nhỏ, stable paths/README semantics, deterministic indexing và một pipeline journey; PDF/OCR nhiều model và live-provider quality chạy theo lịch/trước release. Không test lại nội bộ Docling, gRPC, Temporal hay mọi failure boundary.

Archive toàn bộ tests của Account/Workspace/LetFS/ingest/shared packages, toàn bộ root E2E và legacy harness theo [inventory archive](plan.md). Theo yêu cầu mới, archive cả toàn bộ Leta domain/runtime tests/fixtures và infra/scripts/CI/tooling cũ. Giữ source/migrations Leta để owner refactor riêng. Viết mới essential checks theo contract mới, không port test chỉ để giữ coverage. Native SDK đã kiểm tra TLS/parser/retry engine của nó; không kiểm lại bằng một test framework của dự án.

Không hứa số LoC/performance chưa đo. Báo handwritten production, tests và generated riêng; exclude archive/build outputs. Benchmark các API thường dùng và cây kích thước bình thường trước/sau bằng cùng fixture, môi trường và baseline commit. Chi phí CI cũng đo elapsed/container starts thay vì chỉ đếm test.

## 14. Archive và cutover

1. Chụp inventory/hash trạng thái hiện tại, gồm uncommitted changes. Di chuyển nguyên Account/Workspace/LetFS/ingest, mọi package folder cũ và toàn bộ affected testing/e2e/fixtures/harness vào archive theo plan; không reset worktree. Cả ingest parser/CPU/IO implementation đều viết mới, không giữ fallback.
2. Xây active trees từ contract/behavior đã chốt. Không copy/paste code/test; không gọi archive làm fallback. Generated bindings tạo lại từ proto mới.
3. Đổi go.work/uv workspace, image builds, Compose, Envoy routes/descriptors, YAML và dependency secrets sang Platform/LetFS mới; bỏ app service-token plumbing theo MVP proposal. Root pnpm/Turbo/Make cũ đã archive; [infra proposal](infra-testing-ci-cd.md) dùng Make/native commands cho bộ mới. Archive bị loại khỏi build, lint, test discovery và Docker context.
4. Người dùng đã chọn database mới, không import dữ liệu cũ. Tạo baseline schema trong database mới, giữ database cũ nguyên trạng đến cutover riêng và vẫn backup trước schema/data change. Không importer, chuyển payload text/blob cũ, giữ ID cũ hoặc backfill membership. Dữ liệu graph/index và jobs của phần viết lại dùng resources/namespace riêng của môi trường mới bằng cấu hình native; không trộn state cũ vào SQL mới hoặc xây migration/reset framework. Không xóa Clerk identities; onboarding publish application user mapping của database mới theo luồng đã thiết kế.
5. Drain hoặc dừng workers/workflows Account/Workspace/LetFS/ingest cũ trước mở traffic mới; không để old worker ghi vào database mới. Không nhận lại processing jobs cũ. Bên tích hợp tự cập nhật consumer theo gRPC contract mới; core không dừng/di chuyển workflows Leta hoặc đòi Leta chạy để cutover. Không viết workflow-history migration trong đợt này.
6. Cutover trong maintenance window, cập nhật caller và server cùng đợt. Không dual serve/dual write API cũ. Rollback dừng bộ mới rồi trỏ lại bộ cũ và database cũ đã giữ nguyên; dùng backup khi cần restore. Không tự merge các ghi phát sinh ở hệ thống mới vào dữ liệu cũ.

Không archive database hoặc xóa dữ liệu chỉ vì archive source. Không run schema/data migration lên môi trường đang dùng ở giai đoạn đề xuất.

## 15. Điều kiện hoàn thành

- Active tree có Platform, LetFS, ingest viết mới; Account/Workspace/LetFS/ingest/shared packages cũ chỉ ở archive và không được import.
- Hai backend chỉ có application gRPC. Public unary và ZIP đi qua Envoy thành công; S3 transfers chạy. Core startup/readiness, CRUD, grant/revoke và delete workspace hoạt động khi Leta không chạy. Leta SSE/integration được kiểm riêng khi chọn chạy Leta.
- Domain functions hiện tại còn dùng được qua contract mới; ownership, exact bytes, quota, readonly artifacts và typed actor boundaries có proof phù hợp.
- Không SQL/graph role mirror, command journal/state framework, object copy compensation, per-node CRUD workflows hoặc SDK mirror DTO quay lại dưới tên mới.
- Leta chỉ có boundary/dependency changes. Ingest giữ CPU/IO workers, chỉ process source blob; text và blob storage đúng hai loại, artifact storage rõ ràng.
- Chỉ test các hành vi/invariant cần thiết; không còn active tests ép giữ cơ chế đã loại bỏ.
- Có số đo source/CI/API thực tế và giới hạn đã chấp nhận được công khai.

## 16. Giới hạn chấp nhận có chủ ý

- Concurrent ordinary edits theo transaction/content-version semantics đơn giản; không snapshot xuyên nhiều requests.
- Read và mutation mặc định dùng minimize_latency, chấp nhận propagation/cache staleness của SpiceDB; optional ZedToken cho read-after-write khi cần. Signed URL/stream đang chạy có thể sống đến expiry/kết thúc sau revoke.
- Object bytes không đổi khi rename/move/copy; shared object chỉ bị GC khi hết reference và qua grace.
- Physical garbage có thể lưu hơn 24 giờ nếu cleanup lỗi. Không mất logical data; không tăng workflow/state để hứa cleanup tức thì.
- Invite bị consume ngay trước dependency failure có thể phải gửi lại. Không tự regrant khi replay token đã dùng.
- Các lệnh set/grant đang thực thi có thể giao nhau với revoke; graph commit cuối quyết định. Không hứa command ordering xuyên caller hoặc lưu receipt để chống một grant hợp lệ cũ đang retry. Workspace đã deleting không admit grant mới; core không hỏi lifecycle của actor tích hợp.
- Member limit không còn distributed-atomic ở đúng ngưỡng; quota bytes vẫn atomic vì ảnh hưởng lưu trữ thực.
- Copy một transaction cho cây thông thường; quá thời hạn/giới hạn request thì trả lỗi nguyên tử, không dựng engine cho cây cực lớn.
- SpiceDB phải được backup vì giữ canonical membership/grants; không có đường rebuild quyền từ SQL.
- SQL mutation retry cùng key/hash replay stored result trong retention window. Idempotency receipt không biến graph/provider effects thành một distributed transaction.
- Text vượt text/manifest limit bị từ chối rõ ràng; không fallback sang S3. Blob unsupported giữ source và báo không ingest.
- Artifact paths do parser quyết định ổn định; đề xuất bỏ AI path rename, vẫn giữ AI title/summary/taxonomy và README hierarchy.

Đã archive source/tests cũ theo plan và kiểm hash; chưa viết implementation mới, chạy integration/benchmark hoặc thay dữ liệu. Active build/deployment/CI chưa được dựng lại. Telemetry native và HTTP survey được ghi riêng; không thêm HTTP server cho Platform/LetFS/ingest. Secrets lấy dotenv/ENV theo config design mới.

## 17. Giới hạn implementation

Application và [infra/E2E/CI/CD](infra-testing-ci-cd.md) đã được chốt. Các quyết định hiện đủ để bắt đầu implementation; cập nhật tài liệu không đồng nghĩa application đã được triển khai. Các quy tắc dưới đây tổng hợp quyết định trong cùng plan, không mở thêm features/framework hoặc plan độc lập.

### Knee point: mục tiêu tối ưu

```text
Chi phí / độ phức tạp
  ^
  |                              /
  |                             /
  |                            /
  |                           /
  |                          *  <- knee point
  |                  _______/
  |          _______/
  |_________/
  +------------------------------------> Độ hoàn thiện
                                      100% mọi edge case
```

Đồ thị minh họa quan hệ, không phải số đo hoặc tỷ lệ phần trăm acceptance. Đến knee point có thể đáp ứng đầy đủ yêu cầu sản phẩm với ít cơ chế. Qua đó, thêm một ít độ bao phủ các tình huống hiếm có thể làm code/tests/state/config/CI tăng nhiều lần. Chi phí còn gồm latency, lock contention, vận hành và công đọc/sửa code; không chỉ production LoC.

Chọn knee point: hoàn thành đủ hành vi đã yêu cầu và các invariant cần thiết, chấp nhận những giới hạn đã công bố. Không lấy đơn giản hóa làm lý do cắt browser E2E, tính năng đã chốt, authorization hoặc tính toàn vẹn dữ liệu. Không ấn định mục tiêu phần trăm hoàn thiện hay số dòng tùy ý.

### Quy tắc thực hiện

1. Giữ đúng phạm vi, service/schema/RPC/workflow inventory và ownership đã chốt. Không tự thêm feature/field/state/table/queue vì nhu cầu tương lai; cũng không tự bỏ tính năng hoặc đổi techstack đã chọn.
2. Chỉ xử lý edge cases có tác động thực tế trong phạm vi sản phẩm. Không xây engine cho copy hàng trăm nghìn nodes, rename trong lúc ZIP hoặc mọi interleaving giả định.
3. Giữ các giới hạn chấp nhận ở mục 16: ordinary read/signed URL có revoke staleness, copy có thể timeout/rollback, GC có thể chậm, invite có thể cần gửi lại và model call có thể lặp trước commit. Không biến chúng thành bugs để thêm cơ chế.
4. Khi bug sinh từ cơ chế dư, xem lại nhu cầu tồn tại của cơ chế đó trước khi thêm bản vá. Không lặp vòng redesign -> fix từng triệu chứng -> thêm state/locks -> redesign tiếp.
5. Xóa implementation và tests bảo vệ cơ chế đã loại bỏ. Không giữ code chết, compatibility wrapper, re-export hoặc API cũ chỉ để tests xanh.
6. Không thay một cơ chế bị xóa bằng cơ chế tự chế phức tạp hơn dưới tên mới. So cả production code, tests, state, queries và vận hành khi chọn phương án.
7. Archive chỉ để hiểu context. Handwritten implementation/tests phải viết mới từng dòng; không copy/paste, import hoặc gọi archive làm fallback. Generated bindings được generator tạo lại từ contracts mới.
8. Dùng standard/native libraries và concrete SDK trực tiếp cho transport, SQL driver, signing, parser, retries, scheduler và telemetry. Không tự viết lại chức năng thư viện đã có hoặc phủ một wrapper framework lên nó.
9. Không repository/usecase/ports/DTO/mapper/command-bus layers chỉ để chuyển request. Generated protobuf types dùng trực tiếp; SDK không mirror mọi RPC hoặc nhân đôi model bằng dataclass/DTO.
10. File/module/shared helper chỉ xuất hiện khi có logic hoặc consumer thật. Không scaffold cho đủ folder, generic plugin/provider framework hoặc interface cho một implementation. Không tạo script mới cho mỗi task/plan.
11. Schema chỉ giữ field có ý nghĩa hiện tại. Một files.version, không revision/generation/epoch thứ hai; không onboarding flags/status hoặc lifecycle/processing history dư. Các bảng và checkpoint đã chốt vẫn phải thực hiện đúng vai trò, không xóa chỉ vì tên có state/stage.
12. Giữ đúng hai loại text/blob và một authority: role/grants ở SpiceDB theo A, text ở PostgreSQL, blob ở S3. Chỉ ingest source blob khi tạo/đổi content, giữ CPU ParseBlob và IO EnrichAndIndex; không ingest user text hoặc trigger vì rename/move/ACL. Không SQL role mirror/sync/outbox, text-on-S3 fallback, refcount/compensation framework hoặc payload authority mới trong ingest/Temporal.
13. Không giảm authorization, mount containment, exact bytes, quota atomicity, version guard hoặc readonly artifacts. Validation ở trust boundary và SQL constraints; không kiểm lại cùng invariant ở SDK/handler/domain/store/response.
14. Lock chỉ theo [allowlist](query-design.md#3-lock-budget): đúng file/source/upload row, native unique/conditional DML, quota UPDATE cuối transaction; Move dùng short SERIALIZABLE. Không khóa bao trùm storage/workspace hoặc ancestors để serialize mọi thao tác.
15. Không application lease, renewer, distributed/advisory lock, owner token hoặc fencing epoch. Chống ingest cũ bằng files.version/stage cùng transaction; upload expiry không reserve quota hoặc giữ độc quyền file.
16. Không network S3/SpiceDB/Temporal/model trong transaction đang giữ row locks. Quota là điểm contention thật giữa byte-changing writes cùng workspace; đo và giữ transaction ngắn, không tự thêm reservation/sharding vì tải giả định.
17. Idempotency dùng receipt/result cùng local SQL transaction hoặc domain identity đã chốt. Không durable pending-operation framework, custom mutation retry engine hoặc lời hứa global exactly-once xuyên providers.
18. SQL phải set-based và batch; không N+1 SQL/RPC, duplicate resolve/hydrate, Stat/readback sau mutation hoặc đọc payload lớn để list metadata. RETURNING, indexes theo query owner và keyset pagination; không SUM/count toàn storage mỗi write/page.
19. Không ép một SQL/CTE khổng lồ để đẹp số query. Đo statements, round trips, bytes, lock wait và EXPLAIN trên fixture bình thường; không claim nhanh hơn/rẻ hơn từ số LoC hoặc library choice.
20. Temporal chỉ giữ durable flows đã chốt, dùng retries/heartbeats/schedules native. Không per-node CRUD/copy workflows, lifetime membership coordinator hoặc custom jobs/history database; file text/manifests/chunks không nằm trong history.
21. Platform/LetFS chỉ application gRPC; Envoy JSON/ZIP, S3 signed HTTP và Leta HTTP/SSE giữ boundaries đã chốt. Không Gin/grpc-gateway/listener riêng cho health/metrics hoặc gateway mapper ép mọi error thành một envelope.
22. MVP private network + Clerk JWT và resource authorization. Permission checks mặc định minimize_latency, optional ZedToken read-after-write; chấp nhận stale window, không local cache hoặc forced fully_consistent mọi mutation. Production mTLS native khi triển khai, không credential/PKI framework trước nhu cầu.
23. Một YAML hoàn chỉnh mỗi môi trường, secret ở dotenv/ENV và YAML tham chiếu ENV. Không secret-file tree, defaults/endpoints rải rác, config merge/interpolation DSL, hot reload hoặc validation lặp mỗi request.
24. Telemetry dùng native OTel/logging, labels bounded và instrumentation có ích. Không telemetry service/database, per-chunk span explosion, duplicate logs hoặc dựng monitoring stack trước khi chọn backend.
25. Test hành vi và invariant ở lớp thấp nhất đủ chứng minh, dùng application/dependencies thật cho integration/E2E. Chỉ thay paid/external APIs tại boundary; không mock business engine, fake data/always-pass checks để che implementation thiếu.
26. Giữ TypeScript + Playwright cho cả api và browser. API dùng request contexts; browser dùng frontend thật khi có. Không tự đổi sang Python vì backend polyglot, cắt browser hoặc lặp toàn bộ API matrix qua UI. Dùng native fixtures/expect.poll/web-first assertions, không test SDK/scenario DSL/polling engine riêng.
27. CI chạy affected owners/consumers, reuse fixtures và một full E2E stack. Không coverage quota, test-count target, matrix mọi transport/layer/OS hoặc boot stack mỗi test; không giấu failure bằng skip/retry/compatibility. Cache dependencies/build layers, không cache correctness results.
28. Infra theo VPS/Compose đã chốt: hai Compose files viết tay, sáu script responsibilities, native Make/pnpm/Go/uv/Buf và hai workflows. Không thêm plan/phase scripts, environment manager, test/control/deploy framework, Kubernetes hoặc cloud variants chưa dùng.
29. Deploy cùng image digests đã được test, giữ persistent volumes và backup/restore native. Database mới không import dữ liệu cũ; không converter/dual-write. Database cũ và dirty work giữ nguyên; backup trước schema/data change, không reset/xóa ngầm hoặc commit secrets.
30. Workspace resource ownership theo workspace-service-redesign.md. Core không cần Leta running cho startup/readiness/hot-path hoặc storage deletion; async owning cleanup được phép. Concrete Leta API/runtime/multiple storage hoãn; không đọc SQL/queue/thread nội bộ hoặc tự thêm callback/transport.
31. Tất cả nằm trong plan hiện tại; cập nhật owning document thay vì tạo plan/report/framework mới mỗi phát sinh. Theo yêu cầu của người dùng, không dùng skill trong đợt này.
32. Kiểm chứng sớm native capabilities trên pinned versions, nhất là Envoy ZIP/status, Go/Python Temporal và signed S3. Nếu thất bại buộc đổi semantics/schema/architecture, đưa bằng chứng và các lựa chọn nhỏ nhất rồi thảo luận; không âm thầm tự chế thay thế. Routine SQL/file layout/native SDK options tự thực hiện trong phạm vi đã chốt, không mở vòng hỏi lại.
33. Hoàn thành gồm callers, generated contracts, manifests, config, tests và CI bị ảnh hưởng. Không dừng ở producer compile/test hẹp; không báo toàn hệ thống pass khi chưa chạy. Báo rõ validation/số đo thật và phần chưa kiểm chứng.

## 18. Boundary hiện tại thay thế các đề xuất trước

Ngày 2026-11-12 user chốt Leta là workspace resource có subject riêng; Platform/LetFS/Leta là peer domain services. Đề xuất SQL-only, external_actor opaque, storage mapping ở Platform và cấm tuyệt đối core resource cleanup call không còn authority.

[Workspace resources](workspace-service-redesign.md) ghi exact authority/roles/visibility/lifecycle; [schema](schema.md) và [API contract](api-contract.md) ghi current boundary. Không đọc SQL/thread/box/history/queue của service khác; shared authorization relationships là contract chung, không business runtime database.

Core không phụ thuộc Leta startup/readiness/hot-path và không stop ACK trước xóa storage. Async owning cleanup intent được phép; concrete API Leta hoãn, không tự implement transport/callback/queue thay thế trước review. Không lấy thay đổi này làm lý do viết lại domain/runtime Leta.
