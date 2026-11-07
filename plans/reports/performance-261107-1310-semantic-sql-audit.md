# Semantic top-K and SQL audit

Semantic search now uses one bounded provider retrieval, validates current candidates, reranks up to 64 evidence documents (maximum three per original), then returns at most the requested 1–50 originals (default 20). HTTP, protobuf, generated bindings and Go/Python clients have no semantic cursor/offset/continuation. Filename keyset pagination remains. Authorization/current-tree/generation/readiness/filter checks and degraded reranker behavior remain. No cache, workflow, progress state or new search engine was added.

## SQL coverage and changes

[The statement ledger](sql-query-audit-261107-1310.md) accounts for 233 application execution sites across Account, Workspace and LetFS. This includes repeated templates, concatenated/variable statements and three advisory-lock/savepoint controls. Simple PK/unique/ANY accesses and existing bounded publication loops were inspected, not rewritten merely to change every query. There are 83 measured cases, including both custom and generic plans for resolver/backfill. These cases cover scans, tree traversal, keysets, maintenance, admission counts, cleanup, and index write costs; they are not 233 separately benchmarked API calls.

Retained production changes in this iteration:

- Backfill keeps its original live-tree traversal and carries node name/revision in the recursive rows, removing the second node lookup. It still stops below original files and preserves active scope/filesystem, detached/generated/depth restrictions, mode filters and keyset semantics. No candidate-walk engine or planner barrier is retained.
- Scope deletion collects aborted upload identities once and uses `ANY(ARRAY(...))` against the existing pending-upload-receipt expression index. The old bulk join scanned unrelated pending receipts. The array uses memory proportional to uploads in the deleted scope; its state/expiry semantics are unchanged.
- `uploads_by_scope` covers terminal as well as pending sessions for cleanup/existence/FK probes. `uploads_user_outstanding` indexes just active user uploads for admission counts, excluding processing outputs.
- `object_deletions_by_filesystem` covers settled tombstones, which the existing backlog partial index cannot serve. `trash_original_parent` indexes non-null original-parent links so each deletion batch does not scan unrelated trash.

The pre-production initial migration and DBML are updated together; no application database was mutated. Previously accepted resolver/search/rename/index changes remain and are documented in [the preceding report](performance-261107-1204-api-sql.md).

## Reproduction

```sh
python scripts/performance/sql-benchmark.py .local/sql-performance/sql-audit-before .local/sql-performance/audit-before.json --audit
python scripts/performance/sql-benchmark.py . .local/sql-performance/audit-after.json --audit
```

The before snapshot was copied before this iteration's SQL/index changes, after semantic contract simplification and the preceding optimizations. The script loads each source's actual migration and SQL into a fresh owned PostgreSQL 18.6 container, pinned by digest, 2 CPUs/768 MiB, no published ports. Runs are sequential. Each case has one warm-up and three `EXPLAIN (ANALYZE,BUFFERS)` measurements; table mutations roll back. Container removal runs in `finally`. Raw SQL, parameters, plans, three timings, server version and index bytes are embedded in [before](../../.local/sql-performance/audit-before.json) and [after](../../.local/sql-performance/audit-after.json).

Base fixture: 100,000-node tree plus 10,000 siblings, 90,000 file payloads, 100,000 processing uploads, 100,000 receipts, 100,000 accounts/members and 10,000 workspaces. Audit extends this with 1,000 filesystems/scopes, 100,000 terminal uploads, 1,000 pending upload receipts matching those scopes, 1,000 open user uploads, 100,000 settled object tombstones plus 100 pending objects, 90,000 index tombstones, about 100,000 trash entries, and 100,000 invitations/Workspace receipts. UUIDs are deterministically dispersed, unlike production UUIDv7 locality. Payloads are deliberately small. Inventory includes its full SELECT/projection/join/payload tail, guarded by an extraction test.

## Retained measurements

Milliseconds are PostgreSQL execution-time medians, not HTTP latency or committed transaction throughput.

| Case (custom plan) | Before ms | After ms |
|---|---:|---:|
| backfill-missing-first | 436.433 | 282.668 |
| backfill-missing-sparse | 451.512 | 335.951 |
| backfill-rebuild-index-first | 495.545 | 322.989 |
| backfill-rebuild-index-late | 169.821 | 130.417 |
| upload-capacity-mixed | 13.972 | 0.351 |
| scope-abort-upload | 18.468 | 1.362 |
| scope-upload-receipts | 31.206 | 0.732 |
| scope-prune-uploads | 19.394 | 0.139 |
| scope-upload-exists | 11.150 | 0.044 |
| filesystem-prune-objects | 6.871 | 0.124 |
| filesystem-object-exists | 2.849 | 0.038 |
| trash-clear-parent | 7.898 | 0.230 |

For backfill, generic plans also improve: empty-missing first page 449.228→303.346 ms; sparse missing 428.125→304.766 ms; rebuild first page 543.283→333.112 ms. The wider recursive rows increase temporary written blocks from 1,320 to 1,709 in this fixture (about 3.0 MiB extra temporary writes); reduced node lookups still improve measured latency. It remains a live-tree scan per page. No materialized path or cached membership state was introduced.

All 83 paired case identities and root output cardinalities match. Backfill returns 0, 100 or 101 rows in the measured modes/pages. Focused integration asserts exact live-original identities and keyset pages, including zero-generation/unprocessed originals, disabled indexing, deleting resources, generated/detached ancestry and the depth boundary. Receipt plans both update exactly one fixture receipt; regression coverage separately checks which upload states/scopes/operations expire.

Four added indexes occupy about 8.97 MiB in this fixture (uploads_by_scope 1.609 MiB; trash_original_parent 6.352 MiB; uploads_user_outstanding 0.016 MiB; object_deletions_by_filesystem 0.992 MiB). The outstanding-user index is small because the fixture has only 1,000 open user sessions; it grows with that workload. Rolled-back 1,000-row writes show additional work: processing uploads 21.976→22.675 ms, terminal uploads 21.206→21.996 ms, trash 67.188→68.462 ms. Object-tombstone baseline samples were noisy ([23.209, 49.615, 48.8] ms versus [23.053, 23.727, 23.925] ms); do not infer a write speedup from that median. Added indexes consume space and write maintenance even when noise hides that cost.

## Rejected or unchanged paths

Both upward-backfill rewrites were rejected. The first validated too many candidates before sorting/limiting, regressing dense rebuild (about 1,063 ms versus 476 ms in the trial). An ordered candidate version improved original-only trees but regressed a realistic missing-mode workload with 100 source originals and 100,000 nested generated artifacts: 629.023 ms versus the original 45.549 ms. Generated artifacts normally have `not_required` publication, so mode filtering cannot remove them before ancestry checks. The final smaller metadata-carry change measures 0.802 ms on that artifact workload and 0.842 ms for rebuilding its 100 originals, with identical complete result digests. On the separate 100,000-node original tree, it measures 326.270 ms (empty missing) and 290.128 ms (rebuild), versus 458.851 and 489.941 ms before.

The supplementary [shape benchmark script](../../.local/sql-performance/backfill-shapes.py), [plans/timings/result digests](../../.local/sql-performance/backfill-shapes.json), [first rejected trial](../../.local/sql-performance/audit-rejected-unordered.json) and [ordered rejected trial](../../.local/sql-performance/audit-rejected-ordered-upward.json) preserve these decisions. Shape queries run sequentially against the same owned database with the same pinned image/resource limits, after integration tests finished; each candidate gets a warm-up plus three measurements. Final paired 83-case measurements use only the retained metadata-carry SQL.

No new due-object index: the existing partial backlog plan already finds 64 pending objects quickly despite 100,000 old settled tombstones. No new expiry, lifecycle or index-cleanup indexes: measured controls do not justify them. Dense-ready index cleanup still scans/anti-joins the due set (about 42 ms for 90,000 tombstones); changing tombstone scheduling or retention would change behavior and is outside this optimization. Archive/move queries traverse and return the affected tree; their tens of milliseconds for an 11,111-node branch do not justify a new tree model. Existing per-node publication/revalidation loops remain; these SQL measurements do not establish their network-round-trip latency.

## Verification

- Focused semantic/current-facts, hydration and filename-cursor integration passed.
- New backfill and scope-deletion receipt regression integration passed with the race detector, alongside disabled-indexing coverage.
- `pnpm check`, `pnpm test` (including all 26 script tests), and `pnpm build` passed. The benchmark extraction self-check was corrected to bind prepared-query parameters; its four focused tests and Ruff checks then passed.
- Scoped simplifier reviewed semantic retrieval/current-facts logic and benchmark helpers; no changes were needed. SQL changes received an inline review against their before queries, plans and exact-result regression fixtures. The final metadata-carry backfill also passed complete result-digest equivalence on both supplementary tree shapes.
- Full LetFS `go test -race -tags integration -p 1 ./...` passed, including filesystem, Temporal, HTTP and gRPC packages. After the final metadata-carry adjustment, race/integration tests matching `Backfill|ScopeIndexingDisabled` passed again in filesystem and Temporal, LetFS unit tests passed again, and repository check/build plus the four benchmark helper tests passed again.

## Complete measured cases

| Case | Plan | Before ms | After ms |
|---|---|---:|---:|
| resolve-path | custom_plan | 0.707 | 0.565 |
| resolve-path | generic_plan | 0.678 | 0.578 |
| resolve-id | custom_plan | 0.594 | 0.494 |
| resolve-id | generic_plan | 0.609 | 0.499 |
| resolve-batch-100 | custom_plan | 4.159 | 3.798 |
| resolve-batch-100 | generic_plan | 4.180 | 3.842 |
| list-1-0000 | custom_plan | 1.049 | 0.994 |
| list-1-eeee | custom_plan | 0.301 | 0.296 |
| list-5000-0000 | custom_plan | 0.138 | 0.124 |
| list-5000-eeee | custom_plan | 0.076 | 0.073 |
| copy-next-child | custom_plan | 0.049 | 0.043 |
| move-subtree-height | custom_plan | 23.297 | 23.010 |
| uploads-for-generation | custom_plan | 0.047 | 0.041 |
| complete-processing-receipt | custom_plan | 0.145 | 0.148 |
| complete-upload-receipt | custom_plan | 0.159 | 0.163 |
| expire-uploads | custom_plan | 0.549 | 0.542 |
| unscoped-child-probe | custom_plan | 0.088 | 0.094 |
| scoped-child-probe | custom_plan | 0.052 | 0.054 |
| name-search-selective | custom_plan | 321.111 | 316.233 |
| name-search-all | custom_plan | 331.769 | 353.220 |
| hydrate-0 | custom_plan | 0.151 | 0.151 |
| hydrate-1 | custom_plan | 0.306 | 0.311 |
| hydrate-80 | custom_plan | 2.353 | 2.277 |
| delete-scope-leaves | custom_plan | 0.369 | 0.370 |
| account-profile | custom_plan | 0.053 | 0.053 |
| account-summaries | custom_plan | 0.499 | 0.488 |
| workspace-list | custom_plan | 0.387 | 0.373 |
| workspace-members | custom_plan | 0.069 | 0.067 |
| insert-1000-nodes | custom_plan | 46.780 | 47.213 |
| insert-1000-uploads | custom_plan | 21.976 | 22.675 |
| insert-1000-receipts | custom_plan | 10.935 | 11.057 |
| backfill-missing-first | custom_plan | 436.433 | 282.668 |
| backfill-missing-first | generic_plan | 449.228 | 303.346 |
| backfill-missing-late | custom_plan | 162.118 | 127.217 |
| backfill-missing-late | generic_plan | 161.235 | 128.949 |
| backfill-rebuild-index-first | custom_plan | 495.545 | 322.989 |
| backfill-rebuild-index-first | generic_plan | 543.283 | 333.112 |
| backfill-rebuild-index-late | custom_plan | 169.821 | 130.417 |
| backfill-rebuild-index-late | generic_plan | 172.664 | 131.588 |
| backfill-missing-sparse | custom_plan | 451.512 | 335.951 |
| backfill-missing-sparse | generic_plan | 428.125 | 304.766 |
| processing-dispatch | custom_plan | 0.569 | 0.592 |
| archive-5000 | custom_plan | 0.239 | 0.233 |
| archive-2 | custom_plan | 36.161 | 28.750 |
| processing-inventory | custom_plan | 0.384 | 0.337 |
| purge-descend | custom_plan | 0.162 | 0.148 |
| purge-leaf-siblings | custom_plan | 0.225 | 0.184 |
| expire-uploads | custom_plan | 0.549 | 0.502 |
| multipart-cleanup | custom_plan | 0.022 | 0.017 |
| upload-capacity | custom_plan | 10.421 | 0.056 |
| archive-current-payload | custom_plan | 0.242 | 0.247 |
| move-transfer-subtree | custom_plan | 58.486 | 62.184 |
| discard-detached | custom_plan | 0.065 | 0.063 |
| receipt-prune | custom_plan | 0.088 | 0.089 |
| upload-capacity-mixed | custom_plan | 13.972 | 0.351 |
| scope-abort-upload | custom_plan | 18.468 | 1.362 |
| scope-queue-candidates | custom_plan | 0.136 | 0.145 |
| scope-upload-receipts | custom_plan | 31.206 | 0.732 |
| scope-prune-uploads | custom_plan | 19.394 | 0.139 |
| scope-upload-exists | custom_plan | 11.150 | 0.044 |
| filesystem-prune-objects | custom_plan | 6.871 | 0.124 |
| filesystem-object-exists | custom_plan | 2.849 | 0.038 |
| object-cleanup-due | custom_plan | 0.261 | 0.253 |
| object-cleanup-claim | custom_plan | 0.249 | 0.254 |
| index-cleanup-dense-ready | custom_plan | 42.012 | 45.701 |
| trash-clear-parent | custom_plan | 7.898 | 0.230 |
| trash-page | custom_plan | 0.244 | 0.206 |
| prune-deleted-scopes | custom_plan | 0.104 | 0.110 |
| prune-deleted-filesystems | custom_plan | 0.101 | 0.101 |
| reconcile-filesystems | custom_plan | 0.099 | 0.100 |
| reconcile-scopes | custom_plan | 0.112 | 0.122 |
| workspace-member-count | custom_plan | 0.043 | 0.040 |
| workspace-remove-relationships | custom_plan | 0.026 | 0.024 |
| workspace-rebuild-member-page | custom_plan | 0.033 | 0.031 |
| workspace-invitation-page | custom_plan | 0.082 | 0.075 |
| workspace-invitation-token | custom_plan | 0.040 | 0.040 |
| workspace-delete-invitations | custom_plan | 0.096 | 0.095 |
| workspace-receipt-prune | custom_plan | 1.169 | 1.101 |
| workspace-rebuild-page | custom_plan | 0.041 | 0.041 |
| account-rebuild-page | custom_plan | 0.043 | 0.043 |
| insert-1000-terminal-uploads | custom_plan | 21.206 | 21.996 |
| insert-1000-object-tombstones | custom_plan | 48.800 | 23.727 |
| insert-1000-trash | custom_plan | 67.188 | 68.462 |

These are warm SQL microbenchmarks on a shared host, with three measured runs per case. They do not verify cold cache, paid-provider quality, sustained concurrency, million-node/many-tenant production behavior, or full authenticated API latency. Unchanged submillisecond controls fluctuate; no performance claim is made from those differences.

All owned benchmark/integration containers and processes exited. User application containers were left running. No commit or push was performed.
