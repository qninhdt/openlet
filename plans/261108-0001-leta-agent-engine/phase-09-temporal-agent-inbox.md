---
title: "Phase 09: Temporal agent inbox and orchestration boundaries"
status: complete
priority: P1
effort: 4d
dependencies: [3]
---

# Phase 09: Temporal agent inbox and orchestration boundaries

## Outcome and dependencies

A creator, tool, schedule, or HITL adapter receives a durable PostgreSQL inbox receipt through **Temporal Update-with-Start**. A busy agent accepts steering without blocking receive handlers; one long-lived AgentWorkflow serializes that agent's graph invocations. Idle/pause never ends the agent; only explicit lifecycle deletion stops it. Root Leta is a workspace resource, never a human user or workspace member; Leti inherits the root subject and has no independent grants.

Depends on [domain schema](phase-03-leta-domain-schema.md), after its foundation/migration gates. The real graph Activity lands in [phase 10](phase-10-langgraph-agent-runtime.md); register it only when implemented, never a successful no-op placeholder. Lifecycle, HITL, and schedules implement the mapping below in phases 12–14. [Accepted design](../reports/design-261108-0148-leta-workspace-resource.md), including items 35–42, supersedes historical review recommendations.

Implementation is in progress. The AgentWorkflow/SQL/client/worker core and focused runtime tests are implemented; see [execution checkpoint](reports/phase-09-execution.md). The actual graph runner remains phase10; shared bridges for lifecycle/HITL/schedule owners and sparse Redis resource publication are completed with their owning later phases, without placeholder implementations here.

## Current evidence and exact files

`apps/workspace/internal/temporal/relationships.go::WorkspaceChanges` already registers a serialized Update handler, awaits AllHandlersFinished, and Continue-As-News. Its `Mutate` client currently regenerates a key; [phase 04](phase-04-workspace-resource-access-and-scope-view.md) owns preserving downstream mutation identity. Pinned Temporal 1.35.0 `_client.py:944–955`, `_workflow.py:1080–1091`, and `workflow/_context.py:175–204` support the Client/history APIs below. Read source cache: `/tmp/leta-engine-review/src`; execution compatibility remains a phase-01 gate. Do not copy the lab's Signals/in-memory inbox, closed idle Workflow, nested AgentRun compatibility Workflow, or waiting-for-human agent state.

| Action | Absolute path | Responsibility |
|---|---|---|
| New proposed | `/home/qninh/projects/openlet/apps/leta/src/leta/temporal/agent.py` | `AgentWorkflow.run/receive/control`: main loop and handlers. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/src/leta/temporal/activities.py` | `bootstrap_agent`, `persist_inbox`, `save_run_control`: bounded SQL Activities. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/src/leta/temporal/bridges.py` | `start_agent`, `control_agent`, `deliver_agent_input`, `change_schedule`, `settle_hitl`: Client bridges; phase16 `publish_resource_event` regular wrapper. |
| Modify phase-01 file | `/home/qninh/projects/openlet/apps/leta/src/leta/worker.py` | Actual SDK Worker registration, two queues, shutdown. |
| Modify phase-03 files | `/home/qninh/projects/openlet/apps/leta/src/leta/domain.py`, `/home/qninh/projects/openlet/apps/leta/src/leta/store.py` | Receipt/bootstrap/control DTOs; inbox/bootstrap SQL methods. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/tests/test_agent_workflow.py` | Time-skipping SDK Workflow tests. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/tests/test_inbox_integration.py` | Real Temporal+PostgreSQL receive/restart tests. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/tests/test_temporal_replay.py` | Replayer fixtures and compatibility gate. |

## The six Workflow types and complete Activity map

This table is canonical for the plan. **L = Local Activity; R = regular Activity.** Each command calls only the needed subset. Pure validation, bounded fan-out, timers, and await logic remain Workflow code. No Workflow per model call, tool call, or communication edge.

| Workflow and lifetime | Activity | Type | Retry boundary |
|---|---|---|---|
| AgentWorkflow(agent_id), until delete | bootstrap_agent | L | Read root/agent state/latest seq/run pointers; reserve the selected new run before runtime dispatch, so yield/stop also work before Activity pickup. No lifetime transcript. |
| | persist_inbox | L | One short SQL transaction validates lifecycle/routing and commits message+seq. |
| | save_run_control | L | Set yield_requested on the named unfinished run, or cancel any still-unfinished reservation after runner cleanup on stop. Terminal outcomes remain unchanged. |
| | run_agent | R | Whole create_agent invocation, checkpoint recovery, model/tools, public activity, Mirage, stream; heartbeat/cancel. |
| LetaLifecycleWorkflow(leta_id), long-lived coordinator | save_leta_change | L | Persist initializing/config/pause/active/deleting/archived and return resource-ID snapshot. |
| | publish_leta_resource | R | Reconcile only Leta-owned `leta:L#workspace/creator` tuples; remove only in explicitly admitted workspace teardown or terminal W-deleting initialization cleanup. |
| | ensure_leta_home | R | Call Workspace `EnsureLetaHomeAccess` for ordinary home storage, home_of, root editor and shared editor defaults. |
| | cleanup_leta_access | R | Call Workspace `CleanupLetaAccess` to remove received scope grants, retaining archive home/history policy. |
| BoxLifecycleWorkflow(box_id), long-lived coordinator | save_box_change | L | Whole immutable graph/lifecycle transaction and resource snapshot. |
| | ensure_box_home | R | Idempotent LetFS home creation/identity validation. |
| | trash_box_home | R | Trash after runtimes stop, reconcile already-trashed known node. |
| HumanRequestWorkflow(request_id), one request | open_hitl_request | L | Persist validated request/deadline/IDs. |
| | resolve_hitl_request | L | Atomic responder/status/deadline decision; non-grant outcomes included. |
| | grant_requested_access | R | Revalidate actual human owner/current workspace-resource binding; call Workspace grant to `leta:L`. |
| | save_hitl_outcome | L | Persist real grant success/permanent failure; no fifth request status. |
| ScheduleChangesWorkflow(schedule_id), long-lived coordinator | save_schedule_change | L | Normalize/persist definition/pause/delete once. |
| | apply_temporal_schedule | R | Native Schedule create/update/pause/delete, stable ID, BUFFER_ONE. |
| ScheduleDeliveryWorkflow, one occurrence | load_schedule_occurrence | L | Snapshot valid schedule/target/content/original scheduled_at/stable message ID. |
| | deliver_agent_input | R | Await receiver's PostgreSQL inbox commit or explicit deleted-target skip. |

No account provisioning, name/profile synchronization, membership or leave Activity remains. Leta owns resource tuples; Workspace owns home/default and foreign-scope grant publication. `publish_leta_resource` is not a general scope writer: ordinary archive retains its tuples, while phase17's explicitly admitted W teardown reuses that Activity's remove mode after stop/settlement/grant cleanup and before stop acknowledgement. Already-admitted trusted cleanup never waits on locked WorkspaceChanges.

Shared regular Activities, referenced by any coordinator that needs them:

| Activity | Contract |
|---|---|
| `start_agent(agent_id)` | Start/use-existing **top-level** AgentWorkflow `agent/<id>`, never a long-lived child bound to box lifetime. |
| `control_agent(agent_id,action,run_id?)` | Client Update for pause/resume/stop; stop waits for runner cleanup. Yield requests use the same control path to set the current run's short SQL yield flag. Heartbeat while waiting. |
| `change_schedule(schedule_id,change)` | Call ScheduleChangesWorkflow Update and await applied result. |
| `settle_hitl(request_id,reason)` | Cancel pending request; accepted decision must finish grant+outcome before this returns. Never rewrite accept as cancel. |
| `deliver_agent_input(agent_id,envelope)` | Client receive Update-with-Start; return after commit, or skipped when parent/target is deleting/archived. |
| `publish_resource_event(leta_id,kind,resource_id)` | Post-commit sparse domain reference through phase16's ordinary publisher into the stable root Redis Stream; no business mutation or token production. |

Workflow-to-Workflow Update calls go through those regular bridge Activities. Python external Workflow handles support signal/cancel, not Client execute_update. API/tools outside Workflow code may call the Client directly; do not wrap every send_message in another delivery Activity inside run_agent.

Local Activities perform only bounded Leta SQL and in-process validation. Remote identity/authz/provisioning belongs at ingress or in the appropriate regular Activity. A Local Activity can execute again if its marker was not committed; SQL IDs/preconditions remain retry-safe. No Local heartbeat or long remote waits. Temporal owns ordinary command retry; do not add a two-stage command journal or an extra completion save solely for historical command deduplication.

### Post-commit resource notifications

Phase16 implements shared regular `publish_resource_event` using its process-owned Redis publisher; phase09 owns this Activity map/registration contract only. This is a release integration gate, not a schema dependency on phase16. After committed lifecycle/control, box, HITL decision/outcome or schedule-definition changes, the owning Workflow invokes it with root ID and a typed sparse resource reference. Phase16 always emits the standard AG-UI CUSTOM envelope with agent_id (relevant requester/owner agent or root) and run_id (null when no run owns the change); no mutable tool/model snapshot enters Workflow state. Existing Client bridges do not cover all final commits, so notifications are not hidden inside unrelated start/delivery/grant effects.

Only the publisher gets its own bounded timeout/retry. On exhausted publication, record an explicit transport diagnostic and continue the already-committed business result/required cleanup; do not throw a business failure, repeat earlier effects, leave deletion blocked or claim event delivery. PostgreSQL stays authoritative; reconnect refreshes the domain snapshot even with a valid text cursor. Redis remains required for startup/readiness; this bounded publication handling is not optional infrastructure or an outbox/poller. API/tools/runtime outside Workflow call that same ordinary publisher directly. Basic inbox and run/token events stay in the existing API/runtime publisher path; no per-token Activity or extra publication wait is added to persist_inbox's commit receipt/receive lock.

## Receive contract and acknowledgement

Ingress authenticates caller, resolves recipient and routing, validates the source adapter/envelope, assigns one stable message ID, and makes this SDK1.35 call:

```python
operation = WithStartWorkflowOperation(
    AgentWorkflow.run, bootstrap_input,
    id=f"agent/{agent_id}", task_queue="openlet-leta",
    id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
)
receipt = await client.execute_update_with_start_workflow(
    AgentWorkflow.receive, envelope,
    start_workflow_operation=operation, id=str(envelope.id),
)
```

The operation object is single-use; recreate it for a transport retry while preserving workflow/update/message identity. SQL message-ID comparison remains the final dedup authority across Continue-As-New or a timed-out Update whose outcome is unknown.

The receive Update uses a short `asyncio.Lock` **only around persist_inbox and latest_seq merge**:

1. Persist through the phase-03 commit-ordered transaction: lock the recipient row, recheck message identity, allocate/increment inbox_seq and insert the one messages row. The next recipient sequence cannot commit first. Source/root/box gates are checked in the owning transaction; avoid shared-to-update lock upgrade when root is also recipient.
2. Merge `latest_seq=max(current,saved.seq)` after successful commit.
3. Notify the main loop and return committed receipt. Do not await model processing or reply.

Do not hold the receive lock while awaiting run_agent, bridge control, or another handler. Update validators remain synchronous/pure; they cannot claim to validate live SQL state. Never return a commit receipt before the Local Activity transaction commits.

When worker is unavailable, no durable PostgreSQL receipt can yet be claimed. Client remains pending and reads/retries the same identity. RPC timeout does not cancel the Update or prove non-delivery. No outbox, reconciliation poller, additional Signal, or server-side fake sent status.

## Main loop, bootstrap race, and failures

Workflow state is small: agent_id, latest_seq, last returned cursor, active business run ID, continuation, pause/stop/rotate flags. No message bodies, tool results, transcript, or file bytes in mutable Workflow state. Update payload text remains in Temporal history by design; do not misstate that limitation.

1. Register handlers before bootstrap. Merge bootstrap latest_seq with any already-received value using max; never overwrite a newer handler update.
2. Reuse an unfinished run ID returned by bootstrap; generate a new business ID with replay-safe Workflow UUID only for a genuinely new run.
3. Await `(not paused and (continuation or latest_seq > cursor)) or stop or rotation_needed`.
4. Start run_agent on `openlet-leta-runtime`. While its handle is pending, receive/control Updates continue. Await completion or a history/control condition; a rotation condition can invoke control_agent(yield) while the runner remains active.
5. Merge returned cursor/result. Completed clears active run; yielded/paused retains business run+continuation. New input beyond cursor starts the next invocation without closing Workflow.
6. Surface a terminal failure through the existing run/Workflow error path; do not erase inbox rows, convert failure into success, or blindly spin a failed invocation. No failure_wake_seq or custom failure-wake policy is added.
7. Idle uses workflow.wait_condition; no polling Activity/thread per agent. Explicit delete requests stop and waits for active Activity cleanup before Workflow completion.

Transient Activity failure retries with the **same** run ID. Retry does not mean new invocation input; phase 10 selects saved result, pending graph work, or new work from checkpoint state.

## Pause, yield, cancellation, and history rotation

- Durable root pause/delete state lives in agents. Runner checks it before each new model call at a safe protocol boundary. Active model/tool call completes or reaches its own bounded timeout before pause takes effect; never inject steering into an in-flight provider call.
- Use the phase-03 `runs.yield_requested boolean default false` field. This is a direct control flag, not a lease/fence/revision or job engine. control_agent(yield,run_id) calls the receiver control Update, which invokes Local `save_run_control` for that named unfinished run; runner checkpoints a continuation and clears the flag when yielding. Root pause/config remains lifecycle-owned; Workflow never performs direct SQL.
- Use public LangGraph control interruption/resume as proven in phase 10, retaining same business run and thread. Human requests do not use this graph-control interruption.
- Check `workflow.info().is_continue_as_new_suggested()`, `.get_current_history_length()` and `.get_current_history_size()` at handler/main-loop boundaries. Initial safeguards: 8,000 events or 8MiB, configurable downward for tests; validate headroom against actual namespace limits in phase18.
- When active, request cooperative yield before rotation. When idle/paused, rotate directly after handlers drain. Always await `workflow.all_handlers_finished`; recheck pending control/input before Continue-As-New. Do not rotate only after naturally completed model work.
- Carry only IDs/counters/flags/continuation; bootstrap validates persisted state in the next execution. No transcript/body copied into Continue-As-New args. A run spanning rotations keeps its original business ID.
- Lifecycle/Box/ScheduleChanges coordinators use the same bounded-history checks between completed commands. HumanRequest/Delivery are finite per request/occurrence.
- Activity heartbeat every second with a 10-second heartbeat timeout is the initial test setting. Use WAIT_CANCELLATION_COMPLETED so stop does not release lifecycle safety gates while code still uses filesystem resources. Worker shutdown closes sessions and the dedicated checkpoint connection; phase 10 covers cancellation during opaque effects.
- Yield a running invocation only when history rotation or an actual upstream technical safeguard requires it. Continue the same run after its saved boundary; no fixed two-minute or 128-boundary segmentation and no product call budget.

## Worker registration and resource ownership

One process may host two SDK Worker objects: orchestration queue `openlet-leta`, runtime queue `openlet-leta-runtime`. Register Workflow definitions on orchestration worker and run_agent only on runtime worker. Keep orchestration/bridge capacity available while models are busy. Local SQL deadlines must fit a short Local Activity timeout; initial statement timeout 2s and Local start-to-close 5s, verified under integration load rather than expanding Workflow Task timeouts.

Bound maximum_cached_workflows and Activity concurrency explicitly in phase18; idle waits consume no Activity slot, though cached Workflow state still uses bounded RAM. Start no duplicate dev servers; fixtures track and stop processes they create.

## Implementation and verification

1. [x] Define serializable typed receive/bootstrap/control/result DTOs and nonretryable validation/conflict/deleted errors.
2. [x] Implement Local SQL Activities using phase03 methods, preserving IDs across retries.
3. [x] Implement Client helper and AgentWorkflow bootstrap race/main loop with receive-only lock.
4. [x] Implement shared bridges with bounded remote timeouts and deleted-target skip; no hidden list_owned_resources Activity or batch orchestration Activity. Wire phase16 shared regular publish_resource_event after sparse Workflow-owned commits; Local Activities never call Redis.
5. [x] Add yield control/history checks and two Worker registrations. Use a test Activity that explicitly blocks on a test event only in Workflow tests; production requires phase10 runner.
6. [x] Commit representative histories as sanitized test fixtures; Replayer must accept input during active run, pause, and Continue-As-New histories.

```sh
uv run --locked --package leta pytest apps/leta/tests/test_agent_workflow.py -q
uv run --locked --package leta pytest apps/leta/tests/test_inbox_integration.py -q
pnpm --filter @openlet/leta test:replay
pnpm --filter @openlet/leta check
```

| Test | Required observation |
|---|---|
| Busy receive | Second Update commits/acks while first run_agent remains blocked; runner lock is not held by handler. |
| Crash after SQL commit/before completion | Retry returns same seq/row and wakes runner; changed content conflicts. |
| Concurrent sequence commits | Hold recipient lock in one transaction; later receive cannot commit a higher seq first or advance a snapshot past a missing lower seq. |
| Worker down/API timeout | No false sent receipt; same ID eventually reconciles exactly one row. |
| Bootstrap race | Message committed during bootstrap remains above merged cursor. |
| Steering | Message arriving during model/tools appears only at next safe boundary. |
| Rotation | Active, idle, and paused histories rotate with handlers drained and no lost receive; same business run survives active yield. |
| Terminal error | Ordinary run/Workflow failure is visible; no custom failure-wake cursor is introduced. |
| Sparse publication failure | Failure after SQL/native-effect commit retries notification only; no duplicate business effect, blocked teardown or false Redis receipt. Reconnect refreshes canonical resource state without PG polling. |
| Cache eviction | Cold replay resumes from current execution history, not lifetime history. |

Use SDK time-skipping only for deterministic Workflow tests. Persistent crash/restart tests use `temporal_address`, `temporal_namespace`, and disposable PostgreSQL fixtures, and fail clearly if services are unavailable.

## Acceptance, risks, rollback

Acceptance: exactly six Workflow types; commit receipts are honest; one agent never has two graph writers; unrelated agents and human waits do not block each other; long-lived histories stay bounded including pause/idle. No delivery/operation entity or per-tool Workflow.

Local marker loss can repeat SQL; tests must kill the Worker around commit, not just mock Activity returns. A client timeout is an uncertain outcome. Before rollout, replay captured histories after Workflow changes and take the phase18 durable backup before schema/checkpoint changes. Rollback preserves registered names/DTO compatibility; drain new executions or use supported worker versioning rather than deploying nondeterministic code over live histories.
