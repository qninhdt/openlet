---
title: "Phase 03: Leta resource and agent runtime schema"
status: complete
priority: P1
effort: 3d
dependencies: [1, 2]
---

# Phase 03: Leta resource and agent runtime schema

## Outcome and authority

Create eight product tables in Leta's own PostgreSQL database, plus the pinned LangGraph saver tables. Root Leta is a workspace resource; its UUID is unrelated to a users row. Leti is a runtime child, not another authorization subject. Follow [accepted design](design-contract.md), [tool arguments](tool-contracts.md) and [user migration](phase-02-user-agent-migration.md).

This phase owns SQL/domain validation and a thin explicit migration entrypoint, not HTTP, remote provisioning or a task system. No cross-service SQL/foreign keys, mirrored grant table, command journal, outbox, lease or new identity registry. Execution evidence is in [Phase03 execution](reports/phase-03-execution.md).

## Current evidence and files

Phase02 now implements human-only users and removes managed-account behavior. Workspace owns human membership/mappings; LetFS `CreateScopes` creates ordinary storage without account identity. The domain schema and listed files below are implemented and tested on isolated PostgreSQL.

| Action | Absolute path | Purpose |
| --- | --- | --- |
| Created | `/home/qninh/projects/openlet/apps/leta/migrations/0001_agent_domain.sql` | Eight tables, checks, FKs, uniqueness and indexes. |
| Created | `/home/qninh/projects/openlet/apps/leta/src/leta/domain.py` | Closed resource/runtime DTOs, generic input envelope and names. |
| Created | `/home/qninh/projects/openlet/apps/leta/src/leta/store.py` | Short SQL transactions, queries, cursor pages and lifecycle gates. |
| Created | `/home/qninh/projects/openlet/apps/leta/src/leta/migrate.py` | Existing Goose mechanism plus pinned saver setup, invoked explicitly. |
| Created | `/home/qninh/projects/openlet/apps/leta/tests/test_domain.py`, `test_store_integration.py` | Real validation/SQL/concurrent commit tests. |
| Extend phase01 | `/home/qninh/projects/openlet/apps/leta/tests/conftest.py` | Disposable DB migrations/teardown, never ambient live DATABASE_URL. |

Uses async psycopg from phase01. Native GetLetaBinding is added in phase04 using these canonical rows.

## Canonical tables

Use UUID, bigint, TEXT, JSONB and timestamptz with server timestamps and parameterized SQL. Archive retains rows, history and files; do not cascade physical removal.

### agents

| Field | Contract |
| --- | --- |
| id PK | Root resource/runtime UUIDv7, or child runtime UUIDv7. Never a human identity. |
| leta_id FK agents | Root references itself; Leti references root. |
| kind | leta or leti. |
| workspace_id, created_by_user_id | Required root fields, immutable; null on children which join root. External IDs have no cross-database FK. |
| home_scope_id | Root-only unique ordinary LetFS scope ID, allocated before provisioning. Not a member personal scope. |
| box_id | Null root; required child, composite FK `(box_id,leta_id)` to boxes. |
| name, description, system_prompt | Bounded validated UTF-8. Leti identity/prompt comes from complete box graph; root prompt/name owner-configurable. |
| model_id, reasoning_effort | Root selected supported pair. Nullable child overrides inherit root fields; owner-only updates validate effective pair. No internal aliases. |
| status | initializing, active, deleting or archived. |
| paused | Root-only control; children read effective root pause. Pause accepts input. |
| inbox_seq, activity_seq | Nonnegative committed-order counters, initial zero, allocated under row lock. |
| created_at, updated_at, archived_at | Server timestamps; archive nullable. |

Checks distinguish root `id=leta_id`, no box, root authority/home/config present from child `id<>leta_id`, box present, root-only fields null and paused=false. Add unique `(id,leta_id)`/`(id,box_id)` for graph references. Validate parent is actually a root in the transaction. thread_id is derived from id, not another editable column. No type=agent user row, account-ID equality, owner_account_id, membership_key or leave_key.

Live Leti names are unique across their root; archived names may be reused with new IDs. Root config edits keep context. Model catalog belongs to configuration, not SQL permissions or a per-run budget.

### boxes and box_edges

boxes contains id, leta_id, name, description, representative_agent_id, reserved home_node_id, lifecycle status and timestamps. Name/graph are immutable. Enforce unique live `(leta_id,name)`, and deferred representative FK `(representative_agent_id,id)` to `agents(id,box_id)`. Insert the whole box and children atomically with deferred checks.

Derive `.leti/<box-slug>` from name; no slug column. Use one deterministic function: NFKC/casefold, preserve Unicode letters/digits and `-`/`_`, replace other runs with `-`, trim separators, reject empty/dot segments. Under a short root lock reject collision against live derived box slugs. After archive plus completed home trash, name reuse reserves fresh box/child/home IDs; never adopts old context or an unrelated path occupant.

box_edges has primary key `(box_id,agent_low_id,agent_high_id)`, low<high and composite endpoint FKs to same box. No self edge; disconnected graphs allowed. Edge is communication permission, not execution order/dependency.

### messages

| Field | Contract |
| --- | --- |
| id PK, leta_id | Stable actual message identity and root namespace. |
| sender_agent_id nullable | Actual verified runtime sender independent of source label. |
| recipient_agent_id, recipient_user_id | Exactly one present. Agent recipient row is its inbox item; human recipient is actual creator chat. |
| seq | Required positive agent-recipient sequence; null human recipient. Unique `(recipient_agent_id,seq)`. |
| source_type, source_id, source_label | Envelope source object. Nonempty bounded type string validated by owning adapter, not a closed future-notification enum. |
| conversation_key nullable | Opaque grouping such as owner/root or box ID; omitted adapter keys normalize to the generic source type/ID pair on admission. Public conversation_id is this projection, not another table. |
| reply_to nullable JSONB | Validated current routing address or null. Source labels never grant a reply route. |
| in_reply_to_message_id nullable FK | Visible prior message with compatible root/conversation/route. |
| content, data | Immutable readable text and adapter-validated structured data. |
| created_at, read_at nullable | Detail-read marker independent of steering cursor and task completion. |

Indexes: recipient/seq; recipient/conversation/seq; partial unread recipient/seq; root/conversation/created_at/id; human recipient/created_at/id. No inbox copy, closed/processed status, conversation lifecycle or generic delivery entity. Final model note is not a message. Domain ID equality on retry compares immutable semantic payload before returning the saved result; changed payload conflicts.

### runs

id (business run), agent_id FK, status running/paused/completed/failed/cancelled, started_at/finished_at, diagnostic attempt, inbox_cursor projection, optional checkpoint_id/checkpoint_ns, continuation, yield_requested default false, result and sanitized error. Partial unique unfinished running/paused row per agent; index agent/started_at/id.

Checkpoint owns input progress inside invocation; SQL run cursor is updated at return. Yield/pause continues the same run. A completed saved result returns without model work; a completed checkpoint can finalize a missing SQL result. Terminal failure uses existing run/Workflow error behavior, no failure-specific cursor/wake subsystem. The existing dedicated saver/advisory connection is phase10's small overlapping-attempt guard, not another lease/fence.

### activity_log

id, agent_id, optional run_id, positive seq, kind, optional llm_message_id/tool_call_id/message_id, dedup_key, data JSONB and created_at. Unique agent/seq and agent/dedup_key; indexes agent/seq and agent/run/seq. Natural identities derive from persisted runtime message/tool IDs.

Public kinds: inbox_input, assistant, tool_call, tool_result, final_note, compaction. Preserve public args/results and intentional summary, not hidden reasoning/provider-private fields or repeated full prompt snapshots. Phase11 owns exact projections/checkpoint publication barriers. Typed input may reference immutable messages rather than duplicating bodies.

Journal is not a permanent command-admission/completion ledger. Tool execution history does not suppress replay of an unfinished shell/Monty command: user accepts duplicate effects and agent correction. Reuse saved results where present. Domain sends/requests/creates still use their real IDs to avoid duplicates under ordinary retries.

### hitl_requests

id, leta_id, requester_agent_id, kind ask/approval, status pending/resolved/cancelled/expired, title, payload, approver_user_id, optional grantee_leta_id/resource/requested_role/decision/outcome, stable outcome_message_id, optional grant_key, expires_at/resolved_at and created_at.

Ask targets root creator and has no grantee/resource role. Approval targets exact human resource owner, grants viewer/editor to root Leta, never human creator/Leti. Accepted decision plus no outcome means granting remains in progress; no fifth status. Keep approver/status/time, requester/time and unsettled-root indexes for cleanup snapshots. Actual grant authority stays Workspace/SpiceDB.

### schedules

id, leta_id, creator_agent_id, target_agent_id, optional box_id route, title, content, canonical spec JSON at/interval/calendar, paused, end_at, deleted_at and timestamps. Normalize relative instants/anchors once; no target reassignment, occurrence table or second scheduler. Index root/id and live target/id. Phase14 owns conversion, BUFFER_ONE and complete bounded calendar ranges without public pagination.

## Commit-ordered transactions and resource gates

1. Inbox insert first looks up message ID; compare immutable payload and return existing receipt or conflict.
2. Root-recipient path takes root FOR UPDATE immediately. Child path takes root FOR SHARE, box FOR SHARE, child FOR UPDATE; do not SHARE-lock root then upgrade. Locks are held for SQL only.
3. Under locks recheck root/box/recipient active, sender route and source admission. Pause is allowed. For a schedule delivery, also recheck source tombstone/current target at admission; pause after captured delivery does not retract it.
4. Recheck message ID, increment recipient counter, insert, commit; only then return seq. Rollback rolls back counter. A later sequence cannot commit first and make an earlier message invisible to cursor collection.
5. Activity insertion locks its agent counter, dedups, allocates and commits in the same fashion. Public forward readers never skip a late lower seq.
6. Child box/request/schedule creation checks root/box gate in its insertion transaction. Deletion takes the update gate, marks deleting and snapshots affected IDs. A racing create commits before snapshot or is rejected afterward. No remote call inside SQL locks.

Workspace lifecycle is external, so root creation/provisioning additionally uses phase04's current W admission, and activation rechecks its local root state. If W deletion wins, normal home provisioning rejects; late initializing rows cannot activate. Do not add a cross-service SQL lock, resource registry or claim distributed transactions.

Keyset pages bind root/agent/filter and last scanned key; avoid deep OFFSET or lifetime transcript loads. Root enumeration for Workspace cleanup includes initializing/deleting/archived rows by immutable id. Neither Redis availability nor a stream event is authority for a committed product row.

## Implementation tasks

1. [x] Implement domain enums, identities, generic source/reply contracts and exact model_id/reasoning_effort naming; test foreign-root and invalid root/child shapes.
2. [x] Create dependency-ordered SQL tables and deferred graph constraints. Exercise actual PostgreSQL18.6 insertion rather than assuming circular FKs work.
3. [x] Implement short commit-order/gate helpers in store.py, immutable retry comparisons and explicit conflicts. No repository framework or ORM generation.
4. [x] Implement root/box/message/run/journal/request/schedule bounded reads and archive transitions, including native canonical-binding/root-enumeration queries for phases04/17.
5. [x] Reproduce concurrent commit with held transaction barriers; prove same ID one row, no skipped sequence and rollback leaves no lost item.
6. [x] Race child create against root/box deletion and prove whole graph/snapshot integrity. Test live name/slug reuse and retained historical IDs.
7. [x] Add `python -m leta.migrate` as a thin explicit entrypoint using existing Goose SQL numbering/tooling and the pinned saver's public setup once. Fixture invokes it on owned disposable DB; API/worker startup only verifies readiness. Phase18 packages it.

## Verification and acceptance

The following checks passed during execution; see the linked execution report:

```sh
uv run --locked --package leta pytest apps/leta/tests/test_domain.py apps/leta/tests/test_store_integration.py -q
pnpm --filter @openlet/leta check
```

- [x] Eight product tables contain resource/runtime data only; human identity and scope grants remain owned externally.
- [x] Commit-order, graph FK, route/root-gate and retry-payload tests pass with real SQL.
- [x] Typed public history and request/schedule state are pageable independently of checkpoints/Temporal history.
- [x] No user/account provision fields, permanent command receipts, extra inbox/task or silent physical cascades.

The user waived backup/legacy conversion prerequisites for this development-only implementation. Use an owned disposable database and do not reset unrelated development state. Before domain writes, schema can be reverted on its owned empty DB; after writes, preserve rows/checkpoints and use compatible forward fixes or phase18's coordinated restore, never automatic destructive down-migration.
