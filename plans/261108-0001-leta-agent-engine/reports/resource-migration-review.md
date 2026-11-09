# Resource identity, access and cleanup rewrite review

Status: DONE_WITH_CONCERNS

## Delivered scope

Rewrote these pending execution phases against the accepted human-user/workspace-resource design and current source:

- [Phase 02: human users and migration](../phase-02-user-agent-migration.md), dependency 1.
- [Phase 04: Workspace resource access and generic scopes](../phase-04-workspace-resource-access-and-scope-view.md), dependencies 2/3.
- [Phase 17: Workspace resource cleanup](../phase-17-workspace-resource-cleanup.md), dependencies 4/12/13/14.

Only these three phase documents and this report were changed by this delegate. Old superseded phases remain for the controller's coherent replacement; no source, test, schema, provider, package, dependency or persistent data changes were made.

## Source-backed corrections

1. Managed accounts are already implemented in Account SQL/store/service/HTTP/Temporal. Phase 02 explicitly removes the real routes, CreateManaged/ApplyAccountChange/StartManaged/AccountChanges and self/owner tuple publication; omitting new provisioning alone would leave the wrong model alive.
2. Human UUIDs remain unchanged while users, membership/invitation fields, summaries, Clerk metadata/session claims, Envoy headers and Go/Python helpers change together. Account deployment/package naming remains possible; public human summaries have no type/owner enrichment.
3. Typed actors use mutually exclusive x-openlet-user-id/x-openlet-leta-id, with kind derived/validated at exact trusted service/method boundaries. Browser gateway identity is user only; Leti uses its root Leta subject.
4. Current schema initialization rejects mismatches, and direct scope grants are canonical SpiceDB state. Migration uses fenced inventory/backup, guarded additive SQL and a bounded one-off subject transformation preserving grants/revoked absence; no graph reset or speculative agent conversion. Real agents/conflicting references block before persistent mutation for separate disposition.
5. scopes_by_filesystem is a real existing index. New private read-only ListScopes returns candidates/roots; the deletion listing changes lifecycle and must not be reused. Generic Workspace discovery filters roots/labels by current typed BulkChecks and handles empty filtered pages.
6. WorkspaceChanges holds a Workflow mutex while awaiting DeleteWorkspace. A Leta callback that queues another mutation would deadlock; ordinary scope mutation also rejects W deleting. Phase 17 requires direct Workspace-owned, explicitly admitted exact cleanup instead, while keeping normal checks intact.
7. Existing DeleteWorkspace currently tears down storage before it knows any agents. The revised order closes W admission, enumerates canonical roots, runs real existing Leta lifecycle stop/HITL/schedule/grant cleanup, waits for actual stop completion, then invokes existing LetFS deletion and RemoveWorkspace. No new Workflow type.
8. Home/default provisioning participates in normal WorkspaceChanges serialization. Late stale creation cannot provision/activate past W deleting; local lifecycle gates defeat delayed activation, and no grant/lease registry is introduced.
9. Integration reread of phases 12/13 confirms the second mutex hazard: an accepted access-grant Update may be queued behind the DeleteWorkspace handler that is waiting for HITL settlement. Phases 04/17 now bound the RPC wait, recover matching retained applied/current-rights state first, then directly validate W/root lifecycle before retry/rejection. Queued execution revalidates active state again before graph mutation, so it cannot apply after W deletion admission; teardown does not wait for its own blocked queue to drain.

## Boundaries handed to the controller

- Workspace native methods: GetWorkspace, ListMembers, ListAccessibleScopes, EnsureLetaHomeAccess, ResolvePersonalScope, ChangeScopeAccess, CleanupLetaAccess.
- Narrow Leta native methods: GetLetaBinding, ListWorkspaceLeta, StopLetaForWorkspaceDeletion. GetLetaBinding is needed in phase 04 rather than deferred to phase 15, to validate canonical root/workspace/creator/home/state without a projection or membership fiction.
- Normal archive retains root/home_of for current creator-member history/home read and removes received direct viewer/editor. W-deletion archive uses existing phase 12 publish_leta_resource remove mode before stop acknowledgement. Root rows/tombstones stay for convergence/recovery; no extra Activity/Workflow/finalization RPC.
- Leta validates its own HITL request/decision/lifecycle; Workspace validates exact current personal owner, membership, root/W binding and viewer/editor. Do not query foreign HITL SQL or run approved filesystem calls as the human.
- GetWorkspace has a narrow actor-free trusted Leta cleanup-status variant: local W deleting/deleted and exact canonical root binding, no creator/member/read/manage or Workflow-lock dependency. GetLetaBinding is likewise a direct canonical read. Applied grant recovery returns actual retained/current state before a new lifecycle failure; it never regrants after a timeout.
- Phase 18 must coordinate real migration, exact caller secrets, listeners, recovery rebuild and Temporal history compatibility. Phase 02 provides explicit backup/inventory/Goose/graph/Clerk/rollback order and proposed CLI actions; it does not claim those commands exist today.

## Verification performed

Read repository AGENTS.md, shared development rules, planning/Ponytail skills, accepted design through final SSE corrections, old assigned phases, root/docs navigation, setup/API/operations material and relevant manifests. Used CodeGraph before indexed implementation exploration across identity, native authentication/authz, Workspace mutations/deletion, LetFS provisioning and recovery/schema tools. Confirmed index name against actual migration.

Document-only assertions passed: all three phases are pending, numeric dependencies match the new map, numbered unchecked tasks exist and each phase is below 800 lines (phase 02: 176 at its original pass; phases 04/17: 189/161 after integration). Accepted-design and owning-doc links resolve. Proposed files/tests/methods are identified as future work, not falsely reported as existing/passing behavior. Integration edits touched only phases 04/17 and this report.

## Concrete concerns for whole-plan integration

- Relative links to phase-03-leta-domain-schema.md, phase-18-deployment-and-recovery.md and phase-19-system-acceptance.md are the controller's canonical parallel rewrite targets and were not present at this delegate's structural check. Resolve after integration.
- Align narrow native Leta transport/client paths and method names with phases 01/03/09/12/15. All proposed paths here are explicit; no implementation was added.
- Phase 12 must retain the serialized home/default admission and stale-create handling described above, and permit already-admitted cleanup after creator visibility/session changes. No new creator-departure runtime policy is inferred.
- Existing external-S3 recovery cannot produce the managed-MinIO snapshot automatically. A persistent external-provider cutover remains blocked until its independent object recovery route is verified; no data inventory was run in this planning task.

No runtime tests, migrations or provider calls ran: this assignment is planning only. No new product-policy questions remain in the owned phases; actual legacy-agent contents/disposition are deliberately a future fail-closed inventory gate.

## Controller integration completion

The current 19-phase index and all replacement phase files now exist. Relative links/dependencies passed the final document sweep. Cross-plan follow-up corrections are recorded in [current plan review](plan-review.md); earlier missing-link/ownership notes above describe the parallel rewrite stage. Required runtime experiments remain pending; none were executed by document review.
