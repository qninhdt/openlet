---
title: "Phase 4: Search APIs and UX Contracts"
priority: P2
effort: 3d
depends_on: [phase-03-search-indexing]
---

# Phase 4: Search APIs and UX Contracts

## Objective

Expose metadata, clean three-stage progress, and two search APIs through the Workspace facade while preserving current authorization. Define sufficient client-facing states for file cards, breadcrumbs, degraded search, and stage-specific retry without creating a frontend application.

## Files

- Create `/home/qninh/projects/openlet/services/letfs/src/fs/search.rs`; modify `/home/qninh/projects/openlet/services/letfs/src/fs/mod.rs`, `/home/qninh/projects/openlet/services/letfs/src/fs/nodes.rs`, `/home/qninh/projects/openlet/services/letfs/src/fs/artifacts.rs`, `/home/qninh/projects/openlet/services/letfs/src/http/mod.rs`, configuration, and Rust tests.
- Modify `/home/qninh/projects/openlet/services/workspace/internal/http/files.go` and HTTP tests; modify `/home/qninh/projects/openlet/services/workspace/internal/letfs/client.go` only if the existing proxy cannot represent the new request/response contract.
- Modify `/home/qninh/projects/openlet/contracts/public/openapi.yaml`, `/home/qninh/projects/openlet/contracts/internal/openapi.yaml`, contract fixtures, E2E tests, and the owning documentation linked from `/home/qninh/projects/openlet/docs/README.md`.

## Tasks

- [x] Add `GET /v1/workspaces/{ws}/files/search` with Viewer authorization: filename/title query; optional parent locator, semantic type, media type, and created/updated ranges; allowlisted `name|created_at|updated_at` sort plus direction; bounded keyset cursor bound to filesystem, actor/scope, normalized query, filters, and sort. Query PostgreSQL directly so newly uploaded files remain discoverable before AI/Qdrant is ready.
- [x] Add `POST /v1/workspaces/{ws}/files/semantic-search` with strict bounded JSON `{query,filters,limit,cursor}`. Workspace performs Viewer authorization and filesystem mapping using the existing flow at `services/workspace/internal/http/files.go:71`; letfs calls OpenRouter embedding/rerank and Qdrant directly.
- [x] Semantic pipeline: dense + BM25 prefetch filtered by `filesystem_id`; RRF; batch DB hydration that removes non-live, non-current, or non-ready sources before rerank; bounded evidence per source and total tokens; rerank; group by unique `source_id`; hydrate latest filename/path/title/description/type/media_type; construct the matched breadcrumb to `file_id`. Parent/type/date/media filters run against live DB candidates because the minimal Qdrant payload does not contain them; refill with a bounded work limit when filtering shortens a page.
- [x] Return `{items,next_cursor,degraded}`. Each item contains original `node_id`, `filename`, current path/revision, nullable metadata, and `matched:{file_id,breadcrumb,snippet}`. Do not expose raw chunks, confidence percentages, generated answers, or a generation-model explanation call.
- [x] If reranking is unavailable, return bounded hybrid order with `degraded=true` and a machine-readable reason. Embedding or Qdrant failure returns 503 `DEPENDENCY_UNAVAILABLE`, never a successful empty result. Semantic cursors carry only bounded continuation context, bind query/filter/model/index context, and allow documented drift as the index changes; do not persist search sessions.
- [x] Replace artifact-status with one clean processing response: `{operation_id,source_id,stages:{parse,enrichment,index}}`, where each stage contains `state=pending|running|succeeded|failed`, nullable `error_code`, and `retryable`. Internal parse state is derived without changing the `operations.state` accounting invariant. Add `POST /v1/workspaces/{ws}/files/processing-retry` with Editor authorization, a live original locator, and `stage=enrichment|index`; retry only the current failed stage, return 202 while running and 200 if already complete, and do not add public cancellation.
- [x] List/stat contract: filename remains the canonical path name; AI title is an additional display label, description is the subtitle, and type/media type are filters. Return context only from stat/detail. README remains an ordinary readable node: clients may render it as an overview, while the content route remains the raw byte authority.
- [x] Document client acceptance flows without adding frontend code: upload with three-stage progress; parse succeeded while enrichment/index failed; filename search before AI readiness; semantic result opens the matched breadcrumb; stale/trashed result disappears; degraded rerank banner; retry targets only the failed stage; README/chunk evidence never appears as duplicate file cards.

## Acceptance

- [x] Viewer results remain within the authorized live filesystem; foreign IDs and stale cursors reveal no metadata.
- [x] Filename search does not depend on OpenRouter/Qdrant; semantic search returns unique originals with breadcrumbs resolvable through existing file APIs.
- [x] DB filters remain correct with the five-field Qdrant payload; missing AI metadata still allows a filename result in basic search.
- [x] Public/internal OpenAPI, fixtures, errors, and docs match implementation; no frontend stack is introduced.

## Validation

```bash
make test-unit SERVICE=workspace
make test-unit SERVICE=letfs
make test-integration SERVICE=workspace
make test-integration SERVICE=letfs TEST=search
make test-e2e TEST=processing-search
python3 scripts/verify-contracts.py
make verify
```

This phase must add `processing-search` to the E2E harness before using that command. Vietnamese/English cases cover overview and detail outside the enrichment sample, authorization revocation, filters, cursors, reranker degradation, Qdrant/embedding 503 responses, stale-operation refill, and breadcrumbs after enrichment renames.

## Risks and Rollback

- **High:** Qdrant results bypass authorization/live state. Mitigation: mandatory PostgreSQL authorization/current-operation validation; payload filtering only reduces candidates.
- **Medium:** semantic pagination drifts. Mitigation: bound work/refill, bind cursor context, and document approximate behavior; basic search retains deterministic keyset pagination.
- Roll back the routes/contracts with the prior service build. Existing stat/list/content behavior remains available, and Qdrant/AI outages do not affect those APIs.

## Execution Evidence

- `make verify GO=/usr/local/go/bin/go` passed: Go/Rust unit tests, Go vet, Clippy, Python Ruff/tests, configuration tests, OpenAPI references and shell syntax.
- Workspace native integration passed. Real Qdrant/PostgreSQL search integration passed with live/current/readiness checks, foreign evidence rejection, filters/cursors, 503/degraded responses, replacement, rebuild, purge and filesystem deletion.
- Public processing-search E2E passed with text outside the enrichment sample, short Vietnamese content, unique source breadcrumbs, filename search before AI readiness, metadata filtering, pagination, Viewer access, Editor-only retry and membership revocation.
- The index failure/retry E2E preserved the same operation and enrichment timestamp. OpenAPI validation accepted 364 captured public response DTOs from that run.
- Updated the existing documentation navigation, setup, workflow, data-model, API and testing owners; no frontend application was added.
