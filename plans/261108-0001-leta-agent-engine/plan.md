---
title: "Leta durable agent engine MVP"
description: "Implement the accepted workspace-resource agent engine, human identity migration, asynchronous HITL, native schedules and Mirage–LetFS integration."
status: completed
priority: P1
effort: "19 implementation phases"
branch: dev
tags: [backend, agents, temporal, langgraph, postgresql, redis, letfs]
blockedBy: []
blocks: []
created: 2026-11-08
---

# Leta durable agent engine MVP

## Outcome and scope

Deliver the accepted durable agent engine as one coherent backend before frontend work. Leta is a workspace resource; humans alone are users. Each agent has independent context/inbox execution, whole-box communication graphs, nonblocking human requests, native schedules, typed public history/compaction and Mirage filesystem access. PostgreSQL owns product data/checkpoints, Temporal coordinates six Workflow types, required Redis serves cache and one stable root-Leta replay stream, and one SSE connection carries AG-UI for root/children.

The [design contract](design-contract.md), [tool contracts](tool-contracts.md) and phase files incorporate all accepted reviews. The [decision checkpoint](../reports/design-261108-0148-leta-workspace-resource.md) preserves user decisions. Older brainstorm/review reports are historical evidence, not competing execution instructions. This plan replaces the account-as-agent and large-canonical-text drafts.

The backend implementation and required acceptance gates are complete. The [acceptance record](reports/acceptance.md) reconciles all phases with exact commands, outcomes and material not-run checks. The [system execution checkpoint](reports/phase-19-execution.md) preserves incremental failures and repairs; earlier open-gate statements there are historical.

Current production-source verification passes contracts, lint, build, unit, Workflow and integration targets. The latest integration run includes 124 Leta tests, and all six Go-owned cross-language fixture cases passed separately without Go caching. The full API/recovery suite passes 45 cases, including nine Leta journeys and restore of an accepted resource request whose grant is still pending. Fresh all-owner replay passes all four tasks; environment ownership/recovery guards pass all three tests. Paid inference, frontend rendering, deployment and a long-duration soak were not run.

The accepted execution constraints remain: no production data, no backup prerequisite, no backward compatibility and no retained legacy/dead code. Existing recovery functionality is extended and tested in owned disposable environments; it is not a prerequisite for development edits. No commit, push or deployment is authorized.

Native text read/write/search use bounded unary RPCs. Mirage follow uses invocation-local range polling for tail -f. Existing ZIP/blob transfers and AI/event Redis–SSE retain their accepted contracts. Exactly six Leta Workflow types are registered; no chat/task engine, outbox, lease or additional scheduler service was introduced.

## Phases

Current completion is derived from phase checklists by `ak plan status`; the table records order/dependencies without duplicating mutable status cells.

| # | Phase | Depends on |
| --- | --- | --- |
| 1 | [Dependencies and service foundation](phase-01-dependencies-and-service-foundation.md) | — |
| 2 | [Human-user identity and agent migration](phase-02-user-agent-migration.md) | 1 |
| 3 | [Leta resource and agent runtime schema](phase-03-leta-domain-schema.md) | 1, 2 |
| 4 | [Workspace resource access and accessible scopes](phase-04-workspace-resource-access-and-scope-view.md) | 2, 3 |
| 5 | [LetFS small inline TEXT and native reads](phase-05-letfs-inline-text-and-reads.md) | 2 |
| 6 | [Atomic small-text mutations and native node operations](phase-06-letfs-text-mutations.md) | 5 |
| 7 | [Generic native text search and default-query GIN validation](phase-07-letfs-native-text-search.md) | 5, 6 |
| 8 | [Mirage workspace adapter and complete native LetFS hooks](phase-08-mirage-workspace-adapter.md) | 4, 5, 6, 7 |
| 9 | [Temporal agent inbox and orchestration boundaries](phase-09-temporal-agent-inbox.md) | 3 |
| 10 | [Checkpointed LangChain agent runtime](phase-10-langgraph-agent-runtime.md) | 8, 9 |
| 11 | [Public history, typed inputs, and durable compaction](phase-11-history-and-compaction.md) | 10 |
| 12 | [Messaging, immutable boxes, and agent lifecycles](phase-12-messaging-and-box-lifecycle.md) | 4, 6, 9, 10, 11 |
| 13 | [Asynchronous human requests and resource access](phase-13-async-hitl-resource-access.md) | 4, 9, 10, 11, 12 |
| 14 | [Temporal schedules and calendar queries](phase-14-temporal-schedules-calendar.md) | 3, 9, 12, 13 |
| 15 | [Owner APIs and typed UI contracts](phase-15-owner-api-and-ui-contract.md) | 4, 8, 11, 12, 13, 14 |
| 16 | [Per-Leta Redis replay and AG-UI streaming](phase-16-redis-agui-streaming.md) | 10, 11, 15 |
| 17 | [Workspace deletion and Leta resource cleanup](phase-17-workspace-resource-cleanup.md) | 4, 12, 13, 14 |
| 18 | [Deployment wiring, migrations and coordinated recovery](phase-18-deployment-and-recovery.md) | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17 |
| 19 | [System acceptance and final conflict review](phase-19-system-acceptance.md) | 18 |

Execute in numbered order by default. Dependencies identify technical prerequisites, not permission for concurrent edits to contracts/migrations/shared modules. Phase16 supplies the shared publisher interface referenced by earlier phases; earlier focused tests can exercise domain behavior without claiming live-stream completion. Phase19 proves integration rather than postponing focused tests until the end.

## Acceptance criteria

- [x] Human migration preserves user UUIDs/onboarding and removes managed-account identity/member lifecycle; user/leta trust boundaries and current scope discovery work for both.
- [x] Owner → Leta → box → Leti question → independent reminder → human answer → exact requester resumes → owner receives the result works through real boundaries.
- [x] Resource owner alone approves personal-scope access to root Leta; Leti inherits, creator gets no direct foreign-scope grant, and revoke/cleanup enforce current rights.
- [x] Full small-text APIs/Mirage hooks, real nested artifact paths, image read_file, Redis cache and GIN benchmark pass their owning compatibility gates; large text stays blob.
- [x] Six Workflow histories, checkpoint recovery/compaction, native at/interval/calendar, creator API/canvas/history and per-Leta SSE satisfy phase acceptance.
- [x] Workspace teardown, coordinated migration/recovery, generated contracts and regression checks pass without rejected ledgers/pollers/fencing or unrequested product limits.

## Review and execution boundaries

[Historical plan review](reports/plan-review.md) records preimplementation consistency checks. The [acceptance record](reports/acceptance.md) supplies runtime evidence for the model/saver/Mirage path, native schedule metadata, default-planner GIN behavior and crash/restore journeys, including the limits of each fixture and measurement. Each phase retains its files, steps, validation and rollback requirements.

Deferred scope is listed in [design contract](design-contract.md#deferred): external/multi-user chat, mutable graph/task engines, full calendar editor, broader resource requests and new infrastructure beyond the accepted stack.

Implementation followed phase01 and the explicit [user/agent migration](phase-02-user-agent-migration.md). Changes remain in the working tree; no commit, push, production migration or deployment is implied by plan completion.

<!-- slug: leta-agent-engine -->
