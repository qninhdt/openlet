---
title: "Phase 4: ZIP Export Workflow and Temporary Delivery"
status: completed
priority: P1
effort: 3d
dependsOn: [phase-03-processing]
---

# Phase 4: ZIP Export Workflow and Temporary Delivery

## Objective

Add bounded normal-folder/multi-selection and explicit-artifact ZIP export using one Rust `ExportArchive` workflow and one Rust archive activity, streaming ZIP/ZIP64 to temporary S3 multipart storage and serving completed results by direct presigned GET.

## Design Evidence And Boundaries

- Final export behavior follows [the ZIP research report](../reports/research-261030-0851-folder-download-zip-export.md). OneDrive/Dropbox/Box support ZIP user journeys, but their public docs do not prove a prebuilt-S3 implementation; Openlet accepts the preparation latency and temporary storage I/O for connection-independent generation and resumable completed downloads.
- Phase 1 owns direct object transfer, signing, multipart, cleanup evidence, and Range descriptors. Phase 2 owns hybrid tree semantics. Phase 3 owns Python document processing. This phase adds no Python work, new service, HTTP-streamed ZIP alternative, or second storage subsystem.
- ZIP can encode file/directory-conflicting names, but normal extracted filesystems cannot represent a regular `report.pdf` and `report.pdf/...` at the same location. The original-only folder rule is a product contract, not a claim that ZIP forbids encoding it.

## Selection And Archive Contract

- [x] A normal single-file download remains Phase 1 inline/direct-object delivery and never starts an export.
- [x] A normal folder or multi-selection export recursively traverses directories. At a file node, include its current original payload and stop; never inject attached generated children. Manually created files and artifacts copied into ordinary directories are ordinary files and are included.
- [x] Explicit source-artifact export starts at the source's published children and produces `<source-name>-artifacts.zip` such as `report.pdf-artifacts.zip`, with paths relative to that child tree. A direct artifact file downloads normally; an artifact directory export includes its readonly subtree.
- [x] Preserve selected directory roots and empty directories. Deduplicate overlapping selections. Resolve duplicate top-level names deterministically without renaming stored nodes. Reject absolute, escaping, device, ambiguous, or otherwise unsafe ZIP relative paths.
- [x] Workspace authorizes the request and letfs creates an export operation/status route. The worker rechecks the delegated filesystem scope, lifecycle, and selection before each attempt; Workspace owns current membership/role authorization when accessing status or issuing/renewing a URL. Do not duplicate workspace membership state in letfs.
- [x] Within an attempt, enumerate bounded metadata with set-based queries and capture each object key or inline node ID/revision plus archive path. Batch inline reads with byte bounds. If captured input changes or disappears, fail the attempt instead of skipping or substituting newer bytes.
- [x] Retries may reauthorize and re-enumerate current inputs. This is not a historical folder snapshot. Source changes may fail a running export; a retry may produce an archive from the then-current tree.

## Workflow, Streaming, And Publication

- [x] Register one Rust `ExportArchive` workflow on the existing Rust worker and schedule one Rust archive activity. No activity per file, per-entry checkpoint, cache, refcount system, stored manifest, or Python dependency.
- [x] Use the existing durable-operation dispatch/recovery pattern with a stable workflow ID and reconciled start acknowledgment. Activity retries have bounded timeouts, heartbeat, cancellation and scratch/stream cleanup; carry only bounded IDs/results in history, never archive bytes, URLs or input lists. Reconcile an already-committed result before rebuilding.
- [x] Before writes, persist the current attempt and candidate key `exports/<operation-id>/<attempt-id>.zip`. A retry always uses a fresh attempt/key.
- [x] Use a maintained ZIP/ZIP64 library and stream archive bytes with bounded memory into Phase 1's native S3 multipart implementation. Do not accumulate the whole archive in RAM or download every source to local disk first.
- [x] Record metadata/attempt state in short DB transactions; perform object reads and multipart writes outside DB locks. Only a current, fully finalized ZIP and completed multipart upload may publish the operation result. A stale attempt cannot replace the winner.
- [x] A failed attempt publishes no descriptor and cleans/abandons its key through existing evidence. Retry rebuilds the whole archive; do not add per-file durable progress.
- [x] After success, a caller polls status and requests a direct GET descriptor. GET renewal and Range retry always target the same export object and never regenerate it.

## Bounds, Expiry, And State

- [x] Enforce independent configurable limits for selected roots, expanded entries, source bytes, output bytes, runtime, and concurrent exports. Reject known excess before generation and output excess while streaming.
- [x] Export objects are not filesystem nodes and do not consume logical quota. They have operational count/byte/runtime/concurrency bounds.
- [x] Default logical retention is 24 hours. Issued GET expiry cannot exceed remaining export lifetime. Provider lifecycle eventually removes `exports/`; do not promise exact deletion at 24 hours.
- [x] Reuse existing operation states where possible and derive queued/ready/expired API meanings from operation/result/expiry facts. If a distinct persisted state is required, change the schema intentionally; current operation state constraints must not be bypassed.
- [x] Reuse maintenance/object-deletion evidence for failed attempts and native incomplete-multipart abort/lifecycle. Never apply export expiry policy to ordinary `objects/`.

## Files

If Phase 1/2 operation/session fields cannot represent export ownership/result/expiry, create the next migration after those phases, currently expected as `services/letfs/migrations/0009_zip_exports.sql`. Confirm the live next number at execution and do not duplicate an earlier migration.

Create:

| File | Purpose |
|---|---|
| `services/letfs/src/fs/exports.rs` | Authorization recheck, selection expansion, safe paths, attempt/result/expiry, descriptor issuance. |
| `services/letfs/src/temporal/export_archive_workflow.rs` | One workflow and one typed Rust archive activity. |
| `tests/e2e/zip_export_test.go` | Public normal/artifact export, status, direct GET, Range and expiry journeys. |

Modify:

| Files | Change |
|---|---|
| `services/letfs/Cargo.toml`, `services/letfs/Cargo.lock` | Add one maintained ZIP/ZIP64 library only if standard/current dependencies do not already provide it. |
| `services/letfs/src/fs/mod.rs`, `services/letfs/src/http/mod.rs` | Export application/status/descriptor routes and bounded metadata enumeration. |
| `services/letfs/src/storage/mod.rs`, `services/letfs/src/fs/uploads.rs`, `services/letfs/src/fs/maintenance.rs` | Reuse native multipart streaming, attempt-owned export keys, abort/cleanup/expiry. |
| `services/letfs/src/main.rs`, `services/letfs/src/temporal/mod.rs`, `services/letfs/src/temporal/lifecycle_workflow.rs` | Register archive workflow/activity and recovery without startup scans. |
| `services/workspace/internal/http/files.go`, `services/workspace/internal/http/server_test.go` | Selection authorization, status and descriptor facade. |
| `contracts/internal/openapi.yaml`, `contracts/public/openapi.yaml` | Selection, explicit artifact export, status/result/expiry and direct descriptor contracts. |
| `services/letfs/tests/integration.rs`, `services/letfs/tests/workflow-replay.rs`, `tests/e2e/history_test.go` | Query bounds, attempt/result/cleanup and actual ExportArchive history replay. |
| `scripts/test-integration.sh`, `scripts/test-workflow.sh`, `scripts/verify-foundation.sh`, `Makefile` | Introduce `zip-export` integration/E2E and `export-archive` replay routes before use; keep comprehensive `all`. |
| `services/letfs/src/config.rs`, `.env.example`, `scripts/configure.py`, `scripts/configure-test.py`, `deploy/compose.yaml`, `deploy/compose.test.yaml` | Export limits/retention, `exports/` lifecycle and incomplete multipart cleanup. |

## Implementation Steps

1. Define export request/status/result/expiry on existing operations; allocate the next migration only for fields the prior schema cannot represent.
2. Implement authorized set-based selection expansion, original-only file stopping, explicit artifact roots, overlap deduplication, empty roots, deterministic collisions, and safe relative names.
3. Register the workflow/activity, persist attempt/key before writes, and stream ZIP/ZIP64 through native multipart with bounded memory and no DB locks around storage I/O.
4. Publish only the current completed attempt, add status and reauthorized direct GET/Range renewal, and clean failed/expired attempts through existing maintenance/provider lifecycle.
5. Add focused integration/E2E/history replay for ordinary/artifact inputs, inline/object bytes, retries, failures, limits, expiration, and query bounds.

## Acceptance Matrix

| Area | Required cases |
|---|---|
| Traversal | Single file bypass, normal folder original-only stop-at-file, manual/copied artifact files, explicit source artifacts, direct artifact file/folder. |
| Names | Selected roots, empty directories, overlapping selection, duplicate top-level names, Unicode/unsafe/traversal paths, deterministic ordering. |
| Inputs | Mixed inline/object bytes, capture revision/key, changed/deleted input failure, retry re-enumeration, no silent skip/substitution. |
| Runtime | ZIP64, bounded memory/query count/bytes/entries/runtime/concurrency, multipart failure/abort, stale attempt, lost publish response. |
| Delivery | Status until fully ready, reauthorized descriptor, same-object Range renewal, no regeneration, expiry-bounded URLs, eventual 24h lifecycle. |

Planned commands after this phase adds routing:

```sh
make test-integration SERVICE=letfs TEST=zip-export
make test-e2e TEST=zip-export
make test-workflow TEST=export-archive
```

None of these selectors exists in the baseline scripts; do not claim them before implementation. Actual binary history generation is required, not a replay test that skips when history is absent.

## Todo

- [x] Add export operation/status/result/expiry without inventing unnecessary state.
- [x] Implement bounded original-only and explicit-artifact selection enumeration.
- [x] Stream ZIP/ZIP64 to attempt-owned native multipart and publish only the winner.
- [x] Add reauthorized direct GET/Range delivery and 24h eventual cleanup.
- [x] Add focused ZIP integration/E2E/replay and query-bound coverage.

## Risks And Rollback

Archive path safety, output amplification, and stale input substitution are the highest risks; fail closed, enforce independent bounds, and verify captured identities. Rollback stops new export admission, lets active activities/capabilities reconcile, aborts multipart where known, retains attempt evidence until ambiguity clears, and leaves ordinary file/artifact downloads unaffected.
