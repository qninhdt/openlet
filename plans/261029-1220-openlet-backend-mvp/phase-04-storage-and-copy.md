---
phase: 4
title: "Object Storage, Uploads, and Copy"
status: pending
priority: P1
effort: "7d"
dependencies: [3]
---

# Phase 4: Object Storage, Uploads, and Copy

<!-- Updated: Validation Session 1 - apply conditional/state recovery and retain only necessary creation/durable identity. -->

## Goal

Add configurable S3-compatible content, retry-safe one-transfer uploads, and durable object/directory copy extending phase 3 inline-copy behavior with per-item coherence rather than snapshot claims.

## Files to Create / Modify

Paths below are relative to `/home/qninh/projects/openlet`; all are planned creations or extensions from prior phases.

- Create: `services/letfs/src/storage/`, `services/letfs/src/fs/uploads.rs`; extend: `services/letfs/src/fs/copy.rs`
- Modify: `services/letfs/src/{temporal,http}/`, `services/letfs/migrations/`
- Modify: `services/workspace/internal/{letfs,http}/`
- Modify: `contracts/{public,internal}/openapi.yaml`
- Modify: `deploy/compose.yaml`, `.env.example`
- Create: storage, upload, copy, recovery, and wire-contract tests

## Data Model

- `uploads` store caller/scope, target precondition, candidate key, one transfer claim, bytes/digest, state, and result.
- `operations` store copy admission, source/destination scope, staging root, totals, state, and result.
- `copy_items` map each stable source node ID once to a destination ID and freeze revision/key/size per item.
- `object_deletions` tracks unpublished or superseded keys and a not-before later than maximum read/write duration.
- Each committed object-backed file owns an independent key; there are no manifests, pins, shared references, or refcounts.

## Upload Data Flow

1. Create validates scope/preconditions and commits an upload row with a registered candidate key before I/O.
2. One transfer request CAS-claims the upload and streams bytes with byte/deadline bounds.
3. Finalize verifies bytes/digest, rechecks revision and scope, and atomically publishes metadata plus quota.
4. Failure preserves old content; unpublished bytes stay uncharged and the registered key is cleaned later.

## Copy Data Flow

1. Inline file copy is direct; object-backed file copy uses `CopyNode` with one frozen item and publish transaction.
2. Object/directory copy starts `CopyNode`; its first activity admits the caller/fingerprint and creates a detached destination.
3. Batches keyset-enumerate source node IDs, record each directory's child-ID upper bound, map each once, and freeze each item's current revision/key.
4. Processing rechecks the item; edit/move/trash/delete may return `SOURCE_CHANGED`; new entries may be omitted.
5. After all items succeed, one transaction rechecks destination/quota and publishes the root plus full charge.

## Requirements

- [x] Support configurable external S3-compatible storage and optional local storage only for development/tests; external endpoints require verified TLS, private objects and object-only credentials.
- [x] Stream bounded data without buffering arbitrary files in Workspace or letfs memory.
- [x] Classify small valid UTF-8 inline and large/binary content as object-backed from actual bytes.
- [x] Preserve old data when transfer, validation, revision, authorization, or quota finalization fails.
- [x] Treat missing deletes as success while retaining ambiguous-write evidence; durable key/state prevents late publication and repeat effects.
- [x] Enforce same-filesystem copy/full logical quota cost without reservation; reject source/self/descendant destinations at prepare and final publish.
- [x] Copy each source node no more than once by stable mapping, not mutable names.
- [x] Promise per-file coherent revisions only; no whole-tree snapshot or filesystem epoch.
- [x] Keep directory destination detached until success and publish plus quota in one transaction.
- [x] Never perform S3 calls while holding bucket or filesystem locks.

## Implementation Steps

1. Define a minimal provider interface for put/copy/get-range/head/delete and implement S3-compatible storage.
2. Add upload, copy-item and object-deletion migrations and extend the phase-3 operations schema with state/uniqueness constraints.
3. Implement upload create/stream/finalize/abort and finalized-state retry with configured outstanding upload/copy/cleanup admission caps from existing rows; retain ambiguous terminal keys and stop new work if cleanup stalls.
4. Implement object/inline range reads with validated single-range semantics and safe headers.
5. Preserve phase-3 direct inline-copy request identity/result behavior; object-file copy uses the same durable `CopyNode` path with independent key and source revision check.
6. Register letfs-owned `CopyNode` workflow/activities using the official Rust SDK and stable IDs.
7. Implement detached staging, keyset ID enumeration, stable mapping, item freeze/recheck, idempotent key creation and finite directory bounds plus overall copy node/byte/runtime ceilings.
8. Implement final publication with destination, lifecycle, quota, and aggregate-byte checks.
9. On terminal failure, mark discarding and durably remove uncharged staging; never discard published state.
10. Return 201 for direct inline copy and 202 for object/directory copy only after durable admission.

## Test Matrix

| Layer | Evidence |
|---|---|
| Unit | Classification, ranges, copy fingerprints, state transitions |
| Integration | Real PostgreSQL/S3 API for finalize, copy, independent keys, delayed cleanup |
| Concurrency | Barrier finalize quota race, stale overwrite, source edit/move/trash during copy, self/descendant destination, continuous-add termination and resource caps |
| Workflow/recovery | Restart per batch, lost provider/DB response, publish-response loss, cleanup retry, closed-before-admission replacement run |
| Contract | Go/Rust DTO fixtures, 201/202, `SOURCE_CHANGED`, range/upload errors |

## Planned Verification Commands

```bash
make test-integration TEST=object-storage
make test-integration TEST=uploads
make test-integration TEST=copy-races
make test-workflow TEST=copy-node
make test-integration TEST=storage-copy
```

## Failure Modes and Mitigations

| Failure | Risk | Mitigation |
|---|---|---|
| Object succeeds but DB publish fails | High | Pre-registered key and delayed cleanup row |
| DB publishes but response is lost | High | Return terminal result on retry; exclude published cleanup |
| Source mutates during copy | High | Freeze/recheck each item; return `SOURCE_CHANGED` |
| New child is mistaken for snapshot | Medium | Document omission semantics and no tree snapshot |
| Final quota fails after transfer | Medium | Atomic admission and cleanup; accepted no-reservation trade-off |

## Rollback

- Stop new uploads/copies, let admitted work checkpoint, and retain candidate/staged keys.
- Preserve upload/copy/cleanup rows across compatible binary rollback.
- Restore database plus matching objects for destructive rollback; database-only restore is insufficient.
- Do not delete uncertain objects until proven unpublished and due.

## Success Criteria

- [x] Upload failure never replaces old content or charges quota; identical finalize retry returns one result.
- [x] Object copies use independent keys and survive worker/provider/DB response failures.
- [x] Directory copy publishes no partial tree, charges once, and cleans failed hidden staging.
- [x] Races prove per-item revision, stable mapping, `SOURCE_CHANGED`, and permitted new-entry omission.
- [x] No contract claims snapshot, source pin, manifest, epoch, reservation, or resume semantics.

