# Viết lại Leta: plan và các quyết định đã duyệt

Cập nhật 2026-11-12. Người dùng đã chốt schema 11 bảng và các PK/FK/UNIQUE/CHECK có invariant thật. Thay thế thiết kế 9 bảng/81 cột; không triển khai hoặc archive thêm trong lượt cập nhật plan. Không dùng skill/subagent.

## Kết quả, phạm vi và ràng buộc

Viết mới toàn bộ apps/leta, giữ Leta/Leti, immutable box graph, durable messaging, checkpointed runtime/history/compaction, async HITL, native schedules, Mirage files/search và public events. Archive source/tests cũ chỉ context, không copy handwritten implementation/tests/SQL từ đó, compatibility layer hoặc giữ old tests để ép thiết kế. Fresh database/Temporal namespace, không import data/jobs/histories cũ; database cũ giữ nguyên tới cutover riêng.

Agent có thể luôn bận 24/7 nhiều tháng/năm: Agent/ScheduleChanges Continue-As-New, native checkpoint boundaries/sync slices/pruning, không lifetime timeout/manual reset hoặc đợi workload rỗng. PostgreSQL domain, LangGraph context/progress, Temporal orchestration, Redis provisional events/cache, SpiceDB rights.

Thuật ngữ cho implementation mới: workflow HitlRequest, workflow ID hitl/{request_id}, module hitl.py/jobs/hitl.py, bảng hitl_requests/source_kind=hitl, activities open_hitl_request/resolve_hitl_request/apply_hitl_outcome và DTO prefix Hitl. Nếu chọn HTTP cho owning API thì request collection dùng hitl-requests; concrete transport vẫn chưa chốt. Không alias compatibility cho thuật ngữ cũ. Human/user vẫn chỉ người dùng/người duyệt; giữ nguyên type HumanMessage của LangChain vì đó là tên thư viện. Archive và hồ sơ implementation lịch sử giữ nguyên để tham khảo, không đổi tên source cũ rồi dùng lại.

## Tài liệu owning

- [Kiến trúc và folder structure](design.md).
- [Đề xuất chi tiết VFS/shell/Monty](filesystem.md): một home binding, giữ native dynamic mounts public/shared/private được cấp quyền; paths hướng agent dùng ~. Đề xuất bỏ persistent file cache chưa thay quyết định cache/folder hiện tại hoặc triển khai runtime.
- [Schema/field audit/constraints](schema.md) và [DDL review](schema.sql): 11 bảng, chưa active migration. Root resource và executable fields tách; agent/user deliveries tách; source hitl; HITL/schedule type ngoài JSON.
- [Temporal](temporal.md): sáu workflows, 21 activities, ba queues trong một worker process. Pending schedule command ở native history; finalized receipts theo schema core, không pending-command table/completed_at.
- [API/boundary review](boundaries.md): active proto/handlers/config, callers/actors/ownership, integration work và decisions còn mở.
- [Plan core](../261111-1727-platform-letfs-rewrite/plan.md), [resource authority](../261111-1727-platform-letfs-rewrite/workspace-service-redesign.md), [core API](../261111-1727-platform-letfs-rewrite/api-contract.md).

## Trạng thái workspace và phạm vi song song

Core active tree hiện có Platform/LetFS proto, generated Go clients, selected handlers/migrations; chưa kiểm build/deploy của phiên khác. Apps/leta hiện absent; tiến độ mới của core báo archive toàn bộ source/migrations/native dependencies vào archive/2026-11-11/apps/leta và đối chiếu hash 60 files. Lượt này dùng báo cáo phối hợp, không chạy lại archive/hash audit hoặc restore files cũ. Shared contracts/authz/YAML/infra do core owner quản lý, thay đổi integration phải đồng bộ trước code.

Platform/LetFS native gRPC, JSON qua Envoy. Leta là generated native gRPC consumer và native Authzed owner cho agent relations. Core không đọc SQL/thread/queue Leta hoặc phụ thuộc startup/readiness/stop ACK/permission hot path của Leta. Async owning cleanup được phép nhưng chưa API. Concrete Leta API/transport/access/transfer/physical cleanup và đổi home storage vẫn hoãn; giữ dynamic mounts cho storages agent được quyền đọc. Không tự phục hồi HTTP/SSE như transport đã chốt hoặc dựng dual server.

Quyết định đã chốt 2026-11-12: bỏ PlatformInternalService.RegisterAgent/UnregisterAgent và AgentRegistrationRequest khi implementation, không giữ compatibility wrapper. Platform cung cấp CheckWorkspaceActive(workspace_id) dùng chung, không nhận resource type/ID. Leta kiểm quyền tạo tại admission rồi tự ghi agent.workspace@workspace:W và workspace.agent@agent:A trong cùng native SpiceDB batch với owner/operators. Hai chiều mô tả agent thuộc workspace, không có bước/trạng thái đăng ký riêng; đổi tên relation cũ registered_agent thành agent. Agent chạy bằng identity/grants riêng, không phụ thuộc membership của human owner. RemoveMember chỉ thu hồi human membership, không quét/dừng agent hoặc sửa resource relations. Không thêm owned_agent hay Register<Resource>. Check workspace không phải distributed lock hoặc runtime permission proxy. Chi tiết tại [boundary mục 4](boundaries.md#4-root-provisioning-và-access) và [RemoveMember](boundaries.md#71-removemember-và-agent-độc-lập).

## Các bước

| Bước | Trạng thái | Acceptance |
|---|---|---|
| Kiến trúc/runtime nhiều năm | Đã duyệt thiết kế | 6/21/3; bounded context/checkpoints, cùng logical run qua rollover |
| Schema 11 bảng và integrity | Đã duyệt, artifacts cập nhật | Fields/constraints khớp; receipt sáu fields giống core |
| Rà soát active API/boundary | Đã ghi nhận | Matrix actors/callers và gaps tại boundaries.md |
| Agent relationship lifecycle | Đã duyệt; chưa implementation | Generic workspace check; Leta ghi hai chiều agent.workspace/workspace.agent cùng batch; xóa RPC cũ, không registration state |
| RemoveMember không liệt kê resource | Đã duyệt; chưa implementation | Chỉ thu hồi human membership; agent độc lập owner; không owned_agent, quét resource hoặc stop fanout |
| Box directory provisioning contract | Cần chốt | Giữ NOT NULL/preallocated ID hay nhận LetFS-generated ID khi provisioning |
| Cross-service retry horizon | Cần chốt | Không hứa append/copy dedupe vượt receipt retention core |
| Concrete Leta API/transport/access/cleanup | Hoãn theo quyết định trước | Một owning contract, không core stop/readiness dependency |
| Python bindings/config/infra integration | Chưa implementation | Generate từ active proto; role-scoped settings/three queues không phá core loader |
| Archive source/tests cũ | Core đã báo hoàn tất | Theo archive/progress record; lượt này không move/restore hoặc chạy lại hash audit |
| App Leta mới | Chưa implementation | Không copy handwritten archive code/tests |
| Implementation/checks/cutover | Chưa thực hiện | Narrow behavior + shared integration, fresh DB/namespace và backup trước data change |

Không schema/runtime/API core nào được tự sửa để giải quyết findings. Home node DDL giữ NOT NULL theo user decision; boundaries.md đề xuất nullable trong provisioning như một lựa chọn, chưa áp dụng.

## Thứ tự implementation

1. Chốt box home-ID/retry horizon và owning API/transport/cleanup còn hoãn. Đồng bộ core owner khi contract/config/infra bị ảnh hưởng; không hỏi lại routine choices đã được duyệt.
2. Dùng archive/progress record của core, kiểm actual inventory/dirty tree trước tạo app mới. Chỉ archive thêm nếu có source mới còn active; không ghi đè snapshots hoặc recreate/restore source đã absent. Loại archive khỏi discovery.
3. Viết app mới từng dòng: baseline schema, role config/native generated clients, feature functions, native saver/runtime/Mirage. Giữ schema ownership/constraints đã duyệt.
4. Nối activities/workflows và API; bỏ hai registration RPC/AgentRegistrationRequest khỏi proto, handlers, generated clients/descriptor và callers; thêm generic workspace check và Leta native graph batch. Đổi registered_agent → agent trong owning Zed, graph readers/writers và affected fixtures/bootstrap; bỏ owned-agent scan/revocation khỏi RemoveMember. Giữ quyền human/owner guard, kiểm một remove/rejoin case: human mất quyền còn agent cùng workspace giữ quyền, agent workspace khác không được cấp quyền. Đồng bộ core owner cùng đợt; không khôi phục test cũ để giữ policy đã bỏ. Cập nhật affected config/build/exports/CI; không dual serve/dual write, wrappers hoặc generic framework.
5. Chạy focused checks và một shared dependency environment/journey; core suites vẫn chạy khi Leta không deploy. Đo CI elapsed/container starts/handwritten lines riêng, không invent savings.
6. Cutover riêng có backup/restore và stop old writers/schedules; không thay data ở lượt design này.

## Acceptance

- [ ] Source/tests cũ chỉ context archive; không import/re-export/copy/fallback hoặc restore old suites.
- [ ] Schema đúng 11 bảng/field audit; root-only fields ở letas, recipient-specific deliveries, scalar type/status; không permission/progress mirrors.
- [ ] Giữ same-root/box/run FKs, naming/home/order uniqueness và essential CHECK; không cắt constraints để đạt số lượng thấp.
- [ ] Home directory provisioning thực thi được bằng owning API đã chốt, không giả định node-ID input chưa có.
- [ ] Runtime luôn bận qua slices/CAN/restart giữ logical run/context/pending work/public history; không lifetime reset.
- [ ] Schedule canonical pending command ở Temporal, old finalized receipt chặn stale apply qua CAN; không pending receipt/journal hoặc network trong SQL transaction.
- [ ] Retry guarantees đúng actual receipt horizon từng service; không exactly-once toàn shell hoặc grant/revoke concurrent.
- [ ] No bridge-slot cycle; cleanup settle producers/writers/grant effects, không chờ queued HITL delivery/BoxDelete cùng pool.
- [ ] Core gRPC/actor/resource contracts đúng: Leta ghi/dọn agent.workspace và workspace.agent cùng native graph batch; Platform kiểm workspace active dùng chung; storage/grants LetFS. Không RegisterAgent/UnregisterAgent hoặc adapter còn active; child IO là root actor + enforced box containment.
- [ ] eligible_actor = participate + agent; không owner-membership gate cho agent hoặc owned_agent. RemoveMember chỉ xóa human membership; human mất quyền, agent giữ quyền theo grants của chính nó, cross-workspace vẫn bị chặn. Agent/workspace delete mới dọn quan hệ thuộc workspace.
- [ ] HITL addressed human là event identity; apply kiểm current rights. Cache hit authorize, không bypass qua raw IDs/copy/move.
- [ ] Core revoke/delete chạy khi Leta tắt; không claim physical Leta cleanup khi chưa có owning API. Một home binding, public/shared/private grants discover/mount bằng root actor; refresh sau HITL, không alias toàn home storage để Leti thoát box. Không tự thêm tính năng đổi home binding hoặc SQL mount/grant mirror.
- [ ] Public events/replay/authorization theo transport contract được review, không hidden reasoning.
- [ ] Tests từ essential behavior, không test dependency internals/old exact structure; không stack mỗi case hoặc duplicate E2E.
- [ ] Không migration/data cutover nếu chưa backup; không old jobs/data/histories vào namespace/database mới.

## Verification

Đã đối chiếu selected active core source/contracts qua CodeGraph, migrations và design docs. DDL parse/field audit khớp 11 bảng/86 cột, 15 FK có PK/UNIQUE đích; receipt signature khớp hai core migrations. Doc links/fences/whitespace/line limits và inventory 6/21/3 đã kiểm. Chưa apply DB, build/run services, generate Python, Envoy/JWT smoke, provider/integration/benchmark hoặc validate lại Zed. Không khởi động background process hoặc đọc secrets.

Lượt chốt agent độc lập đã kiểm 11 Markdown files, 138 local links/anchors, fences/whitespace/line limits và tính nhất quán target graph/API/policy. workspace.agent là quan hệ thuộc workspace, RemoveMember chỉ tác động human; đã bỏ proposal owner-membership/owned_agent. Chỉ cập nhật plan/owning design; active Zed, runtime, proto/generated và SQL DDL chưa đổi. Không chạy DB/runtime tests hoặc Zed validation.

Lượt đổi thuật ngữ HITL đã kiểm sáu Markdown files trong plan và owning links mới từ docs: 67 local links/anchors, fences/whitespace/line limits, tên workflow/activities và inventory 6/21/3 nhất quán. Evergreen Leta sections đánh dấu nội dung implementation cũ, dùng thuật ngữ mới và dẫn về rewrite; không đổi archive/hồ sơ lịch sử hoặc tên HumanMessage của thư viện. filesystem.md là đề xuất chi tiết mới, có delta cache=0/bỏ policy.py được ghi rõ là chưa chốt; baseline cache trong design.md chưa tự thay. Đã đọc Mirage public wheel để đối chiếu APIs, không install dependency. Chưa chạy Mirage/Monty/native integration, benchmark, DB hoặc Zed validation; không tạo background process.

Đính chính theo yêu cầu truy cập public/shared/private storages: một storage_id là home binding, không là giới hạn số mounts. Đã sửa plan/design/boundaries/filesystem để giữ native dynamic mounts và đường dẫn ~; không thêm schema fields/activities hoặc đổi core contracts. Đối chiếu active ListStorages/capabilities và native cross-storage transfer qua CodeGraph, Mirage 0.0.8 add_mount/unmount/set_mount_mode/expand_tilde qua public wheel. Kiểm 66 local plan links/anchors và inventory activities không đổi; chưa runtime integration, DB hoặc Zed validation.
