# Durable execution

Service-owned workflows use pinned Go/Python SDKs. File parsing, semantic enrichment and search indexing run as three whole-source Python activities scheduled by letfs. Implementation reports and the [completed plan](../plans/261031-1758-simplify-backend-refactor/plan.md) record verification evidence and remaining external release checks.

## Ownership and communication

| Owner | Workflow/activity code | Application core |
|---|---|---|
| Account | `apps/account/internal/temporal/` | `internal/user/` |
| Workspace | `apps/workspace/internal/temporal/` | `internal/workspace/` |
| letfs | `apps/letfs/internal/temporal/` | `internal/filesystem/`, `internal/storage/` |

Official Go SDK workers run inside the corresponding service. One private namespace per environment, explicit owner queues. Workflow code is deterministic and performs I/O only through activities. HTTP/activity adapters reuse application functions. No file bytes, credentials or growing traversal arrays in history.

Account onboarding admits its initial workspace through the Workspace Activity, saves the returned ID, then awaits a Workspace child workflow on `openlet-workspace`. Its user lifecycle is admitted before dispatch; an owner-managed five-minute schedule recovers the commit/start gap and classifies terminal workflows. Workspace uses named remote Activities on `openlet-letfs` for storage ownership and awaits `DeleteFilesystem` children. Both Go owners reconcile bounded durable admissions at startup and every five minutes. The same workflows scan canonical Account/Workspace IDs in keyset pages of 100, including retained nonactive records, and use Continue-As-New between pages. A failed Account page or Workspace resource does not block later pages or IDs; the full scan reports any failure. There is no whole-scan execution deadline that repeatedly strands later pages. Existing schedules retain their operator state and timing while startup updates the owned workflow action. Account publishes its self relationship before completing onboarding; Workspace synchronizes inheritance before completing creation and disables inherited access before destructive cleanup, then synchronizes its final tombstone. HTTP remains the transport for providers and resource/byte access.

## Catalogue

| Workflow | Owner | Durable work |
|---|---|---|
| `OnboardUser` | Account | Internal identity, initial workspace/storage, Clerk claim |
| `CreateWorkspace` | Workspace | Workspace/Owner, storage provisioning, activation |
| `DeleteWorkspace` | Workspace | Deny access, freeze bucket, remove every filesystem, finalize tombstone |
| `SyncWorkspace` | Workspace | Read current business state and synchronize graph relationships before mutation success |
| `ReconcileAccounts` / `ReconcileWorkspaces` | Respective owner | Recover dispatch gaps and synchronize bounded canonical ID pages |
| `CopyNode` | letfs | Bounded traversal and per-item visible commits with partial results |
| `PurgeTrash` | letfs | Direct leaf batches for either node kind |
| `DeleteFilesystem` | letfs | Remove live/trash/artifact/upload state |
| `StorageMaintenance` | letfs | Expire uploads, recover admissions, drain detached forests and reclaim objects |
| `ProcessFile` | letfs | `process_file` on `openlet-letfs-cpu`, then `enrich_file -> index_file` on `openlet-letfs-io` |

Workspace role/owner changes and new accepted memberships commit canonical state, then await an ID/revision/lifecycle-scoped synchronization workflow before normal success. A disconnected caller does not cancel durable work; a synchronization failure after commit is reported explicitly. Name-only updates and invitations without changed membership remain direct. Account reconciliation publishes each page in one bounded relationship write; a failed page does not block later pages and the full scan still reports failure.

Direct operations: auth, profile and invitation mutations, path/stat/list, mkdir, rename/move, inline text edits, upload transfer/finalize, trash/restore. Physical object cleanup follows logical deletion asynchronously.

## Activity sequences

### OnboardUser

HTTP admission commits a user keyed by unique Clerk subject, then starts `onboard/<subject>`. `OnboardUser` awaits the `CreateWorkspace` child using stable `initial-workspace/<user-id>` identity. Workspace allocates its own ID; `SaveInitialWorkspace` records the returned mapping before `PublishClerkUserID` merges backend-owned metadata. `CompleteOnboarding` makes the user active. A Clerk outage retries publication; completed users never recreate a deleted initial workspace. Terminal failure remains visible on the user lifecycle. `ReconcileAccounts` checks bounded pending users at startup and every five minutes, starts missing executions with duplicate rejection and preserves active users.

### CreateWorkspace

HTTP commits the provisioning Workspace, owner membership and `idempotency_keys` receipt atomically before dispatch. The Account child admits them in `EnsureWorkspace`. `ReserveStorage` saves stable bucket/filesystem IDs before remote `CreateBucket` and `CreateFilesystem` Activities on the Go owner queue. LetFS validates the creating service and generic storage lifecycle; no provision key or business mapping exists there. `ActivateWorkspace` saves the returned root reference, then `SyncWorkspaceRelationships` publishes storage inheritance before creation completes. `ReleaseProvisioning` unpins remote receipts after references are durable; `CompleteWorkspaceCreation` completes the Workspace receipt. Reconciliation recovers gaps using saved IDs. Completed receipts expire after 24 hours; stable IDs and tombstones prevent duplicate allocation or resurrection. Permanent failure stays visible on Workspace and its owner can delete partial storage.

### DeleteWorkspace

HTTP `BeginDeletion` checks the delete action before taking the Workspace lock, then rechecks canonical scope/revision/lifecycle and commits the deleting tombstone before dispatch. The remote `FreezeBucket` prevents new provisioning/growth. Keyset `ListBucketFilesystems` includes all filesystems in the bucket; Workspace awaits a `DeleteFilesystem` child for each, with ABANDON parent-close policy. Traversal cursor stays in workflow input/history across Continue-As-New, after each child completes. `CompleteBucketDeletion` requires no active filesystem/upload and zero charged usage. `CompleteWorkspaceDeletion` removes invitations and nonowner memberships, retaining the owner-readable tombstone. Cancellation uses a disconnected workflow scope. Terminal failures preserve deleting state with an error code. Recovery rechecks that durable tombstone and an explicitly closed execution before resuming; deleted resources never restart. A recovery run uses distinct child execution IDs while retaining the same logical deletion key, and frozen-bucket enumeration skips already-deleted filesystems. Completing the bucket releases receipts from partial provisioning.

### CopyNode

HTTP commits a scoped copy receipt and immutable admission before dispatch. `CopyItem` publishes one ordinary node after verified storage copy and atomic quota checks; deterministic destination IDs and captured parent/source revisions protect response-loss retries. `NextCopyItem` reads bounded high-water children; `FinishCopyFile` admits processing once after a logical file subtree completes. Artifact descendants stay read-only and do not receive independent processing intents.

The workflow carries at most 128 frames, one selected item and cumulative counts across Continue-As-New every 100 steps. Node/byte/depth ceilings and a one-hour deadline bound work. A failure returns an explicit partial result and preserves committed nodes; no staging, rollback or item table exists. `CompleteCopy` starts the receipt's 24-hour TTL. The scoped monitor reads Temporal admission/progress, checks current `copy_read` permission and requires the initiating actor or `copy_inspect_any` action. Missing retained history returns 410.

### PurgeTrash

`BeginPurge` claims the trash entry, excluding restore. `DeleteNodesBatch` follows one bounded branch and removes at most 64 leaf siblings, with quota debit and object-deletion intent in the same transaction. Remaining nodes preserve progress after response loss; no deletion item or execution-state table is used. The trash entry disappears when its root is removed. Every purge uses this workflow. A purging entry fences restore and is sufficient for maintenance to recover a lost dispatch.

### DeleteFilesystem

`BeginDeletion` disables access, aborts unattached open transfers and preserves immutable-key cleanup evidence under the filesystem lock. Shared `DeleteNodesBatch` queries at most 64 leaves across all roots, including trash and detached artifacts. Each batch removes metadata, debits actual usage and records cleanup atomically; the last batch retains a deleted filesystem tombstone with no nodes or charged bytes. Continue-As-New carries only immutable filesystem/entry identity after 200 batches. Lifecycle guards reject late copy/upload/publication attempts; no SQL traversal snapshot is required.

### StorageMaintenance

A finite five-minute Schedule with overlap SKIP runs bounded `ExpireUploadsBatch`, `ReconcileResourcesBatch` and `DeleteObjectsBatch`. Reconciliation drains detached artifact forests, recovers purging entries and incomplete copy admissions, and reconciles processing/index cleanup. A closed copy completes its receipt without deleting partial output. Unknown/unavailable history never proves abandonment. Copy writers register candidate evidence before I/O; unresolved write counts survive worker death. Cleanup rejects referenced keys, and an attempted deletion permanently fences that copy candidate from later publication/reuse. Unresolved late writes retain compact daily cleanup tombstones.

Inspect S3 per-key errors and retry. Physical GC never debits logical usage again. Keep bucket attribution while cleanup exists. No automatic age-based trash purge or counter repair.

Processing reconciliation runs within existing bounded maintenance work. It starts committed intents missing a workflow, reconciles closed workflows, and cleans unpublished output sessions. Unknown Temporal status never authorizes failing an active job.

### ProcessFile

Eligible source publication commits a monotonic desired generation on `files`. PDF/DOCX/PPTX/XLSX parse first; direct text/CSV/image sources skip parsing. Dispatch starts `process-file/<file-id>/<generation>` with `{source:{file_id,generation},parse_required,enrichment_required}`. Bounded maintenance recovers a lost start and records explicit failure after a closed workflow; unknown Temporal state never authorizes failure. Manual reprocessing commits its caller-scoped receipt and generation before dispatch.

Parse/enrichment requests carry the existing source file ID and generation; the dedicated ingest principal is authenticated independently. Temporal handles retries without a custom attempt number/UUID protocol. Shared upload completion saves transfer evidence. Parse publication selects finalized uploads from the actual worker result, atomically attaches children and charges quota, then discards unused outputs. Completed publication is naturally idempotent and does not hash manifests.

Enrichment classifies leaves, then directory README files from deepest to root, using their own text and completed child-file/README summaries. Directory nodes own no semantic or MIME fields; their names derive from README results. The publication transaction updates final names, Markdown links/README bytes, metadata and quota, then copies root README semantics to the original file. Direct sources keep their original names/bytes and create no artifacts. The single exact family:kind taxonomy is defined in the [protobuf contract](../packages/contracts/proto/openlet_api/letfs/v1/letfs.proto).

Indexing uses full text for overlapping chunks, independently of the enrichment sample. README files carry directory evidence; CSV/image files use context overviews. Qdrant stores dense vectors and native BM25. Immutable point IDs include source generation and full vector space. Readiness commits only after acknowledged writes and a live/current-generation recheck. Index-only rebuilds reuse `process-file/<file-id>/<generation>` with native Temporal duplicate policy, skipping completed parse/enrichment stages. One pipeline status records readiness. Cleanup uses current embedding configuration and file/generation tombstones; no per-file configuration history or space-specific workflow exists.

The Python application has two explicit process roles: `python -m letfs_ingest.worker cpu` registers parsing only and checks offline models/OCR; `python -m letfs_ingest.worker io` registers enrichment/indexing only and does not require parser preflight. Both roles propagate Temporal/gRPC/provider-HTTP trace context and shut down in a bounded time.

## Admission, retry and change safety

Account/Workspace commit owner lifecycle or a create receipt before Temporal dispatch; a start outage leaves accepted work for their native reconciliation schedules. Letfs copy/upload admission commits scoped receipts before dispatch; processing starts from a file intent committed with source publication. Plain stable workflow identity plus DB uniqueness/results survives duplicate starts/history expiry. No HMAC or generic idempotency framework. Trusted private backend access is mandatory; queues do not authenticate callers. Workspace admits an authorized scoped request; letfs processes it without evaluating workspace roles.

Bound each activity attempt and external call. Retry infrastructure errors with SDK backoff; quota/name/revision/source conflicts are non-retryable for that attempt. Generation, stage and resource lifecycle guards protect repeated effects. Temporal is at-least-once execution, not exactly-once effects. Never hold DB locks during network I/O.

Starts use stable identities and reject closed duplicates. Copy receipts replay the original handle, and upload finalize returns its saved result. Trash uses the original node revision; restore/purge use current entry identity/state without response receipts.

Copy checkpoints and counters live in bounded workflow history; deletion uses remaining nodes as its durable checkpoint. Operator termination retains committed business state. Keep representative fresh histories and replay tests for current workflow definitions; no production compatibility/version scaffolding is required. Verify commit acknowledgment loss, bounded history continuation and actual worker/server restart against real domain operations.
