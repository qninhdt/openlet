# Final scope and whole-plan consistency review

> Historical review of the superseded draft. All items 1–42 have since been reviewed; accepted corrections are incorporated in the [current 19-phase plan](../plan.md) and [design contract](../design-contract.md). Old phase numbers, line references and recommendations below describe that earlier draft and must not be implemented as current requirements. Navigation links now point to replacement owning phases.


Reviewed on 2026-11-08 (Asia/Ho_Chi_Minh). Scope: the accepted brainstorm's current decisions, design-contract.md, tool-contracts.md, plan.md and all 18 phase files. Account/Workspace/operations and filesystem source surveys are taken from review-contracts.md and review-filesystem.md; review-engine.md owns the engine-specific source findings. Only this report is owned by this reviewer.

The requested feature set and 18-phase organization remain fixed. No requested feature is recommended for removal. No unrequested runtime service, Workflow type, operation/delivery table, outbox, reconciliation worker, leasing/fencing engine or model-call budget was found in the current plan.

## Findings resolved during this review

### Medium — two accepted context tools lacked an explicit implementation/test owner — resolved

- **Evidence:** tool-contracts.md:11–12 requires `get_workspace` and `list_workspace_members`. Phase 07:47 mentions the former only as a mount-refresh trigger. Phase 10:28 assigns runtime/tools.py capability-roster assembly, while Phase 10:119–124 never explicitly implements or tests these two adapters. The remaining tool groups have concrete implementation phases: history in Phase 11:123; messaging/boxes in Phase 12:115–118; HITL in Phase 13:122–126; schedules in Phase 14:51; filesystem in Phase 07:184. A bounded name search across all current phase files found no `list_workspace_members` implementation step.
- **Failure scenario:** an executor completes every listed phase checklist and registers the named concrete product tools but omits the member-discovery tool. `request_access` still accepts a human ID, without the accepted agent-facing way to discover it. `get_workspace` can likewise remain an assumed wrapper despite its identity/model/permission/roster contract.
- **Existing owner to reuse:** Phase 03:56–64 supplies typed GetWorkspace/ListMembers/GetFilesystemView; Phase 07:21–25 and :47–50 supplies identity/view hydration and safe refresh. Current `apps/workspace/internal/workspace/service.go:113–139` already owns bounded active-member enrichment, and `apps/workspace/internal/workspace/store.go:174–179` pages active members. The planned wrapper must filter verified human type without losing the scanned cursor when a page contains only agent members.
- **Smallest correction:** assign both tools to the existing Phase 10 runtime/tools.py boundary, using those typed clients and the Phase 07 refresh helper. Add focused schema/identity/model/roster/current-permission and human-only/filtered-pagination tests to the existing runtime test file. No extra service or module is required.
- **Verified resolution:** Phase 10:125 now explicitly owns both implementations in runtime/tools.py, their authenticated root/workspace identity, current model/rights/mount/roster projection and filtered active-human pagination tests. The existing Phase 03 client and Phase 07 safe-refresh helpers remain the integration owners.

### Medium — Phase 08 consumed a migration entrypoint before any phase created it — resolved

- **Evidence:** Phase 08:158 says to use the “phase-01 migration entrypoint” for disposable schema verification. Phase 01:48–61 lists package/config/lifespan/API/worker/tests, and :76–79 defines build/check/test commands, without a migration entrypoint. Phase 17:27 first proposes src/leta/migrate.py; Phase 17:35 then owns the explicit domain/checkpointer migration command. Phase 08 depends on Phase 01, while Phase 17 depends on Phase 08.
- **Failure scenario:** Phase 08 cannot perform its declared real-schema test setup using the promised predecessor command; the executor has to invent that command or borrow work from a later phase. This is a phase ownership mismatch, not a need for another migration system.
- **Smallest correction:** make Phase 08 own the small domain migration entrypoint and disposable-fixture use when it introduces the first domain schema. Keep Phase 17 responsible for image/Compose wiring, coordinated application and upstream saver setup before API/worker readiness. Update the stale Phase 08 reference and Phase 17 file-action wording together.
- **Verified resolution:** Phase 08:28 and :159 now introduce `python -m leta.migrate`, delegate the existing Goose SQL migration mechanism and pinned saver setup, and use it only on an owned disposable fixture during verification. Phase 17:27 consumes the existing worker/migration entrypoints for packaging and deployment. This removes the backward dependency without adding a migration framework.

## Decision deltas checked across the whole plan

| Accepted decision/correction | Consistency evidence |
| --- | --- |
| Existing activity_log is the durable coordinator retry authority across Continue-As-New | Phase 08:98–113 defines resource_change admitted/completed rows and same save_* definitions; Phase 09:69, Phase 12:105 and Phase 14:42 check completed identity before state/RPC effects and save completion before returning/rotation. No new table, Activity definition or Workflow is introduced. |
| Old retries cannot reverse newer accepted state | Phase 08:111–113 retains immutable command identity/snapshot; Phase 12:105 specifies pause K/resume J/rotation/retry K; Phase 14:42 specifies old/new schedule retry against both SQL and native state. Workspace grant replay independently uses existing receipts at Phase 03:81–89 and :166. |
| Six public LLM transcript kinds exclude internal receipts | Phase 08:102 and Phase 11:32/43–50 separate resource_change from inbox_input/assistant/tool_call/tool_result/final_note/compaction. Phase 15:66 uses the same public transcript union. |
| Canonical TEXT above the unary message ceiling remains usable by existing consumers | Phase 04:42–52 requires typed Download/inventory text refs, bounded ReadText/ReadProcessingText, narrowly scoped ingest authority, actual processor eligibility/read updates and >8 MiB downstream regressions. Phase 04:112 assigns the transport/client/processor owners; no second canonical object or global message-limit increase is proposed. |
| Approval is addressed to resource owner; grant is to Leta | Design-contract.md:50–53, tool-contracts.md:46/68, Phase 03:43–45/64, Phase 13:54–65/94 and Phase 18:29 agree. Ask still addresses root owner and completes its tool protocol immediately. |
| Mixed structured forms, no Other, empty selections and optional notes | Tool-contracts.md:45–68, Phase 13:40–52 and Phase 18:26–28 agree. Text answers have a single text field. |
| Box is an immutable undirected communication graph; sending work is separate | Phase 08:57–66, Phase 12:32–60/95–101 and Phase 18:25/31 retain representative routing, one send_message tool, exact roster IDs/names and no DAG/edge executor or implicit final forwarding. |
| Model catalog, inheritance and owner-only Leti overrides | Phase 01:36/42/83, Phase 08:48, Phase 10:40–42, Phase 12:58/77 and Phase 15:29/35/62 agree. Catalog context counts are operational context limits, not a product call budget. |
| One native scheduler with at/interval/calendar and BUFFER_ONE delivery semantics | Tool-contracts.md:76–94 and Phase 14:35–50 agree on canonical time, recurring end_at, preserved one-shot consumption, nominal scheduled_at, bounded preview and delivery-only overlap. Phase 18:53–55 exercises that behavior. |
| Full applicable Mirage hooks, current authorization before cache reads and no agent raw-blob access | Phases 04–07 retain native root-limited text/tree/search/mutations, the complete applicable hook matrix, readonly artifact projection, bounded original-image previews, Redis FRESH and Policy.pre_vfs checks. Opaque shell/Monty recovery remains outcome_unknown rather than automatic replay at Phase 05:107, Phase 07:155 and Phase 10:105. |
| Typed custom input/compaction UI and retained public history | Phase 10:66–70, Phase 11:30–108, Phase 15:66–70 and Phase 16:26/38–42 share saved structured inputs, exact committed summaries, owner-message dedup and PostgreSQL reset authority. Frontend implementation remains outside this backend plan. |
| Recovery extends the existing deployment route | Phase 17:18–25/34–46 extends the owned Compose/bootstrap/recovery/CI machinery and includes model configuration, domain/checkpoint state and native schedule state. Phase 18:34/63–65 requires real restore and all six histories. Redis remains disposable. |

## Review boundaries

The engine review's summary-input correction is now explicit at Phase 11:92: a supported async summarizer projects messages through the public-content allowlist before inference, supplies its own summary prompt, and tests a unique hidden-reasoning marker. It preserves the exact-summary checkpoint/publication contract and adds no compaction service or private upstream override. Engine-specific pinned-source verification remains owned by review-engine.md.

This review did not execute implementation tests, install dependencies, call a provider, mutate a database, start services, commit or deploy. Source/plan agreement does not establish runtime compatibility, performance, crash recovery or restore success; their owning phase acceptance gates remain mandatory.

Status: DONE
Summary: All 18 phases were read, the accepted scope was preserved, and the two small ownership/order gaps were resolved and rechecked.
Concerns/Blockers: No unresolved concrete plan blocker found. Runtime compatibility and recovery acceptance remain unexecuted implementation gates.
