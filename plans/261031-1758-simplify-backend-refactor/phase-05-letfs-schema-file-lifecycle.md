---
phase: 5
title: "Letfs schema, file lifecycle, partial workflows, and ZIP streaming"
status: completed
priority: P1
effort: "6–8 days"
dependencies: [4]
---

# Phase 5: Letfs schema, file lifecycle, and ZIP streaming

## Goal and mandatory scout

Remove generic Letfs operations/item/staging/export machinery while preserving the actual filesystem guarantees. Deliver nodes/files ownership, retry-safe upload/publication, partial copy/delete, durable object cleanup, and bounded HTTP ZIP streaming.

Sources: [final architecture](<../261031-1738-refactor-three-notes/inputs/openlet-final-architecture-status-to-processing (1).md>) and [numbered note](<../261031-1738-refactor-three-notes/inputs/1. xóa bảng operation của user và workspace, quá.md>).

Before execution, trace the moved equivalents of fs/copy.rs, deletion.rs, uploads.rs, exports.rs, maintenance.rs, artifacts.rs, processing.rs, tree/path/quota guards, HTTP handlers, Temporal workflows/registration, storage signing, Workspace facade, gateway timeouts, and their native tests. Current source uses operations for response replay and processing identity as well as execution tracking. Delete the latter only after relocating the required invariants.

## Schema responsibilities

| Entity | Kept responsibility |
|--------|---------------------|
| nodes | Shared file/directory structure, names, parents, identity and revisions |
| files | File-only payload/inline bytes/object reference, MIME and semantic fields |
| uploads | Shared user/processor transfer session, owner, multipart evidence, verification and finalization result |
| trash_entries | Detached root, original parent/name/actor, trashed/purging lifecycle |
| idempotency_keys | Non-natural request deduplication/admission under phase-4 rules |
| object_deletions | Transactional cleanup intent and required late-write evidence |
| index_deletions | Minimal collection/file/generation/vector-space cleanup intent that survives deletion of file metadata; no execution history |
| filesystems/quota_buckets | Resource lifecycle, freeze/deletion guards and atomic quota |

Delete operations, copy_items, deletion_items, export_attempts, nodes.staging_operation_id and the old file_data table after its required fields move into files. Do not move those tables wholesale into JSON receipts or create a replacement generic jobs table.

Semantic fields and media_type are removed from nodes, including directory rows. Artifact directory meaning belongs to its README.md file row. Phase 6 changes pipeline/search consumers; this phase must update schema/DTO readers and provide a coherent boundary without keeping old columns as fallback.

Edit the single Letfs baseline migration. Preserve same-filesystem parent references, live sibling uniqueness, root/NULL-parent/trash semantics, cycle prevention, checked counters, and correct indexes. Name uniqueness is independent of request idempotency: retry K1 replays; new K2 targeting an occupied name conflicts.

### Processing boundary required before removing operations

Implement the file-owned generation/readiness schema and port Letfs processing admission, attempt validation, dispatch, publication controllers and the Python HTTP transport callers described in phase 6 as part of this phase's operations removal. Include fs/indexing.rs and fs/search.rs: their current hydration SQL, payload operation_id, readiness/vector-space validation and cleanup queries also depend on operations. Port these consumers to file/generation identity here, including durable index_deletions intent before source rows disappear. Preserve the current callable pipeline/search against the new contracts; no placeholder controller, disabled processing/search route, or legacy SQL fallback is allowed. Phase 6 completes the semantic algorithm, worker split and final index behavior. Source-mutation transactions must already record generation intent and preserve stale-attempt fencing here.

## File and upload contracts

### Inline and download

Small inline content is written directly through the node/content resource API and nodes/files transaction, without an upload session. Preserve exact arbitrary bytes where the existing API supports them; do not accidentally narrow all inline content to text because text editing is one caller.

Single-file content reads return inline bytes with supported Range behavior or authorize then redirect to a presigned object GET. Preserve content type, safe disposition, TTL, and no-store treatment for signed credentials. The Workspace facade must preserve required headers and cancellation.

### Object upload

1. POST uploads validates ownership, destination/mode, declared size and preconditions; creates a session and unique immutable candidate key under receipt deduplication.
2. Return single PUT or native multipart transport. Client sends bytes directly to S3; backend-only byte relay remains only where the processor/internal contract actually needs it.
3. GET upload parts signs bounded requested part numbers and returns Cache-Control: no-store. Do not recreate the session on retrieval.
4. PUT uploads/{id}/completion freezes completion evidence, completes multipart where required, and verifies actual object evidence.
5. Under one database transaction, recheck lifecycle/revision/quota, create or replace nodes/files, record the finalized result, and enqueue the previous object key on replacement.
6. Repeated finalize returns the durable finalized result without another node or quota charge. Repeated abort respects terminal states and handles an unknown remote completion outcome.
7. Expired/aborted unpublished candidates enter durable cleanup. Never publish an object merely because a provider call timed out.

Use status open → completing → finalized, or aborted only when safe; expiration is timestamp-based. Keep immutable completion_parts/native MPU identity and reconcile CompleteMultipartUpload when its acknowledgment is lost. Do not compute a universal full-object MD5 from multipart ETags.

Before selecting verification details, inspect installed object_store APIs and the configured provider's documented capabilities. Validate size and supported checksum evidence; treat ETag as an opaque validator unless its exact semantics are proven. Reject an unsupported required checksum contract explicitly rather than silently downgrading it. Keep existing transfer thresholds/limits unless a concrete provider constraint requires a documented change.

User and processor share uploads. A successful processor transfer means bytes are available, not that nodes/artifacts are published or searchable. Keep processing association minimal (file/generation/output identity), not a second stage/retry state machine in uploads.

## Partial copy workflow

No whole-tree snapshot, staging/publish/discard cycle, item table, or rollback feature. A copied item becomes visible only after its bytes and database transaction are committed. If a later item fails, retain completed items and return a failed/partial outcome with destination root and bounded counts.

### Identity, traversal, and retry

- Admission uses one receipt and one stable logical copy/workflow ID. Letfs allocates destination identities; derive stable per-item destination IDs from the copy identity and source node identity, not names or a changing workflow Run ID.
- Carry bounded traversal state in Workflow history/Continue-As-New input. Fetch bounded pages; do not materialize the whole source tree in SQL or workflow payloads. Preserve configured depth/node/byte/history ceilings.
- Keep cumulative committed node/byte counters in workflow state and Continue-As-New input, and expose them through a scoped workflow Query. Advance counters only for effects newly recognized by that logical step, including acknowledgment-loss retries; terminal workflow result includes the final counters. This replaces old operation totals without a progress table. Verify continuity across restart and Continue-As-New.
- A bounded page captures selected source IDs and revisions/content identities. Revalidate each selected item at the effect boundary. Changed/missing selected sources or conflicting destinations stop the copy; new concurrent children may be included or omitted.
- Prevent copying a node into itself/its descendant. Use bounded traversal/high-water rules so continuous additions cannot keep a workflow alive indefinitely.
- Every Activity retry uses the same destination identity and immutable object candidate. An already committed destination is not reinserted or recharged.
- Capture destination-parent identity/revision preconditions in the logical item input. Never refresh preconditions during a retry to bypass an intervening user mutation.
- Account for response loss followed by destination mutation/deletion: stable IDs plus original revision guards must reject conflicting recreation, not resurrect deleted results or double-charge quota. Check parent/ancestor liveness in the same transaction.
- Copy bytes before publishing a file row. Revalidate source identity and destination/quota before commit; clean rejected candidate objects through durable intent.
- Record candidate cleanup evidence before an external write can become orphaned. Keep ambiguity for a write that can outlive cancellation; a successful early delete is not proof no object can appear later.

After a committed item, advance workflow traversal/checkpoint. Retry recognizes committed item identity even if its acknowledgment was lost. Use heartbeat checkpointing only as an optimization, not the sole durable proof of a database effect.

### Progress/status contract

POST nodes with source_id admits a copy and returns 202 + a scoped monitor Location. Use a thin Temporal-backed copy monitor, such as GET /v1/workspaces/{ws}/copies/{copy_id}, with matching internal ownership checks. It exposes destination root, terminal result/error and available progress; there is no copies database/job table.

Finalize the exact route and response in phase-1 OpenAPI before writing implementation. EVERY monitor read first reauthorizes current workspace/filesystem membership, then applies the admission-actor/current-owner rule to immutable admission identity. Removed members receive a non-enumerating not-found response. Never authorize arbitrary Workflow IDs or rely only on historical membership. The receipt retains the result/handle, not progress. Once Temporal retention removes monitor history, return the documented expired/410 outcome; copied resources remain ordinary resources.

## Delete, trash, and purge workflows

- Keep trash_entries. Trash detaches a subtree root without copying it; restore preserves IDs and checks parent/name conflicts and entry identity.
- Purge atomically marks the entry purging; restore is then rejected. Filesystem deletion marks deleting/frozen so no new writes or processing publication can escape traversal.
- Traverse existing nodes directly in bounded post-order/leaf batches. No deletion_items snapshot. Repeat a batch by querying remaining work under the same root; missing already-deleted nodes are success.
- Delete file rows/nodes, subtract the bytes/nodes actually removed, and enqueue objects in the same transaction. Retry must not debit quota twice.
- Preserve partial progress on failure. Permanent deletion can continue from remaining rows; do not add rollback or reconstruct the deleted tree.
- Include detached trash/artifact forests, not only the live root. Retain a durable lifecycle/tombstone preventing late writers or delayed requests from recreating deleted resources.
- Coordinate source/ancestor lifecycle, uploads and processing fences. Async workers cannot publish into a trashed/purging/deleting ancestor after its guards change.
- Continue-As-New uses bounded cursors and stable logical operation identity; no full item list or arbitrary unbounded history.

## Object cleanup

Retain object_deletions as an outbox. Metadata removal/replacement and enqueue happen in the same transaction. Reuse the existing five-minute Temporal maintenance schedule with a non-overlapping execution policy and idempotent bounded batches; do not add a broker, per-object workflow, scheduler, or DB lease framework.

Before deleting, check active references and upload/write ownership. Remove obsolete copy_items/export_attempts checks only after replacing their actual reference/ambiguity responsibilities.

A successful DeleteObject and an expired presigned URL do NOT close an in-flight PUT. Keep ambiguous-write/tombstone evidence and re-delete conservatively until provider/transport evidence proves no late write can recreate the key. Without that proof, do not prune ambiguity based on a guessed grace period. Multipart abort/lifecycle is a safety net, not a replacement for cleanup intent.

The closure rule is explicit: prune only after all writer capabilities are closed, every backend-controlled write/complete/abort request has a known terminal outcome, and a post-closure delete is acknowledged. URL expiry or a current HEAD absence alone cannot establish this for arbitrary in-flight presigned PUTs. For such unresolved writes, retain one compact tombstone per immutable key indefinitely and re-delete at a low bounded cadence (retain the current one-day reschedule), using capped maintenance batches. Count unresolved tombstones against the existing MAX_CLEANUP_BACKLOG admission guard, including rows whose last delete succeeded; do not allow state='deleted' to hide ambiguity from that bound. Preserve MAX_OUTSTANDING_STORAGE safeguards when operations disappears. The trade-off is eventual admission rejection when uncertainty fills the configured ceiling, rather than unsafe evidence deletion. No global claim that every tombstone expires, no arbitrary fixed grace, and no new reconciliation service.

Do not claim versioned-bucket deletion removes all physical versions. Preserve/document the configured provider's versioning policy and operational obligations.

## HTTP ZIP streaming

- GET nodes/{id}/archive authorizes and preflights a bounded metadata enumeration for path safety, duplicate names, empty directories, file count, declared bytes, and download duration.
- Reuse async_zip and useful existing validation, then stream inline/S3 bytes incrementally with bounded buffers/backpressure. No whole-folder bytes in RAM/disk, S3 ZIP object, export workflow, background archive job, or export_attempts.
- No whole-tree snapshot is promised. Record selected file identity/path/revision during enumeration; if it changes or disappears when read, fail the stream instead of silently omitting it. Concurrently added entries may be absent.
- Client disconnect cancels the writer and outstanding storage reads; a retry restarts the download. Preserve empty directories and safe Content-Disposition.
- Enforce limits during streaming too, not only preflight. A failure before headers returns a problem response; after headers, abort the body so the archive cannot look complete with missing data.
- Update Letfs, Workspace proxy and Envoy stream/timeouts together. Current pre-move Envoy route timeout is 120s and Go WriteTimeout is 125s; choose explicit stream deadlines without globally disabling protection.
- Delete ExportArchive workflow registration/Activities, S3 export keys, status APIs, clients, tests and config that exist only for old ZIP jobs.

## File inventory

| Action | Target files/group | Size | Test impact |
|--------|--------------------|------|-------------|
| Modify | apps/letfs/migrations/0001_initial.sql; node/file models and SQL | Large | Ownership/constraints/fresh baseline |
| Rewrite/delete | src/fs/copy.rs, deletion.rs, exports.rs and associated workflows | Large | Partial progress, retry, bounded streaming |
| Modify | src/fs/uploads.rs, maintenance.rs, artifacts.rs, processing.rs, indexing.rs, search.rs | Large | Transfer/result/cleanup/fence safety and live search SQL port |
| Modify | src/http, storage clients/signing, Temporal registration | Medium | Resource routes and transport |
| Modify | Workspace facade, contracts, Envoy config, native tests/new E2E | Medium | Entire public-to-storage path |
| Modify | apps/letfs-processing/src/openlet_processor/activity.py, its HTTP/config/input/output models and focused contract tests | Medium | Replace every operation-shaped processing/enrichment/index endpoint and payload before old routes disappear |
| Update | Owning data-model/API/workflow/operations docs and DBML | Medium | No obsolete table/job claims |

## Steps and execution checklist

- [x] Inventory operations/item/staging/export references and map retained invariants to the owners above.
- [x] Edit the baseline and node/file repositories/DTOs; preserve ID/path/readonly/quota semantics and update all known consumers.
- [x] Port Python activity.py and its HTTP/config/models/tests to the accepted file/generation/output resource contracts in the SAME slice as Letfs controllers. The real parser/worker must remain callable; do not defer removed-endpoint callers to phase 6.
- [x] Implement Letfs receipts and scoped monitors under phase-4 admission/TTL rules.
- [x] Replace copy traversal/publication with stable per-item identity and partial-progress workflow semantics.
- [x] Replace delete/purge item tables with bounded direct traversal and atomic accounting.
- [x] Implement shared upload transport/completion reconciliation and provider-aware verification; remove legacy transports.
- [x] Update durable cleanup/reference checks and late-write protection before deleting old tables.
- [x] Replace ZIP export with an HTTP stream across the complete facade/gateway path.
- [x] Delete obsolete SQL, DTOs, endpoints, client methods, workflows, Activities, config, tests, imports, and dependencies. No compatibility aliases.
- [x] Make the new file/upload/copy/trash/ZIP API E2E green, run focused native checks, and update owning docs.

## Validation matrix and gate

| Risk | Lowest useful proof |
|------|---------------------|
| Namespace/ID/path/revision races | Real PostgreSQL native integration, not duplicated endpoint matrices in E2E |
| Strict create/copy request retry | Same result/handle; changed payload conflicts; quota charged once |
| Copy progress across Continue-As-New/restart | Scoped Query and terminal result preserve cumulative committed counts without SQL progress state |
| Copy acknowledgment loss and source/destination changes | Barrier-controlled real DB/S3 plus one public recovery journey |
| Direct multipart lost completion acknowledgment | Real S3 complete/HEAD reconciliation, persisted part receipts |
| Wrong checksum/size and stale replace | No publication; previous bytes/metadata/quota remain correct |
| Purge/restore/delete retry | Terminal guards, same IDs on restore, no duplicate debit or resurrection |
| Late write after first successful cleanup | Actual delayed storage write appears and is subsequently removed |
| ZIP paths/empty dirs/errors/disconnect | Independent ZIP reader, real streaming through gateway, bounded cancellation |
| Structural deletion of detached data | All roots/forests removed; admitted destructive work survives restart |

- [x] No operations/copy_items/deletion_items/export_attempts/staging_operation_id/file_data remains in current implementation or app baselines.
- [x] File-only fields are in files; no directory semantic metadata or MIME fallback remains.
- [x] Every visible copied/published file has verified bytes; partial failure retains committed work.
- [x] Upload, trash, cleanup and ZIP contracts pass real boundary tests and new API E2E.
- [x] Configured resource/history limits remain enforced.

## Risks and recovery

The dangerous simplification is deleting evidence with the old execution tables. Preserve effect identity, lifecycle guards, source fences and object ambiguity explicitly; reject any proposal to rely on retries alone.

Local-emulator success is not universal provider proof. Perform opt-in selected-provider evidence checks before declaring that provider verified. Reset only identified development/test databases after backup; revert/restore a coordinated checkpoint if needed. Do not keep old schema/code for rollback.

Next: [phase 6](./phase-06-processing-search-final-gates.md).

## Execution checkpoint

The current source inventory confirms: copy_items/staging own copy visibility and ambiguous write references; deletion_items owns deletion traversal; operations owns processing identity/readiness, dispatch, copy progress and export jobs; file_data and nodes jointly own file payload and semantic fields. These invariants move to workflow history/receipts, resource lifecycle, files generations, uploads and cleanup outboxes as described above. None can be deleted by renaming the old tables.

The first independent implementation slice replaces ZIP export jobs with bounded request-owned HTTP streaming. Affected owners: Letfs fs/archive + storage/archive + HTTP routes, Workspace archive authorization/proxy, Envoy archive-only timeout, Letfs config/main/maintenance/baseline, native ZIP/replay tests, contracts and owning docs. No running application database is being reset; schema checks use isolated testcontainers. The phase-4 invitation E2E gate remains dependent on the subsequent resource-node API slice.


### Node and upload resource slice

Native Gin routes now expose strict nodes/create/read/resolve/patch/content and object upload resources. Route handlers receive their action explicitly; escaped Gin route names are never used to infer resolve versus list. The old public/internal user upload action/bytes/POST-parts/finalize routes are deleted.

Upload admission uses caller/filesystem-scoped `idempotency_keys`, committed atomically with the session. Incomplete receipts stay pinned; finalized/aborted/expired admissions start a 24-hour TTL once. Filesystem deletion also completes cancelled upload receipts. Single PUT binds size/Content-MD5 and an immutable conditional key. Multipart freezes ordered opaque ETag receipts and reconciles a lost acknowledgment through the unique candidate key; no synthetic full-object MD5 or MD5-shaped ETag requirement remains. Public GET parts signs bounded part numbers. Source/output URLs for processor callers use the internal S3 endpoint.

The combined gateway run passes **8/8** for exact inline/revision behavior, ZIP, mounted path resolution, single object bytes/Range, stale replacement, lost multipart acknowledgment, publication quota rejection, and invitation/membership revocation. Full processing identity, shared processor terminal publication state, copy/partial workflows, purge/deletion traversal and obsolete table removal remain open; this slice does not close phase 5.

Focused direct-storage native verification passes **4/4**, including real S3 protocol evidence, current HTTP content behavior, processor internal signing, admission receipt TTL/reuse, concurrent completion/abort and cleanup backpressure. The other 18 integration cases passed in the preceding broad run. All-target Clippy, Workspace unit/vet, Python nonparser **69/69**, Ruff, TypeScript, OpenAPI component/reference and Markdown-link checks pass. Test runners and containers have exited cleanly.

### Shared transfer completion and artifact-forest cleanup

Processor uploads now share the terminal transfer states with user uploads. Finalization saves an immutable transfer receipt; attaching a published artifact does not rewrite it. Unattached finalized outputs remain eligible for supersession cleanup. The Python client reconciles completing/finalized outputs rather than requesting more capabilities or resending object bytes.

Invalidation no longer creates artifact-discard operations or deletion-item rows. Detached roots outside filesystem roots, trash and active copy staging are drained directly in bounded leaf batches. Remaining rows preserve partial cleanup progress; actual removal, quota and object cleanup intent commit together. General copy/purge traversal and processing identity still retain their old owners and remain open work.

### Current execution checkpoint — file-owned processing and natural deletion

Processing admission/publication/indexing and Python consumers now use file/generation identity; CPU and I/O workers operate independently. Purge/filesystem deletion no longer allocate operation/item rows: admitted resource lifecycle plus remaining nodes preserve progress, with at most 64 leaves removed and accounted per batch. New trash resources and current cross-language child input are implemented. Fresh integration, gateway recovery, telemetry and replay evidence is in [validation.md](validation.md#file-generation-recovery-and-direct-deletion-checkpoint--2026-11-01).

Copy remains the old machinery's final owner. Its replacement must remove operations/copy_items/staging and every old copy endpoint/monitor/registration/test assumption together. Phase 5 remains in progress; phase 6 final acceptance is not complete.

### Completion checkpoint

The former copy implementation and its operations/copy_items/staging machinery are removed. Current bounded workflow traversal commits ordinary nodes with stable per-item identity, preserves partial output and carries progress across Continue-As-New. Candidate cleanup intent precedes external writes. Processing/search consumers use files/generations, deletion traverses remaining nodes, and ZIP streams directly through the facade/gateway.

Final current-source proof: 32/32 API E2E including coordinated restore, lost-copy/MPU acknowledgments, source changes and real worker restarts; 26/26 native Letfs integration plus tracing/continuation; both Go integration/workflow suites; current Go/Rust history replay. See validation.md for exact scope, earlier failed attempts and external-provider limits. Phase 5 is complete; phase 6 retains final environment/recovery and documentation reconciliation until their checks finish.
