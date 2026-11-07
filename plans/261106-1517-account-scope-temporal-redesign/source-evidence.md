# Source and SDK evidence

Read-only scouting on 2026-11-06, branch `dev` at `dbc9077`. The existing working tree has inline_text_only changes; no implementation source was changed during planning. Paths/lines below describe current source, not already-implemented target symbols. Proposed behavior is in [Design contract](design-contract.md).

## Current ownership and affected callers

| Evidence | Verified current behavior / required reach |
|---|---|
| `apps/account/migrations/0001_initial.sql:2` | users has required Clerk identity, provisioning state and initial_workspace_id; cannot represent independent agent accounts unchanged. |
| `apps/workspace/migrations/0001_initial.sql:3,12,29,37,74` | Existing receipt, invitations, members, workspace storage mappings and one-owner index. |
| `apps/letfs/migrations/0001_initial.sql:34,46,67,81,92,106` | Filesystem/root/bucket schema; nodes, cleanup, trash and uploads all require ownership/attribution changes. |
| `apps/workspace/internal/config/config.go:57-61` | Default max workspaces and max members are both 100; MAX_OWNED_WORKSPACES removal does not remove MAX_MEMBERS. |
| `apps/workspace/internal/workspace/store.go:118-121,306-310` | Workspace-count enforcement exists in creation AND ownership transfer; both must disappear. |
| `packages/contracts/authz/schema.zed` | user subjects, capability role/role_grant, filesystem/quota_bucket inheritance and per-API permissions are the old model. |
| `scripts/contracts/generate.py:85-103`, `test_generate.py:15` | Generator assumes known resources and globally unique action→resource mapping; updating schema alone is insufficient. |
| `packages/go/authz/client.go:30,56`, `packages/python/src/openlet/authz.py:50-58` | Both clients hardcode subject type user. |
| `apps/account/internal/transport/http/server.go:50-53` | Only onboarding/me APIs exist; owned-account management is required by target account model. |
| `apps/workspace/internal/transport/http/server.go:55-61`, `collaboration.go:34-65` | Members can be read/updated/deleted; no direct account-ID add exists. Email invitation alone cannot admit an agent account. |
| `apps/workspace/internal/workspace/invitations.go:151-194` | Join requires trusted verified email; current row existence/removal behavior must be updated for inactive membership. |
| `apps/letfs/internal/filesystem/paths.go` | Mount dispatch, virtual path and root/ancestry behavior are shared by callers, not confined to HTTP. |
| `packages/go/clients/letfs/{filesystem.go,operations.go}`, `packages/python/src/openlet/clients/letfs.py` | Mount/PathContext propagated throughout handwritten clients. |
| `apps/letfs/internal/clients/search/query.go:15-33`, `apps/letfs-ingest/src/letfs_ingest/processing/indexing.py:47-54`, `clients/qdrant.py:70` | Search/index currently partition by filesystem; adding scopes requires payload/filter and candidate validation changes. |
| `apps/letfs/internal/filesystem/{uploads.go:292,processing_uploads.go:156,copy_state.go:143,maintenance.go:137-150}` | Logical bucket identity affects immutable S3 keys, cleanup locking and backpressure. |
| `apps/letfs/internal/clients/storage/storage.go:34,68,103-180` | Physical S3 bucket is a separate configuration; do not remove it. |
| `infra/config/envoy.template.json:127,215-216` | Old bucket route and claim/header mapping must change with clients/adapters. |
| `scripts/operations/recovery.py:16-23,400-416,456-467` | Existing recovery includes SpiceDB, repairs transaction IDs and invokes derived graph rebuild. Keep working; do not create new recovery architecture. |
| `e2e/tests/api/backup-recovery.spec.ts:75-77` | Test erases all non-role tuples; that is incompatible with canonical direct scope grants and must be replaced. |
| `apps/workspace/internal/workspace/relations.go:139-170` | Existing role-grant rebuild must be narrowed to actual derived relationships. |
| `docs/README.md`, root `package.json`, service manifests, `.github/workflows/check.yaml` | Existing docs navigation and commands own validation; no frontend app is in current repository scope. |

The current registered catalogue is ten workflows: Account OnboardUser; Workspace CreateWorkspace/DeleteWorkspace/WorkspacePermissions/WorkspaceMaintenance; LetFS CopyNode/ProcessFile/PurgeTrash/DeleteFilesystem/StorageMaintenance. Target twelve adds AccountChanges and DeleteScope while replacing old orchestration and activity placement.

## Temporal duplicate child IDs

Pinned SDK: `go.temporal.io/sdk v1.50.0` in `packages/go/go.mod`. Installed source under `/home/qninh/go/pkg/mod/go.temporal.io/sdk@v1.50.0/`:

- `internal/workflow.go:377-504`: ChildWorkflowOptions has WorkflowIDReusePolicy for closed execution; no child WorkflowIDConflictPolicy/use-existing option.
- `internal/internal_event_handlers.go:1897-1928`: collision produces ChildWorkflowExecutionAlreadyStartedError; no existing run ID is attached to the child future.
- `internal/internal_event_handlers.go:571-575`: omitted child ID is generated from parent current run and sequence.
- `apps/letfs/internal/temporal/client.go:94-99`: USE_EXISTING is used on CLIENT starts today; it is not proof of child adoption.
- `apps/letfs/internal/filesystem/nodes.go:122-136`, `deletion.go:194-265`: existing locked transactions and actual-row accounting/cleanup provide the pattern for new idempotent scope bulk deletion; they do not yet prove scope implementation.

Resolution: parent-generated child IDs plus idempotent bulk effects, with concurrency/failure tests. No automatic join claim, new workflow or schema.

## Copy source and superseded proposal

- `filesystem/copy.go` and `filesystem/copy_state.go` currently contain bounded CopyState, deterministic destination IDs and per-item commit/revision guards.
- `temporal/copy.go`, `temporal/client.go` and `temporal/registration.go` own old item orchestration and progress-query wiring. HTTP/gRPC contracts and both handwritten SDKs are affected consumers.
- Earlier scouting verified that ordinary heartbeat is buffered and that the installed SDK exposes a synchronous heartbeat RPC. The resulting Pending/frontier/terminal checkpoint and heartbeat/history-progress proposal was subsequently rejected by the user. API availability does not make that proposal a requirement.

Current direction: one CopyTreeData activity with direct traversal, no progress API or exact resume protocol. Partial failure keeps copied files and returns error; no automatic whole-copy retry. Preserve validation, action checks, accounting, bounds and object cleanup. Remove obsolete durable state/progress code and tests rather than retaining an unused engine. Existing admission recovery may dispatch only a copy that never started, not restart a partially failed one.

## Verification actually performed during scouting

One pre-change existing test suite was run by the read-only SDK scout:

```sh
# cwd apps/letfs; cached supported toolchain, offline dependency resolution
GOPROXY=off /usr/local/go/bin/go test -tags workflow ./internal/temporal -run '^TestCopyNode' -count=1
```

PASS. Initial attempt with GOTOOLCHAIN=local failed because base Go 1.26.4 is below go.mod 1.27.3; the normal launcher used cached 1.27.3 successfully. This baseline does not validate the redesigned single-activity copy. No new workflow/fault-injection/integration/API tests have run; no service processes or persistent databases were started/changed for planning.

## Planning method

HOLD SCOPE; reuse the accepted design rather than reopening alternatives. Five serial phases separate schema/contracts, identity, storage, orchestration and final cleanup. No new standalone infrastructure/framework. Plan files retain actionable checkboxes because no runtime task-management surface is exposed. Validation reuses user answers already given and rejects review suggestions that expand product/schema/tree without approval.
