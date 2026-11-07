# Reviewed design contract

This file locks the result approved in the conversation on 2026-11-06. Phases describe implementation; they may not introduce a different product model. `W` means workflow, `A` activity; brackets name the service that executes it.

## Outcome, constraints and exclusions

Replace filesystem-wide inherited authorization with scopes, independent account identities and service-owned Temporal orchestration. There is one filesystem per workspace, with default shared and per-member personal scopes. Other services can create scopes in that filesystem without LetFS knowing their business meaning.

There is no production data. Rewrite the fresh-install schema/contracts directly, regenerate artifacts and fresh replay histories; do not build data conversion, dual reads/writes, old-object-key support or workflow version markers. Existing operations recovery is still a supported consumer. Preserve all existing `inline_text_only` behavior and user edits.

No new services, AI execution, agent assistants/delegation model, credentials, principal table, custom roles, quota reservation, SQL scope ACL mirror or generic workspace-scope registry. Existing receipt tables may continue providing actual retry guarantees; do not add another idempotency table or erase their guarantees as incidental cleanup.

## SQL ownership and fields

Existing file/upload/processing columns remain unless explicitly replaced below. Cross-service IDs are logical references, not cross-database foreign keys. Retain existing timestamp/size validation. Do not add revision to Workspace or Account.

| Owner/table | Target fields | Change and reason |
|---|---|---|
| Account `accounts` | `id`, `type`, nullable unique `clerk_id`, nullable `owner_id`, `display_name`, `avatar_url`, `created_at`, `updated_at` | Replace `users`; `type=user|agent`; no account status/disable field. User has Clerk identity/no owner; agent has owner/no Clerk identity. `owner_id` is an Account-local FK. Identity type is immutable; reject self-ownership. |
| Workspace `workspaces` | `id`, `name`, `filesystem_id`, `shared_scope_id`, `status`, `created_at`, `updated_at` | One filesystem and one default shared mapping. No duplicated owner; owner remains membership. Remove `quota_bucket_id`, `root_id`, `limit_bytes`, `revision`, provisioning-only `error_code`. |
| Workspace `workspace_members` | `workspace_id`, `account_id`, `role`, unique `personal_scope_id`, `status`, `joined_at` | PK workspace/account; `role=owner|admin|member`, `status=active|inactive`. Preserve personal mapping on leave/rejoin. At most one active owner; owner cannot leave or be removed; ownership is fixed at creation. |
| Workspace `workspace_invitations` | Existing fields, replace `accepted_user_id` with `accepted_account_id`; role `admin|member` | Keep trusted-email verification, hashed token, expiry and replay restrictions. Direct account-ID admission handles accounts without email. |
| LetFS `filesystems` | `id`, `limit_bytes`, `used_bytes`, `node_count`, `inline_text_only`, `state`, `created_at` | Move quota here; remove `bucket_id` and `root_id`. Node count starts at zero until scopes create roots. |
| LetFS `scopes` | `id`, `filesystem_id`, `root_id`, `state`, `created_at` | New actual storage boundary; root belongs to scope. No account type, owner service, role, shared/personal discriminator or per-scope quota fields. |
| LetFS `nodes` | `id`, `scope_id`, `parent_id`, `name`, `kind`, `size_bytes`, `revision`, `created_at`, `updated_at` | Replace filesystem-owned tree with scope-owned tree. Unique scope/id and scope/parent/name; composite FK enforces same-scope parent/root. Resolve filesystem through scope. |
| LetFS `trash_entries` | Existing fields with `scope_id` replacing filesystem scope | Original-parent reference cannot cascade away a separately trashed tree. |
| LetFS `uploads` | Keep transfer/publication fields; store scope identity and existing initiating `actor_id` | Actor ID means account ID. Remove logical bucket identity; derive filesystem from scope for quota/locks. Preserve transfer-result and processor-generation ownership. |
| LetFS `object_deletions` | Existing cleanup fields, replace `bucket_id` with `filesystem_id` | Cleanup survives logical resource removal. Retain a filesystem tombstone only while actual cleanup/FK attribution requires it; remove it when that dependency ends. |
| LetFS `files`, `index_deletions`, existing receipts | Existing payload, generation and cleanup facts | No new progress or item table. Scope identity in request/receipt payload where needed; index cleanup evidence must outlive source deletion. |

Delete `users.initial_workspace_id`; do not move two workspace IDs onto Account. Initial-workspace identity is part of the durable onboarding/creation request, not a permanent Account storage mapping. Workspace creation progress comes from Temporal until `SaveWorkspace`; SQL workspace starts active, then deleting/deleted. Preserve existing lifecycle tombstones where retry/cleanup needs them; `Remove*` means complete logical removal, not unsafe FK cascade before GC.

Inactive membership is excluded from active list/auth/count and shared access. Removal revokes membership-derived access and Workspace's default personal grant; it does not purge the scope. Rejoin reuses its existing `personal_scope_id`. Independently granted access outside this default membership policy is not globally traversed or rewritten.

## Authorization contract

| Resource | Actions |
|---|---|
| account | `read`, `update` |
| workspace | `read`, `update`, `manage_members`, `delete` |
| filesystem | `read`, `delete` |
| scope | `read_metadata`, `read_content`, `write`, `trash`, `restore`, `purge`, `manage_access` |

Catalogue notation is `resource:action`; actual Check takes resource type/id and action. Validate the pair; `read` is not globally unique. Generate Go/Python constants and the matrix from the owning contract, not independent hardcoded lists.

| Assignment | Permission policy |
|---|---|
| Account self / owner | Self can read/update its own account; owner can read/update the owned account. Owner is fixed at creation. Managing an account never grants that account's resource access. |
| Workspace owner | All workspace actions. |
| Workspace admin | Read/update/manage members; cannot delete workspace. Cannot mutate/remove owner through member management. |
| Workspace member | Read workspace; self-leave is the membership operation's explicit self-target rule; owner cannot self-leave. |
| Scope viewer | Read metadata/content. |
| Scope editor | Viewer plus write/trash/restore. |
| Scope manager | Editor plus purge/manage access. |

Shared defaults: owner/admin get manager access, active members get editor access through stable workspace usersets. Personal default: only the corresponding member gets manager access. Updating shared membership does not fan out to files/nodes. Workspace admin has no automatic personal access. Scope owner services publish grants; LetFS checks actions and never looks up workspace role or account type.

Use `account` directly as graph subject. Account service owns type and owner; LetFS does not inspect either. Remove the proposed account status, `account:disable` and `account#active` gating entirely. No replacement account lock/enable flag or lifecycle mechanism. Workspace membership status remains independent.

Replace old `user`, `quota_bucket`, capability `role`/`role_grant` schema and role bootstrap/policy code with fixed resource relations. Remove old filesystem→workspace content inheritance. Filesystem read/delete bindings are administrative rights published by its owner; they confer no scope content rights.

Metadata-only access cannot return snippets, extracted text, semantic context or reranked content. Copy requires source content-read and destination write; moving within scope requires write. `write` includes ordinary creation/editing, upload lifecycle and reprocessing; keep upload-initiator/session checks. Scope creation/quota configuration are system operations, not additional user permissions.

| Operation family | Required action / remaining invariant |
|---|---|
| Scope stat/list/resolve, trash metadata, processing status without output text | `scope:read_metadata`; scope/live/trash identity checks remain |
| File bytes/download, all content/semantic search, snippets/context, archive | `scope:read_content`; check before excerpt retrieval/rerank/provider calls |
| Create/edit/move-in-scope, upload admission/sign/finalize/abort, reprocess | `scope:write`; preserve upload initiator/session state and node revision guards |
| Trash / restore / permanent purge | Corresponding `scope:trash`, `scope:restore`, `scope:purge` |
| Copy | Source `scope:read_content`, destination `scope:write`; no copy-progress/monitor surface |
| Scope access changes | `scope:manage_access` at its owning business service; never a role-aware LetFS endpoint |
| Workspace metadata/member list | `workspace:read`; invitation management/member changes require `workspace:manage_members` |
| Workspace deletion | `workspace:delete`; admin cannot remove owner via member mutation |
| Filesystem metadata / deletion | `filesystem:read` / `filesystem:delete`; trusted system cleanup uses the previously admitted operation |

An async access change succeeds only after graph publication is acknowledged. Preserve the existing SQL→graph retry model: an intermediate SQL status change alone does not mean revocation has completed; while the command is pending, the previous graph rights may still apply. Do not introduce a graph-first two-phase protocol or a new SQL/SpiceDB coordinator. Tests must prove no success response while required publication fails and convergence after retry.

Check auth/input at service admission before starting workflows. Do not add permission/quota-check activities. Internal child entry paths must reuse the owning admission/business rules. Once admitted, retry-safe operations finish that command without reauthorizing each low-level step. Copy uses the no-automatic-retry policy below. Mutation transactions still enforce lifecycle, node identity/revision and hard accounting/member-cap invariants. Keep `MAX_MEMBERS`; remove workspace-count limits and the ownership-transfer feature, including obsolete enforcement.

## API and path boundary

- Request context explicitly identifies filesystem and scope. HTTP node/content/trash/upload/search/archive routes live under `/filesystems/{filesystem_id}/scopes/{scope_id}/...`; filesystem metadata remains a filesystem resource.
- `/` is the selected scope root. Relative paths/cwd, `..`, `@UUID`, raw IDs and expected identity guards must remain within that scope and live ancestry.
- Remove `Mount`, `PathContext`, `path_context`, `mount_path`, default mounts, virtual prefixes and every mounts parameter. Keep the locator/path feature itself.
- Cross-scope copy is allowed within the same filesystem, with separate source/destination scope authorization. Move stays within a scope; no recursive scope-ID reassignment.
- Scope goes through index input/payload/filter, semantic candidate validation, processing outputs, trash/upload/receipt scopes, archive preflight and backfill. Search never broadens to all scopes of a filesystem.
- Replace claim/header/response `user` naming atomically across Clerk, Envoy, Go, Python and fixtures: `openlet_account_id`, `x-openlet-account-id`, `account_id`. Do not keep old aliases.
- Required account-management surface supports create/read/update of owned accounts without agent runtime/credentials. Required direct workspace member admission takes account ID; keep email invitations for users with verified email.
- Managed-account creation forces `type=agent` and takes `owner_id` from the authenticated actor, not arbitrary body input. Account summaries return basic profiles for requested existing accounts; retain exact-set validation. No disabled-account special case or status response field.
- Remove `EnsureInitialWorkspace` polling RPC and clients once Account uses child `CreateWorkspace`. Do not keep an unused Workspace administration server or token/client configuration just for that route.

## The twelve workflow trees

```text
W OnboardUser [account]
├── A EnsureAccount [account]
├── child W CreateWorkspace [ws]
└── A PublishAccountIdentity [account]

W AccountChanges [account]
└── A ApplyAccountChange [account]

W CreateWorkspace [ws]
├── A CreateFilesystem [letfs]
├── A CreateScopes [letfs]
└── A SaveWorkspace [ws]

W WorkspaceChanges [ws, serialized per workspace]
├── Add/join: A CreateScopes [letfs] → A AddMember [ws]
├── Role/remove: A UpdateMembership [ws]
├── Scope grant: A UpdateScopeAccess [ws]
└── Delete: child W DeleteWorkspace [ws]

W DeleteWorkspace [ws]
├── A MarkWorkspaceDeleting [ws]
├── child W DeleteFilesystem [letfs]
└── A RemoveWorkspace [ws]

W DeleteFilesystem [letfs]
├── A ListScopesForDeletion [letfs]  (write fence + keyset page)
├── child W DeleteScope [letfs] × scopes, bounded concurrency
└── A RemoveFilesystem [letfs]

W DeleteScope [letfs]
└── A DeleteScopeData [letfs]

W PurgeTrash [letfs]
└── A PurgeTrashData [letfs]

W CopyTree [letfs]
└── A CopyTreeData [letfs]

W ProcessFile [letfs]
├── A process_file [letfs-ingest / CPU]  (if required)
├── A enrich_file [letfs-ingest / IO]    (if required)
└── A index_file [letfs-ingest / IO]

W StorageMaintenance [letfs, scheduled]
├── A ExpireUploads [letfs]
├── A ReconcileResources [letfs]
└── A DeleteObjects [letfs]

W WorkspaceMaintenance [ws, scheduled]
└── A PruneReceipts [ws]
```

All run in the existing per-environment Temporal namespace, explicit owner queues. Add only the shared typed workflow/activity names and DTOs needed for these cross-service calls under `packages/go/temporal/`; no domain implementation in that package. Activities are registered only on the executing owner's worker. No Workspace wrapper activity polling LetFS gRPC; no per-node child or activity.

AccountChanges → ApplyAccountChange handles managed-account creation and its SQL/graph publication only; retain no disable/transfer branches or generic future command controller. Profile-only edits remain direct. Create account graph facts retry-safely without persisting an initial workspace FK. `PublishAccountIdentity` publishes Clerk metadata; no generic CompleteOnboarding activity. Repeated completed onboarding must not recreate a deleted initial workspace, including after Temporal history retention; use verified Clerk completion identity and existing durable creation identity, not an added Account mapping field.

Ordinary CreateWorkspace requests are admitted by Workspace before start. Onboarding's child is a trusted system initial-workspace command: EnsureAccount already validates the Clerk/account identity and carries that admitted actor forward; there is no workspace-count rule left to reserve. Workspace reuses deterministic input/name checks and SaveWorkspace's integrity checks, not an extra network-check activity before storage.

Workspace allocates stable IDs once per command. It decides which opaque scope IDs are shared/personal and saves the mapping; LetFS scope creation has no such discriminator. Rejoin skips scope creation if the retained scope still exists. `SaveWorkspace` and `AddMember` are actual writes/graph publication, not success-marker activities. SQL/graph acknowledgement loss uses existing Workspace receipts and captured affected IDs; no graph RPC while holding SQL locks.

Ownership transfer is excluded for both Account and Workspace. Set owner at creation; owner fields/relations are not mutable through update/member APIs. Remove transfer actions, API branches, expected/prior-owner command fields, compare-and-set reconciliation and transfer-only tests. Keep existing Workspace receipts for the remaining membership/access changes; Account has no receipt table and gains none.

No workspace-count admission or reservation. Member cap is enforced atomically in AddMember. A permanent creation/join refusal runs existing child deletion for resources created by that command only; transient failure retries. Committed admission/membership must be reconciled before compensation so a lost acknowledgement cannot delete published storage. Cleanup failure remains visible and retryable. Accepted deletion continues independently of caller/controller closing; do not treat missing cancellation acknowledgement as completed cleanup.

Deletion fences scope/filesystem writes, uploads and processing publication. Bulk activities loop over bounded SQL batches internally, atomically preserving cleanup evidence, deleting actual rows and debiting actual usage once. Missing/deleted resources are successful retries. Logical completion can precede physical GC. Filesystem workflow paginates and waits for bounded children before ContinueAsNew; Workspace never enumerates scopes or repeatedly requests filesystem deletion.

### Duplicate deletion

Concurrent deletion requests may execute independently. Use default Temporal-generated child IDs and existing idempotent bulk deletion: missing resource means done; only actually deleted rows affect quota/node count and cleanup facts. No singleton coordinator, join mechanism or lock table. Bound child concurrency and test concurrent cleanup/accounting.

### Ordinary copy

CopyTree has one CopyTreeData activity that traverses and copies directly within existing byte/node bounds. Preserve source/destination validation and permissions, filesystem quota, revision guards, transactional writes and S3 cleanup evidence. On failure after partial writes, return a workflow error and retain files already copied. HTTP 202 acknowledges admission; subsequent failures are recorded in Temporal and are not returned through that completed request. No status/progress API is added. Configure this activity with `MaximumAttempts: 1`; do not retry the whole workflow/copy automatically after partial failure. No automatic rollback or exact resume guarantee.

Remove the old item-by-item orchestration, durable Pending/frontier/terminal checkpoint state, checkpoint RPCs, worker-death resume protocol and all progress queries/endpoints/SDK methods/counters. Do not read heartbeat details or workflow history to synthesize progress. Keep only local traversal state needed to do the copy; no progress table, copy journal or replacement engine. Existing admission/receipt facts stay only where genuinely used for admission/result integrity.

ReconcileResources may redispatch a committed admission whose workflow never started, alongside existing purge/deletion/processing dispatch recovery. It must not restart a terminal, partially failed or already-started copy. No new dispatch table or recovery service.

## Cleanup and acceptance boundary

Update contracts, generated artifacts, handwritten clients, bootstrap/recovery, Envoy, fixtures and docs together. Existing recovery must preserve canonical direct scope grants in SpiceDB and rebuild only SQL-derived relationships; it must not erase grants and pretend SQL can reconstruct them. Keep physical S3 bucket configuration; only logical quota buckets disappear. Fresh object keys use filesystem identity, with no old-key compatibility path.

No dead code, unused RPC/service clients or registrations, deprecated flags, old workspace ETags, role-policy loaders, virtual-root adapters, dual claims or skipped obsolete tests. Historical plans/journals remain historical; current docs and executable surfaces must contain only the new architecture. Root verification and cleanup evidence in Phase 5 is required before marking implementation complete.
