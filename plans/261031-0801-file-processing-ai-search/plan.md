---
title: "AI File Processing and Hybrid Search"
description: "Extend the existing file pipeline with semantic enrichment and hybrid search without changing source bytes, authorization, quota, or lifecycle invariants."
status: completed
priority: P2
effort: 14d
branch: dev
tags: [feature, backend, database, api]
blockedBy: []
blocks: []
created: 2026-10-31
---

# AI File Processing and Hybrid Search

## Outcome

Process each source as one whole-tree job: the parser produces an artifact tree with at most two semantic content levels, enrichment generates bottom-up metadata and atomically publishes final names/README files, indexing writes file and chunk evidence to Qdrant, and search returns unique original files with a matched artifact breadcrumb. Original bytes, ID/path authorization, artifact read-only behavior, quota accounting, and lifecycle rules remain unchanged.

## Constraints

- `ProcessFile` uses three whole-source activities in order: `process_file -> enrich_file -> index_file`. Direct text, CSV, and image sources skip parsing. Do not add per-child activities, per-child checkpoints, distributed locks, or unrelated activity/polling changes.
- OpenRouter provides generation and vision through Instructor + Pydantic, and embeddings/reranking through direct APIs. Use standalone `langchain-text-splitters`; do not add the LangChain framework or an inference proxy service.
- Store `title`, `description`, `semantic_type`, `context`, and `media_type` directly on `nodes`. Structural sections/sheets use `<index>-untitled` then `<index>-<slug>`; other generated files use `untitled-<index>.<ext>` then `<slug>.<ext>`, with independent per-type counters and collision suffixes.
- Qdrant payload contains only `filesystem_id`, `source_id`, `file_id`, `operation_id`, and `text`. PostgreSQL/letfs owns metadata, filters, authorization, current-operation checks, and readiness.
- Model IDs, token budgets, and numeric thresholds are validated configuration inputs selected during implementation evaluation; they are not architectural blockers.

## Non-Goals

- Image-to-image search, row-level CSV search, chatbot/RAG answers, advanced PPTX layout, formula evaluation, and merged-cell interpretation.
- A new frontend application. Phase 4 defines concrete API and client interaction contracts only.
- Production deployment choreography. Development artifacts and Temporal histories may be regenerated explicitly.

## Data Flow

```text
source bytes + durable processing operation
  -> parser/exporter or direct-source reader
  -> 0/1/2-level artifact tree
  -> semantic sampling/profile/vision
  -> node metadata + atomic README/name/link publication
  -> full-text chunks + dense embeddings + Qdrant BM25
  -> DB live/current/ready validation + RRF/rerank
  -> unique original files + matched breadcrumb
```

## Phases

Phase completion is recorded by the checklists in the linked files.

| # | Phase | Dependency | Effort |
|---|---|---|---:|
| 1 | [Artifact Layout and Exporter](./phase-01-artifact-layout.md) | - | 3d |
| 2 | [Semantic Enrichment and Publication](./phase-02-semantic-enrichment.md) | 1 | 4d |
| 3 | [Search Indexing, Temporal, and Lifecycle](./phase-03-search-indexing.md) | 2 | 4d |
| 4 | [Search APIs and UX Contracts](./phase-04-search-api-and-ux.md) | 3 | 3d |

## Plan Acceptance

- [x] Layout selection, Excel/PPTX rules, and media ownership preserve every source item exactly once while leaving original bytes unchanged.
- [x] Parse success retains its current publication/quota accounting meaning; enrichment and index states are separate, and index retry never reruns OCR or committed enrichment.
- [x] Dense + BM25 + RRF + rerank returns unique live original files; stale, trashed, deleted, or unauthorized candidates never reach the response.
- [x] Text create/replace, eligible upload/copy, and explicit backfill create the correct processing intent; generated artifacts never recursively trigger processing.
- [x] Public contracts expose metadata, clean three-stage progress/retry, filename search, and semantic search with breadcrumbs without introducing a frontend stack.
- [x] Database backup precedes schema changes; Qdrant remains rebuildable derived data; rollback never removes source bytes or charged published artifacts.

## Dependencies and Rollback

- Execute phases sequentially because later phases consume schema and publication contracts from earlier phases.
- Back up the development database before migration, apply schema and services, then run explicit backfill/reprocess as needed.
- Qdrant is derived state. It may be dropped, recreated, and rebuilt from PostgreSQL plus the source/artifact tree; PostgreSQL and stored bytes remain authoritative.

## Validation Log

- **Tier:** Standard (4 phases; Fact Checker + Contract Verifier).
- Verified current owners and paths for exporter/preflight, parser publication/quota, processing intent/invalidation, Temporal dispatch/worker registration, copy/trash/deletion/maintenance, Workspace file authorization/proxying, OpenAPI contracts, and Makefile test commands.
- Current flow evidence: upload finalize records and dispatches processing (`services/letfs/src/fs/uploads.rs:699`); the workflow currently schedules `process_file` (`services/letfs/src/temporal/process_file_workflow.rs:22`); parser complete publishes and charges atomically (`services/letfs/src/fs/processing.rs:190`); replace/trash/maintenance are owned at `services/letfs/src/fs/nodes.rs:340`, `services/letfs/src/fs/trash.rs:39`, and `services/letfs/src/fs/maintenance.rs:24`.
- Workspace authorizes and maps filesystem scope in `services/workspace/internal/http/files.go:71`; file routes are registered at `services/workspace/internal/http/files.go:250`; letfs internal file actions are owned by `services/letfs/src/http/mod.rs:266`.
- Commands were verified in `Makefile:22`, `Makefile:33`, `Makefile:40`, `Makefile:43`, `Makefile:46`, and `Makefile:49`. The current integration selector only accepts `direct-storage|artifacts|zip-export` at `scripts/test-integration.sh:7`, so phase 3 must add the search selector before using it.

### Whole-Plan Consistency Sweep

- Files reread: `plan.md` and all four phase files.
- Confirmed one typed workflow input, regenerated workflow fixtures, and one clean three-stage API status schema.
- Preserved stage-aware enrichment upload ownership, parse accounting, source/auth/quota invariants, minimal Qdrant payload, and all accepted format/search decisions.
- Unresolved contradictions: 0.

## Open Questions

No architectural decision blocks implementation. Model IDs and threshold values are chosen through configuration and evaluation during the relevant phase.

## Completion Evidence

- All four phase checklists are complete (55/55 tasks); detailed evidence is recorded in each phase file.
- `make verify GO=/usr/local/go/bin/go` passed, including 13 Rust unit tests, 63 processor non-parser tests, Go tests/vet, Clippy, Ruff, configuration tests, OpenAPI and shell syntax. The separate full processor run passed 73 tests, including real parser/OCR fixtures.
- All 21 native letfs integration tests passed with PostgreSQL, S3, Temporal, Qdrant and Chromium; Workspace native integration also passed.
- Document processing, semantic search, worker recovery/exhaustion, and ZIP export E2Es passed. Both ProcessFile replay tests passed against regenerated histories.
- Coordinated backup and isolated restore passed with source/artifact/ZIP byte equality, quota reconciliation, preserved Temporal history and paused-schedule verification. Qdrant is rebuilt separately as documented in `docs/operations.md`.
- OpenAPI accepted 578 captured public response DTOs. No paid model calls, commits, push or deployment were performed.

<!-- slug: file-processing-ai-search -->
