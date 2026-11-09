---
title: "Phase 04: Workspace resource access and accessible scopes"
status: pending
priority: P1
dependencies: [2, 3]
---

# Phase 04: Workspace resource access and accessible scopes

## Outcome and boundaries

Workspace provisions ordinary LetFS homes/default access for workspace-owned Leta resources, manages scope grants and exposes one bounded accessible-scope view for humans and Leta. Human memberships remain human-only. Each Leta has a separate resource UUID, creator and home; Leti inherits its root subject and uses a backend-restricted box root.

Follow the [accepted resource design](../reports/design-261108-0148-leta-workspace-resource.md), [identity migration](phase-02-user-agent-migration.md) and [domain schema](phase-03-leta-domain-schema.md). Supply native contracts to [Mirage](phase-08-mirage-workspace-adapter.md), [lifecycle](phase-12-messaging-and-box-lifecycle.md), [HITL](phase-13-async-hitl-resource-access.md) and [cleanup](phase-17-workspace-resource-cleanup.md). No account/member creation, bot role, owner-leave exception, default creator personal access or additional Workflow type.

Implementation is complete for this phase. The [execution checkpoint](reports/phase-04-execution.md) records the seven native Workspace methods, canonical home/personal access/cleanup, shared user/Leta discovery, actual clients/listeners and verification. Runtime lifecycle, asynchronous HITL and workspace teardown orchestration remain in their owning later phases.

## Read first and source evidence

- `apps/workspace/internal/workspace/service.go::{Get,Members,AddAccount,ChangeMember}` currently assumes member-shaped identity and Account summaries. Phase 02 renames human paths; do not reuse membership admission for Leta.
- `apps/workspace/internal/workspace/relations.go::{ChangeScopeAccess,UpdateScopeAccess,WriteMemberRelationships,RebuildWorkspaceRelationships}` owns scope defaults/grants. Current ownership recognizes shared/personal mappings and hardcodes account subjects; recovery intentionally preserves direct grants.
- `apps/workspace/internal/temporal/relationships.go::{WorkspaceChanges,Mutate}` serializes changes under one Workflow mutex. `Mutate` replaces supplied keys today; preserve explicit ordinary retry keys instead.
- `apps/workspace/internal/workspace/mutation_receipt.go` uses existing `idempotency_keys`; completed entries expire after 24 hours. No new table or indefinite replay contract.
- `apps/letfs/internal/filesystem/provisioning.go::{CreateScopes,Scope}` creates independent scopes/roots with stable supplied IDs, without an identity record.
- `apps/letfs/internal/filesystem/deletion.go::ListScopesForDeletion` pages scopes but changes lifecycle. Discovery needs a separate read-only query using `scopes_by_filesystem`.
- `apps/letfs/internal/transport/grpc/administration.go`, `packages/go/clients/letfs/client.go` own private generic storage administration; no normal candidate-list RPC exists.
- Workspace config/main have no RPC listener. Reuse Account/LetFS native TLS/health/OTel/error/secret/shutdown patterns and generated exact method allowlists.

## Authority and ownership

Phase 02 owns canonical policy; this phase consumes it rather than declaring a different schema.

| Operation | Owning check and effect |
| --- | --- |
| Create resource | Active human membership plus workspace.create_leta; Leta persists root and its workspace/creator relationships. |
| Read/manage root/history/home | leta.read/manage = creator & workspace->read. Only current creator member; no automatic admin/member transcript/control access. |
| Home/defaults | Workspace validates canonical binding, calls LetFS and writes home_of plus home/shared editor to the Leta subject. |
| Personal scope | Existing membership mapping identifies exact human owner. HITL grants viewer/editor to root Leta, never creator or Leti; no home_of on foreign personal scope. |
| Scope manager | Human/workspace usersets only; Leta cannot become manager/member or receive a human role. |
| Relationship ownership | Leta owns resource rows and leta relations; Workspace owns foreign/default scope writes and provisioning integration; LetFS owns storage. |
| Actor | Verified typed native user/Leta actor; business target IDs are not actor authority. |

Creator departure removes human resource/home access through policy. Add no leave handler, permanent viewer tuple, ownership transfer or departure-triggered runtime lifecycle policy. Existing resource lifecycle and independent scope permissions still govern runtime.

## Proposed native interfaces

Create `openlet_api.workspace.v1.WorkspaceService`. Requests carry business IDs/cursors/ordinary mutation keys; actor/service authority comes from verified metadata, never protobuf owner/actor credentials.

| Method | Business input/caller | Result and admission |
| --- | --- | --- |
| GetWorkspace | Workspace ID; Leta service with verified user/root, or narrow actor-free cleanup-status request with root ID | Normal human requires workspace.read; runtime validates active root→W binding, without membership fiction. Cleanup-status variant requires exact trusted Leta service, local W deleting/deleted and canonical root→W binding, returning only required W status/storage identity. It never calls creator/read/manage admission or a Workflow queue. Return personal membership only for a human actor. |
| ListMembers | Workspace ID, cursor, limit 1–100; same actor forms | Enriched active human members. Human read/root binding checks as above; no bot filtering/type/owner enrichment or transcript/config data. |
| ListAccessibleScopes | Workspace ID, cursor, limit 1–100; verified user/root | Current effective rights/root metadata from private LetFS candidates. Human inspection of leta_id additionally requires leta.read. |
| EnsureLetaHomeAccess | Workspace/root/home IDs, stable create key; exact Leta service with delegated creator | Canonical initializing/active binding, active W, creator/create_leta checks; CreateScopes then acknowledged home_of/home/shared defaults. Return storage identity, no membership/profile. |
| ResolvePersonalScope | Workspace, human owner user, root Leta; exact Leta service | Canonical human personal scope/owner and current membership/resource binding for HITL; resolution grants no content access. |
| ChangeScopeAccess | Workspace/scope, typed user/Leta grantee, role/revoke/key; delegated human | Existing manage_access contract. Leta must be active same-W root and viewer/editor only. HITL additionally requires exact active personal owner; Leta owns current request validation. Return current rights after acknowledged mutation. |
| CleanupLetaAccess | Workspace/root/home IDs; exact Leta service with normal deletion or separately admitted workspace cleanup | Repeat-safe cleanup defined in phase 17; no public revoke bypass or membership removal. |

Runtime GetWorkspace/ListMembers authority is narrowly rooted in the trusted Leta service and canonical binding. It supports accepted workspace discovery/list_workspace_members, not generic workspace mutation rights or workspace.read@leta tuples. Foreign resource IDs cannot select an actor.

Add proposed service-only `LetaService.GetLetaBinding` backed by phase 03 rows: root ID/kind, workspace, creator, home scope and lifecycle status. Only Workspace service may call, actor-free. Return no prompt/history/model secrets. This narrow validation primitive is implemented with this phase rather than depending on phase 15 owner APIs. Ensure compares the same binding against Leta-owned resource relationships; a caller cannot register an invented home/foreign resource.

Add private `StorageAdministrationService.ListScopes(filesystem_id,cursor,limit)` for Workspace service only, actor-free. Return active scope/filesystem/root IDs and flags, no file tree/content/identity/grant projection. Never call mutating ListScopesForDeletion or admit browser/Leta tokens. Workspace validates and filters metadata before publication.

GetWorkspace cleanup status and GetLetaBinding are direct bounded owning-service reads, not Updates submitted to WorkspaceChanges or LetaLifecycleWorkflow. A deletion coordinator may already hold either Workflow's command lock while these methods run. Actor-free cleanup-status admission cannot expose a normal user view, history or any active-W mutation.

Use generated full-method constants and safe errors: validation, forbidden, not found, state conflict, dependency failure; preserve cancellation/deadlines. A failed dependency is never a successful empty list or completed home.

## Generic public accessible scopes

```text
GET /v1/workspaces/{workspace_id}/scopes
GET /v1/workspaces/{workspace_id}/scopes?leta_id={resource_id}
```

Default is authenticated user's scopes. leta_id inspection requires caller leta.read plus exact W binding before any candidate metadata. No arbitrary user_id inspection parameter. Admin/member status alone cannot inspect another creator's resource scopes. Native runtime uses verified root actor without a human session.

Return workspace/filesystem IDs, typed subject, items and next_cursor. A visible item includes scope/root IDs, current read_metadata/read_content/write and permitted known kind/owner labels. Stable mount key derives from scope ID. Adapter layout is home `~/`, shared `/shared/`, approved personal `/users/<human-user-id>/`. Generic user discovery may return other permitted scopes; do not invent runtime paths for them.

1. Resolve human inspection/root runtime admission and W before fetching candidates.
2. Fetch at most 100 ordered candidate scopes for W filesystem. Include homes/retained scopes, not only shared/personal mappings.
3. BulkCheck actual subject for read_metadata/read_content/write in separate fully consistent batches of at most 100 unique resources. Malformed/duplicate/missing responses or dependency failures fail the request.
4. Filter metadata-denied entries before root IDs or labels. Hydrate visible human labels through local membership mappings/bounded user summaries. No cross-service SQL or grant mirror.
5. Bind cursor to W, subject, inspector context and last scanned candidate; advance through filtered candidates. Empty page with next_cursor is valid. LetFS validates its opaque cursor; Workspace binds its wrapper to request context.
6. Return roots from candidate metadata, validating active root scope/filesystem identity. Do not load file trees or issue per-scope stat just to discover mounts.
7. Each subsequent LetFS operation checks current rights and backend mount root. View/cache is never authority; new grants cannot escape a Leti box.

No per-scope direct-role scan/can-relinquish feature is needed for this view. Existing human grant/revoke remains with its mutation owner; HITL uses resource-specific native checks.

## Home, grants and retry semantics

EnsureLetaHomeAccess reuses CreateScopes with persisted home_scope_id and stable create key across ordinary retries. Validate returned filesystem/scope/root/options. Same ID in foreign filesystem or changed options conflicts; lost acknowledgement never triggers deletion of a real home. Activation waits for acknowledged storage and graph effects; Temporal retries the owning Activity.

Publish exactly home home_of@leta:L, home editor and shared editor. No creator viewer/manager, personal grant, workspace role or Leta-owned relationship write from Workspace. Phase 12 serializes initialization; stale retries inspect current binding/state and cannot reactivate archived/deleting resources.

Use WorkspaceChanges for ordinary changes, including the narrow home/default operation: it serializes CreateScopes/publication with Workspace deletion and rechecks local W active state when executed, rather than relying on an earlier API check. Canonical root binding is a direct read, never a call back into its waiting lifecycle coordinator. Preserve supplied Mutation.Key and generate only when a legacy caller omitted it. Reuse existing idempotency_keys/retention where applicable; duplicate responses describe current state. No permanent receipts, stage journal, outbox, leases, fencing tokens, reconciliation loop or arbitrary ancient-command replay guarantee.

Personal approval revalidates recorded exact human owner/current active membership, canonical personal scope, root/W binding and viewer/editor role in Workspace. Leta validates its current request decision/lifecycle before calling; Workspace does not query Leta's HITL SQL. Requester is not approver. After grant, content calls remain root Leta; creator does not inherit private personal-scope access.

### Grant waiting, uncertain acknowledgement and deletion

ChangeScopeAccess uses a bounded native RPC/Workflow-update wait. Deadline/cancellation stops that wait; an already accepted Update may remain queued, so timeout is neither permanent grant failure nor proof that no grant happened. Phase 13 retries the same immutable W/scope/actor/grantee/role/key and performs these owner checks in order:

1. Validate trusted service/actor and exact request identity; inspect any matching retained idempotency result/completion under existing key/hash rules, then check actual current scope grant/rights directly. Recover an already-applied operation or already-sufficient current access before returning a new lifecycle rejection. A changed payload conflicts. Do not replay a grant merely because its acknowledgement was lost, and do not fabricate historical success after retention expires.
2. If no retained applied result/current sufficient access resolves the call, directly read current W state and canonical root lifecycle/binding before submitting or waiting for another Update. W/root deleting produces its real permanent lifecycle rejection without waiting behind the deletion mutex. An unresolved dependency remains retryable, not a false rejection or success.
3. At the actual queued mutation execution after acquiring WorkspaceChanges serialization, revalidate active W and eligible current root again before any graph write. A previously queued grant cannot apply after MarkWorkspaceDeleting, even when its original RPC timed out or cancellation did not cancel its accepted Update. A retained result read may report the prior acknowledged effect; it never authorizes a fresh grant in deleting state.
4. Phase 13 saves the recovered actual outcome or proven unapplied lifecycle rejection and completes delivery/skipped before root grant cleanup. Cleanup need not wait for a queued Update held behind that same delete: its eventual execution is guaranteed to reject by step 3. Do not infer absent effects from a timeout, empty receipt lookup or a stale cache alone.

Use existing idempotency_keys retention and current canonical graph checks for this ordinary retry path. No new grant receipt table/result journal, indefinite retention, fencing protocol or reconciliation poller. Tests must distinguish applied-with-lost-reply from accepted-but-unapplied-behind-delete, with current rights independently observed.

Deleting-state cleanup uses phase 17's explicitly admitted contract. It cannot submit ordinary active-only scope mutations or recurse into a locked WorkspaceChanges handler.

## Files and caller reach

All paths are under `/home/qninh/projects/openlet/`. Proposed paths do not exist yet; earlier-phase files are extended after dependencies.

| Action | Path | Purpose |
| --- | --- | --- |
| Create, proposed | `packages/contracts/proto/openlet_api/workspace/v1/workspace.proto` | Seven typed methods and bounded DTOs. |
| Extend proposed foundation/domain files | `packages/contracts/proto/openlet_api/leta/v1/leta.proto`, `apps/leta/src/leta/transport/grpc.py`; create `packages/go/clients/leta/` | Service-only root binding, Workspace-only credential and validated client. |
| Modify | `packages/contracts/proto/openlet_api/letfs/v1/letfs.proto`, `apps/letfs/internal/transport/grpc/administration.go`, `packages/go/clients/letfs/client.go` | Private candidate listing and exact caller scope. |
| Create, proposed | `apps/letfs/internal/filesystem/list_scopes.go` | Read-only bounded scope/root query using current index. |
| Modify | `apps/letfs/cmd/server/main.go`, `apps/letfs/internal/config/config.go` | Workspace listing credential/registration via shared secret reader. |
| Modify | `apps/workspace/internal/workspace/{service.go,relations.go,authorization.go,mutation_receipt.go}` | Common admission, typed grantees and acknowledged home/default/grant operations. |
| Create, proposed | `apps/workspace/internal/workspace/{resource_access.go,accessible_scopes.go}` | Binding/personal-owner validation and generic view. |
| Modify | `apps/workspace/internal/temporal/relationships.go` | Preserve supplied keys; ordinary mutation integration. |
| Create, proposed | `apps/workspace/internal/transport/grpc/server.go`, `apps/workspace/internal/transport/http/scopes.go` | Native/public adapters. |
| Modify | `apps/workspace/internal/transport/http/server.go`, `apps/workspace/internal/config/config.go`, `apps/workspace/cmd/server/main.go` | Route, listener, exact credentials, health/readiness/shutdown. |
| Create, proposed | `packages/python/src/openlet/clients/workspace.py`, `packages/go/clients/workspace/` | Validated destination clients. |
| Modify | `packages/python/src/openlet/clients/__init__.py`, earlier Leta client wiring | Exports and trusted actor propagation. |
| Generate | Go/Python bindings/native references | Canonical outputs, never hand-edit. |
| Extend existing/create proposed tests | Workspace resource/view/native integration tests, LetFS listing tests, `packages/python/tests/test_workspace_client.py`, Go Workspace/Leta client tests, `apps/leta/tests/test_resource_binding.py` | Real graph/storage/wire and bounded pagination. |
| Modify | `packages/contracts/{rpc-surface.md,public/openapi.yaml}`, `docs/{architecture,api-contracts,setup,operations}.md` | Owning native/resource/discovery docs. |

No managed-owner/membership SQL migration. Use existing Workspace mappings, canonical Leta rows and LetFS scopes; do not add a grant mirror or identity projection.

## Numbered implementation tasks

- [x] Prove resource/actor authority with real Workspace/LetFS/SpiceDB cases: create_leta, foreign creator/admin denial, equal human/Leta UUID separation, no personal inheritance or Leta membership.
- [x] Generate Workspace methods, private ListScopes and narrow root binding; validate response identity/exact sets and service-only versus delegated actor method allowlists.
- [x] Add read-only LetFS candidate query and root/lifecycle validation. Demonstrate no lifecycle/provisioning side effect and no unauthorized metadata publication.
- [x] Implement canonical binding and home/default publication. Lost storage/graph response converges on same identities; false binding/conflict grants nothing and never deletes real storage.
- [x] Implement shared user/Leta view, BulkChecks, filtered labels/context cursors and direct root metadata. Filtered-empty pages still advance to later allowed scopes.
- [x] Implement exact personal resolution and typed grants. Preserve normal human manager behavior; reject Leta manager, foreign-W/stale root/request and unrelated approver. Wait for acknowledged graph outcome.
- [x] Integrate ordinary Temporal/idempotency behavior with preserved keys and bounded grant waits. Recover retained applied/current-rights outcomes before lifecycle rejection, use direct W/root reads on retry, and revalidate active state at queued execution. Keep phase 17 cleanup outside the active-only mutation queue.
- [x] Wire listeners/TLS/health/OTel/secrets/shutdown, Go/Python exports and HTTP route. Client input cannot select trusted native actor.
- [x] Verify owning docs/contracts/callers together and hand exact home/binding/grant/cleanup interfaces to phases 12/13/17.

## Focused verification during implementation

| Contract | Required observation |
| --- | --- |
| Home/defaults | One home/root, exact default tuples; no user/member/creator personal grant; ordinary retries converge, conflicting identity fails. |
| Human visibility | Current creator sees/manages resource/home; another member/admin and departed creator get no transcript/control/permanent viewer bypass. |
| Personal approval | Exact owner grants to Leta; Leti uses root; creator still cannot directly read grantor personal scope. |
| View/pagination | Shared user/Leta logic includes homes; denied roots/labels absent; filtered page advances; foreign context cursor fails. |
| Native trust | Wrong token/service/method/actor, duplicate headers and browser Leta fail before mutation. |
| Current authority | Revoke after view/cache defeats next content/search/mutation; Leti backend root still applies. |
| Grant/delete queue | Applied lost reply recovers actual result/current rights before cleanup; unapplied grant queued behind delete settles without waiting on that queue and rejects before any later graph write. Direct status/binding reads never require creator/manage or a Workflow lock in admitted cleanup. |
| Bounds/failure | Bounded graph/storage calls, exact result validation, cancellation and explicit dependency errors. |

```sh
pnpm contracts:generate
go -C apps/letfs test ./internal/filesystem ./internal/transport/grpc
go -C apps/letfs test -tags integration ./internal/filesystem ./internal/transport/grpc -count=1
go -C apps/workspace test ./...
go -C apps/workspace test -tags integration ./internal/workspace ./internal/transport/http ./internal/transport/grpc -count=1
go -C apps/workspace test -tags workflow ./internal/temporal -count=1
go -C packages/go test ./clients/letfs ./clients/workspace ./clients/leta ./authz ./rpc
uv run --locked --package openlet-python pytest packages/python/tests/test_workspace_client.py packages/python/tests/test_rpc_wire.py packages/python/tests/test_wheel.py -q
uv run --locked --package leta pytest apps/leta/tests/test_resource_binding.py -q
pnpm --filter @openlet/workspace check
pnpm --filter @openlet/letfs check
pnpm --filter @openlet/python check
pnpm contracts:check
```

New clients/tests are proposed deliverables. Use app-owned isolated dependencies and real wire/storage/graph for authorization/discovery claims. Persistent Temporal cleanup is phase 17; full runtime journeys are phase 19.

## Acceptance, rollout and rollback

- [x] Seven typed Workspace contracts plus narrow binding/listing have actual clients, exact credentials and explicit failure paths.
- [x] Human membership stays human-only; Leta/Workspace/LetFS relationship/storage ownership is preserved.
- [x] Home/shared defaults and creator-gated home read match accepted policy; no personal inheritance/admin transcript/leave exception.
- [x] One bounded user/Leta view returns only permitted current roots/rights/labels with correct filtered pagination.
- [x] Exact personal owner grants to Leta; no manager escalation or inherited private-scope authority.
- [x] Existing key retention/ordinary retries suffice, without a grant mirror/background engine.
- [x] Applied and merely queued grants are distinguished under bounded waits; deleting-state replay cannot create a late grant, deadlock settlement or discard an actual applied outcome.
- [x] Phase 17 can finish trusted cleanup during deleting state without WorkspaceChanges recursion.

Phase 18 deploys compatible policy/native binaries and credentials after phase 02 migration. Missing binding/credential fails safely; no permissive fallback. Rollback fences new resource/grant writers and preserves homes/current grants/root rows for compatible retries; no destructive compensation or grant recreation from history.
