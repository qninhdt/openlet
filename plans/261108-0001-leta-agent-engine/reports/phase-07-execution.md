# Phase 07 execution checkpoint

Status: implementation and owning validation complete. Phases01–07 are complete (7/19). No approval is pending; the overall goal remains active. Continue phase08's complete Mirage adapter and real native/cache integration.

## Implemented baseline

- `apps/letfs/internal/filesystem/text_search.go::TextSearch` authorizes current content access, resolves the selected native mount/traversal Locator and captures text/blob metadata in one repeatable-read operation. Current permission is checked again before returning buffered paths/excerpts.
- FILES uses the production `textCandidatesSQL`: live subtree including real artifact children, separate parameterized TEXT literal branch and conservative blob-metadata candidates, deterministic path/ID order and exact representation fingerprints. It never searches raw blob bytes. Short/empty/ignore-case candidates remain correct without assuming a GIN plan.
- LINES returns complete original candidate-line bytes from the same permitted representation. CRLF and final fragments remain exact; duplicate matches do not duplicate lines. Ignore-case and multiline inputs conservatively return original lines for Mirage matching. NUL literals return no matches. Invalid UTF-8, missing/foreign roots, authorization and dependency failures remain errors.
- Current native file/line/byte limits return `complete=false` without partial candidates. Buffered output is not presented as a complete top-k answer. Oversized blob-metadata representations decline the optimization instead of reading original bytes.
- Tests added before code initially failed due to missing implementation. Unit tests prove literal wildcard escaping and original-line/bound behavior. Real PostgreSQL/SpiceDB fixture covers nested TEXT artifacts, readonly provenance, exact/overinclusive candidates, blob metadata rather than blob bytes, semantic-index-disabled scopes, mount isolation, guarded append visibility and detached-artifact exclusion. Final focused integration passed9.392s with race detection after the column-list reuse/limit-handling cleanup. Log `/tmp/openlet-leta-phase07-search-baseline.log`. Final full filesystem unit tests and LetFS formatting/vet (integration/workflow tags) passed too.

## Completed API and index

`0003_inline_text_search.sql` adds pg_trgm and the partial GIN index for `storage_kind='text'`. There is no search worker, index lag, stream protocol or search session table; `allow_indexing=false` affects semantic indexing only. Unary TextSearch is exposed in protobuf/gRPC, the narrow Leta credential and handwritten Go/Python clients. gRPC checks actual serialized response size, including stat/paths, below the existing RPC ceiling. Client validation rejects incomplete results containing partial payloads, foreign scope, unsafe/duplicate/disordered paths and wrong line-result identity/mode. Existing SearchFiles/SemanticSearch behavior/admission is unchanged; mount-aware semantic integration remains phase08 work.

## Default-planner experiment

`text_search_benchmark_integration_test.go::TestTextSearchQueryPlans` uses the real current schema and exact production SQL on owned disposable PostgreSQL18.6. No hints, disabled scans or cost changes. Each query has one warmup plus five warm EXPLAIN ANALYZE/BUFFERS samples. Before/after outputs compare full ordered rows/metadata, with independent rare-result expectations excluding unrelated-scope hits. Fixtures include a128-file box, a foreign scope, an inline blob and nested artifact TEXT. Main corpora are4096×8KiB,512×64KiB and16384×8KiB documents, plus4096×8KiB high-entropy logs; each also has128 unrelated files.

| Corpus | Rare full-scope median before → after | Actual default GIN | GIN bytes after writer samples |
| --- | --- | --- | --- |
| docs8KiB | 98.718 → 6.106 ms | Yes | 1,490,944 |
| docs64KiB | 94.717 → 3.016 ms | Yes | 548,864 |
| logs8KiB | 86.989 → 68.463 ms | No; valid scan | 53,338,112 |
| docs128MiB | 363.772 → 25.671 ms | Yes | 4,792,320 |

All three document rare-query sample ranges are nonoverlapping before/after. Narrow-box rare medians also improve (92.727→2.513,93.970→1.687,380.063→10.113ms). Common/short/empty/wildcard/absent/Unicode queries preserve results; scans are allowed. These are synthetic warm measurements on shared hardware, not universal latency claims. The high-entropy GIN is154% of logical log text (53,338,112/34,603,008bytes), so there is no small fixed overhead promise.

Six paired16-row writer transactions, each concurrent with a reader and rolled back to keep the corpus identical, expose GIN update cost. Warm median writer times are3.811→12.851ms,29.511→116.661ms,4.197→20.639ms and5.691→13.399ms. This measures statement/index maintenance with concurrent reading, not committed WAL/fsync throughput or saturation. Heap/TOAST/GIN sizes, pg_stats, server settings, ordered-result sizes, samples and plans are retained in [raw evidence](phase-07-query-plans.json.gz); `gzip -dc` produces ordinary JSON. Final experiment passed107.056s; `/tmp/openlet-leta-phase07-query-plans.log`.

The first query timed out on the largest common-result case. EXPLAIN showed underestimated recursive-CTE `kind='file'` selectivity causing quadratic nested-loop candidate comparisons, plus unnecessary per-result TEXT child lookups. Semijoin membership, skipping TEXT's irrelevant child lookup, and removing the redundant kind predicate (the files FK/join already excludes directories) fixed the real SQL. First-run [raw failing plans](phase-07-original-join-plans.json.gz) remain; intermediate failures are not green checks. The final selective gate passes without forcing an index.

## Final verification

- Real PostgreSQL/SpiceDB tests cover nested artifact paths/readonly metadata, wildcards, no blob-body access, disabled semantic indexing, roots, errors and bounds. Native write/append/copy/publish/trash/restore/move become immediately searchable; uncommitted/rolled-back and detached artifacts stay absent. Revocation blocks later requests; cancellation remains an error. Final expanded focused lifecycle test passed9.882s with race detection (`/tmp/openlet-leta-phase07-search-lifecycle.log`).
- Authenticated Leta gRPC exercises FILES/LINES, typed subject, blob metadata candidates, limits and root denial alongside native mutation coverage. Focused gRPC passed11.985s. Serialized exact-bound/one-byte-overflow responses have a unit test.
- Full LetFS integration race suite passed: filesystem290.767s, Temporal48.717s, gRPC126.842s, HTTP24.294s, server25.263s. Log `/tmp/openlet-leta-phase07-full-integration.log`. This includes the final expanded native tests; no standalone build claim is made.
- Full LetFS units, Go native-client/RPC tests, formatting/vet with integration/workflow tags passed. Shared Python51 tests passed2.51s. Contracts generate/check, Ruff check/format and whitespace checks passed.
- `apps/leta/tests/test_mirage_search_compatibility.py` uses real pinned Mirage0.0.8 commands with isolated candidate fixtures. Both hooks are actually reached; deliberate extra candidates and incomplete→None preserve exact fallback command output for grep/rg literal, word, regex, Unicode ignore-case, numbered/context, wildcard and absent cases (2 tests,0.87s). This proves the library contract, not the complete Mirage–native-service adapter; phase08 connects the adapter to real LetFS/Redis and repeats boundary tests. Initial fixture writes failed because mounts default READ; the fixture now explicitly uses WRITE. Initial lint errors were corrected.
- A read-only scoped simplification/review was requested through ak-cook's live-diff gate. The final review response is recorded in the following continuation if it has not returned yet.

## Continue with phase08

Implement invocation mounts/lifetime, all adapter hooks, observations, required Redis FRESH/current authorization, semantic root support and tools. Preserve source FILE kind and named/original-ID artifact paths. Phase01 proved the tiny pinned library probe; phase08 repeats against native service. Current SHA-verified source is `/tmp/openlet-mirage-source/mirage_ai-0.0.8/` as recorded in phase06; `/tmp/leta-filesystem-review/src` no longer exists.

No production-data backup prerequisite, legacy conversion, persistent reset, commit, deployment or paid inference was introduced. All owned test/benchmark processes and containers exited; user-owned agent-lab containers remain untouched.
