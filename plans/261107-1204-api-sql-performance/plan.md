---
title: API and SQL performance
status: completed
---

# API and SQL performance

Keep the accepted adjacency-list model (`parent_id`, `name`) and existing API behavior. Audit Account, Workspace and LetFS API-to-SQL paths, then optimize only demonstrated unnecessary work. Preserve authorization, current-tree visibility, artifact provenance, quota, transaction ordering and request-owned file operations. No cache, materialized path, new job, progress mechanism or dependency.

- [x] Scout HTTP/gRPC entry points, SQL families, indexes, pagination and query loops; record coverage and candidate costs.
- [x] Benchmark the before snapshot and candidate changes on disposable PostgreSQL with identical fixtures/settings; retain timings and plans.
- [x] Apply justified SQL/index/local control-flow changes, including callers/tests/docs where affected.
- [x] Re-run the benchmark against the final source; execute focused integration and broader checks, review results and remove owned containers/processes. Full integration has one documented preexisting semantic-pagination failure, reproduced with original and optimized SQL; see the report.

Before source: `.local/sql-performance/before-source`, reconstructed after an environment restart cleared `/tmp`; the report records the reconstruction and raw measurements. Preceding uncommitted file-operation changes are preserved. Results, plans and the SQL inventory are retained under `.local/sql-performance/`.

Acceptance: reproducible before/after measurements distinguish SQL execution from API latency; changed queries return equivalent results; no unmeasured performance claim; no unrelated edits or persistent database mutation. Findings/results go in [the report](../reports/performance-261107-1204-api-sql.md).
