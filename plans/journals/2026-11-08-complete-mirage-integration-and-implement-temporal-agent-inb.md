---
title: Complete Mirage integration and implement Temporal agent inbox
date: 2026-11-08
summary: "Verified native Mirage/Redis/Monty and implemented commit-ack inbox, crash recovery and bounded agent history rotation."
---

# Complete Mirage integration and implement Temporal agent inbox

## What happened

Completed phase08's native Mirage adapter gate, including truthful blob/artifact paths, root isolation, Redis FRESH authorization/invalidation within a single command, Monty memory/host denial and shell cleanup. The final cross-language Go race gate passed with three Python journeys.

Implemented phase09's AgentWorkflow, SQL Local Activities, typed Pydantic converter, Update-with-Start client helpers and separate orchestration/runtime Worker factory. An owned worker was SIGKILLed immediately after inbox SQL commit; a new Worker recovered one message row/sequence and returned an honest receipt. Queue-pickup tests prove named yield and stop do not leave an unfinished reservation.

## Review and checks

Read-only gpt-6.1-sol/xhigh review found a rotation/stop drain deadlock. The original predicate was empirically reproduced; the corrected predicate and an SDK-real blocking-handler test pass. A graceful Worker shutdown was initially unsuitable as crash injection, so the test now kills its own subprocess. A mixed-package pytest command bypassed package async config; correctly separated invocations passed without changing settings/assertions.

Full Leta suite:110 passed,3 fixture-dependent skips,99.57s. The additional stop/drain regression passed separately0.80s. The skipped Mirage journeys separately passed through the native fixture with race detection. Four captured histories replayed; shared platform14 tests, Ruff, build, contracts and whitespace checks passed within their recorded scope.

## Next steps

Phase09 remains partially open for concrete cross-Workflow bridges/publication owned by later phases. Continue phase10's actual checkpointed LangGraph runner using the implemented inbox core. No successful placeholder runner, new workflow type, outbox, lease, receipt table or paid inference was added. Checkpoints and exact validation are under the active plan's phase08/09 execution reports. No commit/push/deployment/persistent reset. Owned test processes/containers exited; pre-existing agent-lab containers were untouched.

## Continuation: checkpointed agent runtime

Implemented phase10's real create_agent/AsyncPostgresSaver runner with sync durability, typed digest/full inbox batches, dynamic prompt/model/reasoning, independent Leti overrides, dedicated saver ownership, control interruption/recovery, an independent Temporal heartbeat and the concrete workspace/filesystem roster. Saved tool results use the existing activity log and deterministic primary-key lookup; unfinished opaque commands may repeat under the accepted policy.

The pinned graph-order gate passed before adding application hooks. A real Temporal worker subprocess was SIGKILLed after tool-result commit; its replacement reused the result and produced one effect. Other gates cover pending-model/final-checkpoint recovery, overlapping attempts, cancellation/connection-loss cleanup, more than100 model calls without per-iteration checkpoint reload, and safe yield before the upstream step safeguard. The initial managed-step annotation was corrected after that safeguard test exposed its metadata-order requirement.

Independent gpt-6.1-sol/xhigh review found a late-pause control-resume bug and ambiguous delimiter encoding of provider IDs. A pure durable-control recheck loop and JSON tuple encoding fixed both; focused regression tests and follow-up review pass. No new workflow type, command ledger, outbox, lease/fence or paid inference was added.

Final phase10 checks:18 focused runtime tests passed68.78s; full Leta suite129 passed/3 fixture-dependent skips166.55s; shared Python51 passed2.29s; lint/format/build/whitespace and46 local Markdown links passed. Owned processes/containers exited; pre-existing agent-lab containers were untouched. See the active plan's phase10 execution checkpoint for precise scope. Next: phase11 public history/typed UI projection and durable compaction; later phases retain product-tool and Redis/AG-UI ownership. Overall goal remains active; no approval, commit, push, deployment or backup prerequisite.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
