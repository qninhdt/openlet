---
title: "Phase 16: Per-Leta Redis replay and AG-UI streaming"
status: completed
priority: P1
dependencies: [10, 11, 15]
---

# Phase 16: Per-Leta Redis replay and AG-UI streaming

## Outcome and dependencies

One authenticated SSE connection receives root Leta and all its Leti activity through one stable Redis Stream per Leta. Normal disconnect preserves client partial text; a valid Last-Event-ID resumes its suffix. Only unavailable replay requires an explicit durable-history reset. Follow the [accepted contract](design-contract.md), [typed history](phase-11-history-and-compaction.md) and [API contract](phase-15-owner-api-and-ui-contract.md).

Redis is required for startup/readiness and Mirage caching. It is temporary live/replay storage, not canonical product data. This phase adds no PostgreSQL discovery polling, per-run stream registry, second event bus, WebSocket requirement, distributed semaphore or 32-Leti product limit.

## Evidence and affected files

The lab `../agent-lab/labs/durable-chat/chat/streaming.py::{StreamPublisher,read_events,coalesce_events}` and `chat/api.py::events` demonstrate worker-to-Redis-to-API SSE. Their old open-block scans/writer fencing and run topology are not the product contract. [AG-UI event definitions](https://github.com/ag-ui-protocol/ag-ui/blob/main/docs/concepts/events.mdx) define public message/tool events; phase01 verifies pinned adapter compatibility.

| Action | File relative to repository root | Responsibility |
| --- | --- | --- |
| Create | apps/leta/src/leta/streaming.py | Shared publisher, bounded root log, cursor validation and compatible delta coalescing. |
| Create | apps/leta/src/leta/http/events.py | Authorized stable SSE reader/bootstrap/resume and cancellation. |
| Modify | apps/leta/src/leta/temporal/bridges.py | Regular publish_resource_event Activity wrapper calling the same publisher; no SQL Local Activity writes Redis. |
| Modify | apps/leta/src/leta/runtime/runner.py and phase11 publication boundary | Public model/tool deltas and committed typed activity references. Use actual owning phase10 module path if its final name differs. |
| Create | apps/leta/tests/test_streaming.py, apps/leta/tests/integration/test_streaming_integration.py | Ordering/coalescing, real Redis/PG replay and transport failure checks. |

Phase18 owns Redis image/configuration, Compose and gateway SSE wiring. Sparse postcommit events from phases09–14 use this publisher; implementing one publisher does not add a Workflow per event or Activity per token.

## Event contract

Stream key: `leta:stream:<leta-id>`. Root and children write to the same key, including new runs/boxes after a client connects. Mirage uses separate prefixes. Redis ordering is transport append order, not a global transaction sequence across agents.

```json
{
  "leta_id": "root-resource-uuid",
  "agent_id": "root-or-child-runtime-uuid",
  "run_id": "business-run-uuid-or-null",
  "event": {"type": "TEXT_MESSAGE_CONTENT", "messageId": "public-block-id", "delta": "text"}
}
```

The outer envelope carries routing. Preserve the standard AG-UI payload; do not combine different agents into one AG-UI run. UI maintains separate agent/run reducers. run_id is null for sparse domain changes not owned by a run. Use RUN_STARTED/FINISHED/ERROR, TEXT_MESSAGE_START/CONTENT/END and TOOL_CALL_START/ARGS/END. A runner yield/retry is not a false task completion. Assistant text is an intentional public note, not an owner-directed message.

CUSTOM events carry committed ActivityEntry or message/request/schedule/resource references. Typed inbox_input/compaction data comes from phase11, not parsing prompt text or replacing it with raw MESSAGES_SNAPSHOT. Stable entry/message/tool IDs deduplicate historical and live materialization. Hidden reasoning/provider-private content never enters this stream.

## Implementation steps

1. [x] Use a process-owned Redis client and shared publisher. Runner callbacks publish public deltas directly. Domain services/API publish sparse refs after successful SQL commit. Workflow paths call regular publish_resource_event after Local save; its exact arguments are (leta_id,kind,resource_id); the publisher derives the relevant agent_id and nullable run_id from canonical resource data, never private resource bodies in Workflow arguments. Publishing never owns the mutation.
2. [x] Append to the stable root key even without clients. Verify agent belongs to root before publication. Allocate public block identities consistently with checkpointed messages/tool_call_id; preserve boundary events and separate child state. Do not reset a valid client cursor merely because an Activity attempt changes. An abandoned block can be superseded by a typed durable entry/run status; never silently splice a restarted generation into an unrelated block.
3. [x] Publication uses one bounded append attempt and transport diagnostics. An unknown append outcome is never retried because it can duplicate provisional deltas. Failure cannot repeat a model/tool/domain action, stop required cleanup or invalidate a committed checkpoint. Dependency health becomes unready when Redis is unavailable; no optional/degraded startup or cache-bypass mode is added. After restoration, reconnect refreshes domain state from PG. No outbox or automatic repair replay of already committed effects.
4. [x] Bound the stream while active: initial 24-hour touch TTL, 8MiB payload and 20,000 events **per Leta**, across all runs/children. Use a small tested atomic append/accounting/trim operation; no lifetime prefix scan. Reset disposable accounting with a missing stream so eviction cannot create unbounded allocation. Redis server memory starts at 256MiB in phase18; cache and replay may be evicted and recovered according to their own contracts.
5. [x] Authorize GET /v1/letas/{id}/events through current creator workspace membership and leta.read before reading stream/history. Client cannot select another root through an agent/run ID. Native stream keys are never capabilities. Apply ordinary gateway/server connection bounds and bounded output buffers. Slow clients disconnect and resume; no Redis semaphore/custom global SSE quota.
6. [x] Distinguish a true resume from fresh bootstrap. A client with its corresponding retained UI state sends Last-Event-ID. If the cursor remains within the available root log, XREAD strictly after it and replay the suffix; keep partial text/tool arguments already on the client. Refresh sparse PG domain status on connection without clearing this valid text state. No reset due only to disconnect, worker attempt change or another child starting a run.
7. [x] For a fresh client without corresponding UI state, load bounded PG history/status plus available bounded live replay. Establish the replay boundary before snapshot; deduplicate committed blocks/entries by saved IDs. Replay only blocks with available START or fully materialized PG state; do not append an orphan CONTENT/ARGS suffix as a complete block. Replay can cover an available partial block; if its start/prefix was trimmed, show committed state and explicit resync limitation. Do not fetch lifetime history or scan all old checkpoints.
8. [x] A cursor older than the retained range, missing/expired/evicted stream or explicitly lost log emits CUSTOM resync_required with bounded history/status routes, then bootstraps committed PG state. Distinguish a new empty root stream from lost replay for a previously observed cursor. Never promise provisional tokens outside the available log. Ordinary HTTP history remains backed by PG; Redis remains a readiness requirement.
9. [x] Wait with XREAD BLOCK after catchup. A newly started child/run and an idle-root request timeout arrive on the same stream via normal publication; no two-second SQL refresh, separate subscription or stream discovery. A lost sparse notification is recovered on explicit refresh/reconnect; no polling or durable event repair service. Publish root/archive status before ordinary closure where available.
10. [x] Coalesce at the API **after Redis** only adjacent compatible TEXT_MESSAGE_CONTENT or TOOL_CALL_ARGS sharing root/agent/run/block identity. Flush at 25ms/16KiB initially and before every identity/start/end/custom/terminal boundary. Concatenate payload bytes in order. Set emitted SSE id to the last consumed Redis ID so reconnect never replays part of an already emitted merged frame. A standard SSE decoder commits cursor only with its complete frame.
11. [x] Keep SSE envelope and typed historical DTO aligned. Actual send_message creates the owner chat bubble from committed messages, while final_note/inbox_input/tool/compaction get their own components. Public projection identity prevents an owner message plus input reference from rendering twice. Cross-agent event interleaving never merges their text/tool reducers.
12. [x] Cancel XREAD tasks and close response buffers/readers on disconnect/shutdown. Heartbeats carry no fake domain event and do not advance data cursor. Set SSE headers/no buffering and gateway-compatible idle deadlines. Recheck current access on reconnect and at bounded live-connection authorization boundaries; do not retain access solely because a stream opened before membership removal.

## Verification and acceptance

Owning verification commands (executed; evidence linked below):

```sh
uv run --locked --package leta pytest apps/leta/tests/test_streaming.py -q
uv run --locked --package leta pytest apps/leta/tests/integration/test_streaming_integration.py -q
pnpm --filter @openlet/leta check
```

- [x] One SSE receives interleaved root/two-child events, new runs while idle, HITL timeout/decision/outcome, schedules, box deletion and lifecycle changes without polling.
- [x] Mid-text/tool-args disconnect plus valid cursor preserves prefix and exactly resumes suffix. Activity retry alone does not invalidate cursor or delete client text.
- [x] Coalesced output has identical bytes/identity/order and correct final Redis cursor; flushing custom/tool boundaries preserves presentation. Report original Redis events, SSE frames and bytes separately. No claim of fewer Redis writes or faster Temporal replay.
- [x] Fresh bootstrap deduplicates committed entries and handles available partial blocks; missing starts never become fabricated complete output.
- [x] Trim/TTL/eviction/lost stream produces explicit reset; committed PG history survives. Byte/event caps hold under a busy root with multiple children and no clients.
- [x] Redis outage fails readiness; publication failure does not replay business effects, prevent checkpointing or block deletion. Mirage failures retain phase08's explicit cache/error semantics.
- [x] Wrong creator/root/child/cursor cannot reveal another Leta. Membership removal cuts future authorized access.
- [x] Cancellation/slow clients release readers and buffers; test cleanup leaves no owned background tasks.

## Risks and rollback

An 8MiB root log may retain less history during high parallel activity; this affects temporary replay, not durable history. Coalescing reduces SSE frames, not Redis write volume. PG reset can omit uncommitted token prefixes after lost replay; the UI must say so. Native AG-UI adapter compatibility and bootstrap races need real tests.

Rollback stops SSE admission and preserves PG history/checkpoints. Disposable stream/cache state may be cleared with explicit cursor reset. Do not silently run the service without its required Redis dependency or delete durable records as stream cleanup.

## Execution checkpoint

Runtime callbacks, typed history/domain publication and the root SSE route are
implemented and reviewed. See [execution evidence](reports/phase-16-execution.md)
for native tests, reconnect/cleanup behavior and measured post-Redis coalescing.
Production process construction and gateway/Redis deployment remain phase18.
