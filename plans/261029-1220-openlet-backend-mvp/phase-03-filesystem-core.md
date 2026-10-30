---
phase: 3
title: "Filesystem Core and Inline Content"
status: pending
priority: P1
effort: "6d"
dependencies: [2]
---

# Phase 3: Filesystem Core and Inline Content

<!-- Updated: Validation Session 1 - apply conditional/state recovery and retain only necessary creation/durable identity. -->

## Goal

Implement generic tree, path, mount, inline-content, quota, move, trash, restore, and direct inline-file copy semantics as short atomic letfs operations behind Workspace authorization.

## Files to Create / Modify

Paths below are relative to `/home/qninh/projects/openlet`; all are planned creations or extensions from prior phases.

- Modify: `services/letfs/migrations/`, `services/letfs/src/{fs,http}/`
- Create: `services/letfs/src/fs/{nodes,paths,mounts,quota,trash,copy}.rs`
- Modify: `services/workspace/internal/{workspace,http,letfs}/`
- Modify: `contracts/{public,internal}/openapi.yaml`
- Create: focused Rust, Go integration, security, and concurrency tests

## Data Model

- `quota_buckets` own hard `limit_bytes` and committed `used_bytes` and may serve many filesystems.
- `filesystems` reference a bucket and contain one live root plus lifecycle state.
- `nodes(id, filesystem_id, parent_id, name, kind, size_bytes, revision)` form the adjacency tree.
- `file_data(node_id PK, storage_kind, inline_bytes, object_key)` enforces the applicable value XOR.
- Create the base letfs `operations` migration here for scoped direct inline-copy keys/fingerprints/result IDs; phase 4 extends it for durable copy. Trash/restore do not create receipt rows.
- `trash_entries` bind a detached root to original parent/name and lifecycle state.
- Mount context names authorized filesystem roots supplied by the caller; no persistent mount registry/table is needed now.
- Do not add content entities, shared references, refcounts, materialized paths, or a filesystem epoch.

## Data Flow

1. Workspace authorizes the user and passes an explicit mapped filesystem and mount context.
2. letfs resolves IDs by filesystem plus verified live ancestry; UUID knowledge is insufficient.
3. letfs resolves paths with one indexed recursive SQL statement from the authorized root.
4. A mutation revalidates locators under one short filesystem lock and commits metadata/content/quota atomically.
5. Workspace returns identical node/revision/error semantics for ID and path APIs.

## Requirements

- [x] Enforce unique sibling names, valid parent kinds, no cycles, configured bounds, and same-filesystem scope, and a transactional node-count cap including empty/trash/staging nodes.
- [x] Lock quota bucket before filesystem for any accounting/bucket-lifecycle transaction; pure structural writes may lock filesystem only.
- [x] Store exact UTF-8 bytes inline only below threshold; reject invalid UTF-8/NUL for text helpers.
- [x] Use quoted ETags and require `If-Match` on replacement, rename, move, trash, and restore; path mutations require expected target/parent IDs and recheck them under lock.
- [x] Increment file revision on change and parent revision on child-set change.
- [x] Keep trash charged; only purge or filesystem deletion releases logical bytes.
- [x] Detach only the trash root while preserving node IDs and descendant edges.
- [x] Restore atomically and return name conflict rather than auto-renaming.
- [x] Hide trash/staging nodes from ordinary stat, list, content, path, and ID reads.
- [x] Prevent `cwd`, relative paths, and `..` from escaping an authorized mount.
- [x] Avoid network I/O and content streaming while holding database locks.

## Implementation Steps

1. Extend migrations with node kinds, revisions, file-data XOR, sibling uniqueness, trash and the base operations table for inline-copy deduplication; implement root mount context in request handling.
2. Implement common locator resolution for ID or path into one scoped node representation; compare expected node/parent IDs so path replacement cannot redirect old intent.
3. Implement one indexed recursive path query with root confinement and bounded validation.
4. Implement batch stat/list with keyset pagination and set-based bounded query counts.
5. Implement mkdir, inline text create/read/replace, rename, and same-filesystem move.
6. Reject self/descendant moves and cross-filesystem destinations inside the locked transaction.
7. Implement hard quota admission as atomic bucket update plus metadata commit.
8. Implement trash detach/list/restore with lifecycle/original revision guards and ambiguous-response reconciliation. Separately implement direct inline copy, committing scoped request identity/result with creation to prevent duplicate output.
9. Expose Workspace facade routes with Owner/Editor mutation and Viewer live-read permissions.
10. Update OpenAPI fixtures for locators, decimal counts/revisions, ETags, and error codes.

## Test Matrix

| Layer | Evidence |
|---|---|
| Unit | Path normalization, mount confinement, UTF-8 classification, ETag parsing, arithmetic |
| Integration | Real recursive SQL, live ancestry, sibling conflicts, cycle rejection, trash/restore |
| Concurrency | Barrier quota oversubscription, rename conflict, restore/trash, stale If-Match, two-filesystem shared-bucket admission, empty-node cap, ambiguous trash/restore response recovery, delayed stale retry after intervening lifecycle and inline-copy deduplication |
| Security/contract | Foreign IDs, `..` escape, trash-by-ID denial, role matrix, ID/path equivalence, equal-revision path replacement rejection |

No stress loop or arbitrary coverage target substitutes for deterministic race tests.

## Planned Verification Commands

```bash
make test-unit SERVICE=letfs
make test-integration TEST=filesystem-core
make test-integration TEST=files
make test-integration TEST=filesystem-scope
```

## Failure Modes and Mitigations

| Failure | Risk | Mitigation |
|---|---|---|
| Concurrent writes exceed quota | High | Bucket-first lock and quota/metadata in one transaction |
| Detached node is readable by UUID | High | Verify ancestry to live authorized root on every read |
| Resolved path writes a moved node | High | Resolve/revalidate locators under mutation lock |
| Relative traversal escapes mount | High | Root-bounded recursion and boundary rejection |
| Hot filesystem lock limits throughput | Medium | Short transactions; measure before splitting locks |

## Rollback

- Disable mutations while allowing reads against the last compatible schema.
- Roll back only to binaries that understand current node/trash states.
- Restore database backups for destructive migration rollback; never reconstruct hierarchy from paths.
- Do not decrement quota or purge trash as rollback.

## Success Criteria

- [x] ID/path operations are equivalent and cannot reach foreign, trash, staging, or out-of-mount nodes.
- [x] Inline writes preserve exact bytes and stale revisions leave prior content unchanged.
- [x] Concurrent commits never exceed the bucket limit or partially publish metadata.
- [x] Move cannot cycle/cross filesystems; trash preserves IDs and restore reports conflict.
- [x] List and batch-stat query counts are bounded independently of entry count.

