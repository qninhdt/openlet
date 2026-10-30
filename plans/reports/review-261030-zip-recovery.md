# ZIP Export and Local Recovery Review

Status: DONE_WITH_CONCERNS

## Scope

Reviewed the ZIP export flow from Workspace authorization through letfs enumeration, archive generation, publication, direct download, retry and cleanup. Also reviewed coordinated local backup refusal, format-2 image pinning, isolated restore, the phase 4/5 contracts, operations documentation, and connected integration/E2E tests.

## Finding

### High: Source changes permanently disable the configured export retry

- Paths: `services/letfs/src/temporal/export_archive_workflow.rs:41`, `services/letfs/src/temporal/mod.rs:17`, `services/letfs/src/fs/exports.rs:335`
- Scenario: A selected entry is renamed, replaced, or revised after archive generation but before publication. Publication correctly returns `SOURCE_CHANGED`, but the activity marks the operation `failed` because the error is HTTP 409. The shared Temporal conversion also marks every 4xx failure non-retryable. Temporal therefore does not perform the configured second attempt, and a retry would be rejected by `prepare` because the operation is no longer running.
- Impact: A normal concurrent edit turns an export that should retry by reauthorizing and re-enumerating current inputs into a permanent failure under its idempotency key. This contradicts the accepted phase-4 retry contract.
- Smallest fix: Classify export terminal errors explicitly. Keep `SOURCE_CHANGED` running and retryable, while terminal validation, idempotency and hard-limit failures remain failed/non-retryable. Add a workflow-level test that changes the source during attempt one and proves attempt two re-enumerates and publishes the changed archive.

## Checks

- Confirmed actor/filesystem binding and current Workspace membership authorization on create, status and download.
- Confirmed original-only traversal stops at files and explicit artifacts use their separate child tree.
- Confirmed current-attempt publication fencing, output/source bounds, multipart cleanup evidence, expiry-bounded signing and direct object delivery.
- Confirmed local backup refuses unfinished storage work, preserves existing test volumes during the drill, pins format-2 service/model images, and restores infrastructure without application execution before explicit resume.
- Confirmed Windows superscript device names are covered by the focused `COM`/`LPT` validation fix.

## Not Checked

Docker suites were not rerun during this independent review. Current full integration, E2E, workflow replay, backup drill and provider evidence was supplied by the controller. External R2 coordinated disaster recovery remains deliberately not run and is still a production gate.

## Fix Review Disposition

The first fix correctly keeps an export operation running when `SOURCE_CHANGED` is returned, and the new E2E test is a strong regression case: it blocks the first real source GET, renames the source, releases the request, requires generation 2, and independently checks the renamed ZIP entry and exact bytes. The mandatory retry history and replay wiring are also appropriate.

However, the implementation introduces a new high-priority regression and is not accepted yet.

### High: Shared retry classification changes CopyNode source-change behavior

- Paths: `services/letfs/src/temporal/mod.rs:17`, `services/letfs/src/temporal/copy_workflow.rs:39`, `services/letfs/src/temporal/copy_workflow.rs:100`, `services/letfs/src/fs/copy.rs:232`, `services/letfs/src/fs/copy.rs:353`
- Scenario: A copy source is renamed, removed, revised, or has its object key replaced while a copy batch is running. `copy::batch` returns `SOURCE_CHANGED` so the workflow can leave its batch loop and run its existing discard path.
- Regression: The new shared `terminal_activity_error` makes `SOURCE_CHANGED` retryable for every activity using `activity_error` or `with_heartbeat`, including `CopyNode`. Its batch activity has no explicit bounded retry policy. A deterministic copy source change can therefore remain in Temporal activity retries instead of returning to the workflow for discard.
- Smallest fix: Preserve the existing shared client-error classification and apply the `SOURCE_CHANGED` exception only to `ExportArchive`, either through an export-specific error mapper or an explicit retryability parameter at that activity boundary. Keep the export database failed-state decision on the same export-specific predicate.
- Required check: Retain the new export retry E2E/replay, and run the existing copy source-change/race coverage to prove copy still reaches its discard behavior without retry drift.

Fix review status: CHANGES_REQUESTED

## Scoped Correction Review

The follow-up correction resolves the CopyNode regression:

- `temporal::activity_error` is restored to its prior behavior, so all HTTP 4xx errors remain non-retryable for copy and lifecycle activities.
- `with_heartbeat` now requires an explicit error mapper. All four callers were checked: CopyNode and both lifecycle maintenance activities pass the unchanged shared mapper; only ExportArchive passes `export_error`.
- ExportArchive owns one `terminal_error` predicate and uses it consistently for both the persisted failed-state transition and Temporal `ApplicationFailure` retryability. `SOURCE_CHANGED` therefore leaves the operation running for generation 2, while other terminal 4xx failures still stop retries.
- Workflow commands, activity options and retry bounds are unchanged. The real barrier E2E and mandatory `ExportArchiveRetry` replay remain suitable evidence for the repaired contract.

No high or medium defects were found in the scoped correction.

Final fix review status: ACCEPTED

Verdict: Ship after the controller's current-revision E2E and replay checks pass.
