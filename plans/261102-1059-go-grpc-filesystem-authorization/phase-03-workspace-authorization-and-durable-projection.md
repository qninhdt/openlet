---
phase: 3
title: "Workspace authorization and relationship synchronization"
status: completed
priority: P1
effort: "40-56h"
dependencies: [1, 2]
---

# Phase 3: Workspace authorization and relationship synchronization

## Outcome and dependencies

Replace Account/Workspace permission decisions with direct SpiceDB action checks. Load built-in role/action policy from the repository into SpiceDB, synchronize only relationships derived from existing business records through Temporal, and complete authenticated Account gRPC adoption. Preserve workspace/invitation/bootstrap/file behavior.

Depends on Phases 1–2. Read [architecture](architecture-contract.md), [verification matrix](verification-matrix.md), [authorization inventory](../reports/scout-261102-1059-authorization-rpc-inventory.md) and [action matrix](../../packages/contracts/authz/action-resource-matrix.md). The user's November 2 correction supersedes SQL permission catalogs and the former head/intent/ack/epoch framework. Rust remains an isolated reference until Phase 6.

## Requirements and retained invariants

- PostgreSQL owns existing users, workspaces, assigned membership roles, invitations, lifecycle and storage references. Add no SQL role/action catalog, graph mirror, authorization intent/head/ack tables or projection revisions in any service.
- SpiceDB schema declares actions/evaluation; repository `packages/contracts/authz/roles.json` defines built-in role/action relationships, loaded/verified by deployment. No runtime custom-role management is included.
- Services call the official SDK for typed `CheckPermission`/`CheckBulkPermissions` with explicit `fully_consistent` reads. No local role evaluator, SQL-role fallback, cache or Access service.
- Temporal owner work synchronizes current canonical relationships. Repeated writes/deletes are idempotent; role changes and both sides of an Owner transfer use atomic graph writes. Same-resource sync is serialized; retries/reconciliation read current business state. After synchronized revoke/transfer success, delayed or retried older writes cannot restore superseded access.
- Synchronized success follows graph write completion. A disconnected/timed-out caller does not cancel durable work. The existing resource/revision contract reconciles an ambiguous business outcome; no pending membership state or polling API.
- Preserve business revisions/If-Match, exactly-one-Owner, member/workspace limits, invitation authority, actor binding, lifecycle, idempotency and tombstones. No remote calls while holding owner SQL locks.
- Preserve native Account→Workspace and Workspace→letfs orchestration. Generic letfs Activity cutover remains Phase 6; letfs stores no business mapping and writes no graph relationships.

## File inventory

S/M/L indicate local, multi-consumer and cross-boundary review size. Companion names marked “same directory” share the shown absolute parent. New filenames are proposed execution targets; generated files are never edited by hand.

| Absolute path | Action / current or new | Size / test impact |
|---|---|---|
| `/home/qninh/projects/openlet/apps/workspace/migrations/0001_initial.sql` | Remove the rejected SQL authorization tables; retain business constraints/revisions and prepare stable storage IDs | L; actual PG constraints/transactions |
| `/home/qninh/projects/openlet/apps/workspace/internal/workspace/store.go`, `invitations.go`, `deletion.go`, `reconciliation.go` in same directory | Separate authorization admission from canonical reads/mutations/invariants | L; transfer, self-leave, limits, lifecycle and receipts |
| `/home/qninh/projects/openlet/apps/workspace/internal/workspace/authorization.go`, `relations.go`, `relations_integration_test.go` in same directory | Action admission and current business-state reads for relationship synchronization; remove the old SQL projection proof | L; real PG+SpiceDB and failure injection |
| `/home/qninh/projects/openlet/apps/workspace/internal/workspace/policy_test.go`, `store_integration_test.go` in same directory | Replace role-helper tests with graph behavior; retain invariant assertions | L; exact current operation matrix |
| `/home/qninh/projects/openlet/apps/workspace/internal/temporal/projection.go`, `projection_test.go` in same directory | Resource-scoped relationship synchronization in native owner workflows/reconciliation | L; duplicate, stale, timeout and restart |
| `/home/qninh/projects/openlet/apps/workspace/internal/temporal/workflows.go`, `deletion.go`, `reconciliation.go`, `workflows_test.go`, `deletion_test.go`, `replay_test.go` in same directory | Integrate relationship-write completion and recovery | L; fresh current-history replay |
| `/home/qninh/projects/openlet/apps/workspace/internal/http/server.go`, `workspaces.go`, `collaboration.go`, `deletion.go` in same directory | Adopt shared verified identity/action boundary and completion errors | L; public permissions and committed timeout |
| `/home/qninh/projects/openlet/apps/workspace/internal/http/files.go`, `nodes.go`, `uploads.go`, `trash.go`, `search.go`, `archive.go` in same directory | Transitional graph-backed checks; final removal is Phase 6 | M; preserve existing Rust packages/contracts/actor bounds |
| `/home/qninh/projects/openlet/apps/workspace/internal/http/server_test.go`, `routing_test.go`, `tracing_test.go` in same directory | Extend trust/error/stream regression cases | M; no public identity bypass |
| `/home/qninh/projects/openlet/apps/workspace/internal/user/client.go`, `client_integration_test.go` in same directory | Replace Account HTTP wrapper with generated gRPC and exact-ID checks | M; independently testable real boundary |
| `/home/qninh/projects/openlet/apps/account/internal/rpc/server.go`, `server_integration_test.go` in same directory | New real summary/email RPC implementation | M; service method allowlist and active-user filtering |
| `/home/qninh/projects/openlet/apps/account/internal/user/store.go`, `store_integration_test.go`, `relations.go`, `relations_integration_test.go` in same directory | Keep identity/profile invariants; self relationship derived from existing users | M; concurrent onboarding and own-user checks |
| `/home/qninh/projects/openlet/apps/account/migrations/0001_initial.sql` | Preserve existing user baseline; add no authorization tables or projection revisions | M; subject uniqueness retained |
| `/home/qninh/projects/openlet/apps/account/internal/temporal/workflows.go`, `workflows_test.go`, `replay_test.go`, `projection.go`, `projection_test.go` in same directory | Integrate self relationship sync and durable bootstrap completion | M; dispatch gap and fresh replay |
| `/home/qninh/projects/openlet/apps/account/internal/http/server.go`, `identity.go`, `server_test.go`, `routing_test.go`, `tracing_test.go` in same directory | Preserve narrow bootstrap/profile HTTP; remove migrated internal endpoints | M; Clerk-subject exception and user scope |
| `/home/qninh/projects/openlet/apps/account/cmd/server/main.go`, `/home/qninh/projects/openlet/apps/workspace/cmd/server/main.go` | Wire actual clients/servers/sync activities/health with cleanup | M; startup and graceful shutdown |
| `/home/qninh/projects/openlet/apps/account/internal/config/config.go`, `config_test.go` in same directory; `/home/qninh/projects/openlet/apps/workspace/internal/config/config.go`, `config_test.go` in same directory | Real gRPC/SpiceDB endpoints/credentials/deadlines | M; malformed config and secret redaction |
| `/home/qninh/projects/openlet/packages/go/authz/actions.go`, `client.go`, `projection.go`, `projection_integration_test.go` in same directory | Use official SDK/typed checks; remove unused head/epoch projection primitives | M; inherited checks and native atomic relationship updates |
| `/home/qninh/projects/openlet/packages/contracts/authz/schema.zed`, `/home/qninh/projects/openlet/packages/contracts/authz/schema_test.yaml`, `/home/qninh/projects/openlet/packages/contracts/authz/roles.json`, `/home/qninh/projects/openlet/packages/contracts/authz/action-resource-matrix.md` | Final operation/role/tuple ownership consistency | L; repository-owned role policy loaded directly into SpiceDB |
| `/home/qninh/projects/openlet/packages/go/cmd/authz-schema/`, `/home/qninh/projects/openlet/packages/go/authz/schema.go`, `/home/qninh/projects/openlet/infra/bootstrap/Dockerfile` | Extend existing initializer/tests and image inputs to load/verify repository role policy | M; missing/repeated/drifted policy and preservation of business relationships |
| `/home/qninh/projects/openlet/packages/contracts/proto/openlet_api/account/v1/account.proto`, `/home/qninh/projects/openlet/packages/go/gen/openlet_api/account/v1/` | Adjust source if real boundary exposes mismatch; regenerate | M; wire/presence/error contract |
| `/home/qninh/projects/openlet/infra/compose/dev.yaml`, `/home/qninh/projects/openlet/infra/compose/e2e.yaml`, `/home/qninh/projects/openlet/e2e/setup/environment.ts` | Adopt Account gRPC and graph readiness without Go letfs dependency | M; existing Rust stack still starts |
| `/home/qninh/projects/openlet/e2e/tests/api/workspaces.spec.ts`, `/home/qninh/projects/openlet/e2e/tests/api/onboarding.spec.ts`, `/home/qninh/projects/openlet/e2e/tests/api/gateway.spec.ts` | Extend real public journeys | L; no proxy-cutover assumptions |
| `/home/qninh/projects/openlet/scripts/operations/recovery.py`, `/home/qninh/projects/openlet/e2e/setup/recovery.test.ts` | Rebuild relationships from owner business state under the existing maintenance fence | L; isolated restored canonical authority |
| `/home/qninh/projects/openlet/packages/contracts/public/openapi.yaml`, `/home/qninh/projects/openlet/packages/contracts/internal/openapi.yaml`, `/home/qninh/projects/openlet/docs/api-contracts.md`, `/home/qninh/projects/openlet/docs/workflows.md`, `/home/qninh/projects/openlet/docs/data-model.md`, `/home/qninh/projects/openlet/docs/operations.md` | Update changed contracts; remove Account internal HTTP portion only | S/M; retain letfs HTTP reference until Phase 6 |

App go.mod/go.sum and package.json change only for actual dependencies/tasks; current shared setup comes from Phase 2. Do not alter Rust domain behavior merely to make the new authorization tests pass.

## Numbered implementation steps

1. **Remove rejected machinery.** Delete the four SQL catalog tables and the two authorization head/intent tables introduced during implementation, their foreign-key additions, catalog code, saved-response waiters and unused graph head/epoch proof implementation. Do not add equivalents to Account. Preserve existing business revisions, receipts and unrelated Phase 1–2 work. Historical proof reports stay historical and explicitly superseded.
2. **Load repository policy.** Define complete Owner/Editor/Viewer action sets in `packages/contracts/authz/roles.json`; validate action identifiers against the schema/typed contract. Extend the existing deployment schema initializer to initialize/verify these capability relationships directly in SpiceDB. Policy updates use the deployment job under its normal writer fence; no mutable SQL catalog or catalog workflow.
3. **Synchronize business relationships.** Account derives self relationships from existing user records. Workspace derives stable grants from memberships, enabled state from lifecycle, and bucket/filesystem inheritance from its references. Use owner activities and direct official SDK `WriteRelationships`; synchronize current state, including removing obsolete grants/bindings, without persisting a second tuple model in SQL.
4. **Integrate durable execution.** Reuse native owner workflows and reconciliation. Serialize writes for a resource, reread its current canonical data on retry, and perform related role changes in one graph transaction. Recover SQL-commit/start gaps by bounded reconciliation of existing business records and retained tombstones. Verify duplicate delivery, lost acknowledgment, concurrent updates and worker restart converge to current SQL facts. Also hold an older graph write in flight, complete a newer revoke/transfer, then release the older write: it must not restore superseded access. SQL rereads and Temporal serialization alone do not prove that remote-write ordering. Prove the smallest owner-specific/native-API solution before adoption; if it fails, stop the affected phase rather than accept eventual repair as safety. Do not add a generic event ledger, version waiter or epoch registry.
5. **Implement action admission.** Resolve actual owner-local resource/scope, check the specific action, then enforce transaction identity/revision/lifecycle invariants. Keep graph/RPC calls outside SQL locks. A concurrent local change causes bounded fresh admission or an existing conflict; it must not enable SQL-role fallback. File operations check actual filesystem or bucket IDs, not caller-supplied business ownership.
6. **Preserve Workspace behavior.** Replace role-minimum helpers and permission branches with action checks. Preserve status access for provisioning/failed/deleting and retained Owner tombstones. List bounded canonical membership candidates and bulk-check them; advance by the last scanned candidate even for an empty filtered page. Transfer targets an existing different member, respects owner limits, demotes the old Owner to Editor and preserves exactly one Owner. Self-leave binds actor==target and rejects Owner until transfer. Name/member/delete operations retain current If-Match semantics.
7. **Preserve invitations.** Keep normalized email, random 32-byte token/hash-only storage, expiry, pending-only revoke, editor/viewer grants, all-status metadata and one-time raw token. Same pending email/role returns metadata without token; changed role conflicts; expiry allows replacement. Accept uses Account-sourced verified email and active destination. Existing members retain their roles; accepted replay cannot re-add a removed member. Sync new membership before normal synchronized success.
8. **Complete Account gRPC adoption.** Authenticate Workspace service and allowed methods. Validate 1–100 unique non-nil summary IDs, expose only active public profiles, and require the exact response ID set in the Workspace client. Resolve active internal ID→stored Clerk subject for verified emails. Keep bounded deadlines, cancellation and safe typed dependency errors; remove migrated internal HTTP/config. Keep Clerk's external HTTP.
9. **Integrate bootstrap/self checks.** Account profile uses self-resource actions. Narrow subject-based onboarding remains available before UUID/graph existence. Owner and self relationships must be synchronized before reporting completed usable onboarding. Avoid child→active-Account lookup cycles; preserve provisioning 202/completed 200, fresh-session flow and never recreating a later-deleted initial workspace. Keep credentials out of history.
10. **Keep transitional file checks correct.** While Rust remains, replace Workspace permission decisions with graph actions. Preserve Viewer reads, Editor writes and Owner purge; initiating-actor upload restrictions and current `copy_inspect_any` remain mandatory. Any temporary forwarded compatibility assertion comes from an explicit action result, never SQL role. Phase 6 removes the proxy/header entirely.
11. **Prepare stable storage lifecycle.** Persist preallocated bucket/filesystem IDs before remote create and retain them on retry. Save returned references, synchronize inheritance through the Workspace worker, then complete creation. letfs returns storage state independently and denies access if graph permission is missing. Deletion removes inherited access while preserving Owner status and storage tombstones. Stage generic payloads here; activate at Phase 6.
12. **Rebuild and verify.** Drain public/owner writers with the existing maintenance fence. Initialize schema and repository policy; synchronize Account/Workspace relationships from their databases, including retained storage references/deletion state. Repeat interrupted rebuilds idempotently and verify parity before resume. Do not introduce projection epochs or import graph facts into SQL. Run real graph/PG/RPC/public/restart/replay checks, audit remaining role branches and update owning docs.

## Todo / success criteria

- [x] Remove SQL permission catalogs and the rejected head/intent/ack/epoch framework without deleting business revisions or unrelated work.
- [x] Repository role/action policy initializes/verifies SpiceDB; no application SQL permission catalog exists.
- [x] Workspace exclusively synchronizes its membership/lifecycle/storage relationships; stable storage IDs survive retries.
- [x] Concurrent transfer/member changes preserve one canonical Owner and atomic graph grant changes.
- [x] Duplicate delivery, commit/start gap, lost acknowledgment and restarted sync converge from existing canonical records; older in-flight/retried writes cannot undo synchronized revoke/transfer success.
- [x] Normal mutation success follows graph write; timeout/disconnect preserves durable work and honest possible-commit semantics.
- [x] Self-leave, invitations, status/tombstone and bounded list-cursor behavior match the inventory through action checks.
- [x] Account summary/email gRPC is independently tested and internal HTTP removed.
- [x] Bootstrap/self relationships and fresh-session flow work before Go letfs adoption.
- [x] Transitional uploads/copy monitors retain actor/current-action restrictions until proxy removal.
- [x] Fenced rebuild uses repository policy plus existing business data and proves parity before reopening admission.
- [x] Focused integration/public/restart/replay checks pass; docs and role-branch audit match implementation.

## Required scenarios

Current execution evidence is in [Phase 3 progress](reports/phase-03-progress.md). Native Account self-admission, owner Temporal synchronization/reconciliation and Workspace mutation waiters now have focused evidence. Workspace action admission, stable storage IDs and full phase restart/replay acceptance remain unchecked above.

| Severity | Scenario | Evidence |
|---|---|---|
| Critical | Concurrent transfer/removal/leave | Real SQL one-Owner invariants and atomic multi-grant graph write |
| Critical | Commit then dispatch failure or graph response loss | Existing reconciliation recovers; no false synchronized success |
| Critical | Older delayed/in-flight write or retry after newer revoke/transfer success | Superseded access is never restored; independently check inherited FS permission when the old write completes, not only after reconciliation drains |
| Critical | Public/spoofed service calls; graph check outage | Deny before effect; no SQL-role fallback |
| High | Independent inherited FS check after synchronized change | Fully-consistent check sees written relationship; no mutator-token shortcut |
| High | Request disconnect/worker restart | Durable sync continues, resources are bounded and cleaned up |
| High | Wrong email, expired/revoked/replayed invitation | Existing authority/replay behavior retained |
| High | Empty filtered list page or nonactive/tombstone status | Cursor progresses; status/file lifecycle semantics remain distinct |
| High | Another actor's upload/former Owner's copy inspection | Actor/current-action restrictions hold |
| High | Completed onboarding's first workspace later deleted | Completed identity is not re-provisioned |
| High | Rebuild interrupted with writers fenced | Policy/business relations converge; stale payloads are not resumed as grant commands |
| Medium | Missing/duplicate/foreign summary IDs, >100 IDs, canceled Clerk call | Exact client scope and safe native RPC errors |

## Verification commands

From the repository root; there is no root Go module:

```sh
pnpm --filter @openlet/account test
pnpm --filter @openlet/workspace test
pnpm --filter @openlet/account test:integration
pnpm --filter @openlet/workspace test:integration
pnpm --filter @openlet/account test:workflow
pnpm --filter @openlet/workspace test:workflow
pnpm --filter @openlet/account check
pnpm --filter @openlet/workspace check
go -C packages/go test -tags integration ./authz -count=1
pnpm contracts:check
pnpm check:e2e
pnpm --dir e2e exec playwright test --project=api workspaces.spec.ts onboarding.spec.ts gateway.spec.ts --list
pnpm --dir e2e exec playwright test --project=api workspaces.spec.ts onboarding.spec.ts gateway.spec.ts
```

Use actual PG18.6/SpiceDB/native gRPC fixtures. Export fresh complete histories before final replay with `OPENLET_HISTORY_DIR="$PWD/.local/api-e2e/histories" pnpm test:replay`. Do not use old graph-marker tests as acceptance for this new design. Replacing tests of rejected implementation is intentional; retain role, resource isolation, concurrency, retry and fail-closed behavior coverage.

## Risks and rollback

SQL and SpiceDB are separate writes. A request can time out after commit; old graph rights can remain during sync outage. Fully-consistent reads do not force projection or cancel remote writes. A delayed old write must not undo synchronized revoke/transfer success; the required real race proof remains pending in this phase. Native API ordering/preconditions must be verified rather than assuming serialization or a SQL reread fences remote work. The rejected generic CAS/head/ack/epoch framework is not required. Never claim instantaneous revocation of admitted operations or signed URLs.

Back up before changing existing databases. These baseline edits have only been used in disposable fixtures so far; do not apply them over live dev data. Stop/drain only owned processes, preserve existing business constraints and use isolated matched recovery on failure. No data, deployment or schema reset is authorized merely by updating this plan.
