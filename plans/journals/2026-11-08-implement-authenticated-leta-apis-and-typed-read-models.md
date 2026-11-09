---
title: Implement authenticated Leta APIs and typed read models
date: 2026-11-08
summary: Completed phase15 with native HTTP gates and started the isolated Redis replay core.
---

# Implement authenticated Leta APIs and typed read models

## What happened

Implemented creator lifecycle/canvas/chat/history/calendar APIs and recipient-safe
HITL forms over existing domain coordinators. Full Leta suite passed 260 tests with
5 native-fixture skips; final native HTTP/contract gate passed 7 tests. The native
Temporal server replaced its Java test server for worker-offline Update admission
because the latter crashes in that scenario.

## Decisions and corrections

Ordinary API key completion/expiry follows Workspace, with no operation object.
Changed-payload message retries compare persisted content after Temporal receipt.
Child pause projections use root state consistently. SDK failed start futures are
observed through its public workflow_handle API on cancellation. Independent
review identified concrete retry/pause defects; both are covered by tests.

## Next steps

Phase16 streaming primitives pass 12 pure/native Redis tests, but are not wired to
runner callbacks, sparse notifications or SSE yet. Continue that phase, then
Workspace teardown and deployment/system recovery gates. No commit or deployment.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
