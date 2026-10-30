# Hybrid Artifact Plan Review — Assumption Destroyer

## Scope

- Reviewed the current `plan.md` and all three phase files against the existing resolver, copy/deletion, storage-builder, workflow-test, E2E, and backup/restore surfaces.
- Checked caller counts, phase ownership, selector feasibility, direct-child publication/copy semantics, and remnants of the retired detached-root design.
- Did not edit plans or production code and did not run builds, tests, installs, containers, or external checks.

## Findings

### High — Phase 2 requires a real `ProcessFile` history but owns no executable journey that starts it

- **Plan location:** Phase 2 assigns workflow history generation to `scripts/test-workflow.sh`, `services/letfs/tests/workflow-replay.rs`, and `tests/e2e/history_test.go` at `plans/261029-1624-artifact-file-processing/phase-02-processing.md:110`. It requires the actual pinned Rust/Python bridge at line 117, runs `make test-workflow TEST=process-file` at line 135, and says that selector must generate/use actual cross-language history at line 138. The public processing journey and E2E selector are deferred to Phase 3 at `phase-03-acceptance.md:59-60` and `phase-03-acceptance.md:70`.
- **Flaw:** None of the Phase 2-owned test surfaces initiates a `ProcessFile` execution. The history helper only serializes a workflow after another test supplies its ID; the workflow script only validates existing files and invokes replay/tests. Therefore the phase cannot satisfy its own claim that the focused selector generates a real cross-language history.
- **Concrete failure condition:** A clean Phase 2 workspace runs `make test-workflow TEST=process-file`. Either the selector follows the current model and fails because `ProcessFile.bin`/JSON do not exist, or it only replays a hand-created fixture and never proves that the Rust workflow scheduled the Python worker on the real queue. The first executable public journey capable of producing that history does not exist until Phase 3.
- **Source evidence:** `scripts/test-workflow.sh:14-19` checks pre-existing history files and then runs Go/Rust replay; it does not start Compose or execute a workflow. `tests/e2e/history_test.go:16-60` defines only `saveHistory`, and its line 30 waits on an already-known workflow ID. Existing callers that create histories live in concrete E2E journeys such as `tests/e2e/storage_test.go:97` and `tests/e2e/lifecycle_test.go:137-144`.
- **Smallest fix:** Move a minimal real processing journey plus its `verify-foundation.sh`/Compose routing into Phase 2, sufficient to upload one fixture, await processing, save `ProcessFile` history, and replay it. Phase 3 can retain the broader public, recovery, and race matrix. Alternatively assign an equivalent dedicated history generator to Phase 2 explicitly; changing only the replay selector is insufficient.

### High — Phase 3 requires a runtime pause invariant but does not own the runtime files that enforce it

- **Plan location:** Phase 3 requires backup to stop admission and drain processor capabilities at `plans/261029-1624-artifact-file-processing/phase-03-acceptance.md:36`. Its implementation step 5 at line 83 correctly states that pausing the maintenance schedule is insufficient and requires an admission/dispatch pause gate checked by post-commit starts, maintenance recovery, processor `prepare`, and `complete`, enforced before letfs starts during restore. However its file list at lines 64-75 assigns only integration/E2E tests, provider smoke, selectors, backup scripts, and docs; it does not include the production configuration, HTTP, processing, maintenance, upload/start, Compose, or configure owners needed to implement that gate.
- **Flaw:** The required safety property is not a shell-only operation. Every admission path must read one authoritative paused state, including code paths that run after the backup script has stopped or restarted individual services. The phase has no declared owner for that state or for the four enforcement points it names.
- **Concrete failure condition:** Restore starts letfs while maintenance is paused but a restored pending intent exists. Without a runtime gate, startup/maintenance or a concurrent processor request can dispatch or complete work against restored storage before validation finishes, so the snapshot is no longer quiescent even though the scripts report maintenance paused.
- **Source evidence:** Current restore starts storage and then `issuer user workspace letfs envoy` directly at `scripts/restore-local.sh:49-51`. Current backup only pauses the Temporal maintenance schedule and stops services at `scripts/backup-local.sh:14-18`. Processing admission will be owned by the Phase 2 runtime surfaces (`phase-02-processing.md:102-109`), including `http/mod.rs`, `config.rs`, `uploads.rs`, `maintenance.rs`, Temporal helpers, Compose, and configuration scripts, but none is assigned to Phase 3.
- **Smallest fix:** Define and implement the authoritative pause gate in Phase 2's runtime/config contract, including post-finalize start, maintenance recovery, processor `prepare`, and `complete`; then let Phase 3 own only script orchestration and restore assertions. If implementation remains in Phase 3, add those exact production/config/deploy owners to its file list and acceptance matrix.

## Contract Verdict

The direct-child design is internally coherent and the previous detached-root/pointer contract is retired from the active phase instructions. Caller counts for `paths::resolve`, `Session::resolve`, and `storage::build` match current source, and the earlier storage-consumer and real-XLSX-fixture phase gaps are corrected. The two findings above still prevent the declared phase gates from being independently executable and safe.

## Unresolved Questions

- None requiring product input. Both findings are plan ownership/order corrections within the approved design.

Status: DONE

Summary: The hybrid contract is feasible, but Phase 2 lacks an owned producer for its required real cross-language history, and Phase 3 lacks the runtime owners for its mandatory backup/restore pause gate.

Skipped checks: No build, test, install, container, Docling, Temporal, provider, or backup execution was performed by instruction. The plan's linked `validation-261030-0737-hybrid-artifact-plan.md` was not present during this review, so its claims could not be inspected.

## Resolution Update

The active plan was corrected after the review above. Both findings are resolved:

- **Cross-language history ownership:** Phase 2 now creates the executable minimal journey in `tests/e2e/processing_test.go` (`phase-02-processing.md:98`), owns the `processing` route through `scripts/verify-foundation.sh` (`phase-02-processing.md:113`), and explicitly runs the tiny-PDF journey before saving and replaying real `ProcessFile` history (`phase-02-processing.md:120`, `phase-02-processing.md:138-139`). Phase 3 extends the same journey rather than introducing its first producer (`phase-03-acceptance.md:66`).
- **Restore pause contract:** The unsupported extra runtime pause-gate requirement was removed. Phase 3 now relies on the actual dispatch model: keep public mutation admission closed, the Python worker stopped, and scheduled maintenance paused; there is no startup scan, so restored pending work cannot dispatch until explicit resume (`phase-03-acceptance.md:84`). This matches current ownership, where workflow starts occur from finalize or scheduled maintenance rather than service startup.
- **Python command paths:** Ruff and pytest commands now explicitly target `services/letfs/processor` because `uv --project` selects the environment without changing the working directory (`phase-02-processing.md:127-134`).

**Updated verdict:** No remaining assumption-destroyer finding in the narrowly re-read sections. The two High findings above are historical and should not block the corrected plan.

Status: DONE

Summary: Narrow re-review confirms the corrected phase ownership, restore behavior, and Python command scoping are coherent with current source and tooling surfaces.
