# Security Adversary / Fact-Checker Review

## Scope and fact-check coverage

Reviewed `plan.md`, `architecture-contract.md`, `verification-matrix.md`, and all seven phase documents against the current source. I checked at least 15 relevant current-state/path/behavior claims per phase where the phase made that many verifiable claims. Target-state requirements were checked for cross-phase completeness rather than treated as implemented facts. Application tests, builds, lint, and type checks were intentionally not run.

The accepted decisions remain unchanged: direct official SDK clients, no Access/proxy service, PostgreSQL as canonical authority with Temporal projection, the dedicated SpiceDB database on the existing PostgreSQL instance, backed-up development reset, gRPC application RPCs, unchanged signed-S3/inline-PostgreSQL byte paths, no quota/billing/AI-agent expansion, and the `letfs-ingest` rename.

## Findings

### Critical — letfs-owned authorization projection has no implementation phase

- **Plan location:** `architecture-contract.md:43`, `architecture-contract.md:45`, `architecture-contract.md:106`, `phase-03-workspace-authorization-and-durable-projection.md:73`, `phase-04-go-filesystem-core-and-storage.md:54`, `phase-06-direct-filesystem-api-and-proxy-removal.md:48`.
- **Flaw:** The architecture assigns filesystem-to-resource bindings and filesystem authorization facts to letfs and requires every canonical owner to commit durable projection intents/acknowledgments. Phase 3 explicitly defers whole-letfs rebuild, but Phases 4-6 never assign files, schema work, a projector workflow/activity, reconciliation, acknowledgments, or deletion/rebuild behavior for the letfs-owned tuples. Phase 4 ports binding/provisioning and performs checks; Phase 6 exposes generic binding, but neither phase implements the required durable PostgreSQL-to-SpiceDB writer.
- **Failure scenario:** After direct-route cutover, a newly provisioned filesystem has canonical binding state but no graph relationship. Fully-consistent filesystem admission fails closed for legitimate members. If implementation fills the gap with a synchronous relationship write, a crash between PostgreSQL and SpiceDB leaves a permanent missing/stale binding and violates the plan's own canonical/projection recovery contract. Deletion can likewise leave an inherited grant reachable through a stale filesystem binding.
- **Source evidence:** The current filesystem table has only `id`, bucket, `provision_key`, root, lifecycle/count fields and no typed resource binding or projection revision/intent/ack state (`apps/letfs/migrations/0001_initial.sql:55`). Current provisioning accepts a workspace ID but reduces it to a string provision key (`apps/letfs/src/fs/provisioning.rs:35`, `apps/letfs/src/fs/provisioning.rs:66`) and creates the filesystem without any authorization projection (`apps/letfs/src/fs/provisioning.rs:94`, `apps/letfs/src/fs/mod.rs:99`).
- **Fix within accepted scope:** Add letfs-owned binding columns plus immutable projection intent/head/epoch/ack storage to Phase 4, and add the ordered letfs projector/reconciler, deletion fencing, and rebuild snapshot path to Phase 5 (or a clearly named Phase 4 sub-gate). Make provisioning completion and Phase 6 cutover wait for the binding version's graph acknowledgment. Extend the existing real CAS/epoch and recovery scenarios to letfs-owned tuples before direct APIs are enabled.

### High — the ProcessFile parity contract reverses current failure ordering

- **Plan location:** `phase-05-go-workflows-ingest-and-search.md:20`, `phase-05-go-workflows-ingest-and-search.md:38`, `phase-05-go-workflows-ingest-and-search.md:90`.
- **Flaw:** The phase repeatedly describes `index_file` as “always-run.” In the current workflow, parse and enrichment are awaited with error propagation; indexing is reached only after every required preceding activity succeeds. “Always-run” is true only in the sense that indexing is the final required stage when earlier required stages succeed or are not required.
- **Failure scenario:** A literal Go port invokes indexing in a `defer`/finally path after terminal parse or enrichment failure. That can publish or reconcile index state for content whose processing pipeline failed, creating stale search visibility and breaking the generation/publication invariants the same phase is meant to preserve.
- **Source evidence:** `process_file` returns on error at `apps/letfs/src/temporal/process_file_workflow.rs:48`; `enrich_file` returns on error at `apps/letfs/src/temporal/process_file_workflow.rs:52`; only then is `index_file` scheduled at `apps/letfs/src/temporal/process_file_workflow.rs:59`. The Python activity also records terminal enrichment failure before returning an error (`apps/letfs-processing/src/openlet_processor/activity.py:162`).
- **Fix within accepted scope:** Replace “always-run” with “final stage after all required prior stages succeed; still runs when parse/enrichment are not required.” Add a workflow test proving parse/enrichment failure does not schedule indexing, plus the existing index-only path test.

### Medium — Phase 2 creates the Phase 5 rename destination before the atomic move

- **Plan location:** `phase-02-shared-go-contracts-and-infrastructure.md:43`, `phase-02-shared-go-contracts-and-infrastructure.md:64`, `phase-05-go-workflows-ingest-and-search.md:76`, `phase-05-go-workflows-ingest-and-search.md:99`.
- **Flaw:** Phase 2 creates generated Python output under `apps/letfs-ingest/src/openlet_api/`, while Phase 5 later requires moving the existing `apps/letfs-processing/` directory atomically to `apps/letfs-ingest/`. The destination is therefore already a competing partial application tree.
- **Failure scenario:** The Phase 5 move fails because the destination exists, or an implementation merges/overwrites trees and loses the generated package or old application metadata. A stale partial package can then pass an import-only proof while the built wheel or worker still resolves old modules, weakening the intended cross-language authentication test.
- **Source evidence:** The active uv workspace points only to the current application path (`pyproject.toml:2`), whose distribution is `openlet-processor` (`apps/letfs-processing/pyproject.toml:2`) and whose wheel currently includes only `src/openlet_processor` (`apps/letfs-processing/pyproject.toml:46`). No current `apps/letfs-ingest` application exists.
- **Fix within accepted scope:** In Phase 2, generate/import-test Python stubs in an isolated temporary/codegen output or under the current app without packaging them as the final tree. Create `apps/letfs-ingest/src/openlet_api/` only as part of the Phase 5 atomic rename, then build the final wheel containing both namespaces.

## Accepted residual risk

The plan correctly states that OSS SpiceDB credentials are broad and that tuple ownership is a convention, not a credential-enforced boundary (`architecture-contract.md:150`, `phase-02-shared-go-contracts-and-infrastructure.md:126`). Current services also combine public servers and Temporal workers in one process (`apps/account/cmd/server/main.go:95`, `apps/account/cmd/server/main.go:106`, `apps/workspace/cmd/server/main.go:94`, `apps/workspace/cmd/server/main.go:106`; Rust letfs does the same at `apps/letfs/src/main.rs:77` and `apps/letfs/src/main.rs:103`). Under the accepted trust model, compromise of a credential-holding backend can forge graph state; the plan must continue to describe this as a backend-boundary assumption and must not claim per-domain enforcement.

## Unresolved questions

- Which phase owns the missing letfs authorization projector and makes its acknowledgment a provisioning/cutover gate?

Status: DONE_WITH_CONCERNS

Summary: Three material plan defects found: one critical missing letfs projection owner/path, one high-risk workflow parity reversal, and one medium phase-ordering collision in the ingest rename.

Concerns/Blockers: Phase 6 should not enable direct filesystem admission until the letfs-owned graph binding projection and rebuild path are explicitly assigned and proven.
