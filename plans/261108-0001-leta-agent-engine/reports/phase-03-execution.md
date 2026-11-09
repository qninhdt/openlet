# Phase 03 execution checkpoint

Status: complete. Phase04 resource access is next; this report covers local domain persistence, not a runnable agent engine or external provisioning.

## Delivered

- Eight product tables in `apps/leta/migrations/0001_agent_domain.sql`, plus the pinned LangGraph saver tables. Root Leta is a workspace resource; children carry no human identity or authorization subject. Circular box/representative references use actual deferred composite foreign keys.
- Validated domain inputs for root/box/message/activity/request/schedule storage. Model selection uses the existing catalog. Names and derived Unicode box slugs are validated; there is no slug column, closed future-input enum or task entity. Detailed question/answer and schedule compilation rules remain with phases13/14.
- `store.py` implements parameterized, bounded SQL reads, immutable retry comparisons, whole-graph insertion, routing checks, per-agent inbox/history counters, runs and archive transitions. Root/box gates and counters are held only inside short SQL transactions. No network effect runs inside them.
- Deletion closes the owning gate before returning source/request/agent snapshots. Late creation/admission rejects; archived graph/history rows remain. Reused box/Leti names receive new identities and do not revive previous context.
- `python -m leta.migrate` uses the existing pinned Goose mechanism and the saver's public async setup. Repeating migration preserves existing domain/checkpoint tables. API readiness now checks applied product/saver versions without running migrations. Phase09 will use the same verification for its real worker startup.
- Disposable fixtures build Goose from the pin in `infra/bootstrap/Dockerfile` when it is absent, create their own PostgreSQL, apply the actual entrypoint and clean up. They never read ambient DATABASE_URL.

## Verification

- Full Leta suite passed:78 tests, including17 real PostgreSQL domain/migration tests plus existing saver/Mirage/Monty/Redis/Temporal compatibility gates.
- Subsequent boundary review added three UTF-8/JSON validation cases; all22 domain tests and all17 SQL integration tests passed after the final DTO tightening.
- SQL tests prove whole-graph atomicity, FK rejection, derived-slug collisions, retained historical IDs, one row under concurrent same-ID receive, ordered history counters, held-transaction commit ordering, real insert rollback, root/box deletion races, representative/edge routing, no Leti-human chat, reply-address checks, scope-root isolation, exact request approver storage, schedule tombstones, bounded reads and terminal run result reuse.
- `uv build --package leta`, app Ruff check/format and `git diff --check` passed. The Phase04 continuation reran the entire app suite with the tightened DTOs:87 passed, including the17 SQL tests and new native binding tests.
- ak-cook's conditional simplification ran with gpt-6.1-sol/xhigh, limited to Store. It removed redundant representative/reply expressions without changing SQL/gates/counters. Two focused real-SQL tests and Ruff passed after its edits.

## Remaining owning phases

Workspace permission/provisioning and native binding/listing are phase04. Filesystem/Mirage integration is phases05–08. Actual six Temporal Workflows, steering, graph execution/public history, human settlement, native schedule execution and SSE are phases09–17. Phase03 does not publish resource tuples, run an LLM, grant access or start schedules.

No existing development data/containers were modified, and no commit/push/deployment or paid inference occurred. The entire19-phase goal remains active.
