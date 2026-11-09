---
title: Implement native Leta schedules and calendar forecasts
date: 2026-11-08
summary: "Added native Schedule coordinators, shared inbox delivery, complete bounded forecasts and typed schedule tools; verified native retries and lifecycle settlement."
---

# Implement native Leta schedules and calendar forecasts

## What happened

Implemented the native scheduler core following phase14: two Workflow types, Local definition/snapshot SQL, regular native Schedule apply and inbox delivery, BUFFER_ONE, at/relative/interval/calendar specs, five runtime tools and complete bounded calendar forecasts. Real server tests establish nominal search attributes, native Workflow ID format and exclusive-start/inclusive-end preview behavior, including the exact-1000 continuation.

The SDK rejects creating limited-actions schedules with zero allowance. Past-at provisioning now creates a paused source first, applies consumed state and starts the same occurrence identity used by native actions. Delivery start acknowledgment does not wait for the inbox, allowing independent pause/delete. Review exposed shared delivery being registered only with HITL; it now belongs to common AgentActivities and constructor/standalone-worker callers were updated.

## Verification and repair

Native gates cover consumed one-shot edits/rearm, SQL/native lost completions, worker outage, BUFFER_ONE and deletion/pause after snapshot. A real SQL/Temporal box test also cancels HITL, removes the native source and archives after cleanup, using explicit existing external lifecycle fakes.

Full regression finished 250 passed, 2 failed, 5 skipped. Both failures were history tests implicitly depending on the former shared 10k model window. They now explicitly retain 10k; all six history tests pass. No full repeat after this test-only repair. Ruff/format (77 files), plan/local-link/whitespace checks pass. Owned subprocesses/containers exited.

## Next steps

Continue authenticated phase15 APIs. Phase16 sparse publication and full native WorkspaceChanges/home teardown remain open. Details and exact evidence are in plans/261108-0001-leta-agent-engine/reports/phase-14-execution.md. No commit, push, production migration or deployment was performed.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
