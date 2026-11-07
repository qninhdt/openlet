---
title: Semantic top-K and measured SQL cleanup
date: 2026-11-07
summary: "Removed semantic pagination and retained measured backfill, admission and cleanup SQL improvements."
---

# Semantic top-K and measured SQL cleanup

## Changes

Semantic search retrieves once, validates candidates, reranks before output limiting and returns no continuation. HTTP/protobuf/Go/Python contracts and tests match. The affected Python search paths also now pass and validate their actual scope ID.

Audited 233 application SQL execution sites and measured 83 workload/plan cases. Retained metadata-carrying live-tree backfill, indexed bulk upload receipt completion and four cleanup/admission indexes. Kept the adjacency-list tree, existing publication guards and unchanged indexed operations.

## Evidence and correction

The first upward-backfill rewrite regressed dense rebuild; the benchmark exposed it, and ordered candidate processing corrected that case. A supplementary realistic artifact workload then exposed a second regression in that candidate version. Both upward rewrites were discarded; carrying metadata through the original live traversal improved both shapes with identical result digests. The expanded benchmark extraction test caught an incomplete inventory SELECT during development; full projection assembly is now checked. Its prepared-query self-check was subsequently updated to bind actual parameters before checking completeness.

Focused semantic and SQL regression integration passed. The final measurement and verification record is [the report](../reports/performance-261107-1310-semantic-sql-audit.md); [the ledger](../reports/sql-query-audit-261107-1310.md) records every execution-site disposition. All data measurements use owned disposable databases, with mutation probes rolled back. No commit or push was requested.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.

AgentWiki publish skipped.
