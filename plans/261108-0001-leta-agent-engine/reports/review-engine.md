# Engine plan review and pinned-source evidence

> Historical review of the superseded draft. All items 1–42 have since been reviewed; accepted corrections are incorporated in the [current 19-phase plan](../plan.md) and [design contract](../design-contract.md). Old phase numbers, line references and recommendations below describe that earlier draft and must not be implemented as current requirements. Navigation links now point to replacement owning phases.


Reviewed on 2026-11-08 (Asia/Ho_Chi_Minh). Scope: phases 08–13, accepted design/tool contracts, and their boundaries with phases 01/03/07/14–16. This is a plan/source review, not implementation or a persistence/restart execution claim. No production code, database, runtime configuration, or Git history was changed by this reviewer.

## Result

Two concrete defects were found and resolved in the revised plan: coordinator commands lacked deduplication after Continue-As-New, and upstream summary formatting could expose hidden reasoning through a public summary. Smaller inconsistencies corrected during review concern model-context metadata, upstream summary trimming, the history-tool signature, and checkpoint-load acceptance language. No unresolved engine-plan defect remains from this review.

## Coordinator command retry finding

### P1 — an old completed update can overwrite a newer command after rotation

**Plan evidence:** `phase-09-temporal-agent-inbox.md:121` rotates lifecycle/box/schedule coordinators between completed commands; `phase-12-messaging-and-box-lifecycle.md:64` promises stable command identity, and lines 77–79 apply configuration/pause mutations. `phase-14-temporal-schedules-calendar.md:41–42` promises stable schedule updates. The original `phase-08-leta-domain-schema.md:38–53/117–121` schema persisted desired agent/schedule state but no receipt identifying an already completed mutation. `phase-15-owner-api-and-ui-contract.md:63` promises retry-safe command identity without specifying this missing local authority.

**Concrete scenario:** pause command K commits and its response is lost. Resume J subsequently commits. The lifecycle Workflow Continue-As-News. Retrying K against the current Workflow execution is now a fresh Update and reapplies pause, reversing J. A schedule update K followed by J has the same problem; a new application of K can also reset one-shot scheduling behavior after its original command was already completed. UUID identity on message/request/create rows does not deduplicate these mutations.

**Pinned server evidence:** Temporal Server 1.32.1 `service/history/workflow/update/registry.go:455–468` checks the current registry/store for a completed Update, while `registry.go:226–235` creates a new Update when none exists. `service/history/workflow/mutable_state_impl.go:1546–1555` returns NotFound when the current execution has no matching UpdateInfo. Continue-As-New creates a new mutable state at `mutable_state_impl.go:6242–6250`; `NewMutableStateInChain` at `mutable_state_impl.go:628–655` initializes new state and carries selected fields, without copying UpdateInfos. An Update ID by itself is therefore not a lifetime command receipt. SDK 1.35.0 `temporalio/client/_workflow.py:813–833` also exposes the addressed run separately from Update ID and states timeout does not cancel the Update.

**Minimal correction agreed with controller:** reuse the existing activity journal for internal immutable admitted/completed command entries, keyed by the stable command key plus actor/root/action namespace. Save normalized immutable request/hash and original resource snapshot at admission; save the acknowledged result only after all required effects/cleanup finish. An exact completed retry must return its saved result **before** changing desired state or issuing remote effects; a payload mismatch conflicts. Pending retries reuse the saved canonical snapshot under the existing serialized coordinator. Use the existing save_* Local Activity definitions for both stages, with no new Workflow, Activity definition, operation entity, table, outbox, lease, or fencing engine. Retain completed identity so old retries never become fresh commands. Keep these internal receipts outside the six public LLM-transcript variants, or explicitly project them as separate domain references rather than assistant/tool history.

**Required regression:** K pause → lost response → J resume → forced Continue-As-New → retry K leaves J effective. Repeat for a schedule spec/pause change and for lost completion after native Schedule acknowledgement. Also repeat a Local Activity after admission commit but before its marker commits, and after completion commit but before handler response. Count one acknowledged effect and verify immutable snapshot/result reuse.

**Resolved in the revised plan:** phase 08:109–113 now owns immutable resource_change admitted/completed variants, original snapshots, completed-first checking and retained command identity. Phase 09:69 propagates this to Local save_* definitions; phase 12:105 applies it to lifecycle/config/control; phase 14:42 adds same-definition SQL completion after native acknowledgement plus the K/J/rotation regression. Phase 11:32 explicitly excludes internal receipts from the six LLM-transcript variants and history tools. This addresses the finding without adding a table, Workflow or Activity definition.

## Summary disclosure finding

### P1 — filtering history output alone does not prevent reasoning disclosure through compaction

**Plan evidence:** `phase-11-history-and-compaction.md:52–54` requires public-block allowlisting and excludes provider reasoning from persisted public history. Its durable compaction algorithm uses the upstream summary and publishes its exact persisted text. The original plan did not require filtering private provider blocks before the summarizer consumes the working messages.

**Concrete scenario:** a provider returns AIMessage content with both intended text and a reasoning block. The working checkpoint retains that message. Upstream summarization serializes the reasoning into its model prompt; the summarizer can paraphrase it as ordinary summary text, which the public compaction entry then publishes. Filtering blocks from the original assistant entry cannot remove reasoning that is already embedded in generated summary prose.

**Source evidence:** pinned LangChain1.4.8 `agents/middleware/summarization.py:988–993` calls `get_buffer_string(messages,format='xml')` on the checkpoint messages. Its declared lower-bound dependency is `langchain-core>=1.7.4` (`langchain-1.4.8.dist-info/METADATA:27`). The inspected lower-bound core1.7.4 `messages/utils.py:168–171` explicitly serializes a reasoning block to `<reasoning>…</reasoning>`; `utils.py:447–463` uses this serializer for XML content blocks.

**Minimal correction:** before summary inference, use the same public-content allowlist to remove reasoning/thinking/reasoning_content and private provider metadata from the messages supplied to that inference. Preserve message/tool IDs, public tool-call/result grouping and required user/public content. A supported async function/Runnable passed through SummarizationMiddleware's public `summarizer` parameter can perform this projection and call the configured async model; no private formatter override is needed. LangChain source documents function/Runnable summarizers at `summarization.py:379–383/396–405` and invokes the function with the selected old messages at lines 974–976. Alternatively sanitize model-state input if the provider protocol permits it, while retaining any required opaque provider continuation privately.

**Required regression:** inject distinct hidden-reasoning and public-text markers into a realistic provider response. Assert hidden marker is absent from the summarizer request, summary checkpoint/public compaction entry, SQL transcript, SSE and API, while public text/tool grouping survives. This is a source-backed boundary correction, not a request for a separate summarization engine.

**Resolved in the revised plan:** `phase-11-history-and-compaction.md:92` now specifies the supported `async summarize_public(messages: list[AnyMessage]) -> str` callable. It copies/projects raw selected messages into the public allowlist before its own fixed prompt formatting, preserves public tool structure, uses bounded async inference, and requires the private-marker regression. This bypasses default XML formatting through the public hook without changing upstream compaction/checkpoint ownership. Source `summarization.py:44–50/297/468–469/974–978` confirms the callable type, constructor, coercion, async invocation, and early return before default formatting.

## Resolved inconsistencies

| Concern | Source and failure | Current correction |
| --- | --- | --- |
| Model-context metadata was absent | Summary thresholds and full new-input fit checks require an actual selected model budget, but the original catalog only contained id/model/reasoning modes. | Phase 01 now requires context_window_tokens/max_output_tokens; phase 11:95 derives usable input budget after output/system/tool overhead. |
| Default upstream summary trimming drops old prefix content | LangChain `agents/middleware/summarization.py:116` defaults to 4,000 tokens; lines 970–980 trim before async summary generation; lines 1028–1043 keep the last tokens with partial messages. Returning a real persisted summary does not prove the complete old prefix was summarized. | Phase 11:95 explicitly selects `trim_tokens_to_summarize=None`, which pinned source supports at lines 296/362–365/1031–1032, and requires complete-prefix coverage. The supported public summarizer must enforce its own input budget instead of copying the default overflow retry, which can omit the middle at source lines 981–985 and 1022–1025. |
| History tool had two incompatible signatures | The original phase 11:111 described a seq-range read, while tool-contracts:14 defines entry_id/start_line/max_lines. | Phase 11:113 now matches the catalog: `read_history(entry_id,start_line=1,max_lines=200)`, current agent only, no agent_id or seq-range argument. Owner API selection/pagination remains separate. |
| One checkpoint-read assertion contradicted recovery selection | `graph.aget_state` itself calls `aget_tuple` at LangGraph `pregel/main.py:1485–1501`; a subsequent invocation loads its checkpoint at `pregel/_loop.py:2067–2096`. | Phase 10:134 now permits bounded recovery snapshot plus graph-entry load and prohibits reload on each model/tool iteration. |

## Verified engine contracts

| Contract | Plan evidence and conclusion |
| --- | --- |
| Actual Update-with-Start syntax and honest receipt | Phase 09:75–85 matches Temporal 1.35.0 Client overload/implementation. `WithStartWorkflowOperation` accepts the positional bootstrap argument and mandatory conflict policy. The operation is recreated per transport retry; SQL message identity is the final dedup authority. |
| Commit-ordered inbox and concurrent steering | Phase 08:131–141 allocates seq under recipient row lock, rechecks ID, and acknowledges after commit. Root recipient avoids SHARE→UPDATE upgrade. Phase 09:89–95 locks only receive persistence/seq merge, preserving admission while run_agent is busy. Bootstrap max-merge at phase 09:103 avoids dropping a concurrently admitted message. |
| Six Workflow types and correct Activity boundary | Phase 09:32–69 preserves Agent, LetaLifecycle, BoxLifecycle, HumanRequest, ScheduleChanges, and ScheduleDelivery. Local Activities contain short Leta SQL; runner/remote effects/Workflow bridges are regular. No per-call/edge Workflow or secretly orchestrating batch Activity was introduced. |
| Long-lived idle/paused/active histories | Phase 09:113–123 checks current history size/count/suggestion, drains handlers, rotates idle/paused states, and cooperatively yields active runner state. Phase 10:109–115 retains the same business run/thread and segments operationally without a product model-call budget. |
| Dedicated saver connection and resource cleanup | Phase 10:74–80 takes the session advisory lock on the same dedicated AsyncConnection used by the saver, rechecks completed run after acquisition, refuses reconnect without reacquisition, and closes invocation resources on failure/cancellation. This follows the useful lab pattern without claiming global side-effect fencing. |
| Resume/finalize/new-pass distinction | Phase 10:82–96 distinguishes terminal SQL result, completed checkpoint awaiting finalization, pending ordinary nodes with input=None, control interrupt with Command(resume), and a new business run. Stable thread does not imply appending new input over unfinished graph work. |
| Supported middleware/checkpoint barriers | Phase 10:45–62 and phase 11:84–105 use separate before_model nodes for boundary/summary/input/publication and after_model publication. Pinned factory creates these nodes and chains them; sync durability waits between supersteps. The real pinned graph/saver ordering test remains mandatory. |
| Actual public tool execution start | Phase 10:100–106 distinguishes planned assistant tool calls from tool_call entries written immediately before execution. Persisted result reuse and unknown opaque effect recovery use the existing journal; compound shell/Monty calls with start but no result do not automatically execute again. |
| Typed public history and compaction | Phase 11:30–86 defines the six transcript variants, runtime input metadata, separate owner-chat projection, no provider reasoning storage, durable summary identity, and publication after checkpoint/SQL commit. Public tool data remains intentional history; permission revoke cannot erase already-read context. |
| Fixed graph and representative routing | Phase 08:57–66 and phase 12:32–60 preserve atomic immutable graph, undirected edges, no DAG executor, representative-only parent route, actual sender audit, and separate create/send behavior. A final note is not an implicit message. |
| Names and configuration | Phase 08:47–48/61–64 and phase 12:55–58 make names unique among live resources, permit reuse only with fresh IDs after archive/trash, preserve descriptions/prompts, and validate effective inherited model/reasoning choices. No slug field or agent graph-edit tool is added. |
| Structured ask | Phase 13:40–52 and tool-contracts:45–68 support mixed multi-question forms, null/empty selection with optional note, text-only answer fields, exact question/option IDs, and no Other sentinel. A pending ask completes its tool protocol and does not suspend agent work. |
| Correct resource approver/grantee | Phase 03:43–45/61–64 and phase 13:54–65 resolve the actual active human resource owner; that human approves; root Leta receives viewer/editor access even for a Leti requester. Owning Leta does not allow accepting another human's resource approval. |
| Deadline, revoke and archive races | Phase 13:80–112 arbitrates deadline after SQL row lock with clock_timestamp, keeps decision separate from actual grant outcome, preserves grant_key, settles accepted grants before archive cleanup, and skips deleted requester delivery. Phase 03:85–89 provides durable internal grant receipts and serialized grant/leave so an old lost-ack grant cannot regrant after revoke. |
| Mirage/streaming boundaries | Phase 07:45–75 and phase 10:43 refresh only safe mount boundaries and reauthorize backend operations/cache access. Phase 16:24–43 keeps Redis provisional/bounded, publishes typed durable refs, resets orphaned suffixes, and treats stream failure as transport failure rather than a graph/effect retry. Mirage cache failure behavior is separately phase-07-owned. |

## Pinned source record

The source cache used here is `/tmp/leta-engine-review/src`, extracted without installing these packages into the repository environment. Original wheels are in `/tmp/leta-engine-review`. The earlier `/tmp/leta-research` directory did not exist during this review. The lines below identify versioned distribution source, not an assertion that all libraries have run together.

| Distribution | Downloaded wheel SHA-256 |
| --- | --- |
| [langchain 1.4.8](https://pypi.org/project/langchain/1.4.8/) | `31ddb8688db67f9eb1fd4e77594573ef863b2e3c086397273d4a7a3ff4245b45` |
| [langgraph 1.2.19](https://pypi.org/project/langgraph/1.2.19/) | `6094a5cbed52a77d8c74c276fcd2056abde7b2836eab1c7a6b74bacbd1a269b3` |
| [langgraph-checkpoint-postgres 3.2.0](https://pypi.org/project/langgraph-checkpoint-postgres/3.2.0/) | `4d89526ab3dff0c71d575233e4132327f95812deb07b6c2e75fc473525b5b8fc` |
| [temporalio 1.35.0](https://pypi.org/project/temporalio/1.35.0/) | `45b5438f41ab154eda4eea40069df2fa8779cb8f5c27f266b917a700bfba8bb8` |

Precise evidence paths under that extracted cache:

- `temporalio/client/_client.py:944–955/987–1045`: single-argument execute_update_with_start_workflow, USE_EXISTING semantics, worker delivery/completion and timeout ambiguity.
- `temporalio/client/_workflow.py:1080–1091`: WithStartWorkflowOperation typed bootstrap argument and id_conflict_policy; lines 813–833 distinguish addressed run, Update identity and timeout.
- `temporalio/workflow/_context.py:175–204`: current history length/size and Continue-As-New suggestion APIs.
- `langchain/agents/factory.py:1643–1688`: independent middleware nodes; lines 1834–1857 chain before_model hooks and place after_model after model. Multiple after_model hooks run in reverse composition order, so generated graph inspection remains a useful gate.
- `langgraph/pregel/main.py:3519–3550`: superstep semantics and awaited sync checkpoint future before the next loop tick.
- `langgraph/pregel/_loop.py:2067–2145`: entry loads the saved checkpoint, initializes checkpoint/RAM channel state and sets operational recursion stop.
- `langgraph/checkpoint/postgres/aio.py:50–65/186–215/418–428`: saver accepts a connection, reads latest thread/namespace with checkpoint_id DESC LIMIT1, and serializes its cursor use. This does not provide ownership over unrelated side effects.
- `langgraph/types.py:903–925`: public interrupt/Command continuation; a resumed node starts again and re-executes its pre-interrupt logic.
- `langchain/agents/middleware/summarization.py:526–564`: async summary partitions old/recent messages and returns RemoveMessage(REMOVE_ALL_MESSAGES) plus summary and retained suffix. Lines 842–847 create the summary HumanMessage with lc_source=summarization. Lines 296/362–365/954–985/1028–1046 establish trim=None and trimming/overflow failure behavior.
- `langchain/agents/middleware/summarization.py:379–405/974–976/988–993` and additionally inspected minimum dependency `langchain_core/messages/utils.py:168–171/447–463`: supported public async summarizer substitution and the default XML reasoning-serialization path. Core1.7.4 is evidence for this supported dependency behavior, not a claim that the future uv resolution has selected that transitive version.
- `/home/qninh/projects/agent-lab/labs/durable-chat/chat/worker.py:178–209/235–240`: dedicated connection, advisory lock and saver-on-that-connection pattern. Lab DeepAgents, async durability, recursion100 and native dangerous-tool approval are not product authority.

The additional pinned server files are under `/tmp/leta-engine-review/server` and come from [Temporal Server v1.32.1](https://github.com/temporalio/temporal/tree/v1.32.1): `service/history/workflow/update/registry.go`, `service/history/workflow/mutable_state_impl.go`, and `service/history/workflow/context.go`. Their exact relevant lines are cited with the coordinator finding.

## Verification limits

Source AST checks confirmed the four named Client/factory/saver methods and supported summarizer/trim constructor keywords in the downloaded distributions. No dependency installation, model call, real saver/Temporal execution, database mutation, or system test was performed. Implementation gates already require real compiled graphs, disposable PostgreSQL/Temporal, deterministic inference-boundary models, crash injection and six replay histories; source support does not replace those gates. Only this report is owned/modified by this reviewer.

Status: DONE
Summary: Engine/source review completed; coordinator retry and compaction disclosure findings are resolved in the plan with implementation regressions required.
Concerns/Blockers: None for planning. Real graph/saver/Temporal execution remains an implementation acceptance gate, not a claim of this review.
