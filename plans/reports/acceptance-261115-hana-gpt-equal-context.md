# HANA: GPT low versus DeepSeek medium with equal context

**GPT completes the operational journey with about half the tools and no tool errors or compactions.** This run provides evidence that model behavior contributes substantially to the previous inefficiency. It does not prove the harness is flawless or establish a general ranking from one scenario.

## Comparison controls

- GPT root/session: `0d35c756-813c-483f-9793-d778fec57093`; model `openai/gpt-6.1-sol`, requested reasoning effort **low**, through the existing Vilao credential/gateway configuration.
- Procurement Leti `bb89a038-700a-5859-b985-862e32a24621`; quality Leti `6738de10-fd28-57a0-937d-c3626eb89bb7`. They inherit root's selection; Cloud confirms GPT for all three sessions.
- DeepSeek comparison: `0a1ca438-45fe-4174-8cf9-cd6b184dcadd`, `deepseek/deepseek-v4.1-flash`, medium effort. See [previous report](acceptance-261115-hana-preview-followup.md).
- Both catalog input/context limits are **65,536**. The user requested equality after an initial GPT trial started with its catalog-derived 922,000 limit. That trial was paused, deleted through the resource lifecycle and excluded. It is not continued or included in the results below.
- Added only GPT's explicit max_input_tokens=65536 override for this comparison. The override remains as requested. The model's advertised maximum output capability differs, but both role prompts request the same **8,192** output budget; the harness reserves that same budget from the context limit.
- Same deployed Leta code, common/root/Leti **v8**, compaction **v5**, summary/tail/trigger settings, root role, workspace and existing document/artifact content. Prompt compilation still matches the WireMock fixtures. No prompt, code, tools or dependency changes during the measured run.
- Fresh root home/history/checkpoint; zero root history and checkpoints before the first message. All test control, output snapshots and collectors remain under `/tmp/openlet-hana-gpt-equal-context/`.

### Decision-channel deviation

The business requirements of the same five turns were retained. Turns 1, 2, 4 and 5 were sent verbatim. Unlike DeepSeek, GPT asked the supplier choice through normal chat rather than hitl_ask, contrary to the system instruction.

To avoid falsely claiming a nonexistent form had been answered, turn 3's first sentence changed from “Tôi đã chọn GreenCarton trong phiếu xác nhận.” to “Tôi chọn GreenCarton theo đề xuất.” All remaining text is identical. No extra recovery instruction or tool-calling cue was added. This is a disclosed channel/wording difference, not a claim of a byte-identical replay. GPT did later create the requested SEAL-lot HITL correctly.

The supplier selection therefore does **not** pass formal HITL adherence, even though human confirmation was received and the subsequent business work completed. The missing supplier form saves one tool call; it cannot explain the 108-call difference by itself.

## Results

| Measure | DeepSeek medium | GPT low |
|---|---:|---:|
| Context/input limit | 65,536 | 65,536 |
| Requested output budget | 8,192 | 8,192 |
| Tool calls | 211 | **103** |
| LLM generations | 155 | **63** |
| Explicit tool-result errors | 8 | **0** |
| Additional partial shell/API failures found | 2 | **0** |
| Compactions | 4 | **0** |
| History search / read | 6 / 28 | **4 / 4** |
| execute calls | 56 | **12** |
| inbox_read / inbox_list | 9 / 1 | **6 / 0** |
| Activity runs | 11 | **7** |
| Elapsed, including tester response timing | 11m58s | **8m52s** |
| Recovery user instruction required | No | No |

Measured reductions: **51.2% tools**, **59.4% generations**, **25.8% elapsed**. Elapsed includes human/tester timing and provider latency; it is not an isolated model-speed benchmark.

GPT tool counts by agent: root **73**, procurement **19**, quality **11**. DeepSeek: root 142, analyst 50, QA 19. Both root orchestration and specialist work shrink; the difference is not only a shorter root answer.

GPT naturally uses **25/27** tool types. hitl_get and inbox_list are absent; they were not forced into the task. This is not a claim of complete model-driven tool coverage.

## Why this run is more efficient

- History queries use distinctive, short terms: `14.950.000`, `box_create`, `15044400.00`, `granted`. They lead to four specific reads containing the actual calculation result, box-create result and access-grant input, instead of exploring 28 guessed entry numbers.
- Execution uses supported commands and Python operations. No invented /home/user box path, create-only overwrite error, unsupported md5sum/nl/shutil or Path sorting failure appears.
- Specialist outputs are smaller and more focused. A 14-column cost CSV covers the calculation; budget/eligibility explanations stay in the working paper/report rather than expanding every row. QA correctly distinguishes the BOX image result, absent BOX lot identifier and the SEAL retest's narrow scope.
- Root and Leti exchange fewer updates. Procurement updates its state once after the user's choice, but does not repeatedly rerun the complete analysis in response to completion notices.
- The context stays below the same trigger instead of repeatedly expanding through long file arguments, history reads and duplicate verification. Peak recorded GPT generation input is **34,462**, below the configured context limit. This is not a larger-window advantage: the 922,000-window trial is excluded.

## Business and lifecycle checks

- Cost oracle passes: NorthPack **15,044,400**, SouthPack **13,556,160**, GreenCarton **14,886,720**. GreenCarton has **63,280** headroom under **14,950,000**. SouthPack is late; NorthPack exceeds the approved cap.
- Personal access requested by user ID, accepted/granted and read. No private note was copied wholesale into the deliverables.
- Two Leti exchange substantive procurement/QA findings through their links. Root receives the representative's consolidated answer. Image read succeeds directly; the signed SEAL result and BOX result are represented correctly.
- Report explicitly distinguishes the signed finance note from a direct user statement: root's prior message relayed the cap, and the user confirmed supplier choice without approving contingency. It supplies actual history references rather than inventing a historical confirmation.
- Payment wording retains disputed-units-only withholding, no unrelated invoice offsets, three-business-day notice, 48-hour replacement and normal 30-day payment for the undisputed balance. It does not invent a blanket freight/VAT allocation rule.
- One-shot reminder fired. Group reminder changes 600 to 900 seconds and pauses without changing its anchor. Paused forecasts are reported conditionally. Both schedules are deleted, including the fired one-shot.
- SEAL-lot request is created and cancelled. No pending HITL remains. The report/checklist retain the unconfirmed actual delivery lot and require warehouse comparison/retesting if different.
- Four original team workpapers survive byte-for-byte under `~/HANA-procurement/working-papers/`; three report/evidence files and an index are also preserved under the handoff folder. The original delivered report folder remains. Box deletion removes only its saved work folder.
- GPT checks backup hashes before deleting the box, then updates copied Markdown references to surviving handoff paths. The final report points to the retained CSV/checklist, unlike the previous run's stale box references.
- Final report: **3,432 characters / 616 whitespace-delimited units**, versus DeepSeek's 5,811 / 1,085. A rendered one-page layout was not checked, so the length requirement is not certified solely by this count.

## What remains a harness or prompt concern

This result does not make every prior error purely a model defect:

- Monty remains a Python subset. The same harness still rejects some valid CPython APIs and ordinary shell commands. GPT avoids the known limitations in this run; their existence and discoverability have not changed.
- Ordinary inbox delivery still uses previews, with full reads left to the model. Both models read the full five requests in these runs, but the earlier omission risk is not eliminated by an enforced runtime gate.
- History search still uses literal AND matching and individual-entry reads. GPT navigates that contract better; the interface has not become more forgiving.
- Any inbox update can wake a completed specialist. GPT performs fewer unnecessary follow-ups, but the orchestration still permits them.
- Both roots independently recalculate costs after delegating. GPT uses one compact verification instead of a long parallel report, yet overlap remains.
- GPT fails the supplier-choice hitl_ask instruction and initially sends a fairly long proposal/reminder. Prompt adherence is improved overall, not perfect.

file_write's existing overwrite=true argument and description were inspected: the harness explicitly supports full replacement when that flag is supplied. The prior FileExistsError calls omitted it. No write-contract or agent-loop change was made to achieve GPT's result.

**Interpretation:** in this task, DeepSeek medium's repeated history exploration, duplicate review, unsupported operations and verbosity account for a substantial portion of the extra work. The unchanged harness supports a much more efficient GPT low journey at the same context budget. Further harness work should target demonstrated contract problems; these measurements do not justify another broad rewrite or additional orchestration layers.

## Persistence and observability

- All **7 activities complete** without error_code. Three latest checkpoints have no invalid_tool_calls, unmatched retained calls/results or pending writes. Each agent retains exactly one checkpoint.
- Public history pages are distinct **20 + 20** entries. Recent SSE replay folds **39 captured frames into 4 replay frames** with equivalent native state and RUN_FINISHED.
- Worker logs from the first activity start: **189 lines**, no traceback, WorkflowUpdateFailedError, activity-failure, unhandled-task or PERMISSION_DENIED markers. Complete execute-result inspection finds no hidden partial failure in this run.
- Cloud: **7 traces**, **593 observations**, **63 generations**, correct logical GPT model and all three sessions. Recorded cumulative input **1,011,584**, output **19,356**; these are repeated-request totals, not context size. DeepSeek recorded 4,083,237 / 121,932 respectively.
- GPT generation cost estimates are populated (approximately **1.6992** total); DeepSeek generation costs remain null. These are configured/model-derived estimates, not Vilao invoices, and do not establish which run is cheaper.
- Two semantic-search tool calls create three retrieval/embedding observations: first scoped to DOCX and PDF separately, then to their shared parent folder. All carry root session attribution. The two duplicate document representations are a small remaining retrieval inefficiency.

No paid repetition, different scenario, load test, full API E2E, Grafana review or dependency patch was added. One scenario with model-specific tokenizers, requested reasoning settings and response timing cannot isolate every causal factor or guarantee the same gains on other tasks. Temporary evidence includes the disclosed decision-channel deviation and the excluded larger-context trial.
