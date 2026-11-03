# Go filesystem parity ledger

Status: implementation inventory; unchecked operations are not implemented acceptance. Rust remains the running reference. All RPCs below are defined in `packages/contracts/proto/openlet_api/letfs/v1/letfs.proto`. Actions refer to the actual filesystem unless explicitly marked bucket. Shared machine errors retain `ErrorInfo` through `packages/go/rpc/errors.go`.

## Operation owners

| RPC | Rust application owner | Action / exceptional authority | Required result and error contracts |
|---|---|---|---|
| GetFilesystem | `fs/mod.rs`, `http/mod.rs::get_fs` | `node_read` | FS/bucket/root UUIDs, state; missing/inactive resource hidden |
| GetBucketUsage | `http/mod.rs::get_bucket` | `bucket_read` on quota bucket | Decimal byte counters, upload limits; independent FS permission insufficient |
| CreateNode | `fs/nodes.rs::create` | `node_create` | Actor/FS/key receipt; directory or exact inline bytes; parent guard, quota, depth, sibling conflict |
| GetNode, BatchStat | `fs/nodes.rs::read`, `fs/paths.rs::resolve` | `node_read` | Live same-FS ancestry; batch 1–100, atomic failure; detail context retained |
| ResolveNode | `fs/paths.rs::resolve`, `fs/nodes.rs::read` | `node_resolve` | ID/path/cwd; longest boundary mount; root alias; no detached metadata |
| ListNodes | `fs/nodes.rs::read` | `node_list` | Scoped UUID keyset cursor, 1–100 (default 50), context omitted |
| UpdateNode | `fs/nodes.rs::modify` | `node_update` | Rename/move, revision and expected identities, cycle/depth, read-only artifacts |
| ReplaceContent | `fs/nodes.rs::modify`, `fs/artifacts.rs` | `content_write` | Exact bounded bytes; revision/quota; old payload/artifact cleanup; generation intent |
| GetDownload | `http/mod.rs::inline_content`, `fs/ranges.rs` | `content_read` | File MIME/name/logical ETag/size; bytes oneof preserves empty inline; object direct URL; optional positive revision |
| CreateCopy | `fs/copy.rs::admit` | `copy_create` + source `node_read` | Same-FS scoped admission receipt, deterministic destination, captured revision/payload, bounded job |
| GetCopy | `temporal/copy_workflow.rs::monitor` | `copy_read`; other actor also `copy_inspect_any` | Actor/resource binding; progress/status/error and decimal counts; expired history 410 |
| TrashNode | `fs/trash.rs::trash` | `node_trash` | Detach only root, revision bump, retained descendants/charged bytes, entry identity |
| ListTrash, GetTrash | `fs/trash.rs::list/entry` | `trash_read` | Entry UUID/node/nullable original parent/name/actor/state/time; scoped cursor |
| RestoreTrash | `fs/trash.rs::restore` | `trash_restore` | Current entry, original live writable parent, original name; no overwrite/reparent; purge conflict |
| PurgeTrash | `fs/deletion.rs::prepare` | `trash_purge` | Missing entry means 204; otherwise durable purging entry (202); dispatch belongs to Phase 5 |
| CreateUpload | `fs/uploads.rs::create/insert` | `upload_create` | Public object-only; immutable actor/destination/size/MD5/key; single/multipart; no-store capabilities |
| GetUpload | `fs/uploads.rs::status` | `upload_read` + initiating actor | Excludes ingest sessions; terminal status cannot renew write capabilities |
| GetUploadParts | `fs/uploads.rs::part_urls` | `upload_sign` + initiating actor | Bounded unique part batch; exact part sizes and signed headers; no renewal after completing |
| CompleteUpload | `fs/uploads.rs::finalize` | `upload_complete` + initiating actor | Freeze contiguous opaque receipts; provider HEAD/complete/HEAD; revalidate/publish once; immutable result |
| AbortUpload | `fs/uploads.rs::abort` | `upload_abort` + initiating actor | Terminal no resurrection; retain ambiguity/cleanup evidence; finalized abort conflicts |
| CreateBucket, CreateFilesystem | `fs/mod.rs::ensure_*`, `fs/provisioning.rs` | Explicit authenticated owner service | Caller-preallocated UUIDv7 IDs; receipt keyed by service/operation/key; immutable fingerprint; no provision key |
| FreezeBucket | `fs/provisioning.rs::freeze` | Explicit authenticated owner service | Unknown stable ID tombstone fences late creation; cannot freeze another caller's bucket |
| ListBucketFilesystems | `fs/provisioning.rs::filesystems` | Explicit authenticated owner service | Bounded ordered UUID keyset; includes deleting resources until terminal |
| CompleteBucketDeletion | `fs/provisioning.rs::complete` | Explicit authenticated owner service | Frozen bucket, no live FS/bytes; retained tombstone |
| ReleaseProvisioning | `fs/provisioning.rs::release` | Explicit authenticated owner service | Validate exact bucket/FS/root; complete existing receipts; no alternate key/table |

GetDownload carries the complete descriptor; Range parsing and HTTP 206/307/416 handling belong to the byte adapter, not an extra application RPC. Optional protobuf scalars preserve missing revision/cursor/metadata. Protobuf int64 JSON uses decimal strings. Creation and mutation ETag/Location/status mapping is Phase 6 over these same application methods; no new public route is enabled here.

## Shared failure contracts

- Invalid names/locators/mounts/media types/size/cursors/UUIDs: `VALIDATION` / InvalidArgument.
- Missing/foreign/detached resource: `NOT_FOUND` / NotFound; cross-FS mount: `CROSS_FILESYSTEM_UNSUPPORTED` / Aborted (409).
- Absent revision/expected identity: `PRECONDITION_REQUIRED` / FailedPrecondition (428); mismatch: `REVISION_MISMATCH` or `TARGET_MISMATCH` / FailedPrecondition (412).
- Sibling collision: `NAME_CONFLICT` / AlreadyExists (409); request-key mismatch: `IDEMPOTENCY_CONFLICT` / Aborted; lifecycle/immutable create mismatch: `SCOPE_CONFLICT` / FailedPrecondition.
- Read-only artifacts: `ARTIFACT_READ_ONLY` / PermissionDenied; denied action: `FORBIDDEN` / PermissionDenied. Missing actor: Unauthenticated.
- State failures retain their Rust codes: `NOT_DIRECTORY`, `NOT_FILE`, `CYCLE`, `RESOURCE_LIMIT`, `QUOTA_EXCEEDED`, `BUCKET_FROZEN`, upload/copy/entry conflicts. No provider/SQL response body is exposed.
- Graph, SQL and provider failures: `DEPENDENCY_UNAVAILABLE` / Unavailable; context cancellation/deadline preserved. Invalid ranges retain `INVALID_RANGE` (416); expired copy retains `COPY_EXPIRED` (410).

Exact operation-specific branches remain source-owned; port them with the corresponding tests instead of manufacturing a second error-policy catalog.

## Regression references

`apps/letfs/tests/integration.rs`: exact bytes, namespace/revisions/quota, downloads/ranges, mounts, uploads, multipart, provisioning and receipts. `tests/artifacts/mod.rs`: readonly ancestry and alias/cwd boundaries. `tests/copy/mod.rs`: deterministic identity, partial commit, ambiguity and cleanup. `tests/deletion/mod.rs`: bounded leaves/accounting/retry. `src/fs/paths.rs` and `ranges.rs`: path/alias/range unit boundaries. New Go tests use their own PG/S3/graph resources and real authenticated gRPC.

## Deferred to their owning phase

Phase 5: GetProcessing/ReprocessNode (`fs/artifacts.rs`), SearchFiles/SemanticSearch (`fs/search.rs`), StreamArchive (`fs/archive.rs`), all IngestService RPCs (`fs/processing.rs`, `enrichment.rs`, `indexing.rs`, upload authority variants), full copy/deletion/maintenance workflows and object cleanup. Phase 4 ports their persistent core admission/state boundaries; no unimplemented workflow returns success.

Phase 6: public HTTP/native gateway registration and routes, Workspace proxy deletion, real runtime/consumer switch and Python rename. Phase 7: Rust deletion and clean whole-stack acceptance.
