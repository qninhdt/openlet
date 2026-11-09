---
title: "Phase 14: Temporal schedules and calendar queries"
status: complete
priority: P1
dependencies: [3, 9, 12, 13]
---

# Phase 14: Temporal schedules and calendar queries

## Overview

Implement one schedule product backed by PostgreSQL and executed by native Temporal Schedules. Agents can schedule a specific time, a relative delay, an anchored interval or calendar recurrence. Owner can later render the same definitions and occurrences as a calendar.

Read [accepted design](../reports/design-261108-0148-leta-workspace-resource.md), [schema](phase-03-leta-domain-schema.md), [inbox/Workflow boundaries](phase-09-temporal-agent-inbox.md) and [tool catalog](tool-contracts.md). No APScheduler process, separate calendar system or generic scheduler-node engine. Creator controls require current workspace membership and `leta.manage`; target IDs are resource/runtime IDs, never human IDs for bots.

Execution state: pure typed validation/canonicalization and native ScheduleSpec compilation are implemented; **28 pure tests passed** against the installed temporalio 1.35.0 types. Native Schedule CRUD/delivery/forecast, tools and runtime acceptance remain unimplemented/unrun. See the [execution checkpoint](reports/phase-14-execution.md).

## Current evidence and files

- Existing services have Temporal workers, but no product schedule API. The lab is evidence for agent/stream integration, not this scheduler's implementation.
- Pinned SDK is `temporalio==1.35.0`, read in `/tmp/leta-engine-review/src/temporalio/client/_schedule.py`: `ScheduleHandle.update:240–275` may repeat conflict callbacks; `ScheduleSpec:279`, `ScheduleCalendarSpec:418`, `ScheduleIntervalSpec:480`, `SchedulePolicy:950`, `ScheduleState:995` define native fields/defaults. See [versioned source](https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/client/_schedule.py). This is source evidence, not executed server compatibility.
- `workflow_service.list_schedule_matching_times` is the generated service method, not a ScheduleHandle convenience method. Verify the deployed server supports it in the Phase 1 compatibility fixture.
- Modify phase03 repository/schema only for its declared schedule contract; phase15 mounts routes, phase16 emits typed events, phase18 deploys workers. Do not duplicate service logic in HTTP handlers/tools.

All paths below are relative to `/home/qninh/projects/openlet` and are proposed, not existing source:

| Owner/action | File and symbols | Boundary |
| --- | --- | --- |
| New | `apps/leta/src/leta/schedules.py`: `canonicalize_schedule`, `compile_schedule`, `calendar_occurrences` | Pure validation/native translation and bounded complete previews. |
| New | `apps/leta/src/leta/temporal/schedules.py`: `ScheduleChangesWorkflow`, `ScheduleDeliveryWorkflow`, `save_schedule_change`, `apply_temporal_schedule`, `load_schedule_occurrence` | Serialized changes and one-occurrence delivery. |
| New | `apps/leta/src/leta/runtime/schedules.py`: create/list/get/update/delete schedule tools | Runtime context injects actor/root/target; tools reuse domain operations. |
| Modify | `apps/leta/src/leta/store.py`, `apps/leta/src/leta/domain.py`, `apps/leta/src/leta/worker.py`, `apps/leta/src/leta/runtime/tools.py` | Schedule SQL/DTOs, actual registration and roster. |
| New | `apps/leta/tests/test_schedules.py`, `apps/leta/tests/test_schedules_integration.py` | Translation/one-shot state, real server matching/delivery/crash tests. |

## Schedule contract

Store ID, root/creating-agent/target-agent IDs, optional box address, title/content, canonical spec JSON, paused/deleted state, end_at and timestamps. Root supplies workspace_id/created_by_user_id; no account/membership identity. Keep one product definition per native Schedule ID. Actual delivered messages carry schedule_id and scheduled_at; do not materialize unbounded occurrence rows.

```json
{"type":"at","at":"2026-11-09T09:00:00+07:00"}
{"type":"at","after_seconds":5}
{"type":"interval","every_seconds":432000,"anchor_at":"2026-11-08T09:00:00+07:00"}
{"type":"calendar","timezone":"Asia/Ho_Chi_Minh","fields":{"hour":[9],"minute":[0],"second":[0],"day_of_month":[1]}}
```

The first two are alternative tool/API inputs. Canonical persisted at always has an absolute timestamp, normalized once with server time and rounded upward to native second precision. For interval, persist a default anchor once; reject zero/negative duration. For calendar, fields accept "*", integer values or `{start,end,step}` ranges supported by ScheduleRange, with explicit range/step validation. Omitted fields use Temporal's documented CalendarSpec defaults; expose the canonical expanded form in API output so UI does not guess. Validate IANA timezone; timestamps require offsets. Do not interpret one month as 30 days or every five days as `day_of_month=*/5`.

Leta creates schedules for self or a box representative. Leti creates schedules only for self. Leta/owner can inspect and manage schedules of their boxes. Persist resolved target and box address; reject cross-Leta targets. An end_at is optional for recurring schedules; explicit null removes it on update. Reject end_at on at to avoid a contradictory second deadline.

## Implementation steps

1. [x] Add typed tagged-union validation and canonicalization in the domain service. Repeated create/update with the same persisted tool call or command key reuses canonical timestamps; it never recomputes now+delay on retry. Preserve creator/target identity when updating spec; do not expose arbitrary target reassignment in MVP.
2. [x] Implement `ScheduleChangesWorkflow(schedule_id)` with serialized Update handlers. Local `save_schedule_change` validates lifecycle and saves the normalized definition/tombstone in one short transaction. Regular `apply_temporal_schedule` applies native CRUD; return after acknowledgment. Temporal retains ordinary execution progress/retry. No command-journal admission/completion stages or second save solely for permanent command deduplication; arbitrary historical update replay after rotation is outside the MVP guarantee.
3. [x] Compile at to a full UTC CalendarSpec with limited_actions=true and remaining_actions=1. Compile interval using `ScheduleIntervalSpec(every,offset)` where offset equals anchor relative to Unix epoch modulo interval, plus start_at when needed. Calendar maps fields and timezone directly to native types. Map end_at to native ScheduleSpec.end_at.
4. [x] Native action starts `ScheduleDeliveryWorkflow` on the control queue with schedule ID. Read nominal scheduled_at from `workflow.info().typed_search_attributes` using `SearchAttributeKey.for_datetime("TemporalScheduledStartTime")`; confirm schedule identity against `TemporalScheduledById`. SDK 1.35.0 exposes typed search attributes and key factories; official Schedule docs name these server-provided fields. Pin and integration-test this against the deployed server. Direct already-due at delivery carries the persisted explicit timestamp instead. Never substitute delivery wall time; absent/mismatched native metadata is an explicit error.
5. [x] Handle at already due when first provisioned: invoke the same delivery Workflow with its original at timestamp and stable Workflow ID, instead of creating a nonmatching future calendar. Delivery message ID is deterministic for schedule+nominal occurrence. Reusing that Workflow ID attaches to its saved snapshot/result; if the occurrence inbox row already exists, metadata-only edits acknowledge without redelivery or comparing new title/content against the old delivered body. Do not restart an already completed occurrence Workflow to rerun Local snapshot reads. Update native one-shot state deliberately: metadata-only edit never resets consumed remaining_actions; changing an unfired at spec changes the deadline. A fired at remains consumed until owner/agent explicitly changes its timestamp/spec, which requests a new occurrence.
6. [x] Apply `ScheduleOverlapPolicy.BUFFER_ONE` and omit catchup_window to retain server default. This bounds overlapping delivery executions; it does not serialize all agent work or guarantee latest-only/all-missed delivery. Native create conflict describes the existing resource. Compare its compiled spec/action with the desired command; an already matching resource is success even if its one-shot remaining_actions is now zero. Use ScheduleHandle.update's conflict-retry callback to preserve current consumed state for metadata/pause edits and already-applied retries. Reset a one-shot allowance only when a genuinely different spec is being installed, never because Activity completion was lost after firing. Do not delete/recreate the resource for update.
7. [x] Implement `ScheduleDeliveryWorkflow`: Local `load_schedule_occurrence` reads current target/schedule/root state and returns a stable snapshot of content, route, scheduled_at and message ID; regular `deliver_agent_input` admits it through AgentWorkflow.receive and completes after inbox commit. Local snapshot is recorded before a later retry, so definition edits cannot change payload under an existing message ID.
8. [x] Deleted schedule/target returns skipped. A paused schedule blocks new snapshot admission; pausing after a delivery snapshot does not retract an already admitted occurrence. Delete marks SQL first and removes native Schedule; a late delivery checks tombstone/root state again at inbox admission. A deleted schedule ID is not reused.
9. [x] Implement **one complete bounded calendar result**, with no public pagination, cursor or partial-success forecast. Read at times from canonical definitions; recurring uses generated ListScheduleMatchingTimesRequest(namespace,schedule_id,start_time,end_time), not a nonexistent ScheduleHandle helper. Initial tunable bounds: default 31/max 366 days, total 1,000 occurrences, 32 authorized definitions, 32 total native preview RPCs and concurrency 4 per request. If definition/result/RPC bound would prevent completeness, return a clear request-too-large error requiring narrower date range or target/schedule filter; return no misleading partial list. Sort the complete result globally by scheduled_at then stable schedule/target IDs. The frontend does not merge incomplete pages.
10. [x] Internal matching-times continuation handles the native 1000-item cap. A response of exactly 1,000 is potentially truncated; continue strictly after its last instant with unchanged end_time, never add one second. Accumulate under the request bounds; even when collected count equals result cap, prove exhaustion or return too-large. Confirm actual server exclusive-start/inclusive-end and cap behavior in phase01/this integration gate; the API date range must consistently apply its declared endpoints when merging persisted at times. No product cursor is exposed. A single get_schedule returns only its explicitly bounded next-time projection, clearly separate from complete date-range calendar.
11. [x] Definitions remain readable from PG during Temporal outage; complete recurring forecast returns explicit unavailable/error, never invented times or partial success. Delivered history comes from messages/runs, separate from forecast. Calendar entries include schedule ID/title/target/box, nominal scheduled_at, IANA timezone and paused state. Pause stops future production; an already-admitted snapshot may finish. Delete additionally rechecks current source/target at inbox admission and never retracts committed input.
12. [x] Register create/list/get/update/delete tools; paused implements pause/resume. Reuse service behind creator API. After save_schedule_change commits a visible definition/pause/delete, call shared regular `publish_resource_event(root.leta_id,kind='schedule',resource_id=schedule_id)` outside Local SQL. Its bounded publisher-only retry cannot redo native Schedule apply, one-shot allowance, inbox admission or block required deletion. Runtime/API outside Workflow use the same ordinary publisher directly. Phase16 emits the stable-root-stream sparse ref with both agent_id and run_id (nullable outside a run); never emit forecasts as committed history or add a second SQL completion save. On notification loss, reconnect refreshes PG definitions while valid text replay continues; no polling/outbox.

## Requirements

- [x] Canonical at/interval/calendar specs support the original examples and specific timestamps.
- [x] Retry-safe native CRUD preserves anchor and one-shot consumed state.
- [x] Delivery completes on inbox commit and applies BUFFER_ONE only to delivery.
- [x] Calendar returns complete sorted bounded date-range result or explicit too-large/unavailable error; no public pagination or partial forecast.

## Verification and acceptance

Future commands after phase01 defines the Leta package/scripts; none run in this planning turn:

```sh
uv run --locked --package leta pytest apps/leta/tests/test_schedules.py -q
uv run --locked --package leta pytest apps/leta/tests/test_schedules_integration.py -q
pnpm --filter @openlet/leta test:replay
pnpm --filter @openlet/leta check
```

Export sanitized histories for both Schedule Workflow types. Use real PostgreSQL and the pinned/deployed Temporal server for delivery and matching-times, not only mocked Client return values.

| Scenario | Required evidence |
| --- | --- |
| Five-second/one-hour delay | Absolute normalized time stable on retry; no early due time. |
| Exact timestamp and already-past provisioning | One inbox item with original scheduled_at. |
| Every hour/every five days | Correct anchor across month/year boundary, not epoch-aligned accidentally. |
| Monthly day 31 / DST zone | Native missing-day/DST behavior matches preview; no hand-written timezone interpretation. |
| Worker stopped across occurrence | Delivery waits durably, then admits once; overlaps demonstrate BUFFER_ONE rather than all-missed promise. |
| Server outage | Catchup behavior is documented for actual server; worker outage is tested separately. |
| SQL commit then native failure | Workflow retry converges without second schedule/duplicate timestamp normalization. |
| Inbox commit then lost delivery completion | Same occurrence message ID, one inbox row. |
| Pause/delete/box archive race | No target resurrection; committed input retained; future source removed. |
| Fired one-shot title/pause edit | No accidental second occurrence. |
| Explicit one-shot time/spec edit | Consumed definition rearms only for genuinely changed time/spec; lost acknowledgement does not reset allowance again. |
| Full calendar/multiple definitions | Complete globally sorted bounded result, no per-schedule partial pages or cursor. |
| Native 1,000 cap | Exact1000 response continues internally to prove exhaustion; >result/RPC bound fails clearly without partial success or missing boundary instant. |
| High-frequency/large range | Error explicitly requires narrower range/filter; no unbounded native fan-out. |
| Forecast dependency outage | Definitions remain readable; forecast unavailable is honest, no partial results pretending complete. |
| Sparse definition publication | Create/edit/pause/delete while root idle emits a committed ref through the regular publisher; Redis failure repeats neither native apply nor a consumed one-shot occurrence and never blocks deletion. |

Use controlled barriers around commit/native apply, not arbitrary sleeps. Short clock waits are acceptable only for checking a real native schedule deadline; use a bounded observable-state wait. Tests use owned disposable dependencies and controlled LLM responses.

## Risks and rollback

Native schedule metadata and action-limit update semantics are load-bearing integration gates, not inferred from type names. High-frequency schedules can accumulate legitimate inbox inputs while agents are paused; BUFFER_ONE is not an inbox size policy. Show pending counts; do not add an unapproved drop policy.

Rollback disables admission and pauses/removes new native schedules before reverting workers. Preserve PG definitions/tombstones/history/IDs; this fresh development implementation has no backup prerequisite. Never delete/recreate a schedule to simplify retry or reset consumed state accidentally. Arbitrary historical change-command replay after Continue-As-New is outside the accepted guarantee; no permanent command receipts or completion saves are added. Final system acceptance is tracked in phase19.
