---
phase: 5
title: "Go workflows, ingest, search, and ZIP"
status: completed
priority: P1
effort: "56-88h"
dependencies: [4]
---

# Phase 5: Go workflows, ingest, search, and ZIP

## Goal

Complete Go parity for all durable letfs workflows and maintenance, processing/enrichment/indexing/search, backfill, and request-owned ZIP streaming. Prepare the target Python activity path in the existing `apps/letfs-processing` app using generated gRPC from `packages/python` while preserving signed S3/provider protocols. Keep the old worker entrypoints/tree rebuildable until Phase 6 atomically activates the target path, renames the app and removes legacy application HTTP. Keep the coordinated Compose, Workspace client, Envoy, and public traffic switch for phase 6.

## Context and evidence

- Current worker registrations include copy, process-file, purge, filesystem deletion, storage maintenance, and six Workspace provisioning activities (`apps/letfs/src/main.rs:77`; parity report, "Temporal port"). Use explicit final wire names consistently; fresh histories permit approved queue/name changes, while native cross-owner contracts must agree.
- Copy exposes a `progress` query and retains bounded state/partial results (`apps/letfs/src/temporal/copy_workflow.rs:95`). Purge/deletion run at most 200 batches then Continue-As-New with cancellation-independent activities (`apps/letfs/src/temporal/lifecycle_workflow.rs:79`).
- ProcessFile uses CPU and I/O task queues, 7200s schedule-to-close, 1800s start-to-close, 30s heartbeat, three attempts, and indexing after all selected earlier stages succeed (`apps/letfs/src/temporal/process_file_workflow.rs:7`, `apps/letfs/src/temporal/process_file_workflow.rs:30`).
- Maintenance is scheduled every 300s with overlap Skip and bounded retries (`apps/letfs/src/temporal/lifecycle_workflow.rs:143`, `apps/letfs/src/temporal/lifecycle_workflow.rs:174`).
- Processing fences generation, source identity, and accepted attempt (`apps/letfs/src/fs/processing.rs:70`, `apps/letfs/src/fs/processing.rs:120`) and atomically validates complete output manifests (`apps/letfs/src/fs/processing.rs:232`).
- The Python worker currently uses authenticated application HTTP separately from unauthenticated signed storage HTTP (`apps/letfs-processing/src/openlet_processor/activity.py:137`). Only the first channel becomes gRPC.
- Semantic search binds cursors to scope/config and hydrates Qdrant candidates against current PostgreSQL facts (`apps/letfs/src/fs/search.rs:99`, `apps/letfs/src/fs/search.rs:256`). Preserve the existing bounded lifecycle lock around destructive Qdrant cleanup (`apps/letfs/src/fs/indexing.rs:133`); this migration does not require redesigning its locking.
- ZIP is request-owned, not a workflow. Its HTTP response is `application/zip`, private/no-store, `nosniff`, and a safe attachment filename (`apps/letfs/src/http/archive.rs:25`).

## Key insights

1. Fresh Go histories are allowed, but workflow semantics are not optional. Preserve IDs, names, timeouts, retry classification, task queues, queries, Continue-As-New state, cancellation, and partial-result recovery.
2. Generated protobuf contracts are the sole application RPC model. Do not hand-edit generated Python imports or maintain parallel manual DTOs.
3. Go search uses the official `github.com/OpenRouterTeam/go-sdk` for embeddings and rerank, pinned in `apps/letfs/go.mod`; do not duplicate its authentication, wire models, JSON serialization/deserialization or provider-error decoding. Preserve finite deadlines/cancellation, tracing, sanitized public errors and search-specific vector/ranking validation; disable implicit SDK retries for interactive queries. Python continues to speak HTTP to signed S3 URLs, Qdrant, OpenRouter, and supported third-party protocols. Generated gRPC replaces only letfs application metadata/control and inline-byte RPCs.
4. Search queries use short SQL snapshots around validation/hydration and network calls outside transactions, followed by current-fact revalidation where publication/readiness can change. Destructive Qdrant cleanup retains its existing bounded lifecycle lock.
5. ZIP owns its semaphore permit, source readers, stream, cancellation, deadline, and cleanup for the request lifetime. It creates no archive entity, receipt, workflow, object, or quota charge.

## Data flow

1. A file mutation commits a processing generation and durable dispatch fact in PostgreSQL; the Go owner starts or reconciles the explicit Temporal workflow identity after commit.
2. `ProcessFile` schedules `process_file` on the CPU queue when needed, `enrich_file` on I/O when needed, and `index_file` on I/O after selected parse/enrichment stages succeed; failures propagate before indexing, using only bounded IDs/generation/vector-space metadata in history.
3. Target Python activity fixtures authenticate to Go letfs through generated gRPC using service/job identity. They obtain metadata, signed descriptors, upload sessions, inline bytes, and completion/failure acknowledgments.
4. Python transfers object bytes directly over signed S3 HTTP and talks to Qdrant/OpenRouter over their native protocols; credentials and file bytes never enter Temporal history.
5. Search embeds/queries outside SQL transactions, then hydrates and revalidates candidates against live/current/ready PostgreSQL facts before grouping/reranking. Rerank failure alone degrades; embedding/Qdrant/current-fact failures do not silently become empty success.
6. ZIP preflights bounded selected identities/revisions and revalidates them while streaming inline/S3 bytes. Cancellation and deadlines are request-owned; no source-tree snapshot is promised.

## Requirements

- Implement `CopyNode`, `ProcessFile`, `PurgeTrash`, `DeleteFilesystem`, `StorageMaintenance`, lifecycle/copy activities, and generic bucket/filesystem provisioning activities with explicit wire names. Replace legacy Workspace-specific contracts at cutover; target letfs accepts no workspace/conversation identifiers.
- Preserve CopyNode's one-hour execution deadline, bounded frames/pending selection, deterministic UUIDv8 destinations, high-water/keyset traversal, 100-step Continue-As-New, progress query, partial success, candidate-before-I/O evidence, and no resurrection/recharge on retry.
- Preserve purge/deletion seven-day execution, 30s disconnected activity scope, 200-batch Continue-As-New, stable logical keys, leaf/branch bounds, upload cleanup evidence, actual-row quota debit, and all-root/tombstone completion.
- Preserve maintenance schedule ID `openlet-storage-maintenance`, 300s interval, overlap Skip, ordered expire/reconcile/delete stages, short 30s and bounded 240s/heartbeat30/max3 options.
- Preserve processing workflow/activity timeouts, queues, heartbeat/retry policy, typed non-retryable application errors, index-only workflow identity, duplicate rules, current-run lookup, and replay-safe telemetry suppression.
- Preserve parse/enrichment/index generation and attempt fencing, immutable source identity, exact manifest replay, bounded outputs/bytes/tree depth, all-at-once output publication directly below the original file without an intermediate `artifacts/` directory or artifact-root identifier, metadata taxonomy, README rewrite, obsolete-index tombstones, and cleanup sequencing.
- Preserve basic filename/title search independently of AI readiness; semantic filters, cursor binding, dense+native BM25 RRF, original-file grouping, current/live/ready hydration, bounded candidates/offsets, and rerank-only degradation.
- Preserve backfill modes `missing` and `rebuild-index`, dry-run default, `--after`, `--limit` 1-1000, explicit `--apply`, live originals, and active-work/source-byte guards. Adapt flags only if the Go CLI contract is explicitly documented and tested; do not invent additional modes.
- Preserve ZIP64, directory-only root, stop-at-file traversal, empty directories, Windows/path safety, case/NFC collision preflight, entry/source/output/runtime/concurrency limits, revision revalidation, exact bytes, disconnect cancellation, and attachment/MIME/no-store/nosniff headers.
- Keep the existing Python directory/distribution/module until Phase 6. Consume `openlet-python` from `packages/python` and prepare/test the target gRPC activity path without changing the old default worker registrations. Reuse parsing/publication logic rather than duplicating a processor implementation.
- Phase 6 moves the app/module and activates gRPC with every build/CI/recovery consumer in one cutover. Never pre-create the future app directory or hand-patch generated imports.
- Fixtures must dial the actual Go gRPC server. No fixture may continue calling old Rust internal HTTP or report success through a fake RPC implementation.
- Controlled AI/provider responses remain valid. Do not add an AI agent, and do not require a real paid LLM E2E.

## File inventory

| Action | Absolute path | Current/New | Rough size | Test impact |
|---|---|---|---:|---|
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/temporal/` | New; ports Rust temporal modules | XL | Workflow unit, integration, replay, recovery |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/filesystem/artifacts.go` | New from `fs/artifacts.rs` | L | Artifact lifecycle/invalidation tests |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/filesystem/processing.go` | New from `fs/processing.rs` | XL | Attempt/generation/publication tests |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/filesystem/enrichment.go` | New from `fs/enrichment.rs` | XL | Whole-tree atomicity/idempotency tests |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/filesystem/indexing.go` | New from `fs/indexing.rs` | L | Vector-space/tombstone/rebuild tests |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/filesystem/maintenance.go` | New from `fs/maintenance.rs` | L | Expiry/reconcile/cleanup recovery tests |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/filesystem/backfill.go` | New from `fs/backfill.rs` | M | Dry-run/apply bounds tests |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/search/` | New from `fs/search.rs` | XL | PG+Qdrant+controlled provider integration |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/storage/archive.go` | New from storage/archive | L | Exact ZIP/cancel/deadline/bounds tests |
| Modify | `/home/qninh/projects/openlet/apps/letfs/internal/grpc/` | Phase-4 handlers expanded for processing/search/workflow control | L | Real processor gRPC fixtures |
| Modify | `/home/qninh/projects/openlet/apps/letfs/internal/http/` | Add ZIP/binary adapter behavior only; runtime route switch waits | M | MIME/header/stream cancellation tests |
| Modify | `/home/qninh/projects/openlet/apps/letfs/cmd/server/main.go` | Register all workflows/activities/queues and backfill/provider modes | M | Startup/registration/readiness tests |
| Modify | `/home/qninh/projects/openlet/apps/letfs-processing/src/openlet_processor/` | Prepare generated client and target activity path; existing worker entrypoints remain until 6 | L | Real target Go gRPC fixtures without a copied app tree |
| Regenerate/check | `/home/qninh/projects/openlet/packages/python/src/openlet_api/`, `/home/qninh/projects/openlet/packages/python/tests/` | Shared generated messages/client/server types from phase-2 proto, outside app tree | M | Isolated shared-wheel/import/gRPC contract tests |
| Modify | `/home/qninh/projects/openlet/apps/letfs-processing/pyproject.toml` | Current distribution; consume shared `openlet-python` workspace dependency, do not bundle generated namespace; rename in 6 | M | `uv build` and import test |
| Modify | `/home/qninh/projects/openlet/apps/letfs-processing/package.json` | Current package/tasks retained until 6 | S | Turbo routing |
| Modify | `/home/qninh/projects/openlet/apps/letfs-processing/Dockerfile` | Current worker/build path retained until 6; include shared package/dependency in clean image | M | Image build/smoke |
| Modify | `/home/qninh/projects/openlet/pyproject.toml` | Current app member and shared Python member retained; only app path changes in 6 | S | Lock/workspace resolution |
| Modify (generated) | `/home/qninh/projects/openlet/uv.lock` | Regenerate with uv tooling | XL | Locked Python build/tests |
| Modify | `/home/qninh/projects/openlet/package.json` | Keep current package references; add target-client tests as needed | S | Root check/test |
| Preserve | `/home/qninh/projects/openlet/infra/compose/dev.yaml` | Runtime switch deferred to phase 6 | 0 | No dev cutover here |
| Preserve | `/home/qninh/projects/openlet/infra/compose/e2e.yaml` | Runtime switch deferred to phase 6 | 0 | Native isolated stack only |

## Implementation steps

1. **Lock workflow wire contracts.** Enumerate workflow/activity names, task queues, IDs, inputs, outputs, queries, retry/cancellation rules, timeouts, and Continue-As-New state from current Rust tests and phase-1 contracts. File bytes, signed URLs, credentials, and unbounded manifests must not enter history.
2. **Implement Go Temporal registration and adapters.** Register explicit names in `cmd/server`; translate application/client errors to typed non-retryable failures and infrastructure errors to retryable failures; own heartbeat loops and graceful worker shutdown.
3. **Port CopyNode.** Reuse phase-4 copy admission/commit primitives. Preserve deterministic destinations, source/destination revisions, immutable payload identity, bounded state/traversal/deadline, candidate evidence before S3 I/O, revalidation, per-node visible commits, progress query, partial results, continuation, and finish-file processing admission.
4. **Port generic lifecycle orchestration.** Register generic provisioning/release/freeze/list/complete over Phase 4 stable-ID primitives. Authenticated caller authority, storage IDs and immutable parameters replace Workspace-specific payload scope. Workspace retains parent orchestration and all inheritance projection; letfs registers no authorization projector. Port purge, deletion, and maintenance. Use disconnected activity cancellation for irreversible cleanup batches; preserve logical identities, continuation bounds, schedule overlap policy, ambiguous tombstone retention, and object I/O outside database transactions.
5. **Port processing and artifact state.** Implement generation/attempt acceptance, source identity, parse outputs, atomic tree attach, quota/node accounting, manifest replay, enrichment whole-tree replacement, detached cleanup, manual reprocess receipts, and conservative workflow-status reconciliation.
6. **Port indexing and search.** Implement exact vector-space identity, prepare/complete/fail, readiness and obsolete-index tombstones, index-only rebuild, basic SQL search, semantic retrieval, hydration/grouping, bounded cursor state, and rerank fallback.
7. **Port Qdrant cleanup safety.** Preserve the current lifecycle lock, final serving-state recheck, exact file/generation/vector-space delete filter, finite remote timeout, bounded sweep and retained tombstone. A later PG read cannot undo an unsafe remote delete. Add a real Qdrant old-cleanup versus new-index/rebuild race to verify the port protects current points. Lock removal or a new distributed deletion-fencing design is outside this migration; no measured need requires that optimization. Search/embedding/rerank I/O continues outside SQL transactions with fresh current-fact hydration; separately test trash/replacement during query latency.
8. **Port backfill.** Keep dry-run as default and the existing modes/bounds. Use current canonical facts and dispatch identities; never rewrite original bytes or duplicate active work.
9. **Port request-owned ZIP.** Preflight safe names/collisions/bounds and capture identities/revisions, release DB work, then stream exact bytes with bounded concurrency. Own the permit and producer lifetime through disconnect/deadline. Return safe attachment, `application/zip`, `private, no-store`, and `X-Content-Type-Options: nosniff`.
10. **Prepare Python without destroying the old entrypoint.** Keep `apps/letfs-processing`, its distribution/module and existing Compose/Docker/CI references. Use the shared `openlet-python` workspace dependency, verify both independently installed wheels, and stage target activity/client entrypoints without replacing the default old worker registrations. Do not copy parser/domain logic. Phase 6 owns the destructive rename and registration switch.
11. **Generate, do not patch, Python stubs.** Run the phase-2 generator for `packages/contracts/proto/openlet_api/{account,workspace,letfs}/v1/`. Keep the sole Python output at `packages/python/src/openlet_api/`; fix generator options/package roots if imports are wrong, never edit generated files manually or copy them into the app.
12. **Prepare target application gRPC.** Give the target activity fixture an authenticated generated letfs client for prepare/output/status/parts/finalize/inline bytes/complete/fail/abort. Retain separate HTTP clients for signed S3 and providers, finite deadlines, three-attempt transient handling, terminal error classification, cancellation, and reconciliation.
13. **Build real cross-language fixtures.** Start the actual Go gRPC server and Temporal workers with isolated PostgreSQL/S3/Qdrant/Temporal dependencies, then run Python activities against it. Reject old Rust base URLs/internal HTTP and fake-success stubs in fixture configuration.
14. **Create fresh Go histories and replay tests.** Export Go-created copy continuation/recovery, purge, deletion, maintenance, processing success/failure/recovery/index-only histories. Assert activity order, CPU/I/O queues, heartbeats, retry limits, queries, continuations, partial results, and replay-safe telemetry.
15. **Hold the runtime boundary.** Old Python worker entrypoints and the current app tree remain rebuildable against the Rust reference. Target gRPC activities run only in isolated Go fixtures. Do not change Compose service commands, Workspace clients, Envoy routes, or public test fixtures yet. Phase 6 performs that coordinated switch after this isolated stack passes.

## Todo

- [x] Register and test every Go workflow/activity with explicit wire names.
- [x] Close the remaining copy/lifecycle/processing/search recovery and parity gates.
- [x] Implement bounded dry-run/apply backfill and prove missing/index-only behavior with real PostgreSQL/Temporal.
- [x] Implement request-owned ZIP and prove exact MinIO bytes, limits, cancellation, blocked-send deadline and HTTP response semantics.
- [x] Register private target Ingest RPC with dedicated `INGEST_SERVICE_TOKEN` credentials and prove server composition/allowlist isolation.
- [x] Preserve bounded Qdrant cleanup locking/filter/tombstone semantics and prove delayed cleanup cannot delete new current points.
- [x] Prepare target gRPC activities in the current Python app using the shared RPC package; keep old entrypoints/tree rebuildable.
- [x] Register generic stable-ID lifecycle Activities; no business-domain payloads or graph writer.
- [x] Consume reproducible shared `openlet_api` stubs from the independent `openlet-python` wheel; no app-vendored generated files or hand patches.
- [x] Prove target authenticated gRPC calls in fixtures; final activation and deletion of old application HTTP occur in Phase 6.
- [x] Run Python fixtures against actual Go gRPC/Temporal workers.
- [x] Export and replay fresh Go histories.
- [x] Confirm Compose/Workspace/Envoy still use the pre-cutover runtime until phase 6.

## Scenario matrix

| Severity | Scenario | Expected proof |
|---|---|---|
| Critical | Workflow retry/Continue-As-New/restart after partial copy or deletion | No duplicate charge/publication; progress/result and tombstones survive |
| Critical | Stale processing attempt or replaced source completes late | Generation/attempt/source fences reject it; current bytes/artifacts remain |
| Critical | Delayed obsolete Qdrant cleanup overlaps newly current index | Existing bounded locking and exact file/generation/vector-space filters preserve current points |
| Critical | Query returns after trash/replacement/vector-space change | Fresh PG hydration excludes stale evidence |
| Critical | Lost create acknowledgment, expired receipt, late create after freeze/delete | Persistent retries reuse IDs; no duplicate storage or resurrection |
| Critical | Python caller spoofs file/generation/attempt/job authority | Actual Go gRPC rejects before metadata/byte capability issuance |
| High | Required parse/enrichment stage fails; separate index-only run | Failure schedules no index activity; index-only run still indexes |
| High | Parse/enrichment manifest replay and quota failure | Exact replay succeeds; mismatch conflicts; publication is all-or-nothing |
| High | Maintenance/reconciliation after commit-start gap or worker outage | Durable facts redispatch/reconcile without inventing success |
| High | ZIP disconnect, deadline, changed revision, unsafe/colliding names | Producer and S3 work cancel; no partial archive side effect; explicit error before headers where possible |
| High | ZIP download response | `application/zip`, attachment filename, private/no-store, `nosniff` preserved |
| High | Reranker outage | Semantic results degrade without rerank; embedding/Qdrant failure remains dependency error |
| High | Current app wheel plus independent shared RPC wheel | `openlet_processor` and shared `openlet_api` import outside checkout; no bundled stubs/app dependency; old entrypoints still build; final app names checked in 6 |
| Medium | Controlled provider fixtures | Processing/search orchestration passes without real paid LLM calls |

## Verification commands

### Actual current reference commands

```sh
pnpm --filter @openlet/letfs test:replay
pnpm --filter @openlet/letfs test:integration
pnpm --filter @openlet/letfs-processing test
pnpm --filter @openlet/letfs-processing test:parser
cargo test --locked --package letfs --test integration search -- --ignored --test-threads=1
```

These are the current Rust/Python names and schedules. They are reference evidence only.

### Planned commands after this phase

```sh
go -C apps/letfs test ./internal/temporal/... ./internal/search/... ./internal/filesystem/... ./internal/storage/... ./internal/grpc/...
go -C apps/letfs test -tags integration ./internal/temporal/... ./internal/search/... ./internal/filesystem/... ./internal/storage/... ./internal/grpc/...
go -C apps/letfs test -tags workflow ./internal/temporal/... -count=1
go -C apps/letfs test -tags replay ./internal/temporal/... -count=1
uv run --locked --package openlet-processor pytest apps/letfs-processing/tests -m 'not parser'
uv run --locked --package openlet-processor pytest apps/letfs-processing/tests -m parser
uv build --package openlet-python
uv build --package openlet-processor
pnpm --filter @openlet/python check
pnpm --filter @openlet/python test
pnpm --filter @openlet/python test:integration
pnpm --filter @openlet/letfs-processing check
```

Add Go `test:workflow`/`test:replay` and target Python gRPC checks in the existing package as **new/renamed-by-scope** schedules while preserving the repository's unit-versus-integration separation. Do not run phase-6 public E2E as proof of this phase before the coordinated runtime switch.

## Success gate

- All named workflows/activities run in Go with explicit names/options and fresh histories replay successfully.
- Restart, response-loss, continuation, cancellation, partial-copy, deletion, maintenance, and processing recovery tests pass against real isolated Temporal/PostgreSQL/S3 dependencies.
- Search tests use real Qdrant plus controlled providers and prove current/live/ready hydration, cursor binding, grouping, cleanup, degradation, and cleanup/query race safety with existing bounded locking preserved.
- ZIP tests prove bounds, collisions, exact bytes, changed-source rejection, cancellation/deadline ownership, attachment, MIME, no-store, and `nosniff`.
- The current Python app consumes reproducible stubs from the separate shared Python wheel and its target activity fixtures talk to actual Go gRPC; existing default entrypoints/tree remain rebuildable. Full rename/activation is explicitly Phase 6.
- Generic provisioning retries/local fences pass; letfs checks owner-projected permissions without loading or projecting business bindings.
- No AI agent exists, no real-LLM E2E is required, and Compose/Workspace/Envoy have not switched before phase 6.

## Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Cross-language Temporal semantic drift | High | Critical | Explicit names/options, fresh exported histories, replay plus real restart tests |
| Premature Python switch breaks the reference worker | High | High | Keep default entrypoints/tree until 6; prove target fixtures independently, then switch every consumer together |
| Cleanup port loses serialization or exact delete scope | Medium | Critical | Preserve current bounded lifecycle locking, timeouts, filters and tombstones; real cleanup/new-index and query races |
| Generated Python imports are hand-fixed and non-reproducible | Medium | High | Fail generation/package test; fix generator configuration only |
| ZIP producer outlives disconnected request | Medium | High | Stream owns context, permit, readers, goroutines, deadline; assert cleanup after cancellation |
| Fake processor fixture masks RPC/auth failures | Medium | Critical | Fixture must dial bound Go gRPC address and assert server-side effects/denials |

## Security and data safety

- Authenticate service/job identity independently from generation/attempt IDs in payloads. Scope every processing RPC to its accepted job authority.
- Never place file bytes, signed URLs, credentials, raw provider responses, document text, or unbounded manifests in Temporal histories/logs.
- Validate generated artifact paths and ZIP names as data; reject traversal, separators, Windows hazards, duplicate/case/NFC collisions, and header injection.
- Keep Qdrant/OpenRouter/S3 credentials inside the owning process and redacted telemetry. Fail closed on application authorization or required current-fact checks.
- Before any later real reset/cutover mutation, create and verify PostgreSQL, SpiceDB, and object backups. Phase-5 fixtures remain disposable and isolated.

## Rollback

Revert only the new Go workflow/search/archive and staged target-client changes; the current Python app directory/default worker entrypoints remain available. Preserve unrelated work and use the matching checkpoint for dependency changes. Delete only disposable phase-5 test containers/histories. Because Compose and public traffic are not switched here, rollback needs no live data conversion. If a non-disposable environment was mutated, stop workers/writers and restore the verified pre-mutation database/object backup before resuming.

## Next

Phase 6 performs the single coordinated runtime switch: Compose and health checks, Workspace generated client/resource references, Envoy public HTTP/native gRPC routing, the full ingest app/module/package rename with CI and recovery controls, real public fixtures, and deletion of the Workspace file proxy. Rust source and obsolete runtime assets remain until phase 7 final cleanup and recovery acceptance.
