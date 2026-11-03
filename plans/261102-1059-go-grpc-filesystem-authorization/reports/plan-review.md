# Plan review and validation record

Status: plan authoring reviewed; application implementation remains pending. This record concerns planning evidence, not implementation acceptance.

## Scope and prior decisions

HOLD SCOPE. Reuse the completed brainstorm and user confirmations: PostgreSQL canonical, direct SpiceDB SDK, no Access service, self-host on existing PostgreSQL with a dedicated DB/user, no member status/workspace-wide role-change gate, signed S3/inline PG byte paths, all application RPC gRPC, direct letfs API, full Rust removal, `letfs-ingest` naming, backed-up dev reset, and AI implementation afterward.

Plan mode: deep migration planning. The user explicitly requested detailed phases in English, so every phase is detailed rather than leaving future phases as outlines. Current source inventories and official research are reused. No new product interview is needed for already accepted decisions.

## Review disposition

Four source-grounded reviews covered [assumptions](review-assumptions.md), [failure/recovery](review-failure.md), [scope/consumers](review-scope.md) and [security](review-security.md). Their original text is retained as review history; latest accepted design and the [boundary review](letfs-boundary-review.md) govern execution.

| Deduplicated finding | Resolution |
|---|---|
| Missing durable inheritance writer | Original recommendation placed the writer in letfs. The latest decisions put references, native relationship synchronization and rebuild in Workspace; SQL intents and acknowledgment framework are superseded. Phases 3/6 and architecture define publication gaps; letfs has no mapping/projector. |
| Ingest rename breaks preserved runtime and CI/recovery | Phase 5 stages activity/client adoption in the current app using the shared Python RPC wheel, with old default entrypoints retained. Phase 6 atomically renames app/module/distribution, CI, Compose, secrets, queues and recovery/restart controls; shared Python codegen output stays fixed in `packages/python/src/openlet_api/`. No future directory is pre-created. |
| Phase 1 proof artifacts scheduled too late | Phase 1 owns minimal Buf/output/shared-wheel and current-app dependency metadata plus real proof tests; Phase 2 extends/integrates them. |
| ProcessFile failure ordering reversed | Indexing follows successful required prior stages; parse/enrichment failure schedules no index. Separate index-only path remains. |
| Superseding acknowledgment undefined | The former high-water/waiter design is superseded by the November 2 correction. Normal synchronized success follows graph completion; ambiguous outcomes retain existing resource/revision semantics and stale-write safety tests. |
| Final rename scan incomplete | Phase 7 includes exact old service/env/secret/queue ledger strings, Makefile, packages and recovery/restart references. Intentional domain processing terminology remains. |
| Destructive Qdrant cleanup locking | Preserve the current bounded lifecycle lock, exact filters, timeout and tombstones during the port, verified with a real new-index race. The mandatory lock-removal optimization was removed in the scope audit below. |
| letfs business boundary and duplicate provisioning identity | Latest user decision removes all provision keys and letfs business mapping/projector. Stable caller-persisted IDs, idempotency receipts and local tombstones replace provisioning keys. Generic lifecycle contracts, mount context, bucket permissions and credentials are explicit across phases. |
| Python generated code coupled to ingest | User-approved follow-up moves the sole generated Python namespace to `packages/python/src/openlet_api/` in an independent `openlet-python` distribution. Phases 1/2 own wheel proof, uv/Turbo/Docker/CI integration; Phase 5 consumes it; Phase 6 keeps output stable through rename. Future Python services can consume client/server types without app imports; no Leti implementation or speculative Python framework. |

All corrections preserve requested scope. No product question remains open. Versions, graph fencing, generation and transport mappings remain implementation proof gates, not claims that prototypes already passed.

## Validation log

CLI format validation and parse have passed during authoring; the final whole-plan sweep is recorded after propagation. Source/path/consumer verification uses the linked scout/reviewer evidence and the later targeted boundary audit. No invented claim-count total is asserted. No application tests, schema migrations, containers, provider checks or benchmarks have been run by the planner. No live task management tool is available; phase checklists remain the durable tracking surface. No background processes were started for this planning work.

Whole-plan checks passed after ownership propagation: CLI validates and parses seven pending phases; all sixteen plan Markdown files have valid local links, balanced fences, no trailing whitespace and fewer than 800 lines; phase dependencies contain no forward/cyclic references. The Account/Workspace and letfs/ingest cycles were source-reviewed with the dispositions in the boundary report. Dependency versions, graph CAS/epoch and actual transport remain Phase 1 implementation proof gates.

### Whole-plan consistency sweep

- Re-read the index, architecture, verification matrix and all seven phase files after updates.
- Checked user deltas: Turborepo layout/codegen paths, ingest cutover timing, idempotency without provision keys, Workspace-owned inheritance, generic lifecycle/mount/bucket contracts and Account bootstrap ordering.
- Earlier brainstorm/scout target suggestions are explicitly marked superseded; current-source evidence and original reviewer findings remain historical records.
- Unresolved authoring contradictions: none found in the reviewed target.
- Ready for Cook at Phase 1. All implementation checkboxes remain pending; no proof gate or application test is represented as already passed.

### Shared Python package follow-up

User approved a shared Python RPC package for ingest and future Python services. Updated the index, architecture, verification matrix and Phases 1/2/5/6/7: sole output `packages/python/src/openlet_api/`, independent `openlet-python` wheel, uv workspace dependency, `@openlet/python` Turbo tasks, Docker/CI inputs and stable codegen through the ingest rename. Phase 1 includes minimal Docker/CI fixes if its proof dependency changes existing builds; Phase 2 completes integration. Handwritten Python helpers require a concrete common need; no Leti implementation was added.

Validation after propagation: `ak plan validate` passed; `ak plan parse` reported seven pending phases, 65 remaining phase tasks and zero completed. A whole-plan check covered all sixteen Markdown files for local links, balanced fences, trailing whitespace, the 800-line limit, dependency ordering and obsolete app-local generated-output instructions in current execution documents; no errors. `git diff --check` passed; the explicit content check also covered these untracked plan files. Existing adversarial reports remain historical; this follow-up received a targeted consistency review, not another four-agent review. No codegen, wheel build, application test, infrastructure or database change ran during this documentation update.

## November 2 authorization simplification — supersedes earlier projection design

The user explicitly rejected SQL permission catalogs and the application head/intent/ack/epoch framework. Role/action capabilities belong to repository policy loaded directly into SpiceDB. Existing PostgreSQL user/workspace/membership-role/storage records remain canonical; owner Temporal activities synchronize their derived relationships and services call native action/resource checks. Existing business revisions/If-Match, idempotency and lifecycle constraints remain.

Updated the index, architecture, all affected phase instructions, verification matrix and action/tuple ownership contract. Phase 3 removes the four catalog tables, two sync-ledger tables and unused proof implementation before proceeding. Earlier CAS/waiter/epoch experiments and reviewer recommendations remain historical evidence and are not runtime requirements. The saved-response acknowledgment framework is superseded; atomic relationship changes, explicit possible-commit failures, fail-closed checks and writer-fenced rebuild parity remain. The behavior that an older delayed/retried write cannot restore access after synchronized revoke/transfer success is retained. Phase 3 must prove its native owner-specific implementation; Temporal serialization or current SQL rereads alone do not fence a remote write already in flight.

Implementation remains incomplete. Account gRPC work and its earlier real test evidence are retained. No database or deployment was changed by this plan update. No new interview is needed: these changes propagate the user's explicit correction and instruction to continue.

## Whole-plan overengineering audit after authorization correction

Re-read the index, architecture, verification matrix and all seven phases against the accepted scope and current source. One additional unnecessary requirement was found: Phase 5 mandated moving destructive Qdrant cleanup outside SQL locks. Current `apps/letfs/src/fs/indexing.rs:133` intentionally serializes its final serving-state check and deletion with lifecycle changes, uses a five-second delete timeout, bounds the sweep and retains tombstones. No measured contention or requested feature requires replacing that mechanism during the Go port. Phase 5 now preserves it and retains the real cleanup/new-index race test. Object cleanup already commits its claim before S3 I/O (`apps/letfs/src/fs/maintenance.rs:62`), so its existing behavior remains.

Also corrected an unjustified weakening introduced by the previous plan edit: final convergence alone does not prove that an older in-flight write cannot restore revoked access after synchronized success. Restored that behavioral gate without mandating the rejected SQL/graph framework. Its Phase 3 implementation proof is still pending. No other evidence-backed overengineering was identified; requested capabilities and existing safety/behavior parity remain in scope. This audit changes documentation only, not code, databases or deployment.

Validation: `ak plan validate` and `ak plan parse` pass; execution remains 19/65 tasks and 2/7 phases complete. All 18 plan Markdown files pass local-link, fence and whitespace checks; `git diff --check` passes. Updated the linked boundary report to remove obsolete intent/ack and policy-ownership instructions. The existing policy initializer, its tests and bootstrap image are explicit Phase 3 file owners. No application tests ran for these documentation changes; the revised synchronization safety proof remains required implementation work.
