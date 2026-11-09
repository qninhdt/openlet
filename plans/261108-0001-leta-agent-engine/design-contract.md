# Leta MVP: accepted design and execution boundaries

This contract consolidates all accepted brainstorm/review decisions, including [the resource redesign and final SSE corrections](../reports/design-261108-0148-leta-workspace-resource.md). The phase files implement this contract; historical source/review records do not override later user decisions. Implementation is authorized. The user confirmed no production data, no backup prerequisite, no backward compatibility and no retained legacy/dead code; use fresh development schemas rather than a production conversion subsystem. Commit, push and deployment remain separately scoped.

## Outcome and component ownership

An active human workspace member creates Leta as a durable workspace resource. It handles independent inputs, delegates through boxes, schedules future work and asks humans without blocking unrelated work. MVP conversation/history/control is creator-only while the creator retains workspace membership. Human personal-resource owners can approve access without receiving Leta's private history.

| Component | Authority |
| --- | --- |
| Existing identity service (apps/account deployment) | Human-only users, Clerk onboarding, own profile, bounded UserSummary/verified-email lookup. No bot account or account ownership. |
| Workspace | Human memberships/personal mappings, generic accessible-scope API, home/default/foreign scope grants and workspace deletion. |
| Leta PostgreSQL | agents, boxes, edges, incoming/outgoing messages, runs, public transcript, human requests and schedule definitions. |
| Leta-owned SpiceDB relations | Resource workspace/creator binding and creator membership-gated read/manage. |
| LetFS | Ordinary scopes/roots, small text/binary/object storage, real artifact children, file lifecycle/quota and per-operation authorization. |
| LangGraph PostgreSQL saver | Working messages/current summary, inbox cursor and graph continuation. |
| Temporal | Six Workflow types, durable orchestration, ordinary retries, timers and native schedules. |
| Required Redis | Temporary per-Leta event replay and Mirage cache, never canonical history or permission authority. |

No cross-service SQL, generic principal/operation/task registry, separate Leti service, new scheduler/chat service or replicated grant table.

## Human identity and resource permission

- Rename mixed accounts to users; keep human UUIDs/Clerk IDs/profile/timestamps, remove type/owner_id/self-owner tuples/managed creation routes and AccountChanges. Preserve human onboarding and ordinary membership roles. Physical apps/account deployment and private AccountService descriptor may retain their technical names; DTOs/methods/headers use users/UserSummary/GetUserSummaries/user_id.
- Public gateway human identity uses openlet_user_id/x-openlet-user-id. Native calls carry a closed verified actor user or leta using mutually exclusive x-openlet-user-id/x-openlet-leta-id, allowed only by exact service/method credentials. Model arguments never choose authority. No per-Leta login/token.
- Root agents row is the Leta resource. Store workspace_id, created_by_user_id and ordinary home_scope_id; no user-ID equality, bot membership/role, managed-owner projection or independent leave/transfer.
- SpiceDB user has no account-owner hierarchy. leta has workspace/creator; read/manage = creator & workspace->read. Scope viewer/editor may name leta:L; manager remains human/workspace usersets. Home scope has home_of@leta:L and its read includes home_of->read. Creator does not inherit foreign scopes granted to Leta.
- Workspace creates home/default scope relationships; Leta writes only its resource relationships. Defaults grant home/shared editor to root Leta, no creator personal access. Leti uses root subject plus box-root restriction, no tuples/grants of its own.
- Creator departure removes human access through ordinary resource policy; no special permanent viewer/archived-file bypass, departure workflow, automatic transfer or newly inferred runtime deletion/pause policy.
- User and Leta use one accessible-scope service; private LetFS candidate listing plus current BulkCheck, not file-tree loads or HITL-history-derived rights.

## Runtime, inbox and communication

- LangChain create_agent builds each agent's async LangGraph; AsyncPostgresSaver uses durability="sync". Working state lives in RAM during invocation, latest checkpoint loads on recovery/new invocation, not every iteration. One stable thread per agent and one active writer; existing dedicated saver/advisory connection guards overlapping Activity attempts without leases/fencing.
- Naming everywhere is model_id and reasoning_effort. Initial provider OpenRouter, server-supported catalog with explicit context/output counts. Creator selects root/child config; Leti inherits unless creator API overrides. create_box agent tool cannot choose model/effort. No product model-call/step budget or forced two-minute/128-boundary segments.
- Incoming messages rows are inbox. Temporal Update-with-Start calls short SQL persistence before acknowledging. Worker outage means pending/unknown admission; retry same message ID. No Signal plus Update duplicate path, outbox, repair poller or replay worker.
- Generic source envelope separates origin, grouping, reply address and content/data. No hardcoded future notification categories. Before model call capture committed high-water snapshot: root gets grouped digest plus inbox tools; Leti gets all pending contents directly. New arrivals during LLM/tools wait for next safe boundary. Input and cursor checkpoint together. If full valid new batch cannot fit after old-context compaction, fail clearly without cursor advancement or silent splitting.
- read_at means details read, checkpoint cursor means notified; neither means finished. No processed/closed state or failure-wake cursor.
- Only send_message delivers. Root sends creator/box; representative receives root messages and replies as box; Leti peers communicate only via undirected edges. No direct child-human chat, cross-box route or implicit final-text forwarding. Final model text is a public short note.
- Whole graph created atomically; no task DAG/edge executor. Names immutable/live-unique, slug derived only, disconnected graphs allowed. Create/send are separate; Leti becomes idle after work, remains until explicit whole-box deletion. Root/box deletion closes input/create gates before stopping sources/runners; files/history retained per lifecycle, box home trashed after children stop.

## HITL and schedules

- Two kinds ask/approval; four statuses pending/resolved/cancelled/expired. Ask targets creator and may mix multiple single/multiple/text questions. Single allows null choice plus optional note; multiple empty list plus optional note; text has one text field, including intentionally blank. No Other option.
- Tools return pending immediately, closing tool-call protocol. Result/expiry enters exact original requester's inbox; no whole-agent waiting-for-human state or retained Python stack.
- Approval requests human personal scope in same workspace; exact resource owner approves; viewer/editor granted to root Leta, never creator/Leti. Acceptance does not replay a held tool. Actual grant outcome distinct from committed decision; timeout is answer deadline, not grant expiry. Revoke blocks new reads, not already disclosed transcript. Current sufficient rights return already_granted.
- Use transaction/server deadline and ordinary duplicate-response handling. Existing downstream idempotency_keys/retention suffices; no new/permanent receipts or two-stage command journal. Unfinished shell/Monty may replay after crash and agent corrects effects. Saved results reuse normally; no synthetic unknown-outcome/replay suppression or global exactly-once promise.
- One schedule product in PG and native Temporal executor: at absolute/relative seconds, anchored interval, calendar fields including "*"/ranges/IANA timezone, optional recurring end_at. No APScheduler process, hardcoded daily/weekly variants or separate calendar subsystem.
- Native BUFFER_ONE covers delivery-to-inbox only; catchup uses Temporal default. Nominal scheduled_at retained. Late one-shot delivers once; metadata/pause edits do not rearm consumed occurrence, explicit time/spec change can. Pause permits already-admitted delivery; delete rechecks source/target and never retracts committed inbox.
- Calendar MVP has no public pagination. Return complete sorted bounded range or explicit too-large/narrower-range error. Internal native matching-times continuation handles server limits without exposing a cursor or silently truncating. PG definitions remain readable during Temporal preview outage.

## Mirage, filesystem and storage

- All agent file tools use Mirage session/VFS dispatch; native adapter supplies every applicable pinned hook. LetFS owns data APIs/authorization, adapter hooks, Mirage commands/parser/matching/fallback. No backend command-specific parser or Mirage fork.
- Small UTF-8 text uses TEXT under existing InlineLimit (default256KiB, configured maximum1MiB). Preserve bytes/BOM/CRLF. Large text remains object/blob on S3; no original body/edit/URL through agent filesystem. Keep existing owner transfers/processing. No new large-text stream RPC/inventory refs/large mutation buffers or migration of large objects into TEXT.
- Ordinary write/edit/append/selected reads work. No NUL/zero-filled pwrite gaps or truncate growth, no UTF-8-corrupt byte edits. Existing guards/quota/processing/trash/copy behavior retained. rm means trash, no purge/quota release; no-overwrite/partial-copy limitations explicit.
- Root home is ordinary scope; child home is .leti/<derived-box-slug>; shared and approved human scopes use /shared/ and /users/<user-id>/. Backend root restriction covers paths/cwd/IDs/aliases/both mutation endpoints; knowing a node ID does not escape a box.
- Artifacts are ordinary child file/directory nodes under original file. Preserve source absolute path/relative artifact and /@<original-file-id>/relative artifact. No separate artifact-ID type, required child-ID lookup, /artifacts mounts or synthetic preview hierarchy. Blob read returns metadata plus actual nested artifact tree/usable paths; readonly provenance remains backend-enforced.
- read_file image returns bounded backend preview/artifact multimodal; source stays FILE, shell/Monty gets metadata. Initial PNG/JPEG/GIF first-frame decode,40M input pixels/2048 edge/4MiB output/two slots. Test actual pinned file-parent path compatibility before expensive integration; do not relabel files or invent a namespace workaround.
- Required Redis cache uses current permissions/fingerprints before cached content, isolated root/projection-free namespaces and FRESH hooks. Workspace/session per invocation, closed afterward; refresh mounts safely after tools/grant/get_workspace. No RAM authority, invalidation bus or optional cache bypass. Monty shares mounts; no host Bash/Python/network/ambient secrets.
- GIN pg_trgm over small TEXT supports generic complete/superset literal hooks, not raw blob/semantic top-K. Test actual query default plans/space/write cost; scans valid for short/common/small cases. Semantic search remains separately scoped/generation-validated.
- Native text read/write/search use bounded unary RPCs. TextSearch returns a complete file list or candidate-line bytes; a response-limit overflow explicitly declines the optimization and Mirage uses its normal permitted fallback. No search stream frames/chunk assembly. Mirage bytes/iterator support does not require backend streaming. The follow hook serves tail -f with invocation-local polling of unary range reads at the supplied interval, ending on timeout/cancel; no changefeed/subscription/follow stream RPC. Preserve existing ZIP/blob-transfer streaming and the accepted AI/event Redis–SSE path; removing existing StreamArchive native API is outside this change.

## History and streaming

PG public transcript is input/assistant/tool call/result/final note/compaction, not checkpoints or hidden reasoning. Persist one typed runtime inbox message and matching UI payload; UI renders custom input cards without parsing raw prompt. Summary plus recent context persists; public history remains. Public-only summary input prevents reasoning disclosure. Publish exact input/summary after sync checkpoint; no default 4k-tail loss or prompt-only trim.

One stable Redis Stream per Leta contains root and every Leti event. Transport envelope carries leta_id/agent_id/run_id and unchanged AG-UI payload. One SSE connection, XREAD BLOCK, UI demultiplexes independent agent/run reducers. No PG discovery polling, per-run stream topology, WebSocket requirement or distributed SSE semaphore/quota.

Worker writes during disconnect; valid Last-Event-ID replays suffix without discarding partial text or reset due only to reconnect/attempt change. Only expired/trimmed/lost log resets from committed PG history, with explicit provisional-output limitation. Fresh sessions bootstrap bounded history/replay, never lifetime history. Coalesce adjacent same-agent/run/block text/args at API AFTER Redis, flush at identity/start/end/custom boundaries, last Redis ID becomes SSE cursor. Redis writes remain original.

Redis is required for startup/readiness. Transient publication errors do not rerun committed domain/tools or bypass cache; recovery/resync uses PG authority and available log. Streams/cache are disposable for restore, not an optional second execution mode. Ordinary gateway/server connection limits and bounded output buffers suffice; no 32-Leti product cap.

## Temporal and execution

Exactly six Workflow types: Agent, LetaLifecycle, BoxLifecycle, HumanRequest, ScheduleChanges and ScheduleDelivery. Canonical Activity map in phase09; Local short SQL, regular remote/runner/Client bridges. Sparse post-SQL resource refs use explicit regular publisher boundary; token streaming stays inside runner, not one Activity per delta. History rotation includes idle/paused and safe active-run yield; no full transcript/body carried into Continue-As-New.

Workspace teardown stops all resources before existing storage deletion. Admitted cleanup does not impersonate creator or reenter WorkspaceChanges mutex held by outer deletion. Pending grants execute active-state revalidation and cannot deadlock teardown or apply after its fence. Do not turn these owner-boundary fixes into new orchestrators/receipts/fencing systems.

Execution progress lives in phase checklists and reports. The user confirmed there is no production data and explicitly waived backup, legacy conversion and backward-compatibility requirements; update fresh development schemas directly and never reset unrelated running environments. Use existing fixtures/commands/generator and exact source/pinned API gates. Migration/restore/model compatibility are execution checks, not already passed by this plan. No commit/push/deployment/paid inference is implied.

## Deferred

Multi-user/group/bot chat, external channels/system/quota notifications, generic Dify/n8n node execution, graph editor/individual Leti mutation, task/job engine, full Google Calendar/RRULE/sync, computer provisioning, new search/memory service, automatic archive purge and distributed connection quota. Preserve every requested MVP capability above; phase count does not add runtime components.
