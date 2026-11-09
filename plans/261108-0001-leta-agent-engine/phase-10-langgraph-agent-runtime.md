---
title: "Phase 10: Checkpointed LangChain agent runtime"
status: complete
priority: P1
effort: 5d
dependencies: [8, 9]
---

# Phase 10: Checkpointed LangChain agent runtime

## Outcome and dependencies

Execute one agent with LangChain **create_agent**, LangGraph working state, AsyncPostgresSaver, and `durability="sync"`. Recover safely after Activity retry; preserve steering, tool-call protocol, and the same business run across pause/yield/history rotation. Config changes apply before the next model call without clearing context.

Depends on [Mirage](phase-08-mirage-workspace-adapter.md) and [AgentWorkflow](phase-09-temporal-agent-inbox.md), with the [phase-03 schema](phase-03-leta-domain-schema.md). [Phase 11](phase-11-history-and-compaction.md) adds public history/compaction; [phases 12–14](phase-12-messaging-and-box-lifecycle.md) add product tools. Only concrete implemented tools enter the roster.

Execution state: runtime core and pinned graph/recovery gates are implemented; see the [execution checkpoint](reports/phase-10-execution.md). The 18-case focused suite uses real PostgreSQL, plus a real Temporal/SIGKILL recovery journey and deterministic inference boundary. Public history/compaction and Redis publication remain their owning phases. The [accepted resource design](../reports/design-261108-0148-leta-workspace-resource.md) controls identity, artifact paths and replay limits.

## Evidence and proposed files

Pinned sources in `/tmp/leta-engine-review/src`: LangChain 1.4.8 `agents/factory.py:1643–1688/1834–1857` creates separate middleware nodes; LangGraph 1.2.19 `pregel/_loop.py:2067–2145` loads latest state and retains invocation RAM state, and `pregel/main.py:3519–3550` awaits sync checkpoint writes. Checkpoint-postgres 3.2.0 `checkpoint/postgres/aio.py:186–215` fetches latest by thread/namespace and checkpoint_id DESC LIMIT1. These are source facts; real composition is an execution gate. Historical [engine evidence](reports/review-engine.md) remains useful for source locations, but its command-journal and opaque-execution suppression recommendations are superseded.

The lab `chat/worker.py::run_agent` demonstrates a whole-graph Activity and advisory lock on a dedicated saver connection. Its DeepAgents factory, async durability, native HITL interrupts, recursion_limit=100, legacy branches, and full checkpoint-derived UI are **not** the product implementation.

| Action | Absolute path | Purpose |
|---|---|---|
| New proposed | `/home/qninh/projects/openlet/apps/leta/src/leta/runtime/state.py` | `LetaAgentState`, `RuntimeContext`, digest/full batch types. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/src/leta/runtime/runner.py` | `run_agent`, recovery selector, saver/lock/resource lifetime. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/src/leta/runtime/middleware.py` | `OpenletBoundary`, `CollectInbox`, dynamic model wrapper, saved tool-result reuse. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/src/leta/runtime/tools.py` | `build_tools`, `get_workspace`, `list_workspace_members`; concrete capability roster. |
| Modify earlier files | `/home/qninh/projects/openlet/apps/leta/src/leta/store.py`, `/home/qninh/projects/openlet/apps/leta/src/leta/worker.py` | Run persistence and actual Activity registration. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/tests/test_runtime.py` | Real compiled create_agent graph with deterministic BaseChatModel. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/tests/test_runtime_recovery_integration.py` | Real saver/Temporal/worker kill and overlapping attempts. |

Use package `leta` and native Python snake_case module names. No LangGraph internals patching, forked provider loop, or graph node executor of our own.

## Working state and model configuration

Extend public AgentState with `business_run_id`, integer `inbox_cursor` default 0, and typed Openlet state needed to identify collected inputs/control continuation. Messages remain LangChain message objects and use the standard reducer. Runtime context contains agent/root/workspace IDs, authenticated service clients, current mounts, and invocation-local control state; never serialize live connections or secret tokens into checkpoint.

- `thread_id=str(agent.id)` is derived for the agent's entire life; do not store a second thread identity. A root UUID is an independent resource ID, never a users ID. `business_run_id` changes only for genuinely new runs. Temporal execution/run IDs are observability fields.
- Root stores selected model_id and reasoning_effort from server catalog. Leti nullable fields inherit independently; validate the **effective pair** after inheritance, both on write and at boundary. Invalid/removed catalog choices are explicit configuration errors, not silent fallback to another model.
- Owner may update root config and Leti model/reasoning override through owner API. Leti name/box graph stays immutable. null override restores inheritance. An active call retains its original model/prompt; the next safe boundary refreshes config.
- Use public `awrap_model_call` ModelRequest override for dynamic model/system prompt; assign AIMessage ID if provider omitted it **before returning model output to the graph checkpoint**. Preserve provider tool_call IDs; reject malformed/colliding IDs with a protocol error.
- Build a private Mirage Workspace+Session per invocation. Both root and Leti use trusted subject `leta:<root-id>`; Leti additionally has a backend-enforced immutable box-root Locator. The credential boundary derives mutually exclusive `x-openlet-user-id` / `x-openlet-leta-id`; browser inputs can identify only user. No actor/grantee/subject-kind tool argument can widen authority.
- Refresh the [generic accessible-scope view](phase-04-workspace-resource-access-and-scope-view.md) only between calls. Root mounts `~/`, `/shared/`, and approved `/users/<user-id>/`; Leti retains its box-root restriction even for ID aliases. Artifacts are ordinary descendants: `/shared/docs/report.pdf/report.md` or `/shared/@<original-file-id>/report.md`, with equivalent home/approved-user paths. There is no `/artifacts` mount or separate artifact ID. Large originals remain blobs: metadata/artifact tree only; raw S3 bytes/URLs never enter runtime tools. Inline reads/writes retain existing InlineLimit, not MaxFileBytes.

## Middleware graph and checkpoint barriers

Use public AgentMiddleware hooks, not provider callbacks as persistence authority. Required node order:

```text
OpenletBoundary.before_model
  -> OpenletSummary.before_model             (phase11)
  -> CollectInbox.before_model
  -> PublishContext.before_model            (phase11)
  -> model
  -> PublishAssistant.after_model           (phase11)
  -> tools, if assistant requested calls
  -> OpenletBoundary.before_model ...
```

Each arrow between nodes is a graph superstep/checkpoint boundary. With sync durability, summary and batch+cursor are committed before PublishContext; assistant output/tool IDs are committed before PublishAssistant/tools. Put tool-result publication after the tools checkpoint at the next safe boundary. Final no-tool text becomes final_note, not an outgoing message.

Implement an executable graph-order test with installed pinned versions before depending on those barriers. Assert saver commit events precede publication and model/tool execution; inspect public get_graph output for expected node names/order. If upstream composition differs, correct middleware composition through supported hooks and rerun this gate; do not silently put summary+publisher into one node or patch private factory functions.

### Inbox collection

1. At before_model capture committed inbox high-water seq and read every pending row through that snapshot (`cursor < seq <= high_water`) using bounded SQL pages. Bound each query, not the logical Leti batch; newly committed later rows wait until the next boundary.
2. Leta builds **one** digest batch grouped by conversation/source, containing IDs, new counts, source badges, preview, and nullable reply address. Leti builds **one** full batch with exact text/data of ALL pending items in that snapshot. Leta counts/IDs cover the same complete snapshot, with bounded previews. Compact older context before collecting; if the full valid new batch still cannot fit the selected model context, fail explicitly without advancing cursor, rather than silently splitting, omitting, or summarizing Leti inputs.
3. Render that typed payload once as a runtime HumanMessage with a fixed internal header and serialized JSON. Give it a stable message ID before checkpoint and `additional_kwargs.openlet={kind:'inbox_input',mode,payload}`. The payload is not a new domain entity.
4. Return messages addition and `inbox_cursor=max_selected_seq` in the **same hook update**. No cursor-only update and no separate transaction that marks messages processed.
5. Leti has no list_inbox/read_inbox tools. Leta may explicitly read details; read_at is independent of cursor. Generic adapter source strings must survive unchanged after validation.

Input arriving mid-model/tool is collected at the next boundary after all current tool results. Never insert a HumanMessage between an assistant tool-call message and its ToolMessages. An ask_user tool returns pending immediately; no unresolved tool-call protocol is held while a human thinks.

## One writer and resource lifetime

Open one dedicated psycopg AsyncConnection, autocommit true, dict_row, prepare_threshold=0. Acquire `pg_try_advisory_lock(hashtextextended(thread_id,0))` on **that same connection** and pass it into AsyncPostgresSaver. Wait cooperatively with heartbeat and bounded backoff if a previous Activity attempt still owns the lock. Do not borrow a pooled connection for the session lock then return it to the pool.

After acquiring, re-read run state: another attempt may have completed while this attempt waited. Connection loss terminates this invocation; do not reconnect the saver and continue without re-acquiring ownership. No lease/fence/revision subsystem. Receive uses separate short SQL transactions and is not blocked for the duration of this lock.

Heartbeat task runs independently of model streaming and Redis availability. On normal completion, yield, cancellation, and partial initialization failure: close Mirage session/workspace, provider streams and child tasks, stop publisher/heartbeat tasks, release lock by closing connection, and return connections. Never save failed as successful because stream publishing failed.

## Recovery selector: decide before invoking graph

Inspect run row and latest `graph.aget_state(config)` under advisory ownership. Use state.business_run_id plus snapshot.next/tasks/interrupts; attempt number alone is insufficient.

| Saved state | Required action |
|---|---|
| Run has immutable terminal result | Return it without graph/model/tools; reconnect stream may publish bounded saved terminal metadata. |
| Same business run, no pending nodes/tasks/interrupts | Finalize the already completed checkpoint into runs; do not call model again. Handles crash between final checkpoint and SQL finalization. |
| Pending ordinary graph node(s), same business run | Resume with input=None and sync durability; do not append inbox batch or rerun model from the start. |
| Persisted Openlet control interrupt | Resume matching interrupt ID using public Command(resume=...), only after control permits; same thread/run. Re-executed boundary hook must be pure/idempotent before interrupt. |
| Previous business run completed, no pending work, new run ID | Start a new invocation update carrying new business_run_id and empty message addition; collect hook obtains new inbox. |
| No checkpoint | Initialize empty working state/cursor, then collect real pending input. |
| Pending work belongs to a different unfinished business run | Recover that original run or reject inconsistent bootstrap; never overwrite it with new input. |

Keep RAM working state for the duration of one graph invocation; do not re-fetch/deserialise latest checkpoint at every model iteration or add a cross-invocation RAM state cache. collect_inbox's SQL query is not a full checkpoint reload. Provider request serialization on every call is distinct from saver recovery.

## Tool effects, persisted IDs, and ambiguous execution

Create effect IDs from `(agent_id,persisted AIMessage.id,persisted tool_call_id,effect kind)` with a fixed UUID namespace. Use those IDs for send_message, ask_user/request_access, create_box, and schedule creation/change command identity. Distinct tool calls produce distinct effects, even with identical args. A retry of one saved call must keep its ID.

- Public assistant journal contains requested tool IDs/args. `awrap_tool_call` writes the existing tool_call entry **immediately before** executing the handler, not merely when a model plans a call. Reuse an existing saved tool_result rather than invoking again.
- Message/request/box/schedule methods reconcile their stable natural IDs with immutable payload and backend result. Crash after effect but before tool-result checkpoint retries the same logical effect without duplicate send/request/box/schedule.
- Filesystem mutation retry follows [phase 06](phase-06-letfs-text-mutations.md) preconditions/current-state reconciliation, including known node IDs and revisions. Domain IDs, saved public results and existing downstream `idempotency_keys` retention cover their own narrow contracts; they are not an infinite historical command journal or global exactly-once guarantee.
- **run_shell/run_python recovery:** if no saved result exists, allow the checkpointed tool call to execute again, even if an earlier attempt may have partially or fully executed it. The user accepts duplicate command effects; the agent inspects results and corrects mistakes. Do not implement start-marker-based replay suppression, outcome_unknown results or an execution ledger.
- Reuse an already saved tool result. Otherwise use ordinary tool execution/recovery. Narrow tool failures become error ToolMessages; cancellation/GraphInterrupt propagate rather than becoming ordinary tool errors.
- Tools run only through the capability roster appropriate for Leta/Leti and server-authenticated actor. Model arguments cannot supply authoritative owner/workspace/grantee or widen mount roots.

## Control continuation without a model-call budget

Boundary hook reads durable root pause/delete state and current run.yield_requested. It may call public `langgraph.types.interrupt` with typed control-only payload `{kind:'openlet_control',reason,run_id}` at a tool-complete boundary. That is an invocation suspension, not HITL. Persist/recover its ID and resume through Command; remember interrupt resumes the node from its beginning.

Do not let the upstream recursion safeguard become a total business-work limit. Continue-As-New is requested when Temporal history approaches its threshold; the runner yields at a tool-complete checkpoint boundary. If the actual upstream step safeguard would be reached first, use the same supported continuation at that boundary. No forced two-minute or 128-boundary segmentation. Configure/test the upstream safeguard against the generated graph; more than 100 model calls must remain possible without a product call budget or duplicate domain effects.

Pause retains continuation even if inbox cursor already caught up; resume requires no new input. Stop records cancellation after current bounded call/cleanup; lifecycle waits before trash. An unfinished shell/Monty call may replay on recovery under the accepted policy above.

## Implementation checklist and checks

1. [x] Establish the pinned create_agent/sync saver graph-order test before adding application hooks.
2. [x] Implement state/context and effective catalog validation; add configuration change tests with the first model call held in flight.
3. [x] Implement collect hook and one typed runtime HumanMessage per batch; prove batch+cursor atomic recovery and protocol safety.
4. [x] Implement dedicated saver connection/lock, run recovery matrix, heartbeat, cleanup, and worker registration.
5. [x] Add control interrupt/resume and history-requested yield under the same run ID, with upstream-safeguard handling only when actually required.
6. [x] Add persisted domain-tool identity, saved-result reuse and ordinary shell/Monty replay on incomplete result; wire only implemented concrete tools.
7. [x] Implement get_workspace/list_workspace_members in runtime/tools.py with phase04 `WorkspaceClient.GetWorkspace`, `ListAccessibleScopes`, and `ListMembers`. get_workspace returns current root/agent resource IDs, effective model_id/reasoning_effort, permitted mount paths/rights and allowed messaging roster, without file bodies. list_workspace_members pages active humans with validated 1–100 pages/default limit 20; cursor does not open a chat route. Root/workspace/actor are server-selected. Test Leti box home/peer roster, foreign personal grant/revoke, empty/continued human-only pages, inactive creator and cross-workspace denial. No extra discovery service.
8. [x] Bind phase16 ordinary publisher to the one stable per-Leta Redis Stream. Every root/Leti event includes agent_id, run_id and AG-UI payload. Runtime/API/tools call the publisher directly; only sparse Workflow-owned resource refs use phase09's regular publish_resource_event Activity. No token/model/tool event creates an Activity. Redis is required at readiness; publication failure is transport failure and must not retry an applied tool/domain effect. No per-run stream or PostgreSQL discovery polling belongs in runner.

```sh
uv run --locked --package leta pytest apps/leta/tests/test_runtime.py -q
uv run --locked --package leta pytest apps/leta/tests/test_runtime_recovery_integration.py -q
pnpm --filter @openlet/leta check
```

| Failure/contract test | Pass condition |
|---|---|
| Checkpoint loads bounded by invocation/recovery | Instrument saver load; recovery selection may inspect a snapshot and graph entry may load it again, but model/tool iterations retain RAM state without a full reload each iteration. |
| Crash after inbox checkpoint | Same runtime batch/cursor recovered; no skipped or duplicate batch. |
| Crash after assistant checkpoint | Saved tool IDs reused; model is not rerun before pending tools. |
| Crash after final checkpoint | Finalize result without an extra model call. |
| Overlapping Activity attempts | Only one reaches model/tools until lock owner exits; second re-reads result. |
| Model/prompt steering | In-flight request unchanged; next request sees new valid effective config/context. |
| Tool effect crash windows | One message/request/box/schedule by existing identity. Unfinished shell/Monty calls may replay; no synthetic unknown-outcome result. |
| Long continuation | More than 100 model calls, pause without new input, yield/rotate, restart retain same run/thread and valid tool protocol. |
| Cleanup | Cancellation/connection loss leaves no open Mirage session, heartbeat task, or advisory lock. |

## Acceptance, risks, rollback

Acceptance requires real compiled pinned graphs and PostgreSQL saver, not only mocks of LangGraph. These core gates passed as recorded in the execution checkpoint. Deterministic BaseChatModel is appropriate at the inference boundary for failure injection; [phase19](phase-19-system-acceptance.md) owns the system journey and any optional opt-in live-provider check.

The most dangerous errors are appending input over unfinished work and reconnecting a saver without ownership. An incomplete shell/Monty result may execute again after crash; the agent must inspect/correct duplicate effects, as accepted. Rollback pauses admission and drains/yields compatible invocations, preserving checkpoint/public-history identities. This fresh implementation has no production data and no backup prerequisite, per user instruction; never reset threads or delete tool calls to bypass recovery failures.
