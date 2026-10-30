---
phase: 6
title: "Public Integration and Operations"
status: pending
priority: P1
effort: "5d"
dependencies: [5]
---

# Phase 6: Public Integration and Operations

<!-- Updated: Validation Session 1 - apply conditional/state recovery and retain only necessary creation/durable identity. -->

## Goal

Complete the public backend contract, cross-service verification, security/efficiency gates, and a tested coordinated backup-and-restore procedure.

## Files to Create / Modify

Paths below are relative to `/home/qninh/projects/openlet`; all are planned creations or extensions from prior phases.

- Modify: `contracts/{public,internal}/openapi.yaml`
- Modify: `services/{user,workspace,letfs}/` only for defects found by the final contract
- Modify: `deploy/{compose.yaml,envoy/,postgres/,temporal/}`
- Create: `scripts/{verify-contracts,system-e2e,backup,restore}.sh`
- Create: final system, security, recovery, and efficiency tests
- Modify: `.env.example`, `Makefile`, and controller-selected operator documentation

## End-to-End Data Flow

1. A user onboards through restricted Envoy, receives durable status, refreshes the token, and enters the initial workspace.
2. Workspace authorizes live membership and calls scoped letfs internal HTTP operations.
3. letfs resolves mounted ID/path locators, commits metadata/quota, and streams inline/object content without users/roles.
4. Durable operations return handles only after Temporal start and first-activity admission; same-key retry recovers status.
5. Operators pause admission/Schedules, drain writers, capture all databases plus objects, and restore one recovery point.

## Public Contract Completion

- [x] Cover profiles, onboarding/status, workspaces, members, ownership, invitations, operations, files, mounts, uploads, trash, copy, purge, and deletion.
- [x] Stabilize quota, conflict, revision, source-changed, not-live, deleting, invitation, owner, cross-filesystem, idempotency, and dependency errors.
- [x] Express byte counts/revisions as decimal strings and conditional mutations with quoted ETags plus expected target/parent IDs for path mutations.
- [x] Use keyset pagination with stable ordering and bounded page sizes.
- [x] Return 202 only for durable admission; timeout returns 503/`Retry-After` for same-key retry.
- [x] Keep integration as authenticated HTTP plus explicit DTO fixtures; no cross-service SDK/schema framework.
- [x] Ensure OpenAPI describes every implemented route and advertises no unimplemented route.

## Operational Requirements

- [x] Emit request, operation, workflow, retry, cleanup-age, query-count, and lock-wait signals without secrets/content.
- [x] Apply consistent gateway/downstream body, duration, concurrency, and streaming limits.
- [x] Verify graceful shutdown drains HTTP and workers within bounded deadlines.
- [x] Document external S3 and optional local test profile without requiring local storage.
- [x] Before backup reject all mutating public/internal HTTP (including direct writes), pause schedules, drain requests/transactions/activities/S3 writes and stop service workers plus Temporal Server writers.
- [x] Restore into isolation and verify application plus Temporal state before reopening admission.
- [x] Never call independent live DB dumps consistent or use volume deletion as rollback.

## Implementation Steps

1. Reconcile routes/DTOs against accepted contracts and remove accidental undocumented behavior.
2. Add contract validation and Go/Rust fixtures for IDs, timestamps, enums, nulls, counts, and errors.
3. Build E2E with test JWT/JWKS, controllable Clerk boundary, real DB/S3/Temporal, and Envoy.
4. Exercise onboarding, invite/join, roles, inline/object files, ID/path/mount, upload, trash, copy, purge, and deletion.
5. Add spoofing, foreign-resource, stale-revision, equal-revision path replacement, removed-member, Viewer-trash, and service-credential cases. Cover ambiguous short-mutation responses and stale retries after intervening trash/restore; preserve upload/copy/durable retry identity without generic response replay.
6. Assert bounded query/service-call counts for list, batch stat, members, path resolve, and status.
7. Add deterministic shutdown/restart cases for streams, workers, Temporal, PostgreSQL, and storage.
8. Select the deployment provider's exact object preservation/restore method as a prerequisite; implement guarded scripts for that method with explicit target checks, not an unverified generic S3 backup promise.
9. Perform an isolated restore drill and record recovery point, inventory, checks, and limitations.
10. Run the release gate sequentially by default and fix defects without weakening assertions.

## Final Test Groups

| Group | Required evidence |
|---|---|
| Unit | Openlet-owned policy, parsing, fingerprints, transitions, configuration |
| Integration | Real PostgreSQL, S3 API, Temporal, Envoy, internal HTTP, Clerk boundary |
| Workflow | Retry, replay, admission, cancellation, owner-local completion, restart, cleanup for seven types |
| System E2E | Critical user journeys through Envoy and all three services |

Tag relevant cases `security`, `concurrency`, `recovery`, `contract`, or `efficiency`. Do not add arbitrary coverage targets, a broad load suite, random stress loops, or sleep-based races.

## Planned Verification Commands

```bash
make verify
make test-integration
make test-workflow
make test-e2e
make backup-restore-drill
```

`make verify` should cover format, lint, compile/type checks, migrations, OpenAPI, and focused units; broader groups remain separately diagnosable. Add required credential-dependent `make test-clerk` and `make test-provider` release checks with explicit not-run reporting.

## Failure Modes and Mitigations

| Failure | Risk | Mitigation |
|---|---|---|
| Contracts drift from handlers | High | Route inventory plus request/response validation |
| Backup captures inconsistent state | High | Reject direct/durable mutating HTTP, pause schedules, drain storage/DB work and stop all service/Temporal writers |
| Restore targets wrong environment | High | Explicit target guardrails and isolated default |
| Logs expose content/credentials | High | Field allowlist and log-capture assertions |
| Final suite becomes flaky | Medium | Sequential default, barriers, lowest reliable layer |

## Rollback

- Roll back gateway/services together when contracts change.
- Pause new durable admission while preserving operations and histories for compatible rollback.
- Restore the last coordinated database/object point in isolation before promotion.
- Record purges after the recovery point as non-recoverable rather than claiming recreation.

## Success Criteria

- [x] Every public journey passes through Envoy against real services and infrastructure.
- [x] Security tests prove spoofing, foreign IDs, stale revisions, role bypass, and trash access fail closed.
- [x] Contract/efficiency tests prove stable DTOs/errors and bounded query/service-call counts.
- [x] All seven workflow types have focused SDK checks; representative real retry/restart/recovery proves the shared risk boundaries and caller-bound status.
- [x] Isolated restore recreates service data, Temporal state, and referenced objects without volume deletion.


## External release prerequisites

Local acceptance and real Clerk development/Cloudflare R2 smoke checks passed. The external provider recovery procedure remains open. See [external configuration evidence](../reports/implementation-261029-1822-external-configuration.md).

- [x] Run `make test-clerk` with an onboarded real Clerk development session and refreshed claim.
- [x] Run `make test-provider` against the chosen HTTPS/private S3 bucket; verify public-access denial and incomplete multipart cleanup policy.
- [ ] Establish and drill the R2 object preservation/retention and coordinated database/object restore procedure.

See [final local evidence](../reports/implementation-261029-1737-local-acceptance.md).
