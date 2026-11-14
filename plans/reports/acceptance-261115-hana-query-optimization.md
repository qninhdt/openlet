# HANA rerun after Leta query optimization

Date: 2026-11-15. **The four query optimizations pass integration checks. The original five-turn journey fails unassisted acceptance.** One additional natural user instruction recovers the omitted operations, but content defects remain. This is not a demonstrated overall efficiency improvement.

## Change and verification boundary

- `messages.pending`: return bounded ordinary root previews from PostgreSQL, rather than full message bodies. Use PostgreSQL's native whitespace class. Keep Leti bodies and HITL/schedule events complete. Preserve the existing renderer and batch admission bound.
- `inbox_read`: resolve the recipient-scoped incoming sequence and conversation in one SELECT, retaining row locks, 20-item pagination, read marking, missing-message errors and empty-filter responses. One SELECT + one UPDATE replaces two SELECTs + one UPDATE.
- `box_get`: use the existing name-aware `boxes.get` directly: three SELECTs replace four.
- Schedules: create uses the already known target name; get/update resolve the display name in the existing scoped schedule read. Remove the standalone target-name query. HTTP schedule reads also receive the display label.

The existing one-to-one sender/HITL/schedule JOINs, history queries, schema, authorization, native agent loop and prompts remain unchanged in this patch.

Checks: 30 Leta tests pass; Ruff lint/format pass; strict Pyright passes with the project interpreter. Real PostgreSQL assertions cover Vietnamese previews, whitespace and truncation boundaries, complete Leti/system content, pagination, read marking, missing/cross-recipient message numbers and scoped schedule labels. Native ToolNode plus real DB confirms name-based box_get uses exactly three SELECTs. Native inbox_list succeeds after cleanup.

An initial setup trial exposed a projection boundary bug: cutting at a space could lose the ellipsis after Python trimmed the preview. That trial was stopped and deleted through the resource lifecycle. The final patch retains a character beyond a possible trailing space before rendering; a real-DB regression assertion covers this case. The trial is excluded from all metrics below, and its evidence remains in the temporary evidence directory.

## Scenario and method

- Fresh root/session: `97aa974f-9176-4dae-a468-67b81fffd97e`.
- Analyst: `9dea0986-0a6b-5eec-9c72-e47a3b536daf`; reviewer: `980fc39d-50fd-592b-bdb0-96b8fc45b283`.
- Model: `deepseek/deepseek-v4.1-flash`, reasoning effort medium; Cloud confirms the logical model name.
- Zero root history/checkpoints before starting. Reused the same eight existing HANA source files in the same workspace: brief, workbook, DOCX/PDF terms, signed QA image, Python reference calculation, receiving CSV and private finance note. The new root requested its own viewer grant.
- Replayed the five original Vietnamese user messages verbatim and sequentially. Approved personal access and selected GreenCarton through actual HITL requests. No tool names or resource IDs were inserted into the user messages.
- Published prompts remained common/root/Leti v7 and compaction v5; no prompt/config changes during the measured run.
- Saved the failed five-turn state before sending one additional, 102-character natural instruction: “Tôi đã gửi đầy đủ nội dung. Hãy đọc lại trọn vẹn hai tin nhắn trước và hoàn tất các yêu cầu còn thiếu.”

Temporary scripts, checkpoint exports, complete histories, API conversations, source-state references, downloaded outputs and Cloud evidence: `/tmp/openlet-hana-optimized/`. No test script was added to the repository. The original two runs remain under `/tmp/openlet-single-deepseek/` and `/tmp/openlet-single-deepseek-rerun/`.

## Comparison

| Measure | First baseline | Second baseline | New: five original turns | New: including recovery |
|---|---:|---:|---:|---:|
| User instruction turns, excluding HITL answers | 5 | 5 | 5 | 6 |
| Tool calls | 176 | 206 | 120 | 162 |
| LLM generations | 117 | 165 | 101 | 129 |
| Persisted tool-result errors | 9 | 6 | 7 | 8 |
| Compactions | 4 | 5 | 2 | 3 |
| Elapsed, including human-response timing | 11m23s | 12m19s | 11m32s | 15m09s |
| Requested cleanup performed | Yes | Yes | **No** | Yes, after extra instruction |

The lower five-turn count includes omitted requirements. It cannot be reported as successful optimization. Recovery added 42 tool calls, 28 generations and one compaction. The query changes themselves reduce DB transfers/round trips; they do not establish a model-tool-count or end-to-end latency percentage.

Final tool calls by agent: root 98, analyst 46, reviewer 18. Compactions: root 2, analyst 1, reviewer 0. All 11 activity runs have completed status and no error_code. This does not mean the long-lived root Temporal workflow has ended; it is active and idle.

## Main failure: previews were treated as complete requests

The full user messages remained intact in PostgreSQL and were retrievable by inbox_read. Native SQL/read checks pass. The failure is the model-facing notification contract and model adherence, not lost storage content.

- The root initially worked from the first preview; it later read that conversation while handling the second user turn.
- For the fourth user turn, root acted on the first paragraph: cancelled the lot question and edited the report. It did not open the full message, so it omitted the requested history excerpts, schedule forecasts and explicit checklist update.
- For the fifth turn, root saw `Trước khi kết …` and asked the user to send the missing text instead of reading the complete message already in its inbox. Both schedules remained undeleted, the box remained active and workpapers had not been preserved in the requested handoff folder.
- The additional short user instruction caused inbox_read to retrieve the complete earlier messages. Root then performed the history lookups, checklist updates, forecasts and cleanup without receiving the business requirements again.

The SQL projection preserves the designed preview/ellipsis for these messages; the semantic failure remains after that implementation check passes. Merely celebrating fewer calls would conceal it.

**Follow-up requiring design review:** either make the notification/read instruction unambiguous and verify it, or supply complete human requests directly while retaining previews for other notifications. This patch does not silently change the previously approved input contract or add an orchestration guard.

## Operational outcome after assisted recovery

- Landed costs independently match the Decimal oracle: NorthPack **15,044,400**, SouthPack **13,556,160**, GreenCarton **14,886,720**. GreenCarton is **63,280** below the **14,950,000** cap. SouthPack misses the delivery deadline.
- Root requested viewer access to the user's single personal storage, received the grant and read the private cap. No LetFS storage-permission denial was observed during the final journey. No full private note appears in the downloaded deliverables.
- Analyst and reviewer exchanged substantive findings directly; their representative returned the consolidated result. No cross-Leta routing occurred. Shared-home paths worked without nested box-home mappings.
- The one-shot relative reminder delivered while QA was still working. The group interval changed 600 → 900 seconds, preserving its anchor, then paused. Recovery queried forecasts and deleted both schedules, including the already-fired one-shot.
- The supplier-choice request is answered; personal access is accepted/granted; the lot question is cancelled. No request remains pending, and actual delivery lot is still unconfirmed.
- The three box workpapers survive at `~/HANA-procurement/` after box archival. The box work directory is absent. Report, CSVs, checklist and history excerpt remain at `~/HANA-launch/outputs/`; root's calculation script remains at `~/.root-check/verify.py`.
- Root/Leti use 25 of the 27 tool types naturally. Missing model calls: box_get and inbox_list. Both pass separate native integration checks without paid inference or history/checkpoint mutation. This is combined integration coverage, not a claim that the model used all 27 tools.

## Errors and residual inefficiency

All eight explicit tool-result errors recovered without an activity failure:

1. Root invented `system_prompt_extra` in both Leti definitions; native validation rejected it.
2. Analyst guessed a PNG README path that does not exist.
3. Analyst's Python output directory did not match the subsequent shell read path.
4. Monty pathlib compatibility: `Path(...).resolve()` returns str, so standard `.parents` chaining failed. A separate native execution reproduced the str result. This is a runtime compatibility limitation, not invalid standard Python or a DB error.
5. Analyst combined a recipient with an in_reply_to number belonging to another sender. Existing validation rejected it; the corrected send succeeded.
6. Root's compound shell command ended with a failed path listing and exit 2.
7. Analyst attempted create-only file_write on an existing script; it later used file_edit.
8. Recovery used unsupported `cp -p`; plain cp succeeded.

Additional partial shell failure: `nl` was denied by the command profile inside a compound command whose later Python step succeeded. Consequently the overall tool status was success. This is a command-allowlist denial, distinct from LetFS storage authorization. Counting only error statuses misses such partial failures.

Root still substantially read/analyzed sources before delegation, generated long task-specific Leti system instructions, and independently recreated the full calculation. QA wrote a roughly 15.6 KB review and explored five ways to rescue the clearly late supplier. Root's completion update woke the analyst for another review with no new substantive assignment. Long final activity notes still repeat already-delivered content.

History recovery used seven searches and eleven reads. Existing history self-matches and broad preview/search behavior remain deferred. No new history query/cache framework was added.

The single semantic-search tool call explicitly searched shared sources, private finance sources and team workpapers in parallel. This produced three retrieval/embedding calls, not a retry loop. Shared terms were found; the two extra scopes were unnecessary for the user's contract-clause question. Scope selection remains a prompt/model efficiency issue.

## Content defects still present

The assisted operational recovery is not a full content-quality pass:

- The report says GreenCarton is 1.06% cheaper than NorthPack and SouthPack is 9.82% cheaper than GreenCarton. Those percentages use the lower-price denominator and describe the reverse markup. The corresponding discounts are approximately **1.05%** and **8.94%**. The underlying totals and labelled CSV delta calculations are correct; the narrative interpretation is wrong.
- The reviewer recommends advancing GreenCarton's delivery to 24–25 November. The final report turns that into a PO condition instead of clearly labelling it a recommendation; the quoted delivery is 26 November and the source deadline is 27 November.
- The recovered checklist says BOX/MAILER/WRAP have no sample results in the pack. The signed image does include BOX 32 checked / zero critical defects. It lacks a BOX batch identifier, which is a narrower limitation and should be stated accurately. The main report acknowledges the BOX image result, leaving an internal inconsistency.
- The report claims one page, but is about **907 whitespace-separated words** with wide tables. A one-page rendered layout was not verified.

Agent-authored deliverables were preserved as evidence; they were not silently corrected by the tester.

## Persistence, streaming and telemetry

- Every agent retains exactly one latest checkpoint. The three exported checkpoints have no unmatched retained tool calls/results, no invalid_tool_calls and no pending writes.
- Public history pagination returns distinct 20 + 20 entry pages. Detail retrieval is also exercised by the agent's history_read calls.
- Recent SSE replay matches the captured events after the native fold and ends in RUN_FINISHED. The sampled 39 live frames replayed as 39 frames; this sample does not demonstrate event coalescing savings.
- A bounded final worker-log scan covers 387 lines from the final journey start and finds no traceback, WorkflowUpdateFailedError, activity-failure, unhandled-task or PERMISSION_DENIED marker. Captured tool errors and the partial nl denial remain listed above; this is not proof against all failures.
- Langfuse returned 11 traces, 1,094 observations, 129 generations and the correct three session IDs. Generation input totals 3,310,420 and output totals 100,503 across repeated requests; these are cumulative usage, not context size. All generation costs are null, so no LLM dollar-cost or savings claim is made.
- All three RAG retrieval and embedding observations carry the root session ID. Langfuse records 0.00000442 per embedding observation; the sum is 0.00001326, as a recorded estimate rather than an invoice. This is separate from the unknown LLM cost.

Full API E2E, load testing, document re-ingestion and Grafana review were not rerun. Existing unrelated ingestion/config edits were preserved and not deployed by this work.
