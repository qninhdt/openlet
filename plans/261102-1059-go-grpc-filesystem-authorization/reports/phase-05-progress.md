# Phase 5 implementation evidence

Status: completed. The deployed runtime remains Rust; all target Go dependencies below are disposable fixtures. No developer database reset or runtime cutover occurred. Phase 6 owns activation and the ingest rename.

## Implemented

- Go copy, processing, purge and filesystem-deletion workflows have explicit wire names, bounded state/options and generic storage provisioning activities. Copy monitoring checks the requesting actor and current inspect-any authority.
- Parse output uploads reuse the public storage-transfer machinery with independent private stage/generation/attempt scope. Internal S3 signing, inline/single/multipart completion, immutable receipts, candidate cleanup, exact manifests and atomic quota/node publication are implemented.
- Generated children attach directly to the original file. There is no intermediate `artifacts/` directory or artifact-root identifier. PostgreSQL, protobuf, current Rust reference, Go publication/copy/enrichment and Python semantics use the same tree. The removed protobuf field/name are reserved. Original bytes/name remain intact; generated descendants retain read-only provenance.
- Go enrichment publishes whole-tree metadata, sibling renames and Markdown replacements atomically. It validates exact coverage, output linkage and metadata; preserves original bytes/name; derives parsed-source metadata from root README; and fences stale retries/replaced sources.
- Index prepare/complete/fail bind generation and exact model/collection/dimension, require semantic publication, retain obsolete-index tombstones and reject stale acknowledgments. A late failure cannot undo a ready index. Vector-space reconciliation schedules live originals for rebuild.
- Processing status and manual reprocess use independent native actions and existing scoped idempotency receipts. Concurrent replay admits one generation; new source bytes conflict with the old request key. File creation, replacement and upload completion attempt dispatch after commit; durable facts survive dispatch failure.
- Native maintenance schedules expire/reconcile/delete in order with the reference timeouts/retries, a five-minute interval and overlap Skip. Reconciliation handles missing/closed/current processing runs, committed copy receipts, purges and detached forests; observations are revalidated after Temporal I/O. Current-run lookup ignores closures older than the observed admission.
- Qdrant cleanup preserves the existing lifecycle lock across the finite remote delete. Deletion filters include exact source/generation/model/dimension and collection; the final current-state check protects active rebuilds. Tombstones remain for subsequent sweeps to catch late obsolete upserts. Cleanup failure is deferred without blocking unrelated reference maintenance stages.

- Backfill supports bounded `missing`/`rebuild-index` pages, explicit `--apply` and dry-run by default, skips active processing/index workflows, revalidates observed state after Temporal I/O and preserves source/parsed publication on index-only rebuild. The staged Go command is `--backfill-processing`.
- Request-owned ZIP uses standard Go `archive/zip`, short PostgreSQL preflight/current-ancestry checks, immutable S3 readers and a bounded pipe. Stream close cancels and joins the producer before releasing its permit. Native RPC emits metadata then chunks of at most 64 KiB, with non-OK terminal failures and a runtime deadline even when HTTP/2 Send is blocked. The staged HTTP adapter preserves attachment/MIME/private-no-store/nosniff and aborts partial failures.
- The staged Go server registers private Ingest RPC with dedicated `INGEST_SERVICE_TOKEN` credentials; gateway and Workspace credentials cannot invoke it, and ingest has no public/user or storage-administration allowlist. Stored generation/attempt authority remains enforced by handlers.
- Basic search covers live originals, filename/title lookup independent of AI state, filters/sort, actor/filesystem/mount-bound keyset cursors and context omission.
- Semantic search uses dense/native BM25 RRF, PostgreSQL current-generation/vector-space/ancestry hydration, bounded evidence per source, original-file grouping and rerank-only degradation. Final authorization and hydration run after provider I/O.
- OpenRouter embeddings/rerank use official `github.com/OpenRouterTeam/go-sdk v0.9.101`. Handwritten OpenRouter HTTP, authentication and JSON models/decoding are removed. SDK requests retain the 15-second budget, tracing, cancellation and no implicit retries. Only application-specific vector/ranking validation and sanitized public errors remain. The HTTP JSON helper is Qdrant-only.
- Python parse/enrich/index activities consume generated protobuf requests/responses through `IngestRPC`. They reuse the same parser, publication and provider logic as the reference worker. `worker.py` retains `LegacyProcessor`, whose isolated `legacy_http.py` binding is removed at cutover. The shared `openlet-python` wheel remains the sole generated package.
- Actual Python Temporal workers process a Word document with an image through Go gRPC, signed MinIO transfer, enrichment and Qdrant indexing. All three completion acknowledgments are lost through the client's three RPC retries; Temporal retries each real activity, whose preparation reconciles the committed result. An index-only run uses the completed index. Fresh histories replay independently. Public semantic gRPC groups generated evidence into its original and preserves rerank-only degradation.
- Native client tests prove credential/attempt rejection, bounded dependency exhaustion and cancellation reaching the Go server context. Resource/request limits are terminal; internal dependency failures retry with a finite bound. Error bodies remain sanitized.
- Real Qdrant forwarding fixtures verify at most three retrieval batches, three evidence documents per source and 64 rerank documents; duplicate originals are not returned again on later pages.

## Measured checks

Commands run from repository root, using `/usr/local/go/bin/go` where Go is required:

| Check | Result / local evidence |
|---|---|
| Current Rust artifact integration | 12 passed; `.local/letfs-direct-output-rust.log` |
| Python non-parser suite after direct-child change | 80 passed, 11 deselected; `.local/letfs-direct-output-python.log` |
| Actual reference API processing/recovery journeys | 8 passed, including coordinated recovery and CPU-worker restart; `.local/letfs-direct-output-e2e.log` |
| Go parse/copy/replacement/public-upload regression, race-enabled | filesystem and gRPC passed; `.local/letfs-direct-output-integration.log` |
| Go atomic enrichment PostgreSQL fixtures, race-enabled | passed; `.local/letfs-enrichment-integration.log` |
| Authenticated private parse/enrichment/index gRPC | passed; `.local/letfs-ingest-enrichment-rpc.log` records the earlier parse/enrichment run; index RPC was verified in the later combined indexing invocation |
| Go indexing generation/space/source fences, race-enabled | passed; `.local/letfs-indexing-integration.log` |
| Concurrent manual reprocess and observed-state reconciliation | passed; filesystem result in `.local/letfs-processing-control.log`; the initial workflow timeout assertion was subsequently moved to actual Temporal history checks |
| Maintenance with actual PostgreSQL and Temporal, schedule idempotency, lost-dispatch recovery, terminal-run reconciliation and history replay | passed; `.local/letfs-maintenance-integration.log`; exported histories in `.local/go-phase5-histories/` |
| Go race-enabled unit/workflow suite after OpenRouter SDK migration | passed; `.local/letfs-openrouter-sdk-go.log` |
| Basic search PostgreSQL/SpiceDB filters/cursors | passed; `.local/letfs-basic-search-integration.log` |
| Semantic search with actual PostgreSQL/SpiceDB/Qdrant and controlled OpenRouter SDK endpoints, race-enabled | passed; `.local/letfs-semantic-search-integration.log`; includes grouping, stale evidence exclusion, cursor binding, dependency/degradation behavior and trash/replacement/revocation during rerank |
| Authenticated public search RPC authorization/result mapping | passed; `.local/letfs-search-rpc-integration.log` |
| Go vet with integration/workflow build tags; formatting and diff whitespace | passed after SDK and semantic fixture changes |
| Backfill dry-run/apply, cursor, unsupported/detached/generated exclusion, active workflow skipping, stale admission and index-only source/publication preservation against actual PostgreSQL/Temporal | passed; `.local/letfs-backfill-integration.log` |
| Actual PostgreSQL/SpiceDB/MinIO ZIP bytes, bounds, names, revisions, cancellation/deadline and joined-resource cleanup | passed; `.local/letfs-archive-final-integration.log` |
| Actual authenticated gRPC ZIP metadata/chunks, flow-controlled Send deadline, cancellation and terminal non-OK failure | passed; `.local/letfs-archive-final-integration.log` |
| Target server Ingest registration/readiness/credential isolation plus parse/enrichment/index handlers | passed; `.local/letfs-ingest-composition-integration.log` |
| Combined race-enabled Go unit/workflow tests after backfill/ZIP/private registration | passed; `.local/letfs-phase5-backfill-archive-ingest-unit.log` |
| Exact Qdrant deletion and concurrent rebuild admission with actual PostgreSQL/Qdrant, race-enabled | passed; `.local/letfs-index-cleanup-integration.log` |
| Complete race-enabled Go integration suite across all target packages | passed; `.local/letfs-phase5-final-integration.log` |
| Real Python activities, actual Docling Word/image parsing, native Go gRPC, signed MinIO bytes, Qdrant, public semantic RPC and committed-response loss through Temporal activity retries | passed; `.local/letfs-python-worker-retry-integration.log` |
| Generated Python client authentication, attempt fencing, transient exhaustion and Go-context cancellation | passed in the same final scoped invocation; `.local/letfs-python-worker-retry-integration.log` |
| Bounded semantic evidence and actual Qdrant batch counts | passed; `.local/letfs-semantic-search-bounds.log`, then included in the final integration suite |
| Separate Go replay schedule requiring every named history family, including Python activity histories | passed; `.local/letfs-phase5-final-replay.log`; CI exports histories before invoking `test:go:replay` |
| Final race-enabled Go unit/workflow suite, tagged vet and native server build | passed; unit/workflow output in `.local/letfs-phase5-final-unit-workflow.log`; build output is `.local/letfs-go-native` |
| Final Python non-parser suite | 97 passed, 11 deselected; `.local/letfs-phase5-python-tests.log` |
| Shared/app independent wheel packaging and isolated imports | passed; `.local/letfs-phase5-python-wheel.log` |
| Reproducible contracts and Python formatting/lint | passed; `.local/letfs-phase5-contracts.log` and final Ruff checks |
| Rebuilt reference-runtime API processing and failed-model/manual-reprocess journeys | 2 passed; `.local/letfs-python-legacy-processing-e2e.log` |

The delayed-delete race forwards to real Qdrant, waits until PostgreSQL observes the new admission blocked on the lifecycle lock, completes old deletion, then publishes a new current index and rejects the stale deletion candidate. Sibling source/generation/model/dimension points remain present. This is a provider/concurrency proof, not a mocked successful deletion.

The cook simplification pass inspected processing control and its public gRPC adapter without edits. Its integration compilation attempt overlapped the introduction of the Qdrant fixture; the unsupported wait-helper call was corrected and the actual Qdrant integration subsequently passed. The subsequent SDK simplification pass retained the application validation and Qdrant helper, exposing only the rerank model for cursor binding. The backfill/ZIP simplifier pass ran clean without edits. Scoped review then preserved typed output-limit errors and made deadline status deterministic when producer failure races timeout; final actual ZIP integrations passed after those corrections. The Python simplifier removed one redundant manifest list and retained the transport bindings. Final scoped review corrected omission of the reference HTTP root's required empty path and native retry/resource-limit classification; focused regressions failed before these corrections and passed afterward. The rebuilt reference API and real target pipeline passed after correction. No independent full-phase review is claimed.

## Handoff

- Phase 5's scoped success gate is complete. Reference Compose/Workspace/Envoy remain active and the default Python registrations still use their reference binding.
- Phase 6 must bind the worker to `Processor`, delete `legacy_http.py` and its reference-only tests, rename the existing app/module/package and update all runtime/CI/bootstrap/recovery consumers together.
- Phase 6 runtime/direct-API/proxy cutover and Phase 7 Rust removal/recovery remain fully authorized. No paid LLM evaluation or full parser-corpus rerun is claimed; the changed activity path was exercised with the actual Word/image parser and controlled providers.
