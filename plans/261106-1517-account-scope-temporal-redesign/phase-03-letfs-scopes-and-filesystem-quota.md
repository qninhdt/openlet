---
title: "Phase 3: LetFS scopes and filesystem quota"
priority: P1
dependencies: [1, 2]
---

# Phase 3: LetFS scopes and filesystem quota

## Overview

Make scope the real tree/access boundary in every LetFS path, replace quota bucket with filesystem accounting, and remove mounting across handwritten clients. Depends on Phases 1–2. Keep the existing payload/transfer/processing guarantees.

## Requirements

- [x] Filesystem and scope creation are generic, idempotent SQL operations without Workspace semantics.
- [x] Every node/content operation validates filesystem → scope → live node ancestry and its action.
- [x] Usage, node count and cleanup evidence remain transactionally correct under concurrent operations.
- [x] No mount compatibility path, SQL ACL mirror or scope-local quota.

## Owning file inventory

| Boundary | Existing files to modify |
|---|---|
| Session/tree/path/authz | `apps/letfs/internal/filesystem/{nodes.go,paths.go,authorization.go,node_writes.go,provisioning.go,service.go}` |
| Transfers/content | `uploads.go`, `upload_publication.go`, `download.go`, `archive.go` in that filesystem package |
| Copy/trash/lifecycle | `copy.go`, `copy_state.go`, `trash.go`, `deletion.go`, `maintenance.go` |
| Processing and output publication | `processing.go`, `processing_control.go`, `processing_uploads.go`, `processing_publication.go`, `artifacts.go`, `enrichment.go` |
| Search/index/backfill | `search.go`, `semantic_search.go`, `indexing.go`, `index_cleanup.go`, `backfill.go`; `apps/letfs/internal/clients/search/query.go` |
| HTTP transport (all 9 source files) | `apps/letfs/internal/transport/http/{router.go,responses.go,requests.go,content.go,nodes.go,uploads.go,search.go,archive.go,trash.go}` and all colocated handler tests |
| gRPC transport (all 10 source files) | `apps/letfs/internal/transport/grpc/{administration.go,filesystem.go,ingest.go,copy.go,search.go,uploads.go,archive.go,download.go,processing.go,trash.go}` and all colocated handler tests |
| Handwritten SDKs | `packages/go/clients/letfs/{client.go,filesystem.go,operations.go,ingest.go}`; `packages/python/src/openlet/clients/letfs.py` |
| Ingest search identity | `apps/letfs-ingest/src/letfs_ingest/processing/indexing.py`, `clients/qdrant.py`, ingest temporal activities and tests |

Review the full transport inventory, but modify only scope-affected code; unrelated range/JSON helpers stay unchanged. Update colocated unit/integration tests for each affected owner. Add a small `scopes.go` in the existing filesystem package only if it makes scope SQL cohesive; no scope framework/package/service is needed.

## Implementation Steps

1. Implement CreateFilesystem with limit/policy and zero nodes, and CreateScopes with opaque IDs/filesystem identity/root creation. Verify retry input identity and immutable inline-only policy. No shared/personal/member terminology in LetFS creation input or default logic.
2. Replace session bucket lock/accounting with filesystem lock/accounting. Fetch scope/root in the same owning session; enforce active/deleting states at both levels. All quota changes, actual node counts and publication happen atomically. Keep existing node/job/backlog limits without inventing reservation slots or counters.
3. Remove Mount/PathContext/path_context/mount_path, longest-prefix matching, synthetic root/default mount, and mounts parameters from every service/store/client. Resolve `/`, relative path/cwd, `..`, aliases and raw node IDs within one scope; keep expected identity/revision checks, file-descendant rules and name/cycle/depth validation.
4. Update every HTTP/gRPC handler named above and node/file CRUD, listing, transfer/sign/finalize/abort, trash/restore/purge and archive. Apply the operation→action matrix in the contract: all content/semantic search, snippets/context, download and archive require read_content before excerpt/rerank/provider calls. Stat/list/resolve and text-free processing/trash metadata use read_metadata. Upload sessions still enforce initiating actor and captured destination.
5. Store/check scope identity in transfer, copy and trash admissions. Support source/destination scopes in one filesystem for copy with separate actions; keep same-scope move. Scope lookup must reject foreign filesystem/IDs before side effects.
6. Carry scope through parser/enrichment/index input and outputs. Qdrant payload/filter and semantic candidate revalidation must include scope, not just filesystem. Backfill and artifact/output uploads must not publish into another scope or a deleting source.
7. Replace logical bucket IDs in cleanup attribution, upload SQL/indexes, open-write tracking, backpressure and fresh object keys (`objects/<filesystem-id>/<immutable-write-id>`). Preserve physical S3 bucket settings and exact-key ambiguity/late-write evidence; no old-object-prefix compatibility logic.
8. Keep existing inline-only tests and behavior for user content, copy and processor outputs. Cross-scope same-filesystem copy inherits the same filesystem policy; no per-scope policy variation.
9. Make DeleteScopeData/PurgeTrashData bulk internals retry-safe under existing filesystem-lock transactions. Only actual deletion subtracts bytes/count; write cleanup records before removing source metadata. Lifecycle activities/orchestration are registered in Phase 4, not invented here.
10. Update Go/Python SDK signatures and transport serialization; remove dead helpers and bucket APIs immediately. Remove copy-progress endpoints/queries, response fields and client methods alongside the old durable copy-state/checkpoint machinery; retain only ordinary local traversal and genuinely used admission/result facts. Do not leave optional path_context arguments ignored for compatibility.

## Todo

- [x] Generic scope creation and scope-bound sessions/FKs/paths implemented.
- [x] Bucket accounting/object identity replaced; physical GC safeguards retained.
- [x] Upload/copy/trash/archive/processing/search/backfill scope propagation complete; copy progress/checkpoint/resume surfaces removed.
- [x] Mounting removed from transport/domain/handwritten clients and tests.
- [x] Inline-only and cross-scope isolation/quota integration tests pass.

## Success Criteria

Two scopes in the same filesystem are isolated under raw ID, path, cwd, search and output publication. Shared filesystem quota cannot be exceeded by concurrent scope writes; trash remains charged, move is zero delta, purge charges/debits once. Parent/root FKs reject scope escape. Logical deletion preserves physical cleanup evidence. No role/type/workspace lookup occurs in LetFS to decide access.

## Verification

```sh
pnpm --filter @openlet/letfs test
pnpm --filter @openlet/letfs test:integration
pnpm --filter @openlet/python test
pnpm --filter @openlet/letfs-ingest test
pnpm contracts:check
```

Narrow meaningful cases first: same-FS foreign scope IDs/paths/cwd/aliases, metadata-only content redaction, cross-scope parent rejection, search candidate injection, upload/parse generation into wrong scope, cross-scope copy versus forbidden cross-scope move, concurrent quota and purge accounting, separately trashed children, ambiguous S3 writes after logical deletion, restricted-inline outputs. Then run the full affected suites.

## Risk and stop rule

Do not turn scope propagation into a new service security framework or per-file ACL. Do not discard FK/cleanup guards to make bulk delete easy. If the reviewed minimal schema cannot preserve existing upload/GC correctness, show the exact failing path and request review before extending it.
