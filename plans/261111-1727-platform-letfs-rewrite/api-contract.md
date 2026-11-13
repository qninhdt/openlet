# API Platform và LetFS: gRPC + HTTP JSON

Ngày 2026-11-12. Contract đã được chấp thuận qua trao đổi; đã có implementation/generated proto và local gateway E2E. Architecture đã chốt ở [workspace resources](workspace-service-redesign.md); API/transport Leta tiếp tục hoãn. Không phục hồi API archived hoặc thêm compatibility aliases.

## 1. URL, routing và transport

Chọn một dạng URL canonical cho workspace resources:

- Platform: /v1/me, /v1/workspaces/{workspace_id}, members/invitations.
- LetFS: /v1/workspaces/{workspace_id}/storages/{storage_id}/...
- Quota LetFS: /v1/workspaces/{workspace_id}/storage-quota.
- Agent/Computer có thể theo cùng hierarchy khi owning API được thiết kế; chưa chốt route Leta lúc này.

Workspace ID cần trong collection để chỉ tenant; trong item endpoint, UUID resource đã unique nên không bắt buộc về kỹ thuật. Bản đề xuất vẫn giữ workspace_id nhất quán để FE/query/log có tenant context. Service đối chiếu actual SQL workspace_id trong cùng resource query, không gọi Platform để xác minh parent và không coi URL là authorization.

Envoy dùng google.api.http annotations và public descriptor chung. Sau transcoding, native route theo /openlet.platform.v1.PlatformService/ hoặc /openlet.letfs.v1.LetFSService/ đến đúng upstream. Prefix /workspaces không đồng nghĩa route qua Platform. Không router middleware/resource proxy hoặc regex dispatcher tự viết. Giữ match_incoming_request_route=false với transcoder ở HTTP filter cấp listener.

Public API chỉ hai protobuf services PlatformService và LetFSService. Internal API tách PlatformInternalService/LetFSInternalService, không HTTP annotation, không public route. auto_mapping=false; services/route allowlist không gồm internal services. Standard grpc.health.v1 chỉ dùng ở internal health boundary.

Native gRPC clients gọi trực tiếp upstream. Platform/LetFS không Gin, grpc-gateway hoặc app HTTP server. Native rich errors/HttpBody dùng cùng handlers, không viết REST handlers riêng.

## 2. Wire schema chung

| Message/field | Contract |
|---|---|
| IDs | UUID string; không owner-derived/deterministic ID |
| ActorRef | oneof user_id hoặc agent_id; target grant/internal provisioning, không caller identity do Internet tự khai |
| StorageOwnership | oneof user_id/agent_id/workspace_id; owner summary đọc từ graph, không SQL column |
| NodeLocator | oneof node_id/path; root_node_id và cwd_node_id khi cần mount/path resolution |
| Node | id, storage_id, parent_id, name, kind, timestamps, readonly; file header khi là file |
| FileHeader | type TEXT/BLOB, version, size_bytes, media_type, metadata/processing projection cần thật; không bytes content trong listing |
| Storage | id, workspace_id, name, visibility, root_node_id, allow_blob_files, allow_indexing, capabilities |
| StorageCapabilities | read, write, manage_access; response projection cho API MVP, không SQL columns |
| WorkspaceStorage | workspace_id, quota_bytes, used_bytes |
| StorageVisibility | UNSPECIFIED, PRIVATE, PUBLIC; wire names STORAGE_VISIBILITY_* |
| StorageRole | OWNER, EDITOR, VIEWER; OWNER chỉ trả/read hoặc ownership lifecycle, không SetStorageAccess |
| Lists | repeated resource field + next_page_token; page_size/page_token request, không total/count bắt buộc |
| Mutation | request_id cho allocate/append/copy và các multi-store retry cần giữ effect; expected_version chỉ cho content precondition |

Metadata update dùng proto3 optional fields có presence; omitted nghĩa giữ nguyên. Không thêm generic JSON Patch/field-mask engine cho vài fields hiện có. Pagination cursor opaque, keyset/native graph cursor; có thể short/empty page mà còn next_page_token sau authorization/filtering.

NodeLocator giữ native ID/path/root/cwd semantics để Leta gRPC không Stat trước rồi convert sang ID. HTTP item paths bind target.node_id/parent.node_id; FE dùng IDs. BatchStat POST nhận path locators khi JSON client cần resolve path. Không tạo HTTP alias cho mọi biến thể locator.

ReadTree/ReadText/MutateText/search giữ các options nghiệp vụ đã chốt: traversal bounds/readonly, byte/line/head/tail/metrics, patch/append/truncate, literal and semantic search. Operation-specific protobuf oneof cho mutations; không opaque JSON command payload.

Không actor field để caller public chọn subject. Envoy verify JWT/strip trusted identity headers; service dùng verified user. Private gRPC caller bind agent context. Request chỉ mang ActorRef khi đó là target của grant hoặc trusted provisioning.

### Resource messages

Các field dưới đây là protobuf fields dự kiến, không HTTP DTO hay SQL mirrors. Enum có giá trị UNSPECIFIED=0; Timestamp dùng google.protobuf.Timestamp. Field profile optional bị omitted nghĩa giữ nguyên; avatar_url chuỗi rỗng nghĩa xóa avatar.

| Message | Fields |
|---|---|
| User | id, display_name, optional avatar_url; không expose clerk_subject |
| Workspace | id, name, state, created_at, optional role; role là projection OWNER/MEMBER của caller human, omitted cho internal system response, không SQL column |
| WorkspaceMember | user: User, role: WorkspaceRole |
| Invitation | id, workspace_id, email, expires_at, optional accepted_by_user_id; không token_hash/plaintext token |
| CreateInvitationResponse | invitation, optional token; token chỉ lần tạo đầu |
| ActorRef | oneof user_id:string / agent_id:string |
| StorageOwnership | oneof user_id:string / agent_id:string / workspace_id:string; agent nghĩa agent và current agent owner, workspace nghĩa current workspace owner userset |
| StorageAccess | ownership: StorageOwnership, repeated grants: AccessGrant, visibility; public viewer inheritance là projection của visibility |
| AccessGrant | actor: ActorRef, role: EDITOR/VIEWER; chỉ direct grants |
| NodeLocator | oneof node_id:string / path:string; optional root_node_id, cwd_node_id; mặc định storage root |
| Node | id, storage_id, optional parent_id, name, kind:DIRECTORY/FILE, created_at, updated_at, readonly, optional file:FileHeader |
| FileHeader | type:TEXT/BLOB, version:int64, size_bytes:int64, media_type, optional metadata:FileMetadata, optional processing:ProcessingSummary |
| FileMetadata | optional title, description, semantic_type, context |
| ProcessingSummary | stage và error_code từ processing; unsupported blob suy từ media type/policy, không extra SQL state |
| ReadTextResponse | content:string, version:int64 và selection/metrics được yêu cầu |
| TrashEntry | id, node:Node, optional original_parent_id, trashed_by:ActorRef, trashed_at |
| Upload | id, expires_at, optional transfer descriptor hoặc completed Node; không expose object_key làm public identity |
| SignedDownload | url, expires_at |
| TextDownload | filename, media_type, content:string |
| GetDownloadResponse | oneof blob:SignedDownload / text:TextDownload |

Storage và WorkspaceStorage fields nằm ở bảng wire schema bên trên. role/capabilities là response projection; assigned relationships chi tiết chỉ đọc ở member/access screen. Workspace list derive role bằng bulk permission check; FE phân loại storage của mình bằng capabilities.manage_access, không owner lookup riêng từng card.

### Command payloads và retry

- CreateNode: parent locator, name, oneof directory:{} / text:{content,media_type}, request_id. Không nhận blob bytes ở đây.
- MutateText: target locator, oneof replace/append/patch/truncate, optional expected_version, request_id. Patch dùng typed edits đã chốt; không arbitrary JSON commands.
- CreateUpload: oneof create:{parent,name} / replace:{target,expected_version}, size_bytes/media_type/checksum, request_id. Response giữ native signed transfer descriptor cho single PUT hoặc multipart.
- Move/Copy: source locator, destination_storage_id, destination parent/name, request_id; destination phải cùng workspace.
- BatchStatResponse: results theo thứ tự input; mỗi item oneof node hoặc google.rpc.Status. Không fail toàn batch vì một path thiếu.
- List responses dùng tên resource cụ thể: workspaces/members/invitations/storages/nodes/entries/hits cùng next_page_token. Không total count mặc định.

request_id là UUID command identity, chỉ bắt buộc khi allocate/append/copy hoặc durable multi-store command cần replay. SQL receipt nằm tại database owning service, key (caller,method,request_id), hash input và small response commit cùng mutation. Cùng key khác payload trả conflict. Không thêm request_id cho read hoặc native desired-state setters chỉ để đồng bộ hình thức.

Onboard dùng unique Clerk subject; upload complete dùng upload_id; processing dùng file_id/version/stage; restore/purge dùng trash occurrence ID. Các identity này thay request_id riêng khi đủ. Pure role/grant/revoke dùng native SpiceDB set/delete; không SQL receipt giả lập graph transaction hoặc global exactly-once. Owner transfer dùng atomic graph batch/preconditions và trả success nếu target đã là current owner.

## 3. PlatformService public

W là /v1/workspaces/{workspace_id}. POST/PATCH body "*" trừ khi chỉ rõ. GET/DELETE fields còn lại đi qua query.

| RPC | HTTP | Input chính | Output |
|---|---|---|---|
| Onboard | POST /v1/me:onboard | Verified Clerk identity; không user/workspace ID tự khai | User |
| GetMe | GET /v1/me | Verified user | User |
| UpdateMe | PATCH /v1/me | optional display_name/avatar_url | User |
| ListWorkspaces | GET /v1/workspaces | page_size/page_token | workspaces, next_page_token |
| GetWorkspace | GET W | workspace_id | Workspace |
| UpdateWorkspace | PATCH W | optional name | Workspace |
| DeleteWorkspace | DELETE W | workspace_id | Workspace với lifecycle deleting; row không còn sau cleanup core |
| TransferWorkspaceOwnership | POST W:transferOwnership | new_owner_user_id đang là member | WorkspaceMember của owner mới |
| ListMembers | GET W/members | pagination | members gồm user profile và role |
| AddMember | POST W/members | user_id, request_id; role luôn member | WorkspaceMember |
| RemoveMember | DELETE W/members/{user_id} | Target human member; owner thực hiện hoặc member tự rời; không remove owner; chỉ xóa membership | Empty |
| CreateInvitation | POST W/invitations | email, request_id; không role selector | Invitation + optional first-response token |
| ListInvitations | GET W/invitations | pagination | invitations, next_page_token |
| RevokeInvitation | DELETE W/invitations/{invitation_id} | IDs | Empty |
| AcceptInvitation | POST /v1/invitations:accept | token; workspace được resolve từ token | WorkspaceMember |

Owner transfer là native graph batch, owner cũ thành member; không update SQL owner mirror. Add/remove/accept membership không trả storage ID. Client discover resources ở LetFS.

RemoveMember không liệt kê resource, sửa workspace.agent hoặc stop/cleanup agent. Agent độc lập human owner; membership gate thu hồi quyền human, không thu hồi quyền agent. Rejoin chỉ tác động human grants còn giữ. Quan hệ agent.workspace/workspace.agent được Leta ghi/dọn trong cùng native batch theo agent lifecycle; không có bước đăng ký riêng.

Onboard chỉ system-create default workspace khi insert user mới; retry user cũ không tạo workspace mới. CreateWorkspace không public ở MVP. Storage provisioning có thể tiếp tục theo existing workspace lifecycle; không thêm initial workspace/personal storage progress fields vào user response.

Invitation giữ accepted_by/expiry/hash và giới hạn đã chốt: consumed token không tự regrant membership. Plaintext token chỉ trả first response, không cất token vào receipt; nếu mất response cần revoke/create invitation khác. Không email-send integration mới.

## 4. PlatformInternalService: private, không HTTP

| RPC | Input/output chính |
|---|---|
| CreateWorkspace | owner_user_id, name, request_id; system provisioning, trả Workspace |
| BatchGetUsers | user_ids; một SQL batch profiles, không list global user public |
| CheckWorkspaceActive | workspace_id; Empty nếu tồn tại và active, NOT_FOUND nếu không có, FAILED_PRECONDITION nếu chưa active/đang deleting; dùng chung cho resource services |

Quyết định 2026-11-12: bỏ RegisterAgent/UnregisterAgent và AgentRegistrationRequest khỏi proto/handlers/generated consumers, không compatibility wrapper. Leta kiểm quyền tại admission và ghi/dọn agent.workspace/workspace.agent cùng owner/operators bằng native SpiceDB batch; đổi registered_agent thành agent. Core source/generated đã bỏ API cũ và có CheckWorkspaceActive; Leta implementation hoãn. RPC check không cấp quyền tạo resource hoặc khóa workspace; owning service kiểm permission bằng native SpiceDB. [Boundary Leta](../261111-2010-leta-rewrite/boundaries.md#71-removemember-và-agent-độc-lập) đã chốt bỏ policy thu hồi quyền agent khi owner rời workspace, không còn proposal chờ rejoin decision.

Không ResolvePersonalStorage, ListStorages hoặc SetStorageAccess ở Platform. Không SetMemberRole: chỉ owner/member, transfer-owner là action riêng. Không public lifecycle/admission RPC qua native gRPC path của Envoy.

## 5. LetFSService: storage/quota/access public

S là /v1/workspaces/{workspace_id}/storages/{storage_id}.

| RPC | HTTP | Input chính | Output |
|---|---|---|---|
| GetWorkspaceStorage | GET /v1/workspaces/{workspace_id}/storage-quota | workspace_id; workspace.view | WorkspaceStorage |
| UpdateStorageQuota | PATCH /v1/workspaces/{workspace_id}/storage-quota | quota_bytes; workspace.manage | WorkspaceStorage |
| ListStorages | GET /v1/workspaces/{workspace_id}/storages | page_size/page_token, optional visibility, owned_only | storages, next_page_token |
| GetStorage | GET S | IDs; storage.read | Storage |
| UpdateStorage | PATCH S | name không rỗng; storage.manage_access; chỉ rename, không nhận visibility/request_id | Storage |
| ListStorageAccess | GET S/access | IDs; storage.manage_access | owner summary, direct viewer/editor grants, visibility/public inheritance |
| SetStorageAccess | POST S:setAccess | target ActorRef, EDITOR/VIEWER | AccessGrant |
| RevokeStorageAccess | POST S:revokeAccess | target ActorRef | Empty |

Public defaults viewer for human owner/member and agents thuộc W qua workspace.agent. Explicit editor can grant write. owned_only uses effective ownership/manage_access permission; private/public filter SQL applied with actual workspace. Lists batch capabilities, không ReadRelationships owner riêng từng storage. Owner/grants detail chỉ khi access screen cần; không enumerate tất cả members cho public access UI.

Đã chốt cắt API đổi visibility. Private/public được chọn khi provisioning và cố định sau create. Giữ field/enum/filter visibility và public_workspace graph relation được ghi bởi provisioning; cấp/thu hồi direct editor/viewer vẫn giữ. UpdateStorageRequest chỉ còn workspace_id/storage_id/name; implementation phải xóa visibility/request_id và CEL tương ứng trong message này, đồng bộ generated clients/descriptor/callers và bỏ tests của tính năng đã cắt. Không giữ deprecated branch hoặc runtime wrapper.

Rename chỉ permission check + một UPDATE RETURNING, không request_id/receipt/Temporal. CreateDirectories là mkdir-p: chỉ tạo thư mục còn thiếu, retry trả directory hiện tại; không request_id/receipt. Xóa workflow/activity đổi visibility, không thay bằng cơ chế serialization khác.

CreateStorage/DeleteStorage là lifecycle nội bộ ở MVP. Không expose public create/delete hoặc API switch storage của agent trước feature đó.

## 6. LetFSService: nodes/content/search/trash public

HTTP fields {target.node_id}/{parent.node_id} là nested protobuf field bindings, không path trong filesystem.

| RPC | HTTP | Input/output và permission |
|---|---|---|
| Stat | GET S/nodes/{target.node_id} | NodeLocator → Node; read |
| BatchStat | POST S/nodes:batchStat | repeated locators → ordered per-item results; batch graph + SQL |
| ListNodes | GET S/nodes/{parent.node_id}/children | parent locator, pagination → nodes/page; read |
| ReadTree | POST S/nodes:readTree | root locator, traversal options → tree entries/truncation; read |
| CreateNode | POST S/nodes | parent/name, directory hoặc inline text, request_id → Node; write |
| CreateDirectories | POST S/nodes:createDirectories | base/path → final directory Node; write |
| MoveNode | POST S/nodes:move | source, destination_storage_id/parent/name, request_id → Node; write hai endpoints |
| CopyNode | POST S/nodes:copy | source/destination, request_id → copied root Node; read source/write destination |
| ReadText | GET S/nodes/{target.node_id}/text | selector/read options → text + version/metrics cần dùng; read |
| MutateText | PATCH S/nodes/{target.node_id}/text | replace/append/patch/truncate oneof, expected_version, request_id → Node; write |
| ReadImage | GET S/nodes/{target.node_id}/image | image options → google.api.HttpBody; read |
| GetDownload | GET S/nodes/{target.node_id}:download | → signed URL cho blob hoặc inline text download payload; read |
| DownloadArchive | POST S/nodes:downloadArchive | selected locators → stream google.api.HttpBody ZIP; read |
| SearchFiles | POST S/files:search | root/query/page → file hits; read |
| TextSearch | POST S/files:textSearch | root/query/file-or-lines options/page → text hits; read |
| SemanticSearch | POST S/files:semanticSearch | root/query/search options → validated semantic hits; read |
| TrashNode | POST S/nodes/{target.node_id}:trash | locator, request_id → TrashEntry; write |
| ListTrash | GET S/trash | pagination → trash entries; read |
| RestoreTrash | POST S/trash/{trash_id}:restore | optional destination parent/name → Node; write |
| PurgeTrash | DELETE S/trash/{trash_id} | occurrence ID → Empty; write |

Cross-storage move/copy chỉ cùng workspace; resolve/authorize cả source/destination trong batch. Quota chung nên move không đổi usage; copy tăng logical bytes. Không cross-workspace transfer feature hoặc object-copy saga.

Read/list projection không chứa text bytes. Text create/upload luôn string vào PostgreSQL. Blob publication chỉ qua upload API. Artifacts readonly; copy-out trở thành ordinary content, giữ contract đã chốt.

GetDownload trả protobuf oneof: blob SignedDownload(url, expires_at) hoặc TextDownload(filename, media_type, content). HTTP JSON text là UTF-8 string, không tạo signed S3 text object. FE có thể tạo download từ text response. DownloadArchive và ReadImage là raw HttpBody exceptions, không success JSON envelope.

## 7. LetFSService: blob transfer public

| RPC | HTTP | Input/output |
|---|---|---|
| CreateUpload | POST S/uploads | create-parent/name hoặc replace-target, blob size/media/checksum, expected_version, request_id → upload ID/signed transfer descriptor |
| GetUpload | GET S/uploads/{upload_id} | owner/expiry/result state projection; không provider HEAD |
| SignParts | POST S/uploads/{upload_id}:signParts | parts:{part_number,checksum CRC32C base64} batch → signed URLs + signed headers |
| CompleteUpload | POST S/uploads/{upload_id}:complete | multipart parts/checksums → published Node; replay bằng upload receipt |
| AbortUpload | DELETE S/uploads/{upload_id} | abort → Empty |

All require storage.write; target/actor/root bound khi tạo upload và rechecked khi publish. Source user uploads verify native S3 completion/metadata trước write transaction. Quota debit tại publication, không reserve lúc ký URL.

SignParts yêu cầu checksum CRC32C từng part (base64 của 4 byte), part numbers hợp lệ và không trùng. Caller gửi đúng URL/headers SDK trả về; CompleteUpload vẫn gửi ETag/checksum từng part và kiểm whole-object checksum. Không thêm checksum middleware hoặc bỏ integrity checks để chiều provider.

Không binary/base64 upload body qua application JSON. Signed S3 request dùng native HTTP riêng. Text dùng CreateNode/MutateText; không text-on-S3 fallback.

## 8. LetFSInternalService: private, không HTTP

| RPC | Contract |
|---|---|
| ProvisionWorkspaceStorage | workspace_id/quota; idempotent budget provisioning |
| CreateStorage | workspace_id, ordinary storage_id được cấp một lần, owner, visibility/name/policy → Storage; native IDs giữ trong provisioning input/receipt |
| DeleteStorage | IDs; lifecycle cleanup, graph+local SQL, không public standalone delete |
| DeleteWorkspaceStorage | Current internal RPC: workspace_id; graph/storage/budget cleanup. Workspace workflow sẽ gọi owning activity theo workspace-cleanup.md, rà callers rồi xóa RPC nếu không còn dùng; không forwarding wrapper |
| GetProcessingInput | file_id/version → source+artifact input cần stage hiện tại; LetFS resolve actual storage/workspace |
| PrepareArtifactUploads | source/version + batch outputs → handles/signed URLs |
| CommitParse | source/version + typed manifest/handles → stage outcome |
| CommitEnrichment | source/version + batch node_id, optional name/text_content/metadata → stage outcome; directory dùng ID/name, không metadata. Đổi tên và sửa Markdown được commit nguyên tử; README/source giữ tên |
| CompleteIndex | source/version → stage outcome |
| FailProcessing | source/version/error_code → stage outcome |

[Workspace cleanup mới đã chốt](workspace-cleanup.md) là Temporal shared activity contract, không RPC bổ sung. Cần sửa backend hiện có; public DeleteWorkspace vẫn trả admitted lifecycle, storage/Platform SQL không đợi Leta còn workflow vẫn observe cleanup future.

Processing giữ source version/stage guards, native retries và set-based SQL. Không expose internal worker API qua HTTP hoặc dùng caller-chosen public actor để gọi processing. Maintenance native activities/schedules không phải public REST resources.

## 9. Proto annotation minh họa

Đây là excerpt contract, chưa là file proto generate/compile:

~~~proto
syntax = "proto3";
package openlet.letfs.v1;

import "google/api/annotations.proto";

enum StorageVisibility {
  STORAGE_VISIBILITY_UNSPECIFIED = 0;
  STORAGE_VISIBILITY_PRIVATE = 1;
  STORAGE_VISIBILITY_PUBLIC = 2;
}

message GetStorageRequest {
  string workspace_id = 1;
  string storage_id = 2;
}

message UpdateStorageRequest {
  string workspace_id = 1;
  string storage_id = 2;
  optional string name = 3;
  optional StorageVisibility visibility = 4;
  string request_id = 5;
}

message StorageCapabilities {
  bool read = 1;
  bool write = 2;
  bool manage_access = 3;
}

message Storage {
  string id = 1;
  string workspace_id = 2;
  string name = 3;
  StorageVisibility visibility = 4;
  string root_node_id = 5;
  bool allow_blob_files = 6;
  bool allow_indexing = 7;
  StorageCapabilities capabilities = 8;
}

service LetFSService {
  rpc GetStorage(GetStorageRequest) returns (Storage) {
    option (google.api.http) = {
      get: "/v1/workspaces/{workspace_id}/storages/{storage_id}"
    };
  }
  rpc UpdateStorage(UpdateStorageRequest) returns (Storage) {
    option (google.api.http) = {
      patch: "/v1/workspaces/{workspace_id}/storages/{storage_id}"
      body: "*"
    };
  }
}
~~~

Các public methods còn lại theo matrix, internal service không có annotations. Không thêm một HTTP DTO/controller khác; responses từ generated protobuf.

## 10. JSON, errors và status

Success là ProtoJSON trực tiếp: field lowerCamelCase; int64/uint64 decimal string; bytes base64; enum symbolic name; unset/default có thể omitted. List resource field + nextPageToken; không success/data/error envelope.

~~~http
GET /v1/workspaces/W/storage-quota

HTTP/1.1 200 OK
Content-Type: application/json

{"workspaceId":"W","quotaBytes":"1073741824","usedBytes":"4096"}
~~~

~~~http
PATCH /v1/workspaces/W/storages/S
Content-Type: application/json

{"name":"Tài liệu nhóm"}
~~~

Unary success thường HTTP 200, Empty thành {}; không mapper để ép 201/202/204. DeleteWorkspace trả admitted lifecycle, physical cleanup không được suy từ HTTP 200.

convert_grpc_status=true: application error là google.rpc.Status JSON trực tiếp, code/message/details, có ErrorInfo.reason khi cần. Không RFC9457, outer error envelope hoặc Lua/Wasm mapper. QUOTA_EXCEEDED dùng RESOURCE_EXHAUSTED/HTTP429; version conflict dùng ABORTED/409. Native Envoy local replies có thể khác body, signed S3 theo S3; đọc Content-Type/status trước rich-error decode.

ZIP là raw application/zip stream qua HttpBody, image là image/*; lỗi sau stream bắt đầu không đổi lại thành JSON. [HTTP details](http-json.md) giữ limits và smoke criteria.

## 11. Query/verification và phần hoãn

Không thêm storage discovery/grants proxy ở Platform. Một file/list operation kiểm storage một lần; batch storage/action checks cho batch/cross-storage, không per-node profile/permission loops. Mutation trả Node từ RETURNING/receipt, không Stat sau mutation.

List resource visibility/capabilities không đòi đọc owner relationship N+1; direct owner/grants chi tiết đọc theo resource khi cần. Không total count bắt buộc, arbitrary filter DSL hoặc unbounded refill để lấp page sau auth filter.

Đã generate Buf/clients/descriptor và chạy local Envoy/API E2E trên databases test mới; không sửa database cũ hoặc dotenv thật. Không validate lại Zed theo yêu cầu. Theo quyết định sau [audit](../reports/feature-parity-261112-platform-letfs-rewrite.md), chỉ bổ sung hybrid BM25 + dense/RRF phía implementation SemanticSearch; không đổi wire schema, không thêm search filters/sort, cross-storage restore hoặc mkdir/empty-trash options. Executable proto là wire authority. API/transport Leta, agent multiple storage/switch, Computer runtime và user-created extra storages đều hoãn.

## Nguồn

- [Envoy routing sau transcoding và HttpBody](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/grpc_json_transcoder_filter).
- [Envoy native transcoder options](https://www.envoyproxy.io/docs/envoy/latest/api-v3/extensions/filters/http/grpc_json_transcoder/v3/transcoder.proto).
- [ProtoJSON](https://protobuf.dev/programming-guides/json/).
- [HTTP annotations](https://docs.cloud.google.com/endpoints/docs/grpc/transcoding).
