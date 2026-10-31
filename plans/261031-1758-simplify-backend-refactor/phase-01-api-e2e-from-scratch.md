---
phase: 1
title: "Rewrite API E2E from scratch"
status: completed
priority: P1
effort: "4–6 days"
dependencies: []
---

# Phase 1: Rewrite API E2E from scratch

## Goal and context

Delete the entire existing system E2E implementation and write real TypeScript/Playwright API tests before backend refactoring. Read [current testing guidance](../../docs/testing.md) and the [target testing architecture](../261031-1738-refactor-three-notes/inputs/openlet-architecture-decisions.md) for behavior and boundaries, never as permission to reuse old E2E code.

Existing `tests/e2e/` includes Go tests, its module/Dockerfile, and `cmd/issuer/` containing JWT/JWKS, Clerk/model doubles, and an S3 proxy. `deploy/compose.test.yaml` depends on that issuer/tester. All are replacement scope.

## File inventory

| Action | Files or group | Size | Test impact |
|--------|----------------|------|-------------|
| Delete | ALL `tests/e2e/**` | Entire tree | No old tests, issuer, fixture, helpers, recorder, module, or Dockerfile |
| Delete | `scripts/verify-foundation.sh`, `test-storage-browser.py`, `test-clerk.py`, `backup-restore-drill.sh`, `verify-contracts.py` | Entire files | Rewrite useful checks in their proper test level |
| Create | `e2e/package.json`, `playwright.config.ts`, minimal root pnpm manifest/lock/workspace | Small | One Playwright project: api |
| Create | `e2e/tests/api/*.spec.ts`, `e2e/fixtures/`, `e2e/setup/` | Medium/large | Entirely new tests, data, boundary servers, lifecycle |
| Create | `infra/compose/e2e.yaml` and required E2E configuration | Medium | Uses current app Dockerfiles until phase 2 |
| Modify/delete | Makefile E2E entries, old test Compose, contracts, docs setup/testing | Medium | Remove every old harness entrypoint |

Paths under the new layout are planned files, not claims that they already exist. Do not copy/move old E2E source, binary fixtures, or helper implementations. Native unit/integration tests and parser regression corpora are assessed separately.

## Environment design

1. Run Playwright on the host. Setup/teardown invokes Docker Compose directly using Node process APIs with argument arrays. No Docker socket inside a tester container, shell runner, or marker-file protocol.
2. Give E2E its own fixed Compose project, credentials, volumes, and state. Acquire an atomic exclusive OS lock for that project before any Compose mutation; record/verify the owning process, worktree and run identity, and fail immediately if another run owns it. Kernel-managed lock release avoids a stale PID-file protocol. Cleanup verifies ownership and expected project/volume labels before teardown. Each run starts clean; never read/reset development `.local` or development volumes. Back up before resetting existing database state. For a genuinely new database, verify that no prior database exists.
3. Run real gateway, apps/workers, PostgreSQL, persistent Temporal, S3-compatible storage, Qdrant, and parser. Readiness has deadlines; a running container is insufficient.
4. Write new test servers only for external Clerk/model boundaries: real signed JWT/JWKS, realistic metadata-merge behavior and schema-valid model responses. Storage fault injection proxies real S3 rather than implementing fake storage. Stubbed model responses do not prove AI quality.
5. Own fixture servers within Playwright lifecycle. Choose host/container-reachable addresses and a presigned endpoint reachable by the host. No production test-control endpoints or development credentials.
6. Start with `workers: 1`, `fullyParallel: false`. Give each test distinct identities/data; reset barriers and injected failures in finally blocks. Poll observable outcomes with deadlines, never fixed sleeps.
7. Declare deterministic E2E ports distinct from development in one config source. Check ownership before startup; fail clearly on collision, never increment ports or kill another session's process. Tear down every owned process/container after success, failure, or partial setup.
8. Collect logs and failure artifacts before teardown. Redact bearer/invite tokens, signed URLs, credentials, and sensitive payloads. Avoid wholesale response recording.

## Steps and execution checklist

- [x] Inspect old coverage to identify business guarantees. Write new test descriptions from requirements; do not translate old test algorithms. Put SQL locking/query-count/exhaustive validation in service integration.
- [x] Establish the target OpenAPI contract from the notes and phases 4–6: routes, inputs, RFC9457 errors, ETags, receipts, async monitors. Do not create a legacy/target compatibility adapter.
- [x] Delete the entire old E2E tree and dependent commands. Write fresh Playwright configuration, lifecycle fixtures, boundary servers, and test documents.
- [x] Start the real stack using current migrations. Prove the new harness with readiness/authentication scenarios that the current implementation already supports. Do not implement the backend refactor before writing its tests.
- [x] Write actual target-contract tests for the matrix below, including assertions, before production changes. Run them and capture concrete expected failures; no skip/fixme/TODO assertions, fake backend, or relaxed expectations.
- [x] Separate the passing infrastructure baseline from known target-contract failures in reporting. A focused baseline selection is allowed; the full target suite must still fail until the owning phases implement it. Do not label a baseline-only run as full acceptance.
- [x] Expose the planned native command `pnpm --dir e2e exec playwright test --project=api`; use Playwright filtering for journeys. Delete old TEST selectors and custom orchestration.
- [x] Verify cleanup after a setup failure and a failed test. Update only docs describing implemented tooling.

## New scenario matrix

| Risk | Journey and independently observable outcome | Owning phase |
|------|---------------------------------------------|--------------|
| Critical | Real Envoy/JWKS auth/readiness, rate limiting, spoofed/duplicate trusted headers, internal route isolation | 1; recheck 3 |
| Critical | Repeated onboarding, Clerk failure/recovery, fresh JWT, one identity/workspace, unrelated metadata preserved | 4 |
| High | Invitation one-time token/roles/ownership and cross-workspace isolation | 4 |
| Critical | Exact inline bytes, strict create retry/conflict, ETag and move/rename guards | 5 |
| Critical | Direct single/multipart upload, lost completion acknowledgment, stale replace, exact download/Range and quota | 5 |
| High | Copy source change/destination conflict/restart retains committed work without duplication; trash/restore/purge | 5 |
| High | ZIP through gateway, empty directories, independent ZIP reader validates paths/bytes, source error/disconnect | 5 |
| Critical | Real parse → leaf/README enrichment → publication → search with new document fixtures; same-key manual reprocessing admits one generation | 6 |
| Critical | Real worker crash/restart, lost response, exhausted retries, admitted workspace deletion and scoped monitors | 4–6 |
| High | New backup/restore automation restores isolated metadata/bytes and resumes real workflows | 6 |
| Medium | Explicit opt-in sandbox Clerk/selected-storage-provider smoke; missing configuration is NOT RUN | 6 |

Write fresh small document fixtures that exercise the real parser. Failure injection uses a barrier or dropped acknowledgment at the actual side-effect boundary, not random restarts. No browser suite until a real frontend exists; do not claim browser CORS proof from API requests.

## Test ownership and diagnostic boundaries

- Playwright owns complete public API journeys and environment lifecycle. Compose owns containers/network/storage. Native app tests own SQL locks, query-count invariants, protocol validation, and workflow decision tests. No root shared Go module replaces the deleted E2E implementation.
- Use APIRequestContext through the gateway for public assertions. Access test controls only for deliberate external-boundary failure injection and lifecycle control; control endpoints are never application behavior under test.
- Check requested selectors actually execute tests. An unknown/empty selection is an error, not a successful no-op. Native Playwright list/report facilities are sufficient; do not create a custom recorder or selector framework.
- Capture the observable async outcome and correlation information with a bounded deadline. An accepted 202 or healthy worker alone does not prove publication, indexing, or durable completion.
- Never reuse a previously issued bootstrap JWT as proof that onboarding metadata reached a refreshed session. Mint a new token using the test issuer's current Clerk metadata contract.
- Temporary state generated by a real test is owned test data; do not create temporary executable scripts to prepare it. Use runner fixtures/native tools and clean owned files through the test lifecycle.

## Dependency handoff

Phase 2 updates this new suite's build/config paths without changing its implementation into a second harness. Phases 4–6 make the already written target tests green. Update an assertion only when the accepted business contract changes, never simply to match a failing implementation. Keep one current OpenAPI contract and one API suite throughout the refactor.

## Gate, risks, and recovery

- [x] New readiness/auth baseline passes against clean real infrastructure; target tests have recorded pre-implementation failures.
- [x] Zero old E2E code/files or entrypoints remain, including the issuer and test Dockerfile.
- [x] Full-suite failures are explicit and assigned to phases; no false-green skips or mock-only success.
- [x] Process/environment cleanup is owner-safe, including partial initialization.

If real infrastructure cannot start, repair setup first. Revert code changes for recovery; do not restore legacy harnesses in the final implementation or reset developer databases to repair tests. Continue to [phase 2](./phase-02-monorepo-infra-scripts.md).

## Execution evidence

The latest clean real-stack run executed all 26 target API tests: four gateway tests passed; 22 target journeys failed at the unimplemented onboarding admission (403 versus 202). All tests have real assertions; none are skipped or adapted to the old API. Target implementation and full acceptance belong to phases 4–6.

Environment lifecycle passed 2/2 after the PostgreSQL TCP-readiness fix, including occupied-port refusal and SIGTERM during actual startup. The permanent recovery CLI passed its separate real-infrastructure test: an isolated restore recovered a database value and exact S3 bytes, remained fenced before explicit resume, and rejected a corrupted dump. Repeated Goose jobs performed no additional migrations. Cleanup removed the owned projects.

The public contract validator and TypeScript pass. The opt-in Clerk test is authored against Clerk's official session-token endpoint but has NOT RUN without explicit sandbox credentials. Selected-provider storage verification remains a separate native opt-in. No developer database was reset. Processing-source signing still requires the phase-5 internal endpoint fix.
