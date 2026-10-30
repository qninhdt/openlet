> Historical snapshot, superseded on 2026-10-30 by the user-approved [direct-child artifact plan](../261029-1624-artifact-file-processing/plan.md). Its schema, path, ownership and pending-review statements describe the previous draft; do not execute them. Use the current plan and [validation report](./validation-261030-0737-hybrid-artifact-plan.md). General runtime/source evidence remains useful where the current plan retains it.

# Artifact File Processing Plan Review — Assumption Destroyer

## Scope

- Reviewed `plan.md`, all three phase files, and both supporting research reports.
- Verified load-bearing claims against the current Rust storage, deletion, migration, Makefile, and test-script surfaces.
- Did not run builds, tests, installs, containers, or Docling; this is a document/source contract review only.

## Findings

### High — Phase 2 changes `storage::build` but defers two required consumers to Phase 3

- **Plan location:** `plans/261029-1624-artifact-file-processing/phase-02-processing.md:104` changes `storage::build` from the current object-store return into a struct containing both the dyn store and typed signer. The Phase 2 file list includes `storage/mod.rs` and `main.rs` at lines 87 and 90, but not `services/letfs/tests/integration.rs` or `services/letfs/src/storage/provider_smoke.rs`; those are assigned to Phase 3 at `phase-03-acceptance.md:70` and `phase-03-acceptance.md:72`.
- **Flaw:** The return-type change is a public Rust call-contract change inside the crate. Phase 2 is described as independently verifiable and runs `make verify` (`phase-02-processing.md:115-120`), but it does not own all callers that must be adapted in the same phase.
- **Concrete failure condition:** After Phase 2 makes `build` return a composite storage value, `App.storage` construction in the integration harness and method calls in provider smoke still expect `Arc<dyn ObjectStore>`. `cargo clippy --all-targets` from `make verify` compiles both targets and fails before Phase 3 begins.
- **Code evidence:** Current callers are `services/letfs/src/main.rs:43`, `services/letfs/tests/integration.rs:192`, and `services/letfs/src/storage/provider_smoke.rs:10`. The latter immediately calls object-store methods on the result at `provider_smoke.rs:16`, while `App.storage` remains `Arc<dyn ObjectStore>` at `services/letfs/src/http/mod.rs:18`. `Makefile:48` runs Clippy with `--all-targets`.
- **Smallest fix:** Move the mechanical caller adaptations for `integration.rs` and `provider_smoke.rs` into Phase 2's modified-file list. Keep Phase 3 responsible only for adding presigned provider assertions, not for repairing the Phase 2 type migration.

### High — The exact XLSX contract depends on data Docling is not yet proven to expose, but the first real fixture is deferred to Phase 3

- **Plan location:** Phase 2 requires empty sheet folders, singleton cells, and uncovered standalone cells grouped into deterministic CSV regions at `phase-02-processing.md:47`, implements the exporter at line 77, and claims exact-layout success at line 154. Actual XLSX fixtures and end-to-end assertions are not introduced until `phase-03-acceptance.md:26-28` and `phase-03-acceptance.md:59`.
- **Flaw:** The plan treats the XLSX export algorithm as implementable from the typed Docling stream before proving that the pinned Docling result retains every required sheet and isolated cell. The supporting research verifies only `iterate_items`, sheet groups, and `TableItem.export_to_dataframe`; it explicitly says isolated non-table cells must not be dropped, without identifying a verified source for them.
- **Concrete failure condition:** If Docling omits an empty sheet or does not emit isolated cells as typed items/tables, Phase 2's exporter cannot reconstruct the accepted tree from `result.document`. The failure appears only in Phase 3, after the package lock, image, activity, exporter, and unit-test structure have already been built around the incomplete representation; satisfying the contract may require changing the dependency set or conversion boundary.
- **Evidence:** `plans/reports/research-261029-2317-processor-runtime.md:93-103` lists the verified Docling APIs. Its XLSX row at line 109 states the additional isolated-cell requirement but supplies no verified API for retrieving those cells, and line 178 names the “XLSX isolated-cell fallback” as still requiring implementation-time acceptance. The same report requires real format fixtures at lines 143-150.
- **Smallest fix:** Move the tiny XLSX fixture and a pinned Docling compatibility test into the start of Phase 2, before locking the exporter design. The gate must prove sheet enumeration, empty sheets, singleton cells, and isolated regions are observable; if not, Phase 2 must record the minimal non-AI local parsing fallback before implementing the exporter. Keep the broader cross-language/E2E matrix in Phase 3.

### High — The ownership FK can block artifact-root deletion because pointer teardown is not part of the traversal contract

- **Plan location:** Phase 1 adds the `nodes.artifact_dir_id` same-filesystem FK at `phase-01-artifacts.md:26`, says purge/filesystem deletion traverse the ownership edge at line 37, and tells deletion batches to insert ownership edges before removal at line 88. It explicitly clears the pointer for overwrite at line 30, but does not require pointer clearing for source/ancestor purge or filesystem deletion.
- **Flaw:** The proposed FK points from the source row to the detached artifact root. Existing deletion discovers leaves only through `parent_id`, then deletes selected node IDs directly. Adding the artifact root to `deletion_items` does not by itself remove the referencing `artifact_dir_id`, define an `ON DELETE` action, or guarantee that the source and root are deleted in the same SQL statement.
- **Concrete failure condition:** During a bounded purge or filesystem-deletion batch, an artifact root becomes a `parent_id` leaf and is selected while its live source row remains outside that batch. PostgreSQL rejects `DELETE FROM nodes` because the source still references the root. The operation then retries/fails without making progress, leaving charged detached nodes and preventing filesystem deletion from completing.
- **Code evidence:** The current parent FK is immediate (`services/letfs/migrations/0001_foundation.sql:33`), demonstrating that node relationship FKs are not automatically deferred or cascaded. Leaf selection checks only `NOT EXISTS ... c.parent_id=n.id` at `services/letfs/src/fs/deletion.rs:166`; deletion is a direct `DELETE FROM nodes ... id=ANY($2)` at line 141; batches are capped at 64 at line 166. The proposed research DDL has no delete action at `plans/reports/research-261029-2317-artifact-integration.md:75-81`.
- **Smallest fix:** Make pointer teardown an explicit Phase 1 invariant: before an artifact root is eligible for `deletion::remove`, clear every owning `artifact_dir_id` in the same transaction (including source/ancestor purge and filesystem deletion), or define and test an intentional FK delete action that provides the same result. Add one bounded multi-batch case where the source and artifact root cannot land in the same delete statement.

## Contract Verdict

The accepted product scope is coherent, but the plan is not execution-ready across phase boundaries. Phase 2 currently cannot satisfy its own Rust verification gate, the exact XLSX layout rests on an unverified data-availability assumption, and Phase 1 does not close the FK contract needed by its deletion claims. These are plan corrections; none requires a new filesystem, manifest/index/history, content revision, extra Temporal activity, or AI feature.

## Unresolved Questions

- Which pinned Docling representation, if any, exposes empty XLSX sheets and isolated non-table cells? The current research does not establish it.
- Should artifact-root deletion use explicit pointer clearing or an FK delete action? The plan must choose one invariant before migration implementation.

Status: DONE

Summary: Three high-severity assumption failures were verified: incomplete Phase 2 storage API migration ownership, deferred proof of the exact XLSX export contract, and missing FK-safe artifact deletion ordering.

Concerns/Blockers: No runtime checks were executed by instruction; Docling feasibility remains document-evidence-only until the Phase 2 compatibility gate is added.
