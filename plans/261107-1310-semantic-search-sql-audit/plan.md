---
title: Bounded semantic search and SQL audit
status: completed
---

# Bounded semantic search and SQL audit

Semantic search returns top-K originals from one bounded candidate request with no pagination. Remove its cursor/offset/seen-chain contracts, code and tests across HTTP, gRPC and SDKs. Preserve filters, current-tree/generation/readiness checks, provider failure behavior and authorization recheck. Filename search keeps keyset pagination. Keep the existing candidate (80), rerank (64), evidence-per-source (3), and output (default 20, maximum 50) limits; rank before applying the output limit. No new engine, state, dependency, cache, workflow or data model.

Then audit every application-owned SQL statement in Account, Workspace and LetFS. Reuse the preceding inventory and measured baseline, classify simple indexed/bounded statements, and benchmark the remaining scans, loops, batch writes and maintenance operations. Only retain changes with equivalent results and measured benefit. Use isolated owned disposable PostgreSQL containers; preserve fixtures/preimages before mutations and never change application databases. Preserve all preceding uncommitted work.

- [x] Remove semantic pagination throughout implementation, generated contracts, clients, tests and owning docs; focused verification.
- [x] Complete a per-statement SQL disposition ledger and benchmark remaining workload families under equivalent before/after conditions.
- [x] Apply justified optimizations with regression checks and recorded read/write/index trade-offs.
- [x] Review, run affected integration and repository checks, reconcile docs/results and clean owned processes/containers.

Acceptance: semantic search performs one bounded retrieval and no continuation, outputs at most limit distinct current originals after reranking; filename pagination still works. Every application SQL statement has a reasoned disposition; every retained SQL optimization has before/after evidence. Do not claim API/load performance from SQL microbenchmarks. No commit/push requested.

Evidence: [measurement report](../reports/performance-261107-1310-semantic-sql-audit.md), [233-site SQL ledger](../reports/sql-query-audit-261107-1310.md). Focused semantic/SQL regressions, full LetFS race/integration, repository check/test/build and final backfill-specific rechecks passed. Four indexes and two small SQL rewrites retained; both upward-backfill rewrites rejected after workload benchmarks. Owned processes/containers exited; no commit/push.
