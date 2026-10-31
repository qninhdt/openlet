# Openlet — Quyết định kiến trúc cuối cùng (Status → Processing)

> **Phạm vi:** Tổng hợp các quyết định đã thống nhất trong cuộc thảo luận, bắt đầu từ quy ước `status` đến kiến trúc `processing`. Đây là **target design**, không phải tuyên bố source hiện tại đã được refactor.
>
> **Phân biệt:** **Đã chốt** = quyết định về kiến trúc; **Chưa chốt chi tiết** = còn phải xác nhận hợp đồng API, provider hoặc chính sách vận hành trước khi code. Không suy diễn rằng một schema ví dụ đã là migration cuối cùng.

## 1. Quy ước `us` — ĐÃ CHỐT

- Chuẩn hóa tên cột mô tả lifecycle của resource thành **`status`**, thay vì lẫn `state`, `onboarding_state` hoặc các tên không thống nhất.
- **Mỗi bảng có tập giá trị hợp lệ riêng**; không tạo một PostgreSQL enum global cho tất cả resource.
- Ưu tiên `TEXT NOT NULL CHECK (status IN (...))` cho các trạng thái cần ràng buộc ở DB.
- Chỉ lưu `status` khi resource có một lifecycle thực sự quan trọng với hành vi nghiệp vụ; không nhân bản trạng thái retry/execution mà Temporal đã quản lý.
- Resource có hai lifecycle độc lập thì dùng tên tường minh (`publication_status`, `index_status`), không nhồi vào cùng một `status`.

| Resource                | Trạng thái định hướng                               | Ghi chú                                                       |
| ----------------------- | --------------------------------------------------- | ------------------------------------------------------------- |
| `users`                 | `provisioning`, `active`                            | Onboarding/readiness, không phải trạng thái Temporal Activity |
| `workspaces`            | `provisioning`, `active`, `deleting`, `deleted`     | Bảo vệ truy cập trong lúc provision/delete                    |
| `quota_buckets`         | `active`, `frozen`, `deleted`                       | Freeze để ngăn ghi mới khi dọn dữ liệu                        |
| `filesystems`           | `active`, `deleting`, `deleted`                     | Lifecycle của filesystem                                      |
| `workspace_invitations` | `pending`, `accepted`, `revoked`                    | Expiration vẫn phải được xử lý riêng                          |
| `trash_entries`         | `trashed`, `purging`                                | Ngăn restore trong lúc purge                                  |
| `uploads`               | `open`, `completing`, `finalized`, `aborted`        | Expired có thể biểu diễn bởi timestamp và maintenance         |
| `nodes`, `files`        | Không có lifecycle status chung                     | Dùng identity/metadata/revision                               |
| `object_deletions`      | Không cần job-status phức tạp nếu pending-intent đủ | Còn phụ thuộc cơ chế chống late write                         |

**Điểm cần lưu ý:** Bảng `operations` sẽ bị loại bỏ theo kiến trúc đích, nhưng các trạng thái nghiệp vụ thực sự và checkpoint cho quá trình xóa/copy dài vẫn cần chỗ lưu phù hợp nếu không thể được thay thế an toàn bằng Temporal History.

## 2. `operations` và ranh giới Temporal — ĐÃ CHỐT VỀ HƯỚNG

- Loại bỏ **generic `operations` tables** khỏi `user`, `workspace`, `letfs` sau khi chuyển các trách nhiệm còn cần thiết ra đúng nơi.
- Temporal chịu trách nhiệm orchestration, scheduling, retries, workflow execution và activity history; không tạo một job framework trùng lặp trong PostgreSQL.
- **Không** đồng nghĩa xóa mọi checkpoint, durable intent, upload session, deletion cursor, artifact-publication state hoặc business status.
- Đối với operation chạy lâu, API có thể trả `202 Accepted` và một status monitor; thời hạn tra cứu status phải được định nghĩa theo Temporal retention / dữ liệu nghiệp vụ còn tồn tại.
- Temporal Activity vẫn chạy theo cơ chế *at least once* ở side-effect boundary; các mutation bên ngoài phải an toàn khi Activity retry.

## 3. Chính sách idempotency thống nhất — ĐÃ CHỐT

### 3.1. Quy tắc

- **Không yêu cầu `Idempotency-Key` cho mọi mutation.** Chỉ dùng khi effect không có idempotency tự nhiên, hoặc khi API yêu cầu deduplication/replay theo request.
- Natural idempotency có thể đến từ resource ID, unique constraint, state transition, assignment (`SET x = value`), revision/`If-Match`, hoặc một session ID đã tồn tại; **có ID không tự động làm mọi hành động idempotent** (ví dụ cộng quota cần bảo vệ riêng).
- Không dùng file name làm **request idempotency key**; file name là ràng buộc namespace của filesystem.
- Không lưu request idempotency key vĩnh viễn trên resource chỉ để retry: các mutation cần key dùng **receipt table với TTL** tại service thực thi mutation.
- Không giữ một `provision_key` độc lập nếu cùng chức năng đã được phục vụ bởi request-level `Idempotency-Key` theo hợp đồng mới; những endpoint `Ensure*` cũ được thiết kế lại thống nhất.
- Không bắt buộc `fingerprint` riêng: cùng key/khác payload là kiểm tra tuỳ chọn theo API contract. Nếu cần nghiêm ngặt, lưu `request_hash` trong receipt, không tạo tầng fingerprint/operations mới.
- Server phải xử lý key **atomically**: concurrent requests cùng key không được tạo hai effect; request đang xử lý phải có kết quả `in-progress`/xử lý đồng thời phù hợp, không được báo thành công giả.
- TTL giới hạn phạm vi deduplication: sau khi receipt bị prune, key cũ **không còn được bảo đảm** nhận diện như retry; công bố retention phù hợp.

### 3.2. Ai sinh key?

| Caller                                | Quy tắc                                                                                                                                                               |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Browser                               | Sinh UUIDv4/v7 **một lần cho logical operation**, lưu đủ lâu để retry và gửi `Idempotency-Key`                                                                        |
| Go/Rust/Python service                | Cũng là client: tạo key một lần cho mutation, giữ nguyên key khi retry                                                                                                |
| Temporal Activity                     | Theo hướng dẫn Temporal, dùng identity ổn định qua retries, điển hình **`Workflow Run ID + Activity ID`**                                                             |
| Qua `Continue-As-New` / execution mới | Nếu cùng *logical operation* phải tồn tại qua nhiều executions, truyền key ổn định trong Workflow input / logical step identity; không mặc định Run ID còn giữ nguyên |

- Không cần Activity riêng chỉ để sinh UUID phục vụ idempotency. Temporal lưu Workflow/Activity input trong Event History để replay.
- **Workflow ID** giúp nhận diện workflow được start trùng theo policy/retention; **Activity idempotency key** dùng khi gọi side-effect API. Hai khái niệm không nên đánh đồng.
- Key được scope theo authenticated caller/actor và operation/API semantics, không tin `caller_id` do request body tùy ý khai báo.

### 3.3. Nơi chịu trách nhiệm

| Service                         | Thiết kế                                                                                                                                                                                     |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `user`                          | **Không cần** idempotency table cho onboarding/profile; Clerk identity (`clerk_id UNIQUE`) là natural identity                                                                               |
| `workspace`                     | Receipt table có TTL cho các mutation thực sự cần request-level deduplication, chủ yếu `CreateWorkspace`; invitation xử lý bằng natural uniqueness nếu đổi contract                          |
| `letfs`                         | Một receipt table có TTL cho các filesystem mutation **không idempotent tự nhiên**: provisioning server-generated IDs, strict create/copy, upload-session creation, một số processor outputs |
| Workspace proxy → Letfs         | Workspace authorize/resolve scope và **chuyển tiếp cùng key**; Letfs chịu trách nhiệm thực hiện và deduplicate filesystem mutation, không tạo receipt trùng ở proxy                          |
| Temporal Activity → Service API | Truyền key ổn định như mọi client khác; service nhận mutation xử lý receipt hoặc natural idempotency                                                                                         |

**Schema định hướng, chưa khóa cứng tên cột:**

```sql
CREATE TABLE idempotency_keys (
    caller_scope TEXT NOT NULL,
    key UUID NOT NULL,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    result JSONB,
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (caller_scope, key)
);
```

- Receipt tối thiểu cần nhận biết đang thực hiện/hoàn tất và trả resource/operation handle (hoặc response nếu contract đòi hỏi).
- Không biến receipt thành bảng nghiệp vụ chứa copy checkpoint, quota lifecycle hoặc workflow execution history.
- Với mutation DB, receipt và side effect cần được giao dịch atomically nếu có thể; với S3/Temporal hoặc cross-service phải thiết kế admission/commit/recovery rõ ràng, **không** thể coi unique key một mình là transaction phân tán.

### 3.4. Các mutation chính

| API class                          | Hướng xử lý                                                                                |
| ---------------------------------- | ------------------------------------------------------------------------------------------ |
| User onboarding                    | Natural uniqueness theo `clerk_id`                                                         |
| Profile updates                    | Assignment theo `user_id`; revision/conditional update nếu cần                             |
| Create workspace                   | `Idempotency-Key` + workspace receipt TTL                                                  |
| Rename workspace / edit membership | Resource identity + revision/state/unique membership                                       |
| Workspace delete                   | Workspace ID + deletion lifecycle và workflow identity ổn định                             |
| Create invitation                  | Một **pending** invitation cho `(workspace_id, normalized_email)`; unique index chống race |
| Accept/revoke invitation           | Invitation token/ID + membership uniqueness + terminal transitions                         |
| Letfs create bucket/filesystem     | Request key nếu Letfs tự sinh IDs; IDs do Letfs sở hữu                                     |
| Create directory/text node         | Key nếu yêu cầu strict retry; unique destination vẫn phải giữ                              |
| Copy node/tree                     | Request key cho một logical copy operation                                                 |
| Rename/move/replace/trash          | Resource ID, revision và state transition; không mặc định cần key                          |
| Upload create                      | Request key tạo session                                                                    |
| Upload finalize/abort              | Upload ID + terminal state/result; không cần key riêng                                     |
| Object DeleteObject                | Key của object và durable cleanup intent; retry theo effect idempotency                    |

**Invitation caveat:** Nếu API trả plaintext invite token nhưng DB chỉ lưu hash, retry có thể tìm invitation cũ mà không lấy lại plaintext token. Cần chốt contract: gửi link qua email/không replay token, hoặc giữ receipt/token an toàn trong thời gian cho phép; đây là vấn đề response, không phải race tạo trùng.

## 4. Filesystem name uniqueness — ĐÃ CHỐT

- Request idempotency độc lập với filesystem namespace constraint.
- Vẫn ràng buộc **một tên duy nhất dưới cùng một parent trong cùng filesystem** cho các node live.
- Ví dụ: Request `K1` create `report.pdf` → retry `K1` trả kết quả đã nhận diện; request **mới** `K2` tạo cùng tên → `409 Conflict`.
- Target unique key cơ bản: `(filesystem_id, parent_id, name)`; xử lý riêng `NULL parent_id`, detached/trash, root và policy case sensitivity/canonicalization.
- `If-Match`/revision giải quyết lost updates; không có nghĩa retry lúc nào cũng nhận HTTP response giống lần đầu.

## 5. Ownership và proxy boundary — ĐÃ CHỐT

- Ba service giữ ranh giới: `user` (identity), `workspace` (workspace/collaboration/authorization), `letfs` (generic filesystem/storage).
- Letfs **generic**: bất kỳ authenticated external service phù hợp quyền đều có thể xin cấp filesystem; không thêm FK hoặc `workspace_id` domain-specific vào schema chung chỉ để idempotency.
- Service **sở hữu resource tự sinh resource ID**. Caller cung cấp operation identity/key ổn định, không cần cấp `filesystem_id` thay Letfs.
- Workspace là **filesystem public facade/proxy**: kiểm tra quyền, map workspace → filesystem, forward key/identity. Letfs là source of truth của mutations và receipt.
- Đã thống nhất trước đó: `workspace_storage` gộp vào `workspaces` (quota bucket/filesystem/root IDs và storage limit), song một workspace có thể tạm thời `provisioning` trước khi cấp đủ tài nguyên.

## 6. Thiết kế HTTP API — ĐÃ CHỐT HƯỚNG RESOURCE-ORIENTED

### 6.1. Quy tắc chung

- Public: `/v1/...`; nội bộ: `/internal/v1/...`.
- Danh từ số nhiều, resource IDs trong URL; `GET` read/list, `POST` create, `PATCH` partial update, `PUT` replace/content, `DELETE` delete.
- Không dùng `/files/{action}` và những endpoint đặt theo tên hàm `rename`, `move`, `stat`, `ensure`, `freeze` khi có resource semantics rõ.
- Chỉ dùng custom method khi thật sự cần (ví dụ `:restore`), không tạo một bảng/tài nguyên giả chỉ để REST thuần hình thức.
- `nodes` là collection thống nhất cho file và directory; `PATCH /nodes/{id}` quản lý rename/move.
- Áp dụng `ETag` + `If-Match` cho cạnh tranh revision, JSON `snake_case`, error schema `application/problem+json` theo RFC 9457.
- HTTP: `201 Created + Location` cho resource mới, `202 Accepted + Location` cho việc còn chạy, `204` cho mutation không body; `409` conflict tên, `412` revision mismatch, `428` thiếu required precondition.
- Đây là **định hướng contract**. Một số URL biến thể/edge cases (batch search, quota freeze, async monitor) cần chốt trong OpenAPI trước khi triển khai.

### 6.2. Public User API

```http
GET   /v1/me
PATCH /v1/me
GET   /v1/me/onboarding
PUT   /v1/me/onboarding
```

- Onboarding singleton dựa trên Clerk identity, không cần bắt client gửi một idempotency key riêng.
- Internal read: `GET /internal/v1/users?ids=...` (nếu batch nhỏ); giữ batch POST-read nếu kích thước query lớn. Verified-emails vẫn là subresource read.

### 6.3. Public Workspace + Collaboration API

```http
GET    /v1/workspaces
POST   /v1/workspaces
GET    /v1/workspaces/{ws}
PATCH  /v1/workspaces/{ws}
DELETE /v1/workspaces/{ws}

GET    /v1/workspaces/{ws}/members
PATCH  /v1/workspaces/{ws}/members/{user}
DELETE /v1/workspaces/{ws}/members/{user}

GET    /v1/workspaces/{ws}/invitations
POST   /v1/workspaces/{ws}/invitations
DELETE /v1/workspaces/{ws}/invitations/{id}
POST   /v1/memberships
```

- Ownership transfer được biểu diễn như thay đổi owner trên `PATCH /workspaces/{ws}` nhưng backend vẫn thực hiện transaction/authorization đặc thù; không coi là update một field tùy ý.
- `POST /memberships` với invitation token đại diện cho accept invitation, thay vì `/invitations/accept`.
- Workspace status monitor cho async operation nếu cần và có contract retention rõ.

### 6.4. Public Filesystem API do Workspace expose

> Prefix: `/v1/workspaces/{ws}`.

```http
GET    /nodes?parent_id=...
POST   /nodes
GET    /nodes/{node}
PATCH  /nodes/{node}
DELETE /nodes/{node}
GET    /nodes/{node}/content
PUT    /nodes/{node}/content
GET    /nodes/{node}/archive

GET    /trash-entries
POST   /trash-entries/{entry}:restore
DELETE /trash-entries/{entry}

GET    /uploads/{upload}
POST   /uploads
GET    /uploads/{upload}/parts?numbers=...
PUT    /uploads/{upload}/completion
DELETE /uploads/{upload}

GET    /search?q=...
POST   /search
GET    /nodes/{node}/processing
POST   /nodes/{node}/processing-runs
GET    /storage
```

- `POST /nodes`: tạo directory, inline text file, hoặc copy từ `source_id` (copy lớn có thể trả `202`).
- `DELETE /nodes/{id}`: đưa vào Trash; `DELETE /trash-entries/{id}`: purge vĩnh viễn.
- `GET /nodes/{id}/archive`: ZIP folder stream trực tiếp, không tạo export job.
- `GET /search` cho query đơn giản, `POST /search` **read-only** cho body filter phức tạp.
- Presigned part URL retrieval có thể là GET vì không mutate session; phải `Cache-Control: no-store`.
- Upload completion là singleton theo upload ID (`PUT`), idempotent nhờ session result.

### 6.5. Internal Letfs API

> Prefix: `/internal/v1`; mirror những resource semantics mà service thật sự sở hữu.

```http
POST   /quota-buckets
GET    /quota-buckets/{bucket}
PATCH  /quota-buckets/{bucket}
DELETE /quota-buckets/{bucket}
GET    /quota-buckets/{bucket}/filesystems

POST   /filesystems
GET    /filesystems/{fs}
DELETE /filesystems/{fs}

GET    /filesystems/{fs}/nodes
POST   /filesystems/{fs}/nodes
GET    /filesystems/{fs}/nodes/{node}
PATCH  /filesystems/{fs}/nodes/{node}
DELETE /filesystems/{fs}/nodes/{node}
GET    /filesystems/{fs}/nodes/{node}/content
PUT    /filesystems/{fs}/nodes/{node}/content

GET    /filesystems/{fs}/trash-entries
POST   /filesystems/{fs}/trash-entries/{entry}:restore
DELETE /filesystems/{fs}/trash-entries/{entry}

POST   /filesystems/{fs}/uploads
GET    /filesystems/{fs}/uploads/{upload}
GET    /filesystems/{fs}/uploads/{upload}/parts
PUT    /filesystems/{fs}/uploads/{upload}/completion
DELETE /filesystems/{fs}/uploads/{upload}
```

- `PATCH /quota-buckets/{id}` (ví dụ status = frozen), `DELETE /quota-buckets/{id}` (complete deletion) là định hướng REST; invariant nghiệp vụ không được nới lỏng.
- Processor có thể cần `PUT /filesystems/{fs}/uploads/{id}/content` nội bộ nếu upload bytes qua backend.
- Thay `POST /files/{action}` bằng typed handlers/resources rõ ràng; không cho Workspace proxy chuỗi action tùy ý.

## 7. Upload và Download — ĐÃ CHỐT KIẾN TRÚC

### 7.1. Inline file nhỏ

- Client → Letfs → PostgreSQL `nodes` + `files` trong một transaction.
- Không tạo upload session chỉ để ghi file inline nhỏ.

### 7.2. Object file (S3-compatible storage)

- **Direct-to-S3:** Client (browser hoặc external service) → S3 bằng presigned PUT / Multipart; bytes không đi qua Workspace/Letfs thông thường.
- Letfs backend xác thực/quyền/quota, tạo upload session + object key mới, cấp URL, xác minh bytes, rồi publish metadata trong PostgreSQL.
- Sử dụng Rust `object_store`/native provider APIs cho S3 multipart, presigning và storage operations; **không tự xây lại S3 multipart protocol**, không thêm một upload server/tusd chỉ để tải file.
- Tạo upload session cần request-level key; finalize dựa vào `upload_id`, lưu outcome ổn định.
- Một upload có **object key mới, bất biến**, không ghi đè object key của version đang publish.
- `replace` kiểm tra expected revision và atomically chuyển `files.object_key` sang key mới, enqueue old key vào `object_deletions` trong cùng DB transaction.
- Quota/destination/preconditions phải kiểm tra lại tại finalize; không chỉ check ở create-session.
- Verify size/checksum bằng khả năng provider; **không giả định ETag luôn bằng MD5**, nhất là multipart.
- Multipart completion cần đủ durable receipts/part evidence để phục hồi sau timeout; không xóa thông tin cần thiết chỉ để giảm số cột.
- Các upload records terminal cần TTL/pruning sau khi đã giải quyết nghĩa vụ cleanup an toàn.

```text
POST uploads (auth/quota/session) → presigned URL(s)
    ↓
Client PUT/UploadPart trực tiếp S3
    ↓
PUT uploads/{id}/completion
    ↓
Complete MPU nếu cần → verify object
    ↓
SQL transaction: publish nodes/files + finalize upload + queue old-key deletion
```

### 7.3. Download

- Inline files: Letfs trả bytes trực tiếp; có thể hỗ trợ HTTP Range.
- S3 files: Letfs kiểm tra quyền, trả redirect/presigned GET; client lấy bytes từ S3 trực tiếp, cần xử lý đúng Range và URL TTL.
- Folder ZIP: Rust Axum + `async_zip` stream từ nguồn file; giữ cây thư mục (kể cả empty dirs). Không tạo ZIP tạm trên S3, không tạo export Workflow, không cần Temporal cho tải ZIP thông thường.
- Ngắt kết nối ZIP stream → tải lại từ đầu (đã chấp nhận cho MVP).

### 7.4. Upload DB responsibility

- `uploads`: transfer/session/ownership + multipart state + verification/finalization result.
- Processing-specific stage/generation/attempt metadata **không nên trộn sâu** vào upload table; liên kết tới processing run/output identity thay vì nhân bản upload lifecycle.
- Không cần chia `user_uploads` và `processor_uploads`: sử dụng chung upload transport.

## 8. Trash — ĐÃ CHỐT

- Giữ `trash_entries` riêng, không gộp vào `nodes` hay thay bằng Workflow History.
- Trash folder bằng cách detach subtree root khỏi live tree, **không copy toàn cây sang nơi khác**.
- `trash_entries` giữ original parent/name/actor và trạng thái để restore/purge.
- Restore kiểm tra conflict destination; purge có thể chạy async; giữ node IDs khi restore.
- Trash retention tự động (ví dụ 30 ngày) là lựa chọn sản phẩm, **chưa bắt buộc chốt**.

## 9. Durable `object_deletions` và Temporal Maintenance — ĐÃ CHỐT + 1 NGOẠI LỆ

- **Giữ bảng `object_deletions`** như transactional outbox / durable deletion intent: PostgreSQL metadata thay đổi và enqueue object key trong **cùng transaction**.
- **Giữ Temporal Schedule hiện có (5 phút)** điều phối batch deletion Activity; **không thêm queue broker, lease service, scheduler hoặc Workflow riêng cho mỗi object**.
- Worker đọc object keys đến hạn, kiểm tra còn tham chiếu/đang upload không, gọi S3 `DeleteObject`, rồi hoàn tất intent khi thật sự an toàn.
- Retry side effect được Temporal hỗ trợ; DeleteObject với key bất biến và bucket versioning policy tương thích có thể gọi lặp. Tránh nhầm `DeleteObject` trên versioned bucket với purge tất cả object versions.
- Mục tiêu là **bảng pending intents đơn giản**, không giữ job history với `pending → deleting → deleted` vĩnh viễn.
- Worker overlap policy, retry và duplicate execution phải được xử lý theo Temporal + tính idempotent của delete; không mặc định cần DB lease nếu không có nhu cầu multi-consumer claim độc lập.
- **S3 Lifecycle `AbortIncompleteMultipartUpload`** là safety net cho MPU bỏ dở, **không** thay thế deletion outbox của object đã publish.

**Schema đích tối thiểu đang cân nhắc, KHÔNG phải migration cuối cùng:**

```sql
CREATE TABLE object_deletions (
    object_key TEXT PRIMARY KEY,
    bucket_id UUID NOT NULL,
    eligible_at TIMESTAMPTZ NOT NULL
);
```

**Chưa chốt an toàn:** Bỏ `ambiguous_write`/terminal tombstone chỉ khi bảo đảm không còn request ghi muộn có thể tạo lại object. Nếu không chứng minh được điều đó, phải giữ tombstone/ghi nhận ambiguity hoặc thiết kế reconciliation, không được prune vô điều kiện.

### 9.1. Late-write hazard minh họa

```text
T0  Letfs cấp presigned PUT cho objects/K
T1  Client bắt đầu PUT nhưng request còn đang chạy
T2  Upload hết hạn / bị hủy; Letfs enqueue DeleteObject(K)
T3  Cleanup worker DeleteObject(K) → S3 báo thành công (K hiện chưa tồn tại)
T4  PUT từ T1 hoàn thành → S3 lại có objects/K (mồ côi)
T5  Nếu đã DELETE object_deletions row tại T3 thì không còn ai biết cần dọn K
```

- Presigned URL expiry chủ yếu kiểm tra lúc **request bắt đầu**, không có nghĩa request đang chạy sẽ tự bị hủy đúng thời điểm hết hạn.
- `If-None-Match: *` ngăn overwrite object **đang tồn tại**, nhưng sau khi cleanup xóa object, điều kiện tồn tại có thể lại thỏa; nó **không tự giải quyết** late-create race.
- Multipart: backend phải kiểm soát `CompleteMultipartUpload`; `AbortMultipartUpload` có thể xảy ra đồng thời với các part uploads còn in-flight, nên cần xử lý provider behavior và dọn dangling parts.
- Không có bằng chứng cho một khoảng grace cố định bảo đảm an toàn tuyệt đối trên mọi S3-compatible provider. Chính sách thực tế có thể gồm TTL rất ngắn, client write fencing, bảo đảm completion chỉ ở backend, các hạn mức transfer có thể chứng minh, và một kỳ reconciliation/re-delete bảo thủ.
- **Kết luận:** Terminal deletion intent chỉ được prune khi write capability/in-flight uncertainty đã được đóng hoặc có một chính sách recovery rõ ràng.

## 10. Processing pipeline — ĐÃ CHỐT HƯỚNG

### 10.1. Service responsibilities

- **Letfs** sở hữu filesystem state, file metadata, processing operation identity, publication và search/index readiness.
- **Temporal** điều phối các bước chạy dài/cross-service, retries, timeout, continuation/replay; **không** phải nơi lưu business metadata bất biến mãi mãi.
- **Python processor** nhận source để parse/extract → enrich/describe → tạo artifact output; Qdrant/index stage được publish theo contract của pipeline.
- Generated artifacts (text extracts, `README.md`, metadata) dùng **cùng upload transport** của Letfs, không tạo từng bộ endpoint khác nhau cho enrichment/processing attempts.
- Upload thành công chỉ có nghĩa **bytes đã tới storage**; không đồng nghĩa artifact đã được **publish** vào `nodes`/`files` hay đã **index-ready**.

### 10.2. Pipeline khái niệm

```text
File/version được publish trên filesystem
    ↓
Temporal ProcessFile Workflow (nguồn, version/generation/attempt identity)
    ↓
Parse / extract source
    ↓
Enrich / summarize / classify; chuẩn bị generated artifacts
    ↓
Processor upload artifacts qua Letfs upload transport chung
    ↓
Letfs verify bytes + publish artifact metadata cho đúng generation/attempt
    ↓
Index (Qdrant) + mark searchable/ready cho đúng version
```

- Các stage/attempt/generation identities phải ngăn **stale attempt** publish output hoặc ghi đè index của một version mới hơn (fencing).
- Retry stage/Activity không được tạo vô hạn upload sessions hoặc artifact nodes; sử dụng output identity ổn định hoặc request idempotency như các client khác.
- Chỉ lưu trạng thái nghiệp vụ cần cho serving (`published_version`, `indexed_version`, readiness/error cần hiển thị); không sao chép không cần thiết `running/retrying` của Temporal vào DB.
- Với semantic metadata: file chứa `title`, `description`, `semantic_type`, `context`; folder có thể được diễn đạt bằng `README.md` child theo quy ước đã thống nhất trước đó.

### 10.3. API processing nội bộ định hướng

> **Chưa chốt chính xác OpenAPI:** hướng là `processing-runs`, `stages`, `attempts` dạng resources, thay cho `/processing/{op}/enrichment/{action}` hoặc `/index/{action}`.

```http
PUT   /internal/v1/processing-runs/{run}/stages/{stage}
PATCH /internal/v1/processing-runs/{run}/stages/{stage}
PUT   /internal/v1/processing-runs/{run}/attempts/{attempt}
PATCH /internal/v1/processing-runs/{run}/attempts/{attempt}
```

- Chỉ expose HTTP cho những thao tác thật sự đi qua service boundary (ví dụ Python processor → Letfs); các bước nội bộ của cùng Letfs worker không cần tạo HTTP endpoints.
- Output upload dùng collection `uploads` chung với processing owner/attempt association, **không** nhân bản `enrichment/uploads/...` và `processing/.../uploads/...` chỉ do stage khác nhau.

## 11. Những điểm chưa chốt / cần kiểm chứng trước migration

1. **Idempotency receipt:** TTL, claim atomicity, response replay vs resource-handle, scope key, in-flight errors và cleanup; không đồng nhất receipt với `operations` cũ.
2. **Invitation token:** nếu chỉ lưu hash, retry có trả lại plaintext token hay không; hay chuyển sang gửi invitation qua email.
3. **Upload:** checksum contract của AWS S3 vs R2/MinIO, multipart completion evidence, threshold small/multipart và cleanup retention.
4. **Object deletion:** chính sách late-write fencing/reconciliation; **chưa được phép bỏ `ambiguous_write` chỉ vì Temporal đã có retry**.
5. **Processing:** chính xác stage output identity, commit/publish boundary, index version fencing, retry-safe generated artifacts và status monitor retention.
6. **REST:** xác nhận OpenAPI và các edge cases cho workspace ownership PATCH, multipart parts URL GET, async operation monitor và batch reads.
7. **Refactor:** trước khi xóa generic `operations`, rà hết nơi đang lưu deletion cursor, copy progress, processing intent hoặc response receipts, rồi chuyển phần thực sự cần sang đúng nguồn dữ liệu.

## 12. Tài liệu đối chiếu

- HTTP semantics (RFC 9110): [https://www.rfc-editor.org/rfc/rfc9110](https://www.rfc-editor.org/rfc/rfc9110)
- HTTP problem details (RFC 9457): [https://www.rfc-editor.org/rfc/rfc9457](https://www.rfc-editor.org/rfc/rfc9457)
- Zalando REST API guidelines: [https://opensource.zalando.com/restful-api-guidelines/](https://opensource.zalando.com/restful-api-guidelines/)
- Google API design guide: [https://google.aip.dev/](https://google.aip.dev/)
- Temporal Activity idempotency: [https://docs.temporal.io/activity-definition](https://docs.temporal.io/activity-definition)
- AWS S3 presigned URLs: [https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html)
- AWS S3 conditional writes: [https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)
- AWS S3 abort multipart: [https://docs.aws.amazon.com/AmazonS3/latest/API/API_AbortMultipartUpload.html](https://docs.aws.amazon.com/AmazonS3/latest/API/API_AbortMultipartUpload.html)

---

*Ghi chú này phản ánh quyết định đã thảo luận, đồng thời đánh dấu rõ những vấn đề an toàn/correctness chưa được giải quyết bằng một lựa chọn triển khai cụ thể.*
