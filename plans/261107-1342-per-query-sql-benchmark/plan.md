---
title: Measure every application SQL execution site
status: completed
---

# Measure every application SQL execution site

Measure every application SQL execution site in Account, Workspace and LetFS, including indexed lookups, writes, maintenance and observed dynamic query variants. Start from the 233-site AST inventory and preserve existing work. Use actual SQL/parameters and transaction state from disposable integration fixtures. Collect a warm-up and three EXPLAIN ANALYZE/BUFFERS samples inside rolled-back savepoints/transactions. SQL control statements receive separately labelled actual client timing. Persist SQL, parameter types/sizes and plans; plans may embed synthetic fixture constants, and bound values are not recorded separately.

Instrumentation belongs only to the benchmark harness, enabled through a Go overlay of test fixtures. No production instrumentation, dependency, cache, schema or API change is needed for measurement. Track unmeasured sites explicitly and supply focused fixture cases until every site has measurements. Distinguish empty and affected results; a nonmatching mutation does not establish normal write cost. Existing large-data benchmarks remain necessary for scale.

- [x] Refresh inventory; implement and verify rollback-safe fixture-only measurement.
- [x] Measure three services; reconcile every site/variant and exercise missing or nonmatching cases.
- [x] Investigate measured bottlenecks; retain changes only with comparable before/after evidence and regression checks.
- [x] Review results, run affected checks, record per-site evidence and clean owned resources.

Acceptance: every inventory site has a measurement or a precise non-data control timing; totals are mechanically checked. Keep missing measurements visible until satisfied. Report SQL execution time separately from API/load performance. No commit/push.

Evidence: [per-site table](../reports/performance-261107-1342-per-query-sql.md); `.local/sql-performance/per-query/` contains raw plans, SQL, sample timings, inventory and service logs. Prior larger before/after workloads remain in the [SQL optimization report](../reports/performance-261107-1310-semantic-sql-audit.md).

Completed: 233/233 sites, 238 observed variants, 661 successful EXPLAIN observations and 14 control observations. All data sites have positive work-row evidence; one expected constraint-error probe is separated. Measured the remaining trash-query hotspot and rejected slower candidates, retaining current SQL. Full app integration runs, final rollback/supplemental/traced checks, seven Python tests, scoped Ruff/gofmt and diff checks passed. Simplifier made scoped harness edits. All owned containers/processes were cleaned. No production SQL change, commit or push.
