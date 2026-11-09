---
title: "Phase 13: Asynchronous human requests and resource access"
status: pending
priority: P1
effort: 5d
dependencies: [4, 9, 10, 11, 12]
---

# Phase 13: Asynchronous human requests and resource access

## Outcome and dependencies

Leta/Leti can ask the Leta creator a structured multi-question form, or ask any active same-workspace human personal-resource owner for access **granted to root `leta:L`**. Tools return pending immediately and complete tool-call protocol. HumanRequestWorkflow waits separately and later delivers outcome to the exact requester inbox; neither that agent nor unrelated work waits for the human.

Depends on [Workspace resource API](phase-04-workspace-resource-access-and-scope-view.md) and engine/lifecycle phases09–12. [Phase03](phase-03-leta-domain-schema.md) owns hitl_requests schema; [phase09](phase-09-temporal-agent-inbox.md) owns four request Activities/shared bridges; [tool catalog](tool-contracts.md) owns arguments; phase15 owns HTTP/UI adapters. [Accepted design](../reports/design-261108-0148-leta-workspace-resource.md) controls resource identity and forms.

Forms, SQL transitions, finite HumanRequestWorkflow, delegated Workspace grants, exact-requester delivery/settlement and root/child tools are implemented. Real PostgreSQL/Temporal and Python→Go Workspace→SpiceDB tests cover worker SIGKILL, applied-grant acknowledgement loss, sparse publication and mutex-held workspace deletion. Compose also verifies restore of an accepted request whose grant dependency was unavailable. See the [final acceptance evidence](reports/acceptance.md); the [execution checkpoint](reports/phase-13-execution.md) preserves earlier increments.

## Existing contracts and file inventory

Current `apps/workspace/internal/workspace/relations.go::ChangeScopeAccess` checks scope manage_access, resolves a target through account summaries and forwards a Workspace mutation; that target assumption is removed by phase02/04. Phase04's proposed `ResolvePersonalScope(workspace_id,user_id,leta_id)` returns canonical human owner/scope and exact workspace-resource binding. `ChangeScopeAccess` accepts closed `user|leta` targets with the actual authenticated human approving and Leta grantee. Never infer ownership from manager tuples, read another service database or write foreign scope tuples directly from Leta.

| Action | Absolute path | Purpose |
|---|---|---|
| New proposed | `/home/qninh/projects/openlet/apps/leta/src/leta/temporal/human.py` | `HumanRequestWorkflow`, `open_hitl_request`, `resolve_hitl_request`, `grant_requested_access`, `save_hitl_outcome`. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/src/leta/runtime/human.py` | `ask_user`, `request_access`, `list_hitl`, `get_hitl`, `cancel_hitl`, canonical request resolver. |
| Modify earlier files | `/home/qninh/projects/openlet/apps/leta/src/leta/domain.py`, `/home/qninh/projects/openlet/apps/leta/src/leta/store.py` | Question/answer/decision/outcome variants and atomic transitions. |
| Modify earlier files | `/home/qninh/projects/openlet/apps/leta/src/leta/temporal/bridges.py`, `/home/qninh/projects/openlet/apps/leta/src/leta/worker.py`, `/home/qninh/projects/openlet/apps/leta/src/leta/runtime/tools.py` | settle_hitl, registration, capability roster. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/tests/test_human_requests.py` | Typed forms, decision transitions, nonblocking Workflow tests. |
| New proposed | `/home/qninh/projects/openlet/apps/leta/tests/test_human_requests_integration.py` | Real SQL deadline races, Workspace/SpiceDB grant, restart/archive. |

## Domain: two kinds, exactly four statuses

```text
pending -> resolved | cancelled | expired
```

The terminal status is shared. decision/outcome differ by kind. `resolved` plus accept and outcome=null means grant still running; no granting/failed fifth HITL status. UI shows accepted decision separately from actual access outcome. A permanent grant failure is a saved outcome, not rewritten deny/cancel or successful grant.

Request IDs and outcome_message_id derive from the persisted tool-call identity. Reserve approval grant_key UUIDv7 before remote mutation. Duplicate open uses the same ID and compares immutable normalized payload; changed questions/resource/role/deadline conflicts. Optional timeout is normalized **once** by open_hitl_request using server clock; retry never extends an existing deadline.

### Ask contract

`ask_user(title,questions[],timeout_seconds?)` always addresses verified `root.created_by_user_id`, for root and Leti alike, with current workspace membership required for human visibility/response. It may mix these variants:

| Question | Definition | Submitted answer |
|---|---|---|
| single_choice | id,text,nonempty options[{id,label}] | `{option_id:null\|known_id,note:string}` |
| multiple_choice | id,text,nonempty options[{id,label}] | `{option_ids:[known_id...],note:string}` |
| text | id,text; no options | `{text:string}` only |

Question IDs unique per form, option IDs unique per question. Validate answers map **every** question ID exactly once, no unknown IDs/fields, no duplicate multiple choices. Empty single selection, empty multiple selection, and empty note are valid. Omitted note normalizes to empty string; empty text is an intentional submitted answer unless an explicitly accepted product rule changes it. There is **no Other option**, generated Other sentinel, or freeform answer field on a choice beyond note. Text has no note/selection fields.

Submission is one resolved form, distinct from leaving it pending. Card identifies actual requester and box; a Leti asking owner gains no send_message(owner) route. No Python stack, unresolved ToolMessage, graph HITL interrupt, or wait_for_human Activity remains suspended for this form.

### Resource approval contract

`request_access(resource={type:'personal_scope',user_id},role='viewer'|'editor' default viewer,reason,timeout_seconds?)`:

1. Runtime injects root/workspace/principal; model cannot choose grantee, approver, raw scope ID, actor, or approved=true.
2. Through Workspace ResolvePersonalScope under trusted `leta:L`, resolve **any active human** in the same W, canonical personal scope/owner, and eligible root resource binding. It need not be the creator. Reject other W, inactive human, shared/Leta-home target or missing mapping. Leta itself is not validated as a workspace member; it has no membership.
3. Verify current effective access. If requested access is already sufficient, return already_granted plus current mount without creating another pending request. Do not infer this from old resolved request rows.
4. Otherwise open approval with actual requester agent ID, grantee **root leta_id even for Leti**, canonical scope, approver_user_id, requested role/reason and stable grant key. IDs are injected by server context, not model authority.

Resource owner's card states that acceptance grants Leta and inheriting Leti access, not only the requesting Leti. Only the verified addressed resource owner may accept/deny. Leta owner may manage/cancel pending owned requests but cannot approve another human's scope merely by owning Leta. Scope manager/admin is not substituted for resource owner.

Accept grants access only; no held filesystem/tool action executes automatically. Result enters requester inbox and the agent chooses its next read/search/write. Timeout bounds answer deadline, not grant lifetime. Access persists until explicitly revoked; delete_box/cancel request does not revoke a completed grant. Revocation blocks new access through backend checks but cannot erase already read context/transcript/results.

## Workflow and Activity execution

Use stable Workflow ID `human-request/<request_id>`, one execution per request. Update-with-Start opens request; open Update returns saved pending record immediately after Local SQL commit. The main Workflow waits on a condition and durable deadline timer with no polling Activity or reserved thread.

| Path | Exact sequence |
|---|---|
| Open | open_hitl_request L -> return pending to tool; Workflow awaits response/timeout. |
| Ask answer | resolve_hitl_request L -> deliver_agent_input R to requester. |
| Approval accept | resolve_hitl_request L -> grant_requested_access R -> save_hitl_outcome L -> deliver_agent_input R. |
| Approval deny/cancel/expire | resolve_hitl_request L (includes non-grant outcome) -> deliver_agent_input R. |

After open/decision/outcome SQL commits, the main Workflow invokes shared regular `publish_resource_event(root.leta_id,kind='hitl',resource_id=request_id)` to notify the phase16 stable root stream. In particular, timer expiry and cancellation must reach this boundary even when no agent run is active. It is outside the short transition lock and open/decision receipt: tools/human response still acknowledge committed pending/decision state without waiting for Redis. The regular publisher reads authoritative resource projection/ref; Local open/resolve/save-outcome Activities perform no Redis I/O.

The publisher has independent bounded timeout/retry; exhaustion logs explicit transport failure and continues grant/outcome/delivery/settlement, never repeats an accepted grant or blocks deletion. A saved grant outcome and requester input remain authoritative even if the sparse event is lost. Reconnect refreshes canonical request snapshots; no outbox, timer poller or token Activity is added. Runtime/API callers outside Workflow use the same ordinary publisher directly.

Use async Update handlers with one short request transition lock, not a lock held while waiting for humans or granting. If the human response endpoint awaits outcome, it may await Workflow grant progress without blocking unrelated request handlers/AgentWorkflows. Prefer returning committed decision with explicit pending actual outcome; phase15 displays actual progress honestly.

### Deadline and competing responses in PostgreSQL

resolve_hitl_request performs the definitive decision transaction:

1. Lock hitl_requests row FOR UPDATE. Check authenticated responder against persisted addressed approver/owner management rule; source payload cannot supply actor.
2. If the exact same actor+normalized decision was already committed, return the recorded decision/outcome as idempotent retry, even after deadline. Changed decision on terminal row conflicts with current status; cancel never changes resolved accept.
3. For a new response, read **clock_timestamp() after the row lock**, not browser time, Workflow replay time, or PostgreSQL transaction-start now(). If expires_at is reached, conditionally commit expired instead; reject the late answer with current state.
4. For timer expiry require status=pending AND expires_at<=clock_timestamp(); otherwise return current state. Early timer/retry does not expire an unexpired request.
5. Save answers/accept/deny/cancel/expired and resolved_at. For non-grant terminal cases save outcome in this same transaction. Commit before returning or invoking grant.

Concurrent answer vs timeout/cancel has one winner under SQL lock and actual deadline. A response before the worker processes the timer still loses if its transaction reaches the deadline first; a delayed timer cannot overwrite an already committed valid answer. Request transaction also checks root/box lifecycle gates for new admission; terminal cleanup for an already stored request remains allowed while parent deletes.

### Approval grant and recovery

grant_requested_access is regular because it calls Workspace. Re-resolve exact personal-resource/human owner/current W and root lifecycle binding and requested viewer/editor. Invoke Workspace ChangeScopeAccess using the **recorded authenticated human approver** as delegated `user` actor, grantee kind=`leta`, ID=root.leta_id, and persisted grant_key. Phase04 validates service/method allowlist, delegation and exact resource mapping at its own boundary. No direct tuple write, self-approved boolean, Leti grantee, creator substitution or bot-membership validation.

Transient dependencies retry this Activity with the same key/resource/grantee/role, using the existing Workspace idempotency_keys behavior and retention. A completed request returns its saved decision/outcome rather than opening a new grant request. Current access is rechecked; do not infer present rights from an old acceptance. No permanent-receipt extension or unlimited delayed-command replay guarantee is introduced.

save_hitl_outcome persists actual success/permanent failure without changing resolved decision. Outcome includes request_id, decision, granted bool when approval, role, canonical scope/mount path if granted, and sanitized error/reason if failed. Retried save compares existing outcome. A grant success describes the acknowledged operation/current check; runtime still reauthorizes every filesystem operation and never treats this row as a grant cache.

Delivery envelope has stable outcome_message_id, source identifying request, nullable reply_to, and data with request_id/kind/status/answers or decision/grant outcome. Ask delivers to **the exact requesting Leti/Leta**, not root by default. If requester/root/box deleted, deliver_agent_input returns skipped and Workflow ends; no resurrection. Lost completion retries same message ID and cannot duplicate input.

## Lifecycle settlement ordering

settle_hitl(request_id,reason) is the shared regular bridge, not a new Workflow:

- Pending: request cancellation through HumanRequestWorkflow, commit cancelled outcome, and await delivery or skipped.
- Resolved accept with incomplete grant/outcome: wait for grant/permanent failure + saved outcome + delivery/skipped; do not turn accepted into cancelled.
- Terminal settled request: return existing outcome.

Leta archive closes admission first, deletes schedules, settles **accepted grants before** `cleanup_leta_access`, stops runtimes, then removes received root scope grants through Workspace. No membership leave/removal occurs. A newly attempted grant against a deleting root/W fails current lifecycle validation; save that real permanent outcome and settle. Already applied grant must finish saved outcome/delivery-or-skip before cleanup.

Workspace deletion has an additional queue boundary: existing WorkspaceChanges holds its mutation mutex while waiting DeleteWorkspace. Phase04/17 must bound grant RPC waits, recover an already retained downstream result/current grant when an earlier apply acknowledged uncertainly, revalidate deleting state on retry, and reject queued grants again at their actual mutation boundary. A timeout alone is not proof of failure. Already-applied grant saves its actual outcome; a still-unapplied command rejected by W/root deletion saves that real lifecycle rejection instead of waiting forever on the queue held by deletion. Late queued retries must reject before cleanup safety is declared. `CleanupLetaAccess` for already-admitted trusted deletion takes the direct native cleanup route, never the locked mutation queue. No lease, grant journal or reconciliation poller is introduced.

Box deletion settles its own requests and stops Leti before home trash, but never revokes a grant already given to Leta. Late ask answer after cancellation conflicts; late duplicate grant result cannot reopen request or box. No general grant-revocation-on-request-expiry job.

## Read/manage authorization

list_hitl defaults to current agent; Leta may select its own box, Leti only self. get/cancel use the same namespace bounds. Creator API requires current `leta.read/manage` and may inspect its requests. Addressed human resource owner can list/get/respond **only its addressed request projection**, with current same-W membership; this does not expose Leta prompt/history/other requests. Filter on verified user/root IDs, never UI role.

Cancellation applies only pending; requester/owning manager may cancel within its allowed namespace. Human response endpoint accepts AskAnswers or approval action=accept/deny by kind. No agent tool can impersonate human response. All public/body/UUID/size/question validation happens at ingress and again at domain boundary where callers differ.

## Implementation checklist and verification

- [x] 1. Write pure mixed-form/answer tests, including empty selections+notes, text-only fields, duplicate/unknown IDs, no Other, and incomplete answer maps.
- [x] 2. Implement open/resolve/outcome SQL methods with immutable identity and clock_timestamp-after-lock deadline semantics.
- [x] 3. Implement HumanRequestWorkflow handlers/timer and regular grant/delivery bridges; test no Activity remains waiting for human.
- [x] 4. Implement resource resolution/current-access fast path and real delegated Workspace grant, never scope lookup through cross-service SQL.
- [x] 5. Wire lifecycle settlement/snapshots, including admitted Workspace deletion and grant queue timeouts; verify late queued grants reject before resource cleanup can be considered safe. Add post-commit shared sparse publication for pending/decision/outcome and timer/cancel paths, independent of grant/delivery retry. Update roster/card DTOs.
- [x] 6. Inject crash after decision, after Workspace grant/lost acknowledgement, after outcome save, and after inbox commit; recover same request/key/message.

```sh
uv run --locked --package leta pytest apps/leta/tests/test_human_requests.py -q
uv run --locked --package leta pytest apps/leta/tests/test_human_requests_integration.py -q
pnpm --filter @openlet/leta test:replay
pnpm --filter @openlet/leta check
```

| Test | Required result |
|---|---|
| Mixed form | Single/multiple/text coexist; blank choices+note accepted; malformed/Other/text-extra-fields rejected. |
| Nonblocking work | Leti asks owner and finishes tool; same agent later consumes another input, root handles schedule independently. |
| Correct approver/grantee | Another active human U sees approval, O cannot answer for U, Leti requester still grants root L; outside/inactive user fails. |
| Deadline race | Clock controlled by actual test deadline/locked transaction; only valid first terminal decision wins, timer cannot overwrite. |
| Accepted crash/retry | One acknowledged grant under same key; outcome not sent granted=true before real grant; no duplicate request/outcome message. |
| Revoke and current access | Runtime checks reflect current permissions; already completed requests return saved outcomes without creating a new request. No indefinite old-command replay guarantee. |
| Archive race | Accepted grant settles before received-scope cleanup; retained home/history uses creator current membership through resource policy. |
| Workspace deleting during grant | Grant queued behind delete cannot deadlock teardown or apply afterward; timeout is reconciled with real lifecycle/current authorization, cleanup avoids locked mutation queue. |
| Creator versus resource owner | Human U approves its scope to `leta:L`; no home_of or viewer grant gives creator O direct raw access to U's scope. |
| Requester deleted | Terminal outcome persists; delivery skipped without recreating agent/box. |
| Timeout with idle root / Redis outage | Connected stream receives sparse request ref after committed expiry without PG polling when Redis works; publication failure retries no grant/outcome input and cannot block settlement. Reconnect refreshes saved state. |

Use real Workspace SQL/SpiceDB/Python→Go transport for permission tests; mocking only the client would hide the actor allowlist and actual grant semantics. SDK time-skipping is for deterministic Workflow timers, not proof of PostgreSQL deadline arbitration.

## Acceptance, risks, rollback

Acceptance is the full accepted route: owner sends work → Leta messages box → Leti asks owner → Leta handles another schedule → owner answers → exact Leti resumes by inbox → representative messages Leta → Leta sends owner. Resource approval additionally proves U's scope grants to L under U authority with no tool replay.

Mandatory integration gates cover wrong-human approval, Leti grantee substitution, accepted grant versus cleanup and the Workspace deletion lock boundary. Rollback stops new requests while compatible saved Workflows settle; preserve decisions/outcomes and existing Workspace idempotency records. There is no backup prerequisite for this fresh development implementation. Never revert accepted to cancelled or remove grants as automatic rollback. Final system acceptance is tracked in phase19.
