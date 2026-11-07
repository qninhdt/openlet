---
title: "Phase 5: Cleanup and acceptance"
priority: P1
dependencies: [1, 2, 3, 4]
---

# Phase 5: Cleanup and acceptance

## Overview

Finish remaining connected consumers, prove no dead/legacy path remains, and verify the whole accepted replacement. Depends on all preceding phases. Do not defer cleanup to a later task.

## Requirements

- [x] Contracts, executable code, SDKs, infrastructure, operations, fixtures and current docs agree.
- [x] Existing recovery preserves canonical direct scope grants without a new backup/migration system.
- [x] No compatibility adapter, old registration/config or silently skipped regression remains.

## Files and consumers

- Runtime/bootstrap: `packages/go/cmd/authz-schema/`, `packages/go/testfixture/spicedb.go`, `scripts/bootstrap/{configure.py,test_graph.py,test_configure.py}`, `infra/config/envoy.template.json`, `infra/compose/{dev.yaml,e2e.yaml}`.
- Operations: `scripts/operations/{recovery.py,test_recovery.py}`, `e2e/setup/recovery.test.ts`, `e2e/tests/api/{recovery.spec.ts,backup-recovery.spec.ts}`.
- Fixtures: `e2e/fixtures/{api-test.ts,boundary-server.ts,native-grpc.py,filesystem-lock.ts,temporal-control.ts}` and setup settings/environment readers.
- API suites: `e2e/tests/api/{onboarding,workspaces,files,uploads,processing,streaming,native-grpc,gateway,recovery,backup-recovery,telemetry}.spec.ts`; external Clerk smoke contract if fixture shape changed.
- Shared SDK tests: `packages/python/tests/{test_letfs_clients.py,test_platform.py,test_rpc_wire.py,test_contracts.py,test_authz_wire.py,test_import_boundaries.py,test_wheel.py}` and affected Go client/authz/RPC tests.
- Current docs: `README.md`, `docs/{README,architecture,data-model,api-contracts,workflows,operations,setup,testing}.md`, `docs/openlet.dbml`.
- Tooling authority: root `package.json`, service/package manifests, `go.work`, `uv.lock`, `.github/workflows/check.yaml`; no dependency upgrade is requested.

## Implementation Steps

1. Finish Envoy route removal and account-claim/header wiring. Remove old workspace polling client/server startup and any now-unused config/client/service token only after verifying no remaining callers. Existing service RPC authentication remains; do not rebuild it.
2. Replace old dynamic role bootstrap/verification calls and test fixtures with fixed schema setup. Delete roles.json/policy.go or their obsolete portions when no live caller remains; update generate/contract verification accordingly.
3. Update offline Account/Workspace relationship rebuild to touch only SQL-derived account identity/owner, active membership and stable shared bindings. Preserve direct scope viewer/editor/manager grants, including explicitly changed personal grants; do not manufacture manager grants from SQL on rebuild or erase/regrant whole scope ACLs.
4. Keep existing recovery dump/restore of SpiceDB and existing transaction-ID repair. Change the test that currently deletes every relationship except role, because SQL cannot rebuild canonical direct grants. Test derived-tuple repair separately from full graph restore. No new backup system, migration backup phase or SQL grant mirror.
5. Update E2E fixture to account/workspace/filesystem/shared scope/member personal scope identities. Replace mount/quota endpoints and workspace ETags. Keep inline-only expectations and physical S3 config. Test one-FS shared/private scopes, direct account-ID join, private scope isolation, removal/rejoin, quota and workflow fault paths.
6. Scan source/config/generated outputs and current docs for the exact removed surfaces below. Inspect every hit; remove dead implementations, imports, helper types, registrations, params, env wiring, tests and comments. Do not satisfy scans by renaming dead code or adding an ignored compatibility parameter.
7. Update the smallest owning docs and DBML against implementation; link scripts/contracts instead of duplicating generated details. Historical plans/journals remain historical and are excluded from runtime-removal scans. Update any README link that presents an old design as current authority.
8. Run narrow changed suites first, then full required checks below. Investigate failures; no skipped tests, weakened auth/quota assertions or fabricated replay histories. Record exact command/results/environment limits.
9. Review final diff against the initial user working tree: preserve inline-only changes and unrelated work, remove own temporary artifacts, stop any processes started for tests. No commit/push/deploy without another instruction.

## Todo

- [x] Connected SDK/Envoy/bootstrap/recovery/E2E consumers updated and dead contracts/config removed.
- [x] Direct grants survive rebuild/restore; shared membership bindings remain correct.
- [x] Source/generated/config/current-doc legacy sweep completed with each hit explained.
- [x] Full check/build/unit/workflow/integration/replay/API suites pass.
- [x] Docs/DBML, final diff and process cleanup reviewed; no user changes lost.

## Success Criteria

Implementation has no executable consumer of removed contracts or hidden old-model fallback. All twelve workflow trees and scope/action semantics match the reviewed contract. Current docs describe the implementation; root verification results and real restart/cleanup evidence are recorded honestly before phase checkboxes close.

## Removal sweep

Search only current source/config/generated/current docs (exclude `.git`, dependencies, historical `plans/`, cache/build artifacts). Use `rg -l` with explicit owner directories/globs to enumerate matching files, then inspect each matching file fully. The final zero-match existence gate must not truncate matches. Include tests:

```text
Mount / PathContext / path_context / mount_path / mounts parameters
quota_buckets / quota_bucket_id / logical bucket_id / GetBucketUsage
CreateBucket / FreezeBucket / ListFilesystems / CompleteBucketDeletion
MAX_OWNED_WORKSPACES / MaxWorkspaces
initial_workspace_id / EnsureInitialWorkspace / GetUserSummaries
openlet_user_id / x-openlet-user-id / X-Openlet-User-ID
WorkspacePermissions / PrepareMutation / PrepareWorkspace / CompleteWorkspace
CopyNode WORKFLOW registration; NextCopyItem / CopyItem / FinishCopyFile activities
copy progress endpoints/queries/SDK methods, durable copy checkpoint/resume state
account:disable / account#active / proposed accounts.status and disable branches
workspace:transfer_ownership / ownership-transfer API/workflow/config/tests
expected_owner / prior_owner command fields and transfer CAS protocol
role_grant / InitializeRolePolicy / VerifyRolePolicy / obsolete roles.json consumers
workspace revision / ETag / If-Match guards
```

Keep workspace_members.status=active|inactive and storage/workspace lifecycle states. Do not ban legitimate `type=user`, descriptive user text, physical S3 bucket configuration, node revision/ETags, existing receipt tables or parser stage names. Replace removed security tests with new-contract behavioral tests, not deleted coverage.

## Full verification

Commands below exist in current manifests/CI; execute from repository root, after the focused phases pass:

```sh
pnpm contracts:check
pnpm check
pnpm build
pnpm test
pnpm --filter @openlet/account test:workflow
pnpm --filter @openlet/workspace test:workflow
pnpm --filter @openlet/letfs test:workflow
pnpm test:integration
pnpm test:replay
pnpm check:e2e
pnpm e2e:api
git diff --check
```

Use existing Compose/Testcontainers harnesses, deterministic ports and process ownership rules. No paid external-provider run is implied. Existing external smoke requirements can be reported separately if credentials/infrastructure are unavailable; never claim them passed.

## Risk and stop rule

Keep cleanup evidence and direct grants even when deleting old code. Do not interpret no-production-data as permission to erase user environments. No compatibility rollback layer is required; implementation rollback is source-level until any persistent environment operation is explicitly authorized. Any unexplained executable old-model reference or failing required test blocks completion.

## Execution evidence — 2026-11-06

- Passed `pnpm contracts:check`, `pnpm check`, `pnpm build`, `pnpm test`, all three owning `test:workflow` commands, `pnpm test:integration` (7 tasks), and `pnpm check:e2e`.
- Passed `pnpm e2e:api`: 34/34 tests against freshly built real services, including isolated backup/restore, independent accounts, private scope isolation, membership removal/rejoin, copy failure, worker restart, upload accounting and deletion after caller/parent loss.
- Passed `pnpm test:replay` with the 18 freshly exported E2E histories covering all twelve workflow types. Native LetFS integration histories also replayed successfully.
- Passed `node --test --test-concurrency=1 e2e/setup/environment.test.ts e2e/setup/recovery.test.ts`: 3/3 tests, no skips. Startup port refusal, SIGTERM cleanup and isolated database/S3 restore all passed. Owned Compose containers, volumes and networks were removed; fresh replay histories were retained separately during harness verification.
- Real Temporal/PostgreSQL/SpiceDB fault tests passed for managed-account and workspace/member publication after lost graph acknowledgements and worker replacement. Deletion tests stop the worker after an actual committed batch while overlapping standalone/child cleanup; usage is debited once and parent deletion completes.
- Final review added the missing lifecycle check before a queued scope grant publishes after workspace deletion. Its focused PostgreSQL/SpiceDB regression, Workspace check/build/unit tests and the subsequent full API run passed.
- The ingest image initially stalled downloading the pinned table model through Xet. Direct HTTP retrieval worked; disabling Xet only in the existing model-prefetch build step completed the build and full E2E run without changing model revisions or runtime behavior.
- Removal sweep found no executable old-model surface. Remaining `CopyItem` matches are local bounded-copy helpers, not activities or checkpoints; `CreateBucket` remains solely for physical S3 test storage. No new skipped tests or lint/type suppressions were introduced.
- Markdown links resolve. Original inline-only migration, plan and journal are byte-identical to the pre-implementation snapshot; inline-only behavioral tests pass against the scoped model.
- External paid-provider/Clerk smoke, persistent environment resets/migrations, commit, push and deployment were not run.
