# Phase 19 execution checkpoint

The sections below preserve incremental results. The [acceptance record](acceptance.md) owns final integrated evidence and phase reconciliation.

## Final integrated result

The final full API/recovery suite passes **45 tests in 8.5 minutes**, including all nine Leta journeys and restore of an accepted approval awaiting its actual Workspace grant. Contracts, check, build, unit, Workflow and all eight integration tasks pass; the six Go-owned Python fixture cases additionally pass through uncached race-enabled native gates. Fresh all-owner replay passes four tasks, and environment ownership/recovery guards pass all three cases. All 19 plan phases are reconciled to complete. Exact commands, fixture limits and material not-run checks are in the acceptance record; earlier open-gate statements below remain historical.

## Verified product journey

`e2e/tests/api/leta.spec.ts` passes through the owned Compose stack in 9.5 seconds. Only remote inference is scripted; Account, Workspace, LetFS, Leta, PostgreSQL/checkpointer, Temporal, Redis and SpiceDB are real.

- An owner creates Leta and sends the same inbox item twice; one item/sequence is returned.
- Leta creates an immutable two-Leti box and delegates through `send_message`. The representative delegates to its connected peer.
- The peer opens one form with single-choice, multiple-choice and free-text questions. Empty selections and accompanying notes are accepted.
- Leta processes a native one-shot reminder while the peer's form remains pending.
- After the answer, the peer requests another human's personal scope. The Leta creator cannot approve; the resource owner accepts.
- The peer reads actual private evidence through Mirage's `/users/<user-id>/` mount. Its public tool result contains the evidence. The creator receives no personal-scope access.
- Results travel peer → representative → parent box → Leta → owner through explicit messaging.
- The resource owner revokes the Leta viewer grant. Accessible-scope discovery reflects the removal. Ordinary archive retains messages; workspace deletion completes.

The extended journey passes in 10.8 seconds with one actual gateway SSE connection carrying root/child events and suffix replay after reconnect. The retained cursor delivers the researcher's read_file tool call without resync or old event IDs. A separate actual Compose journey passes in 1.0 second: creator departure removes resource/home access and workspace deletion still cleans that creator's Leta.

## Defects repaired during acceptance

- The public Workspace scope-access adapter did not accept the existing native typed Leta grantee. It now accepts optional `grantee_kind=user|leta` while retaining the owning permission/lifecycle checks. Contracts and invalid-kind validation were updated.
- LetFS requires UUIDv7 for home scope/node identities. Leta provisioning now allocates UUIDv7 and reuses persisted home identities on retry. Stable box/Leti effect identities remain unchanged.
- The controlled model fixture omitted `created` from SSE chunks. The installed OpenRouter SDK rejects that response. A direct SDK reproduction failed with the missing field and passed after repair; the Compose journey then passed.
- The shared Envoy integration fixture replaced all clusters but omitted the new Leta route's cluster. Adding the Leta backend to that existing fixture repairs startup; the isolation test passes in 1.47 seconds.
- Retrying the create_box tool before its accepted Temporal command saved the home identity could allocate another UUIDv7 and conflict. A real Temporal/SQL regression failed before repair. The tool now uses its existing box ID as the Update ID, joining the accepted creation. Both the focused retry/tool tests and all 11 lifecycle integration tests pass; no additional persistence mechanism was introduced.
- Actual box deletion returned LetFS PRECONDITION_REQUIRED because trash_box_home omitted the node revision. It now stats the persisted home ID and passes its current revision to the existing trash call. The lifecycle fixture enforces that contract: its regression fails before the fix; all 11 lifecycle tests plus the schedule/HITL box-deletion integration pass afterward (12 tests, 33.82 seconds). Missing/already-trashed identity recovery is retained.

## Current regression evidence

- After adding the three complex journeys, `pnpm --dir e2e exec playwright test --project=api` passes **42 tests in 7.3 minutes**, including coordinated populated-state recovery and all six Leta-specific cases. `pnpm check:e2e` passes. Log: `/tmp/openlet-leta-api-42-final.log`. The runner exited and its owned Compose containers were removed by teardown.
- `pnpm contracts:check`, `pnpm check`, `pnpm build`, `pnpm test`, `make test-workflow`, `pnpm check:e2e` and API test discovery pass.
- The first `make test-integration` stopped at the Envoy fixture defect above. Its focused regression passes. The complete rerun passes all 8 tasks in 12m59s, including LetFS race detection and 120 Leta integration tests. Six Python tests require separately launched native Go fixtures; their prior native evidence remains in the owning phase reports.
- All 13 Leta replay tests pass on the current revision, covering the six Workflow types.
- `make test-replay` with fresh full-API histories passes all 4 tasks: Account, Workspace, LetFS and Leta.
- A cold-saver experiment creates real compacted state, adds 10,000 synthetic older checkpoint rows and opens a new saver connection. The latest checkpoint identity/content remain exact. At 10,029 rows and 18,464,768 relation bytes, single-load measurements are 2.51 ms before and 3.06 ms after growth. This is not a months-long soak or a guarantee of fixed storage/query cost.
- Phase 18 retains the completed isolated seven-database backup/restore/resume and native revoked-grant rebuild evidence.

## Remaining gates

- The full API suite passed 38 tests before the final restore/box-deletion assertions. Fresh full-API histories passed all four replay tasks.
- The populated restore extension, including the stale-Redis-cursor resync assertion, passes: pending form, retained box/home/file, native future schedule, exact saver-table checksums, paused root/queued input, exact public compaction summary and answer/resume. The repaired pending-source box deletion also passes through actual LetFS. Targeted Compose run: 4 passed in 3.1 minutes; /tmp/openlet-leta-product-restore-final.log.
- The first targeted verification process was lost during an execution-environment restart; no surviving process or test container was found. It is not counted as a pass; the result above comes from the completed rerun.
- User-requested complex Leta journeys pass: all six cases in `leta.spec.ts` completed in 1.8 minutes (`/tmp/openlet-leta-complex-journeys.log`), including the three additions below, and passed again in the full 42-case run. Only the remote-model fixture gains an explicit call barrier; no production mechanism was added for the tests.
- Reconcile outstanding phase checklists and final lifecycle/compaction/longevity evidence against the actual source and tests.
- Finish the scoped source/docs/contract review. No paid-provider smoke has been run.

No user/lab containers were stopped and no commit or deployment was made. The plan remains in progress.

## Additional complex journeys

- **Revocation during a child model call:** two reads warm the personal-scope mount/cache, a viewer write is denied, then the provider response is held while the resource owner revokes access. The next read fails without returning the private content. Direct child-to-owner messaging fails; the result returns through the box. The original file remains unchanged and accessible-scope discovery removes the grant.
- **Cancelled and replacement forms:** a child question is cancelled, its late answer is rejected, and the cancellation wakes the exact child to create a replacement with all three question types. Leta completes unrelated owner work while that form remains pending. An invalid option leaves the form pending; concurrent identical answers produce one child inbox item, while a changed answer after completion is rejected.
- **Worker outage across an absolute reminder:** a paused root has a one-shot schedule, the worker is stopped, and owner input returns an unacknowledged/pending response without claiming persistence. After restart, retrying the same message ID and the overdue schedule create exactly two inbox items, with the original scheduled timestamp. No model history appears until resume; the owner result and final note each appear once.

These cases use real Account, Workspace, LetFS, Leta, PostgreSQL/checkpointer, Temporal, Redis and SpiceDB. Remote inference is scripted. They found no additional production defect in this run; they do not establish live-model behavior or long-duration stability.

## Additional complex journeys: combined input, graph boundaries and expiration

Added three further Compose journeys in `e2e/tests/api/leta.spec.ts`:

- **Input during a model call:** hold the root's first provider call, admit an owner message twice with the same ID, deliver one root reminder and one child reminder, and let the child return its box result. The root's next model boundary collects the three new root items exactly once in one digest, after the previous tool result, within the same run. The child's schedule input uses the full-content representation.
- **Graph boundaries:** a representative cannot send to a disconnected agent or an agent in another box; a connected nonrepresentative cannot send directly to the parent. Allowed messages travel by peer ID, peer name and representative box ID. Rejected recipients have no inbox/history entries, while the result reaches the owner once through the representative.
- **Expiration during pause:** a child opens a timed question, then the root is paused. The child's reminder and expiration outcome enter its inbox without running the model. A late human answer returns the existing expired decision without accepting its content. Resume collects both inputs in one full-content batch; only the child receives the HITL input and the result returns through the box.

The first run passed eight of nine Leta cases and found a real response-contract defect in the expiration case. `Store.create_request` retains `timeout_seconds` inside its JSON payload to compare retries, while public `AskForm` and `AccessReason` prohibit that internal field. Consequently a timed question made `GET /v1/human-requests` return HTTP 500. A focused real PostgreSQL/Temporal HTTP regression also reproduced the same defect for timed access approval.

The shared `runtime.human.projection` now copies the payload and removes this internal timeout field. Public cards/tools retain `expires_at`; database payloads, retry checks and expiration behavior remain unchanged. No schema/table, Workflow, Activity or infrastructure was added. The existing HTTP regression now exercises timed ask and approval through detail/list/managed-list and answer routes. The late-answer E2E assertion follows the existing store contract: HTTP 200 with the retained `expired` decision, rather than an invented HTTP 409 requirement.

Verification at this checkpoint:

- Before repair: `.local/leta-final-verification/complex-additions.log` records **8 passed, 1 failed**. `.local/leta-final-verification/timed-hitl-before.log` reproduces timed approval response validation failure. The initial attempt to run that focused test omitted Go from PATH and failed during fixture setup; it was rerun with `/usr/local/go/bin` before counting the regression failure.
- After repair: `PATH=/usr/local/go/bin:$PATH uv run --locked --package leta pytest apps/leta/tests/test_http.py apps/leta/tests/test_human_requests_integration.py apps/leta/tests/test_human_tools.py -q --tb=short` passes **13 tests in 71.10 seconds**. Log: `.local/leta-final-verification/timed-hitl-after.log`.
- Leta Ruff checks/format and `pnpm check:e2e` pass. Playwright discovery finds **45 API/recovery tests in 12 files**; this is discovery, not a new full-suite execution claim.
- Final Compose rerun: `PATH=/usr/local/go/bin:$PATH pnpm --dir e2e exec playwright test leta.spec.ts --project=api --no-deps` passes **9 tests in 2.2 minutes**. All six existing Leta journeys and the three additions load the repaired application image. Log: `.local/leta-final-verification/complex-additions-final.log`. The full 42-case pass above predates this repair and the three new cases; the full 45-case suite was not rerun for this bounded change. Remote inference remains scripted; service/storage/authorization boundaries are real.

## Preceding final lifecycle review evidence

The final lifecycle review found that root archive stopped Leti and archived SQL box rows but left `BoxLifecycleWorkflow` coordinators running. Root archive now uses the existing `snapshot.box_ids` to request cancellation of those coordinators after the agent stop barrier. It retains box files and does not invoke box deletion/trash. No new cleanup protocol or Activity was introduced. External cancellation acknowledges the cancellation request; it does not independently prove all box Update handlers have drained.

`test_paused_root_new_box_and_archive_keep_home` verifies the active coordinator reaches CANCELED, retains files and replays the archive-with-box history. The absent/already-closed coordinator regression uses the existing persistent Temporal fixture: the time-skipping Java test server hung at external-cancel initiation for those cases, while the real server completed both. The final lifecycle/native-cleanup slice passes **16 tests in 54.92 seconds**; `.local/leta-final-verification/lifecycle-final.log` records that completed run. The independent lifecycle reviewer reread the final repair and reported no remaining findings within its scope.

Before the timed-HITL repair in this section, the full integration command with `OPENLET_MIRAGE_INTEGRATION=1` and `OPENLET_LETA_HITL_INTEGRATION=1` passed all eight Turbo tasks in 11m58.659s, including native/race fixtures; `.local/leta-final-verification/integration.log` retains the output. Its Leta process loaded source before the coordinator repair, so the 16-case lifecycle slice is the direct evidence for that change. `pnpm check` also passed all eleven tasks; `.local/leta-final-verification/check.log` records it. The timed-HITL repair is covered by the focused 13-test and nine-journey reruns above.
