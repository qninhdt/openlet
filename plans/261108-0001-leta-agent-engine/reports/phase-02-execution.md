# Phase 02 execution checkpoint

Status: complete. Reconciled against current source after the repository-wide dependency upgrade. Continue Phase03; do not restore managed-account behavior.

## Completed implementation slices

- Account initial SQL now defines human-only users with mandatory unique Clerk ID, profile fields and timestamps. Store queries use users and EnsureUser. Profile has no type/owner_id; managed creation/storage is removed.
- Removed managed HTTP routes/handlers, AccountChanges/StartManaged/ApplyAccountChange and registrations. Human OnboardUser remains. Replay registration now covers the retained human Workflow only.
- Removed account self/owner graph publication, rebuild implementation and graph-dependent profile access. Account startup/config/health no longer requires SpiceDB. Native credential/method checks remain.
- Removed tests of deleted behavior. Replaced profile graph tests with actual PostgreSQL/HTTP tests proving current-human profile, no type/owner fields, unknown users rejected, removed managed/cross-user routes404 and another profile unchanged. Concurrent human creation/profile tests remain.
- Native human summaries are UserSummary/GetUserSummaries with users response; email lookup uses user_id. Updated Account server, Go/Python wrappers, Python UserClient export, Workspace summary alias, native allowlists, tests and generated bindings from canonical protobuf.
- Removed managed public OpenAPI paths and profile type/owner fields; current docs describe the removed behavior truthfully.

## Verified

- Account unit tests, workflow-tag tests and full integration target passed after the human-only removal; integration uses fresh owned PostgreSQL and actual gRPC/HTTP.
- After native DTO regeneration, Go destination client tests, Account and Workspace unit tests passed; shared Python30 nonintegration tests passed.
- Account native gRPC integration passed again with UserSummary/user_id, including exact caller restrictions, response fields, invalid requests, provider failure and cancellation.
- Generated contract check and Account gofmt/vet integration check passed. Plan validation and git diff --check passed.
- A first Python collection run caught a missed UserClient re-export; it was corrected and the full shared nonintegration suite passed. This is fixed, not an ignored failure.

## Completed identity and authorization integration

- Human onboarding/membership/invitation fields, initial Workspace SQL, HTTP contracts, E2E fixtures, DBML and operational callers now use UserID/user_id and accepted_user_id. Generic mutation ActorID/TargetID remain.
- Clerk metadata/template and gateway authority use openlet_user_id/x-openlet-user-id together. Managed routes and legacy identity are not accepted.
- Native Go/Python actors are the closed user/Leta pair. Exact service/method allowlists reject duplicate/both/legacy headers, invalid UUIDs and unauthorized Leta delegation. Leti has no subject or token.
- Canonical SpiceDB policy has human users, workspace.create_leta, Leta workspace/creator relations, creator membership-gated read/manage and scope home_of/viewer/editor access. No account definition/self/owner hierarchy remains.
- LetFS retains actor kind in actor-owned uploads, transfers, trash and idempotency keys. Same-UUID human/Leta authorization is covered by packages/go/authz/relationships_integration_test.go; native metadata admission is covered in Go/Python wire tests.
- Removed identity-only Account graph rebuild from recovery/bootstrap. General recovery functionality remains. Current docs/OpenAPI/generated bindings agree with human-only schemas.

## Final verification evidence

The later [dependency upgrade execution](../../reports/implementation-261108-dependency-upgrade.md) ran the unchanged identity implementation through all four Go unit/integration suites, all three Workflow suites, shared Python/wire/wheel tests, contract generation/check, build/check and all35 real API E2E tests. Full LetFS integration with race detection and fresh-history replay for Account/Workspace/LetFS passed. These checks include real disposable SQL/SpiceDB/native transport and human onboarding/member/grant/revoke paths. Source was re-inspected before reconciling this report; no identity implementation changed in the Phase03 continuation.

No existing development database was reset or migrated. The final engine acceptance, Leta resource provisioning/access operations and teardown remain in their owning later phases; completing identity migration does not claim those features exist.

## Environment and process state

Use export PATH="/usr/local/go/bin:$PATH" for Go/pnpm contract commands; Go1.27.3 is installed there but absent from this shell's initial PATH. Use uv/pnpm locks as checked in the worktree. No commit/push/deployment/live-provider call occurred. Test processes and fixtures own cleanup; no application server was started.

Phase01 compatibility evidence remains in [its execution report](phase-01-execution.md). Its Mirage FILE-parent, saver sync, Monty and Redis gates are already proven; phase08 still repeats filesystem behavior through real LetFS. The entire19-phase objective remains active.
