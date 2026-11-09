---
title: "Phase 12: Messaging, immutable boxes, and agent lifecycles"
status: in-progress
priority: P1
effort: 5d
dependencies: [4, 6, 9, 10, 11]
---

# Phase 12: Messaging, immutable boxes, and agent lifecycles

## Outcome and dependencies

An active human workspace member can create a long-lived Leta resource; its creator alone may configure/pause/resume/archive it while still a member. Leta creates an immutable communication box, messages its representative, and deletes only whole boxes. Leti communicate along allowed edges, and representative returns results as the box. Completed Leti becomes IDLE and remains addressable; final text is a note, never delivery.

Depends on [Workspace resource APIs](phase-04-workspace-resource-access-and-scope-view.md), [LetFS mutations](phase-06-letfs-text-mutations.md), and runtime/history phases09–11. Schema is [phase03](phase-03-leta-domain-schema.md); Activity map is [phase09](phase-09-temporal-agent-inbox.md). Later HITL/schedule implementations must integrate the cleanup bridges before release. This is a release gate, not a dependency cycle requiring placeholder behavior. [Accepted design](../reports/design-261108-0148-leta-workspace-resource.md) is authority.

Messaging/inbox and root/box lifecycle are implemented, including native provisioning, home identity/trash, pause/resume, HITL/schedule settlement, sparse publication and workspace teardown. SQL/Temporal/saver/native tests and the real Compose journeys cover routing, recovery, busy stop, rotation/replay and checkpointed tools. See the [final acceptance evidence](reports/acceptance.md); the [execution checkpoint](reports/phase-12-execution.md) preserves earlier increments.

## Current evidence and file inventory

Current `WorkspaceChanges`/`DeleteWorkspace` serialize mutations and teardown; `LetFS.Store.CreateScopes` validates stable scope IDs independently of accounts. Current CreateNode generates an ID and its receipt expires; phase06 owns optional desired node_id plus identity preconditions for home retry. Phase04 owns `EnsureLetaHomeAccess`, `CleanupLetaAccess` and typed native validation. Leta never writes other service databases or scope tuples; it publishes only its own `leta` resource relationships.

CodeGraph source showed `apps/workspace/internal/temporal/relationships.go::WorkspaceChanges` holds its mutex while waiting for `DeleteWorkspace`, which immediately deletes filesystem storage today. Phase17 must stop resource runtimes before storage teardown and admit trusted cleanup without waiting back on that locked mutation queue. A normal creator command still requires active membership; already-admitted workspace deletion uses the trusted workspace credential and persisted exact binding.

| Action | Absolute path | Purpose |
|---|---|---|
| New proposed | `/home/qninh/projects/openlet/apps/leta/src/leta/temporal/lifecycle.py` | `LetaLifecycleWorkflow`, `save_leta_change`, `publish_leta_resource`, `ensure_leta_home`, `cleanup_leta_access`. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/src/leta/temporal/box.py` | `BoxLifecycleWorkflow`, `save_box_change`, `ensure_box_home`, `trash_box_home`. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/src/leta/runtime/messaging.py` | `send_message`, allowed roster resolver, `list_inbox`, `read_inbox`. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/src/leta/runtime/boxes.py` | `LetiSpec`, `create_box`, `list_boxes`, `get_box`, `delete_box`. |
| Modify earlier files | `/home/qninh/projects/openlet/apps/leta/src/leta/store.py`, `/home/qninh/projects/openlet/apps/leta/src/leta/domain.py` | Atomic graph/lifecycle/snapshot methods. |
| Modify earlier files | `/home/qninh/projects/openlet/apps/leta/src/leta/runtime/tools.py`, `/home/qninh/projects/openlet/apps/leta/src/leta/worker.py` | Capability roster and Workflow/Activity registration. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/tests/test_messaging.py` | Routing/identity/tool schema tests. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/tests/test_lifecycle_integration.py` | Actual remote provisioning, races, archive/trash/retry. |

## Messaging contract

Use one `send_message(to,content,in_reply_to?)` and server-provided allowed roster. IDs are canonical addresses; name resolution is exact within this roster, with ambiguous/unknown names rejected rather than globally searching users. Validate content/size and referenced message visibility before delivery.

| Sender | Allowed target | Actual recipient and source |
|---|---|---|
| Leta | Its creator | messages.recipient_user_id=created_by_user_id; source describes Leta; real creator chat event after SQL commit. |
| Leta | Its active box ID/name | Resolve representative agent; receive Update-with-Start; source Leta, reply address parent Leta. |
| Leti | Peer linked by undirected edge in same active box | Peer receive; source actual Leti, reply address actual Leti. |
| Representative | Parent Leta | Parent receive; source `{type:'box',id:box.id,label:box.name}`, reply address box ID; sender_agent_id retains true representative. |

No Leti→owner chat, no nonrepresentative→parent shortcut, no cross-box/cross-Leta message, no edge traversal executor. One-Leti box uses the same representative route. A reply_to address is still checked against the current roster; an old envelope cannot grant new routing permission.

Creator→Leta API requires current `leta.read/manage` as appropriate, uses authenticated user source and the same recipient inbox path. source.type remains adapter-defined text; engine code does not enumerate chat/schedule/HITL as exhaustive origins. Actual source IDs/permissions come from backend, never a display label. Admin/member status alone does not expose another creator's conversations.

Effects use phase10's persisted tool-call-derived message ID. Agent recipient delivery acknowledges **commit only** and returns immediately while recipient is busy. Creator recipient inserts one immutable message row with seq=null using the same effect ID, then emits a domain message event. One messages table owns both routes; no separate chat/inbox copy. Retry checks immutable recipient/content/routing; no duplicate chat bubble or workflow-start effect. Do not turn a final model response into send_message automatically or echo text already sent.

`list_inbox`/`read_inbox` are Leta-only and use conversation_id=opaque conversation_key plus bounded cursor/IDs. When an adapter omits a grouping key, admission derives it from the generic source type/ID pair; no source categories or conversation entity are added. `read_inbox` sets read_at only for the detailed rows returned, not a pagination lookahead row, the entire digest group or future arrivals. Runtime commits these markers with the existing saved tool-result row in one SQL transaction, so a lost result cannot hide unread input on retry. Cursor delivery is checkpoint state and read_at is a user-facing read marker; neither completes a task. Conversation grouping has no close/processed state.

## Box specification and immutable graph

`create_box` receives display name, description, `LetiSpec{name,description,system_prompt}[]`, one representative by local spec name, and undirected edges by those names. The agent tool schema permits **only those three LetiSpec fields**, never model_id/reasoning_effort overrides; only creator API may set overrides later. Names/edges resolve before reserving stable IDs; reject duplicate/self/foreign endpoints and absent representative. No DAG/execution order; disconnected topology is valid.

- Reserve one box ID and every Leti/home ID from the persisted create call before side effects. Same call+same payload returns the same box; changed payload conflicts.
- Leti names are unique among live agents across the Leta, not merely within the box. Box names and derived home path are unique among live boxes. Preserve the accepted deterministic name-to-slug policy, including collision checks; **no slug field** is introduced. Serialize root gate and whole graph insertion. After explicit box archive/trash, reuse names only with fresh IDs; never resurrect old agents/home.
- Each Leti belongs to this box, has no user, account, membership, scope or independent grant, and uses `leta:L` plus backend-enforced box-root restriction. All Leti share `.leti/<derived-box-slug>` under root home, with private invocation sessions.
- Box graph/name/Leti names are immutable. Owner may set Leti model/reasoning override through phase15 API; null restores inheritance and effective catalog pair must be valid. No agent graph-edit tools or update_agent tool.
- `list_boxes/get_box` expose authorized description, prompt/config, roster, representative, edges, state, schedules, and pending requests. Inspection is not permission to mutate graph or deep transcript tools.
- Creating a box starts runtimes after home is ready, but **does not send initial work**. Caller sends a separate message when desired. No delete_leti in MVP.

## LetaLifecycleWorkflow commands

Stable Workflow ID `leta-lifecycle/<leta_id>`; serialized Update commands, preserving client command identity through SQL and RPC. Use the Local/regular mapping in phase09. Every terminal command drains handlers before return/Continue-As-New, and long-lived coordinator rotates between completed commands by current-history thresholds.

### Create

1. Ingress authorizes verified human `workspace.create_leta`; phase04 revalidates active creator/workspace binding at its own boundary. `save_leta_change(initializing)` persists independent root resource ID, kind=leta, leta_id=id, workspace_id, created_by_user_id, reserved home_scope_id and accepted profile/config. Thread ID is derived from id. Repeated create compares immutable payload; no owner_account_id, membership_key, leave_key or user row is created.
2. `publish_leta_resource(mode=publish)` reconciles exactly `leta:L#workspace@workspace:W` and `leta:L#creator@user:U` for an eligible initializing/active binding. It rechecks the local gate on retries; a deleting/archived root cannot republish removed tuples. All read/manage remains creator intersect current workspace read.
3. `ensure_leta_home` calls `Workspace.EnsureLetaHomeAccess` with persisted IDs and a stable ordinary storage-create request key. Workspace validates trusted Leta caller/creator/create_leta/exact W-L-H binding, uses existing LetFS CreateScopes, and owns `scope:H#home_of@leta:L`, `scope:H#editor@leta:L`, `scope:S#editor@leta:L`. It participates in WorkspaceChanges serialization and rechecks W active plus canonical root eligibility at actual execution; no member role, creator permanent viewer or personal membership is added. Native waits are bounded; retry reads direct current W/root state rather than waiting forever behind a deleting W's mutation lock.
4. `save_leta_change(active)` records returned home mapping only with compare-and-set on the existing initializing/nondeleting root gate. `start_agent(root)` also rejects the current deleting/archived gate. A delayed provisioning acknowledgement cannot override deletion. Report active only after actual effects acknowledge; emit sparse root-state ref through shared regular publish_resource_event after committed state, with publisher-only retry.

Transient failures retry the current regular Activity with identical resource identity. Permanent conflict leaves explicit initializing/error state for inspection/retry; never fabricate active status, delete a real home as compensation, or add a provisioning operation entity. Local save methods contain short Leta SQL only; every remote call/SpiceDB effect is regular.

If current Workspace deletion permanently rejects an initializing root, record that terminal initialization failure through the existing lifecycle state/error path and reconcile only this root's own resource tuples with `publish_leta_resource(mode=remove)`. Keep the row/tombstone available for W deletion enumeration. Do not start a producer, retry active-only provisioning forever, create a user/member or delete storage as compensation; W teardown remains its storage owner.

### Configure and pause/resume

`save_leta_change(config)` updates accepted root name/description/system_prompt/model_id/reasoning_effort and validates effective inheritance for affected Leti. Profile comes from Leta, with no identity-service/name-sync call. Keep thread/context/history. Creator-only Leti model_id/reasoning_effort override uses this root command path; null restores inheritance. Box graph/name/prompt stays immutable.

Pause/resume: save root paused state plus snapshot agent IDs, then control_agent per target with bounded concurrency. Runner reads current DB state at safe boundary. Inbox/HITL/schedules continue receiving while paused. A child created while root paused starts paused effectively; do not overwrite root authority with stale command snapshots. Resume a continuation even if all current input was already collected.

After committed visible config/control state, invoke shared regular publish_resource_event for the root; do not put Redis inside save_leta_change/save_run_control. Publication exhaustion reports transport failure only and cannot undo config/control or stop required lifecycle cleanup.

### Archive

1. `save_leta_change(deleting)` atomically closes root creation/receive gates and returns snapshot of all root/Leti IDs, boxes, active schedules, and unsettled HITL requests. Accepted approvals with no completed outcome are included.
2. `change_schedule(delete)` each schedule; `settle_hitl` each request. Accepted grant must finish outcome settlement before grant cleanup; pending requests may cancel.
3. `control_agent(stop)` each root/Leti and await Activity/Mirage/checkpoint cleanup. Explicitly archive child box/agent rows through existing save changes; retain box/home files rather than trashing root data.
4. `cleanup_leta_access` invokes `Workspace.CleanupLetaAccess` for this root's received scope editor/viewer grants after HITL settlement and stop. Normal archive preserves home/files/history, home_of and Leta tuples for creator read gated by current W membership; it never calls resource-tuple remove mode. No membership leave/removal or user deletion. Workspace owns direct admitted cleanup, without callback into locked WorkspaceChanges.
5. For [phase17](phase-17-workspace-resource-cleanup.md) explicitly admitted W teardown only, reuse `publish_leta_resource(mode=remove)` after producer/HITL/grant cleanup and before StopLetaForWorkspaceDeletion acknowledges. Remove only this root's Leta-owned tuples; no new Activity/Workflow/finalization RPC. Already ordinarily archived roots still perform this W cleanup mode rather than returning an archive-status shortcut. W storage deletion follows the stop acknowledgement.
6. `save_leta_change(archived)` closes lifecycle; publish its sparse root ref with publisher-only retry. Late message/schedule/HITL delivery skips without runtime restart. Redis notification failure never prevents the required stop/access-cleanup acknowledgement or turns archived work back into active.

Archive retains boxes/home/history for creator viewing while that human remains a workspace member; it does not run delete_box on every home. Foreign personal grant never gains home_of, so creator does not get direct raw access merely because Leta read it. An already-running identity-bound box deletion may settle without creating resources after the root gate closes. Workspace deletion instead stops all resources before filesystem teardown; enumeration uses root workspace_id, never members.

Trusted `StopLetaForWorkspaceDeletion` admission closes the root deleting gate in the existing domain transaction **before waiting for the serialized lifecycle Update**. The native handler calls the shared store/domain helper also used by Local save_leta_change; it does not execute a Temporal Local Activity from RPC. This makes an in-flight create's active/start compare-and-set lose even when its coordinator command lock is still held. Authority is exact Workspace credential, directly verified W deleting state and canonical W-root binding; no new state field, endpoint, Workflow or caller-selected bypass. Ordinary creator archive still performs its normal authorization before closing that gate.

## BoxLifecycleWorkflow commands

Stable Workflow ID `box-lifecycle/<box_id>`; serialized Update and Continue-As-New policy as above.

Create: `save_box_change(initializing graph)` under root/box gates → `ensure_box_home` through LetFS → `save_box_change(active)` → `start_agent` each Leti. Save whole graph/representative/IDs before filesystem/start calls. Bounded per-ID fan-out is in Workflow, so one failed target retries without repeating completed targets.

Home creation resolves/creates `.leti` parent with normal directory semantics, then creates the slug directory with **reserved boxes.home_node_id** and parent/name/kind preconditions. Retry beyond existing receipt expiry resolves the known ID and verifies original identity. A different node at that path conflicts. Root `.leti` must not be a symlink/alias that widens root policy. Avoid ad hoc path adoption/deletion.

Delete: `save_box_change(deleting + resource IDs)` → delete each schedule → settle each pending/accepted-in-progress HITL → stop all Leti and wait cleanup → `trash_box_home` → `save_box_change(archived)`. Trash is identity-bound and recoverable via ListTrash by known node ID; no purge. Grant already given to Leta is **not revoked** by box deletion. Never trash while an invocation can still write.

Visible committed box changes emit a sparse box ref through shared regular publish_resource_event, after Local SQL and independently of actual home/start/stop/trash effects. It cannot fabricate a domain transition or replay the side effects on Redis failure. Box activation/start also rechecks the existing root/box gate, so root deletion defeats delayed box-home acknowledgement.

Leti completion/final note does not delete it or its box. Agent/box/thread/home remain for future peer messages, schedule occurrences, or HITL outcomes until explicit delete_box/owner deletion. No automatic edge forwarding, recursive final-text dispatch, or cleanup-after-task policy.

## Races, failure handling, and security

- Use Temporal progress/retry and existing stable resource/command identities for ordinary command retries. No activity_log admission/completion stages, extra completion save, or guarantee of replaying historical control/config commands indefinitely after Workflow rotation.

- Every create/send/request/schedule path checks parent gate in its transaction. Deletion snapshot cannot miss a resource that commits afterward. No remote RPC is held inside a SQL lock.
- Before external mutation, bridge uses stable persisted command key. Retry same name with changed graph does not silently create another box.
- Workspace/LetFS authenticate service caller and closed user/leta subject from the credential boundary; model-supplied IDs are not authority. Creator must be active for normal API commands; admitted W teardown is trusted internal authority. Resource approver cannot inspect/manage Leta engine.
- Control response means runtime reached requested state, not merely update admission, when lifecycle relies on stopping resources. Use heartbeat and bounded retries; do not launch a second runtime because the first is slow.
- Stop failure leaves deleting state and retained home; it never reports archived while code is still using the filesystem. Failed trash likewise remains deleting and retryable with the same home identity.

## Implementation checklist and tests

- [x] 1. Implement roster resolution and route matrix tests, including representative source/reply address and malformed in_reply_to.
- [x] 2. Implement owner-message SQL insertion and agent receive client path with persisted effect IDs; register one send_message and Leta-only list/read inbox tools.
- [x] 3. Reuse phase03 whole-graph validation, root gate, live uniqueness/slug collision, and idempotent graph save; phase03's real SQL regression continues to pass. Concrete box tools are implemented; native lifecycle acceptance remains under items4–6.
- [x] 4. Implement lifecycle with Leta-owned resource tuple publication plus real typed Workspace/LetFS clients; remove all account/member/leave/name-sync effects. Register no additional Workflow types.
- [x] 5. Wire real HITL/schedule cleanup and phase16 shared sparse publisher, including ordinary archive versus admitted W-teardown resource-tuple modes. Mark release incomplete until these integrations pass.
- [x] 6. Test create/delete retries after each cross-service step, including home receipt expiry, bounded Ensure wait behind W deletion and delayed create acknowledgement after trusted stop admission closes the shared gate. No producer may start after deleting wins.

```sh
uv run --locked --package leta pytest apps/leta/tests/test_messaging.py -q
uv run --locked --package leta pytest apps/leta/tests/test_lifecycle_integration.py -q
pnpm --filter @openlet/leta test:replay
pnpm --filter @openlet/leta check
```

| Scenario | Pass condition |
|---|---|
| Routing matrix | Only allowed routes accepted; representative result arrives as box with true sender audit; nonrepresentative cannot bypass. |
| Busy recipient/retry | Tool returns after one inbox commit while recipient remains busy; no duplicate send or owner bubble. |
| Create box only | Whole graph/home/runtimes ready, zero unsolicited work messages. |
| Long lifetime | Completed Leti receives later message under same ID/thread; final note does not delete/forward. |
| Resource provisioning crash | Independent root/home IDs unchanged after tuple/storage acknowledgement loss; one home/default-access mapping, zero user/member records. |
| Delete race | No child escapes snapshot; new input skips; stopped runtime cannot write trashed home. |
| Archive grants | Accepted grant settles first, then root received-grant cleanup; creator home read uses home_of→leta.read, with membership revocation effective. |
| Workspace deletion | Trusted cleanup bypasses already-held mutation queue; runtimes stop before storage teardown, no recursive-lock deadlock. |
| Create versus W deletion | Trusted stop closes local gate before waiting coordinator; delayed home ack cannot activate/start. Unapplied queued Ensure rejects actual W-deleting state; only owned tuples reconcile on terminal init failure. |
| Archive modes/publication | Normal archive keeps Leta tuples; admitted W teardown removes them before stop ack. Lost sparse notification retries no grant, provisioning, stop or trash effect. |
| Foreign personal scope | Approval grants Leta/Leti access without granting creator raw access or changing home_of. |
| Recreate name | After archived home trash, same names create fresh IDs, no old message/context resurrection. |

## Acceptance and rollback

Acceptance requires the accepted owner→Leta→box→Leti→representative→Leta→owner route, plus independent work while human answers are pending. No graph scheduler, send_box, per-Leti deletion, scope/account per Leti, or task engine appears.

Rollback pauses new commands and lets persisted coordinators finish with compatible Activity names/contracts. Preserve initializing/deleting rows and actual resource IDs for retry. This fresh development implementation has no backup prerequisite; tests own disposable state. Do not purge scopes/history, adopt arbitrary directories at reused names, or restore bot membership as a workaround. Current native and system evidence is recorded in the execution checkpoint; final acceptance is reconciled in phase19.
