# Application RPC surface ledger

This ledger records implemented application RPC boundaries. The [authorization matrix](authz/action-resource-matrix.md) owns action/resource admission. Protobuf sources in `proto/` own native RPC contracts; the [API contract guide](../../docs/api-contracts.md) describes public HTTP transport.

## Owners and current foundation

| Service | Caller | Generated contract | Implementation state |
|---|---|---|---|
| AccountService | Workspace service | GetUserSummaries, GetVerifiedEmails | Implemented; active-user lookup, verified Clerk emails, exact caller response scope |
| FilesystemService | Gateway carrying a verified public user | All public operations assigned below | Active Go handlers; direct public HTTP and native gRPC use the same filesystem operations |
| StorageAdministrationService | Explicit storage-owner service/job | CreateBucket, CreateFilesystem, FreezeBucket, ListBucketFilesystems, CompleteBucketDeletion, ReleaseProvisioning | Active Go handlers; caller credentials restrict storage-owner operations |
| IngestService | Ingest service plus stored generation/attempt scope | All ingest operations assigned below | Active Go handlers called by Python letfs-ingest through generated gRPC; dedicated ingest credentials; no public ingress |

Workspace exposes its public HTTP API; Account creates workspaces through native Temporal remote Activities. Native Temporal children/remote Activities remain native durable orchestration. Health uses standard gRPC health. External Clerk, S3 signed transfers, Qdrant and OpenRouter keep provider-native protocols.

## Complete filesystem operation assignment

All public operations below belong to `FilesystemService` unless stated otherwise. Filesystem identity is explicit; aliases/mount descriptors provide path context only. Source and destination cannot override the authenticated actor or cross filesystem boundaries.

| Operation | Native RPC | Contract |
|---|---|---|
| Bucket usage | GetBucketUsage | Explicit bucket-read action; decimal counters and upload limits; cannot expose siblings through an FS grant |
| Filesystem/root status | GetFilesystem | Storage IDs/lifecycle; no business resource mapping |
| Create directory/inline file | CreateNode | Typed variants, exact inline bytes, scoped idempotency; HTTP 201 + relative Location + ETag |
| List/stat/resolve/batch-stat | ListNodes, GetNode, ResolveNode, BatchStat | Bounded pages/locators, scoped cursor, optional fields, decimal revisions |
| Rename/move | UpdateNode | Observed identity/revision, cycle/depth/artifact checks; HTTP If-Match |
| Read payload | GetDownload | Inline bytes or signed URL descriptor; HTTP 200/206/307; single Range, revision query, selected MIME + attachment/nosniff/no-store |
| Replace inline payload | ReplaceContent | Bytes/revision, bounded payload; no public object-upload shortcut |
| Admit/monitor copy | CreateCopy, GetCopy | HTTP 202 + relative Location; partial-progress/expired-410 result; initiator/current inspect-any authority |
| Processing status/reprocess | GetProcessing, ReprocessNode | Read/run actions; immutable generation intent and scoped request key |
| Request-owned ZIP | StreamArchive | Metadata first, <=64KiB chunks, terminal non-OK invalidates partial bytes; HTTP adapter streams raw ZIP, aborts after headers on failure |
| Filename and semantic search | SearchFiles, SemanticSearch | Exact filters/sort, actor/mount/FS/query/space-bound cursor, bounded hydrated results |
| Upload admission | CreateUpload | Object-only for public users; immutable initiating actor, destination/revision and candidate identity |
| Upload status/abort | GetUpload, AbortUpload | Initiating actor plus current action; immutable completed result |
| Multipart URLs/finalize | GetUploadParts, CompleteUpload | Bounded parts, opaque ETags/checksum/size, saved preconditions; signed S3 bytes remain direct |
| Trash detach/list/get | TrashNode, ListTrash, GetTrash | Detached IDs hidden; trash-entry identity retained; bounded cursor |
| Restore/purge | RestoreTrash, PurgeTrash | Revision/lifecycle, original parent/name, explicit Owner purge action and durable purge identity |
| Generic provisioning | StorageAdministrationService methods above | Caller-preallocated UUIDv7, scoped request key, local tombstones, no provision key |
| Filesystem deletion | Generic DeleteFilesystem workflow/Activities | Explicit storage-job authority, bounded local cleanup, retained tombstone; no business identifier |

## Ingest operation assignment

All application calls below belong to the private `IngestService`. Go handlers live in `apps/letfs/internal/grpc`; Python callers live in `apps/letfs-ingest/src/letfs_ingest/activity.py`. A caller credential never replaces the recorded file/generation/stage/attempt checks.

| Operation | Native RPC | Contract |
|---|---|---|
| Parse prepare | PrepareParse | File/generation/attempt number+UUID; already-complete or typed input descriptor; inline bytes/signed source; finite output limits |
| Parse output admission | PrepareParseOutput | Relative path, storage mode, exact size/checksum; immutable output upload descriptor |
| Parse publish/abort | CompleteParse, AbortParse | Exact upload/directory manifest or bounded semantic failure code; stale attempt cannot publish |
| Enrichment prepare/output | PrepareEnrichment, PrepareEnrichmentOutput | Whole-tree bounded inventory, source payload identity, replacement upload |
| Enrichment publication/failure | CompleteEnrichment, FailEnrichment | Exact node/path/metadata/upload manifest; atomic rename/link/quota/publication |
| Index prepare/complete/fail | PrepareIndex, CompleteIndex, FailIndex | File/generation plus exact model/collection/dimension; no false index-ready acknowledgment |
| Output upload status/parts/finalize | GetOutputUpload, GetOutputUploadParts, CompleteOutputUpload | Stored generation/stage/attempt scope; same transfer receipts and reconciliation |
| Inline output bytes | WriteOutputBytes | Bounded raw protobuf bytes under the recorded output scope; no signed credential forwarding |

Ingest never imports an app-local generated package. All client and server interfaces generate into the independent `openlet-python` wheel. Typed parse/enrichment manifests, generation/attempt scope, vector-space identity and output-transfer receipts are included. The deployed ingest app consumes this wheel independently of Go service source.

Public upload publication returns the node ID/revision; private output completion returns the upload ID/status/size receipt. Receiving inline output bytes does not publish an artifact. A native multipart transfer signs part numbers into bounded `{part_number, transfer}` items; signed PUT descriptors include required headers, exact content length and expiry. Native RPC uses int64 and bytes; HTTP adapters retain decimal-string counters, flattened metadata, response status/headers and raw byte semantics. GetNode has a generated HTTP annotation. Explicit public HTTP routes and byte/ZIP adapters live in `apps/letfs/internal/http`; no generated HTTP gateway runs in production.
