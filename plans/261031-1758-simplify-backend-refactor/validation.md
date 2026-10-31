# Plan validation and review

Date: 2026-10-31. Scope: plan documents only. All six implementation phases remain pending. No application build, test suite, provider call, migration, database reset, or deployment was performed to validate this plan.

## Accepted outcome and validation decisions

The existing brainstorm and subsequent user instructions already resolved the material product decisions. This is an English record of those decisions, not a new interview or implementation approval.

| Topic | Accepted decision | Owning phases |
|-------|-------------------|---------------|
| Compatibility/data | No production data/clients to preserve; breaking replacement, no legacy code, squash app migrations | All |
| E2E | Delete every old test/harness/helper/fixture; write from scratch, no move/copy; API E2E first with real dependencies | 1, 6 |
| Scripts | Delete all old standalone scripts; rewrite only necessary permanent automation; no temporary scripts | 1, 2 |
| Tests | Meaningful behavior/failure proofs; no junk tests, fake success or arbitrary coverage goals | All |
| Document precedence | Architecture decisions for repo/testing/infra; final architecture for API/lifecycle; numbered note for semantics/workers | All |
| Copy/delete | Keep committed partial progress; no rollback feature or whole-tree copy snapshot | 5 |
| ZIP | Bounded direct HTTP stream, no temporary object/workflow; fail on changed/missing selected source | 5 |
| Temporal | Child workflows for long processes, remote Activities for short internal mutations; HTTP for external/byte/resource boundaries | 4–6 |
| Idempotency | Real Workspace/Letfs idempotency_keys tables where needed; natural Account identity; 24h after logical completion, never prune active work | 4–6 |
| Invitations | Hash-only storage, plaintext once; retry returns metadata; lost token requires revoke/recreate | 4 |
| HTTP/telemetry | Complete Chi→Gin; native OTel across all app languages and both workers; no observability backend | 3, 6 |
| Language | Full detailed plan in English; changing language does not authorize shortening scope or execution detail | All |

No additional product questions were introduced. Routine source-backed plan corrections below were applied within the authorized planning scope.

## Source verification

Four independent read-only reviewers checked current implementation claims and target contracts, using CodeGraph/source evidence. Planned files/commands were distinguished from existing artifacts. Claim counts include overlapping samples; they are not counts of unique proven behaviors.

| Lens / verification role | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 | Phase 6 |
|--------------------------|---------|---------|---------|---------|---------|---------|
| Security / Fact Checker | 4 | 4 | 4 | 4 | 4 | 4 |
| Failure / Flow Tracer | 4 | 4 | 4 | 8 | 10 | 10 |
| Assumptions / Scope Auditor | 7 | 9 | 10 | 8 | 12 | 9 |
| Complexity / Contract Verifier | at least 4 | at least 4 | at least 4 | at least 4 | at least 4 | at least 4 |

The full-tier sample budget was met across roles. These are source checks of plan accuracy, not runtime verification of the future implementation.

## Red-team review and disposition

After deduplication: 14 material findings, 11 High and 3 Medium; 13 accepted corrections and 1 rejected proposed mechanism. No Critical finding. The rejected mechanism received a narrower explicit trust-boundary clarification.

| Finding | Severity | Disposition and plan change | Current-source evidence |
|---------|----------|-----------------------------|-------------------------|
| Fixed E2E cleanup can collide with another run | High | Accept: atomic project exclusivity and cleanup ownership check, phase 1 | scripts/verify-foundation.sh:10; scripts/backup-restore-drill.sh:7 |
| Bootstrap rewrite can lose secret/endpoint protections | High | Accept: private generated paths/files, HTTPS/URL validation and fresh behavior tests, phase 2 | scripts/configure.py:144; scripts/configure.py:163; scripts/configure.py:179 |
| Add a custom per-Activity MAC/capability protocol | High | Reject this mechanism: same-team private Temporal control plane is the accepted boundary; explicitly preserve isolation, prohibit untrusted publishers and validate durable owner scope, phase 4 | deploy/compose.yaml:54; deploy/compose.yaml:221; deploy/compose.yaml:226; docs/workflows.md:103 |
| Copy monitor might authorize a removed member | High | Accept: current membership check precedes admission-actor/current-owner checks, phase 5 | services/workspace/internal/http/files.go:357; services/workspace/internal/http/files.go:388 |
| Ambiguous cleanup evidence has no explicit closure policy | Medium | Accept: known-terminal writer proof before pruning; unresolved presigned writes retain compact tombstones with bounded re-delete/admission limits, phase 5 | services/letfs/src/fs/maintenance.rs:98; services/letfs/src/fs/maintenance.rs:129; services/letfs/src/fs/uploads.rs:37 |
| Rust Temporal distributed tracing requires experimental features | High | Accept: pin native 1.1.0 OpenTelemetryPlugin, enable experimental + opentelemetry, disable default baggage; distinguish Core otel metrics, phase 3 | services/letfs/Cargo.toml:19; installed temporalio-sdk-1.1.0/src/opentelemetry.rs:3; installed temporalio-sdk-1.1.0/Cargo.toml:53 |
| Phase 5 operations deletion omitted live search/index consumers | High | Accept: port indexing/search hydration/readiness/cleanup in the operations-removal slice, phase 5 | services/letfs/src/fs/search.rs:242; services/letfs/src/fs/search.rs:268; services/letfs/src/fs/indexing.rs:21 |
| Account/Workspace have no existing reconciliation schedule | High | Accept: small owner-managed native Temporal schedules plus alive-service start-failure proof, phase 4 | services/workspace/cmd/server/main.go:68; services/letfs/src/main.rs:57 |
| Deleted file loses Qdrant cleanup identity | High | Accept: minimal index_deletions outbox survives file metadata removal, phases 5–6 | services/letfs/src/fs/indexing.rs:79 |
| New readiness omits vector-space identity | High | Accept: persist/compare model, collection, dimension; index-only invalidation/recovery, phases 5–6 | services/letfs/src/fs/indexing.rs:48; services/letfs/src/fs/search.rs:268 |
| Copy progress has no owner across Continue-As-New | Medium | Accept: workflow counters/query/final result and continuity proof, phase 5 | services/letfs/src/fs/copy.rs:106; services/letfs/src/temporal/copy_workflow.rs:125 |
| Manual reprocessing has no unconditional retry identity | High | Accept: required caller-scoped key atomically binds the admitted generation, phases 1, 4, 6 | architecture input openlet-final-architecture-status-to-processing (1).md:41; same input:67 |
| Phase 5 inventory omits Python operation-shaped clients | High | Accept: activity.py, models/client/config and focused contracts explicitly included, phase 5 | services/letfs/processor/src/openlet_processor/activity.py:129; activity.py:389; activity.py:489 |
| Readiness gates could hide filename search while AI is pending | Medium | Accept: SQL filename search remains independent, with a pending/failed case, phase 6 | services/letfs/src/fs/search.rs:190; docs/api-contracts.md:99 |

### Whole-plan consistency sweep

- The language change preserves requirements and execution detail. The index is intentionally short; phase files contain the detailed contracts, inventories, steps, verification, risks and recovery behavior.
- All phases agree on E2E/script deletion and fresh rewrites, one baseline per app DB, no backward compatibility, and real dependency testing.
- Phase 5 owns ALL mechanical consumers needed to remove operations, including Python transport and search/index SQL. Phase 6 finishes semantic ordering, queues and final indexing behavior. There is no broken intermediate API or legacy schema fallback.
- The new index outbox preserves an existing remote-cleanup obligation; it is not an execution/progress table. Copy counters belong to Temporal; receipts do not become manifests.
- Native owner schedules cover the database-commit/start gap without adding a scheduler service. OTel uses the verified native Rust plugin rather than a handwritten framework.
- Ambiguity retention explicitly trades bounded re-delete/admission cost for safe evidence preservation. No false promise that URL expiry proves a writer stopped.
- Implementation tasks remain unchecked. Native/runtime/selected-provider acceptance must be established during execution, not inferred from this review.

## Authoring checks and handoff

Completed authoring checks: ak plan validate reports valid; parse/status discovers all six phases and 94 pending implementation items with none complete. Every local Markdown link resolves, fenced blocks balance, and no scaffold placeholder remains. The files-first plan store is reindexed and this plan is pinned for the worktree. No task-management connector is available in this session; the phase checklists are the durable execution tracker. These checks validate the plan artifact, not future application behavior.

Execute only when requested using:

```text
/ak:cook /home/qninh/projects/openlet/plans/261031-1758-simplify-backend-refactor/plan.md
```

The native Rust tracing API remains experimental and requires integration proof against pinned versions. External-provider checks require their isolated sandbox configuration; absent credentials do not count as a pass.

## Implementation evidence — API E2E foundation

- Fresh Playwright suite replaces all 23 tracked legacy E2E files, their issuer and test Dockerfile. No legacy source was moved/copied.
- Full real-stack run: 22 tests, 4 gateway passes, 18 failures at target onboarding (403/expected 202). This is expected pre-implementation evidence, not acceptance.
- Native setup lifecycle: 2 passed (port collision and SIGTERM while containers start), with owner-safe cleanup and no residual project containers/volumes.
- TypeScript, public OpenAPI validation, Rust test compilation, formatting and diff whitespace checks passed for the recorded foundation.
- Added destination-conflict, publication-quota and path-locator cases; typecheck passes, execution pending.
- Pending test design: coordinated recovery/permanent CLI and opt-in live provider replacement. No provider recovery claim or existing database reset.
- Processing internal descriptors currently use the public signer. Port them to internal-reachable signing in phase 5; never rewrite signed hostnames.

## Implementation checkpoint — foundation verification

- Full fresh API suite: **26 executed, 4 gateway passes, 22 failures** at target onboarding (403/expected 202). This closes test-first authoring, not backend acceptance.
- Environment lifecycle: **2/2 pass** after TCP PostgreSQL readiness replaced a UNIX-socket check that could see the temporary init server.
- Permanent recovery CLI: **1/1 pass** using real PostgreSQL/Temporal/S3/Qdrant containers; verifies database state, exact object bytes, empty-target writer fencing, explicit resume, checksum rejection, and repeated native migration no-op.
- Recovery defects fixed from runtime evidence: Python 3.10-compatible streaming checksums, restored mounted-file permissions, and removal of unsupported Compose create --no-deps.
- Native parser suite initially failed because DOCLING_MODELS_PATH was absent. After the permanent package prefetch command and explicit offline-model path: **11/11 parser tests pass**, with no assertions weakened.
- Latest public OpenAPI and E2E TypeScript checks pass. Live Clerk, selected external storage and remote CI remain NOT RUN. Business-workflow restore/replay evidence remains owned by phases 4–6.
- Phase 3 now active: direct Gin conversion with native middleware/handlers; no WrapH compatibility adapter. Cross-language OTel acceptance is still open.

- Phase-2 Rust real integration completed: **20/20 pass**. Foundation layout, native migrations and permanent operations tooling are complete; final replay/business recovery remains explicitly pending with its owning implementation phases.


## Implementation evidence — Gin and OpenTelemetry

- Account/Workspace now use native Gin, otelgin/otelhttp/otelpgx, and the supported Temporal Go interceptor. Letfs uses Axum/tracing, native reqwest instrumentation and the pinned Rust 1.1.0 experimental OpenTelemetryPlugin with trace-context-only propagation. Python uses native HTTPX + HTTPX2 instrumentation and Temporal contrib tracing.
- Fixed two discriminated fixture errors: JSON-stringifying schema messages escaped quotes; Instructor actually sends system content as text-part arrays. The fixture now reads strings and text parts before extracting the semantic enum. No business validation was weakened.
- Real current-route file creation completed parse/enrichment/index with trace `511ec448fe64c13e7bd84e4c6f192e16`. The authenticated model boundary observed generation and embedding requests on that same trace with baggage absent. Earlier failed probes remain diagnostic history, not passing evidence.
- New native `apps/letfs/tests/telemetry.rs` passes against an isolated real Temporal server: two workflow runs and two Activities preserve one trace across Continue-As-New; both captured histories replay successfully with no additional exported spans.
- Gateway baseline: **4/4 pass** without exporters, **4/4 pass** with `OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:1` and HTTP/protobuf. A broader grep also selected ZIP, which remains expected-red at the unimplemented target onboarding route (403 vs 202); it was not hidden or reclassified as a gateway failure.
- Native checks: both Go unit/workflow/vet and PostgreSQL suites pass; Rust **14/14 lib tests**, new Temporal continuation/replay integration and all-target Clippy pass; Python **69 nonparser cases** and **4 telemetry cases** pass; TypeScript and both Compose config validations pass. Earlier Rust storage **20/20** and Python parser **11/11** evidence remains from the recorded foundation; those unchanged suites were not repeated solely for this checkpoint.
- Native bootstrap/logging checks prove resources, parentage and active-span correlation. Signed queries are excluded on success and HTTP transport failure. Exporters are optional with bounded queues/timeouts/shutdown. Stack cleanup left no owned containers or processes.
- Phase 3 is complete. Target APIs, schema/lifecycle replacement, both Python worker roles and final business/recovery acceptance remain phases 4–6. Live Clerk/selected external providers and remote CI remain NOT RUN.


## Early phase-4 checkpoint

- Account's operation table and old Workspace HTTP start/status methods are deleted. Natural user lifecycle admission commits before dispatch; Workspace child results are recorded before Clerk publication. Duplicate-rejecting starts and a native five-minute reconciliation schedule recover missing dispatches.
- Workspace storage mappings are merged into workspaces; lifecycle columns/DTOs use status. Resource reads expose provisioning state and optional mappings. Old internal Account-to-Workspace endpoints and their unused service token/configuration are removed, including bootstrap and Compose consumers.
- Invitations have a partial uniqueness constraint for normalized pending email, hash-only tokens and one plaintext creation response. Repeated pending creation returns metadata; changed role conflicts; expired invitations can be replaced. Ownership PATCH and membership mutation use workspace revisions and atomic owner transactions.
- Go unit/workflow/vet checks and real Account/Workspace PostgreSQL suites pass at this checkpoint. Native Workspace tests include eight concurrent invitation calls with exactly one plaintext token. Bootstrap tests: **6/6 pass**; TypeScript passes.
- Real gateway onboarding: **2/2 pass**, including two injected Clerk metadata failures. Ownership-transfer E2E passes. Invitation E2E now reaches the phase-5 target nodes route, where viewer mutation expects 403 but receives 404 because that route is not implemented yet. The assertions remain intact; membership-removal/replay tail is not claimed as executed by that case.
- At that earlier checkpoint, Workspace still used its operations table and HTTP-based Letfs provisioning/deletion. Receipts, direct remote Activities, deletion children, Workspace reconciliation and full target API/recovery acceptance remain unfinished. No phase-4 completion claim.


## Phase-4 implementation — receipts and direct Go/Rust orchestration

- Removed Workspace operations and the obsolete HTTP create/ensure/freeze/delete-poll contracts, clients and orphaned schemas. Receipts contain create scope/key/hash, immutable admission input, Workspace/Workflow IDs and completion/expiry; no execution status or cursor. Letfs owner-generated provisioning effects and receipts commit together.
- Public Workspace create commits resource/owner/receipt before dispatch and returns resource Location. A bounded dispatch outage remains 202. Natural delete commits its tombstone first, uses no request key, and keeps an owner-readable terminal resource. Current roles/revisions, invitation token/expiry guards and membership removal remain enforced.
- Mapping commit precedes remote receipt release; receipt completion follows release. A bounded scan in the existing native owner schedule recovers active mapping/release gaps. Incomplete remote results stay pinned; completion records a 24-hour expiry without extension on retry. Stable owner keys/tombstones also prevent internal provisioning retries from allocating replacements after expiry.
- Review found and repaired two concrete dead ends: failed provisioning could not be deleted, and a terminated deletion parent could strand later cleanup. Owner DELETE now cleans failed/partial provisions through an owner-keyed frozen-bucket fence. Terminal recovery checks durable deleting state and explicit closed execution status before another run; running/unknown workflows are not restarted. Child execution IDs differ between recovery runs, but logical deletion keys and owner-side atomic effects remain stable. Frozen enumeration skips deleted filesystems.
- Latest combined E2E: **10/10 pass**, covering four gateway cases, two onboarding cases, concurrent Workspace create, ownership transfer, normal deletion and terminated-parent recovery. Separate real Temporal outage: **1/1 pass**; Workspace remains running, returns durable 202, then its registered owner schedule dispatches after Temporal restarts. Full invitation still fails at the phase-5 nodes route (403 expected, 404 current); no assertion was hidden.
- Fresh real lifecycle histories are exported by the deletion journey under ignored `.local/api-e2e/histories`. Account and Workspace Go replayers pass. The Rust filesystem-child replayer passes using official protobuf JSON-to-binary conversion in the owning Go replay check. Rust SDK 1.1.0 plain serde history JSON is incompatible with CLI protobuf JSON; no handwritten codec was added.
- Native Workspace PostgreSQL suite passes, including concurrent receipts/limits, request mismatch, incomplete mapping rejection, explicit 24h receipt expiry/reuse, same-execution replay after expiry, active unreleased-result scans and failed-resource cleanup. Both Go unit/workflow/vet suites pass. Rust storage, receipt/owner-scope and failed/partial-cleanup boundary cases pass, as do all-target Clippy, TypeScript and local OpenAPI references.
- Scoped simplifier re-review found no remaining concrete defects after these fixes. No production worker delegation or temporary script was used. Cross-language wire contracts were exercised by actual registered Go/Rust workers, not only SDK mocks.
- Remaining phase-4 proof: full invitation journey depends on phase-5 file routes; actual response-loss injection for provisioning release and parent termination with additional filesystems still need targeted coverage. The real PostgreSQL-lock E2E terminated the Workspace parent while its filesystem child was active, repeated DELETE, and completed cleanup (1/1 pass). The SDK test proves Workspace Continue-As-New after 100 children carries its cursor and completes the next run; this is native workflow evidence, not a real multi-run integration claim. Live Clerk, selected external providers and remote CI remain NOT RUN.

### Phase-5 ZIP and files checkpoint

- Deleted ExportArchive workflow/Activity/registration, export_attempts baseline, export status/download routes, temporary ZIP S3 transport, replay case, legacy native ZIP tests and retention/root-selection config. ZIP uses a request-owned bounded stream and per-process semaphore; Workspace preserves HTTP body errors and propagates cancellation. The archive-only Envoy route has an explicit deadline.
- New native real PostgreSQL/S3 archive tests: 3/3 pass (exact inline/object bytes, relative names/empty directories, no stored archive/quota effect; changed source/path/limits; body-owned concurrency/deadline). Pure path tests pass, including canonical Unicode normalization collisions. Go real HTTP proxy tests prove incomplete upstream bodies abort and client disconnect cancels the upstream read.
- Review found Unicode normalization collisions; the implementation now compares normalized case-insensitive collision keys while preserving original names. No task/job framework or detached archive producer was added.
- Replaced file_data with files in the single Letfs baseline and every current Rust SQL consumer. Moved MIME and semantic columns out of nodes; directory DTOs omit those fields. Publication, search hydration, path resolution, copy MIME and cleanup references use files. The full native real-storage suite passed 21/21 after that schema split. Subsequent strict-create resource API work is under verification separately.
- Public ZIP/invitation E2E is running against the new node create/read slice; no pass is claimed yet. Copy/deletion/processing operation removal, upload API migration and phase-6 semantics remain open.


### Phase-5 node/upload resource verification

- Real gateway run: **8/8 pass** for strict node create/byte/revision semantics, ZIP, path resolution, four object upload contracts and invitation/current-membership authorization. Single/multipart transfers use actual storage; the multipart boundary drops its completion response once and the API reconciles without duplicate publication/quota.
- Upload create uses an atomic scoped admission receipt, separate from upload session/result facts. Active receipts pin; terminal completion/abort/expiry starts a non-extending 24-hour TTL. Old user upload action routes, byte relay, POST-parts/finalize route shapes, per-part MD5 request DTO and legacy upload baseline transport are removed. The shared processor's transfer-ready/publication state remains to be ported with processing generation ownership.
- MIME persists on the file row. ETags are opaque; completion checks immutable candidate ownership and actual size rather than assuming an MD5 format. Required single-PUT Content-MD5 enforcement is still checked by the provider protocol gate; no universal provider verification claim is made.
- All source/output processor signing uses internal-reachable storage endpoints. A native real-storage case deliberately configures an unreachable browser signer and verifies the processor can GET source bytes and PUT output bytes through its own descriptors.
- Latest broad native run: **21/22 pass**; the remaining failure was the new expiry fixture changing only expires_at while the schema requires expires_at=completed_at+24h. The fixture now ages both timestamps under that same constraint; the focused direct-storage rerun passes **4/4**. It also verifies receipt pin/expiry/reuse, non-extending abort TTL and unresolved-write cleanup backpressure, plus the internal signer source/output boundary. Earlier obsolete MIME/text-helper expectations were corrected for the actual resource API (text/plain fixture MIME; replacing PDF bytes admits a new parse intent).
- Workspace Go unit tests and vet pass; Python nonparser suite **69/69 pass**, Ruff and E2E TypeScript pass. Rust all-target Clippy passes after relocating the native telemetry test module to the end of its file. Both OpenAPI files have resolved local references, valid JSON Schema components and unique operation IDs. Scoped simplifier review completed without new abstractions or compatibility code.
- Copy/deletion/processing still depend on operations/copy_items/deletion_items/staging; their removal and final phase-6 acceptance are pending. Live external Clerk/storage/model verification and remote CI remain NOT RUN for this slice.

- End-of-slice reconciliation: both test runners exited, E2E Compose teardown completed, and no owned test containers or background runners remain. Goal remains active in phase 5.

## Shared upload terminal-state verification

- Removed the processor-only `uploaded` state from schema, controllers, cleanup predicates, contracts and native fixtures. Shared uploads use `open`, `completing`, `finalized`, `aborted`; inline transfer saves immutable bytes/hash while open. The baseline requires every finalized session to have its verified size and saved completion result.
- Processor finalize records an immutable transfer receipt without publishing nodes or charging quota. Parse/enrichment publication attaches its result-node reference and moves inline bytes into files without rewriting that receipt. Repeated finalize and same-byte inline replay preserve it after publication; changed inline bytes conflict, terminal sessions issue no new capabilities, and finalized sessions cannot be aborted or expired.
- Superseded/unused finalized output candidates enter durable cleanup while their receipts remain terminal. Maintenance includes unattached finalized evidence, so replacing a source cannot strand its output bytes. Native coverage proves object deletion retains ambiguous-write tombstones and transfer completion alone neither exposes artifacts nor charges quota.
- Python output retry reconciles `completing`/`finalized` sessions through completion without requesting capabilities or resending object bytes. Aborted sessions fail explicitly. New HTTP-boundary cases cover these three states.
- Full real PostgreSQL/S3/Temporal native integration: **23/23 pass** (`cargo test --locked --package letfs --test integration -- --ignored --test-threads=1`, 292.67s). This supersedes the earlier split-run native evidence for the upload slice. The scoped simplifier subsequently made equivalent value-reuse/SQL-predicate edits; current all-target Clippy passes.
- Current-source gateway run: **8/8 pass** for strict inline create/revisions, ZIP, mounted paths, single-object download/Range, stale replacement, multipart lost acknowledgment, publication quota rejection and invitation/membership revocation.
- Focused Python Activity boundary: **16/16 nonparser pass**, one parser deselected. Ruff and OpenAPI local-reference/component-schema/operation-ID checks pass. No external Clerk/storage/model or remote CI checks were run for this slice.
- Phase 5 remains in progress: processing still uses operations; file/generation ownership, direct partial-copy/delete traversal, trash resource routes and obsolete-table removal are unfinished. Phase 6 and final recovery/replay acceptance remain pending.

## Direct artifact-forest cleanup

- Removed creation of `discard-artifacts` operations and their `deletion_items`, plus the obsolete cleanup index. Source replacement detaches roots transactionally; a small partial nodes index supports discovery. No new table, job, workflow, script or compatibility path was introduced.
- Existing maintenance excludes live filesystem roots, trash entries and active copy staging, rechecks the same ownership under bucket/filesystem locks, follows one branch bounded to 128 edges, and deletes at most 64 leaf siblings. Actual removal, object-deletion intent and quota debit share the existing deletion transaction. Remaining rows preserve progress across calls without a separate checkpoint table.
- Meaningful existing lifecycle cases now additionally prove that trash and active staging survive cleanup, a 70-leaf forest is only partially removed on the first 64-leaf batch, later batches finish it, and a repeated empty pass cannot debit usage again. The successful publisher remains succeeded until its charged descendants are removed.
- Focused artifact lifecycle suite **4/4 pass** before the final indexed-name traversal and stronger batch assertions; a fresh full integration run verifies those final changes below. Current all-target Clippy, formatting, **14/14 Rust lib tests**, E2E TypeScript and owning Markdown links pass. The full updated Python nonparser suite passes **72/72**, with 11 parser cases deselected.
- Scoped simplifier review left this cleanup implementation unchanged with no concerns. File-owned processing/search generation, general copy/purge traversal and the remaining phase-5/6 gates are still open.
- Final source after the direct-forest change: full real PostgreSQL/S3/Temporal integration **23/23 pass**, zero skips/failures (`cargo test --locked --package letfs --test integration -- --ignored --test-threads=1`, 293.07s), including the final bounded-batch, staging/trash exclusion and repeated-cleanup assertions. This is a fresh full run after the earlier upload-only 23/23 result.
- The native and API E2E runners completed with automatic teardown. No owned test containers or background runners remain. Goal remains active in phase 5; no commits/pushes or existing database resets were performed.

## File-generation recovery and direct deletion checkpoint — 2026-11-01

- Current processing uses file/generation/source/attempt fences, shared uploads, README-owned enrichment and family:kind taxonomy; CPU parsing and I/O enrichment/indexing run on separate queues. This supersedes older checkpoints saying processing still uses operations. Copy remains the only owner of the old Letfs operations/item/staging machinery.
- Fresh gateway recovery/telemetry selection: **2/2 pass**. A real CPU worker restart resumes object-source DOCX parsing without another artifact tree; a trace supplied through Workspace/Letfs reaches Python provider calls with no baggage. The preceding processing journey evidence remains the two successful real-DOCX/manual-retry/filename-search cases from the prior continuation; it is not a live model-quality claim.
- Purge and filesystem deletion now use immutable natural resource identity, direct remaining-node traversal and atomic per-batch accounting. Removed deletion_items from baseline/source/DBML, removed deletion execution receipts/operation rows and the synchronous file-purge branch. Purge admission commits trashed→purging before dispatch; the existing maintenance schedule redelivers a lost start. Filesystem tombstones and every detached root remain covered. No new table, scheduler, temporary script or rollback machinery was added.
- New public trash resources implement node DELETE, paginated entry reads, original-parent/name restore, and owner-only entry DELETE. Entry identity fences stale restore cycles. A deleted Workspace now returns NOT_FOUND from its shared authorization guard instead of WORKSPACE_DELETING for nested resources; the owner-readable Workspace tombstone remains available.
- Gateway selection **3/3 pass**: exact trash/restore bytes and identity, repeated purge/quota, normal Workspace deletion, and a terminated Workspace parent while its filesystem child is active. Each run uses a fresh PostgreSQL-backed Temporal/real storage stack with automatic teardown. The final read-only review removed a redundant post-commit trash-entry fetch; the same committed response is returned directly.
- Full real PostgreSQL/S3/Temporal integration **24/24 pass**, zero skips/failures (312.57s). It includes a new bounded 70-leaf purge case: first batch removes 64, restart resumes remaining work, outside content survives, restore is fenced and repeated completion cannot debit again. Existing processing/search/upload/forest cases remain green.
- Dedicated real Temporal tracing test **1/1 pass**: trace identity survives Continue-As-New and replay exports no duplicate spans. Fresh Account and Workspace history replay pass; the current Rust filesystem-child replay passes after official protobuf JSON conversion in the owning Go replay check.
- All-target Rust Clippy/format, Workspace unit/workflow/vet and E2E TypeScript pass. Independent scoped read-only simplifier review found no correctness defects and identified only the redundant fetch removed above. Contracts and owning documentation now reflect natural purge identity, no deletion_items and the exact TrashEntry DTO.
- Remaining: replace copy operations/copy_items/staging with bounded workflow traversal, stable per-item effects and retained partial progress; then final phase-5 cleanup and phase-6 full E2E/replay/restore acceptance. Full target API E2E, live external Clerk/S3/model checks and remote CI are not claimed for this checkpoint. No commit/push/deploy or reset of an existing environment was performed.

## Copy replacement and final recovery verification — 2026-11-01

- Copy now uses bounded workflow traversal, deterministic destination identities, captured source/parent revisions and immediately visible per-item commits. Receipts retain immutable admission only; cumulative counters survive Continue-As-New. Cleanup records candidate ownership before I/O and prevents reuse after deletion starts. No operations, copy_items, deletion_items, export_attempts, staging_operation_id or file_data reference remains in current application source/baselines. The earlier checkpoint above is superseded.
- Current native full integration passed across Account, Workspace and Letfs. Letfs: **26/26 real PostgreSQL/S3/Temporal cases**, plus **1/1 Temporal trace/continuation/replay case**. The new cases cover acknowledgment-loss recognition without quota duplication/resurrection, rejected object-copy cleanup and bounded purge progress. Both Go workflow suites pass. Repo checks pass with the supported Go binary on PATH; parser regressions pass **11/11** with the documented offline model path. An initial parser invocation without that environment failed explicitly; assertions were unchanged.
- Coordinated API recovery passed independently: isolated databases/storage restore, exact original object bytes, and an interrupted DOCX workflow resumed to published/indexed readiness. A concrete restore defect was fixed: Compose selected stale project-named application images for the isolated target. `resume` now builds its application services from the current checkout. Snapshot restore requires the matching schema/code checkout. Generic command failures no longer falsely claim every writer remains fenced after a partially failed resume.
- The first combined run passed recovery and 27 subsequent API cases but failed the first four API sessions at onboarding with 503 immediately after source resume. Container health did not establish gateway routing readiness. Recovery teardown now recreates its source fixture identity and polls its existing GET onboarding route before handing the environment to the next project. This preserves the original business assertions and uses no arbitrary delay/retry of mutations. A clean full-suite rerun is in progress; no full acceptance claim yet.
- Replaced obsolete processing replay expectations/queue names with histories exported by the new parsed/direct/failed/restarted journeys. Purge and scheduled maintenance histories are also captured; official Go protobuf APIs export them for Rust. Terminal history capture waits for actual completion/failure, including copy and cross-language lifecycle runs. Final replay remains pending the complete clean E2E run.
- Scoped independent read-only review of the recovery/replay changes found the misleading fencing diagnostic noted above; it is corrected. README/current docs now describe Gin, two worker roles, direct traversal, resource status and ZIP streaming. Both OpenAPI documents pass local-reference, unique-operation-ID and JSON Schema definition checks; owning Markdown links resolve.
- Live Clerk, selected external S3/model verification and remote CI remain **NOT RUN for the refactored source**. Local boundary doubles and managed SeaweedFS do not establish external-provider/model quality or external-object disaster recovery. No existing development database was reset; no commit/push/deploy was performed.

### Clean full-suite result

- `pnpm e2e:api`: **32/32 pass, zero skipped**, including recovery before the API project and the previously failing source-resume handover. Recorded output: ignored `.local/api-e2e/final-api-e2e-rerun.log`. Current body assertions prove exact inline/object/ZIP bytes, ordinary partial copies, quotas, upload completion response loss, current membership, semantic readiness/search, real CPU/Letfs restart and cross-language trace continuity.
- Current generated histories replay successfully with native Go owners and Rust: onboarding, Workspace creation/deletion, filesystem child, purge, maintenance, copy (continuation and partial failure), parsed/direct processing, exhausted enrichment failure and recovered CPU processing. Rust verifies Activity order, correct CPU/I/O queue, heartbeat and retry limit. No previous-version history compatibility path remains.
- `pnpm build` passes for both Go applications, Letfs and the Python wheel; `pnpm check` passes native formatting/vet/Clippy/Ruff/TypeScript. Final owner-safe setup/corruption-rejection CLI recovery check is running separately after full-suite teardown. Phase 5 is complete; final phase 6 remains active until that check and plan/doc reconciliation finish.

### Final acceptance and execution completion — 2026-11-01

- Final environment/recovery command: `node --test --test-concurrency=1 e2e/setup/environment.test.ts e2e/setup/recovery.test.ts` — **3/3 pass, zero skipped**, 141.11s. Evidence: ignored `.local/api-e2e/environment-recovery.log`. This verifies occupied-port ownership/lock release, SIGTERM cleanup during real startup, repeated baseline migrations, isolated fenced restore of database values and exact S3 bytes, explicit resume, and rejection of a corrupted snapshot. The full API recovery journey above separately proves unfinished workflow continuation.
- Current-source native tests pass: Python **79 nonparser cases**, Rust **14 unit cases**, both Go applications, and **6 bootstrap cases**. The configured offline parser run passes **11/11**. Full native integration, fresh workflow replay, repository checks/build and **32/32 API E2E** results above form the final local acceptance evidence; no failed earlier attempt is counted as a pass.
- Phase 6 and all plan acceptance criteria are complete. README and docs navigation identify this plan as an execution record. Current docs/contracts/DBML remain the product authority. All application databases retain one baseline migration; no legacy compatibility or temporary automation was added.
- Final process reconciliation finds no owned API/restore containers or test/recovery runners. The pre-existing CodeGraph services were left untouched. No existing development database was reset; no commit, push or deployment was performed.
- **External verification:** Clerk **NOT RUN**; selected external S3 provider **NOT RUN**; live model provider **NOT RUN**; remote CI **NOT RUN** for the refactored source. Managed storage recovery and model protocol doubles establish only the local boundaries exercised; they do not establish external-object disaster recovery or live model quality.
