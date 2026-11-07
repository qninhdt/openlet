# API and SQL performance

The adjacency-list model stays unchanged. The implementation removes a bad resolver plan, validates semantic candidates by walking their ancestors, avoids fetching every search node twice, skips move validation for same-parent rename, and adds four indexes supported by measurements. No API, role/action, workflow, quota rule, cache, materialized path, dependency or background mechanism was added.

## Audit coverage

HTTP/gRPC handlers were traced to the shared stores, including internal provisioning/processing and maintenance. Account has seven business HTTP routes and two private RPC methods. Workspace has fifteen business HTTP routes; member enrichment uses one Account summaries batch. LetFS has twenty-five business HTTP routes and the Filesystem, Ingest and Provisioning RPC services. Health/readiness is separate. The retained [query inventory](../../.local/sql-performance/query-inventory.json) contains SQL-bearing Go raw-string fragments, including pieces of concatenated statements; it is not a count of distinct SQL statements or endpoints. No application SQL owner was found outside the domain stores and LetFS maintenance.

| Owner/API family | SQL behavior and decision |
|---|---|
| Account onboarding, profile, managed account, verified emails | PK/unique Clerk lookups and bounded `ANY` summaries; keep existing checks and external Clerk calls. |
| Account relationships | Bounded PK batches/keyset rebuild; unchanged. |
| Workspace get/list/update | PK/member joins, account/workspace keysets and transactional update; indexed controls measured, unchanged. |
| Workspace membership/invitations/scope access | PK/token/pending-invitation indexes; summaries already batched. Preserve authorization, owner/member constraints and serialized mutations. |
| Workspace deletion/relationships/receipts | Existing scoped indexes, bounded rebuild/pruning and lifecycle transactions; unchanged. |
| LetFS filesystem/scopes/provisioning | PK and filesystem/scope indexes. Keep filesystem lock and mutation ordering for quota/lifecycle integrity. |
| Get/resolve/batch-stat and callers | Fix recursive resolver JOIN so index conditions remain visible to the planner. Reused by read/write, upload and processing paths. |
| List/copy child traversal | Add `(scope_id,parent_id,id)` for ID keysets; sibling-name uniqueness index remains necessary for names/path lookup. |
| Create/replace/move/restore | Keep atomic publication, quota and identity guards. Same-parent rename skips cycle/depth/subtree-height SQL because tree structure does not change. Actual moves still validate the entire subtree. |
| Cross-scope move/trash/invalidation | Per-source processing cleanup stays inside its existing transaction; indexed generation uploads and completion receipts remove repeated unrelated-row scans. |
| Trash/purge/scope/filesystem deletion | Keep bounded leaf batches and index/object cleanup semantics. Scope leaf selection measured; no replacement engine or workflow change. |
| Download/ZIP | PK reads and bounded archive preflight; per-entry validation protects the stream against intervening mutations. No speculative batching of those checks. |
| Upload/finalize/abort/expiry | Keep transfer reconciliation and locking. Add pending-upload-receipt lookup index. Expiry index candidate discarded: gain was too small in the measured case. |
| Parse/enrich/index/output uploads | Add source/generation upload index and pending-processing-receipt expression index. Manifest publication and configured output limits stay intact. |
| Filename search | Carry node metadata through the existing live traversal, removing a second node lookup per visited row. It still scans the selected subtree for substring matching. |
| Semantic search | Walk only candidate original ancestors to the selected search root; separately verify evidence ancestry, generation/readiness and filters. Keep authorization recheck after providers. |
| Dispatch/GC/backfill/maintenance | Existing due/dispatch/cleanup indexes and bounded batches remain. Manual backfill still traverses the live tree per page; it was inspected but not redesigned or benchmarked here. |

The four new indexes are `nodes_children_page`, `uploads_processing`, `processing_receipts` and `upload_receipts`. Executable DDL and the DBML agree. As accepted for this pre-production project, the initial migration is updated; no compatibility migration or persistent database mutation was performed.

## Reproduction and evidence

Run [the benchmark](../../scripts/performance/sql-benchmark.py) sequentially against before/after source trees. It loads each tree's migrations into a new Docker-owned PostgreSQL 18.6 container with 2 CPUs and 768 MiB, no published ports, then removes that container in `finally`. It uses `EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON)`, one warm-up and three measured executions, and records their median. Every measured mutation runs inside a rolled-back transaction. Both completion-receipt fixtures actually match one pending receipt.

The dataset has one 100,000-node tree (branching ten, depth five), another 10,000 root children, 90,000 inline file payloads, 100,000 processing uploads, 100,000 mixed receipts, 100,000 accounts, 10,000 workspaces and 100,000 memberships. IDs are deterministic dispersed UUIDs; production uses UUIDv7, so physical locality/page behavior can differ. Prepared resolver queries run with both forced custom and generic plans; list/copy probes also use prepared parameters. Other cases use literal fixture parameters. Server settings retain default JIT and work memory.

The initial `/tmp` snapshot was cleared by an environment restart. The baseline was reconstructed in [before-source](../../.local/sql-performance/before-source) by retaining preceding file-operation work and restoring only this task's optimizations. `paths.go`, `search.go`, `semantic_search.go` and the initial migration were unchanged by the preceding task and restored from HEAD; only the new same-parent rename condition was undone in `node_writes.go`. Both measurements were then repeated. Each JSON embeds its SQL and parameters:

```sh
python scripts/performance/sql-benchmark.py .local/sql-performance/before-source .local/sql-performance/before.json
python scripts/performance/sql-benchmark.py . .local/sql-performance/after.json
```

Raw evidence: [before](../../.local/sql-performance/before.json), [after](../../.local/sql-performance/after.json). These artifacts live in ignored local state; the numeric record below remains in this report.

## Results

All times below are PostgreSQL execution milliseconds. They exclude planning, pool/transaction setup, HTTP/gRPC, SpiceDB, providers and network. This is a controlled microbenchmark, not a production latency, throughput or percentile claim. Unchanged control differences should be read as run-to-run variation.

| SQL case | Plan mode | Before ms | After ms |
|---|---|---:|---:|
| resolve-path | custom | 797.912 | 0.556 |
| resolve-path | generic | 846.926 | 0.555 |
| resolve-id | custom | 881.237 | 0.481 |
| resolve-id | generic | 694.657 | 0.468 |
| resolve-batch-100 | custom | 686.407 | 3.793 |
| resolve-batch-100 | generic | 679.144 | 3.756 |
| list-1-0000 | custom | 1.079 | 0.942 |
| list-1-eeee | custom | 1.311 | 0.249 |
| list-5000-0000 | custom | 0.131 | 0.126 |
| list-5000-eeee | custom | 0.086 | 0.075 |
| copy-next-child | custom | 0.055 | 0.045 |
| move-subtree-height | custom | 21.720 | 22.857 |
| uploads-for-generation | custom | 9.973 | 0.040 |
| complete-processing-receipt | custom | 11.953 | 0.149 |
| complete-upload-receipt | custom | 11.622 | 0.169 |
| expire-uploads | custom | 0.470 | 0.463 |
| unscoped-child-probe | custom | 0.083 | 0.091 |
| scoped-child-probe | custom | 0.054 | 0.050 |
| name-search-selective | custom | 478.476 | 309.681 |
| name-search-all | custom | 468.238 | 327.646 |
| hydrate-0 | custom | 0.126 | 0.154 |
| hydrate-1 | custom | 142.086 | 0.304 |
| hydrate-80 | custom | 145.380 | 2.218 |
| delete-scope-leaves | custom | 0.307 | 0.342 |
| account-profile | custom | 0.052 | 0.048 |
| account-summaries | custom | 0.516 | 0.455 |
| workspace-list | custom | 0.310 | 0.343 |
| workspace-members | custom | 0.073 | 0.070 |
| insert-1000-nodes | custom | 43.310 | 46.709 |
| insert-1000-uploads | custom | 21.191 | 22.080 |
| insert-1000-receipts | custom | 6.680 | 10.834 |

The old path resolver spent about 448 ms in JIT in the retained last custom-plan run; the new plan does not invoke JIT. Its shared buffer hits fell from 23,262 to 75. Semantic hydration for 80 candidates fell from 72,797 to 2,886 buffer hits and stopped spilling this fixture's traversal to temporary storage.

Filename search avoids roughly 110,000 repeated node lookups here. Its shared buffer hits fell from 871,843 to 445,082, while carrying wider recursive rows increased temporary blocks written from 1,490 to 3,330. The measured latency improves on this machine; search remains linear in the selected subtree and its temporary I/O remains a trade-off.

Same-parent rename now removes three validation statements, including a subtree-height traversal that took about 22 ms for the 11,111-node branch in this fixture. That is removed SQL work, not a measured end-to-end rename latency. Height validation for a real move is intentionally unchanged.

| New index | MiB in measured fixture |
|---|---:|
| nodes_children_page | 9.50 |
| processing_receipts | 3.62 |
| upload_receipts | 3.80 |
| uploads_processing | 4.62 |

Together these indexes occupy 21.55 MiB after fixture loading and the rolled-back insert probes. The 1,000-row insert cases show extra write work: node insert increases about 3.4 ms, upload insert 0.9 ms, and processing-receipt insert 4.2 ms. These are isolated batch costs, including index/FK work but excluding transaction commit; they do not establish an OLTP throughput regression percentage.

## Verification

Focused integration passed for mixed path/ID/cwd/`..`/alias resolution, detached/read-only boundaries, node writes/depth/cycles, filename filters/cursors and semantic current facts/revocation. New direct hydration coverage includes nested search roots, paths/breadcrumbs, duplicate evidence, stale generation, foreign scope, generated originals, detached ancestry, empty evidence and the depth boundary. Rename coverage verifies its revision and child path; filename coverage verifies nested-root/time/MIME filters.

The mandatory scoped simplifier reviewed the benchmark script, clarified error/signal/measurement handling and corrected the upload-receipt UUID fixture. Three script helper tests passed. Broader checks are recorded when completed below.

- `pnpm check`, `pnpm build` and `pnpm test` passed after the final source changes. The script test stage includes the three new benchmark helper tests (25 total script tests).
- Full LetFS `go test -race -tags integration -p 1 ./...` finished. Server, storage/search clients, config, Temporal, gRPC and HTTP packages passed. The filesystem package failed only `TestIntegrationSemanticSearchWithOpenRouterSDKAndCurrentFacts:164`: the second semantic page was empty instead of containing one remaining source. The full suite is **not green**.
- Investigation used Go overlays, leaving production files and assertions unchanged. Both original and optimized SQL passed three isolated iterations, then each failed the same assertion in a ten-iteration diagnostic run. Those repetitions diagnose the intermittent failure; they do not replace the failed full-suite result.
- Captured provider responses establish a preexisting pagination defect: ordering changes across offset queries, and the missing source is absent before hydration. The provider-query implementation and this existing integration test are unchanged from HEAD. The optimization and failure disposition received a scoped review; no hydration regression was found. All owned benchmark/integration containers and processes exited; user services were left running.

### Existing semantic pagination defect

The provider returns the same small fixture in different orders between requests. In the failed optimized run, the one-source first page received `[invalid ancestry, A, invalid dimension, B, duplicate A, ...]` and saved offset `3`, stopping before unseen B. The next provider response at offset `3` was `[invalid dimension, duplicate A, invalid generation, invalid model, not ready]`; B had moved before the offset and was already missing from the input to hydration.

The original-SQL diagnostic independently reproduced it: the first page received `[A, not ready, invalid generation, B, ...]`, saved offset `3`, then received `[invalid generation, invalid dimension, invalid ancestry, invalid model, duplicate A]`. Again B was missing before SQL validation. The fixture has equal dense vectors and random point IDs, but attributing the ordering change specifically to RRF tie handling is not established.

Diagnostic logs are retained locally as [full integration](../../.local/sql-performance/integration.log), [original SQL probe](../../.local/sql-performance/semantic-baseline-probe.log) and [optimized SQL probe](../../.local/sql-performance/semantic-probe-10.log). Cursor correctness is a separate follow-up. This task does not sort individual provider batches, add retries, relax assertions or introduce cursor state to conceal it.

There is no benchmark of full authenticated HTTP, paid providers, sustained concurrent writes, cold cache or multiple million-node scopes. Those are limits of these measurements, not claims of verified production performance.

Follow-up: the user selected bounded semantic top-K without pagination. Cursor/offset state and continuation contracts are removed in [the subsequent implementation](performance-261107-1310-semantic-sql-audit.md); the failed historical suite above is retained as recorded evidence.
