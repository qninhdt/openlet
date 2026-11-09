# Phase 12 execution checkpoint

Historical increment: the open gates below were subsequently exercised. See [final integrated acceptance](acceptance.md) for current phase reconciliation and fixture boundaries.

Status: messaging/inbox and lifecycle/box-tool cores are implemented. Native cross-service lifecycle acceptance and later-phase cleanup/publication integrations remain open. Overall goal is active and no approval is pending. Scoped reviews found three concrete recovery/admission defects; fixes and verification are recorded below. Do not mark the whole phase complete.

## Implemented

- One `send_message(to, content, in_reply_to?)` tool with runtime-injected context/call identity. Arguments cannot choose an actor or source. A stable message UUID derives from the checkpointed assistant/tool-call IDs, using the existing effect identity helper.
- `runtime/messaging.py` owns the same roster used by get_workspace and actual delivery. IDs and exact roster names are accepted; unknown/ambiguous names fail. Root sends only to its creator or an active box. Leti peers require a same-box edge. Only the representative has the parent route, addressed by its box ID or the roster's parent alias. A one-Leti box uses the same path.
- Root→box inputs carry a reply address using that box ID. Representative→root inputs have box source/reply identity and retain sender_agent_id for the actual Leti. SQL reply validation resolves the box address in the appropriate direction, while still checking original recipient/current allowed route and root namespace.
- Agent recipients use the existing Temporal Update-with-Start bridge and commit the canonical inbox row before acknowledgement. Creator recipients use the same messages table with recipient_user_id and no inbox sequence. No second inbox/chat copy, send_box tool, edge executor or automatic forwarding exists.
- Permanent inbox admission failures cross Temporal as ordinary AppError values, so the tool wrapper can save a useful error ToolMessage. Transient infrastructure failures keep ordinary retry behavior.
- Leta-only list_inbox/read_inbox expose grouped source metadata/counts/preview/reply address and bounded detail pages. Leti has no inbox tools. Source categories remain generic. Missing grouping keys normalize to the source type/ID pair; this is an ordinary grouping string, without a new conversation record.
- Pagination lookahead does not mark an extra row read. During agent execution, read markers commit atomically with the existing saved tool result. A crash before that commit leaves input unread; a crash after it reuses the saved exact result. There is no extra receipt, command journal or processed/closed state.
- Shared projection `InboxItem.from_row` supplies the same typed details to runtime input and explicit reads. The pinned tool factory drops Pydantic field aliases in its subset schema, so list_inbox uses the supported JSON-schema form and explicitly validates with InboxQuery. Its public argument remains `from`, not Python's `from_`.

## Lifecycle and canvas increment

- Added exactly the planned LetaLifecycleWorkflow and BoxLifecycleWorkflow, with serialized Updates, bounded per-agent fan-out, handler draining and history-triggered Continue-As-New. Terminal archive ends its coordinator. Creation starts independent top-level AgentWorkflows, without inserting work or invoking a model.
- Local save_leta_change/save_box_change reuse canonical SQL for root create/config/pause/activation/deletion/archive and immutable graphs. Root profile/config updates preserve context; child profile/prompt stays immutable, while model/reasoning overrides remain supported.
- Regular Activities use typed Workspace/LetFS clients for stable home provisioning and identity-bound box directory creation/trash, plus exactly the two Leta-owned resource relationships. Ordinary archive retains home, files, history and resource tuples; it removes received scope grants through Workspace using the persisted creator actor.
- Home creation uses reserved IDs and verifies directory/parent/name on retry. A lost trash acknowledgement is recovered by the known node ID in native trash. Late box-home acknowledgement cannot reactivate a root whose deletion gate already closed.
- A permanent home rejection confirmed by the native W-deleting status path closes the initializing root, removes only its Leta-owned tuples and retains an archived tombstone. It neither starts a producer nor compensates by deleting real storage.
- Added root-only create_box/list_boxes/get_box/delete_box. Creation uses the persisted assistant/tool identity for box/home/Leti IDs, inherits model configuration and leaves delivery to send_message. Inspection exposes graph/prompts, derived home, counts and persisted run/request/schedule summaries. Archived records remain readable by ID; live names resolve within their root.
- AgentConfiguration now serializes only explicitly supplied patch fields. Real Temporal JSON transport exposed that omitted profile values otherwise became explicit nulls; the supported Pydantic serializer preserves omission/null semantics.
- Workflow registration accepts concrete lifecycle dependencies; runtime-only tests do not advertise unimplemented lifecycle handlers. Production process wiring remains phase18.

## Scoped review and fixes

The messaging reviewer identified a committed send being reported as failure after a root rename or target box archive. send_message now validates/reuses its existing immutable message before rebuilding current admission metadata. The regression checks unchanged message count and rejects changed payload/recipient.

The lifecycle reviewer identified that actorless Workspace cleanup is reserved for W teardown; ordinary archive now supplies the persisted creator Actor. The focused test asserts this native call contract explicitly.

The reviewer also identified delete-by-name recovery after name reuse. A new regression first failed by archiving the replacement box. The fix binds the resolved box ID in the existing pre-effect TOOL_CALL arguments and reuses that row on retry through supported ToolCallRequest.override. No new table, receipt, command stage or lease was added. Already archived IDs return their real archived state without restarting deletion.

## Verification to date

- Initial route/runtime/inbox suite after Temporal error translation: **16 passed** with real owned PostgreSQL/Temporal dependencies. Includes busy recipient delivery, representative/peer/single-agent routes, disallowed targets, saved-message retry and existing inbox worker-loss recovery.
- Existing store/compaction regression plus messaging: **32 passed**, with one new test failing on the pinned tool schema's alias behavior. The public schema was corrected using the supported JSON-schema input; no library patch/fork was added.
- A new read-marker crash regression first failed before the fix: the tool had marked a message read before saving its result. After moving those writes into the same existing SQL transaction, the focused group/marker suite is **3 passed**, including before/after commit failures and exact saved-result reuse.
- Full Leta suite: `PATH=/usr/local/go/bin:$PATH uv run --locked --package leta pytest apps/leta/tests -q --tb=short -rs`: **152 passed, 3 skipped** in 234.32s. The three skipped tests are `integration/test_mirage_cache_permissions.py`, `integration/test_mirage_letfs.py` and `test_filesystem_tools.py`; they require the fixture supplied by `TestIntegrationMirageLetFS` with `OPENLET_MIRAGE_INTEGRATION=1`. This plain pytest invocation does not configure that fixture. The owning native Mirage gate passed earlier in phase08; it was not rerun for this messaging increment.
- `pnpm --filter @openlet/leta check`: passed, 52 files formatted. `git diff --check`: passed.
- Final focused SQL checks after normalizing reply comparisons: **3 passed** (`test_store_integration.py -k 'reply_requires or saved_inbox_read'`). Both explicit and omitted grouping keys retain reply validation. Supplying foreign inbox IDs rolls back the entire marker/result/sequence transaction, and Leti cannot use the root read-marker path.
- The pinned `convert_to_openai_tool` output was inspected directly: send_message/read_inbox retain their actual function names, runtime remains hidden, and list_inbox exposes the public `from` field under its actual tool name. No paid provider request was made.

## Remaining phase work

1. Complete native lifecycle execution against actual Workspace/LetFS/SpiceDB, including provisioning acknowledgement loss/receipt expiry and deletion races. The current lifecycle tests use real owned PostgreSQL/Temporal and the real LangGraph saver, with explicit external-service fakes; they do not prove those remote service contracts at runtime.
2. Integrate phase13/14 request/schedule settlement and phase16 sparse resource/message publication before deletion/release acceptance. The coordinators name the planned settlement Activities; those Activities are not yet registered/implemented. Do not admit this as a completed HITL/scheduler deletion path or add fake cleanup.
3. Phase17 must implement trusted W-teardown admission, early local delete gate, actorless cleanup and resource-tuple removal ordering, including already archived roots. Ordinary archive is implemented; the W-stop RPC remains pending.
4. Continue the owning HITL/schedule phases, then native cross-service cleanup/deployment and the phase19 system journey. Preserve all earlier remaining phase09/10/12 release gates.

### Lifecycle verification

- Root profile prerequisites: **36 passed** in domain/runtime tests before lifecycle integration.
- Initial seven lifecycle checks: **7 passed**, including root create/config/pause/archive, repeat box create/known-ID trash recovery, wrong-home identity rejection, root delete versus late home acknowledgement, busy-runtime cleanup before trash, paused-root child creation, and actual Temporal rotation/replay of root/box histories.
- Checkpointed create/get/delete box tool path: **1 passed** after correcting two test-fixture issues (a helper argument-name collision and repeated provider tool-call IDs). No product validation was weakened.
- Full service before the final review fixes: **171 passed, 3 skipped** in 268.00s. The same three native Mirage fixtures are skipped as above. This run includes terminal W-deleting initialization cleanup and committed-send metadata recovery.
- Delete-name recovery regression before its fix: **1 failed, 9 passed**; failure proved the replacement was incorrectly archived. After the fix, the full lifecycle suite is **10 passed** in 34.16s, including exact creator delegation and replacement preservation.

No commit, push, deployment, production migration or paid inference was performed.

## Final verification for this increment

- Full post-review service regression: `PATH=/usr/local/go/bin:$PATH uv run --locked --package leta pytest apps/leta/tests -q --tb=short -rs`: **172 passed, 3 skipped** in 272.10s. The three skips are exactly the owning native Mirage fixture tests listed above; the native gate was not rerun here.
- `pnpm --filter @openlet/leta check`: passed, 58 files formatted. `git diff --check`, plan validation/link checks and journal validation passed.
- Actual pinned `convert_to_openai_tool` schema inspection confirms create_box exposes only name/description/letis/edges/representative, each Leti has only name/description/system_prompt, delete_box accepts box, and runtime identity stays hidden. An initial standalone inspection used an incomplete filesystem fixture; correcting the fixture's session field allowed the actual schema check to run, without product changes.
- Scoped reviewer completed with the concrete findings recorded above; all were fixed with regression coverage. A separate independent re-review of the final fixes was not performed.
- Continuation: lifecycle core is available for phase13, but leave phase12's native/release checkboxes open. Implement the real HumanRequestWorkflow and settlement bridge next, then schedules/publication/W teardown and their native gates. Do not treat the named but unregistered settlement Activities as completed behavior.

### Phase13 integration update

HumanRequestWorkflow, real delegated grant and shared settle_hitl/deliver_agent_input Activities now exist and register when concrete HumanActivities are supplied. Root/box lifecycle calls pass typed Leta/request identity. Native grant/revoke/lost-ack recovery passed through Python→Go Workspace→SpiceDB with race detection, and final Leta regression passed 240 tests with five fixture skips. Schedule source settlement, sparse publication, actual WorkspaceChanges lock teardown and full native home lifecycle remain with their owning phases; the HITL fixture does not prove them. See [phase13 checkpoint](phase-13-execution.md).

### Phase14 integration update

Both native scheduler Workflow types and their concrete Activities now register. Lifecycle schedule settlement uses typed ScheduleChange commands including root/requester identity. A focused real PostgreSQL/Temporal test creates a box, an actual native Schedule and a pending HumanRequestWorkflow, then deletes the box: schedule source is removed, request cancelled, agents stopped and home trashed before archive. The external Workspace/LetFS/SpiceDB lifecycle collaborators in this test are the existing explicit fakes; it does not close the native home or WorkspaceChanges deletion-lock gate. See [phase14 checkpoint](phase-14-execution.md).
