# Runtime plan rewrite review

Date: 2026-11-08, Asia/Saigon. Scope is planning/documentation only. No production source, configuration, dependency lock, schema, database, Clerk state or running service was changed. No package install, provider call, test, migration or runtime acceptance ran.

## Authority and owned files

Read the complete [accepted resource design](../../reports/design-261108-0148-leta-workspace-resource.md), including final items 35–42, repository AGENTS.md, human development rules and every previous owning phase before editing. The current phase files below replace their stale execution instructions; historical reports remain evidence and do not override accepted decisions.

| Phase | Current owner document | Dependency IDs | Rewrite result |
| --- | --- | --- | --- |
| 09 | [Temporal inbox](../phase-09-temporal-agent-inbox.md) | 3 | Six Workflow types; commit-before-receipt, small Workflow state, SQL-only Local versus remote regular Activities, ordinary terminal error, safe history rotation. |
| 10 | [LangChain runtime](../phase-10-langgraph-agent-runtime.md) | 8,9 | Resource subject, sync saver, dedicated advisory-lock connection, exact digest/full input snapshot, saved-result recovery, accepted incomplete shell/Monty replay. |
| 11 | [Public history/compaction](../phase-11-history-and-compaction.md) | 10 | Six typed public variants, distinct chat/activity cursors, persisted summary/input, pre-inference sanitization, complete older-prefix summary. |
| 12 | [Messaging/lifecycle](../phase-12-messaging-and-box-lifecycle.md) | 4,6,9,10,11 | Independent Leta resource creation, immutable whole boxes, exact routing, resource-home/default-access effects, ordered archive cleanup. |
| 13 | [Async HITL](../phase-13-async-hitl-resource-access.md) | 4,9,10,11,12 | Four statuses, mixed forms, creator ask, exact human resource approver, root Leta grantee, exact requester inbox, deadline/cleanup ordering. |
| 14 | [Schedules/calendar](../phase-14-temporal-schedules-calendar.md) | 3,9,12,13 | Native schedules, stable normalization/one-shot consumed state, BUFFER_ONE delivery, bounded complete sorted calendar or clear error. |

Only these six phase files and this report were modified by this task. Exact code owners/symbols/proposed files, unchecked implementation steps, scenario matrices and future commands are included in each phase. Shared domain/store/worker files are sequential integration points, not authorization for parallel writers.

## Retained and removed contracts

- Root `agents.id` is an independent resource; kind=leta, leta_id=id, workspace_id, created_by_user_id and home_scope_id. Child kind=leti inherits root binding, scope rights and effective model_id/reasoning_effort. Thread ID derives from agent ID. No account-ID equality, owner_account_id, bot membership, role, membership_key or leave_key.
- `publish_leta_resource` is regular and writes only Leta-owned resource tuples. Normal archive retains them; admitted W teardown reuses its remove mode after stop/settlement/grant cleanup and before stop acknowledgement. A terminal W-deleting initialization failure reconciles only its own tuples. `ensure_leta_home` calls phase04 Workspace EnsureLetaHomeAccess; Workspace owns storage/default scope publication. `cleanup_leta_access` calls CleanupLetaAccess after HITL settlement and runtime stop. Obsolete account/member/leave/name-sync effects are removed.
- Archive retains home/history and creator read through home_of→leta.read while creator remains active in W. Foreign personal grants contain viewer/editor→leta only; they do not traverse to creator raw access. Workspace deletion enumerates by workspace_id and uses the existing trusted StopLetaForWorkspaceDeletion boundary to close root deleting through the shared domain/store transaction before waiting for its serialized lifecycle command. It does not invoke a Local Activity from RPC. Delayed create active/start compare-and-set loses to that gate; bounded EnsureLetaHomeAccess waits and actual WorkspaceChanges active/root rechecks reject late provisioning without compensating storage deletion.
- One messages table owns inbox and actual human chat. Recipient-row lock makes inbox seq commit-ordered. Update-with-Start returns only after SQL commit. Bootstrap max-merge and receive-only lock preserve busy-agent steering. No outbox or reconciliation poller.
- Six Workflow types stay Agent, LetaLifecycle, BoxLifecycle, HumanRequest, ScheduleChanges and ScheduleDelivery. New narrow Local save_run_control owns the existing unfinished-run yield flag; no direct Workflow SQL, leases, fencing, custom failure-wake, generic resource Workflow or per-tool Workflow.
- LangChain create_agent and AsyncPostgresSaver use durability=sync. Public middleware nodes checkpoint summary/input/assistant before publication. One dedicated saver connection holds the existing advisory lock; overlapping attempts re-read saved result after obtaining ownership. No reconnection under a lost lock.
- Domain IDs, saved tool results and existing downstream idempotency_keys retention remain the retry mechanism. There is no admitted/completed resource_change command journal, extra completion save or promise to replay arbitrary historical commands forever after Continue-As-New. Incomplete shell/Monty results may execute again; no outcome_unknown protocol, execution ledger or replay suppression.
- Temporal history rotates on actual history suggestion/threshold, yielding safely and preserving business run/thread; actual upstream technical step protection must not become a product call budget. No periodic two-minute/128-boundary runner segmentation.
- Only send_message delivers. Root→creator/box, Leti→edge peer, representative→parent as box; final_note is local public history. create_box LetiSpec contains only name/description/system_prompt; creator API alone controls model overrides. Graph is immutable/undirected, disconnected allowed, names unique live with derived slug and no slug field, completed Leti retained IDLE.
- HITL remains pending/resolved/cancelled/expired with decision distinct from grant outcome. Mixed single/multiple/text forms allow null/empty selection plus note and text-only answers, without Other. Ask always targets creator; personal-resource approval targets any exact active same-W human owner, granting root leta:L and delivering to the original requester. Acceptance grants access only, never a held filesystem/tool replay.
- InlineLimit owns editable text size; large text remains object/blob metadata plus ordinary nested artifacts. Runtime paths preserve source/child and /@original-file-id/relative-artifact under authorized mounts, never a separate /artifacts namespace or raw S3 source read.
- Runtime/history publishers use one stable root-Leta Redis Stream including all Leti, with agent_id/run_id plus AG-UI payload. Redis is required; its failure must not repeat applied effects. Ordinary Last-Event-ID reconnect replays available unfinished text; only expiry/trim/loss resets PostgreSQL. Phase09 maps shared regular `publish_resource_event(leta_id,kind,resource_id)` for sparse Workflow-owned lifecycle/control/box/HITL/schedule refs after SQL commit. It delegates phase16's ordinary publisher with independent bounded timeout/retry; exhaustion is an explicit transport diagnostic, not business failure or a teardown barrier. API/runtime/tools call that ordinary publisher directly; basic inbox/run/tokens stay there without per-token Activities. Local Activities remain SQL-only. Reconnect refreshes domain snapshots independently of valid text replay; no outbox/poller. This is a release integration gate, not a phase09 schema dependency on16.
- Calendar has no public pagination/continuation. Internal native1000 matching-time continuation is bounded and must prove completeness; otherwise return a request-too-large/narrower-range-or-filter error. Preserve second-precision round-up, IANA timezone, end_at, interval anchor, pause/admitted delivery, delete admission recheck and one-shot metadata-versus-spec semantics.

## Source evidence and verification limits

CodeGraph was used before current-code questions. It returned current source for WorkspaceChanges/Mutate, DeleteWorkspace, ChangeScopeAccess/UpdateScopeAccess and LetFS CreateScopes. Important observed boundary: WorkspaceChanges holds its mutex while waiting DeleteWorkspace; current DeleteWorkspace proceeds directly to filesystem deletion. Phase17 therefore must stop Leta resources first and use already-admitted trusted direct cleanup instead of calling the locked Workspace mutation queue.

The same boundary affects an accepted HITL grant queued behind workspace deletion. Phase13 requires bounded RPC waits, retained-result/current-rights recovery before lifecycle rejection, actual mutation-boundary rejection of queued grants and settlement of any real applied grant before cleanup. A timeout alone is not proof of non-delivery. Current phase04/17 now record this same direct recovery/rejection path; a real race test remains unrun. It adds no grant journal/background reconciler.

Pinned source read from `/tmp/leta-engine-review/src`:

| Version/source | Inspected contract |
| --- | --- |
| Temporal Python 1.35.0 `client/_client.py:944–955`, `_workflow.py:1080–1091` | Actual Update-with-Start argument shape and conflict policy. |
| Temporal `workflow/_context.py:175–204` | Info current-history length/size and Continue-As-New suggestion methods. |
| LangChain 1.4.8 `agents/factory.py:1643–1688/1834–1857` | Separate middleware nodes, before_model chain and reversed after_model composition. |
| LangGraph 1.2.19 `pregel/_loop.py:2067–2145`, `pregel/main.py:3519–3550` | Latest checkpoint at invocation entry, RAM channels, operational step safeguard and awaited sync checkpoint writes. |
| LangChain `agents/middleware/summarization.py:296/526–564/970–978/1031–1032` | Persisted state replacement, public async summarizer and disabling default 4k tail trimming. |
| Temporal `client/_schedule.py:240–275/279/418/480/950/995` | Conflict-retry callback, calendar defaults, epoch interval offset, native policy/action-limit state. |
| Existing lab `chat/worker.py:178–240` | Dedicated saver connection and session advisory-lock pattern only. DeepAgents/async durability/native approval are not copied. |

Pinned Mirage 0.0.8 paths in `/tmp/leta-filesystem-review/src` were checked for PathSpec/mount_key/_keyed_paths locations; the accepted design already records native alias/file-parent traversal source evidence. A real Mirage–LetFS named/ID-prefixed child traversal test remains phase08 acceptance. Native matching-time cap/endpoints, Schedule action metadata and one-shot action-limit semantics remain real-server integration gates; SDK types alone cannot prove them.

`reports/review-engine.md` remains historical and unchanged. Its retained-command receipts and incomplete opaque-call replay suppression are explicitly superseded by accepted decisions; phase10 and phase11 say so directly. Its upstream source locations remain evidence, not current design authority.

## Documentation checks and remaining integration gates

- Read all rewritten phases after edits and checked their owning contracts against the accepted design. Dependencies match the controller's new 19-phase ordering. No checked implementation/acceptance item was introduced.
- Checked document line counts: each phase is under 800 lines. Readability fixes and Markdown link/checkbox checks are documentation checks only, not runtime tests.
- Canonical links target phase03 schema, phase04 resource APIs, phase06 mutations, phase08 Mirage and phase17/18/19 cleanup/deployment/acceptance. Cross-owner files are integrated by the controller; the final whole-plan link/contract sweep remains its gate. Phase16 owns sparse publisher implementation, mapped in phase09 and used explicitly by phases12–14 after committed transitions.
- Future narrow pytest/replay/check commands are included for execution after phase01 defines the Leta package/scripts. No command output here is a test-pass claim. Durable backup/restore gates precede persistent schema/checkpoint work; workers and state formats must remain compatible on rollback.
- Remaining implementation gates are the real pinned graph/saver barriers, crash/restart recovery, user/leta native isolation, actual delegated Workspace grants, deletion queue race, native schedule metadata/cap/state behavior and accepted complete owner→Leta→box→Leti→HITL→representative journey.

Status: DONE
Summary: Six runtime phases align resource identity, ordinary archive versus admitted W teardown, late-create gates and the sparse post-commit Redis publisher boundary, with explicit owners/steps and unrun acceptance gates.
Concerns/Blockers: Final whole-plan link/contract integration remains controller-owned; runtime, source and tests were not executed by this planning task.

## Controller integration completion

The current 19-phase index and all replacement phase files now exist. Relative links/dependencies passed the final document sweep. Cross-plan follow-up corrections are recorded in [current plan review](plan-review.md); earlier missing-link/ownership notes above describe the parallel rewrite stage. Required runtime experiments remain pending; none were executed by document review.
