---
title: API SQL performance
date: 2026-11-07
summary: Measured adjacency-list optimizations; retained and diagnosed an existing semantic pagination failure.
---

# API SQL performance

Kept adjacency-list storage and the existing API/security/quota behavior. Audited Account, Workspace and LetFS SQL paths. Fixed resolver JOIN planning, hydrated semantic candidates through ancestor walks, removed repeated filename-search node fetches, skipped structural validation for same-parent rename, and added four measured indexes.

Reconstructed the lost temporary baseline after an environment restart and reran 31 comparable SQL cases. Path resolve measured 797.912→0.556 ms; hydration of 80 candidates 145.380→2.218 ms. Indexes cost 21.55 MiB in the fixture and additional insert work; wider filename traversal rows increased temporary I/O. Full details and raw evidence routes are in plans/reports/performance-261107-1204-api-sql.md.

pnpm check/build/test and focused integration passed. Full LetFS race/integration failed one existing semantic-pagination assertion. Diagnostic runs reproduced it with both original and optimized SQL: provider ordering changed across offset queries, dropping an unseen source before hydration. Kept assertions and cursor behavior unchanged; recorded the correctness follow-up instead of expanding the SQL task. Required simplification and scoped review completed. All owned processes/containers exited; no commit/push or persistent application database mutation.

AgentWiki publish skipped; local journal only.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
