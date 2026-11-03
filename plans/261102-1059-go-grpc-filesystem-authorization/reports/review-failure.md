# Failure Mode / Flow Trace Review

## Scope and coverage

Reviewed `plan.md`, `architecture-contract.md`, `verification-matrix.md`, and all seven phase files against current source paths and control flow. I sampled at least 15 relevant claims per phase where that many claims were source-verifiable, tracing PostgreSQL commits, Temporal dispatch/continuation, filesystem provisioning, runtime staging, timeout handling, and recovery boundaries. No application tests, builds, lint, type checks, containers, or provider checks were run.

The fixed product decisions remain intact: PostgreSQL is canonical, Temporal projects to SpiceDB, no Access service or membership-status/workspace-wide lag gate is added, public success waits for projection, old rights during pending projection are accepted, byte storage remains signed S3 plus inline PostgreSQL, and old Rust history compatibility is not required after a backed-up development reset.

The already-steered authoring corrections for `packages/go`, the Phase 4 baseline-file label/command blocks, the Phase 5 snapshot wording, and the destructive Qdrant cleanup gate are intentionally not repeated here.

## Findings

### Critical — letfs-owned filesystem bindings have no durable projection implementation path

- **Plan location:** `architecture-contract.md:43`, `architecture-contract.md:45`, `architecture-contract.md:106`, `phase-03-workspace-authorization-and-durable-projection.md:73`, `phase-04-go-filesystem-core-and-storage.md:77`, `phase-04-go-filesystem-core-and-storage.md:78`, `phase-06-direct-filesystem-api-and-proxy-removal.md:48`.
- **Failure:** The architecture makes letfs the canonical owner of filesystem-to-resource bindings and requires every owner to persist projection intents and acknowledgments with its canonical facts. Phase 3 defers whole-letfs rebuild, but Phases 4-6 assign no letfs projection-intent schema, ordered projector/reconciler, graph acknowledgment wait, deletion tombstone/head update, or rebuild snapshot reader. Phase 4 only ports binding/provisioning state; Phase 6 assumes the graph binding exists when direct authorization begins.
- **Failure scenario:** Workspace provisioning commits the filesystem and returns its IDs, but no filesystem-to-workspace relationship reaches SpiceDB. After Phase 6 cutover, fully-consistent direct file checks deny legitimate members. An implementer who fills the gap with a synchronous `WriteRelationships` call creates the dual-write hole the plan is designed to avoid: a crash after PostgreSQL commit permanently loses the binding, while a crash during deletion can leave stale inherited access.
- **Source evidence:** The current filesystem table has lifecycle/storage fields but no typed resource binding, projection revision, immutable intent, epoch, or acknowledgment (`apps/letfs/migrations/0001_initial.sql:55`). Current provisioning accepts `workspace_id` but reduces it to a `provision_key` (`apps/letfs/src/fs/provisioning.rs:35`, `apps/letfs/src/fs/provisioning.rs:66`) and commits the filesystem through `ensure_filesystem` with no authorization projection (`apps/letfs/src/fs/provisioning.rs:94`, `apps/letfs/src/fs/mod.rs:99`). Workspace then treats the returned IDs as the durable mapping (`apps/workspace/internal/temporal/workflows.go:80`, `apps/workspace/internal/temporal/workflows.go:88`).
- **Fix:** Add letfs-owned typed binding plus aggregate revision/intent/ack/epoch storage to Phase 4. Assign an ordered letfs projector, post-commit reconciliation, deletion fencing/tombstones, and rebuild enumeration to Phase 4 or 5. Provisioning completion and Phase 6 readiness must wait for the binding version's graph acknowledgment, and the real CAS/epoch/rebuild scenarios must cover these letfs tuples.

### High — Phase 5 destroys the runtime that it promises to keep available until Phase 6

- **Plan location:** `phase-05-go-workflows-ingest-and-search.md:14`, `phase-05-go-workflows-ingest-and-search.md:55`, `phase-05-go-workflows-ingest-and-search.md:76`, `phase-05-go-workflows-ingest-and-search.md:85`, `phase-05-go-workflows-ingest-and-search.md:86`, `phase-05-go-workflows-ingest-and-search.md:99`, `phase-05-go-workflows-ingest-and-search.md:104`, `phase-05-go-workflows-ingest-and-search.md:116`.
- **Failure:** Phase 5 completely moves and converts `apps/letfs-processing` to the gRPC-only `apps/letfs-ingest`, while explicitly preserving both Compose files and claiming the pre-cutover runtime remains usable. The preserved Compose configurations still build the deleted old Dockerfile and start the old HTTP worker contract against Rust letfs.
- **Failure scenario:** After Phase 5, a clean `docker compose build/up` or the existing E2E environment fails because `apps/letfs-processing/Dockerfile` no longer exists. Keeping a stale image only hides the break: the source tree and lock/workspace now describe `letfs-ingest`, while Compose still starts `processor-*` with `LETFS_URL` and the old HTTP/token contract. Phase 6 therefore begins from a stack that cannot be rebuilt or rolled back using the committed Phase 5 state.
- **Source evidence:** Dev Compose builds `apps/letfs-processing/Dockerfile`, names the image `openlet-processor`, and supplies `LETFS_URL` to `processor-cpu/io` (`infra/compose/dev.yaml:222`, `infra/compose/dev.yaml:225`, `infra/compose/dev.yaml:228`, `infra/compose/dev.yaml:233`, `infra/compose/dev.yaml:273`). E2E Compose has the same old build path and contract (`infra/compose/e2e.yaml:231`, `infra/compose/e2e.yaml:233`, `infra/compose/e2e.yaml:238`, `infra/compose/e2e.yaml:252`). The uv workspace also points only to the path Phase 5 removes (`pyproject.toml:2`).
- **Fix:** Preserve a runnable old processor tree/image contract until the coordinated Phase 6 switch, while developing the renamed gRPC worker as an isolated parallel target; then switch Compose, locks/consumers, and remove the old target atomically in Phase 6. Alternatively move the destructive rename/conversion itself into Phase 6. Do not accept reliance on a previously cached image as a staging contract.

### Medium — the superseding-revision acknowledgment rule is referenced but never defined

- **Plan location:** `architecture-contract.md:116`, `architecture-contract.md:124`, `architecture-contract.md:126`, `phase-01-contracts-and-proof-gates.md:47`, `phase-03-workspace-authorization-and-durable-projection.md:63`, `phase-03-workspace-authorization-and-durable-projection.md:69`.
- **Failure:** Phase 3 says superseding revisions resolve older waiters according to a Phase 1 “explicit contract,” but Phase 1 only says to specify that contract later. The plan never states whether a waiter for version `N` succeeds when the monotonic SQL acknowledgment is already `N+1`, what proof is required that `N` was applied in order, or which resource/revision is returned when `N` has already been superseded.
- **Failure scenario:** Mutation A commits workspace revision 10 and waits. Mutation B commits revision 11 and projects through the same ordered stream before A observes the acknowledgment. An equality-based waiter (`ack == 10`) now times out forever even though synchronized state is newer; a loose `ack >= 10` waiter can return success safely only if the projector proves gap-free ordered application and the response contract defines whether it returns A's committed representation or current revision 11. Different handlers can otherwise implement incompatible timeout/retry semantics.
- **Source evidence:** Current workspace mutations serialize and increment one workspace revision (`apps/workspace/internal/workspace/store.go:286`, `apps/workspace/internal/workspace/store.go:324`, `apps/workspace/internal/workspace/store.go:328`; member changes do likewise at `apps/workspace/internal/workspace/store.go:365`, `apps/workspace/internal/workspace/store.go:388`). The HTTP handler currently returns the just-committed representation directly (`apps/workspace/internal/http/workspaces.go:222`, `apps/workspace/internal/http/workspaces.go:228`), so adding a post-commit wait creates this observable branch and requires a single defined rule.
- **Fix:** Make Phase 1 record the invariant and wire contract explicitly: ordered, gap-free projection allows `ack_version >= requested_version` to satisfy the waiter; equality is not required. Define the response/error representation when a newer revision supersedes the requested one, and add a real concurrent test where `N+1` is acknowledged before the `N` waiter reads the acknowledgment. Apply the same helper/contract to every projected mutation.

## Unresolved questions

- Which phase owns the letfs binding projector and makes its acknowledgment a provisioning and Phase 6 cutover gate?
- Will Phase 5 keep the old processor runtime reproducible, or will the rename/conversion move into the coordinated Phase 6 switch?
- What exact acknowledgment predicate and response revision are authoritative for a superseded mutation waiter?

Status: DONE_WITH_CONCERNS

Summary: Three material plan defects found: a missing durable letfs projection path, a Phase 5 rename that breaks the promised pre-cutover runtime, and an undefined superseding-version waiter contract.

Concerns/Blockers: Direct filesystem cutover is blocked until letfs-owned binding projection is assigned and proven; Phase 5 is not a reproducible staging boundary as currently written.
