---
title: "Phase 4: Workspace and Temporal"
priority: P1
dependencies: [1, 2, 3]
---

# Phase 4: Workspace and Temporal

## Overview

Implement exactly the twelve [workflow trees](design-contract.md#the-twelve-workflow-trees), Workspace membership semantics and cross-service execution. Depends on the preceding schemas/identity/storage phases. Existing source/SDK findings are recorded in [evidence](source-evidence.md); implementation fault behavior must still be proven.

## Requirements

- [x] Register the reviewed workflows/activities only, on their executing owner's queues.
- [x] Workspace owns default-scope purpose/mappings and membership policy; LetFS creation remains generic.
- [x] Remove workspace-count checks and ownership transfer. Keep member cap, active owner invariant and existing retry receipts.
- [x] No per-node activities, generic prepare/complete sequence, wrapper polling, copy checkpoint/resume engine or progress tracking.

## Files and ownership

- Account: `apps/account/internal/temporal/workflows.go`, its workflow/replay tests and `cmd/server/main.go`; domain account functions from Phase 2.
- Workspace domain: `apps/workspace/internal/workspace/{service.go,store.go,authorization.go,invitations.go,relations.go,mutation_receipt.go,deletion.go,maintenance.go}` and integration tests.
- Workspace orchestration: `apps/workspace/internal/temporal/{workflows.go,relationships.go,deletion.go,maintenance.go}`, workflow/replay tests and `cmd/server/main.go`.
- Workspace API/config: `internal/transport/http/{server.go,workspaces.go,collaboration.go,deletion.go}`, `internal/transport/grpc/server.go`, `internal/config/config.go`, `infra/compose/dev.yaml`.
- LetFS orchestration: `apps/letfs/internal/temporal/{registration.go,client.go,activities.go,copy.go,lifecycle.go,processing.go,processing_client.go,maintenance.go,backfill.go}`, their tests and worker startup.
- Shared boundary: `packages/go/temporal/` for narrowly scoped typed names/DTOs; remove now-unused `packages/go/clients/workspace/client.go` and corresponding Python client/RPC server plumbing when no callers remain.
- Ingest: `apps/letfs-ingest/src/letfs_ingest/temporal/activities.py`, `apps/letfs-ingest/src/letfs_ingest/worker.py`, Go/Python processing contract tests; no Python business workflows added.

New domain activity implementations stay in existing owner packages. Split files only for real lifecycle boundaries, not one file/activity or a generic workflow engine.

## Implementation Steps

1. Route API input/auth checks through owning admission before starting work. OnboardUser's EnsureAccount admits the trusted system initial-workspace command after verifying identity; its child needs no permission/quota-check activity. Reuse deterministic input/name rules and transactional integrity checks. No database/SpiceDB I/O inside deterministic workflow functions. Generate request/resource IDs once and validate replay input identity.
2. CreateWorkspace calls remote CreateFilesystem, remote CreateScopes and local SaveWorkspace. No prepare row or fake completion marker. Workspace defines shared/personal IDs; the LetFS DTO contains no business purpose. SaveWorkspace records one filesystem/shared mapping, owner personal mapping and graph policy retry-safely.
3. OnboardUser ensures account, waits on child CreateWorkspace, then publishes Clerk identity. Remove polling/EnsureInitialWorkspace and obsolete completion/failure-marker activities. Preserve completed-onboarding no-recreation behavior without restoring the deleted Account FK or adding a Clerk workspace/completion marker.
4. Keep AccountChanges → ApplyAccountChange only for managed-account creation and its SQL/graph publication. Remove disable/status/active-gating and ownership-transfer branches. No expected/prior-owner protocol, account receipt table or generic future command controller. Ordinary profile writes stay direct; owner/type remain immutable.
5. Replace WorkspacePermissions with WorkspaceChanges for membership/access/delete commands. Active member additions provision one personal scope via CreateScopes, then AddMember saves membership/role/mapping/graph. Inactive members reuse retained scope. Invitation replay never restores a later-removed member without a new authorized join. Direct account-ID add supports accounts without verified email.
6. UpdateMembership handles role/remove in one activity, with transaction and existing receipt for SQL/graph response loss. Owner cannot leave or be removed; there is no transfer operation. Remove transfer command fields/CAS/tests. Acknowledge success after required graph publication. Remove PrepareMutation and generic preparation phase. UpdateScopeAccess changes grants on Workspace-owned shared/personal scopes; no scope registry or SQL ACL mirror.
7. Remove MaxWorkspaces config/wiring/count queries/errors and the old transfer-specific enforcement. Keep locks needed for remaining mutation/idempotency invariants. Enforce MAX_MEMBERS transactionally when adding/reactivating, without a separate activity or reservation table.
8. Compensation runs child DeleteScope/DeleteFilesystem only for newly created storage and after ruling out committed SaveWorkspace/AddMember/receipt on uncertain response. Never delete pre-existing/rejoined scope data on refusal. Retry transient failures; keep accepted destructive cleanup independent of caller/controller closing.
9. DeleteWorkspace marks deleting, waits on child DeleteFilesystem, then RemoveWorkspace clears logical Workspace access/state. DeleteFilesystem fences writes and scope creation, lists a page, waits on bounded DeleteScope children and repeats before RemoveFilesystem. No Workspace filesystem cursor/polls, bucket deletion machinery or wrapper RPC activity.
10. DeleteScope/PurgeTrash each have one bulk activity. Mark lifecycle, abort transfers, process bounded SQL batches and complete logical removal inside it. SQL remaining rows support safe deletion retry. Preserve late-write cleanup evidence, independently trashed subtrees and exact usage/count deltas. Keep a filesystem tombstone only while actual FK/cleanup attribution requires it.
11. Use default Temporal-generated child IDs. Duplicate standalone/child deletions may overlap; existing SQL locking/transactions and actual-row accounting make effects idempotent. Missing resource means done. No singleton coordinator, join protocol or lock table. ContinueAsNew only after outstanding page children/handlers finish; preserve accepted destructive children when parent closes.
12. CopyTree calls one CopyTreeData activity with direct bounded traversal/copy, existing source/destination guards, quota, transactional writes and object cleanup. Set MaximumAttempts to 1 and do not automatically restart the workflow after failure. On partial failure, return error and retain already-copied files. Remove durable CopyState Pending/frontier/terminal checkpointing, synchronous checkpoint RPCs, resume protocol and their tests; retain only local traversal state and genuinely used admission/result facts.
13. Remove all copy progress queries/endpoints/response fields/client methods and counters used for persisted progress. No heartbeat/history decoding, copy journal or replacement engine. Preserve copy's source-content/destination-write admission checks and existing byte/node bounds.
14. Keep ProcessFile CPU/IO/generation checks with scope context. ReconcileResources may redispatch a committed admission whose workflow never started; it must not restart started/terminal/partially failed copy. Preserve existing purge/deletion/processing dispatch recovery. Maintenance phases remain independently attempted with existing schedules/overlap SKIP; no new reconciliation service.
15. Remove old registrations, names, DTOs and obsolete replay histories; capture/replay fresh histories. No registered aliases. Remove Workspace revision/ETag/If-Match while retaining node revisions and expected identity guards.

## Todo

- [x] Twelve trees and owner worker registrations match the contract.
- [x] Membership/invitation/reactivation/access and SQL/graph retries pass.
- [x] Workspace-count config/enforcement and ownership-transfer surface removed.
- [x] Child deletion overlap, lifecycle/GC and compensation fault tests pass.
- [x] Ordinary copy success/partial-failure/no-auto-retry tests pass; progress/checkpoint/resume surfaces removed.
- [x] Fresh histories captured and replayed; old handlers and wrapper clients removed.

## Success Criteria

The exact tree executes against real owner workers in the same namespace. Creating one workspace makes one filesystem and generic scopes; joining/rejoining creates no filesystem. Admin cannot read personal content. Leaving retains its scope/mapping. All destructive effects remain retry-safe under worker loss, duplicate cleanup and cancellation. Retry never deletes committed resources or creates a second logical onboarding result.

## Verification

```sh
pnpm --filter @openlet/account test:workflow
pnpm --filter @openlet/workspace test:workflow
pnpm --filter @openlet/letfs test:workflow
pnpm --filter @openlet/account test:integration
pnpm --filter @openlet/workspace test:integration
pnpm --filter @openlet/letfs test:integration
pnpm test:replay
```

Required real Temporal fault matrix (unit mocks alone do not satisfy it):

| Scenario | Must reject / prove |
|---|---|
| Standalone and filesystem child delete same scope; worker dies between batches | No duplicate debit, lost cleanup evidence, stuck parent or false join assumption |
| Delete while upload/parse/copy in flight | No publication after fence; delayed S3 write still cleaned |
| SaveWorkspace/AddMember SQL or graph acknowledgement lost | Same IDs/mapping, no duplicate member and no compensation of committed storage |
| Managed-account creation SQL/graph acknowledgement lost | Same account identity and owner after retry; no duplicate managed account or resource-right inheritance |
| SQL admission committed but workflow never starts | Existing maintenance dispatches admitted work without new tables; never restarts an already-started or partially failed copy |
| Copy fails or worker is lost after some writes | Error, retained copied files, correct quota/cleanup and no automatic whole-copy retry or resume requirement |
| Successful copy across scopes | Source/destination permissions, bounds and content preserved without progress/checkpoint surfaces |
| Completed onboarding repeated after initial workspace deletion/history retention | Does not create a new default workspace |

## Risk and stop rule

Keep the reviewed twelve trees and ordinary copy failure tradeoff. No exact worker-death resume or persisted progress guarantee. If implementation requires changing schema/tree/public behavior, present the concrete issue for review; do not add copy engines, coordinator tables or lifecycle features.
