# Current whole-plan review

Historical planning review, followed by implementation authorization. Current foundation evidence is in [Phase01 execution](phase-01-execution.md). The user subsequently waived backup and backward-compatibility prerequisites for this development-only rewrite; the current Phase02 supersedes this report's earlier production-conversion assumptions. The planning checks below retain their original scope.

## Scope and accepted baseline

The [19-phase index](../plan.md), [design contract](../design-contract.md), [tool catalog](../tool-contracts.md), research and current delegate reviews implement the [accepted decision checkpoint](../../reports/design-261108-0148-leta-workspace-resource.md). All implementation checklists remain pending/unchecked.

Human-only users replace managed accounts. Root Leta is an independent workspace resource, with Leti inheriting its rights. Explicit phase02 covers identity/schema/headers/claims/generated callers and guarded migration. PostgreSQL owns product read models and LangGraph working checkpoints; Temporal coordinates six Workflow types; required Redis owns disposable cache and one stable event stream per root Leta. One SSE includes all children with AG-UI envelopes and compatible post-Redis coalescing.

No dangerous-tool approval, new receipt table, permanent command journal/retention, operation registry, leasing/fencing, outbox/poller, extra scheduler/chat/Leti service, model-call budget or arbitrary product child cap was added. Small TEXT stays under existing InlineLimit; large text remains blob, with metadata and ordinary source-relative artifact paths for agents.

## Review evidence and resolved integration issues

The user selected gpt-6.1-sol/xhigh for delegated drafting/review. Current reports:

- [Identity/resource review](resource-migration-review.md): actual managed-account removal, typed native actors, canonical scope/home access, teardown ownership and avoiding callbacks into held WorkspaceChanges serialization.
- [Filesystem review](filesystem-rewrite-review.md): small-text APIs, complete applicable hooks, truthful source FILE/artifact paths, Redis authorization/fingerprints, Monty isolation and real GIN benchmark gates.
- [Runtime review](runtime-rewrite-review.md): six Workflow map, SQL-only Local Activities, async graph/sync checkpoint, inbox cursor/public compaction, ordinary shell replay trade-off, resource HITL and schedules.

Follow-up read-only reviews found these concrete integration mismatches, all corrected:

| Issue | Correction |
| --- | --- |
| Old execution phase files and index still described account agents/large TEXT | Replaced with exactly 19 current phases; removed obsolete phase files. Historical reviews are labeled and linked to the current owning phases. |
| API/tool references retained account grantee/authority | user_id human resource owner, root Leta grantee, creator-gated leta.read/manage, no bot member/leave. |
| Old streams used per-run keys, cursor reset on attempt change and PG discovery polling | Stable per-root key, one XREAD BLOCK SSE, valid suffix preserves partial text, reset only for unavailable replay; Redis required. |
| Sparse Workflow commits could not notify an idle stream from SQL-only Local code | Shared regular publish_resource_event boundary for sparse refs; runtime deltas publish directly, never an Activity per token. Publication retry cannot repeat effects or block required cleanup. |
| Redis memory/config and migration CLI ownership references disagreed | Phase18 owns deployment memory/eviction; phase16 replay. Phase03 owns Leta migration CLI/saver setup; phase02/04 cross-service migration/policy. |
| Creator departure fixture immediately attempted creator-only archive | Separate departure fixture; archive journey keeps creator active. |
| API create/PATCH omitted description or used ambiguous prompt field | Canonical description/system_prompt/model_id/reasoning_effort consistently included. |
| Stream phase disagreed with shared Activity arguments | Exact (leta_id,kind,resource_id), publisher derives agent/run envelope identity. |
| Old report/checkpoint implied review 35–42 still pending | Final accepted checkpoint and current plan are explicit; old inventories no longer guide execution. |

Final identity read-only review found no blocker. Filesystem/runtime follow-ups found only the corrected integration issues above. Source navigation and pinned-library evidence are in the owning reports/phases; no duplicate upstream investigation was substituted for runtime tests.

## Validation actually performed

- Checked all 19 phase numbers, pending statuses and unchecked implementation boxes. Each dependency exactly matches the index; all precede the dependent phase, with no cycles.
- Mechanical sweep of 33 Markdown files passed local-link existence, balanced fences and the 800-line limit; largest file 338 lines. Active plan tables have consistent escaped delimiters. No obsolete execution phase files remain.
- ak plan validate returned valid=true with no errors. Reindexed plan store and pinned the current worktree plan; files remain the source of execution progress.
- Inspected working-tree scope: changes remain plan/review/checkpoint/journal records under plans/. No application source, manifests, dependencies, credentials or operational database/service state changed. No commit/push/deployment/model request.
- No owned background process was started or left running by this rewrite. Existing user/lab processes were not stopped.

Validation is document/source consistency, not a successful build or functioning service. Historical lab/benchmark results retain their original scope; they are not final engine acceptance evidence.

## Required implementation experiments

Phase01 must resolve actual dependencies and prove factory/saver/public hooks, sync checkpoint ordering, Monty/Redis/AG-UI, and truthful source FILE plus named/original-ID nested artifact traversal. Phase08 repeats against real LetFS and current authorization, including multiple workers/cache invalidation. A concrete incompatibility must be reproduced before changing accepted paths/stack.

Other mandatory gates are real commit-before-ack/retry/history rotation; graph recovery/public compaction; exact resource-owner grants/revoke/teardown; at/interval/calendar metadata, consumed one-shot state, DST and full bounded previews; default-plan GIN result/space/write measurements; stable SSE bootstrap/resume/coalescing/eviction; coordinated human migration and backup/restore. Source-backed APIs alone do not pass these gates. Controlled provider fixtures exercise runtime; optional paid/live-model smoke is separately reported.

## Handoff

No known unresolved cross-phase design contradiction remains after these corrections. Start phase01 only when implementation is requested, preserve accepted choices and execute focused gates before dependent work. Do not implement old historical account/large-text/receipt/per-run-stream recommendations. Production migration, commit, push and deployment remain outside this planning task.

## Subsequent simplification review: native text transport

The user accepted removing the unnecessary TextSearch streaming protocol and retaining polling for follow. This revision was performed by the controller without subagents. Phases07/08, the design contract, tool catalog and index now agree:

- Unary TextSearch returns a complete file list or intact candidate-line bytes. Explicit output-limit incompleteness returns no partial candidate payload and maps to Mirage's documented None fallback. Permission/dependency/timeout/cancellation failures remain errors.
- No TextSearchFrame, 64KiB line-fragment protocol, completion frame, stream assembly or follow subscription/RPC is required. Existing 8MiB RPC ceiling and small-TEXT/metadata limits remain sufficient for bounded responses.
- Mirage read and lines_containing accept bytes; files_containing accepts a normal list. ByteSource is bytes or an async iterator. Consuming a redirected write iterator under the inline limit does not require client-streamed native writes.
- Follow serves tail -f using an invocation-local iterator around unary range polling, not a durable backend event stream. It obeys interval, current authorization, command deadline and cancellation.
- Existing StreamArchive API is unchanged. Its absent in-repo production consumer makes it a separate possible API-surface reduction, not authority to remove the published contract in this revision. HTTP ZIP/blob I/O and AI/event Redis–SSE remain justified.

The follow-up overengineering sweep reread migration/access, runtime/checkpoint/history, HITL/lifecycle cleanup, schedules/calendar, cache and SSE boundaries. No further concrete subsystem was found that can be removed without reversing an accepted requirement or losing an actual boundary guarantee. In particular, cleanup must avoid the existing WorkspaceChanges deletion mutex; the saver connection lock prevents overlapping graph writers; typed history supports the required UI; calendar completeness handles native result caps. Their presence is not a reason to add more machinery. Keep the six Workflow types, existing idempotency retention and accepted incomplete shell/Monty replay trade-off.

After propagation, the mechanical sweep passed all 19 pending phase/dependency contracts, local links, fences, active tables and file-size limits across 33 Markdown files; ak plan validate returned valid=true with no errors. No application source changed and no runtime tests ran. Runtime/library compatibility, actual response-size/fallback behavior and polling load remain future implementation gates; this review does not report them as passing.
