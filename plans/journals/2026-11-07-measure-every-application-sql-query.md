---
title: Measure every application SQL query
date: 2026-11-07
summary: Measured all 233 SQL sites; retained current SQL after slower trash-query experiments.
---

# Measure every application SQL query

Measured all 233 application SQL execution sites (Account 9, Workspace 43, LetFS 181), including 238 observed SQL variants. Added a test-only Go overlay tracer with rollback-safe EXPLAIN ANALYZE/BUFFERS probes and explicit missing-site reconciliation. Supplemental seeded fixtures fill missing and nonmatching cases; no production query or schema changed.

Final results: plans/reports/performance-261107-1342-per-query-sql.md and .local/sql-performance/per-query/. All instrumented app integration suites, final rollback/supplemental checks, traced Account check, seven Python harness tests and scoped formatting/lint passed. One expected restore/name-conflict probe is excluded from successful timings.

Remaining hotspot: fenceTrashed took 44.716 ms on a two-node subtree among 100,000 sibling files. Separate comparable experiments measured original 49.745 ms versus lateral candidates 102.515/178.932/177.126 ms; none retained. A larger candidate stress probe timed out and its fixture container was removed. Small-fixture query timings do not establish concurrent/API performance. Local evidence only; no commit or push.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
