# Schema hiện tại: boundary Platform và LetFS

Cập nhật 2026-11-12 theo [architecture đã chốt](workspace-service-redesign.md). [API contract](api-contract.md) đã chốt qua trao đổi. Baseline migrations đã implementation cho database mới; executable DDL tại apps/platform/migrations và apps/letfs/migrations là schema thực thi. File/content/processing/transfer fields không liên quan boundary được giữ.

## 1. Identity và service trust

Platform/LetFS chỉ application gRPC, public JSON qua Envoy. Envoy verify Clerk JWT, strip trusted identity headers rồi bind human identity. ActorRef user/agent khác caller process; internal Leta/Computer bind subject từ invocation. Không lấy actor tùy ý trong public body.

MVP tin private service network, không application service tokens/credential registry/caller-name authentication. Internal lifecycle/processing không public qua Envoy. Sandbox/untrusted clients không ở private service network. Production dùng native mTLS khi triển khai; provider/database/SpiceDB credentials native vẫn giữ.

## 2. Source of truth và field policy

SpiceDB canonical workspace membership, resource ownership và role grants. Không SQL membership/grant/owner mirror hoặc personal mapping. PostgreSQL giữ actual workspace_id, visibility và domain data. Parent/public relations được owning service đưa vào graph; SQL+graph không atomic.

Không thêm owner_id/created_by để phục vụ permission. Event actor IDs thật như approver/sender/trashed_by vẫn giữ. Không onboarding flags, initial workspace ID/state, revision/generation hoặc status mirrors. Workspace lifecycle và processing.stage giữ vì có consumer thật.

## 3. Platform database: 4 bảng

### users

```text
id              uuid PK
clerk_subject   text UNIQUE NOT NULL
display_name    text NOT NULL
avatar_url      text NULL
```

Auth/profile giữ nguyên. Onboard INSERT user + system-created default workspace trong local transaction chỉ khi user mới; retry existing Clerk subject trả existing user, không tự tạo thêm workspace. Client dùng ListWorkspaces; không personal-storage mapping hoặc initial progress fields.

### workspaces

```text
id              uuid PK
name            text NOT NULL
state           text NOT NULL  -- provisioning | active | deleting
created_at      timestamptz NOT NULL
```

Owner canonical graph, không created_by dùng như owner. Không filesystem_id/shared_scope_id/quota counters hoặc member_scopes. System provisioning giữ ordinary storage UUIDs trong native workflow input/receipts; SQL workspace không là storage registry. Cleanup core xong xóa row, không deleted state/tombstone hoặc phase flags. Leta physical cleanup API hoãn, không stop-ACK barrier.

### invitations

```text
id           uuid PK
workspace_id uuid FK workspaces ON DELETE CASCADE
email        text NOT NULL
token_hash   bytea UNIQUE NOT NULL
expires_at   timestamptz NOT NULL
accepted_by  uuid FK users NULL
```

Invite chỉ member, không role column. Owner transfer là API riêng. Consume bằng accepted_by, expiry từ expires_at, revoke DELETE. Giữ consumed row để token cũ không regrant; không status/revoked_at/consumed_at. Token plaintext chỉ first response, không receipt secret.

### idempotency_keys

```text
caller       text
method       text
key          uuid
request_hash bytea NOT NULL
result       bytea NULL
expires_at   timestamptz NOT NULL
PRIMARY KEY (caller,method,key)
```

Canonical actor key user:<id>/agent:<id>; không workload credential. result chỉ NULL trong transaction chưa commit, chứa small protobuf response. Không attempt/lease/pending-operation fields. Graph-only mutation dùng native writes; multi-store lifecycle dùng native durable workflow, không coi receipt local là distributed transaction.

## 4. LetFS database: 9 bảng

### workspace_storage

```text
workspace_id uuid PK
quota_bytes  bigint NOT NULL
used_bytes   bigint NOT NULL
```

Mapping 1-1 workspace budget, không storage resource ID/name/state riêng. Quota/usage canonical tại LetFS, dùng chung mọi storage, không mirror sang Platform. Native conditional UPDATE cuối local mutation transaction; không reserve quota qua upload/model/RPC.

### storages

```text
id               uuid PK
workspace_id     uuid FK workspace_storage ON DELETE CASCADE
name             text NOT NULL
visibility       text NOT NULL  -- private | public
root_node_id     uuid UNIQUE NOT NULL
allow_blob_files boolean NOT NULL
allow_indexing   boolean NOT NULL
```

Nhiều storage/workspace/owner ngay từ schema. Visibility public mặc định read cho actors hợp lệ trong workspace, editor/owner mới write; public_workspace graph relation chỉ tồn tại khi public. Không kind personal/shared/home, owner columns, personal_storages, unique actor→storage hoặc UUIDv5.

ID là UUID thông thường giữ trong provisioning identity. MVP system tạo storage ban đầu; FE nhóm private mà mình owner thành “của tôi”, public thành “chung workspace”, private được share vẫn discover. Agent root giữ một storage_id; multiple/switch hoãn.

Root/policy/containment giữ contract hiện có. Same-storage parent và unique sibling constraints giữ cấu trúc cây. Blob/index flags giữ như immutable policy đã chốt. Không storage lifecycle/permission cache fields.

### nodes

```text
id         uuid PK
storage_id   uuid FK storages ON DELETE CASCADE
parent_id  uuid NULL
name       text NOT NULL
kind       text NOT NULL  -- directory | file
created_at timestamptz NOT NULL
updated_at timestamptz NOT NULL
```

Identity/tree và ctime/mtime cho workspace storage metadata/cache. Scope roots và detached trash roots có parent NULL; root_node_id/trash_entries phân biệt hai trường hợp. Không size/revision/generation/status/trash flags/artifact source/generated flags. Same-storage parent FK và unique sibling name giữ cấu trúc cây; ancestry resolver xác định live/readonly.

### files

```text
node_id      uuid PK FK nodes ON DELETE CASCADE
version      bigint NOT NULL
size_bytes   bigint NOT NULL
media_type   text NOT NULL
text_content text NULL
object_key   text NULL
CHECK (num_nonnulls(text_content,object_key)=1)
```

File type ở API vẫn đúng text hoặc blob. Không cần lưu cột file_type/storage_kind thứ hai: text_content có giá trị (kể cả chuỗi rỗng) là text; object_key có giá trị là blob. Stat/List lấy nullness flag mà không kéo text payload; index text dùng WHERE text_content IS NOT NULL.

Version bảo vệ content concurrency và processing publication; size phục vụ quota/list mà không đọc bytes; media_type phục vụ download/parser/image handling. Không SHA/newline counters mặc định, desired_generation, upload state, AI metadata hoặc duplicate byte payload.

### file_metadata

```text
node_id       uuid PK FK files ON DELETE CASCADE
title         text NULL
description   text NULL
semantic_type text NULL
context       text NULL
```

Metadata enrichment hiện có: display title, mô tả, semantic taxonomy và diễn giải ngữ cảnh dùng retrieval. Context là text có nghĩa cụ thể, không JSON bag. Chưa enrich thì không có row. Directory summary nằm trong README file, không row file_metadata của directory. Không timestamps/version/status riêng.

### processing

```text
file_id    uuid PK FK files ON DELETE CASCADE
stage      text NOT NULL  -- pending | parsed | enriched | ready
error_code text NULL
```

Chỉ source blob được hỗ trợ mới có row. Stage là last SQL-committed checkpoint để retry bỏ qua parse/enrich đã xong và API báo tiến độ; Temporal history không commit atomically với artifact SQL. error_code báo lỗi hiện tại, không error history. Không running/failed status thứ hai, attempt/generation/owner/timestamps. Unsupported blob có trạng thái API suy từ media type/capability, không row not_supported riêng. Scope tắt indexing dừng ở enriched, đây là hoàn thành theo policy.

### trash_entries

```text
id                 uuid PK
node_id            uuid UNIQUE FK nodes ON DELETE CASCADE
original_parent_id uuid NULL
trashed_by         text NOT NULL
trashed_at         timestamptz NOT NULL
```

Một occurrence cho root bị detach; original parent là restore hint, không FK cascade. Typed actor key và time phục vụ trash UI. Restore/purge xóa row. Name nằm ở nodes; không original_name, status/purging hoặc duplicate storage_id.

### uploads

```text
id               uuid PK
storage_id         uuid FK storages ON DELETE CASCADE
actor            text NULL
root_id          uuid NULL
parent_id        uuid NULL
name             text NULL
target_node_id   uuid NULL
expected_version bigint NULL
object_key       text NOT NULL
size_bytes       bigint NOT NULL
media_type       text NOT NULL
checksum         text NOT NULL
multipart_id     text NULL
source_file_id   uuid NULL
source_version   bigint NULL
result           bytea NULL
expires_at       timestamptz NOT NULL
```

Các field chia theo dữ liệu thật của transfer, không nhân state:

- id/object_key/size/media/checksum/expiry: cấp URL, verify bytes và GC reference. multipart_id chỉ có nếu source upload dùng native multipart.
- actor/root: ràng buộc upload của user/Leta và mount; không phải service credential.
- parent/name: đích tạo mới; target_node_id/expected_version: đích replace đã chọn. Không dùng FK target vì completed receipt vẫn phải đọc được sau khi file đích bị xóa.
- source_file_id/source_version: chỉ blob artifact handles, bảo đảm commit đúng pipeline/source version; actor/đích user không cần cho variant này.
- result: small CompleteUpload publication response để retry không publish hai lần. Không có completed_node_id/state/completed_at cùng mô tả lại result.

result NULL + chưa expiry là transfer mở. Abort xóa row; expire xóa open row. Complete ghi result và đổi expires_at sang thời hạn giữ receipt; artifact commit consume bằng DELETE handles cùng transaction insert files. Completed receipt hết hạn được dọn, không xóa file đã publish. Không preparing/transferring/completing/aborting/failed states hoặc transfer evidence journal.

Các nullable fields phản ánh user create/user replace/artifact transfer khác nhau; không dồn chúng vào nodes và không thêm bảng/framework cho mỗi variant.

### idempotency_keys

Giống cấu trúc kỹ thuật của Platform, ở database LetFS riêng. Không shared database/service/Redis receipt.

## 5. Ngoài hai database

Leta root resource giữ workspace_id/storage_id trong letas, executable profile chung trong agents. Owner/operator canonical graph; không dùng created_by_user_id làm current owner. [Schema Leta riêng](../261111-2010-leta-rewrite/schema.md) đã chốt lại 11 bảng, tách root/executable và agent/user deliveries, dùng receipt sáu fields giống core; message/HITL recipient IDs là event facts, không quyền hiện tại. Quota/visibility/membership vẫn thuộc core, không thêm mirror trong Leta. Concrete API/transport, multiple storage và physical cleanup integration của Leta hoãn.

Computer tương lai giữ computers.id/workspace_id; manager/operator ở graph. Chưa migrate placeholder tables hoặc runtime. Computer file IO giữ actor của invocation.

Ingest không SQL/jobs database; source version/stage tại LetFS và native Temporal retries. Qdrant là derived index, không liveness/permission authority. SpiceDB cần backup; không rebuild đầy đủ grants từ SQL.

## 6. Contract và validation

[API contract](api-contract.md) định nghĩa field messages, pagination, HTTP bindings và error contract. Source-of-truth/visibility graph schema ở [workspace resources](workspace-service-redesign.md). Không còn phương án PostgreSQL-only hoặc mapping authority song song.

Không migration/DB change, không validate lại Zed theo yêu cầu. Proto/Envoy/queries chưa được implementation hoặc benchmark; schema/query docs là design, không số đo.
