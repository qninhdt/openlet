# Hybrid Artifact Plan Validation

Date: 2026-10-30, Asia/Ho_Chi_Minh. Scope: planning only.

Status: the approved hybrid design replaces the previous execution design in all four plan files. Implementation remains pending. No product question or plan blocker remains after source/document review; parser, SDK and provider execution gates remain unrun.

Plan: [Artifact File Processing](../261029-1624-artifact-file-processing/plan.md).

## Authorization And Contract

The user approved the explained direct-child model and instructed: update the plan and remove the previous design. This authorizes the architecture replacement and corresponding caller, lifecycle, acceptance and phase-order corrections. This action does not implement or deploy the feature.

- A source remains a file with original bytes in `file_data`; artifacts are children through `nodes.parent_id`. No additional root/container, ownership pointer, node kind or per-file filesystem.
- Source/child paths and a root-scoped `@<uuid>` alias replace the previous virtual namespaces. Real root names matching the alias pattern are reserved with collision preflight; nested names are ordinary names.
- Strict file ancestry determines readonly output for ID, normal/alias/cwd paths and mutation destinations. The original source remains writable.
- Publication preserves source revision/ETag/payload timestamps; ordinary byte/metadata mutations retain current behavior. Copy captures payload plus immediate children set-wise under the existing lock, including an empty snapshot.
- Every byte replacement atomically detaches/checkpoints the old child forest and supersedes its intent; succeeded publishers retain accounting state. Only eligible successful uploads create new processing intent.
- Trash terminally fences unpublished work with `SOURCE_TRASHED`; restore reports failed without restarting it. Already-published children survive with their source. Find affected sources through bounded active-operation ancestry, not an N+1 node walk.
- One Rust workflow invokes one Python activity. Python uses letfs plus scoped URLs, has no DB/long-lived S3 credentials, and creates no output nodes before Rust's winning publication transaction.
- Keep agreed layouts, same quota bucket, readonly artifacts and copy-out behavior. AI, billing, legacy Office, standalone image OCR, document manifests/indexes and run history remain outside scope.

## Changed Files And Historical Records

Rewrote the index and all three phases in the existing plan directory; no duplicate plan. The index is 71 lines. Implementation statuses and checkboxes remain pending.

Six previous artifact research/review reports remain historical evidence, each with a superseded banner. Their earlier schema/path/pending-approval statements are not current instructions. The obsolete ownership-FK correction is unnecessary with parent edges; normal parent-before-child insertion and child-before-parent removal remain required.

## Independent Review

| Lens | Current report | Resolution |
|---|---|---|
| Security | [Hybrid security](./review-261030-0737-hybrid-security.md) | No new concrete blocker; alias scoping, strict-ancestor readonly, destination guards and mandatory provider length enforcement checked. |
| Assumptions | [Hybrid assumptions](./review-261030-0737-hybrid-assumptions.md) | Both findings corrected and reread: Phase 2 owns an executable history producer; restore keeps worker/admission off and scheduled maintenance paused without an undefined runtime pause gate. |
| Failure modes | [Hybrid failures](./review-261030-0737-hybrid-failures.md) | Both timing contracts clarified and reread: derived children do not bump source revision; trash permanently fences unpublished processing. |

Phase 2 creates the minimal real PDF E2E/history producer and route; Phase 3 extends that journey. All storage consumers adapt together. Real fixtures and Python tooling are Phase 2 gates, scoped to the processor directory because `uv --project` does not change working directory.

No new sandbox service or output registry. The supervised Docling child retains the worker's process trust; process supervision is not a security isolation guarantee.

Follow-up on 2026-10-30: the user explicitly removed the proposed separate model inventory file. Phase 2 now packages pinned model versions/revisions in the worker image and uses its deployment digest; no custom model inventory or startup hash validator is planned. The removed path never existed as an implemented file. The supervised-child design remains ordinary process management, not a custom Docling sandbox.

## Source Verification

Standard tier: Fact Checker plus Contract Verifier. Thirty baseline source anchors were rechecked, ten per phase; all found. These checks verify existing surfaces, not future runtime behavior.

| Phase | Ten verified baseline surfaces |
|---|---|
| 1 | `0001_foundation.sql:20` nodes; `0002_file_core.sql:1` file data; `paths.rs:88` resolver; `nodes.rs:13` Node; `uploads.rs:27` target; `copy.rs:7` inline copy; `trash.rs:110` purge; `deletion.rs:151` batches; `maintenance.rs:89` object cleanup; Workspace `files.go:220` routing. Rust files are under `services/letfs/src/fs/`, migrations under `services/letfs/migrations/`. |
| 2 | `uploads.rs:188` finalize; `0004_uploads.sql:12` SHA; `0005_durable_copy.sql:1` operations; `temporal/mod.rs:3` queue; `temporal/lifecycle_workflow.rs:133` maintenance; `temporal/copy_workflow.rs:94` scheduling; `main.rs:67` registration; `config.rs:19` config; `storage/mod.rs:3` builder; `scripts/configure.py:19` generation. Rust files are under `services/letfs/src/`, uploads under `fs/`. |
| 3 | `services/letfs/tests/integration.rs:11` Testcontainers; `services/letfs/tests/workflow-replay.rs:10` replay; `tests/e2e/history_test.go:16` helper; `scripts/verify-foundation.sh:5` selectors; `scripts/test-workflow.sh:16` history prerequisite; `scripts/backup-local.sh:16` stop; `scripts/restore-local.sh:10` isolation; `scripts/verify-contracts.py:12` validator; `deploy/compose.test.yaml:4` S3; `Makefile:46` verify. |

Additional hybrid boundaries read directly: directory-only resolver traversal (`paths.rs:109-114`), list guard (`nodes.rs:249`), write-parent guard (`nodes.rs:284`), file-leaf copy (`copy.rs:23`) and directory enumeration (`copy.rs:263`), leaf purge (`trash.rs:126`), directory-only durable purge (`deletion.rs:92`), parent-edge leaf deletion (`deletion.rs:166`). These are changes to implement; current code does not already support the hybrid contract.

Caller inventory:

- `paths::resolve`: three direct sites, `nodes.rs:81`, `nodes.rs:235`, `copy.rs:455`.
- `Session::resolve`: sixteen wrapper sites: four nodes, two uploads, three trash, six copy, one content route; enumerated in Phase 1.
- `storage::build`: three consumers, `services/letfs/src/main.rs:43`, `services/letfs/tests/integration.rs:192`, `services/letfs/src/storage/provider_smoke.rs:10`; all assigned Phase 2.

## Whole-Plan Consistency Sweep

Reread index and all phases after propagation. Checked ten decision deltas across outcome, requirements, steps, file ownership, commands, acceptance and rollback:

1. Parent edges replace the previous ownership representation.
2. Source paths and root ID alias replace previous namespaces.
3. File content/list/trailing-path and reserved-name behavior are explicit.
4. Copy/purge fast paths require no children; durable copy includes payload and child snapshot.
5. Every replacement invalidates old output; detached forests stay charged until removal.
6. Attempt ordering, separate supersession and no prepublication nodes preserve accounting.
7. Source revision and permanent trash-cancellation contracts are consistent.
8. Phase 2 owns all consumers/tooling/fixtures and the actual cross-language history producer.
9. Local backup is distinct from existing external R2 release requirements.
10. Rollback removes artifact descendants before reverting hybrid semantics.

No retired ownership field, old namespace name or detached artifact-root instruction remains in the four active plan files. Historical evidence remains clearly superseded. No unresolved contradiction found.

## Mechanical Validation And Task State

- `ak plan validate`: passed, no structural errors.
- `ak plan parse`: three phases, sixty tasks, zero completed; `ak plan reindex --apply` and `ak plan use` completed successfully for the existing plan.
- Four plan files: local links checked after this report was created.
- Three sequential phases with no dependency cycle. Sixty phase checkboxes and five acceptance checkboxes remain unchecked.
- No exposed live task-management API; Markdown is the durable task source. Reindex/active-plan selection do not constitute implementation progress.
- No task-owned background service, container or test runner started; unrelated work preserved.
- Recorded the decision in the [local journal](../journals/2026-10-30-openlet-hybrid-artifact-plan-update.md); no external publication.

## Execution Limits And Handoff

No lint, compilation, unit/integration/parser/Temporal/provider/backup test or package/model installation was performed. Approximately 661 MiB was free during planning; provision/recheck storage before execution. Parser/model compatibility, cross-language JSON and signed-length enforcement remain execution gates.

The plan is ready as an implementation specification, not proof of runtime or production readiness. When implementation is requested, use `/ak:cook /home/qninh/projects/openlet/plans/261029-1624-artifact-file-processing/plan.md`. This update does not start implementation.

Unresolved product questions: none.
