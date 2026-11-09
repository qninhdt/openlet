---
title: "Phase 11: Public history, typed inputs, and durable compaction"
status: completed
priority: P1
effort: 4d
dependencies: [10]
---

# Phase 11: Public history, typed inputs, and durable compaction

## Outcome and dependencies

Persist an append-ordered **public LLM transcript**, independently of the working checkpoint. Persist real context compaction using SummarizationMiddleware, then publish the exact committed summary/input as typed timeline entries. UI reload and live streaming use the same DTO, never raw LLM template/JSON parsing or reconstruction from lifetime checkpoint snapshots.

Depends on [runtime](phase-10-langgraph-agent-runtime.md); schema authority is [phase03](phase-03-leta-domain-schema.md). [Creator UI/API](phase-15-owner-api-and-ui-contract.md) and [streaming](phase-16-redis-agui-streaming.md) consume this contract. This phase owns DTOs/publishers, not frontend components. Creator-only access requires `leta.read` and current workspace membership; a resource approver does not gain transcript access.

Execution state: typed transcript, history tools and durable compaction are implemented. Focused graph/saver tests passed, including a new batch forcing compaction before the usual threshold. The [execution checkpoint](reports/phase-11-execution.md) records evidence and remaining API/live-publication integration gates.

## Evidence and files

Pinned `/tmp/leta-engine-review/src/langchain/agents/middleware/summarization.py:526–564` (1.4.8) returns RemoveMessage(REMOVE_ALL_MESSAGES), a summary HumanMessage and recent messages. Lines 296/970–978/1031–1032 support `trim_tokens_to_summarize=None` and a public async summarizer before default XML formatting. Factory 1643–1688/1834–1857 gives separate middleware nodes; LangGraph 1.2.19 `pregel/main.py:3519–3550` awaits sync checkpoints between supersteps. Source inspection is not a passed real graph test. The [accepted design](../reports/design-261108-0148-leta-workspace-resource.md) supersedes historical command-journal recommendations in old reports.

| Action | Absolute path | Purpose |
|---|---|---|
| New proposed | `/home/qninh/projects/openlet/apps/leta/src/leta/runtime/history.py` | `public_content`, `PublishContext`, `PublishAssistant`, `read_history`, `search_history` projections. |
| Modify phase10 file | `/home/qninh/projects/openlet/apps/leta/src/leta/runtime/middleware.py` | `OpenletSummary`, public `summarize_public`, ordered composition. |
| Modify earlier files | `/home/qninh/projects/openlet/apps/leta/src/leta/domain.py`, `/home/qninh/projects/openlet/apps/leta/src/leta/store.py` | `ActivityEntry`, `append_activity`, authorized history/search methods. |
| Modify phase10 file | `/home/qninh/projects/openlet/apps/leta/src/leta/runtime/tools.py` | search_history/read_history tools. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/tests/test_history.py` | Typed DTO, summary composition, sanitization, dedup. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/tests/test_compaction_integration.py` | Real saver crash barriers and multiple compactions. |

## Public ActivityEntry contract

This union is the public LLM transcript stored in activity_log. Do not add internal resource-change admission/completion rows for command deduplication. Owner-facing domain references remain separate from assistant/tool transcript entries.

```text
ActivityEntry {
  id: UUID, agent_id: UUID, run_id: UUID|null, seq: bigint,
  kind: discriminant, created_at: RFC3339,
  message_id: UUID|null, tool_call_id: string|null,
  data: corresponding typed payload below
}
```

| kind | Typed data | UI meaning |
|---|---|---|
| `inbox_input` | runtime_message_id, mode=digest/full, cursor_from/to; groups or items below | Custom input card, never owner bubble based on role=user. |
| `assistant` | llm_message_id, public content blocks, tool_calls[{id,name,args}] | Public assistant transcript for a tool-producing response. |
| `tool_call` | llm_message_id, tool_call_id, name, args, started_at | Tool component; created immediately before handler starts. |
| `tool_result` | tool_call_id, name, public result, outcome=success/error | Public result or ordinary tool error. |
| `final_note` | llm_message_id, public content blocks | Intentional final note; never automatically sent/forwarded. |
| `compaction` | summary_message_id, summary, optional replaces_through_message_id, retained_message_ids | Expandable context-compaction card with exact persisted summary. |

Persist one assistant output as assistant **or** final_note, avoiding duplicate text entries. Tool-producing assistant payload retains tool IDs/args even when separate tool_call execution entries appear. Keep public image/file results as authorized artifact references and public text, not arbitrary raw provider objects/bytes.

Public content means intended assistant text/tool data and explicit context summary. Strip hidden reasoning, provider reasoning_content/thinking blocks, secrets/service credentials, and transport internals by allowlisting supported public blocks; do not persist a raw provider response and hide it only at render time. Tool arguments/results are part of the requested public transcript, including data an agent deliberately read. Revoking future scope access does not erase previously read transcript/history.

### Typed inbox payloads

One collection step creates one runtime HumanMessage with metadata identifying the following projection:

```text
DigestInput {
  mode:'digest', runtime_message_id, cursor_from, cursor_to,
  groups:[{
    source:{type,id,label}, conversation_id:string|null,
    new_count, message_ids:[UUID], preview:string,
    reply_to:Address|null
  }]
}
FullInput {
  mode:'full', runtime_message_id, cursor_from, cursor_to,
  items:[{message_id,seq,source,conversation_id,reply_to,content,data}]
}
```

The journal can retain refs plus immutable render metadata and hydrate content/data from messages by IDs, rather than duplicating domain bodies. API projection must reproduce the exact selected batch, not query today's latest unread inbox or expand future items into an old card. Keep source.type generic after adapter validation. reply_to=null means no reply address, even if source has a label.

UI renders owner→Leta message once as an owner bubble. An inbox-input card may reference that message, but never turns the same payload into another owner bubble. Leti full input is a custom card with expandable content/source/data, including request_id/answers and schedule_id/scheduled_at. Normal conversation UI does not expose the internal fixed header or serialized JSON. Typed compaction and inbox cards apply to both live CUSTOM events and paginated reload.

## Journal identity, ordering, and publication

1. Assign every runtime/assistant/summary message ID before graph persistence. Derive natural journal key from `(agent,kind,llm_message_id,tool_call_id?)`.
2. In one short SQL transaction lock agents.activity_seq, check natural key, allocate seq only for a new entry, and insert. A duplicate returns the saved entry; conflicting immutable content errors instead of overwriting history.
3. Emit `CUSTOM(name='activity',value=ActivityEntry)` only after that SQL commit, inside the phase16 envelope `{agent_id,run_id,AG-UI payload}`. Root and all Leti share one stable Redis Stream per root Leta. Redis may repeat or lose an event; UI dedups durable records by entry.id.
4. Ordinary disconnect uses valid Last-Event-ID replay, including unfinished text; it does not discard provisional text or force PG reset. Only expired/trimmed/lost stream data requires an explicit reset to selected-agent PostgreSQL history/current pointer. Redis is required but is never canonical permission/product history. Publication outage cannot replay already applied tools or domain effects.

These runtime publishers call phase16's ordinary publisher directly. Sparse lifecycle/HITL/schedule notifications from Workflows use the phase09 shared regular publish_resource_event after SQL commit, outside the public ActivityEntry union; they add no transcript variant or command receipt. A reconnect refreshes canonical domain snapshots independently of valid unfinished-text replay, covering missed sparse refs without a PostgreSQL polling loop.

PublishContext.before_model observes checkpointed summary and input from preceding separate middleware nodes. PublishAssistant.after_model observes the model output that was checkpointed by the preceding model node. Tool wrapper may record its actual execution result in the existing transcript before returning ToolMessage so retry can reuse it; publish that result to live UI after the tools checkpoint at next boundary. This does not allow a pre-checkpoint compaction-success card.

The publisher itself is a recoverable graph node: crash after checkpoint and before SQL publication resumes publisher; it must not call summarizer/model again just to regenerate UI history. A final checkpoint with missing SQL run result is finalized under phase10's recovery selector.

## Durable compaction algorithm

Use upstream asynchronous SummarizationMiddleware through its public abefore_model override. Call `super().abefore_model`, inspect the returned update, stamp the returned summary HumanMessage with an ID and typed Openlet compaction metadata, and return it. Supply the supported public `summarizer` async callable to prevent provider-private reasoning from becoming a published summary: `async summarize_public(messages: list[AnyMessage]) -> str` copies/project messages into the same allowlisted public text/tool representation before constructing its own fixed summary prompt and calling the configured model with a bounded timeout. Pinned LangChain 1.4.8 passes original trimmed messages to this callable before its default XML formatting; its builtin summary_prompt is not used with a callable, so the wrapper must explicitly supply that prompt. Preserve necessary public tool IDs/args/results and omit hidden reasoning blocks/additional provider-private fields. Test a unique reasoning marker is absent from summarizer input and persisted/public summary; sanitizing only the generated summary afterward cannot prevent paraphrased disclosure. No private `_build_new_messages` override, factory patch, compaction Workflow/Activity/service or summary table.

1. Only compact at a tool-complete before_model boundary; verify there is no assistant call lacking ToolMessage results. Keep complete tool call/result groups in recent context.
2. Derive the input budget from the Phase 1 catalog context_window_tokens minus max_output_tokens and measured system/tool overhead. Initial tunable trigger is 80% of that input budget with about 20% recent retention; use the selected provider's supported token counter or the pinned library's conservative counter with a safety margin. Explicitly set trim_tokens_to_summarize=None if supported by the pinned middleware so its default 4,000-token tail cannot silently discard older history; otherwise use a verified complete older-prefix summarization strategy within the model budget and prove coverage before acceptance. Keep model choice/context metadata explicit rather than guessing. The trigger limits working context, not total model calls/business work. Summarizer uses configured async model and explicit bounded provider timeout.
3. Capture the next inbox batch before the budget check and pin it in the summary node's checkpoint as pending_input. If old context plus this intact batch exceeds the budget, compact all old context early and retain the whole batch for CollectInbox; never summarize or split the new batch. Input arriving during summarization waits for the next boundary. Upstream summary replaces the old prefix in graph state. Persist `messages=[summary,recent...]` with inbox_cursor unchanged until CollectInbox adds the pending batch and cursor together. No prompt-only trim that leaves ever-growing messages in latest checkpoint.
4. Summary ID and metadata survive serialization. PublishContext runs **after this sync checkpoint**, upserting a compaction entry with the exact summary message content used by the next model.
5. On later compaction, summarize the prior summary plus newly old messages; latest state keeps one current summary and recent messages. Earlier summaries remain independent public journal entries.
6. Do not prune old checkpoint/journal rows in this MVP. Long-term storage can grow while latest-state recovery remains bounded; backup/disk costs remain real.

| Crash point | Required recovery |
|---|---|
| Before summary checkpoint | Old state is authoritative; summary model may run again. No successful compaction journal/card exists yet. |
| After summary checkpoint, before input/publisher | Continue pending input/publisher with the saved summary; do not summarize again. |
| After input+cursor checkpoint, before publisher | Publish that exact input and cursor range; no duplicate/omitted batch. |
| After journal commit, before Redis | Upsert same journal identity; live event may repeat, history row cannot. |
| After publisher, before main model completes | Preserve published input/summary; provider model retry may occur only if its own output never checkpointed. |
| Redis expiry or Temporal Continue-As-New | Reload journal or continue graph state; neither action independently compacts or invokes model. |

## History APIs/tools and bounds

- Creator API selects **one** root/Leti history at a time; `leta.read` permits its creator only while active in that workspace, including archived retained history. Selected-agent journal pagination uses per-agent seq. Chat uses separate `(created_at,id)` cursor; conversation carries distinct message/activity cursors and typed refs, with no global commit sequence or implied cross-agent timestamp ordering. One root SSE connection still receives events for all agents and routes UI state by agent/run IDs.
- `read_history(entry_id,start_line=1,max_lines=200)` reads the current agent's selected public entry with bounded line detail; it does not take an agent ID or a transcript seq range. `search_history` searches public persisted content and returns bounded IDs/previews; reading full matches is explicit. Both Leta and Leti read only their own transcript; these tools have no agent_id argument. Owner API may independently select descendants. No cross-Leta or ungranted workspace-wide history access.
- Enforce root namespace before query and before hydrating message/artifact references. Resource approver visibility into one request does not grant this endpoint.
- Prefer existing PostgreSQL text search facilities/indexes if profiling warrants one; start with bounded authorized query and validate plans, without a new service/vector index. Do not use summaries as a replacement for permanent history.
- Initial API defaults: 50 entries, max 100; response byte ceiling handled consistently with phase15. A single large allowed entry must remain fetchable, with artifact references rather than raw blobs.

## Implementation checklist and verification

1. [x] Implement ActivityEntry discriminated DTO and deterministic natural keys; add public-block allowlist tests, including provider reasoning rejection.
2. [x] Add separate summary/collection/publisher nodes in the pinned create_agent composition; prove checkpoint-order assertions before implementing Redis adapters.
3. [x] Add public summary wrapper preserving IDs/state/cursor; verify successive compactions and complete tool-call/result retention.
4. [x] Add assistant/final-note/tool journal writers, exact batch refs, and paginated search/read tools scoped to the current agent. Creator HTTP authorization and live publisher adapters retain phase15/16 ownership.
5. [x] Use real saver failure injection for each checkpoint/journal crash point; compare next model input with the saved summary/card contents. Assert older-prefix coverage with markers across its beginning/middle/end, not only summary length. Default 4,000-token tail trimming or overflow retry that silently drops content is a failing result.
6. [x] Provide phase15/16 one DTO fixture per kind and digest/full/compaction states, including duplicate live event and reload cases.

```sh
uv run --locked --package leta pytest apps/leta/tests/test_history.py -q
uv run --locked --package leta pytest apps/leta/tests/test_compaction_integration.py -q
pnpm --filter @openlet/leta check
```

| Contract | Mechanical acceptance |
|---|---|
| Checkpoint before publication | Saver commit precedes compaction/input journal write and next model call. |
| Publisher-only replay | Inject failure after summary checkpoint; summary/model call counters do not increase when publisher resumes. |
| Multiple compactions | Latest state has current summary+recent groups; all earlier transcript and summary entries remain pageable. |
| Exact UI input | DTO contains exactly the batch and source metadata used by model, without parsing rendered HumanMessage text. |
| No CoT storage | Provider thinking/reasoning fixtures absent from SQL rows, SSE, and API projection. |
| Pre-inference sanitization | Unique private-reasoning marker absent from summarizer input as well as persisted/public output; public tool groups survive. |
| Complete older prefix | Sentinel messages at beginning/middle/end reach the summary input; actual 80% trigger/about 20% recent retention obey selected model budget. |
| Resource visibility | Inactive creator and addressed approver cannot load transcript; current creator can read own retained home/history without gaining foreign-scope raw access. |
| Independent retention | Large old checkpoint history does not cause history UI to enumerate checkpoints or latest recovery to fold all old snapshots. |

## Risks and rollback

Private upstream details are version-sensitive; the pinned integration graph-order test is the release gate. Incorrect summary publishing can falsely tell users context was compacted; preserve the explicit barrier. History contains intentionally public tool arguments/results, so keep owner/request-resource authorization distinct and enforce data minimization at storage.

Rollback may disable future compaction while preserving summary metadata/public-history compatibility. This fresh development implementation has no production-data backup prerequisite, per the accepted execution boundary. Never expand a compacted checkpoint by replaying lifetime transcript or delete history to make a recovery test pass. Focused runtime acceptance is recorded in the execution checkpoint; API and Redis integration remain separate owning gates.
