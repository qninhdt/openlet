---
title: "Phase 3: Search Indexing, Temporal, and Lifecycle"
priority: P2
effort: 4d
depends_on: [phase-02-semantic-enrichment]
---

# Phase 3: Search Indexing, Temporal, and Lifecycle

## Objective

Index the whole source tree with dense embeddings plus Qdrant BM25, extend `ProcessFile` to three durable stages, and cover every creation/copy/backfill/lifecycle trigger without changing unrelated activities or polling behavior.

## Files

- Modify `/home/qninh/projects/openlet/services/letfs/src/temporal/process_file_workflow.rs`, `/home/qninh/projects/openlet/services/letfs/src/temporal/mod.rs`, `/home/qninh/projects/openlet/services/letfs/src/fs/artifacts.rs`, `/home/qninh/projects/openlet/services/letfs/src/fs/nodes.rs`, `/home/qninh/projects/openlet/services/letfs/src/fs/uploads.rs`, `/home/qninh/projects/openlet/services/letfs/src/fs/copy.rs`, `/home/qninh/projects/openlet/services/letfs/src/fs/trash.rs`, `/home/qninh/projects/openlet/services/letfs/src/fs/deletion.rs`, `/home/qninh/projects/openlet/services/letfs/src/fs/maintenance.rs`, `/home/qninh/projects/openlet/services/letfs/src/fs/processing.rs`, `/home/qninh/projects/openlet/services/letfs/src/config.rs`, and `/home/qninh/projects/openlet/services/letfs/src/main.rs`.
- Modify `/home/qninh/projects/openlet/services/letfs/processor/src/openlet_processor/activity.py`, `/home/qninh/projects/openlet/services/letfs/processor/src/openlet_processor/worker.py`, dependency locks, and create `/home/qninh/projects/openlet/services/letfs/processor/src/openlet_processor/indexing.py` with tests.
- Modify `/home/qninh/projects/openlet/deploy/compose.yaml`, test overlays, `/home/qninh/projects/openlet/scripts/configure.py`, `/home/qninh/projects/openlet/scripts/test-integration.sh`, `/home/qninh/projects/openlet/scripts/test-workflow.sh`, `/home/qninh/projects/openlet/services/letfs/tests/workflow-replay.rs`, and processing E2E cases.

## Tasks

- [x] Pin Qdrant `v1.20.x` and create one collection for the configured embedding model with a dense vector plus a full-text BM25 index on `text`. Python calls OpenRouter `/embeddings` and Qdrant directly through HTTP. Validate endpoint, collection, API-key file, model ID, vector dimension, batch/concurrency/token bounds, and timeouts; never log secrets or file text.
- [x] Build file-level overview points for each logical file/folder and chunk-level points for long full text. Root/folder README nodes map to their logical source/folder instead of duplicating the original. CSV indexes profile/context only; images index vision-generated text only. Context prefixes use artifact ancestors, not the external Drive path.
- [x] Derive deterministic point IDs from `(operation_id,file_id,kind,ordinal)`. Payload is exactly `filesystem_id/source_id/file_id/operation_id/text`. Retry may upsert the whole tree. Mark index succeeded only after every batch is confirmed and the operation/source is still current and live. Partial points remain invisible because search requires DB readiness.
- [x] Replace the workflow argument with one typed input: `{ operation_id, parse_required, enrichment_required }`. Dispatch derives both flags from stored source/stage facts before starting the workflow; workflow code performs no database reads and receives no raw content. PDF/DOCX/XLSX/PPTX use `true,true`; direct text/CSV/image use `false,true`; index-only rebuild uses `false,false`.
- [x] Run `process_file` only when `parse_required`, then `enrich_file` only when `enrichment_required`, then `index_file`. Each activity receives only the operation ID, has its own timeout/heartbeat/retry policy, and preserves the previous committed stage when a later stage retries. Keep the existing processing queue and worker concurrency; do not change other workflow activity boundaries or polling intervals.
- [x] Use `UseExisting` for a running workflow and allow a new run after close for the same current operation when a failed stage is retried or an index rebuild is requested. Stage facts determine the typed flags, so successful parse/enrichment is skipped. Regenerate development Temporal histories and update workflow tests to assert the new activity sequence, flags, task queue, and retry boundaries.
- [x] Trigger processing for uploaded PDF/DOCX/XLSX/PPTX through parsing; eligible text/CSV/image uploads and text create/replace through direct enrichment; rename/move does not rerun processing. Eligible inline copy creates a fresh processing intent. Durable copy with an artifact snapshot creates a fresh destination processing operation with parse already succeeded and enriches/indexes the copied tree instead of calling parser complete on a populated source (`services/letfs/src/fs/processing.rs:242`). Copy publication/accounting remains independent and succeeded.
- [x] Add one admin command: `letfs --backfill-processing --mode missing|rebuild-index [--apply] [--after UUID] [--limit N]`. `missing` selects live eligible sources without complete enrichment/indexing; `rebuild-index` selects indexed sources after collection/model change. Dry-run prints counts and next cursor only; apply handles one bounded page and prints the resume cursor. Existing development artifacts may be explicitly reused or invalidated/reprocessed; no automatic migration rewrite is required.
- [x] Snapshot only embedding model ID, collection, and vector dimension needed for vector-space consistency. Index retry uses that snapshot; ready completion verifies that the same vector-space facts are still selected. After the current workflow closes, rebuild commits pending readiness and the existing cleanup marker while retaining the old snapshot. Index preparation confirms old-point deletion before adopting the configured vector space and runs index-only. Generation is already committed enrichment; reranker is query-time configuration. Do not add index generations or a per-operation configuration framework.
- [x] Lifecycle policy: trash keeps Qdrant points but DB live checks hide the source immediately; restore reuses the ready index. Byte replacement supersedes the source operation, so DB current-operation checks reject old points before maintenance deletes them by old `operation_id`. Purge/filesystem deletion marks indexed operations for deletion; maintenance removes exactly those operation points and records terminal cleanup.
- [x] Keep `processing::maintain` from treating direct parse-succeeded operations as failed parser work. Reconcile only stages that are actually pending/running. Preserve the 300-second maintenance schedule and every unrelated activity/polling boundary (`services/letfs/src/fs/maintenance.rs:31`, `services/letfs/src/temporal/lifecycle_workflow.rs:145`).

## Acceptance

- [x] Full text outside the enrichment sample is retrievable; CSV does not promise arbitrary row-value retrieval; images do not promise visual similarity.
- [x] Index retry creates no duplicate points and never reruns OCR or committed enrichment; a stale operation cannot mark a newer source operation ready.
- [x] Overwrite, trash, purge, filesystem deletion, copy, backfill, and rebuild expose no stale or foreign content; restore does not require reindexing.
- [x] Regenerated workflow histories prove the typed input flags, expected stage sequence, retry boundaries, direct skip-parser path, and index-only rebuild.

## Validation

```bash
make test-unit SERVICE=processor
make test-unit SERVICE=letfs
make test-integration SERVICE=letfs TEST=search
make test-e2e TEST=processing
make test-e2e TEST=processing-recovery
make test-workflow TEST=process-file
```

`TEST=search` becomes valid only after this phase adds the selector to `scripts/test-integration.sh`. The matrix covers deterministic IDs, batch failure/not-ready behavior, source replacement between upsert/finalize, trash/restore/purge, filesystem deletion, copied artifact trees, direct text/object CSV/image, token/concurrency bounds, and collection recreation.

## Risks and Rollback

- **High:** stale search exposure. Mitigation: mandatory PostgreSQL live/current/ready validation before rerank or response; Qdrant filtering is never authorization.
- **Medium:** workflow flags diverge from stored stage facts. Mitigation: derive them once in dispatch, test every flag combination, and make stage completion idempotent.
- Roll back by stopping dispatch/backfill, reverting workflow/worker code, and regenerating development histories. Keep database/source/artifact state; drop and rebuild Qdrant as needed.

## Execution Evidence

- Qdrant v1.20.0 is pinned by digest. Real-Qdrant integration covers hybrid retrieval, DB readiness/current-source validation, replacement, trash/restore, rebuild cleanup failure/retry, purge and filesystem deletion.
- Native missing-backfill integration verifies dry-run, one-page apply, active-workflow skip, preserved source bytes and unchanged quota. Directory-copy integration verifies dispatch for every logical child and resumption after an already-published copy.
- Public document E2E passed for PDF/DOCX/XLSX/PPTX and embedded images, including unchanged source bytes and artifact read-only behavior. Copied DOCX artifacts reach index readiness with parser generation zero.
- Public direct-source E2E passed for large object text, short Vietnamese text, object CSV and images; direct sources create no artifacts. Text outside the enrichment sample remains searchable.
- Index failure/retry retains the operation and committed enrichment timestamp. Whole-tree retry uses deterministic point IDs; incomplete or obsolete indexes remain invisible.
- Actual processor kill/restart and retry-exhaustion E2Es passed. Regenerated document, direct, index-only, index-failure, recovery and exhausted histories passed both Rust ProcessFile replay tests.
- Independent review found and verified repairs for short-text retrieval, per-source copy dispatch, rebuild snapshot/cleanup consistency and inline media types. No unresolved concrete finding remains.
