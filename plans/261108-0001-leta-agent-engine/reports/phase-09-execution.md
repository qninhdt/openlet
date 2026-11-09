# Phase 09 execution checkpoint

Status: AgentWorkflow core implemented; phase09 remains in progress because cross-Workflow bridges/publication land with their concrete owning workflows. Next implementation work is phase10's real runner, not another inbox design round. No approval is pending and the overall goal remains active.

## Implemented

- Serializable Pydantic workflow/input/result/control DTOs; Leta's Temporal connection explicitly selects the SDK Pydantic converter. The shared connect helper retains its existing default for other services.
- `AgentWorkflow` accepts Update-with-Start on a stable agent Workflow ID. Receive locks only SQL admission/latest-sequence merge. It commits while a runtime Activity is busy, merges bootstrap races without overwriting newer arrivals, keeps pause/idle long lived, and serializes runtime invocations.
- SQL Local Activities bootstrap state, persist one generic inbox row, and save named run control. SQL errors retry through Temporal; domain validation/conflict errors stay nonretryable. No outbox, polling receiver, leasing/fencing or new receipt table exists.
- The existing bootstrap Activity reserves a chosen run before runtime dispatch. This closes the ordinary queue-pickup gap: a yield may arrive before the runtime Worker has started. Stop waits for cancellation/cleanup, then uses existing run control to cancel an unfinished reservation without overwriting an already-terminal result. No extra Workflow/Activity type or table is introduced.
- Active history rotation requests yield, preserves business run ID and continues after saved-boundary return. Idle/paused rotation drains handlers. Stop breaks the drain predicate before waiting for completion, avoiding a confirmed circular wait. Bootstrap and paused-result refresh preserve concurrent pause/resume decisions.
- Client helpers start/control/deliver; `agent_workers` owns separate bounded orchestration/runtime SDK Workers. It requires a concrete runner callable; there is no executable no-op graph runner or premature production CLI. Later lifecycle/HITL/schedule bridges and sparse Redis publisher remain their owning phases' integration work.

## Verification so far

- Six SDK-real workflow tests passed13.43s: busy receipt/dedup, bootstrap race, paused receive/resume/invalid target, paused rotation, active same-run rotation and terminal nonretryable runner failure. A seventh SDK-real test reproduces the rotation/draining/stop ordering without timing thresholds and passed0.80s.
- Four retained, fixture-only histories cover busy receive, pause and paused/active Continue-As-New. All four replayed without executing SQL or model effects; combined replay/lifespan tests passed11 cases0.89s.
- Real PostgreSQL+Temporal tests plus all Store tests passed21 cases78.66s before the final production Worker-factory wiring check. They include actual SIGKILL of an owned worker immediately after SQL commit/before Local Activity return, replay on a new Worker to one row/sequence, changed-body rejection under a distinct Update ID, no receipt with Worker absent, and yield/stop before runtime pickup. Final full-suite result is recorded on continuation below.
- Shared Python platform tests passed14 cases0.25s. Ruff check/format and wheel/sdist build passed. A mistakenly combined cross-package pytest invocation bypassed package async configuration and failed collection/execution; separate package invocations above passed. No assertions or async settings were weakened.
- First attempted crash injection used graceful SDK shutdown, which waits/retries Local Activities and is not a process crash; that test failed and was replaced by the actual owned SIGKILL process. No production retry workaround was introduced.
- Scoped read-only gpt-6.1-sol/xhigh review identified the real rotation/stop drain cycle. The reviewer empirically reproduced the deadlock with the original predicate and verified the correction without writing files; the SDK-real seventh test independently covers it. Final review found no unresolved concrete defect or useful simplification.

## Final checks

- Full Leta suite passed110 tests99.57s. The three fixture-dependent Mirage tests skipped in the direct Python invocation; all three separately passed through the native Go race gate recorded in phase08. The newly added deterministic rotation/stop test passed separately0.80s after collection of the full run;111 tests are therefore covered by these two runs, without claiming one111-test invocation.
- The full run includes final production two-Worker-factory wiring, real SIGKILL recovery, queued-run yield/cancellation, Store SQL tests and retained history replay. No source change followed the last targeted passing rotation/stop test other than identical-schema removal of a redundant inherited DTO field and documentation.
- Ruff check/format, shared14-test platform suite, Leta wheel/sdist build and whitespace checks passed. Contracts check passed during phase08; phase09 changed no protobuf/OpenAPI contract.
- Owned crash process, SDK test servers and disposable containers exited. Only pre-existing agent-lab containers remain. No migration/reset touched a developer environment.

## Remaining owning work

Phase10 must execute the real checkpointed create_agent graph, heartbeat and resource cleanup, collect steering at safe protocol boundaries, honor saved yield/pause flags, and reuse terminal run/checkpoint results. Its runner may start an already-reserved run idempotently. Phase11 adds public history/compaction; phases12–14 add concrete bridge Activities/lifecycle/HITL/schedules; phase16 supplies sparse resource notifications. These are not represented by successful placeholders.

Use the current six-type Activity map; do not resurrect account-agent identity, tool approval, command journals, leases or per-token Activities. Existing cross-service schemas and earlier uncommitted changes are preserved. No paid model request, persistent reset, commit, push or deployment occurred. Owned test processes/containers must be reconciled after the final running test exits.
