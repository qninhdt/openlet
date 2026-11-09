---
title: "Phase 7: Generic native text search and default-query GIN validation"
status: pending
priority: P1
effort: 3d
dependencies: [5, 6]
---

# Phase 7: Generic native text search and default-query GIN validation

## Outcome and authority

Add native literal-content candidates and original-line reads over the representations phase 5 exposes. Index small TEXT, including generated small TEXT children, with PostgreSQL pg_trgm GIN. Mirage owns commands, regex parsing, option interpretation, final matching and fallback choice; LetFS owns authorized data access and complete/exact-or-superset contracts.

Use the [accepted design](../reports/design-261108-0148-leta-workspace-resource.md), [read/storage phase](phase-05-letfs-inline-text-and-reads.md), [mutation phase](phase-06-letfs-text-mutations.md) and [adapter phase](phase-08-mirage-workspace-adapter.md). Object-backed text remains a blob and is never indexed by reading original S3 bytes for this API. There is no backend shell parser, command dispatch table or grep-specific semantics.

Implementation and owning validation are complete. [Execution checkpoint](reports/phase-07-execution.md) records native RPC/client coverage, the passing default-planner GIN experiment, raw evidence and full race regression. Actual pinned command-hook tests isolate Mirage matching from native service correctness; phase08 connects the complete adapter to real LetFS/Redis.

## Existing evidence and owners

All paths below are relative to `/home/qninh/projects/openlet`.

| Source | Consequence |
| --- | --- |
| `apps/letfs/internal/filesystem/search.go::SearchFiles` | Searches names/titles, not complete file content; retain that public contract. |
| `apps/letfs/internal/filesystem/semantic_search.go` | Semantic top-k/reranking and current-generation hydration do not provide complete literal candidates. Retain independent authorization/degradation behavior. |
| `apps/letfs/migrations/0001_initial.sql` plus phase 5 | Existing schema has no TEXT/pg_trgm index; phase 5 adds small TEXT, this phase adds the derived index. |
| Pinned Mirage0.0.8 `mirage/vfs/base.py::files_containing` / `lines_containing` (published source reverified against the uv.lock sdist hash during phase06) | Literal candidates may overinclude but must never omit matches. Candidate-line bytes retain original newlines/order. Neither hook requires a streaming backend. The temporary old checkout path is no longer an available source. |
| `plans/reports/benchmark-261107-1919-letfs-trigram.py` and historical results | A previous PostgreSQL 18.6 benchmark still chose default Seq Scan for rare terms. Forced-index 1–2 ms diagnostics did not prove production improvement; repeat the actual Store/root query with default planning. |

Historical timings include docs 8 KiB 233.216→241.152 ms, docs 64 KiB 249.047→251.342 ms and logs 8 KiB 149.745→153.164 ms before/after GIN. They are isolated old-query evidence, not current production-query acceptance. Main heap estimates missed substantial TOAST work; actual scope/subtree joins and write load remain to be measured.

## Small-TEXT index and query

Add the next additive LetFS migration after phase 5; verify its actual number before implementation. Proposed physical index:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX files_text_content_trgm
  ON public.files USING gin (text_content gin_trgm_ops)
  WHERE storage_kind = 'text';
```

Use the real migrator's ownership/transaction rules. Verify PostgreSQL18.6 extension availability in the owned fixture. The user waived backup/production compatibility prerequisites because there is no production data. Use fresh disposable fixtures; do not reset unrelated environments or add a backup/conversion subsystem. Do not insert `CREATE INDEX CONCURRENTLY` into the transactional Goose wrapper or invent an online migration path.

- Resolve the verified typed subject's current scope access and root-restricted Locator first. Match only its live same-scope descendants, including real children beneath source files. Exclude trash/detached nodes and obsolete processing generations using phase 5's native hierarchy/provenance rules.
- Use parameterized literal `LIKE` patterns with `%`, `_` and backslash escaped; include `storage_kind='text'` so the partial index is applicable. Preserve deterministic case-sensitive semantics against exact UTF-8; no ranking/similarity/top-k substitutes for containment.
- Join indexed matches to the authorized subtree in SQL. Do not scan every scope and discard forbidden paths in Python. Return actual source/relative-child paths; there is no projection selector or sibling artifact namespace.
- GIN updates are part of the same TEXT transaction. Committed native/owner write, copy, processing publication and restore are immediately searchable; rollback is invisible. No asynchronous index job or lag allowance is added.
- Existing `allow_indexing` still controls semantic processing. Like ordinary filename/content access, literal search remains available when it is false; this physical access index does not re-enable semantic search.

## Proposed generic native API

Add unary `TextSearch(TextSearchRequest) returns (TextSearchResponse)` to `FilesystemService`. Mirage accepts a normal file list or bytes; it does not require a streaming backend. Keep search, small-text reads and mutations as bounded request–response RPCs. Do not add search chunks, continuation/completion frames, stream assembly or a larger shared RPC ceiling.

| Contract | Required behavior |
| --- | --- |
| Request | Filesystem/scope, root-restricted traversal Locator, literal UTF-8 text (up to 4096 bytes), candidate case mode, result mode FILES or LINES, file Locator for LINES, and explicit file/line/output limits. No regex, shell command or command flags. |
| FILES result | Unique real readable paths, ordinary node/source identity and representation fingerprint in deterministic path/ID order. Each result is exact or a documented safe superset; completeness has no top-k cutoff. |
| LINES result | One bytes field containing candidate original lines for one file, retaining exact bytes, CR/LF and original order. Keep long lines intact. Small TEXT is at most 1 MiB and the permitted blob metadata representation at most 4 MiB; original blob bodies are never returned. |
| Completeness and limits | Response includes `complete`. Return results only when `complete=true`. If file/line/output bounds prevent a complete answer, return `complete=false` with no partial results, and the adapter returns `None` to Mirage. Enforce caller limits on actual serialized response size with headroom below the existing 8 MiB RPC ceiling. Authentication, permission, dependency, timeout and cancellation errors remain errors, never incomplete/empty success. |
| Snapshot | Subtree, payload/metadata representation, candidates, lines and fingerprints come from one read snapshot per operation. Recheck current permission before releasing buffered excerpts after long work; permission/dependency errors propagate. |

No cross-request snapshot/cursor service or search session table is added. A bounded query returns a complete set/superset or an explicit inability to do so. Phase 8 returns `None` to Mirage when candidate output is incomplete so the library chooses its normal permitted read fallback; it raises authorization/dependency errors rather than converting them into empty matches.

## Exact/superset rules

1. Search what an ordinary read presents: small TEXT and deterministic blob metadata JSON, including actual nested artifact names/paths. Never search original object/raw binary bytes under the guise of metadata. Artifact TEXT uses the same indexed rows and actual paths as ordinary TEXT.
2. The FILES union contains indexed TEXT candidates plus metadata candidates. It may conservatively include every live blob representation; a metadata match must not be lost merely because JSON has no GIN row. For exact LINES, render/filter permitted metadata bytes using the same snapshot serializer as ReadText.
3. Case-sensitive literals use exact containment. Empty text includes every eligible FILES candidate; empty files yield no invented lines. NUL cannot occur in canonical TEXT/actual JSON bytes, so a literal NUL yields no match after current authorization. Invalid UTF-8 is rejected at the boundary.
4. Ignore-case candidate narrowing must be proven a superset of pinned Mirage's matching. The initial correct fallback is all eligible files/all original lines when that proof is unavailable, including Unicode-fold-sensitive cases. A later safe narrowing can be added only with differential evidence; no second regex/locale/word-boundary engine is required.
5. `whole_word` belongs to the Mirage hook, not the native API. It can use substring candidates because overinclusion is allowed. Multiline literals may likewise conservatively use all eligible files/lines when precise extraction cannot preserve the candidate contract.
6. Short/common terms, empty literals, unsafe Unicode folds and small subtrees may scan. Completeness does not depend on useful trigrams or a particular query plan.
7. The adapter returns `list[PathSpec]` or candidate-line bytes only from a complete unary response. An explicitly incomplete response returns `None` to the corresponding Mirage hook; never use partial results to exclude possible matches. Decline safe line extraction when the actual readable representation can contain NUL. Original binary payload is never substituted for its NUL-free metadata representation.
8. Mirage may read whole candidate files for line/byte/column positions, context, multiple patterns or inverse matching. Accept its actual fallback behavior; do not add backend option-specific APIs or claim all regex execution is pushed down.

Native operations provide coherent per-operation reads. Compound shell commands have ordinary concurrent-filesystem semantics, not a serializable snapshot across later reads. Current FRESH tokens and backend permissions remain required, without a global filesystem revision or changefeed.

## Files and callers

| Action | Paths | Change |
| --- | --- | --- |
| Add | `apps/letfs/migrations/0003_inline_text_search.sql` | Derived partial GIN index/pg_trgm; confirm next migration number. |
| Add | `apps/letfs/internal/filesystem/text_search.go`, `text_search_test.go`, `text_search_integration_test.go` | Literal escaping, root query, metadata union, complete candidates/lines and explicit output limits. |
| Modify | Phase-5 `text_storage.go`, `representations.go`, `tree.go` and phase-6 `text_mutations.go` only where needed | Reuse bytes/tokens/live hierarchy; no duplicate canonical representation or async search state. |
| Modify/add | `packages/contracts/proto/openlet_api/letfs/v1/letfs.proto`; `apps/letfs/internal/transport/grpc/text_search.go` | Generic literal query modes, bounded unary response and completeness/error mapping. |
| Modify | `packages/go/clients/letfs/operations.go`; `packages/python/src/openlet/clients/letfs.py`; client tests | Validate response completeness, exact candidate-line bytes and result scope/root/identity. No stream assembly. |
| Modify | `apps/letfs/cmd/server/main.go` and native admission tests | Admit TextSearch for verified allowed subject/service; original blob transfer remains unavailable to Leta. |
| Add | `apps/letfs/internal/filesystem/text_search_benchmark_integration_test.go` | Real schema/Store query benchmark with actual scope and box-root predicates. |
| Modify | `docs/api-contracts.md`, `docs/data-model.md`, `docs/operations.md` | Literal vs semantic boundary, complete/superset semantics, index cost and reproducible performance route. |

Phase 8 implements hooks; it does not invent a second exact-search service. Serially regenerate/integrate shared proto/client changes with phases 5 and 6. Existing SearchFiles/SemanticSearch consumers remain intact.

## Implementation steps

- [x] Add independently expected text/metadata/nested-artifact fixtures that filename-only or semantic top-k search would miss. Include long lines and more matches than the configured unary output bound.
- [x] Implement the parameterized live scope/root literal query without GIN first and record the real query baseline on an owned disposable fixture.
- [x] Add the index migration and transactional visibility tests for write/append/copy/publish/rollback/trash/restore/move.
- [x] Implement unary FILES/LINES responses with intact line bytes, explicit completeness/output bounds, cancellation and typed authorization/dependency errors. A bound exceeded returns no partial candidate payload; adapter fallback preserves correctness.
- [x] Integrate phase 8's real pinned `files_containing`/`lines_containing` calls. Differentially test regex/Unicode/flag cases at the library boundary; the backend continues receiving only generic literals.
- [x] Run the production-query experiment below and retain raw results in the execution report directory. Investigate planner/TOAST/selectivity issues in the actual SQL, not a favorable diagnostic query.
- [x] Keep the selective-query performance gate open on failure. Review permission/completeness/data leakage, regenerate contracts and update docs from measured behavior.

## Default-query performance gate

Reuse the historical seed/corpus generator as evidence without overwriting its results. The new native benchmark loads current LetFS schema and invokes the production Store query on PostgreSQL 18.6:

- Large granted scope and narrow box subtree inside a larger home, unrelated scopes and nested artifact TEXT. Compare identical data/results before and after the index with the same actual scope/root SQL and default planner settings.
- At least existing 4096×8 KiB and 512×64 KiB document corpora, high-entropy logs and a 16384×8 KiB selective corpus. Every TEXT fixture must fit the configured inline limit; do not load artificial 100 MiB canonical TEXT.
- Rare terms at the historical 0.78125% rate, absent/common/two-character terms, escaped wildcard characters, empty/Unicode candidates and metadata union cases.
- `ANALYZE` both states; collect `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, pg_stats, table/main/TOAST/index sizes, result equality, bytes returned and one warmup plus at least five paired warm samples/medians/variance.
- One controlled writer/read workload to expose GIN write cost/contention and transactional correctness. Track and remove only owned fixture processes/containers; never benchmark on persistent development or production data.

Acceptance requires equal complete results/no cross-root leakage, repeatable latency improvement beyond sample variance for a selective sufficiently large scope/root query, and an actual default plan using the intended GIN path there. Common/short/small-root scans are valid. No global `enable_seqscan=off`, mandatory hint or forced diagnostic plan can satisfy this gate. Report space/write cost honestly; historical high-entropy GIN size was 143.7% of logical text, so a low fixed overhead promise is unsupported.

## Behavior tests and commands

| Scenario | Required result |
| --- | --- |
| Literal/metadata completeness | A content hit absent from name/semantic results still appears, including real artifact children and blob metadata terms. |
| Escaping/case/Unicode/newlines | `%`, `_`, backslash, empty, short, Kelvin sign, long s, dotted/dotless i and multiline cases never yield false-negative candidates. |
| Original lines | CRLF/final fragment/very long line/duplicate matches preserve exact bytes/order without invented separators. |
| Permission/root/generation | Foreign/other-box, detached, trashed, obsolete-generation and revoked data cannot leak candidate paths/excerpts. |
| Immediate visibility | Commit/rollback/append/copy/publish/trash/restore/move reflect current data without async lag. |
| Disabled/degraded semantic path | Literal access remains correct while `allow_indexing=false` or semantic providers are degraded. |
| Bound/error handling | At the response bound, complete results preserve exact bytes; exceeding it returns complete=false with no results and triggers Mirage fallback. Permission/timeout/cancel/dependency errors propagate. No oversized unary message or partial list is presented as complete. |

Future commands; new test names are implementation deliverables:

```sh
pnpm contracts:generate
pnpm contracts:check
go -C apps/letfs test ./internal/filesystem -run 'Test(TextSearch|Literal|TextLines)' -count=1
go -C apps/letfs test -race -tags integration ./internal/filesystem ./internal/transport/grpc -run 'Test(TextSearch|TextSearchQueryPlans|Search|Semantic|Scope)' -count=1
go -C apps/letfs test -tags integration ./internal/filesystem -run '^TestTextSearchQueryPlans$' -count=1 -v
uv run --locked --package openlet-python pytest packages/python/tests/test_letfs_clients.py -q
go -C packages/go test ./clients/letfs
pnpm --filter @openlet/letfs check
pnpm --filter @openlet/letfs test:integration
```

## Acceptance and rollback

- [x] Unary FILES is complete/exact-or-superset or explicitly incomplete; unary LINES preserves original candidate line bytes and order, with no custom stream protocol.
- [x] Real PostgreSQL/gRPC tests establish current typed subject, root, liveness, generation and transactional visibility.
- [x] The actual default-query selective GIN gate passes with raw evidence; valid scan cases and write/index costs are recorded.
- [x] Mirage owns command/regex/fallback behavior, and no original S3 text/body is exposed or indexed by this API.

No backup or persistent-environment reset is a prerequisite or part of this implementation. If a hook implementation is faulty, remove that hook admission and let Mirage use its correct ordinary reads while the backend defect is fixed. This is normal library fallback, not a Redis bypass/degraded service mode. Keep required Redis and current authorization checks. A derived index can be removed through the owning migration while retaining TEXT; do not route exact candidates to semantic top-k or relax completeness.
