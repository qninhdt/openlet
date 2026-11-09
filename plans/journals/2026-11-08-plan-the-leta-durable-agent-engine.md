---
title: Plan the Leta durable agent engine
date: 2026-11-08
summary: Rebuilt the English 18-phase Leta MVP implementation plan and resolved source-backed cross-phase review findings.
---

# Plan the Leta durable agent engine

## Work completed

Replaced the discarded planning draft with the English [Leta MVP plan](../261108-0001-leta-agent-engine/plan.md), retaining accepted brainstorm and benchmark evidence. The user explicitly selected gpt-6.1-sol with xhigh reasoning for delegated drafting and final review. Eighteen phases cover Account/Workspace authorization, LetFS redesign and Mirage, agent runtime/inbox, public history/compaction, boxes, asynchronous resource-access HITL, native schedules, APIs/AG-UI and coordinated recovery.

## Review corrections

Resolved old-command replay after Continue-As-New using the existing journal/save Activities, large TEXT delivery through old unary RPC consumers, public-only compaction input, model context metadata, one-shot schedule retry, bounded occurrence preview, snapshot/live event races and model-catalog recovery. Discovery-tool and migration-entrypoint ownership now has explicit phases. Four English review reports record source evidence and dispositions.

## Boundary and next step

Only plan/checkpoint continuation records changed. No production implementation, dependency update, database mutation, paid-model call, deployment or commit occurred. Static plan validation is separate from the required implementation/integration gates. Start Phase 1 when implementation is requested; preserve the accepted six Workflow types and avoid adding unrequested runtime infrastructure.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
