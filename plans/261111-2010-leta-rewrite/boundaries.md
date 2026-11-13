# Leta: rà soát API và boundary liên service

Snapshot 2026-11-12, đã cập nhật theo current core handler/generated source và [plan core](../261111-1727-platform-letfs-rewrite/plan.md), [resource/roles](../261111-1727-platform-letfs-rewrite/workspace-service-redesign.md), [API design](../261111-1727-platform-letfs-rewrite/api-contract.md). Core đang implementation song song; tiến độ checks/deploy do plan core sở hữu, không chạy lại trong lượt này. Đây là review tĩnh, không chứng minh Leta integration chạy qua.

Leta [schema 11 bảng](schema.md), [DDL](schema.sql), [Temporal](temporal.md). HTTP JSON/SSE, operator access, [workspace cleanup](../261111-1727-platform-letfs-rewrite/workspace-cleanup.md) và retention MVP không auto-purge đã chốt; complete DTO/errors cần cụ thể hóa, transfer hoãn. Không sửa contracts, handlers, config/infra của core trong review này.

## 1. Trạng thái thực tế

- Active contracts có PlatformService/PlatformInternalService và LetFSService/LetFSInternalService; generated Go clients và một phần new handlers/migrations đã có.
- Không còn apps/leta ở active tree. Mục tiến độ implementation mới trong plan core ghi đã archive toàn bộ Leta source/migrations/native dependencies vào archive/2026-11-11/apps/leta, đối chiếu hash 60 files. Dùng báo cáo đó làm trạng thái phối hợp; lượt này không tự chạy lại hash audit hoặc restore archive.
- packages/sdk-python và generated Python gRPC output đã có. buf.gen.yaml vẫn generate Go/Go gRPC; Make generate dùng descriptor + grpc_tools.protoc để generate Python. Chưa có new Leta handler/consumer để kiểm một request end-to-end.
- Sáu workflows/22 activities/ba queues là approved Leta design, chưa worker implementation; thêm DeleteWorkspaceAgents theo cleanup contract, public streaming theo streaming.md.

## 2. Ownership và dependency matrix

| Hướng | API/capability | Actor và authority | Trạng thái |
|---|---|---|---|
| Client/Envoy → Leta | HTTP JSON/SSE; agent/box/messages/history/HITL/schedules/events/access/control | Trusted human; agent operations kiểm current agent rights, addressed HITL kiểm recipient/current workspace participation | Transport/events/operator access đã chốt; complete DTO/errors còn review, transfer hoãn |
| Leta → PlatformInternalService | Generic CheckWorkspaceActive, BatchGetUsers | Platform sở hữu workspace state/user data; Leta tự ghi quan hệ agent thuộc workspace | Core handler/generated đã có CheckWorkspaceActive và bỏ RegisterAgent/UnregisterAgent; consumer Leta chưa viết |
| Leta → PlatformService | Workspace/member/profile operations thực sự cần | Human context khi method yêu cầu human | Không phải runtime permission proxy; map concrete callers khi implementation, không thêm agent call vào human-only RPC |
| Leta → LetFSInternalService | CreateStorage cho provisioning | Private provisioning, không public body actor | Root delete giữ teardown/archive đã chốt; physical storage purge/transfer ngoài MVP, không tự thêm DeleteStorage |
| Leta → LetFSService | GetStorage/ListStorages, native files/search/trash/uploads; SetStorageAccess/RevokeStorageAccess | IO là root agent; grant là accepting human | Native contract/handlers và generated Python stubs hiện có; chưa consumer Leta |
| Leta → SpiceDB | Agent owner/operator, hai chiều agent.workspace/workspace.agent và native checks/bulk | Leta ghi agent lifecycle; Platform workspace/membership, LetFS storage relations | Đã chốt; agent độc lập human owner, RemoveMember chỉ thu hồi human membership |
| Platform → Leta | Shared DeleteWorkspaceAgents activity trên bridge | Không permission/readiness/stop hot-path dependency | JSON/queue contract đã chốt, chưa backend implementation; không gRPC listener mới |
| Leta → Temporal | Own workflows/activities/native schedules | Native orchestration; một shared workspace cleanup entrypoint | Design 6/22/3, chưa implementation |
| Leta → Redis/PostgreSQL | Events/cache và own domain/checkpoints | Không cross-service SQL | Dependencies nội bộ Leta |
| Leta → S3 | Signed URLs từ LetFS | Quyền/hạn signed transfer theo LetFS/provider | Không permanent S3 credentials trong Leta |
| Leta → model provider | LangChain/LangGraph native model calls | Provider credential thuộc role worker | Theo models.leta/catalog/YAML, chưa runtime mới |
| Leta → ingest/Qdrant | File operations qua LetFS tự trigger processing/search | Ingest/Qdrant thuộc LetFS boundary | Không direct processing RPC/Qdrant/SQL từ Leta |
| Leta ↔ Computer | Future service | Computer IO giữ invocation actor | Design-only, chưa thêm client/API/runtime |

## 3. Wire actor và trust

[identity.go](../../packages/sdk-go/identity.go) hiện nhận đúng một metadata value x-openlet-user-id hoặc x-openlet-agent-id, parse UUID; thiếu/cả hai/multiple values là unauthenticated. Đây là actor identity, khác process credential. MVP private-network trust; mTLS native là bước production đã chốt, không service-token registry mới.

- UI/API vào Leta: human từ trusted ingress; model/public request không được tự chọn actor.
- Ask gửi explicit recipient_user_id tới bất kỳ human owner/member hiện tại cùng workspace. Incoming card/answer chỉ cần exact recipient và current workspace.participate, không agent.use hoặc quan hệ owner; quyền này không mở transcript/files của agent. Approval còn kiểm current storage.manage_access. Chi tiết tại [HITL permissions](hitl.md#9-ai-xem-trả-lời-cancel).
- Root và mọi Leti gọi LetFS IO với x-openlet-agent-id = root Leta ID, không child ID. Child box/mount restriction vẫn phải bind riêng trong locator.
- Accepted approval: worker gọi SetStorageAccess với x-openlet-user-id = authenticated accepting human lưu trong response; request.actor.agent_id là root nhận grant. Không gửi đồng thời human + agent metadata, không dùng root subject tự grant.
- Platform public workspace methods trong handler hiện yêu cầu human. Không tự dùng agent metadata gọi GetWorkspace/ListMembers để thay permission check; runtime authorization dùng native SpiceDB/LetFS.
- Core internal services không public HTTP annotations. MVP trusted network cho phép lifecycle calls; Leta HTTP routing/identity strip và actual Python gRPC metadata forwarding vẫn cần integration theo streaming.md.

## 4. Root provisioning và access

[Platform internal proto](../../packages/contracts/proto/openlet_api/platform/v1/internal.proto) và [handler](../../apps/platform/internal/platform/members.go) đã đổi theo quyết định 2026-11-12: bỏ RegisterAgent/UnregisterAgent và AgentRegistrationRequest, không compatibility wrapper; có CheckWorkspaceActive(workspace_id) nội bộ dùng chung cho các resource service. Current handler/generated source đã đối chiếu qua CodeGraph. RPC chỉ xác nhận workspace tồn tại/active, không nhận resource type/ID hoặc ghi resource relationships. Không tạo Register<Resource> theo từng service; consumer Leta đã dùng RPC và tự ghi owning relationships.

Thứ tự implementation đã duyệt:

1. Temporal nhận canonical create input; cấp root agent/storage/storage-root ordinary UUIDs một lần.
2. Leta transaction ghi letas(workspace_id,storage_id,state=provisioning) + root agents và admitted receipt.
3. Provision activity gọi generic Platform CheckWorkspaceActive(workspace_id). Quyền workspace.create_agent và việc cấp owner/operator được kiểm tại admission; quyền chạy của agent không phụ thuộc membership owner về sau.
4. Leta ghi agent.workspace@workspace:W và workspace.agent@agent:A trong cùng native WriteRelationships batch với agent.owner và operators đã được chấp nhận. W lấy từ canonical immutable workspace_id; không có RPC/bước/trạng thái đăng ký riêng. Box/Leti dùng root identity, không thêm workspace.agent riêng.
5. LetFS CreateStorage với workspace_id, storage_id, **root_node_id**, StorageOwnership.agent_id=root, visibility PRIVATE, name và allow_blob_files/allow_indexing policy.
6. Conditional activate; deleting/archived không được resurrect.

[LetFS internal proto](../../packages/contracts/proto/openlet_api/letfs/v1/internal.proto) hiện bắt root_node_id. ID đó giữ trong canonical Temporal provisioning input, không cần thêm root-node field vào SQL Leta. Storage response/GetStorage cung cấp root node cho mounts.

LetFS ghi owner@agent:A và owner@agent:A#owner; human owner theo userset, không SQL owner snapshot. Operator access/control và hai chiều workspace binding đã chốt; transfer ownership hoãn. Complete HTTP DTO/errors còn cần cụ thể hóa, không tạo SQL owner/creator/operator fields để tránh boundary này. SQL state check rồi graph write không phải distributed transaction; cả RegisterAgent cũ cũng không khóa được workspace qua hai bước. Không thêm lease/lock service để hứa atomicity chưa có.

Core plan ghi đã đổi relation registered_agent thành agent trong owning Zed và affected graph reader/writer/fixture/bootstrap. Tên mới chỉ biểu thị agent thuộc workspace, không thêm trạng thái active/registered/unregistered vào SQL hoặc Temporal. Consumer Leta phải dùng active proto/generated/graph contract đó; không làm lại core hoặc giữ hai RPC cũ chỉ để test/client không đỏ. Không đổi application schema hoặc thêm workflow/activity type vì thay boundary này. Khi xóa agent, Leta xóa cả hai chiều thuộc workspace trong cùng graph batch; workspace teardown cũng thu hồi workspace.agent. Không áp xóa này khi remove human member.

## 5. File operations, mounts và cache

[LetFS public proto](../../packages/contracts/proto/openlet_api/letfs/v1/letfs.proto) đã có NodeLocator(node_id/path, optional root_node_id/cwd_node_id), workspace_id/storage_id và native file/version/request_id contracts.

| Nhu cầu Leta/Mirage | Native LetFS API |
|---|---|
| Stat/cache admission | Stat, BatchStat, GetStorage khi mount metadata cần |
| List/tree | ListNodes, ReadTree |
| Text read/write | ReadText, CreateNode, MutateText |
| Directory/create/move/copy | CreateDirectories, CreateNode, MoveNode, CopyNode |
| Image/blob download | ReadImage, GetDownload, signed S3 HTTP |
| Filename/literal/semantic search | SearchFiles, TextSearch, SemanticSearch |
| Remove/restore | TrashNode, ListTrash, RestoreTrash; purge theo quyền/tool contract |
| Blob upload | CreateUpload, SignParts, CompleteUpload, AbortUpload/GetUpload |

Home mount dùng storage root cho root Leta, box.home_node_id cho Leti. Agent-facing paths dùng ~/... qua native Mirage tilde expansion. External mounts /mnt/<storage_id> được discover bằng ListStorages với root actor, gồm public/shared và private được cấp quyền trực tiếp/HITL; mỗi mount bind storage root và capabilities tương ứng. Không tạo external alias cho home storage_id để Leti không mở lại toàn home tree. Leta inject containment root cho mọi locator kể cả raw IDs, và cả source/destination của copy/move. Không để model bỏ root hoặc chọn binding chưa authorize để thoát box. Native LetFS [resolver](../../apps/letfs/internal/storage/paths.go) kiểm actual workspace/storage, live ancestry, mount containment và readonly artifacts.

Leta không tự query Qdrant/LetFS SQL, parse blob hoặc duplicate quota/version logic. Text nằm PostgreSQL; blob qua signed URLs, không binary/base64 request qua app JSON. Mọi file_*/exec_* qua Mirage dispatcher; gRPC chỉ trong adapter. Native Redis content/index cache dùng BOUNDED/default TTL 600 giây, cache hit không remote Stat/auth/version; custom WRITE hook invalidates. Request tới LetFS vẫn enforce quyền/containment/version/quota. Cached bytes có thể dùng tới expiry/unmount; không permission cache hoặc invalidation bus. Signed URLs đã phát hành giữ expiry semantics core, không hứa thu hồi bytes đã giao.

Một storage_id trong SQL chỉ là home binding, không cấm truy cập nhiều storage. Giữ native dynamic mounts: ListStorages/root capabilities → Mirage add_mount/unmount/set_mount_mode tại safe tool boundaries. Discovery result giữ trong runtime RAM; refresh lazily sau 30 giây hoặc HITL grant, không list lại trước mọi file operation. Mọi Leti dùng root actor nên chia sẻ external grants của root; home vẫn bị giới hạn theo box. HITL grant không đổi home storage_id. Chỉ tính năng đổi home binding còn hoãn; không phục hồi Platform personal resolver, /shared hoặc /users mapping và không thêm mount/grant table. Chi tiết tại [filesystem](filesystem.md#2-mount-và-identity).

## 6. HITL storage approval

hitl_requests giữ type/status ở columns, payload storage_id/role/reason, response accepting actor và outcome effect. Khi accepted:

Đề xuất input hitl_request chỉ rõ storage_id và recipient_user_id; requester chưa có read/manage_access không gọi được ListStorageAccess để auto-discover owner. Native graph admission kiểm scoped storage workspace và addressed human manage_access, không dùng Platform personal resolver hoặc giả human actor để đọc metadata private. Chi tiết tại [HITL](hitl.md#2-tools-và-người-nhận); không thêm core RPC hoặc schema mirror.

1. Kiểm root/requester liveness và addressed recipient/current human rights.
2. SetStorageAccess(workspace_id,storage_id,actor.agent_id=root,role EDITOR/VIEWER) với accepting-human metadata.
3. LetFS kiểm actual storage parent, human storage.manage_access và target workspace.eligible_actor; graph ACK xong Leta mới ghi granted outcome.
4. Lost rights/resource → skipped; transient → native retry. Delivery source_kind=hitl vào exact requester, không pause toàn agent. Runtime refresh native mounts sau outcome, không đổi home storage_id; không đợi mount ACK trước kết thúc HITL.

[SetStorageAccess handler](../../apps/letfs/internal/storage/access.go) dùng native graph set/delete và hiện **không có request_id field hoặc permanent grant receipt**. Không mô tả grant key như một API field đang có. Retry assignment idempotent, không globally exactly-once; concurrent revoke lúc effect còn pending chưa có final ordering. Cleanup Leta đợi effect settle, không đợi queued result delivery.

## 7. Cleanup và core independence

Core [DeleteWorkspace](../../apps/platform/internal/platform/provisioning.go) thu hồi workspace graph, dispatch owning LetFS/Leta cleanup activities song song, xóa Platform SQL sau storage ACK và tiếp tục chờ Leta future. Current RemoveMember handler đã chỉ xóa human workspace.member với owner guard, không còn agent-owner scan hoặc resource fanout; mục 7.1 là policy đã chốt và đã triển khai phía core.

Source hiện tại: public DeleteWorkspace ghi state=deleting rồi start native delete-workspace/{workspace_id}, trả sau admission. Workflow chạy RevokeWorkspaceAccess, dispatch DeleteWorkspaceStorage và DeleteWorkspaceAgents tới owning queues. Storage ACK cho phép DeleteWorkspaceRecord chạy trước khi Leta xong. LetFS xóa mọi storage trong workspace, gồm agent-owned storage; FK cascade dọn dữ liệu liên quan. S3 unreferenced objects và Qdrant invalid points được maintenance dọn theo policy sẵn có; ACK không hứa đã xóa vật lý mọi bytes/vector.

Leta cũng là resource thuộc workspace; agent độc lập human owner không giữ agent sống khi workspace bị xóa. [Workspace cleanup đã chốt](../261111-1727-platform-letfs-rewrite/workspace-cleanup.md): Platform revoke graph rồi dispatch DeleteWorkspaceStorage trên LetFS queue và DeleteWorkspaceAgents trên Leta bridge song song. Storage ACK → xóa Platform SQL; workflow vẫn observe Leta future. Backend đã triển khai đường này theo shared contract; không workspace polling hoặc cleanup workflow mới. Inventory Leta thành 6 workflows/22 activities/3 queues.

Leta xử lý permission denied/not found tại safe boundary; không retry permanent revoke như transient vô hạn. Resource core bị xóa khi Leta tắt không chặn storage/Platform SQL cleanup; Temporal workflow còn pending trên Leta activity là chủ ý. DeleteWorkspaceAgents đóng gates và dùng root/box cleanup functions inline, settle producers/writers/grants, dọn schedules/agent relations và archive. Home mất/quyền trash bị thu hồi là expected teardown outcome; không tạo lại resource hoặc retry grant mãi. Đường teardown/archive đã có implementation; physical purge toàn bộ SQL/history/checkpoints vẫn ngoài scope MVP.

User-requested Leta/box delete vẫn đóng admission, settle producers/HITL effects, stop writers, trash box homes khi còn quyền/tồn tại và archive local rows. Root delete xóa agent.workspace và workspace.agent trong cùng native graph batch, không UnregisterAgent RPC; box delete không sửa quan hệ root thuộc workspace. Không tự DeleteStorage chỉ vì root có storage_id; binding không exclusive ownership. Physical purge graph/storage và transfer ngoài MVP; teardown/archive bên trên đã đủ scope, không là decision chặn implementation. Workspace delete vẫn dọn mọi storage theo shared contract.

### 7.1 RemoveMember và agent độc lập

Đã chốt: agent thuộc workspace và là actor độc lập với human owner/creator. RemoveMember không dừng agent, không thu hồi quyền/grants của agent, không transfer/xóa agent và không gọi cleanup từng resource service. Không thêm cạnh user.owned_agent hoặc permission expression phụ thuộc membership của owner.

Zed giữ gate đơn giản, với relation được đổi tên:

```zed
// Trong definition workspace:
relation agent: agent
permission participate = owner + member
permission eligible_actor = participate + agent
```

RemoveMember/self-leave chỉ xác thực human, kiểm workspace/quyền manage nếu xóa người khác, bảo vệ workspace owner bằng native graph precondition, rồi xóa workspace.member@user:U. Xóa agent.owner scan/loop thu hồi quan hệ agent khỏi handler. Thêm resource service mới không thêm nhánh vào RemoveMember.

Human mất quyền trên storage/agent/computer theo workspace membership gate, kể cả direct grants còn giữ. Agent cùng workspace tiếp tục bằng identity và grants riêng; agent workspace khác vẫn bị chặn bởi workspace->eligible_actor. Rejoin chỉ phục hồi quyền human từ grants còn giữ, không start/resume/regrant agent vì agent chưa từng bị membership change tác động. Computer tiếp tục giữ invocation actor, không tự thành principal.

Agent/workspace lifecycle mới dọn quan hệ thuộc workspace; quyền human quản lý agent vẫn cần participation. Quyền administrative delete của workspace owner hiện có giữ nguyên; không tự mở thêm quyền use/manage/transfer private agent cho workspace owner. Core đã triển khai phần boundary của mình; lượt cập nhật Leta plan này không sửa active schema.zed hoặc RemoveMember runtime và không validate lại Zed.

## 8. Các điểm còn thiếu hoặc lệch

### 8.1 Box directory ID — home-first đã chốt

Người dùng đã duyệt [Box/Leti home-first](boxes.md#4-home-first-provisioning): Temporal nhận immutable input/stable IDs trước effects; provision_box gọi native CreateDirectories tại .boxes/<box_id> trong root home, lấy LetFS-generated node ID; prepare_box sau đó ghi active box/children/edges/finalized receipt atomically dưới root gate. Giữ home_node_id NOT NULL, bỏ SQL boxes.provisioning. Không nullable workaround, preallocated directory ID hoặc đổi core proto.

CreateDirectories nhận base locator/path và có thể trả directory hiện có; không dùng receipt identity hoặc node-ID input mà method này không có. Retry giữ nguyên stable path; Temporal lưu activity result. Box create Update COMPLETED/API resource ACK chỉ trả sau SQL commit; HTTP disconnect không cancel durable operation. Pending create thuộc Temporal, box list chưa thấy row trước commit. Crash gap có thể để lại directory rỗng; không thêm orphan ledger/sweeper hoặc distributed compensation. Chưa implementation/integration; không claim SQL/LetFS atomic.

### 8.2 Dedupe horizon của file effects

[Config mẫu core](../261111-1727-platform-letfs-rewrite/openlet.example.yaml) hiện idempotency_retention_seconds=86400 cho Platform/LetFS. [Receipt helper](../../packages/sdk-go/receipt.go) gắn expires_at, local mutation + response commit cùng transaction; migrations hai database có cùng sáu fields. Maintenance có cleanup receipt hết hạn.

Leta chạy liên tục nhiều năm không đòi mọi receipt sống vô hạn. Tuy nhiên nếu tool effect đã commit, chưa checkpoint rồi retry sau khi LetFS receipt bị GC, cùng key không còn bảo đảm dedupe append/copy. Receipt infinity trong DB Leta không kéo dài receipt LetFS.

Đã chốt: giữ finite receipt retention core; retry trong guarantee giữ nguyên request key/canonical payload. Khi recovery checkpoint có pending mutation đã quá guarantee, báo kết quả chưa xác định và không tự thực thi lại; timestamp của checkpoint cho conservative age, không dùng tuổi agent. Chỉ một recovery error path, không periodic task, long-lived receipt API/ledger/table/workflow hoặc thay core policy. Native grant setters, upload complete/domain identities có semantics riêng; không đánh đồng tất cả với append/copy receipts. Semantics chi tiết ở [filesystem mục 8](filesystem.md#8-concurrency-và-retry-giữ-đúng-giới-hạn).

### 8.3 Python bindings và config — integration work

[buf.gen.yaml](../../packages/contracts/buf.gen.yaml) chỉ Go/Go gRPC; [Make generate](../../Makefile) đã generate Python messages/gRPC stubs từ cùng descriptor bằng grpc_tools.protoc vào [sdk-python](../../packages/sdk-python/pyproject.toml). Phần còn lại là consume native stubs/helpers ở Leta và kiểm metadata/consistency/error handling; không copy SDK cũ hoặc thêm HTTP wrapper. Lượt này không chạy lại generation/build.

YAML hiện chỉ queues.leta/leta_runtime; [Queues Go struct](../../packages/sdk-go/connections.go) cũng chỉ hai keys này cho Leta, và [config loader](../../packages/sdk-go/config.go) strict KnownFields khi decode section. Theo cleanup contract mới, bổ sung dependencies.temporal.queues.leta_bridge đồng thời Go struct/Python/YAML mẫu/test/deploy; Platform cần routing name này, không credentials/Redis/provider config hoặc worker healthy. Không thêm key đơn lẻ làm strict core loader lỗi. Chưa sửa shared YAML/loader/manifests.

### 8.4 Leta access/transfer/physical cleanup và đầy đủ DTO/errors

Scope được người dùng thu hẹp: chỉ cấp/thu hồi operator; chưa triển khai transfer ownership API hoặc logic. Owner cố định theo provisioning input hiện tại; owner quản lý operator grants cho current human workspace members bằng native graph Touch/Delete, không thêm SQL ACL hoặc workflow. GET access và PUT/DELETE operator là HTTP surface cần hoàn thiện DTO/errors. Các nhắc transfer ở tài liệu khác mô tả capability/boundary tương lai, không là yêu cầu implementation hiện tại.

Đề xuất startup/periodic workspace housekeeping trong worker đã rút; không polling task, maintenance table hoặc scheduler. Workspace cleanup đã chốt native Temporal owning activities tại workspace-cleanup.md; root/box cleanup được gọi inline trong một workspace bridge activity, không best-effort notification hoặc nested B wait.

[streaming.md](streaming.md) đã chốt HTTP JSON + SSE trực tiếp sau Envoy, routes chính, AG-UI event schema và bounded SQL bootstrap/native Redis suffix replay. Leta vẫn native gRPC consumer của core; không application gRPC listener/dual server. Không tải whole logical run hoặc full tool bodies khi browser mới truy cập; current rights và exact-recipient HITL không đổi.

Operator access, workspace cleanup và retention MVP đã chốt: không auto-purge durable inbox/public history/archived resource records, giữ native checkpoint pruning; future purge/expiry hoãn. Đầy đủ resource/HITL/schedule DTO/errors cần cụ thể hóa; transfer ownership hoãn. Workspace cleanup không cần HTTP endpoint hoặc callback binding/list/stop.

Core không có active Leta client/listener. Shared activity contract đã chốt nhưng chưa implementation; không báo core workspace delete hiện đã cleanup Leta. Computer vẫn design-only, không dependency implementation hiện tại.

## 9. Validation và bước tiếp theo

Đã đọc active contracts/selected handlers/migrations/config và đối chiếu approved design. Không chạy build/Buf/protoc/Python generation, services, native DB constraints/concurrency, Envoy/JWT smoke hoặc cross-service E2E; không validate lại Zed. Không sửa runtime/config/infra/DB hoặc đọc secrets, không khởi động background process.

Mục 8.1 home-first, finite-horizon recovery ở 8.2, operator access, workspace cleanup và retention MVP đã chốt; thực hiện theo owning docs, không hỏi lại. Complete DTO/errors cần cụ thể hóa; transfer ownership hoãn. HTTP/events theo streaming.md, hệ thống/infra theo [system.md](system.md). Python SDK đã có; Leta consumer/shared cleanup config wiring là phần triển khai. Kiểm một shared integration journey: root provision/graph/storage → child containment → HITL human grant → remove/rejoin human không đổi agent access → workspace delete khi Leta offline → worker lên dọn tiếp. Core đã báo đồng bộ relation/RPC/generated; consumer dùng boundary mới, không compatibility alias. Giữ focused receipt test qua CAN/restart, không suite trùng hoặc test stack từng case. Lượt này chỉ kiểm tài liệu/current source, không chạy lại Zed validation hoặc runtime/integration.
