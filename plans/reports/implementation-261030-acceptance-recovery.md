# Acceptance and recovery evidence

Plan: [Direct Storage, Artifact Processing, and ZIP Export](../261029-1624-artifact-file-processing/plan.md), Phase 5. Date: 2026-10-30.

## Outcome and acceptance audit

| Contract | Evidence |
|---|---|
| Direct user/processor storage | Earlier [transport](implementation-261030-direct-storage.md) and [processing](implementation-261030-processing.md) reports; full integration and E2E below. Bounded arbitrary binary inline, immutable single PUT/native multipart, commit-time quota, independent uploads and direct caller/storage byte transfers. |
| Provider/browser/download | Actual R2 smoke and Chromium passed, including signed headers, exact size/MD5, conditional replay/race, native multipart, private reads, CORS and GET/Range. Current-image `make test-provider` also exited zero. |
| Hybrid tree and lifecycle | [Hybrid report](implementation-261030-hybrid-artifacts.md), five artifact integration cases: scoped aliases/cwd/IDs, readonly descendants/writable copies, source/ancestor lifecycle, overwrite invalidation, >64-node forests, snapshot ordering and exact accounting. |
| Actual parsing | Four real PDF/DOCX/PPTX/XLSX journeys; tables remain Markdown, sheets/regions become CSV, empty sheets and isolated/formula cells preserved. Additional embedded DOCX image extracted through direct storage with identical decoded pixels and a Markdown reference. Image/text/legacy Office inputs bypass processing and retain exact originals. |
| Atomic processing and recovery | Twenty inline outputs plus an object output under one job slot; stale generations/invocations, atomic quota rejection and committed-result reconciliation. Actual Python SIGKILL/new generation succeeds once. Three failed GET attempts exhaust the workflow; maintenance records failure, no children appear, original bytes remain unchanged. |
| ZIP | [ZIP report](implementation-261030-zip-export.md): originals only for normal folders; explicit artifacts; roots/empty directories/overlap/collisions; mixed storage; ZIP64/native multipart; stale/change/limit failure; expiry/Range/cleanup. Windows superscript COM/LPT reserved names now rejected too. |
| Query bounds | Multi-part signing reads one upload row for one or three parts. ZIP 1/65 files uses 1/2 inline statements and exactly three tree statements. Processing completion uses one set-based output read and set-based node/data/publication writes; forest lifecycle remains bounded batches, exercised beyond 64 nodes. |
| Recovery snapshot | Successful coordinated local drill restores five databases, storage, source/artifact/ZIP exact bytes, Range, quota and histories. Restored infra starts with applications/Python stopped and Schedule paused; read verification follows explicit application resume. |

## Verification completed

- `make test-integration SERVICE=all TEST=all`: User and Workspace passed; **16 letfs tests passed**, real Testcontainers PostgreSQL/SeaweedFS/Temporal and browser boundary.
- `make test-e2e TEST=all`: passed direct transport, identity/authorization, filesystem/lifecycle, four parsers, ZIP, Python kill/retry and Rust/Temporal/PostgreSQL restart journeys.
- Extended `make test-e2e TEST=processing`: passed all four formats, embedded image and three bypass cases.
- `make test-e2e TEST=processing-recovery`: passed actual worker kill/retry and all-three-attempt exhaustion.
- Full Python suite: **13 passed** with offline models. Two upstream Docling/Pydantic deprecation warnings remain.
- `make verify`: passed after the processing additions, Windows-name fix and scoped export retry repair. Standalone contract validation checked **2230 captured DTOs** after the final full E2E run; focused suites capture their own responses.
- `make backup-restore-drill`: passed in fresh `openlet-test-backup-*` source and isolated restore projects. Existing test volumes preserved.
- Current-image `make test-provider` and separate native R2/Chromium smoke: passed.
- Relative Markdown file links in root README, docs and active plan: verified.

Local logs remain ignored under `.local/`: `final-integration-bounded.log`, `final-e2e-all.log`, `final-processing-extended.log`, `final-processing-recovery-exhausted.log`, `final-python-tests.log`, `final-verify-completion.log`, `final-verify-scoped-retry.log`, `final-backup-drill-isolated.log`, `final-make-provider-current.log`, `final-r2-smoke.log`, `zip-device-names.log`, `zip-retry-regression-before.log`, `zip-retry-regression-after.log`, `final-e2e-scoped-retry.log`, `final-workflow-scoped-retry.log`.

## Operational changes

Backup fences the public gateway and local direct-storage proxy, pauses maintenance, stops Python/application/Temporal execution, rejects unfinished work, and stops storage before capture. Format-2 snapshots retain checksums and exact image IDs including bundled models. Restore requires fresh isolated volumes and available matching images; it starts only infrastructure with no public ports or application dispatch. No volume is deleted by these scripts.

The real R2 development bucket preserves its existing seven-day incomplete-multipart cleanup. Readback confirms an eight-day `exports/` deletion rule, longer than maximum seven-day logical retention plus runtime. No age expiry is installed for ordinary `objects/`. Actual eight-day elapsed deletion has not been observed.

## Independent review and regression repair

The [independent ZIP/recovery review](review-261030-zip-recovery.md) found that `SOURCE_CHANGED` was incorrectly terminal, preventing accepted retry/re-enumeration. A real source-GET barrier regression failed on the original code with `failed/SOURCE_CHANGED`. Export-specific classification now leaves this operation running and permits a fresh attempt. Copy/lifecycle retain their original error mapper; heartbeat accepts the explicit mapper at each of its four callers. The reviewer accepted this scoped correction with no remaining high/medium findings. The final current-revision `make test-e2e TEST=all` passed, including existing copy source-change/move/trash races, the generation-two ZIP regression and both processing recovery cases. Comprehensive `make test-workflow` passed both Go suites and four Rust replay tests, covering actual `ExportArchiveRetry`, `ProcessFileRecovery` and `ProcessFileExhausted` histories alongside all previous histories. Final `make verify` passed; a post-E2E contract check validated 2230 captured DTOs.

## Failures and limitations

An initial unrestricted-parallel integration run lacked Playwright in the selected Python environment and observed one conditional-provider race failure. The focused provider run and full run with standard `RUST_TEST_THREADS=2` passed using the existing browser virtual environment. Assertions were not weakened; the original transient race root cause was not conclusively established.

**NOT RUN: coordinated R2 object-plus-five-database disaster recovery.** Local stopped-storage recovery does not prove external capability drain or external provider restore. This remains a production release gate. Actual Clerk smoke was not repeated because this plan does not change Clerk behavior. No production deployment, Git commit or push was performed.
