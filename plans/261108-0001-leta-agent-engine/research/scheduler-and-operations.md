# Scheduler, streaming and operational evidence

Collected during planning on 2026-11-08. Read-only source/doc inspection; no schedule, database, model request or deployment was executed. Earlier [brainstorm evidence](../../reports/brainstorm-261107-1653-leta-evidence.md) remains the record of prior lab checks and the limited trigram benchmark.

## Version-specific schedule contracts

| Claim | Source and result |
| --- | --- |
| Repo Temporal Python pin is 1.35.0 | `packages/python/pyproject.toml`; native shared dependency is `temporalio[opentelemetry]==1.35.0`. |
| Calendar and anchored interval are distinct | SDK [client/_schedule.py](https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/client/_schedule.py), ScheduleSpec / ScheduleCalendarSpec / ScheduleIntervalSpec. Interval matches epoch+n*every+offset. |
| Calendar fields/defaults | Same source: second/minute/hour default 0, day/month/day-of-week default their full ranges, empty year means all years. Do not default omitted hour to every hour. |
| One-off action limit | Same source: ScheduleState limited_actions and remaining_actions. Actual create/update/consumption remains an integration gate. |
| Overlap/catchup | Same source and [official Schedule policies](https://docs.temporal.io/schedule): SKIP is SDK default; MVP explicitly selects BUFFER_ONE. Default catchup is server policy, currently documented as one year, not an app guarantee. |
| Nominal scheduled timestamp | [Official Schedule docs](https://docs.temporal.io/schedule) name TemporalScheduledStartTime / TemporalScheduledById search attributes. SDK [workflow/_context.py](https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/workflow/_context.py) Info exposes typed_search_attributes; [common.py](https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/common.py) provides SearchAttributeKey factories and TypedSearchAttributes.get. |
| Bounded calendar preview | Generated service exposes ListScheduleMatchingTimesRequest(namespace,schedule_id,start_time,end_time), response start_time list only. Actual server [1.32.1 scheduler source](https://github.com/temporalio/temporal/blob/v1.32.1/service/worker/scheduler/workflow.go), maxListMatchingTimesCount and handleListMatchingTimesQuery, caps at 1,000, starts exclusively and ends inclusively. Phase 14 marks a full cap potentially truncated and resumes at the last timestamp; no invented native page token. |

Context7 lookup used `npx --yes ctx7@latest library temporal ...`, then `docs /temporalio/documentation ...`; both completed. Results corroborate phase offset, nominal search attributes, overlap policies and matching-times preview. CLI-oriented latest snippets were not treated as Python 1.35 method signatures. The pinned SDK source was the authority for Python types.

The native server Compose image currently differs from the scheduler source version cited in the brainstorm. Phases 1/14 must test the actual deployed image; this plan does not upgrade the server solely to match a blog/source example.

## Existing operations and trust boundaries

- `packages/python/src/openlet/identity.py:12`: authenticate_gateway checks trusted gateway token, verified subject and a single nonzero UUID account header in current code (phase02 migrates it to verified user identity). Reuse this in Leta API.
- `packages/python/src/openlet/httpapi.py:6`: problem_json translates safe app errors. Do not leak model prompts/answers in HTTP failures.
- `scripts/bootstrap/configure.py:11`: DATABASES is explicit and omits Leta today. Lines 126–130 generate current app database URLs. Add Leta, preserve credentials.
- `scripts/operations/recovery.py:16`: backup DATABASES is explicit. Lines 31 onward enumerate WRITERS; stop/drain Leta processes before capture. Redis is intentionally reconstructible.
- `infra/compose/dev.yaml` owns PostgreSQL18.6, SpiceDB1.57 and Temporal initialization ordering; `infra/compose/e2e.yaml` is the owned system-test counterpart.
- `.github/workflows/check.yaml` runs native Turbo checks/integration sequentially and separate replay; wire new package into that existing graph.
- `docs/testing.md` requires real PG/Temporal/SpiceDB for persistence/restart claims and separates controlled provider tests from live provider smoke.

CodeGraph was used before inspecting indexed implementation. Current paths were checked against the repository. New Leta source/API paths in phases are proposed additions rather than existing symbols.

## Streaming evidence and its limits

The lab at `/home/qninh/projects/agent-lab/labs/durable-chat/chat/streaming.py` has StreamPublisher, read_events and coalesce_events; `chat/api.py` proxies SSE. It proves an integration direction, not this exact product contract. Its compatibility open_events prefix scan and extra writer fencing are not copied as requirements.

The earlier measured 4,681→438 event/frame result applies to that workload and placement only. Phase 16 coalesces at SSE proxy, so Redis writes/read/parse costs remain. New acceptance measures event bytes, ordering and frame counts independently. Do not infer Temporal replay or checkpoint cost from SSE reduction.

The accepted final design uses one stable Redis Stream per root Leta, including all child/run events, read by one SSE connection with XREAD BLOCK. TTL renewal alone cannot bound it, so phase16 applies per-Leta byte/entry caps. Valid Last-Event-ID resumes partial output; only missing replay resets from PG. No periodic PG discovery polling or per-run stream topology remains. Coalescing happens after Redis and preserves agent/run/block boundaries. Redis is required for readiness; publication failure must not repeat committed business effects.

## What remains empirical

Native one-shot create/update/remaining_actions, already-past delivery, actual nominal metadata, preview cardinality, timezone/DST behavior, worker/server outage distinction, real run recovery, root/request UI consistency and Redis eviction behavior require implementation fixtures. Their acceptance gates are explicit; source support alone is not reported as execution success.
