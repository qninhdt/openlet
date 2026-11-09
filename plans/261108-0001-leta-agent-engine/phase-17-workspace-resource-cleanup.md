---
title: "Phase 17: Workspace deletion and Leta resource cleanup"
status: in-progress
priority: P1
dependencies: [4, 12, 13, 14]
---

# Phase 17: Workspace deletion and Leta resource cleanup

## Outcome and boundaries

Workspace deletion stops every workspace Leta/root/Leti producer and settles schedules/HITL before deleting its filesystem. Individual Leta archive removes that resource's received grants while retaining selected home/history state under creator-gated read. Integrate existing Workspace deletion with the real phase 12/13/14 lifecycles; do not infer resources from human memberships or invent another Workflow type.

Depends on [resource/home/access contracts](phase-04-workspace-resource-access-and-scope-view.md), [lifecycle](phase-12-messaging-and-box-lifecycle.md), [HITL](phase-13-async-hitl-resource-access.md) and [schedules](phase-14-temporal-schedules-calendar.md). The [accepted design](../reports/design-261108-0148-leta-workspace-resource.md) requires teardown before storage. Deployment/recovery is [phase 18](phase-18-deployment-and-recovery.md); full acceptance is [phase 19](phase-19-system-acceptance.md).

No user/account deletion, bot membership removal, owner-leave special path, grant mirror, periodic reconciler, lease/fence registry, permanent receipt or generic workspace-resource Workflow. Use existing lifecycle states, stable resource IDs and ordinary Temporal retry. This phase is necessary integration, not optional cleanup after release.

## Current source evidence and failure model

- `apps/workspace/internal/workspace/service.go::Delete` authorizes workspace.delete and calls mutation kind delete.
- `apps/workspace/internal/temporal/relationships.go::WorkspaceChanges` holds `workflow.NewMutex` during each mutate handler, including awaiting its DeleteWorkspace child. Enqueueing another WorkspaceChanges mutation from a child cleanup call will wait on that same held mutex.
- `apps/workspace/internal/temporal/deletion.go::DeleteWorkspace` currently executes `MarkWorkspaceDeleting → LetFS DeleteFilesystem child → RemoveWorkspace` using a disconnected context. It does not know Leta resources.
- `apps/workspace/internal/workspace/deletion.go::{MarkWorkspaceDeleting,RemoveWorkspace}` persists deleting/deleted; RemoveWorkspace removes invitations, then graph relationships. There is no Leta admission/stop step.
- `apps/workspace/internal/workspace/relations.go::UpdateScopeAccess` rejects nonactive W. Reusing it for already-admitted deleting-state cleanup would fail permanently; checking departed creator permissions would also strand teardown.
- `apps/letfs/internal/temporal/lifecycle.go::DeleteFilesystem` and `filesystem/deletion.go::ListScopesForDeletion` already own finite child scope/storage teardown. Keep this storage owner; do not proxy blobs or delete their SQL from Workspace/Leta.
- `apps/workspace/internal/workspace/relations.go::RemoveRelationships` currently knows shared/personal mappings. Leta home scopes are outside membership mappings; rely on LetFS scope deletion for storage-owned relationships and explicitly finish Leta resource-owned relationship cleanup.

## Required cross-service contract

Extend the existing proposed Leta native service from phase 04, with exact Workspace service credential and no delegated user:

| Method | Input | Admission and result |
| --- | --- | --- |
| ListWorkspaceLeta | workspace_id, cursor, limit 1–100 | Workspace-only enumeration of all canonical root rows by workspace/ID, including initializing/deleting/archived roots. No member list, transcript, prompt or cross-W result. |
| StopLetaForWorkspaceDeletion | workspace_id, leta_id | Verify Workspace caller and current W deleting state, exact canonical root W, then invoke/rejoin existing LetaLifecycleWorkflow archive using trusted cleanup admission. Complete only when real producer stop/settlement/access cleanup is acknowledged, not when Update is merely accepted. |

Workspace owns the outer admitted workspace deletion. Leta owns root/box/child state and the existing per-root lifecycle coordinator. The new method is an explicit service boundary into that coordinator, not a seventh Leta-service Workflow type or an owner impersonation.

For W lifecycle verification use GetWorkspace's narrow actor-free cleanup-status variant from phase 04. Exact authenticated Leta service plus local W deleting/deleted and canonical root→W binding returns required status/storage identity directly; it never invokes root creator/leta.read/manage admission, human membership, WorkspaceChanges or LetaLifecycleWorkflow. GetLetaBinding likewise reads canonical root state directly without submitting a lifecycle command. Public/user and normal runtime calls retain their distinct checks. This is no universal service bypass: exact method/service/cleanup-mode admission and owning state/binding must precede effects.

`CleanupLetaAccess` from phase 04 performs Workspace-owned exact relationship removal directly in its owning service, without dispatching back into WorkspaceChanges. Its two admissions are explicit:

1. Normal resource archive: lifecycle admission verifies current creator/manage authority before the durable deleting transition. Its subsequent Workspace cleanup callback verifies trusted Leta service, delegated creator matching canonical root creator, and exact persisted deleting/archived root/workspace/home. It does not re-require current creator membership after already-admitted deletion. Existing lifecycle state/command identifies the admitted effect; no new receipt or approval entity.
2. Workspace teardown: trusted Leta service, actor-free cleanup mode, local W is deleting/deleted, canonical root belongs to W and is deleting/archived. Originating workspace deletion was already admitted by Workspace. No current creator membership/normal workspace read is required for that cleanup only.

Neither mode can grant, provision, activate, read transcripts or delete arbitrary scopes. A caller cannot switch to trusted cleanup just by putting a mode flag in a public payload. Native handler/credential checks plus owning local state and canonical binding prove the narrow authority. Retain explicit safe errors and cancellation.

## Ordering and lifecycle guarantees

The updated existing DeleteWorkspace Workflow follows this order:

1. MarkWorkspaceDeleting closes Workspace admission first. Normal resource creation/provisioning, new scope grants and public mutations then reject active-only work.
2. Page all canonical Leta roots for W through ListWorkspaceLeta. For each root invoke StopLetaForWorkspaceDeletion with bounded Workflow fan-out and await completion. Page by immutable root ID; admitted pre-fence initializing resources and ordinarily archived roots are included. Archived roots still execute W-deletion relationship cleanup rather than returning an archive-status shortcut. Home/default provisioning participates in the same WorkspaceChanges serialization as delete, so pre-fence provisioned roots were already saved and are visible to enumeration. A root saved late from stale create authorization cannot provision after the W fence; its existing lifecycle handles WORKSPACE_DELETING as terminal initialization failure and removes only its own unpublished/unused resource relationships. It cannot activate, start a producer or compensate by deleting unrelated storage. Activation uses a local state gate so enumeration's deleting transition defeats a delayed activation acknowledgement.
3. Each existing LetaLifecycleWorkflow closes root/box receive/create gates atomically, snapshots children/schedules/unsettled HITL, and performs the phase 12 archive path. Cancel future schedule production, settle accepted grant/decision outcomes, cancel pending human requests where specified, stop root/all Leti and wait for runner/Mirage/checkpoint cleanup.
4. Finish exact Workspace grant cleanup through direct CleanupLetaAccess. Normal archive retains home_of and resource relations for accepted retained-home/history read. In explicitly admitted W teardown only, invoke existing phase 12 `publish_leta_resource` Activity in its remove mode after producer/HITL/grant cleanup and before stop acknowledgement; no new Activity/Workflow/finalization RPC. Normal archive never invokes that remove mode. Remove only this root's received direct viewer/editor grants inside W, including home/shared/personal. No grant to unrelated subjects/workspaces is touched.
5. Verify enumeration completed and all roots acknowledge stopped/settled/access-cleaned state. Only now run the existing LetFS DeleteFilesystem child. Storage failure retries that child while all producers remain stopped; resource rows/tombstones still identify every stopped root.
6. Existing RemoveWorkspace completes canonical deleted state/relationship cleanup after storage succeeds. A crash between storage completion and W finalization retries from current state; no reactivation or extra finalization RPC is needed.

Keep steps in existing owner Workflows/Activities. Do not hold SQL locks across native calls; snapshot/transition under owning transaction, then perform remote effects. Bound pages and fan-out rather than loading all runtime history or all scopes in one request. All admitted effects use stable W/L/home identities on retry.

For ordinary Leta archive, stop failure leaves deleting state with intact storage; late delivery cannot restart it. Accepted deliveries already committed before close remain history, not retracted. Phase 13 handles an accepted HITL whose grant outcome is not settled: finish or produce the specified terminal cleanup outcome before final grant removal. Phase 14 pause/delete semantics remain: pause blocks future production while admitted delivery may finish; delete checks current source/target and never retracts committed inbox input.

Normal scope grants/provisioning are serialized through active-only Workspace changes. During W deletion these are closed, and trusted direct cleanup only deletes exact tuples; this avoids races without another lock/lease subsystem. During individual archive, root lifecycle closes its own grant/request gates and waits outstanding accepted grant settlement before cleanup. A late external grant attempt must revalidate root status and fail rather than recreate a received grant.

### Accepted grant queued behind workspace deletion

The settled HITL barrier must not await an unapplied grant Update queued behind the same WorkspaceChanges delete mutex. Grant RPC/Update waits have deadlines. On uncertain completion, phase 13 repeats the same key and calls phase 04's direct retained-result/current-rights recovery first, before classifying a new lifecycle error. If a grant already applied, save its real outcome and finish delivery/skipped before removing it. Current read/retained result recovery does not write a new grant and must not require active owner/manage permission merely to settle an already admitted effect.

If no applied retained result/current sufficient access resolves the call, direct W/root status proves deleting and the new grant attempt returns the actual permanent lifecycle rejection; dependencies/timeouts alone cannot establish that result. Save that outcome and settle without waiting for the accepted-but-unapplied queued Update. Its eventual handler must recheck W/root active state after acquiring the mutex and before graph mutation, so it cannot apply after MarkWorkspaceDeleting or recreate a grant after cleanup. The deletion barrier relies on this execution invariant, not on waiting for the locked queue to drain. Use existing idempotency_keys/current graph checks and ordinary retry; add no receipt/fencing/retention subsystem.

## Exact relationship cleanup and retained state

For W filesystem, page private LetFS candidates using phase 04 listing. Filter native graph deletes by each canonical scope ID, subject type leta, exact root ID and only viewer/editor relations. Never delete every scope relationship or every subject merely because a resource is being archived. Workspace owns this mutation even when requested by Leta.

Leta resource home is ordinary storage; do not trash/purge it on archive unless the accepted lifecycle explicitly requested that effect. Retain scope:home#home_of@leta:L for creator membership-gated archived home read; no permanent creator viewer repair. Keep archive rows/config/history so old deliveries cannot resurrect runtime. Box deletion continues its identity-bound home trash only after that box's actual Leti stop; root archive does not silently run delete_box for every retained home.

For W teardown LetFS DeleteFilesystem removes all scopes, including homes, using existing object/processing/transfer cleanup. Workspace personal/shared mapping is not an exhaustive home inventory. Leta removes its own resource relationships in the admitted archive teardown before stop acknowledgement; Workspace removes workspace/storage usersets after storage. Rebuild/recovery must include retained lifecycle states and must not re-publish resource/default editor relationships for roots whose W is deleting/deleted or recreate deleted resources. Ordinary archived roots retain only the accepted resource/home read relationships, without runtime editor defaults.

Idempotency is current-state convergence: already stopped/archived resources acknowledge safely; already removed exact grants remain removed; deleted scopes/filesystems satisfy cleanup as currently defined. Do not claim arbitrary old config/control commands replay after receipt retention. An uncertain native timeout is retried with same resource identity and reconciled through current state; it is not a reason to run a second runtime or delete more broadly.

## Files and caller reach

Paths are under `/home/qninh/projects/openlet/`. Proposed phase 04/Leta paths are extended after dependencies.

| Action | Path | Required change |
| --- | --- | --- |
| Modify | `apps/workspace/internal/temporal/deletion.go` | Insert canonical Leta enumerate/stop/finalize before/beside existing storage teardown in correct order. |
| Modify | `apps/workspace/internal/temporal/relationships.go` | Preserve delete admission/serialization; prevent cleanup reentry through mutex-held handler. |
| Modify | `apps/workspace/internal/workspace/{deletion.go,relations.go}` | Deleting-state exact cleanup admission/owner effects and final relationship coordination. |
| Extend proposed | `apps/workspace/internal/workspace/resource_access.go`, `apps/workspace/internal/transport/grpc/server.go` | Trusted cleanup binding/status read; direct exact CleanupLetaAccess path. |
| Extend proposed | `packages/contracts/proto/openlet_api/leta/v1/leta.proto`, `packages/go/clients/leta/`, `apps/leta/src/leta/transport/grpc.py` | Workspace-only ListWorkspaceLeta/StopLetaForWorkspaceDeletion and validated response/completion semantics. |
| Extend proposed | `packages/contracts/proto/openlet_api/workspace/v1/workspace.proto`, `packages/python/src/openlet/clients/workspace.py` | Explicit cleanup/status admission without owner impersonation. |
| Extend earlier phase files | `apps/leta/src/leta/temporal/lifecycle.py`, `store.py`, `domain.py`, `worker.py` | Existing archive coordinator, W root enumeration/finalization and acknowledged terminal state. |
| Extend earlier phase files | `apps/leta/src/leta/temporal/box.py`, actual HITL/schedule bridges from phases 13/14 | Real settlement/cancel/stop behavior; no placeholder callbacks. |
| Modify | Workspace/Leta config/main credentials, authorization-rebuild owner paths | Exact cleanup method lists and correct archived/deleting restoration. |
| Modify existing | `apps/workspace/internal/temporal/{deletion_test.go,relationships_test.go,relationships_integration_test.go}` | Ordering/mutex/restart regressions with current workflow owners. |
| Create, proposed | `apps/workspace/internal/temporal/workspace_resources_integration_test.go`, `apps/leta/tests/test_workspace_cleanup_integration.py` | Persistent cross-service failure/race cases. |
| Generate | Shared Go/Python proto bindings | Actual canonical method descriptors. |
| Modify | `docs/{workflows,operations,architecture,api-contracts}.md`, `packages/contracts/rpc-surface.md` | Stop-before-storage, trusted deleting cleanup and recovery ownership. |

Do not modify LetFS deletion semantics unless a focused test proves a missing contract. Reuse its current owner Workflow and scope/root inventory. Final credential/Compose/recovery execution wiring belongs to phase 18, which must include all new exact methods.

## Numbered implementation tasks

- [x] 1. Reproduce the missing stop boundary and recursive-lock hazard in tests before integration: suspend root cleanup and prove current deletion would reach storage; model mutex-held WorkspaceChanges and callback mutation blocked behind it.
- [x] 2. Add typed Workspace-only Leta enumeration/stop contracts and actual native clients. Validate exact root/W IDs, stable keyset pages, caller identity and real completion (not Update acceptance).
- [x] 3. Add narrow trusted deleting-status read and CleanupLetaAccess admissions. Enforce local W state/canonical root binding; keep normal human active-only checks intact. Prove actor-free cleanup cannot provision/grant/read transcripts or target foreign resources.
- [x] 4. Implement direct owning exact-scope/subject grant cleanup without WorkspaceChanges dispatch. Preserve ordinary archive home_of and retained files; no member removal/default viewer repair.
- [x] 5. Extend existing DeleteWorkspace ordering with bounded enumerate/stop. Include initializing roots and race create against W fence. Require all producers/settlement acknowledged before existing storage child.
- [x] 6. Integrate real HITL/schedule/box outcomes and existing publish_leta_resource remove mode for W teardown only. Reconcile applied grant outcomes before cleanup; reject unapplied queued grants through direct current state and eventual handler checks without waiting for the delete-held mutex. Failed stop/settlement/cleanup preserves deleting state/storage; no no-op bridge success.
- [x] 7. Update canonical relationship rebuild paths for archived/deleting/deleted root/home state. Verify recovery preserves revoked direct grants and does not reactivate producers or republish editor defaults.
- [x] 8. Exercise real persistent Temporal worker restart and response loss at every new cross-service boundary. Rerun same W/L identities; prove bounded cleanup and no duplicate/restarted runtimes.
- [x] 9. Verify full matrix below and hand phase 18 exact native credentials, lifecycle migration/replay requirements and recovery order. Update owning docs only after source behavior is verified.

## Verification matrix

| Scenario | Required evidence |
| --- | --- |
| Storage barrier | With stop/accepted-HITL settlement blocked, DeleteFilesystem is never invoked. After real acknowledgement, exactly owned storage teardown proceeds. |
| Actual stopped | Running root/Leti invocation/checkpoint/Mirage cleanup finishes before scope deletion; merely accepted stop Update cannot satisfy barrier. |
| All resources | Human member enumeration misses no root because root enumeration is canonical; initializing/deleting/archived-pending roots included. |
| Create/fence race | No resource activates after W fence without being stopped; grant/home provisioning cannot run after deletion admission. |
| Lock safety | WorkspaceChanges delete handler stays active while Leta callbacks finish direct cleanup; no recursive mutate call/deadlock. |
| Grant queue and uncertain reply | Applied grant with lost RPC acknowledgement saves real outcome before cleanup; merely accepted/unapplied grant behind delete settles as proven lifecycle rejection without blocking. Resume its queued handler after deletion and observe zero graph writes. |
| Trust | W deleting cleanup works without departed creator session; same call against active/foreign W/wrong root/wrong token fails. Normal user permissions are unchanged. |
| Grants/files | Exact root received viewer/editor removed in W only; unrelated subjects/scopes/W preserved. Normal archive retains home_of/home/history without permanent human viewer. |
| HITL/schedules | Pending requests/future production settle; accepted in-progress outcome handled before grant cleanup; committed inbox messages remain. |
| Restart/lost response | Crash after mark, stop, grant removal, storage completion or final graph cleanup resumes safely from current state with same identities. |
| Dependency failure | Native/graph/Temporal failure leaves visible deleting progress and storage barrier; no false archived/deleted success. |
| Recovery | Fenced rebuild includes lifecycle tombstones, preserves discretionary grants/revokes and cannot revive archived resources/default editor grants. |

Run narrow tests first; proposed test/client paths are deliverables of this phase, not existing verified files.

```sh
go -C apps/workspace test -tags workflow ./internal/temporal -run 'Delete|WorkspaceChanges' -count=1
go -C apps/workspace test -tags integration ./internal/workspace ./internal/transport/grpc -count=1
go -C apps/workspace test -tags integration ./internal/temporal -count=1
go -C packages/go test ./clients/leta ./clients/workspace
uv run --locked --package leta pytest apps/leta/tests/test_workspace_cleanup_integration.py apps/leta/tests/test_lifecycle_integration.py -q
pnpm --filter @openlet/workspace test:workflow
pnpm --filter @openlet/leta test:replay
pnpm --filter @openlet/workspace check
pnpm --filter @openlet/leta check
pnpm contracts:check
```

Use isolated real PostgreSQL/SpiceDB/persistent Temporal and actual authenticated native services for the storage barrier/deadlock/restart claims. SDK workflow tests cover deterministic ordering separately. No provider inference or developer data needed; capture fresh histories and replay changed Workflows before release.

## Acceptance, migration and rollback

- [x] Existing DeleteWorkspace stops all canonical Leta resources before storage, including root/Leti/schedule/HITL producers and initializing races.
- [x] Direct admitted cleanup completes while WorkspaceChanges holds deletion mutex; no active-only permission deadlock or creator-session dependency.
- [x] Bounded grant waits recover applied/current-rights state before rejection/cleanup; queued unapplied grants cannot apply afterward, and direct status/binding reads bypass neither trust checks nor the required lifecycle state.
- [x] Exact cleanup preserves unrelated grants/files; ordinary archive retains accepted home/history read with current creator membership.
- [x] Stop/settlement/storage/native failures remain explicit/retryable with stable identities and no false completion.
- [x] No seventh Leta-service Workflow, bot membership/leave path, new permanent receipt or background resource engine.
- [x] Real wire/Temporal restart/replay and restore-state tests prove the matrix before phase 18 enables production deletion.

This accepted development rewrite has no production-data or old-history compatibility requirement. Current deletion histories must replay with the current Workflow code. Use fresh owned fixtures rather than an old-history migration/version gate; never reset unrelated running environments.

Rollback stops new deletion admission and preserves deleting rows, retained home/history and actual storage state. Continue already admitted cleanup with compatible workers/native handlers or forward-fix it. Do not mark W active, restart stopped runtimes or recreate removed grants to make rollback appear complete. A filesystem already deleted requires the coordinated recovery point, not application compensation.

## Execution checkpoint

Native inventory/stop, the actual mutex-held callback journey, lifecycle gates, canonical rebuild and current replay pass. Compose verifies production runner/storage cleanup and restored product state. See [final acceptance evidence](reports/acceptance.md) for exact fixture boundaries; the [execution checkpoint](reports/phase-17-execution.md) preserves earlier increments.
