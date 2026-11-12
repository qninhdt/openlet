# Leta: rà soát API và boundary liên service

Snapshot 2026-11-12. Đối chiếu [plan core](../261111-1727-platform-letfs-rewrite/plan.md), [resource/roles](../261111-1727-platform-letfs-rewrite/workspace-service-redesign.md), [API design](../261111-1727-platform-letfs-rewrite/api-contract.md) và active proto/generated Go clients/handlers/migrations. Core đang implementation song song; tiến độ mới báo Buf/Go checks và một focused LetFS PostgreSQL integration đã chạy, chưa full-stack; các câu “chưa generate/implementation” trong plan cũ không phản ánh đầy đủ active tree. Đây là review tĩnh, không chứng minh services đang deploy hoặc integration chạy qua.

Leta [schema 11 bảng](schema.md), [DDL](schema.sql), [Temporal](temporal.md). Không sửa contracts, handlers, config/infra của core trong review này; không mở lại lựa chọn transport Leta đã hoãn.

## 1. Trạng thái thực tế

- Active contracts có PlatformService/PlatformInternalService và LetFSService/LetFSInternalService; generated Go clients và một phần new handlers/migrations đã có.
- Không còn apps/leta ở active tree. Mục tiến độ implementation mới trong plan core ghi đã archive toàn bộ Leta source/migrations/native dependencies vào archive/2026-11-11/apps/leta, đối chiếu hash 60 files. Dùng báo cáo đó làm trạng thái phối hợp; lượt này không tự chạy lại hash audit hoặc restore archive.
- Không có packages/sdk-python hoặc Python gRPC output trong packages lúc kiểm; buf.gen.yaml hiện chỉ generate Go/Go gRPC. Không có new Leta handler/client để kiểm một request end-to-end.
- Sáu workflow/21 activities/ba queues là approved Leta design, chưa worker implementation. Public/access/lifecycle API/transport Leta chưa có contract đã chốt.

## 2. Ownership và dependency matrix

| Hướng | API/capability | Actor và authority | Trạng thái |
|---|---|---|---|
| Client/Envoy → Leta | Agent/box/messages/history/HITL/schedules/events/access/control | Trusted human, current agent rights | Product capabilities đã giữ; concrete methods/routes/transport hoãn |
| Leta → PlatformInternalService | Generic CheckWorkspaceActive, BatchGetUsers | Platform sở hữu workspace state/user data; Leta tự ghi quan hệ agent thuộc workspace | Đã chốt bỏ RegisterAgent/UnregisterAgent; source/generated hiện tại chưa đổi |
| Leta → PlatformService | Workspace/member/profile operations thực sự cần | Human context khi method yêu cầu human | Không phải runtime permission proxy; chưa chốt từng Leta caller |
| Leta → LetFSInternalService | CreateStorage; DeleteStorage nếu owning cleanup contract cho phép | Private provisioning, không public body actor | CreateStorage contract có; agent physical cleanup policy còn mở |
| Leta → LetFSService | GetStorage/ListStorages, native files/search/trash/uploads; SetStorageAccess/RevokeStorageAccess | IO là root agent; grant là accepting human | Native contract/handlers hiện có; chưa Python consumer |
| Leta → SpiceDB | Agent owner/operator, hai chiều agent.workspace/workspace.agent và native checks/bulk | Leta ghi agent lifecycle; Platform workspace/membership, LetFS storage relations | Đã chốt; agent độc lập human owner, RemoveMember chỉ thu hồi human membership |
| Platform/LetFS → Leta | Async owning business cleanup nếu có | Không permission/readiness/stop hot-path dependency | Chưa có contract/client/listener; hiện core không gọi |
| Leta → Temporal | Own workflows/activities/native schedules | Native orchestration, không queue service khác | Design 6/21/3, chưa implementation |
| Leta → Redis/PostgreSQL | Events/cache và own domain/checkpoints | Không cross-service SQL | Dependencies nội bộ Leta |
| Leta → S3 | Signed URLs từ LetFS | Quyền/hạn signed transfer theo LetFS/provider | Không permanent S3 credentials trong Leta |
| Leta → model provider | LangChain/LangGraph native model calls | Provider credential thuộc role worker | Theo models.leta/catalog/YAML, chưa runtime mới |
| Leta → ingest/Qdrant | File operations qua LetFS tự trigger processing/search | Ingest/Qdrant thuộc LetFS boundary | Không direct processing RPC/Qdrant/SQL từ Leta |
| Leta ↔ Computer | Future service | Computer IO giữ invocation actor | Design-only, chưa thêm client/API/runtime |

## 3. Wire actor và trust

[identity.go](../../packages/sdk-go/identity.go) hiện nhận đúng một metadata value x-openlet-user-id hoặc x-openlet-agent-id, parse UUID; thiếu/cả hai/multiple values là unauthenticated. Đây là actor identity, khác process credential. MVP private-network trust; mTLS native là bước production đã chốt, không service-token registry mới.

- UI/API vào Leta: human từ trusted ingress; model/public request không được tự chọn actor.
- Root và mọi Leti gọi LetFS IO với x-openlet-agent-id = root Leta ID, không child ID. Child box/mount restriction vẫn phải bind riêng trong locator.
- Accepted approval: worker gọi SetStorageAccess với x-openlet-user-id = authenticated accepting human lưu trong response; request.actor.agent_id là root nhận grant. Không gửi đồng thời human + agent metadata, không dùng root subject tự grant.
- Platform public workspace methods trong handler hiện yêu cầu human. Không tự dùng agent metadata gọi GetWorkspace/ListMembers để thay permission check; runtime authorization dùng native SpiceDB/LetFS.
- Internal services không public HTTP annotations. MVP trusted network cho phép lifecycle calls; gateway routing/identity strip và actual Python metadata forwarding vẫn cần integration khi Leta transport được chốt.

## 4. Root provisioning và access

[Platform internal proto](../../packages/contracts/proto/openlet_api/platform/v1/internal.proto) và [handler](../../apps/platform/internal/platform/members.go) hiện vẫn có RegisterAgent/UnregisterAgent. Quyết định mới 2026-11-12 thay boundary đó: xóa cả hai RPC và AgentRegistrationRequest, không compatibility wrapper; thêm một CheckWorkspaceActive(workspace_id) nội bộ dùng chung cho các resource service. RPC chỉ xác nhận workspace tồn tại/active, không nhận resource type/ID hoặc ghi resource relationships. Không tạo Register<Resource> theo từng service.

Thứ tự implementation đã duyệt:

1. Temporal nhận canonical create input; cấp root agent/storage/storage-root ordinary UUIDs một lần.
2. Leta transaction ghi letas(workspace_id,storage_id,state=provisioning) + root agents và admitted receipt.
3. Provision activity gọi generic Platform CheckWorkspaceActive(workspace_id). Quyền workspace.create_agent và việc cấp owner/operator được kiểm tại admission; quyền chạy của agent không phụ thuộc membership owner về sau.
4. Leta ghi agent.workspace@workspace:W và workspace.agent@agent:A trong cùng native WriteRelationships batch với agent.owner và operators đã được chấp nhận. W lấy từ canonical immutable workspace_id; không có RPC/bước/trạng thái đăng ký riêng. Box/Leti dùng root identity, không thêm workspace.agent riêng.
5. LetFS CreateStorage với workspace_id, storage_id, **root_node_id**, StorageOwnership.agent_id=root, visibility PRIVATE, name và allow_blob_files/allow_indexing policy.
6. Conditional activate; deleting/archived không được resurrect.

[LetFS internal proto](../../packages/contracts/proto/openlet_api/letfs/v1/internal.proto) hiện bắt root_node_id. ID đó giữ trong canonical Temporal provisioning input, không cần thêm root-node field vào SQL Leta. Storage response/GetStorage cung cấp root node cho mounts.

LetFS ghi owner@agent:A và owner@agent:A#owner; human owner mới theo userset khi transfer. Leta sở hữu agent ownership/API transfer và hai chiều quan hệ thuộc workspace. Transfer owner không đổi workspace.agent hoặc quyền agent hiện có. Transfer/control/access methods cụ thể chưa chốt, không tạo SQL owner/creator/operator fields để tránh boundary này. SQL state check rồi graph write không phải distributed transaction; cả RegisterAgent cũ cũng không khóa được workspace qua hai bước. Không thêm lease/lock service để hứa atomicity chưa có.

Đổi relation registered_agent thành agent trong owning Zed và mọi affected graph reader/writer/fixture/bootstrap. Tên mới chỉ biểu thị agent thuộc workspace, không thêm trạng thái active/registered/unregistered vào SQL hoặc Temporal. Implementation phải đồng bộ proto/handler/generated clients/Envoy descriptor và Leta consumer cùng đợt với core owner; không giữ hai RPC cũ chỉ để test/client không đỏ. Không đổi application schema hoặc thêm workflow/activity type vì thay boundary này. Khi xóa agent, Leta xóa cả hai chiều thuộc workspace trong cùng graph batch; workspace teardown cũng thu hồi workspace.agent. Không áp xóa này khi remove human member.

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

Leta không tự query Qdrant/LetFS SQL, parse blob hoặc duplicate quota/version logic. Text nằm PostgreSQL; blob qua signed URLs, không binary/base64 request qua app JSON. Native files.version bảo vệ content; cache hit vẫn authorize/Stat trước expose bytes, không permission cache hoặc invalidation bus. Signed URLs đã phát hành giữ expiry semantics core, không hứa thu hồi bytes đã giao.

Một storage_id trong SQL chỉ là home binding, không cấm truy cập nhiều storage. Giữ native dynamic mounts: ListStorages/root capabilities → Mirage add_mount/unmount/set_mount_mode tại safe tool boundaries, gồm refresh sau HITL outcome. Mọi Leti dùng root actor nên chia sẻ external grants của root; home vẫn bị giới hạn theo box. HITL grant không đổi home storage_id. Chỉ tính năng đổi home binding còn hoãn; không phục hồi Platform personal resolver, /shared hoặc /users mapping và không thêm mount/grant table. Chi tiết tại [filesystem](filesystem.md#2-mount-và-identity).

## 6. HITL storage approval

hitl_requests giữ type/status ở columns, payload storage_id/role/reason, response accepting actor và outcome effect. Khi accepted:

1. Kiểm root/requester liveness và addressed recipient/current human rights.
2. SetStorageAccess(workspace_id,storage_id,actor.agent_id=root,role EDITOR/VIEWER) với accepting-human metadata.
3. LetFS kiểm actual storage parent, human storage.manage_access và target workspace.eligible_actor; graph ACK xong Leta mới ghi granted outcome.
4. Lost rights/resource → skipped; transient → native retry. Delivery source_kind=hitl vào exact requester, không pause toàn agent.

[SetStorageAccess handler](../../apps/letfs/internal/storage/access.go) dùng native graph set/delete và hiện **không có request_id field hoặc permanent grant receipt**. Không mô tả grant key như một API field đang có. Retry assignment idempotent, không globally exactly-once; concurrent revoke lúc effect còn pending chưa có final ordering. Cleanup Leta đợi effect settle, không đợi queued result delivery.

## 7. Cleanup và core independence

Core [DeleteWorkspaceResources](../../apps/platform/internal/platform/provisioning.go) hiện xóa workspace graph relationships, gọi LetFS DeleteWorkspaceStorage rồi xóa workspace SQL; không gọi/chờ Leta. Source RemoveMember vẫn đọc agent.owner để thu hồi relation cũ; đó là logic phải xóa theo quyết định agent độc lập ở mục 7.1, không phải target design.

Leta phải xử lý permission denied/not found tại safe boundary; không retry permanent revoke như transient vô hạn. Resource core bị xóa khi Leta tắt không làm core bị chặn. Async cleanup để đóng local workflows/archive agents có thể thêm sau owning API review; **hiện chưa có kết nối đó**, nên không claim workspace delete đã dọn toàn bộ Leta SQL/checkpoints/workflows.

User-requested Leta/box delete vẫn đóng admission, settle producers/HITL effects, stop writers, trash box homes khi còn quyền/tồn tại và archive local rows. Root delete xóa agent.workspace và workspace.agent trong cùng native graph batch, không UnregisterAgent RPC; box delete không sửa quan hệ root thuộc workspace. Không tự DeleteStorage chỉ vì root có storage_id; binding không exclusive ownership. Xóa graph owner/userset hoặc giữ/chuyển/xóa storage phải chốt cùng physical cleanup contract.

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

Agent/workspace lifecycle mới dọn quan hệ thuộc workspace; quyền human quản lý agent vẫn cần participation. Quyền administrative delete của workspace owner hiện có giữ nguyên; không tự mở thêm quyền use/manage/transfer private agent cho workspace owner. Chưa sửa active schema.zed hoặc RemoveMember runtime trong lượt plan này.

## 8. Các điểm còn thiếu hoặc lệch

### 8.1 Box directory ID — chặn implementation provisioning

Schema đã duyệt yêu cầu boxes.home_node_id NOT NULL và prepare_box biết ID trước remote effect. CreateNodeRequest/CreateDirectoriesRequest hiện chỉ nhận parent/path/name/request_id; không nhận node ID. Root CreateStorage nhận root_node_id nhưng không thay thế directory-create contract.

Hai lựa chọn reviewable:

- **Khuyến nghị:** cho home_node_id NULL trong provisioning, ghi node ID LetFS trả về trước conditional active; active bắt buộc có home node. Giữ native CreateDirectories/request identity và không thêm core RPC.
- Giữ schema NOT NULL/preallocated ID, đồng bộ core owner để thiết kế caller-chosen directory node ID trên owning API.

Chưa áp dụng lựa chọn nào: không đổi field/nullability đã chốt hoặc tự mở proto. Không gọi API xong mới best-effort start workflow; durable admission vẫn phải đi trước external effects.

### 8.2 Dedupe horizon của file effects

[Config mẫu core](../261111-1727-platform-letfs-rewrite/openlet.example.yaml) hiện idempotency_retention_seconds=86400 cho Platform/LetFS. [Receipt helper](../../packages/sdk-go/receipt.go) gắn expires_at, local mutation + response commit cùng transaction; migrations hai database có cùng sáu fields. Maintenance có cleanup receipt hết hạn.

Leta chạy liên tục nhiều năm không đòi mọi receipt sống vô hạn. Tuy nhiên nếu tool effect đã commit, chưa checkpoint rồi retry sau khi LetFS receipt bị GC, cùng key không còn bảo đảm dedupe append/copy. Receipt infinity trong DB Leta không kéo dài receipt LetFS. Chưa có guarantee retry horizon liên service đủ để hứa không duplicate sau outage vượt retention.

Cần chốt retry horizon/retention với core owner hoặc ghi rõ giới hạn chấp nhận trước implementation. Không tự thêm long-lived receipt API/ledger/wrapper hay đổi core retention policy trong audit này. Native grant setters, upload complete/domain identities có semantics riêng; không đánh đồng tất cả với append/copy receipts.

### 8.3 Python bindings và config — integration work

[buf.gen.yaml](../../packages/contracts/buf.gen.yaml) hiện chỉ Go/Go gRPC. Leta cần generate Python messages/grpc.aio stubs từ cùng active proto, native metadata/consistency/error handling; không copy SDK cũ hoặc HTTP wrapper để lấp thiếu client.

YAML hiện chỉ queues.leta/leta_runtime; [Queues Go struct](../../packages/sdk-go/connections.go) cũng chỉ hai keys này cho Leta, và [config loader](../../packages/sdk-go/config.go) strict KnownFields khi decode section. Vì vậy không tự thêm leta_bridge vào shared temporal.queues rồi làm core không load được. Queue thứ ba thuộc Leta worker; đồng bộ owning config mapping hoặc giữ trong Leta-owned settings khi implementation. Chưa sửa shared YAML/loader/manifests.

### 8.4 Leta API/transport/access/physical cleanup — decision đã hoãn

Chưa có method inventory/proto/routes/status/event framing được chốt cho Leta; HTTP/SSE trong design cũ chỉ là phương án. Cần review public resource/control/access/transfer/HITL/schedule/events và internal cleanup trong cùng owning API contract. Không thêm dual server/callback binding/list/stop để lấp chỗ trống.

Core không có active Leta client/listener. Async cleanup được phép nhưng chưa contract; missing contract không cho phép báo core workspace delete đã hoàn tất physical Leta cleanup. Computer vẫn design-only, không dependency implementation hiện tại.

## 9. Validation và bước tiếp theo

Đã đọc active contracts/selected handlers/migrations/config và đối chiếu approved design. Không chạy build/Buf/protoc/Python generation, services, native DB constraints/concurrency, Envoy/JWT smoke hoặc cross-service E2E; không validate lại Zed. Không sửa runtime/config/infra/DB hoặc đọc secrets, không khởi động background process.

Trước implementation boundary, chốt mục 8.1, retry horizon ở 8.2 và owning Leta API đã hoãn; generation/config wiring là phần triển khai. Sau đó kiểm một shared integration journey: root provision/graph/storage → child containment → HITL human grant → remove/rejoin human không đổi agent access → delete. Rename relation/RPC removal phải chạm Zed source, graph readers/writers/fixtures/bootstrap, proto/generated/descriptor và affected consumers; không giữ compatibility alias. Giữ focused receipt test qua CAN/restart, không suite trùng hoặc test stack từng case. Lượt này chỉ kiểm tài liệu, không chạy lại Zed validation hoặc runtime/integration.
