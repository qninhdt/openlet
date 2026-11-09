---
title: Reconcile the accepted Leta workspace-resource plan
date: 2026-11-08
summary: "Updated all accepted reviews into a coherent English 19-phase plan, including explicit user/agent migration."
---

# Reconcile the accepted Leta workspace-resource plan

## What happened

Replaced obsolete account-as-agent and large-canonical-text execution phases in [the Leta plan](../261108-0001-leta-agent-engine/plan.md). The current plan has 19 pending phases, including human identity migration, independent workspace resources, full small-text LetFS/Mirage hooks, six Temporal Workflow types, asynchronous resource HITL, native schedules and typed history/compaction.

Final streaming is one stable Redis Stream per Leta with all children, one AG-UI SSE connection, valid-cursor suffix replay and post-Redis coalescing. Redis is required. Historical review recommendations are explicitly superseded; rejected command ledgers, permanent receipts and PG discovery polling are not execution requirements.

## Review and validation

Reused the user-selected gpt-6.1-sol/xhigh delegates for bounded cross-plan reviews. Corrected migration/config ownership references, API fields, publisher arguments and departure/archive fixture ordering. Mechanical checks covered 19 phase dependencies/pending states and 33 Markdown documents; links, fences, active tables and size limits passed. AgentKit validation returned valid=true and current-plan indexing was refreshed.

## Next step and boundaries

All accepted decisions are saved in the current plan and decision checkpoints. Implementation has not begun. No application code, dependency, schema, database, provider or deployed service changed; no commit or runtime tests. Start phase01 only when requested, then execute compatibility and integration gates. No background process was started by this rewrite. AgentWiki publish skipped; the local plan is the continuation source.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.

## Subsequent simplification

Updated the accepted plan without delegates: native TextSearch is unary with explicit completeness and Mirage fallback, and follow uses invocation-local unary range polling for tail -f. Removed the custom search stream/framing/assembly requirements; retained all applicable hooks, required Redis, AI/event SSE and existing ZIP/blob transfer contracts. The broader follow-up found no additional removable subsystem justified by concrete evidence. Implementation/runtime tests remain pending; current plan review and decision checkpoint record the result.
