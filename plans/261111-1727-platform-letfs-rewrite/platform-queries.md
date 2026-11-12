# Platform: query targets theo boundary hiện tại

Cập nhật 2026-11-12. [API contract](api-contract.md) đã chốt; [schema](schema.md)/[workspace resources](workspace-service-redesign.md) đã chốt. Không dùng inventory 20 RPC hoặc SQL mapping cũ làm authority. Đã implementation/local E2E; query budgets vẫn là targets, chưa EXPLAIN/benchmark.

## 1. Identity/workspaces

| API | Query shape |
|---|---|
| Onboard | DML CTE INSERT user/default workspace chỉ khi clerk_subject mới; duplicate SELECT user. Không member_scopes/initial fields |
| GetMe | Point SELECT users by verified identity |
| UpdateMe | UPDATE RETURNING; không readback |
| ListWorkspaces | LookupResources workspace.view page, bulk workspace.manage để derive role, rồi one SQL batch hydrate IDs theo graph ordinality |
| GetWorkspace | workspace.view + point metadata SELECT |
| UpdateWorkspace | workspace.manage + UPDATE RETURNING, không owner SQL lookup |
| DeleteWorkspace | workspace.manage, conditional lifecycle admission; native workflow revoke/cleanup; không query storage IDs tại Platform |
| TransferWorkspaceOwnership | Graph admission + native owner/member batch, không SQL role/owner mirror |
| CreateWorkspace, private | System admission SQL + provisioning; storage IDs trong workflow input, không workspace row |

Graph cursor không giả làm SQL-created_at cursor. SQL filter có thể tạo short/empty page có continuation; không unbounded refill/count.

## 2. Membership/invitations

ListMembers: một ReadRelationships page owner/member rồi một users batch. Không owner/admin/member ba roles, personal mapping JOIN hoặc per-user RPC.

AddMember: xác nhận target user và workspace, native graph member write, provisioning storage qua LetFS khi cần. Không owner→storage constraint/mapping, không role selector. RemoveMember/self-leave: human/permission/workspace-active checks, một native graph delete workspace.member với owner-protection precondition; không remove owner chưa transfer. Không agent.owner query, resource enumeration, workspace.agent mutation hoặc stop/cleanup fanout. Agent độc lập human owner và tiếp tục bằng quyền riêng; human grants còn giữ bị membership gate vô hiệu.

Invitations chỉ member, token_hash/expiry/accepted_by tại SQL. Create/List/Delete theo workspace index/keyset, không role column hoặc state journal. Accept validate native Clerk email, bounded member-limit check dùng chung AddMember, rồi conditional consume; token consumed không tự regrant. Giữ giới hạn consume-grant và first-response plaintext token đã chốt, không thêm saga/token receipt secret để che semantics.

## 3. Internal admission/profile

BatchGetUsers một SQL batch, không public global users list. CheckWorkspaceActive(workspace_id) dùng point SELECT workspace state, trả NOT_FOUND/FAILED_PRECONDITION theo contract; không nhận resource type/ID hoặc ghi resource graph. Quyết định 2026-11-12 bỏ RegisterAgent/UnregisterAgent; Leta kiểm quyền tại admission và ghi/dọn hai chiều agent.workspace/workspace.agent trong cùng native SpiceDB batch. Core source/generated đã đồng bộ; Leta implementation hoãn. Không agent registry table, registration state hoặc Platform RPC cho mỗi file request.

Không ListStorages/SetStorageAccess/ResolvePersonalStorage proxy ở Platform. UI gọi LetFS; root Leta giữ storage_id ở owning database.

## 4. Budget và retry

[Common budget](query-design.md) vẫn tính SQL/round trips/graph calls riêng. Native bulk checks, RETURNING, local receipts và short transactions; không network khi giữ SQL lock. Multi-store lifecycle dùng native retries, không claim distributed atomicity hoặc exactly-once. API route/proto implementation theo contract đã chốt.
