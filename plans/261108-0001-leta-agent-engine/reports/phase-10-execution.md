# Phase 10 execution checkpoint

Status: checkpointed runtime core implemented and focused gates passed. Overall goal remains active. No approval is pending. Public transcript/compaction is the next owning phase; lifecycle/product tools and Redis publication retain their existing phase ownership.

## Implemented

- A real `create_agent` composition using pinned LangChain 1.4.9, LangGraph 1.2.20 and AsyncPostgresSaver 3.2.0. `durability="sync"` is explicit. A real PostgreSQL graph-order test establishes separate before-model middleware checkpoints and an assistant checkpoint before tool execution.
- Lifetime agent thread, typed inbox metadata, root digest vs complete Leti batches, bounded SQL pages through a committed snapshot, atomic message/cursor checkpoint updates and collection only after complete tool groups. Generic source strings survive unchanged. Context overflow fails without advancing the batch cursor.
- Dynamic model/system prompt selection at the safe boundary. Leti model/reasoning overrides inherit independently. The fresh initial schema no longer disallows reasoning-only overrides; `configure_agent` validates effective catalog pairs, including children affected by a root configuration change. Its HTTP authorization/route belongs to phase15.
- One dedicated async saver connection holds the agent advisory lock. Overlapping attempts wait, then re-read the terminal result. No reconnect-and-continue occurs after saver connection loss. Recovery resumes pending nodes with None, control interruptions with public Command, and finalizes an already completed checkpoint without a new model call.
- Pause/yield uses a pure rechecking boundary loop. Cached interruption responses cannot bypass a newly active control. The upstream graph recursion safeguard yields before exhaustion and resumes the same business run; it is not a business model-call limit. Managed-step metadata must follow the private-schema marker in the annotation because the installed LangGraph checks the last metadata entry.
- A concrete `run_agent` Temporal Activity independently heartbeats and owns cancellation/resource cleanup. Existing `agent_workers` registers this bound method in the integration journey. Deployment CLI/wiring remains phase18, not a dummy runner.
- Concrete workspace/member and seven existing filesystem tools. The model receives no actor/workspace/grantee authority argument; workspace discovery uses the root Leta actor. Leti workspace output lists only graph neighbors and, for a representative, the parent box route.
- Tool execution start/results use the existing activity_log. Saved results are looked up by deterministic primary-key identity before reexecution. Effect identity seeds use an unambiguous JSON tuple. An opaque command with no saved result may execute again after failure, as explicitly accepted. No command ledger, outbox, lease/fence, extra Workflow or Activity type was added.
- Provider invocation owns both OpenRouter sync/async client contexts; the installed SDK closes separate clients through these two exits. No paid inference was used.

## Verification

- Initial standalone pinned PostgreSQL graph-order gate passed before application middleware was implemented.
- Final focused runtime suite passed **18 tests in 68.78s**. This includes typed steering while a model call is held, dynamic prompt/reasoning updates, all 205 Leti items across SQL pages, context-overflow atomicity, saved inbox/pending-model recovery, final-checkpoint-only SQL finalization, late-pause regression, independent overrides, child communication roster and distinct provider-ID encoding.
- Recovery tests include real Temporal plus an owned subprocess SIGKILL immediately after tool-result SQL commit and before the tools checkpoint. Replacement workers reuse that result and produce one SQL effect. The incomplete-result case intentionally produces two effects, proving the accepted ordinary shell replay behavior.
- Two overlapping attempts produce one model execution; cancellation closes invocation resources and releases ownership; terminating the owned saver backend ends the attempt and permits recovery. A 110-tool-call/111-model-call task keeps one thread/business run across yield, with at most eight saver loads across the two invocations. A deliberately reduced upstream recursion safeguard yields repeatedly and still completes its original task.
- An independent read-only gpt-6.1-sol/xhigh review found the cached-control-response and ambiguous-effect-ID defects. Both were corrected and regression-tested. It found no further concrete defect or useful simplification. No delegate edited files.
- The first safeguard test exposed misplaced managed-value annotation metadata; it was corrected against the installed public types/source. No test assertion, safety limit or dependency version was weakened.
- Full Leta suite passed **129 tests, 3 skipped, in 166.55s**. The three skips require the native LetFS fixture and were previously passed through phase08's real Go race gate; phase10 did not modify those adapters.
- The shared Python suite passed **51 tests in 2.29s**. Leta Ruff check/format, wheel/sdist build and whitespace checks passed. All 46 local Markdown links in the changed plan surfaces resolved.
- Read-only follow-up review confirmed both fixes with focused executable checks and found no remaining concrete concern. The simplifier/reviewer made no edits; the scoped diff was unchanged by delegation.
- Logs: `/tmp/openlet-leta-phase10-{all-runtime,controls,worker-crash,recovery,full,shared,build}.log`. Tests used owned disposable PostgreSQL/Temporal containers. All owned subprocesses/containers exited; only pre-existing agent-lab containers remained.

## Remaining ownership

Phase11 must add the actual separate summary/publication nodes, public allowlisted ActivityEntry projection, permanent transcript and compaction/history tools. Current saved tool results are internal replay data in the existing transcript table; they must be projected/sanitized with phase11 before exposing an owner-facing history endpoint. Final model text currently remains checkpoint state; it is not an outgoing message.

Phases12–14 add messaging, complete box/lifecycle behavior, human requests and schedules. Phase16 supplies the real Redis/AG-UI publisher; no successful no-op publisher has been registered. Phase18 supplies the executable production wiring. The final native Mirage + runtime + public-API journey remains a system acceptance gate rather than a claim based on the RAM-mounted inference fixture; the separate real LetFS/Mirage phase08 gates remain valid for unchanged adapter code.

Preserve all earlier uncommitted implementation work. No commit, push, deployment, developer-environment reset, backup prerequisite or compatibility migration was introduced.
