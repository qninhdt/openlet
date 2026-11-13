# Workspace resources, storage và authorization đã chốt

Cập nhật: 2026-11-12. Người dùng đã duyệt mô hình dưới đây; đây là authority thay cho đề xuất PostgreSQL-only và các boundary cũ. Cùng [plan rewrite](plan.md), không tạo plan mới. Core đã implementation/local E2E; [plan](plan.md) ghi acceptance còn mở. [API Platform/LetFS](api-contract.md) là contract đã chốt; API/transport cụ thể của Leta tiếp tục hoãn.

## 1. Domain và service ownership

Workspace là tenant thuộc Platform, chứa nhiều storage (LetFS), agent (Leta) và Computer (service tương lai). Các resource ngang hàng; không có entity filesystem/scope/drive nằm giữa workspace và storage.

| Service | Authority |
|---|---|
| Platform | User/profile/auth binding, workspace, membership/invitations, workspace lifecycle và generic workspace-active check |
| LetFS | Workspace quota/usage, storage/tree/content, storage access, uploads/trash/artifacts/processing/search |
| Leta | Agent definition/runtime/thread/messaging/HITL, agent access và hai chiều quan hệ agent thuộc workspace |
| Computer, tương lai | Computer definition, sandbox lifecycle và access |
| Ingest CPU/IO | Workers của processing boundary LetFS; không database hoặc ACL riêng |

Mỗi owning service có PostgreSQL database riêng; external IDs là references, không cross-service SQL/FK. Resource lưu workspace_id bất biến trong PostgreSQL. Agent root là subject agent; Leti/box giữ cơ chế nội bộ Leta và dùng root identity, không có workspace.agent riêng cho từng child.

Workspace owner/member chỉ dành cho user; owner có đúng một user. Agent là resource và subject độc lập, không mang role member hoặc kế thừa lifetime membership của human owner. Remove human member không dừng agent hoặc thu hồi grants của agent. Computer không tự thành subject: file IO thay agent phải giữ subject agent đó.

ActorRef là oneof user_id/agent_id. Caller process khác actor; actor được bind tại trust boundary, không lấy tùy ý từ model/request body. MVP giữ private-network trust và Clerk JWT ở edge; production mTLS native khi triển khai.

## 2. Storage và quota

LetFS quản lý nhiều storages trong một workspace ngay từ schema. Mỗi storage có cây root, owner/grants và visibility private/public.

- Private: quyền theo owner/editor/viewer.
- Public: mọi actor hợp lệ của cùng workspace, gồm human owner/member và agent thuộc workspace qua workspace.agent, mặc định được đọc. Ghi vẫn cần owner/editor.
- Public chỉ trong workspace, không public Internet.
- Personal/shared là cách FE hiển thị: private mà mình có role owner là “của tôi”; public là “chung workspace”. Private được chia sẻ trực tiếp vẫn xuất hiện trong danh sách truy cập được.
- Visibility không quyết định owner; private/public được chọn khi provision và cố định sau create. Không API/workflow đổi visibility; direct grants vẫn có thể cấp/thu hồi.
- Không bảng personal_storages/member_scopes, không UUIDv5/deterministic actor-derived ID, không UNIQUE owner→storage. IDs là UUID thông thường, được cấp một lần và giữ trong provisioning input/receipt để retry cùng effect.
- MVP chỉ hệ thống provision workspace/storage. Chưa public CreateWorkspace/CreateStorage hoặc UI tạo thêm storage; model đã hỗ trợ nhiều storage để thêm feature sau.
- Leta giữ workspace_id và một storage_id trên root agent. Multiple storage/switch storage của agent hoãn; không tạo workspace thứ hai cho agent trong thay đổi này.

workspace_storage là bản ghi ngân sách, workspace_id làm PK, gồm quota_bytes/used_bytes. Mọi storage dùng chung ngân sách. Không quota ID riêng, quota theo storage hoặc bản quota/usage mirror ở Platform.

Quota accounting giữ contract đã chốt: logical bytes text/blob/artifacts/trash/copies, không directory/metadata/vector overhead. Atomic conditional UPDATE đúng budget row trong transaction mutation; không reservation/lease hoặc workspace/storage lock bao trùm.

## 3. Source of truth

| Dữ liệu | Source of truth |
|---|---|
| User, workspace metadata, invitations | PostgreSQL Platform |
| Workspace owner/member | SpiceDB, Platform quản lý writes |
| Agent thuộc workspace: agent.workspace và workspace.agent | SpiceDB, Leta ghi/dọn cả hai chiều trong cùng native batch theo agent lifecycle; không trạng thái đăng ký riêng |
| Storage metadata, workspace_id, visibility, tree/payload/quota/usage | PostgreSQL LetFS |
| Storage ownership và role grants | SpiceDB, LetFS quản lý writes |
| Agent metadata/workspace_id/storage_id/runtime | PostgreSQL Leta |
| Agent owner/operator | SpiceDB, Leta quản lý writes |
| Computer metadata/workspace_id/runtime | PostgreSQL Computer |
| Computer manager/operator | SpiceDB, Computer quản lý writes |
| Role→permission expressions | schema.zed trong contracts, triển khai vào SpiceDB |

Resource→workspace là relation được owning service ghi vào graph từ workspace_id. Visibility canonical ở SQL và cố định sau create; public_workspace là authorization projection được ghi lúc provisioning. Đây là cross-store write thực sự, không atomic SQL+graph. Dùng native durable retries cho provisioning/deletion, không giữ SQL transaction qua network và không dựng outbox/permission-replication framework. Đã chốt cắt visibility update thay vì thêm workflow serialization.

Leta ghi agent:A#workspace@workspace:W và workspace:W#agent@agent:A trong cùng WriteRelationships batch với owner/operators. Chiều workspace.agent cho eligible_actor xác định agent có thuộc đúng workspace; không dựa vào membership human owner. Khi xóa agent, Leta xóa hai chiều trong cùng batch; workspace teardown cũng thu hồi workspace.agent. Transfer owner không đổi hai chiều này. Đổi tên registered_agent → agent trong active Zed/readers/writers khi implementation, không compatibility alias, RegisterAgent/UnregisterAgent RPC, registration workflow hoặc SQL status mới.

Owner là role đặc biệt trong graph, không owner_id mirror trong SQL. API business giữ cardinality workspace/agent một owner; sharing API không cho đổi owner. Actor IDs trên message, approver hoặc trash là event/business metadata, không role mirror. Không thêm created_by hàng loạt chỉ để phục vụ authorization.

SpiceDB là dữ liệu bền vững cần backup; không thể rebuild đầy đủ memberships/grants từ application SQL.

## 4. Roles và actions

| Resource | Role | Actions |
|---|---|---|
| Workspace | member | Xem workspace/member, dùng resources được cấp; quyền create_storage/create_agent nằm trong schema nhưng MVP chưa expose tạo storage từ client |
| Workspace | owner | Quyền member; membership/settings/quota, tạo Computer, transfer ownership và delete workspace |
| Storage | viewer | Metadata/list/read/download |
| Storage | editor | Viewer + create/write/rename/move/copy/trash/restore nội dung |
| Storage | owner | Editor + access/lifecycle |
| Agent | operator | Tương tác với agent |
| Agent | owner | Operator + configuration/control/access/transfer/delete |
| Computer | operator | Sử dụng môi trường/thực thi |
| Computer | manager | Operator + configuration/control/access/delete |

Không manager role trên storage hoặc agent. Workspace owner có administrative delete resource, không mặc định đọc private storage hoặc dùng agent của người khác. Workspace owner là manager của Computer qua workspace relation.

Personal storage provision cho agent dùng owner@agent:A và owner@agent:A#owner: human owner hiện tại có quyền owner trên đúng storage đó. Không kế thừa các storage/Computer khác chỉ vì agent có access.

Storage khởi tạo chung của workspace có owner@workspace:W#owner. Storage public có thể có owner khác; public access độc lập ownership.

## 5. Schema SpiceDB dự kiến

Không thêm filesystem/file/role/grant/principal object hoặc custom role engine. Các relation là fixed schema, không cấu hình động trong YAML.

~~~zed
definition user {}

definition workspace {
    relation owner: user
    relation member: user
    relation agent: agent

    permission participate = owner + member
    permission eligible_actor = participate + agent
    permission view = participate
    permission manage = owner
    permission create_storage = participate
    permission create_agent = participate
    permission create_computer = owner
}

definition storage {
    relation workspace: workspace
    relation public_workspace: workspace
    relation owner: user | agent | agent#owner | workspace#owner
    relation editor: user | agent
    relation viewer: user | agent

    permission read = (owner + editor + viewer + public_workspace->eligible_actor)
                      & workspace->eligible_actor
    permission write = (owner + editor) & workspace->eligible_actor
    permission manage_access = owner & workspace->eligible_actor
    permission delete = (owner & workspace->eligible_actor) + workspace->manage
}

definition agent {
    relation workspace: workspace
    relation owner: user
    relation operator: user

    permission use = (owner + operator) & workspace->participate
    permission manage = owner & workspace->participate
    permission transfer_ownership = owner & workspace->participate
    permission delete = (owner & workspace->participate) + workspace->manage
}

definition computer {
    relation workspace: workspace
    relation manager: user
    relation operator: user | agent

    permission manage = (manager & workspace->participate) + workspace->manage
    permission use = (operator + manage) & workspace->eligible_actor
}
~~~

Public storage có public_workspace@workspace:W; private không có relation đó. workspace và public_workspace phải cùng W, do LetFS ghi từ actual resource metadata. Membership đổi không cần enumerate/update storages.

Quan hệ default của storage agent là userset agent#owner, nên transfer agent owner không cần sửa owner snapshot trong LetFS. Các direct owner/grants và actual parent được kiểm tra tại owning API, không tin workspace_id/actor tùy ý từ Internet.

Theo yêu cầu người dùng, không validate lại bản Zed mới. Các assertions của draft cũ không chứng minh schema visibility mới đã được chạy.

## 6. Lifecycle và giao tiếp

- Create workspace là system provisioning: Platform row/owner, LetFS budget và initial storage IDs được cấp một lần; user mới có private storage ban đầu, workspace có public storage ban đầu. SQL không giữ storage mapping ở Platform.
- Add/accept member thay graph và provision private storage khi cần qua LetFS. Không có invariant một storage/owner; rejoin discover lại owned storages, không cần personal resolver authority.
- Create root agent: Leta lưu workspace_id; kiểm quyền tạo tại admission, gọi generic Platform CheckWorkspaceActive và tự ghi agent.workspace/workspace.agent cùng owner/operators trong một native SpiceDB batch. LetFS tạo storage thông thường theo provisioning identity; Leta lưu storage_id. Bỏ RegisterAgent/UnregisterAgent theo quyết định 2026-11-12; không Register<Resource> RPC hoặc bước đăng ký riêng.
- Grant/revoke storage đi thẳng API LetFS; HITL acceptance chưa là permission cho tới graph ACK.
- Transfer workspace/agent owner là graph mutation của owning service. Owner cũ không giữ quyền owner qua creator metadata.
- RemoveMember/self-leave kiểm quyền human và workspace active, chặn remove workspace owner bằng native graph precondition, rồi chỉ xóa workspace.member. Không scan agent.owner, sửa workspace.agent, dừng/xóa/transfer agent hoặc gọi từng resource service. Agent tiếp tục với identity/grants riêng dù human owner không còn trong workspace.
- Remove membership giữ dữ liệu/direct grants của human, bị vô hiệu bởi workspace gate. Rejoin kích hoạt lại quyền human từ grants còn giữ; agent không cần regrant/resume vì không bị remove tác động. Xóa dữ liệu/thu hồi vĩnh viễn là thao tác riêng.
- Delete workspace theo [cleanup đã chốt](workspace-cleanup.md): Platform revoke workspace graph rồi dispatch DeleteWorkspaceStorage trên LetFS queue và DeleteWorkspaceAgents trên Leta bridge queue song song. Storage ACK → DELETE Platform SQL; workflow vẫn chờ Leta, không stop-ACK barrier trước storage deletion hoặc readiness/hot-path dependency.
- Shared JSON activity input/queue mapping là contract liên service mới cần triển khai ở backend hiện có; không application cleanup RPC/listener, resource registry hoặc workspace polling. Archive Leta không đồng nghĩa physical purge history/checkpoints; retention vẫn review riêng.
- Ingest dùng sáu internal processing RPC LetFS và source version; không direct SQL hoặc graph authority.

RemoveMember không đọc ownership của resource service khác; thêm resource service không thêm nhánh vào handler này. Không thêm user.owned_agent hoặc expression owner-membership gate cho agent. Human agent owner/operator vẫn cần workspace participation khi điều khiển agent; quyền administrative delete của workspace owner giữ nguyên, không tự mở thêm quyền use/manage/transfer private agent. Generated service/native SpiceDB clients và shared workspace-cleanup activity là boundaries; không generic resource registry, direct SQL/thread/box/private workflows Leta hoặc SDK SQL.

Đây là quyết định đã duyệt thay policy cũ; [boundary Leta](../261111-2010-leta-rewrite/boundaries.md#71-removemember-và-agent-độc-lập) ghi rõ. Core Zed/RemoveMember/proto/fixtures đã đồng bộ rename relation, bỏ hai RPC và owned-agent scan/revocation; native Leta batch thuộc implementation Leta hoãn; không khôi phục policy cũ chỉ để cứu test.

## 7. UI, query và consistency

ListStorages ở LetFS, ListAgents ở Leta; Platform không proxy resource discovery. Native LookupResources hoặc SQL candidate page + CheckBulkPermissions; hydrate SQL theo batch, không N+1.

FE cần biết quyền trên nhiều storage: bulk-check read/write/manage_access; không ReadRelationships riêng từng storage chỉ để render card. Owner/grants chi tiết đọc khi mở access screen của một resource. ListMembers đọc một relationship page rồi batch user profiles tại Platform.

Permission checks mặc định minimize_latency, chấp nhận propagation/cache staleness; ZedToken cho read-after-write khi cần. Không mặc định fully_consistent trên mọi mutation/read hoặc dựng token-distribution/cache-invalidation framework.

Giữ nguyên text PostgreSQL, blob S3, một files.version, readonly artifacts, blob-only ingest và local receipt semantics trong [schema](schema.md)/[thiết kế](design.md). Không sửa domain/runtime Leta hoặc multiple-storage agent.

## 8. Trạng thái và bước tiếp theo

Architecture/ownership/storage/role decisions ở đây đã chốt ngày 2026-11-12. [API contract](api-contract.md) đã chốt qua trao đổi; chưa generate contracts, viết handlers/migrations, dựng infra hoặc chạy integration. API/transport và implementation Leta hoãn. Computer chỉ design trước, chưa thêm service/database runtime.
