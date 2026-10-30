# Hybrid artifact implementation evidence

Plan: [Direct Storage, Artifact Processing, and ZIP Export](../261029-1624-artifact-file-processing/plan.md), Phase 2. Date: 2026-10-30.

## Delivered

Files retain their original payload and can contain generated children through existing `parent_id` edges. Path, raw ID, cwd and root `@<canonical UUID>` aliases share live-filesystem resolution. Strict file ancestors make generated descendants read only; copying them outside a file makes the copy writable. Ordinary writes still require actual directory destinations. Migration `0008_artifact_processing.sql` refuses pre-existing root alias collisions.

Upload publication now atomically invalidates previous children and persists eligible PDF/DOCX/XLSX/PPTX processing intent. Rename/move preserve intent. Replacement fences it; trash permanently fails unfinished intent even after restore. Invalidated forests use existing deletion checkpoints and maintenance, preserving succeeded publishers and exact quota accounting.

Copy captures a file's payload identity and immediate child roots, including an empty snapshot. Copy/purge fast paths require childless files. Durable copy, trash/restore, purge and filesystem deletion handle payload plus descendants. The viewer-authorized artifact-status facade, internal/public contracts, integration selector and owning docs were updated together.

## Verification

- Final `make test-integration SERVICE=letfs TEST=all`: **10 passed**, including all three artifact tests and both latest regressions (container syntax on files and alias migration collision refusal). Testcontainers ran real PostgreSQL, SeaweedFS and Temporal; browser checks also passed.
- Artifact coverage includes readonly mutation/destination guards, alias/raw ID/cwd scoping, writable copies, empty snapshot races, stale source copies, >64-node forests, invalidation, source/ancestor lifecycle, complete filesystem deletion and quota/node accounting.
- `make verify`: passed before the final test-only repairs, including **1,338 captured response DTOs**. Final Rust clippy across all targets and repository formatting checks passed after those repairs.
- Full `make test-e2e TEST=all`: passed for the unchanged product implementation, including restart, isolation/accounting and port checks.
- Rust library suite: **10 passed**. Workspace HTTP unit tests passed.

Evidence: `.local/artifacts-integration-all-final.log`, `.local/artifacts-clippy-final.log`, `.local/artifacts-verify.log`, `.local/artifacts-e2e-all.log`. The test harness cleaned up its containers. Scoped simplification of the new artifact tests completed without changing their contracts.

## Remaining gates

Processing intents remain pending until Phase 3 registers dispatch and the Python worker. No parser execution or atomic processor-output publication is claimed here. ZIP export, actual ProcessFile/ExportArchive history replay, independent final review and coordinated external recovery remain pending in Phases 3–5.

The repository still has no Git HEAD. The pre-artifact source archive is `.local/implementation-baseline/pre-artifacts.tar.gz`; preserve it for review and rollback comparison.
