---
title: "Direct Storage, Artifact Processing, and ZIP Export"
description: "Move file bytes to caller-selected inline or direct object transport, publish processed artifacts as read-only children, and build resumable ZIP exports."
status: completed
priority: P1
effort: 24d
branch: main
tags: [feature, backend, database, api, infra]
blockedBy: []
blocks: []
created: 2026-10-29
updated: 2026-10-30
---

# Direct Storage, Artifact Processing, and ZIP Export

## Outcome

Openlet stores caller-selected bounded inline bytes or transfers object bytes directly between callers and private S3/R2. The same upload application logic serves ordinary files and processor outputs. Eligible documents run through one Rust `ProcessFile` workflow and one Python `process_file` activity, then publish a complete read-only child tree. Folder and multi-selection downloads run through one Rust `ExportArchive` workflow and one archive activity, publish a temporary ZIP object, and download it directly from storage.

## Accepted Contract

- The client and Python worker choose `inline` or `object`. letfs enforces the inline byte limit and normal authorization, scope, quota, protocol, and file-size bounds; it never sniffs UTF-8/NUL, reclassifies, falls back, or reads S3 back to relocate bytes. Inline `bytea` may be binary. Existing text-edit APIs remain string contracts.
- Object bytes never relay through Envoy, Workspace, or letfs HTTP. Workspace retains metadata authorization; letfs owns session state, completion, publication, and abort. The existing full-file object receiver is removed.
- Upload is `prepare -> transfer -> complete`. A persisted UUIDv7 upload/session owns immutable `objects/<quota-bucket-id>/<upload-id>`. The same idempotency key and parameters reuse it; changed parameters conflict. Overwrites always use a fresh key and preserve the old file until atomic publication.
- Single PUT signs conditional create, exact size, and `Content-MD5`; multipart uses native provider create/parts/complete/abort with bounded signing and frozen completion intent. MD5 is transfer integrity only. No physical staging-to-final copy, mandatory S3 readback SHA-256, custom SigV4, per-part ledger, quota reservation, or per-upload workflow.
- Completion verifies provider evidence outside locks, then uses the existing bucket -> filesystem -> upload/operation transaction to recheck destination/revision/liveness, enforce hard commit-time quota, publish once, queue replaced bytes, invalidate artifact children, and create new processing intent atomically.
- Object downloads return a presigned GET descriptor or redirect; inline downloads return bounded bytes. URL issuance and renewal reauthorize, pin revision/content, preserve Range and safe headers, and default to a proposed five-minute GET lifetime. Issued URLs remain bearer capabilities until expiry.
- A source remains `kind=file`, keeps its own payload, and may own read-only artifact children through `nodes.parent_id`. Normal path, raw ID, and scoped root `@<uuid>` access share authorization and lifecycle rules. Copy/trash/restore/purge/invalidation/accounting invariants from the accepted hybrid design remain authoritative.
- One admitted processing job may create more than sixteen bounded outputs without consuming one ordinary outstanding-job slot per output. Unpublished outputs are upload records, not nodes. One current-attempt/source-identity/aggregate-quota transaction publishes the full child tree.
- Normal folder ZIPs contain current original file payloads only and stop at file nodes. Explicit artifact export starts at the source's published children and names `report.pdf-artifacts.zip`; direct artifact files download normally and artifact directories export their subtree.
- ZIP generation uses one `ExportArchive` workflow and one Rust archive activity. It streams ZIP/ZIP64 into native multipart at `exports/<operation>/<attempt>.zip`, publishes only a fully completed current attempt, supports Range/retry after completion, and retains results for 24 hours by default with eventual lifecycle deletion.
- Reuse maintenance and `object_deletions`, preserve ambiguous-write evidence until stale capabilities reconcile, abort incomplete multipart natively, and never age-expire ordinary `objects/`. Storage control endpoints may differ from caller-reachable signing endpoints; signed hostnames are never rewritten.
- No frontend, new SDK project, billing, AI/embeddings, Redis, gateway, notification dependency, new service, archive cache, manifest/run history, per-entry workflow, or historical folder snapshot is added.

## Data Flow

1. Clients authorize through Workspace; Python uses operation-scoped letfs APIs. Each caller chooses inline/object and prepares a persisted upload session.
2. Inline bytes cross the bounded API; object bytes transfer directly to the immutable S3 key by single PUT or multipart.
3. letfs reconciles provider evidence, then atomically publishes metadata/quota/result and optional processing intent.
4. `ProcessFile` gives Python scoped source/output capabilities; Python converts locally and completes bounded output uploads; letfs atomically publishes the winning child tree.
5. `ExportArchive` validates delegated filesystem scope/lifecycle, enumerates bounded current inputs, and streams a temporary ZIP to storage. Workspace reauthorizes access to the winning result before letfs issues a direct GET descriptor.

## Phases

| # | Phase | Status | Depends on | Effort |
|---|---|---|---|---|
| 1 | [Direct storage transport and publication](./phase-01-direct-storage.md) | Complete | None | 6d |
| 2 | [Hybrid artifacts, lifecycle, and durable intent](./phase-02-artifacts.md) | Complete | Phase 1 | 5d |
| 3 | [Processing runtime and atomic child publication](./phase-03-processing.md) | Complete | Phase 2 | 6d |
| 4 | [ZIP export workflow and temporary delivery](./phase-04-zip-export.md) | Complete | Phase 3 | 3d |
| 5 | [Acceptance, recovery, operations, and docs](./phase-05-acceptance.md) | Complete | Phase 4 | 4d |

Phases are sequential because storage publication is the shared prerequisite for artifact lifecycle, Python output transfer, ZIP input/output, and final recovery coverage. Phase migration ownership is ordered: Phase 1 takes the next available migration (currently `0007`), Phase 2 the next after it (expected `0008`), and Phase 4 only takes a later migration if its operation fields cannot reuse the resulting schema (expected `0009`). Re-resolve the next number at execution; never let phases own the same filename.

## Acceptance Criteria

- [x] Direct user and Python transfers support bounded binary inline, conditional single PUT, native multipart, idempotent reconciliation, hard commit-time quota, independent multi-file results, and no object bytes on Workspace/letfs HTTP.
- [x] Provider/browser tests prove signed headers, size/checksum/conditional semantics, CORS/reachable host, lost-response reconciliation, multipart resume/abort, and Range renewal on pinned SeaweedFS and R2 without unchecked fallback.
- [x] Original bytes and read-only child artifacts remain correct across path/ID aliases, copy, overwrite, move, trash/restore, purge, deletion, stale attempts, quota refusal, and more than sixteen outputs.
- [x] Normal and explicit-artifact ZIPs preserve safe deterministic paths, roots/empty directories, inline/object bytes, original-only traversal, retries, expiry, and failure instead of omission/substitution.
- [x] Focused selectors are introduced before use, comprehensive `all` routes include them, actual `ProcessFile` and `ExportArchive` histories replay, metadata queries remain bounded, and backup/restore cannot dispatch until explicit resume.

## Release, Compatibility, And Rollback

- This intentionally replaces the existing object-body upload/download contract. Update internal/public APIs, callers, existing SHA-256 receipt assertions, config generators, all three `storage::build` consumers, Compose/Testcontainers, scripts, docs, and examples together. Preserve node revision, inline range, text-edit, authorization, and error contracts where not explicitly changed.
- Before migration, back up. Roll back by closing upload/export/processing admission, stopping workers, allowing issued capabilities and remote outcomes to reconcile, aborting multipart, draining deletion evidence, and retaining read/delete support for already-published nodes. Revert schema only after no new-format active sessions/exports remain; remove artifact descendants through lifecycle code before reverting hybrid semantics.
- Recheck disk before Python/model/container work; after authorized cleanup, Phase 1 observed about 152 GiB free. R2 direct-transfer/browser checks passed; coordinated R2 object-plus-five-database recovery remains an external production gate. Unknown external checks are `NOT RUN`.

## Validation And Handoff

Phase 1 implementation and verification are recorded in [the direct storage implementation report](../reports/implementation-261030-direct-storage.md). Phase 2 is verified in [the hybrid artifact implementation report](../reports/implementation-261030-hybrid-artifacts.md). Phase 3 is verified in [the processing implementation report](../reports/implementation-261030-processing.md), including four real format journeys and their actual workflow histories. Phase 4 is verified in [the ZIP export implementation report](../reports/implementation-261030-zip-export.md). Phase 5 acceptance and recovery are verified in [the final implementation report](../reports/implementation-261030-acceptance-recovery.md) and [independent review](../reports/review-261030-zip-recovery.md). External R2 coordinated recovery remains NOT RUN as the production release gate. Phase checklists are the execution status used by `ak plan status`. The prior report `../reports/validation-261030-0737-hybrid-artifact-plan.md` validates the superseded three-phase scope and is historical only. Planning validation belongs in [the storage/processing validation report](../reports/validation-261030-0903-storage-processing-plan.md); it does not describe current implementation progress.

## Unresolved Questions

None for product design. Exact provider enforcement, ZIP library behavior, parser/model identity, and numeric concurrency/resource limits are implementation gates.

<!-- slug: artifact-file-processing -->
