# Phase 13 execution checkpoint

Historical increment: the open gates below were subsequently exercised. See [final integrated acceptance](acceptance.md) for current phase reconciliation and fixture boundaries.

Status: structured forms, SQL transitions, finite request Workflow, resource grants, inbox delivery/settlement and agent tools are implemented. Actual Python→Go Workspace→SpiceDB grant/revoke/lost-ack tests pass. Phase13 is not complete: sparse publication and the real WorkspaceChanges deletion-lock integration remain open. The overall goal is active; no approval is pending.

## Implemented

- `leta/human.py` defines mixed single_choice/multiple_choice/text forms, exact question/option IDs, blank selections plus notes, and text-only answers. No Other or human-impersonation tool exists. Canonical personal-resource input validates the actual scope and addressed human owner.
- Store request creation serializes briefly on the existing root row, preserves the original SQL-clock timeout, validates immutable retries before active admission, and allocates one UUIDv7 grant key at first approval insertion. Omitting the key on retry reuses the saved key. No table/migration/ledger was added.
- Request decisions use the row lock and clock_timestamp after acquiring it. The addressed human alone answers/accepts/denies; requester/root/creator may cancel pending requests. Exactly four statuses remain. An accepted decision has outcome=null until actual grant success/permanent failure is saved.
- `temporal/human.py::HumanRequestWorkflow` uses Update-with-Start for opening, separate decision Updates and a durable deadline. Open and decision acknowledge SQL commit independently of grant/delivery. A short transition lock never spans human waiting or remote grant. The main run saves the grant outcome and delivers the exact requester's stable message ID. Pending requests hold no Activity/worker slot.
- `temporal/human_activities.py` supplies Local open/resolve/save-outcome and regular Workspace grant, receiver delivery and settlement. Grant delegates the recorded resource owner to Workspace, grantee=root Leta even for a Leti requester. Already-sufficient rights are read from current Workspace discovery, not old requests. On an interrupted acknowledgement, the same approved command reaches Workspace's existing key/current-rights recovery before lifecycle rejection; no foreign SQL or direct scope tuple writes occur in runtime.
- Inbox outcomes have generic source `hitl`, a typed data payload and no chat reply address. Inactive/deleted targets return skipped without resurrection. Accepted settlement waits for real grant/outcome/delivery-or-skip; pending settlement cancels. Lifecycle callers now pass the scoped typed settlement input.
- `runtime/human.py` and `runtime/tools.py` expose ask_user, request_access, list_hitl, get_hitl and cancel_hitl to root/children. Leti sees only self; root may select an owned box. Approval resource/actor/grantee/key injection remains outside model input. The actual pinned OpenAI conversion preserves mixed question types and hides these internal identities.
- `worker.py` registers HumanRequestWorkflow and its actual Activities only when concrete HumanActivities are supplied. Production dependency wiring remains phase18. No fake grants, publication or cleanup were inserted.

## Verification

Earlier SQL/form increments: 21 pure forms; final pre-Workflow request/store slice 47 passed, including actual post-lock deadline and malformed-form rejection. These are historical scopes, not totals to sum.

Current increments:

- Initial real PostgreSQL/Temporal request Workflow suite: **4 passed**, then **5 passed** with actual LangGraph ask tool checkpoint recovery and independent second business run while the request remains pending.
- Decision/outcome/inbox completion-loss regression: **1 passed**. Each boundary commits then throws once; Temporal retries it, with one saved request, one actual grant invocation and one inbox sequence.
- Actual owned Worker SIGKILL after SQL decision commit and before a Local Activity marker: **1 passed** in 16.94s against persistent Temporal. The replacement Worker recovered the committed answer and delivered exactly one inbox item. This is separate from completion-loss exceptions.
- Request management namespace and actual OpenAI schema: **2 passed**. Existing form/request/store/messaging regression: **56 passed** before the final canonical personal-resource admission strengthening.
- Captured human-answer/cancel/expiry/approval histories and existing Agent histories: **8 replay tests passed**. Fixtures contain completed real Temporal histories; effects are not executed during replay.
- Native Go Workspace fixture ran actual Python client/Activities/Workflow with real SQL/SpiceDB: **2 Python tests passed**. It verifies another resource owner, root grantee, forged creator rejection at Go ingress, creator without raw scope access, current-access fast path, revoke, actual applied grant with lost acknowledgement followed by W/root deletion, same grant key recovery and fresh unreadable-scope grant rejection. Binding/LetFS metadata are fixture implementations; this does not claim full native lifecycle provisioning or the locked WorkspaceChanges queue.
- The native `-race` run found an actual fixture race between GetBinding and test status writes. `nativeBindings` now guards reads/status changes with an RWMutex. Rerun: **Go native gate passed with -race**, 25.327s, including both Python tests.
- Final lint/format passed for 71 files, including the new SIGKILL fixture and schedule validation. No check was disabled.

The first full post-HITL run finished **234 passed, 1 failed, 5 skipped** in 329.84s. The image replay fixture used a 10k-token model; adding HITL tools increased the conservative schema estimate from 3623 to 5799, leaving insufficient room for its 4096-token image allowance. The production guard correctly rejected it. The image-recovery test now exposes only the actual read_file tool, keeping all path/checkpoint/public-reference assertions; its focused rerun passed in 5.22s. Production limits/guards were unchanged. The final full run, including SIGKILL and schedule overflow cases, finished **240 passed, 5 skipped** in **333.29s**. Two skips are the native HITL tests which passed separately under the Go `-race` gate. The other three require the native Mirage fixture and were not rerun here; their owning phase08 gate passed earlier. No failure remains in this full run.

## Review

The earlier scoped reviewer found malformed ask persistence; admission validation fixed it. A new independent scoped review found completed settle retries lacked the root namespace check. Completed settlement now compares the saved result's Leta ID; the regression rejects a foreign root. No additional concrete finding was reported in that review. The final scoped rereview covered native deletion recovery and canonical approval admission and reported no further concrete defect; it did not rerun tests. The locked mutation queue/publication remain explicit open gates.

The ak-cook live-diff threshold triggered a bounded simplifier. It changed only bridges.py's duplicate nested Update failure translation, preserving existing fallback/NOT_FOUND mappings and retry behavior. Its Ruff and 24-case behavior self-check passed. Other assigned files ran clean. The whole-service regression currently includes this simplification.

## Continue here

1. Continue phase14 native engine implementation from its checkpoint. Final full service regression is clean (240 passed/5 fixture skips), the independent scoped rereview is done, and no test process or approval remains pending.
2. Finish phase13's lifecycle/WorkspaceChanges lock test and phase16 sparse resource publisher at their actual owning integrations. The native fixture uses direct Workspace mutation and cannot prove locked coordinator teardown. Phase15 owns authenticated human response/list projections and membership admission.
3. Continue phase14: `schedules.py` and `test_schedules.py` now implement/test pure at/relative/anchored interval/calendar validation and native ScheduleSpec compilation. **28 tests passed**; no native Schedule CRUD/delivery/preview has been implemented by that increment. See the phase14 checkpoint.
4. Preserve phase09/10/12 native/release gates from their reports. Do not mark phase13 or the overall goal complete until required remaining integrations actually pass.

No commit, push, deployment, production migration or paid inference occurred. Owned test processes/containers clean themselves up; reconcile active processes before stopping.

## Reproduction commands

```sh
PATH=/usr/local/go/bin:$PATH uv run --locked --package leta pytest apps/leta/tests -q --tb=short -rs
cd apps/workspace
OPENLET_LETA_HITL_INTEGRATION=1 PATH=/usr/local/go/bin:$PATH go test -race -tags=integration ./internal/transport/grpc -run '^TestIntegrationWorkspaceNativeReadsGrantsAndCleanup$' -count=1
```

No owned background test process or container remains. Unrelated durable-chat containers were left alone. AgentWiki publication was skipped; only the local execution record/journal was written.
