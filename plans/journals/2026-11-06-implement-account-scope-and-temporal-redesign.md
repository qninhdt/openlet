---
title: Implement account scope and Temporal redesign
date: 2026-11-06
summary: "Completed the reviewed replacement, legacy cleanup and real-service acceptance."
---

# Implement account scope and Temporal redesign

Implemented the accepted account identity, workspace membership and filesystem/scope boundary without adding account disable, owner transfer, a credential system or copy progress/resume machinery. Removed mounting, logical quota buckets, workspace-count limits, dynamic role policy and obsolete wire/SDK/workflow surfaces. Preserved the existing inline-only work.

The twelve service-owned Temporal workflow trees now use the reviewed child workflows and bulk activities. Real fault tests verify SQL/graph acknowledgement loss, worker replacement, overlapping deletion and exact quota accounting. Final review also blocked queued scope grants after workspace deletion.

Contracts, check/build/unit/integration, all three workflow suites and native replay passed. Fresh-image API E2E passed 34/34; all twelve workflow types replayed from 18 fresh histories. Startup/cancellation/restore harness checks passed 3/3 with no skips. An ingest build stalled in Xet; direct HTTP worked, and disabling Xet only during model prefetch completed the same pinned model build.

All five plan phases are complete. Test-owned resources were cleaned up. No persistent environment reset/migration, paid external smoke, commit, push or deployment was performed. Copy retains partial results on failure by the accepted contract; baseline schema replacement targets fresh databases.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
