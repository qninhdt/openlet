# Service refactor verification

Decision: [accepted boundaries and scope](tmp-refactor-decision.md).

## Implementation

All four applications use the accepted feature/transport/Temporal boundaries. Shared destination clients and runtime capabilities are implemented in both Go and Python; generated contracts remain separate from handwritten code. SQL schemas were not changed. No commit or deployment was performed.

## Checks completed

| Check | Evidence |
|---|---|
| Native builds | `PATH=/usr/local/go/bin:$PATH pnpm build`: 6 successful Turbo tasks; Go binaries and Python wheels built |
| Formatting/lint/vet | `pnpm check`: 10 successful Turbo tasks plus script Ruff checks; touched Python streaming code checked again after its final fix |
| Unit tests | `pnpm test`: 8 successful Turbo tasks plus 22 script tests; ingest 100 passed, 11 parser cases intentionally run separately |
| Shared Python | Full current handwritten runtime/wire suite: 21 passed, including early archive cancellation |
| Workflow tests | `pnpm exec turbo run test:workflow --concurrency=1`: all 3 Go owner suites passed |
| Integration | `pnpm exec turbo run test:integration --concurrency=1`: all 7 tasks passed, including race-enabled letfs, authenticated native clients, Envoy isolation, real Temporal/MinIO/Qdrant/Python processing and replay |
| Parser/OCR | Current Docker image offline models, pinned local uv environment: 11 passed; scanned PDF OCR and format exporters included |
| Contract generation | `pnpm contracts:check` passed |
| E2E types | `pnpm check:e2e` passed |
| Filesystem history replay | Fresh integration histories replayed successfully in letfs |
| API E2E | `pnpm --dir e2e exec playwright test --project=api --no-deps`: 33 passed; recovery checked on a separate fresh stack |
| All-owner history replay | All 3 replay targets passed against 15 histories preserved from the final successful API run |
| Backup/restore E2E | `pnpm --dir e2e exec playwright test --project=recovery`: 1 passed on a fresh stack; metadata, exact bytes, revoked access and interrupted processing recovered |

Persistent local logs: `.local/refactor-verification/` (ignored). Histories and offline models are ignored artifacts.

## Regressions found and corrected

- Initial-workspace creation receipt lifetime was shorter than recoverable Account onboarding. Reserved actor/request identity now retains its initial mapping; ordinary public creation still uses expiring receipts.
- Account/Workspace Temporal starters now translate terminal application errors into native faults before returning to HTTP.
- Onboarding and Workspace filesystem-deletion polling continue as new after 100 pending polls/steps instead of growing history indefinitely.
- Archive stream adapters preserve native errors. Python archive iterator closure now explicitly cancels its nested RPC; a blocked real-server regression failed before the fix and passed afterward.
- Python processing had a second `VectorSpace` model with validation. Shared clients and indexing now use one native validated model; actual parse/enrich/index/replay passed afterward.
- Unknown Go RPC status codes now become native Internal errors; contract generation validates before publishing generated authorization outputs and reports a missing Go toolchain clearly.
- Integration fixtures resolve repository-relative resources correctly after the directory changes, and Go modules build with workspace mode disabled in Docker.

## System E2E transition

The first full run passed 25 of 34 tests. Three failures were obsolete test assumptions (public native gRPC and cross-service child workflows); six direct storage writes failed with HTTP 507 while host disk was nearly full. The fixtures now assert HTTP-only public ingress, service/actor authentication, owner-local filesystem workflow execution and independent recovery. Generated Go compilation cache was cleared before the final rerun; application quotas and storage validation were not reduced.

A full rerun stopped during recovery before its 33 dependent API tests could run: the recovery subprocess exceeded its external time budget while rebuilding images. With build caches ready, the final API run passed all 33 tests on a fresh stack; the independent recovery rerun then passed on another fresh stack (1 test, 2.0 minutes including setup). All 34 system scenarios passed across these two clean runs; no test was skipped or weakened.

An initial all-owner replay invocation used the integration-only history directory; Account/Workspace export histories through API E2E, so the final all-owner replay must use that E2E directory. A subsequent letfs-only invocation initially used the wrong working-directory-relative history path; the corrected absolute path passed.

## Material external limits

External Clerk/OpenRouter/live S3 credentials were not used. E2E uses controlled external-boundary fixtures with real application processes, storage, authorization and Temporal. Fresh histories validate the new workflow definitions; compatibility with histories from the previous greenfield architecture is not promised.

## Delivery state

All six acceptance criteria in the decision are satisfied within the recorded environment. Current source passed the required checks; all 34 system scenarios passed across two clean runs, and all three owners replayed fresh workflow histories. External-provider acceptance and compatibility with pre-refactor histories remain the explicit limits above.

## Follow-up unused-code audit

The follow-up audit found two unused tracked parser fixtures: `legacy.doc` and `note.txt`. No code, script, documentation or dynamic fixture enumeration referenced them; both were removed. All 13 exporter tests, including real parser/OCR cases, passed afterward.

Go Staticcheck U1000 passed across all application/shared modules with integration, workflow and replay tags. Python AST/reference checks found no unused application helpers; shared public client methods and SDK callbacks remain intentional. No stale imports to the removed application layers or old Python module paths were found. Full Go RTA analysis remains unverified: the installed deadcode binary was built with Go 1.26, and rebuilding its existing v0.48.0 with Go 1.27 passed loading but panicked inside the upstream RTA implementation. These checks do not prove every exported symbol is reachable.
