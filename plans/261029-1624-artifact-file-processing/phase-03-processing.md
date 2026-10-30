---
title: "Phase 3: Processing Runtime and Atomic Child Publication"
status: completed
priority: P1
effort: 6d
dependsOn: [phase-02-artifacts]
---

# Phase 3: Processing Runtime and Atomic Child Publication

## Objective

Register one Rust `ProcessFile` workflow and one Python `process_file` activity, run pinned offline Docling under supervision, transfer source/output through Phase 1's shared inline/direct-object subsystem, and atomically publish one complete read-only child tree.

## Baseline Evidence And Consumers

- letfs pins Rust Temporal `1.1.0` and `object_store 0.14.2` (`services/letfs/Cargo.toml:1`); Compose pins Temporal server `1.32.1` (`deploy/compose.yaml:46`).
- The installed SDK supports typed external-language activities through `ActivityDefinition`; use the pinned typed API, not an invented by-name call.
- Phase 1 updates `storage::build` and its three consumers. This phase consumes that shared signer/store; it does not create a processor-specific S3 client or transport.
- Existing maintenance performs finite work through Rust lifecycle activities (`services/letfs/src/temporal/lifecycle_workflow.rs:133`). Extend dispatch/reconciliation there rather than adding a per-upload or cleanup workflow graph.
- Phase 2 persists current source intent, attempt fencing, source identity, supersession, and invalidation. Dispatch is enabled only when the workflow and Python consumer are registered.

## Workflow And Attempt Contract

- [x] Register one Rust `ProcessFile` workflow on the existing letfs workflow queue. It schedules exactly one Python `process_file` activity on `openlet-letfs-processing`; activity retries are attempts of that scheduled activity. Python registers no workflow.
- [x] Use bounded serde/JSON IDs and primitives across languages. Keep bytes, presigned URLs, secrets, output descriptors, and growing arrays out of Temporal history and heartbeats.
- [x] Stable workflow ID derives from the persisted processing operation/finalized source upload. Commit source plus intent first, then start post-commit; a lost start response is reconciled by stable ID and never rolls back the source upload.
- [x] Use bounded activity retry/timeouts/heartbeat/cancellation. Do not add workflow retry/reset behavior that would reset attempt generation without a protocol.
- [x] Prepare carries Temporal activity attempt number and an invocation UUID. Under the operation lock, higher generation supersedes, equal generation must match UUID, and lower generation fails stale. Every source/output/complete/abort request matches the active tuple and nonsuperseded source identity.
- [x] Reconcile committed success before repeating work. A source overwrite/trash permanently fences the old attempt; preserve the old succeeded operation for accounting while supersession prevents resurrection.

## Python Worker And Shared Transfer

- [x] Package the activity-only worker under `services/letfs/processor` with locked Python dependencies and pretrained model revisions in the image. Deploy by image digest. No runtime model download, DB connection, Workspace credential, or long-lived S3 key.
- [x] The async parent owns HTTP/Temporal, heartbeat, deadlines, cancellation, scratch cleanup, and TERM-then-KILL supervision of a local-file Docling child. Start with one conversion/container and explicit input/pages/pixels/tables/images/output-count/output-bytes/runtime/CPU/memory/scratch bounds.
- [x] Use non-root container hardening, descriptor/environment hygiene, disabled remote enrichment/URL input, and redacted capabilities/content. Do not claim the child is a separate security sandbox or add another service.
- [x] Source access is the captured immutable object key via scoped presigned GET or bounded inline bytes. Renewal stays bound to the same source identity; the worker never switches to a newer node revision.
- [x] Output preparation uses the exact Phase 1 application logic. Python chooses `inline` for bounded output bytes or `object`; object mode receives fresh immutable `objects/<quota-bucket-id>/<upload-id>` keys and uses single PUT/multipart by size. No staging/final key, physical copy, mandatory S3 SHA-256 readback, or processor-only fallback.
- [x] Output upload records bind operation, attempt, relative path, expected size/checksum, and terminal result. Same attempt/path/parameters is idempotent; changed parameters conflict. A new attempt gets independent ownership. Explicit empty directories travel as bounded completion metadata, not zero-byte uploads or a manifest.
- [x] The whole artifact set is one admitted processing job with output count and aggregate-byte limits. Individual output sessions do not consume one of the current sixteen ordinary outstanding-job slots apiece.

## Atomic Publication

After all output sessions are provider-ready, one short bucket -> filesystem -> operation transaction:

1. Rechecks the current nonsuperseded operation/attempt, live source, captured object key or bounded inline SHA-256, source depth, and full output ownership.
2. Validates safe relative paths, duplicates, file/directory collisions, expected output set, counts, sizes, and aggregate hard quota once.
3. Inserts all readonly directories/files parent-before-child under `source.id`, retains source `kind=file` and own payload, and does not bump source revision/ETag or payload timestamps.
4. Publishes all winning output upload ownership and the operation result once. A lost response returns the saved result; a failed transaction exposes no partial child tree.

Quota failure leaves the source intact, publishes no children, and cleans candidates through existing evidence. Old invalidated output stays charged only until its checkpointed deletion. Copy never inherits processing intent. Trash during conversion remains terminal after restore; already-published children follow ordinary source lifecycle.

## Export Layout Contract

| Input | Children under source |
|---|---|
| PDF/DOCX | Flat numbered main-section Markdown; nested headings/tables inline; preamble joins first section; `content.md` fallback only if no sections; optional `images/`. |
| PPTX | Flat numbered slide Markdown in order; tables inline; optional `images/`. |
| XLSX | Numbered named sheet directories; ordered CSV per table plus deterministic positional CSV for uncovered cells; optional sheet `images/`; preserve empty sheets and singleton/isolated cells. |

Examples: `report.pdf/001-introduction.md`, `slides.pptx/001-overview.md`, `budget.xlsx/001-sales/001.csv`. Sanitize names deterministically and use relative image links. Do not emit duplicate full-document Markdown, indexes, manifests, document JSON, run directories, AI/embeddings, text chunks, standalone image OCR, or legacy Office conversion.

Create tiny real PDF/DOCX/PPTX/XLSX fixtures and independently derived expected outputs. Run them through the pinned parser. If XLSX preservation fails, inspect the installed backend/dependencies and fix the accepted exporter contract; do not invent APIs or silently drop content.

## Files

Create:

| File | Purpose |
|---|---|
| `services/letfs/src/fs/processing.rs` | Attempt prepare/reconcile, output ownership, aggregate validation, atomic publication, abort. |
| `services/letfs/src/temporal/process_file_workflow.rs` | Rust workflow and typed external activity marker. |
| `services/letfs/processor/pyproject.toml`, `services/letfs/processor/uv.lock`, `services/letfs/processor/Dockerfile` | Locked tooling, dependencies, offline models, hardened worker image. |
| `services/letfs/processor/src/openlet_processor/worker.py`, `activity.py`, `convert_child.py`, `exporters.py` | Activity worker, scoped I/O, supervised conversion, deterministic exporters. |
| `services/letfs/processor/tests/test_activity.py`, `test_exporters.py` and `fixtures/tiny.{pdf,docx,pptx,xlsx}` | Failure/attempt tests and real parser fixtures. |
| `tests/e2e/processing_test.go` | Minimal real cross-language journey and binary ProcessFile history generation. |

Modify:

| Files | Change |
|---|---|
| `services/letfs/Cargo.toml`, `services/letfs/Cargo.lock` | Only concrete ZIP-independent workflow/processing dependencies using project tooling. |
| `services/letfs/src/http/mod.rs`, `services/letfs/src/fs/mod.rs`, `artifacts.rs`, `uploads.rs`, `maintenance.rs`, `deletion.rs` | Scoped processor routes, shared upload ownership, dispatch/supersession, cleanup/deletion fences. |
| `services/letfs/src/main.rs`, `services/letfs/src/temporal/mod.rs`, `services/letfs/src/temporal/lifecycle_workflow.rs` | Workflow registration, stable start, recovery/reconciliation. |
| `services/letfs/src/config.rs`, `.env.example`, `scripts/configure.py`, `scripts/configure-test.py` | Worker token, queue, resource/attempt settings. |
| `contracts/internal/openapi.yaml` | Processor-scoped source/output/complete/abort contracts using Phase 1 transport. |
| `deploy/compose.yaml`, `deploy/compose.test.yaml` | Worker service, queue, digest/config, resource/shutdown and direct-storage reachability. |
| `Makefile`, `scripts/test-workflow.sh`, `scripts/verify-foundation.sh`, `services/letfs/tests/workflow-replay.rs`, `tests/e2e/history_test.go` | Python gates, `processing` route, `process-file` selector and real history replay. |

## Implementation Steps

1. Implement attempt ordering and operation-owned output sessions on Phase 1's transport; prove stale prepare/handle/complete/abort refusal and committed-result reconciliation.
2. Register the typed Rust workflow and Python activity, then enable post-commit dispatch and maintenance recovery together.
3. Build the pinned offline worker with supervision, resource bounds, cancellation, cleanup, and redaction.
4. Implement deterministic exporters and permanent real fixtures, especially XLSX boundary cases.
5. Implement one aggregate publication transaction and tests for source identity, stale attempts, collisions, quota, empty directories, more than sixteen outputs, and lost responses.
6. Add Python format/lint/unit/parser gates, a real processing E2E route, actual binary history generation, and focused workflow replay before claiming acceptance.

## Acceptance Commands

After this phase introduces the manifests/routes/selectors:

```sh
uv sync --project services/letfs/processor --locked
uv run --project services/letfs/processor ruff check services/letfs/processor
uv run --project services/letfs/processor ruff format --check services/letfs/processor
uv run --project services/letfs/processor pytest services/letfs/processor/tests -m parser
uv run --project services/letfs/processor pytest services/letfs/processor/tests
make fmt
make verify
make test-integration SERVICE=letfs TEST=artifacts
make test-e2e TEST=processing
make test-workflow TEST=process-file
```

The baseline workflow script supports only onboarding, provisioning, destructive-lifecycle, copy-node/replay, and default routing; `process-file` and its actual history generator are planned, not currently runnable. Satisfy disk/model prerequisites first.

## Todo

- [x] Implement fenced attempts and operation-owned shared upload sessions.
- [x] Register ProcessFile/Python activity and dispatch/recovery together.
- [x] Build the pinned supervised offline worker and exact exporters.
- [x] Publish the winning complete child tree in one quota transaction.
- [x] Add Python tooling, real histories, focused E2E/replay, and >16-output coverage.

## Risks And Rollback

Pinned Temporal/Python/parser/provider integration is unverified until execution. Cross-language history and exact fixtures mitigate protocol/parser drift; stale-attempt and aggregate-quota tests mitigate partial publication. Rollback stops processing admission/worker, lets issued direct-storage capabilities reconcile, cleans unpublished sessions, and retains hybrid read/delete support until published descendants are safely removed.
