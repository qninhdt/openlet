---
title: Plan the Openlet backend simplification
date: 2026-10-31
summary: Authored a full English six-phase plan with new API E2E first and explicit removal of legacy orchestration.
---

# Plan the Openlet backend simplification

The planning session consolidated three accepted architecture notes into plans/261031-1758-simplify-backend-refactor/plan.md and six detailed execution phases. All implementation work remains pending.

The user requires all old E2E code and standalone scripts to be deleted and rewritten from scratch, no compatibility/dead code/temp scripts, squashed application baselines, meaningful real-boundary tests, complete Gin migration, and OpenTelemetry across Go/Rust/Python without an observability backend. English translation must preserve detail rather than shorten the plan.

Four read-only review lenses checked source and SDK evidence. Corrections cover owner-managed start reconciliation, file-generation/search/index consumers, durable remote cleanup, vector-space identity, safe E2E ownership, and the native pinned experimental Rust tracing plugin. A custom Activity MAC protocol was rejected under the existing private trusted control-plane boundary.

Plan structure and local links were checked; no application code, database, provider, or runtime test was changed/run. The next implementation entrypoint is /ak:cook /home/qninh/projects/openlet/plans/261031-1758-simplify-backend-refactor/plan.md when execution is requested.

AgentWiki publish skipped; this journal is local session history.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
