---
title: "Phase 2: Semantic Enrichment and Publication"
priority: P2
effort: 4d
depends_on: [phase-01-artifact-layout]
---

# Phase 2: Semantic Enrichment and Publication

## Objective

Generate `title`, `description`, `type`, and `context` bottom-up for the whole source tree, then atomically publish metadata, slugs, relative links, and README files in letfs. Original bytes remain unchanged. The existing `operations.state='succeeded'` parse publication state remains the accounting authority while enrichment and indexing retry independently.

## Files

- Create `/home/qninh/projects/openlet/services/letfs/migrations/0011_semantic_processing.sql`; modify `/home/qninh/projects/openlet/services/letfs/src/fs/artifacts.rs`, `/home/qninh/projects/openlet/services/letfs/src/fs/processing.rs`, `/home/qninh/projects/openlet/services/letfs/src/fs/nodes.rs`, `/home/qninh/projects/openlet/services/letfs/src/fs/uploads.rs`, and `/home/qninh/projects/openlet/services/letfs/src/http/processing.rs`.
- Modify `/home/qninh/projects/openlet/services/letfs/processor/pyproject.toml`, `/home/qninh/projects/openlet/services/letfs/processor/uv.lock`, `/home/qninh/projects/openlet/services/letfs/processor/src/openlet_processor/activity.py`, and `/home/qninh/projects/openlet/services/letfs/processor/src/openlet_processor/worker.py`; create `semantic.py`, `openrouter.py`, and `readme.py` in the same package.
- Modify `/home/qninh/projects/openlet/services/letfs/tests/artifacts/processing.rs`, processor tests, and `/home/qninh/projects/openlet/contracts/internal/openapi.yaml`.

## Tasks

- [x] Add nullable `media_type`, `title`, `description`, `semantic_type`, and `context` columns directly to `nodes`. AI fields may be absent while enrichment is pending, but a successful enrichment must write the complete validated record. Byte replacement clears obsolete AI fields; rename/move preserves them. Do not create a metadata table or add an operation ID to node metadata. Add separate enrichment/index state, error, and completion facts to processing operations without reusing or resetting `operations.state`, which still owns charged parse publication (`services/letfs/migrations/0002_file_core.sql:21`, `services/letfs/src/fs/artifacts.rs:27`).
- [x] Generalize source identity: object sources use immutable `object_key`; inline/direct sources use SHA-256 bytes plus detected technical format/media type. Rename/move does not create a new content identity; byte replacement always supersedes the current processing intent (`services/letfs/src/fs/nodes.rs:350`, `services/letfs/src/fs/processing.rs:60`).
- [x] Add internal stage routes under `/internal/v1/processing/{operation}/enrichment/{prepare|outputs|complete|fail}`. `prepare` returns the current live source, whole-tree inventory, and bounded content descriptors. `complete` rechecks current operation/source liveness and returns the saved result when already complete. Reuse the existing processor-token boundary at `services/letfs/src/http/mod.rs:141`.
- [x] Extend `uploads_processing_owner` for enrichment while leaving parser generation/attempt validation and parser path uniqueness unchanged. Enrichment creates fresh immutable upload IDs for each request; do not add unique `(operation,stage,path)`, an enrichment attempt generation, or per-leaf checkpoints. Add `uploads::Access::Enrichment` and routes `/internal/v1/processing/{operation}/enrichment/uploads/{upload}/{status|parts|complete|bytes}` using the existing inline, single-PUT, and multipart transports.
- [x] Enrichment complete validates the submitted whole-tree manifest, selected upload IDs, ownership, and paths, then commits only if enrichment is not already succeeded. The first committed manifest wins; overlapping retry results return the saved completion. Existing cleanup discards unselected or unpublished enrichment uploads (`services/letfs/src/fs/processing.rs:101`).
- [x] Implement the generic sampler bounded by the shared character-based token estimate with `RecursiveCharacterTextSplitter`: use the whole text when it fits; otherwise build bounded blocks, select evenly across beginning-to-end, preserve source order and omission markers, use zero overlap, and recount after serialization. CSV uses a deterministic profile/reservoir; images use bounded vision input. Do not add filetype-specific samplers.
- [x] Call OpenRouter `/chat/completions` through Instructor + Pydantic for generation and vision. Validate enums/taxonomies, unknown/empty escape values, slugs, and paths in code; document content never controls tools or paths. Bound leaf concurrency. Folder/root prompts use generated child summaries held in memory plus their own content, sampled with the same generic bounded sampler. Persist the enrichment result once for the whole tree.
- [x] Build the final node-ID-to-path map before renaming or rewriting links. Structural sections/chapters/parts and sheet folders become `<index>-<title-slug>`; other generated files become `<title-slug>.<ext>`. On a sibling filename collision, use `<title-slug>-<index>.<ext>` with the file's per-type index and validate uniqueness of the complete final manifest. A README contains its own metadata and own content; `children` contains only direct-child path plus `title/description/type`. Raw inline/object text, standalone CSV, and standalone images store metadata directly on their source node without creating artifacts or renaming the original file.
- [x] In one bucket/filesystem transaction, recheck current operation, live source, and incomplete enrichment; update metadata, names, README bytes/file data, revisions, node sizes, and quota delta; publish everything or nothing. Public artifact mutation remains blocked by `Node::writable()` at `services/letfs/src/fs/nodes.rs:45`.
- [x] Hydrate `title/description/type/media_type` in list responses and add `context` plus three-stage processing status to stat/detail responses. Lists must not include file bodies.

## Acceptance

- [x] Metadata flows leaf -> folder -> root; parent prompts consume completed child summaries and stay within token bounds for long child lists.
- [x] Retry after successful completion does not call the model or change slugs; a mid-stage failure cannot expose a half-renamed tree.
- [x] README/link/name/quota publication is atomic; quota failure preserves the prior tree/metadata and parse publication remains succeeded.
- [x] Original bytes remain unchanged; raw text/CSV/image creates no child artifacts; inline and object storage both work. Metadata is stored directly on `nodes`, and byte replacement clears obsolete AI metadata.
- [x] Structural names retain their ordinal prefix; image/CSV names drop their temporary index unless a sibling collision requires `<slug>-<index>.<ext>`. README names remain fixed, final paths are unique, and rewritten links resolve.

## Validation

```bash
make test-unit SERVICE=processor
make test-unit SERVICE=letfs
make test-integration SERVICE=letfs TEST=artifacts
python3 scripts/verify-contracts.py
```

Fixtures cover Unicode and one-line text, estimated prompt budgets, wide/mixed/null/code-like CSV data, image evidence, long child inventories, slug collisions, object-backed README files, quota rejection, stage-aware upload ownership, and idempotent complete. Unit/integration tests use schema-faithful fake HTTP; paid smoke runs separately only when credentials are supplied.

## Risks and Rollback

- **High:** the rename/README transaction miscalculates quota or links. Mitigation: precompute the manifest and byte delta, preserve existing lock order, and resolve all links before commit.
- **Medium:** prompt injection or invalid structured output. Mitigation: no tools, strict schemas/enums, bounded retry, and explicit failed stage state.
- Roll back by stopping enrichment dispatch and reverting worker/service code. Keep additive metadata/stage data for diagnosis or reset the development database; never delete source bytes.

## Execution Evidence

- Added migration `0011_semantic_processing.sql` after a verified PostgreSQL dump at `.local/snapshots/pre-semantic-processing/letfs.dump`.
- Processor tests: 73 passed, including real parser/OCR fixtures, bounded character-based sampling, structured OpenRouter generation/vision, README rendering, collision/link rewriting, and activity terminal/retry reporting.
- Real PostgreSQL/S3 artifact integration: 11 passed, including whole-tree enrichment publication, idempotent completion, object-backed Markdown, quota rollback, invalid ownership/path rejection and source replacement.
- Metadata is stored directly on nodes. Direct text/CSV/image processing retains source bytes and creates no artifacts; stat exposes context and three-stage progress, while lists omit context.
