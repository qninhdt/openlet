# HANA acceptance after notification and harness follow-up

Date: 2026-11-15. **The five original turns complete the requested operational lifecycle without a recovery message. Overall content quality and efficiency still do not pass.** The preview failure improved in this run; duplicated analysis, history exploration and unsupported commands remain.

## Implementation boundary

Runtime/tool commit: `8fb680d` (`fix(leta): clarify inbox previews and exclude history lookup echoes`).

- Ordinary root notifications explicitly say `Preview:` and have no read-action footer. Keep the 120-character preview, batching and existing admission/unread behavior. Leti, HITL and scheduled-event inputs remain complete.
- Inbox descriptions explain that `message` identifies a conversation, with unread oldest-first batches by default. It is not an exact-message filter or starting offset. `in_reply_to` selects that incoming message's sender; omit it when contacting somebody else.
- Agent history search excludes history_search/history_read tool call/results in its existing SELECT. Stored history, public pagination, direct entry reads and recipient scoping remain intact. No table, index, extra query or recovery subsystem.
- File listings identify images using media type already present in the existing LetFS response. Images are read directly with file_read; extracted office documents retain their directory presentation. No additional Stat/RPC per entry.
- Prompt replacements clarify voluntary notification reading, early independent delegation, deliverable ownership, concise handoffs, percentage comparison bases, source requirements versus advice, image reading, ordered shell steps and supported path operations.

Monty decision: keep pydantic-monty 1.6.0 / Mirage 0.0.8. Native reproduction confirms that Path.resolve returns text, .parent works and .parents is unsupported. The user explicitly chose supported APIs/paths. No dependency patch, monkeypatch or compatibility wrapper was added.

## Validation and publication

- 31 Leta tests pass; Ruff lint/format pass; strict Pyright reports zero errors/warnings for Leta.
- Real PostgreSQL assertions confirm search self-match exclusion, business evidence, recipient scope, pagination, direct lookup-entry reads and unfiltered public history. The regression used a temporary shadow table and rolled back its changes.
- Langfuse production common/root/Leti **v8**: compiled composition checked before promotion, previous config/model defaults preserved, and compiled WireMock fixtures match Cloud. Compaction stays **v5**; no threshold, retained-tail or summary-budget changes.
- Only Leta API and worker were rebuilt/recreated. Unrelated ingestion/configuration edits were neither staged nor included in this deployment.

## Fresh scenario and method

- Root/session: `0a1ca438-45fe-4174-8cf9-cd6b184dcadd`.
- Analyst: `dafeaf01-473d-5f63-86c0-7f179502b716`; QA: `7ae9c4b1-aee9-5ea9-942d-940dbe7f6d1a`.
- Model: `deepseek/deepseek-v4.1-flash`, medium reasoning effort.
- Zero root history/checkpoints before first input. Reused the same existing HANA source pack, including workbook, DOCX/PDF, signed image, Python reference, receiving plan and private cap. No document regeneration or re-ingestion.
- Sent the five original natural user messages in sequence. Approved personal viewer access and answered the actual supplier-choice HITL with GreenCarton. No additional recovery user message, tool instructions or resource IDs were inserted into the requests.
- No prompt/code changes during the run. Agent-authored files were preserved without tester corrections.

Temporary scripts, API conversation, snapshots, complete history, downloaded deliverables, checkpoints and Cloud evidence: `/tmp/openlet-hana-notifications/`. No acceptance script was added to source.

## Measured comparison

| Measure | First baseline | Second baseline | Previous five turns | Previous with recovery | This run |
|---|---:|---:|---:|---:|---:|
| User instruction turns, excluding HITL answers | 5 | 5 | 5 | 6 | 5 |
| Tool calls | 176 | 206 | 120 | 162 | **211** |
| LLM generations | 117 | 165 | 101 | 129 | **155** |
| Explicit tool-result errors | 9 | 6 | 7 | 8 | **8** |
| Compactions | 4 | 5 | 2 | 3 | **4** |
| Elapsed, including human-response timing | 11m23s | 12m19s | 11m32s | 15m09s | **11m58s** |
| Requested lifecycle completed without extra instruction | Yes | Yes | No | Assisted | **Yes** |

The previous five-turn count omitted requirements, so it is not an efficiency target. This run uses more tools than either original baseline. Fewer generations than the second baseline and a shorter elapsed time than assisted recovery do not establish a general performance improvement from one nondeterministic run.

Tools by agent: root **142**, analyst **50**, QA **19**. Model coverage: **26/27** tools; box_get was not called. Its existing native integration coverage is separate from this model run.

Largest categories: execute **56**, history_read **28**, file_read **26**, inbox_send **16**, file_write **15**, file_list **12**, file_edit **11**, inbox_read **9**, history_search **6**. Only one inbox_list and one hitl_list were called. Not every repeated list is polling: later requests explicitly ask for team, schedule and HITL state.

## What improved and completed

- The first model tool was inbox_read(message=1). Root subsequently opened the full user turns, including turns 4 and 5, rather than requesting a resend of a shortened preview. No forced read middleware or full-message injection was needed in this run.
- Personal access was requested by user identity, accepted, granted and used successfully. No LetFS PERMISSION_DENIED appeared. Root and Leti used the same storage paths.
- Analyst and QA exchanged substantive findings directly. QA caught budget-eligibility presentation and percentage-base issues; corrected calculations agree with the oracle.
- All-in costs: NorthPack **15,044,400**, SouthPack **13,556,160**, GreenCarton **14,886,720**. GreenCarton is **63,280** below the **14,950,000** cap. SouthPack is ineligible because of late delivery.
- Image input was read directly; no image/README lookup failure occurred. The final report recognizes the image's BOX zero-defect result and distinguishes SEAL retest evidence from unconfirmed delivery-lot evidence.
- One-shot reminder actually fired. Group interval changed 600 to 900 seconds with its original anchor and was paused. Native forecast returned upcoming times while paused; the agent reported these as conditional, without resuming it. Both schedules were subsequently deleted, including the fired one-shot.
- Supplier-choice request is answered; personal access accepted; actual-lot question cancelled. No HITL remains pending. The final report/checklist explicitly retain the unconfirmed delivery-lot condition.
- Two semantic searches stayed within shared HANA sources. They found the payment/remedy clause; no unnecessary private/team search scope was added.
- All five workpapers survive at `~/HANA-procurement/` after box archival. The box folder is absent. Four delivered files remain under `~/HANA-de-xuat/`; receiving-checklist copies agree.

## Errors and remaining inefficient behavior

Eight explicit tool errors all recovered without an activity failure:

1. Root created a file before its parent directory existed.
2. Root searched the invented `/home/user/.boxes/...` path and ended its shell command with exit 2.
3. Analyst attempted create-only file_write on an existing CSV.
4. Root's reminder tried inbox_send(to="root") from root, although the intended recipient was the human. It corrected the recipient to the actual member.
5. Root tried cd into the same invented `/home/user/.boxes/...` location. It later discovered the real `/home/.boxes/...` path.
6. Root attempted create-only file_write on an existing report, then replaced it through supported operations.
7. Analyst used unsupported md5sum; shell profile rejected it with exit 126. This is not a storage authorization denial.
8. Root used sorted(Path.iterdir()) to compare handoff files; Monty Path objects do not support ordering. It recovered with supported string-based iteration/comparison.

Two further compound execute calls returned success despite an internal failure: unsupported nl, and import of unavailable shutil followed by a successful later command. Prompt guidance to use supported commands and && did not eliminate these model choices. Counting only tool-result status understates them; no shell-runtime semantics were changed silently.

Remaining costs visible in complete histories:

- Root recalculates the entire task rather than taking a distinct coordinating responsibility. Analyst calculates before delegating QA, reducing useful overlap.
- Six history searches avoid self-matching, but several over-specific AND queries find nothing. Root then opens **28 individual history entries**, often guessing sequence numbers and reading call arguments instead of the adjacent result. The exclusion is correct; evidence selection is still poor.
- Root sends completion/status notices to the team; analyst repeatedly rechecks CSVs and writes another comparison memo despite explicit "no more work" wording. Prompt-only suppression did not reliably stop reopening completed work.
- QA still writes a long review and repeats calculations. Long messages and activity notes duplicate file content.
- Root rereads the user conversation once with unread_only=false; this correctly returns earlier messages in the same conversation. It is expected API behavior, not an unread-cursor reset or data loss.
- Four compactions occurred: root three, analyst one. The expanded history results, repeated calculations and verbose handoffs remain substantial context consumers. This round does not demonstrate fewer compactions.

## Content acceptance remains incomplete

Operational completion is not a full quality pass:

- The requested roughly one-page report remains **5,811 characters / 1,085 whitespace-delimited units**, with seven sections and wide tables. A one-page rendered layout was not demonstrated.
- Recommendations still appear as requirements: the report says price must be confirmed before 20 November although GreenCarton's quoted validity is 21 November, and requires adding a late-delivery penalty without clearly labelling that as proposed advice.
- Both the report and root check note claim that *any* additional price/freight exceeds the cap, contradicting the known **63,280** headroom. Only an increase larger than that crosses the cap.
- Some final report references still point into the archived box folder instead of the preserved handoff location. Final delivery correctly lists the surviving paths, but the report itself has stale references.
- The semantic-search response mixes the actual clause with loosely related descriptions. For example, "No discounts / no deposit counted twice" does not establish a prohibition on negotiated invoice offsets. The correct source clause independently states the offset restriction; these extra associations should not be treated as additional contractual evidence.
- Root's historical excerpts include some call entries described as completed reads; call arguments alone do not prove a successful result. The eventual report gives correct totals and grant state, but the route to the requested evidence is unnecessarily long and imperfectly labelled.

Agent-authored content was not silently fixed after measurement. These are residual model/prompt behavior findings, not a justification for an unapproved orchestration/retry framework.

## Persistence, streaming and observability

- All **11 activity runs completed** with no error_code. The root's long-lived workflow is idle, not deleted.
- All agents retain one latest checkpoint. Exported checkpoints have no unmatched retained call/result pairs, invalid_tool_calls or pending writes.
- Public history pagination returns distinct **20 + 20** entries; lookup history remains present in public history and directly readable.
- SSE recent replay: **39 captured frames replay as 4 frames**, identical after the native event fold, ending RUN_FINISHED. This sample verifies replay/coalescing equivalence; it is not a claim about the whole run's compression ratio.
- A worker-log scan from the first activity start covers **465 lines**, with zero traceback, WorkflowUpdateFailedError, activity-failure, unhandled-task or PERMISSION_DENIED markers. Returned tool errors and partial shell failures remain listed above.
- Langfuse records **11 traces, 1,341 observations, 155 generations** and all three agent sessions, with logical model `deepseek/deepseek-v4.1-flash`. Cumulative generation input **4,083,237**, output **121,932** across repeated requests; these are not context-window sizes.
- All generation costs remain null; no dollar saving is claimed. Two RETRIEVER and two query_embedding observations carry root session attribution. Recorded embedding-cost estimates total approximately **0.00000598**, not an invoice.

Full API E2E, load testing, re-ingestion, Grafana review and dependency patches were not performed in this round. Model adherence and content correctness remain the principal limits; the successful lifecycle does not establish that the golden journey is fully solved.
