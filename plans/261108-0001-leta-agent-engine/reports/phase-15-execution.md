# Phase 15 execution: authenticated product APIs

## Scope and result

All accepted non-SSE routes are implemented in `apps/leta/src/leta/http/` and
registered by `api.create_app`. PostgreSQL owns every product read model; API
instances own no model runner, Workflow-history reader or polling coordinator.
Gateway deployment is still phase18; live events are phase16.

- Strict body/response DTOs cover catalog, root lifecycle/configuration,
  inherited Leti overrides, immutable box canvas, actual owner/root chat, inbox,
  typed history/detail, runs, addressed/managed human requests and schedules.
- Creator plus fully-consistent `leta.read/manage` checks protect resources.
  Global human-request cards use exact approver selection plus current Workspace
  access; the agent creator cannot approve another human's personal scope.
- Creator lists/canvas use bounded SQL pages, scoped cursors and batched summaries.
  The calendar is a complete bounded date-range response without pagination.
  Tool/compaction/input history uses the existing ActivityEntry discriminated
  union; replay-only tool message metadata is absent from public output.
- All product responses use no-store. Invalid request errors identify fields
  without echoing submitted text. Output/persisted-data validation is not
  misclassified as a client validation error.
- Root pause is projected consistently on Leti roster, box and configuration
  responses. Archived resources keep the existing read authorization path;
  no alternate archive permission was introduced.

## Ordinary command keys

Migration `0002_api_idempotency.sql` adds the ordinary Leta-local
`idempotency_keys` infrastructure table beside the eight product tables. This
implements phase15's accepted stable HTTP allocation contract by following
Workspace's existing key/hash/completion-expiry mechanics. It is not another
product operation/receipt registry.

Keys bind the authenticated actor, method/path/body hash and allocated resource
UUID. Pending keys keep identity; acknowledgment starts a 24-hour expiry once.
Completed command retries read current resource state without reapplying stale
pause/configuration/schedule changes, independently of the Temporal run's Update
registry. They do not renew expiry. Relative schedule time uses the key's stored
creation time, and accepted Updates keep the same canonical input.

Owner input uses the client-stable message UUID, without a second key table row.
A completed Temporal Update does not revalidate a changed body, so the HTTP
adapter compares the persisted message with the same canonical mapping used by
Store.receive before acknowledging it. Timeout returns 202 and a lookup/retry
route; no PostgreSQL inbox admission is claimed before it exists.

A lost API completion before its ordinary key is completed can still retry an
unfinished command. No global exactly-once guarantee, outbox, lease or recovery
poller is added. Creation retries return existing active/deleting/archived
resources rather than restarting a finished coordinator.

## Verification

- Existing inbox/store/lifecycle gate after configuration factoring and migration:
  **30 passed in 88.37s**.
- Existing HTTP startup/history gate: **13 passed in 1.69s**.
- Complete Leta regression: **260 passed, 5 skipped in 426.32s**. This supersedes
  phase14's two repaired compaction-fixture failures. The skips require the
  explicit native Mirage/Workspace integration fixtures; their earlier owning
  native gates are retained, not claimed rerun here.
- Final HTTP/contract suite after the last route/SDK cleanup edits:
  **7 passed in 41.51s**. Actual PG migrations, Temporal native Schedule delivery,
  six-Workflow worker registration and HTTP adapters run in disposable fixtures.
  Authorization is a protocol-compatible external fake exercising the real Python
  check/bulk adapters; external lifecycle filesystem/workspace collaborators and
  remote grant are explicit existing fakes. Phase13's actual Workspace/SpiceDB
  grant gates remain the native evidence for that remote boundary.
- Tests prove cross-owner/root/agent/box/run/message/request denial, membership
  loss, actual chat versus internal messages, custom typed input/tool/compaction
  reload, scoped cursor mismatch, resource-owner-only approval, exact Leti ask
  resumption, all three question types with empty choices/notes, incompatible
  inherited model names, pause projections, absolute/relative calendar reads,
  stable creation retries and changed-payload conflicts.
- Worker offline test observes202 plus absent message lookup, then starts the
  worker and retries to one admitted inbox item. The Java time-skipping server
  crashes in this no-worker Update-with-Start scenario; this gate therefore uses
  the actual pinned native Temporal server rather than a product fallback.
- Installed SDK 1.35.0 inspection exposed a separate failed start future after
  Update-with-Start RPC cancellation. Shared bridges now observe the public
  workflow_handle future on that error path. The final native timeout/retry
  gate passes without the previous unobserved-Future diagnostic.
- Public manual OpenAPI owns all 23 Leta product paths and strict schemas, 202,
  Idempotency-Key, errors and examples. Contract tests compare active route
  bodies/responses and verify every local ref. `pnpm contracts:check` passes;
  `pnpm --filter @openlet/leta check` passes 88 formatted files before phase16
  additions. No generated LetFS contract was hand-edited.
- Independent read-only scoped review found the message-retry comparison and
  inconsistent child pause projections; both are fixed and covered. Its
  completed-key/run-rotation concern is handled with ordinary completion expiry,
  not another durable-command subsystem.

## Remaining owners

Phase16 owns one Redis root stream, runner/model/tool publication, sparse Workflow
notifications, SSE bootstrap/reconnect and merge measurements. Phase17 owns trusted
Workspace teardown. Phase18 owns real gateway/Compose/API wiring and coordinated
operational recovery. No commit, push, deployment or existing database change was
performed; only owned disposable test databases were migrated.
