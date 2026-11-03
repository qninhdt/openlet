# Durable execution

Service-owned workflows use pinned Go/Python SDKs. File parsing, semantic enrichment and search indexing run as three whole-source Python activities scheduled by letfs. The [service refactor decision](../plans/261103-1348-service-refactor/tmp-refactor-decision.md) records the current boundaries and acceptance criteria.

## Ownership and communication

| Owner | Workflow/activity code | Application core |
|---|---|---|
| Account | `apps/account/internal/temporal/` | `internal/user/` |
| Workspace | `apps/workspace/internal/temporal/` | `internal/workspace/` |
| letfs | `apps/letfs/internal/temporal/` | `internal/filesystem/`, `internal/clients/storage/` |

Official Go SDK workers run inside the corresponding service. One private namespace per environment, explicit owner queues. Workflow code is deterministic and performs I/O only through activities. HTTP and gRPC adapters reuse feature services. Activities invoke the same business steps. Shared Temporal helpers own trace/error conversion; they contain no workflows or business retry policy. No file bytes, credentials or growing traversal arrays in history.

Account and Workspace submit commands with Temporal Update-With-Start before writing business rows. The admission Update waits for the first Activity result; losing the HTTP connection does not cancel accepted work. Temporal unavailability before acceptance returns 503 without a business mutation. Account executes a local Activity calling Workspace gRPC and polls durable initial-workspace admission. Workspace executes its own storage Activities through the shared letfs gRPC client. There are no Account/Workspace graph-scan or dispatch-reconciliation schedules. Workspace retains only a receipt-expiry schedule. letfs retains recovery for SQL intents committed by direct filesystem APIs.

## Catalogue

| Workflow | Owner | Durable work |
|---|---|---|
| `OnboardUser` | Account | Internal identity, initial workspace/storage, Clerk claim |
| `CreateWorkspace` | Workspace | Workspace/Owner, storage provisioning, activation |
| `DeleteWorkspace` | Workspace | Deny access, freeze bucket, remove every filesystem, finalize tombstone |
| `WorkspacePermissions` | Workspace | Serialize member/owner/join/delete commands and their targeted graph writes per workspace |
| `WorkspaceMaintenance` | Workspace | Expire completed idempotency receipts |
| `CopyNode` | letfs | Bounded traversal and per-item visible commits with partial results |
| `PurgeTrash` | letfs | Direct leaf batches for either node kind |
| `DeleteFilesystem` | letfs | Remove live/trash/artifact/upload state |
| `StorageMaintenance` | letfs | Expire uploads, recover admissions, drain detached forests and reclaim objects |
| `ProcessFile` | letfs | `process_file` on `openlet-letfs-cpu`, then `enrich_file -> index_file` on `openlet-letfs-io` |

Workspace authorization commands execute as Updates to `workspace-permissions/<workspace-id>`. A native workflow mutex covers validation, SQL mutation and graph publication, including Activity retries. `PrepareMutation` is a Local Activity with a five-second attempt timeout; `ApplyMutation` remains a regular Activity. Scheduling that regular Activity persists the prepared result before its SQL changes, so worker recovery preserves the original owner and receipt hash. After 100 completed Updates, Continue-As-New waits for all handlers to finish. The existing `idempotency_keys` table records each mutation in its SQL transaction; retries after a lost commit acknowledgement skip SQL and finish the graph write. An ownership transfer changes both users in one atomic SpiceDB request. Name-only updates and invitations that do not change membership remain direct.

Direct operations: auth, profile and invitation mutations, path/stat/list, mkdir, rename/move, inline text edits, upload transfer/finalize, trash/restore. Physical object cleanup follows logical deletion asynchronously.

## Activity sequences

### OnboardUser

`OnboardUser` executes `EnsureUser` (unique Clerk subject plus self relationship), then its local `EnsureInitialWorkspace` Activity calls Workspace's authenticated gRPC admission. The workflow polls the same stable request until Workspace reports active, then executes `PublishClerkUserID` and `CompleteOnboarding`. The final Activity saves the initial workspace ID and activates the user together. Completed onboarding never recreates a later-deleted initial workspace. After 100 pending polls, Continue-As-New starts a fresh history and preserves the same request identity. Account does not reference Workspace workflow names, queues or Activity implementations.

### CreateWorkspace

`PrepareWorkspace` checks limits, commits Workspace/Owner and the existing receipt, reserves stable bucket/filesystem IDs, and grants owner status access. The Workspace-local `CreateStorage` Activity calls letfs administration gRPC, which invokes naturally idempotent bucket/filesystem operations. `CompleteWorkspace` publishes storage inheritance while SQL still blocks membership/deletion, then saves the root and activates, releases letfs provisioning receipts through gRPC, and starts the 24-hour receipt TTL for ordinary creation. Initial-workspace receipts do not expire, so delayed Account recovery cannot create a second initial workspace. An already-active retry skips activation graph writes so it cannot re-enable a later deletion. There are no letfs business mappings or provision keys. Handled permanent failures mark provisioning failed; partial storage remains deletable by its owner.

The workflow ID is `create-workspace/<actor>/<request-key>`. Concurrent admissions validate the same input in the Update handler. Existing receipts replay the same Workspace; changed input conflicts. Closed IDs allow a new execution so receipt expiry can release a key without depending on Temporal history retention. SQL uniqueness and the pinned receipt protect unfinished work. Initial creation reserves `actor_id == request_key`; public creation rejects that reserved key.

### DeleteWorkspace

A serialized `WorkspacePermissions` Update executes `PrepareWorkspaceDeletion`: authorize the action, recheck lifecycle/revision under lock, commit deleting, then disable inherited storage access. Only then does it start the `DeleteWorkspace` child with ABANDON parent-close policy and return 202. Repeated DELETE uses the running child; a closed failed/terminated child can be restarted explicitly with the same resource identity.

`DeleteWorkspace` freezes the bucket, enumerates filesystems with a bounded keyset cursor, polls authenticated `DeleteFilesystem` gRPC admissions until letfs-owned cleanup completes, completes the bucket, then executes `CompleteWorkspaceDeletion`. This final Activity commits the tombstone/removes nonowner memberships and deletes their graph tuples, retaining owner status access. After 100 pending polls or completed filesystem steps, Continue-As-New carries the last completed cursor and resumes unfinished deletion; cancellation uses a disconnected scope. A recovery run reuses stable filesystem deletion identity and skips already-deleted filesystems.

Temporal execution failures, timeouts and operator termination remain visible in Temporal history. Handled provisioning failures also update SQL lifecycle. Termination cannot execute failure handlers: inspect the execution and perform explicit deletion retry or operator recovery. No periodic reconciliation silently restarts terminal workflows.

### CopyNode

HTTP commits a scoped copy receipt and immutable admission before dispatch. `CopyItem` publishes one ordinary node after verified storage copy and atomic quota checks; deterministic destination IDs and captured parent/source revisions protect response-loss retries. `NextCopyItem` reads bounded high-water children; `FinishCopyFile` admits processing once after an ordinary file subtree completes. Directories and derived files skip this Activity. Artifact descendants stay read-only and do not receive independent processing intents.

The workflow carries at most 128 frames, one selected item and cumulative counts across Continue-As-New every 100 steps. Node/byte/depth ceilings and a one-hour deadline bound work. A failure returns an explicit partial result and preserves committed nodes; no staging, rollback or item table exists. `CompleteCopy` starts the receipt's 24-hour TTL. The scoped monitor reads Temporal admission/progress, checks current `copy_read` permission and requires the initiating actor or `copy_inspect_any` action. Missing retained history returns 410.

### PurgeTrash

`BeginPurge` claims the trash entry, excluding restore. `DeleteNodesBatch` follows one bounded branch and removes at most 64 leaf siblings, with quota debit and object-deletion intent in the same transaction. Remaining nodes preserve progress after response loss; no deletion item or execution-state table is used. The trash entry disappears when its root is removed. Every purge uses this workflow. A purging entry fences restore and is sufficient for maintenance to recover a lost dispatch.

### DeleteFilesystem

The owner admission disables access, aborts unattached open transfers and preserves immutable-key cleanup evidence under the filesystem lock. The deletion workflow starts directly with `DeleteNodesBatch`, whose store validation rejects invalid identities and lifecycle states. Shared `DeleteNodesBatch` queries at most 64 leaves across all roots, including trash and detached artifacts. Each batch removes metadata, debits actual usage and records cleanup atomically; the last batch retains a deleted filesystem tombstone with no nodes or charged bytes. Continue-As-New carries only immutable filesystem/entry identity after 200 batches. Lifecycle guards reject late copy/upload/publication attempts; no SQL traversal snapshot is required.

### StorageMaintenance

A finite five-minute Schedule with overlap SKIP runs bounded `ExpireUploadsBatch`, `ReconcileResourcesBatch` and `DeleteObjectsBatch`. Each phase runs even if an earlier phase fails; the workflow reports all errors together. Resource recovery drains detached artifact forests, recovers purging entries and incomplete copy admissions, and reconciles processing/index cleanup. A closed copy completes its receipt without deleting partial output. Unknown/unavailable history never proves abandonment. Copy writers register candidate evidence before I/O; unresolved write counts survive worker death. Cleanup rejects referenced keys, and an attempted deletion permanently fences that copy candidate from later publication/reuse. Unresolved late writes retain compact daily cleanup tombstones.

Inspect S3 per-key errors and retry. Physical GC never debits logical usage again. Keep bucket attribution while cleanup exists. No automatic age-based trash purge or counter repair.

Processing reconciliation runs within existing bounded maintenance work. It starts committed intents missing a workflow, reconciles closed workflows, and cleans unpublished output sessions. Unknown Temporal status never authorizes failing an active job.

### ProcessFile

Eligible source publication commits a monotonic desired generation on `files`. PDF/DOCX/PPTX/XLSX parse first; direct text/CSV/image sources skip parsing. Dispatch starts `process-file/<file-id>/<generation>` with `{source:{file_id,generation},parse_required,enrichment_required}`. Bounded maintenance recovers a lost start and records explicit failure after a closed workflow; unknown Temporal state never authorizes failure. Manual reprocessing commits its caller-scoped receipt and generation before dispatch.

Parse/enrichment requests carry the existing source file ID and generation; the dedicated ingest principal is authenticated independently. Temporal handles retries without a custom attempt number/UUID protocol. Shared upload completion saves transfer evidence. Parse publication selects finalized uploads from the actual worker result, atomically attaches children and charges quota, then discards unused outputs. Completed publication is naturally idempotent and does not hash manifests.

Enrichment classifies leaves, then directory README files from deepest to root, using their own text and completed child-file/README summaries. Directory nodes own no semantic or MIME fields; their names derive from README results. The publication transaction updates final names, Markdown links/README bytes, metadata and quota, then copies root README semantics to the original file. Direct sources keep their original names/bytes and create no artifacts. The single exact family:kind taxonomy is defined in the [protobuf contract](../packages/contracts/proto/openlet_api/letfs/v1/letfs.proto).

Indexing uses full text for overlapping chunks, independently of the enrichment sample. README files carry directory evidence; CSV/image files use context overviews. Qdrant stores dense vectors and native BM25. Immutable point IDs include source generation and full vector space. Readiness commits only after acknowledged writes and a live/current-generation recheck. Index-only rebuilds reuse `process-file/<file-id>/<generation>` with native Temporal duplicate policy, skipping completed parse/enrichment stages. One pipeline status records readiness. Cleanup uses current embedding configuration and file/generation tombstones; no per-file configuration history or space-specific workflow exists.

The Python application has two explicit process roles: `python -m letfs_ingest.worker cpu` registers parsing only and checks offline models/OCR; `python -m letfs_ingest.worker io` registers enrichment/indexing only and does not require parser preflight. Both roles propagate Temporal/gRPC/provider-HTTP trace context and shut down in a bounded time.

## Admission, retry and change safety

Account/Workspace commands must be durably accepted by Temporal before SQL business mutations. Letfs copy/upload admission commits scoped receipts before dispatch; processing starts from a file intent committed with source publication. Plain stable workflow identity plus DB uniqueness/results survives duplicate starts/history expiry. No HMAC or generic idempotency framework. Trusted private backend access is mandatory; queues do not authenticate callers. Workspace admits an authorized scoped request; letfs processes it without evaluating workspace roles.

Bound each activity attempt and external call. Retry infrastructure errors with SDK backoff; quota/name/revision/source conflicts are non-retryable for that attempt. Generation, stage and resource lifecycle guards protect repeated effects. Temporal is at-least-once execution, not exactly-once effects. Never hold DB locks during network I/O.

Starts use stable identities and operation-specific duplicate policies. Workspace creation keys become reusable after receipt expiry; deletion retries explicitly resume closed cleanup. Copy receipts replay the original handle, and upload finalize returns its saved result. Trash uses the original node revision; restore/purge use current entry identity/state without response receipts.

Copy checkpoints and counters live in bounded workflow history; deletion uses remaining nodes as its durable checkpoint. Operator termination retains committed business state. Keep representative fresh histories and replay tests for current workflow definitions; no production compatibility/version scaffolding is required. Verify commit acknowledgment loss, bounded history continuation and actual worker/server restart against real domain operations.
