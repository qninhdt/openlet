# Durable execution

Service-owned workflows use pinned Go/Rust SDKs. Document conversion runs as one Python activity scheduled by letfs. Implementation reports and the active plan record verification evidence and remaining release checks.

## Ownership and communication

| Owner | Workflow/activity code | Application core |
|---|---|---|
| User | `services/user/internal/temporal/` | `internal/user/` |
| Workspace | `services/workspace/internal/temporal/` | `internal/workspace/` |
| letfs | `services/letfs/src/temporal/` | `src/fs/`, `src/storage/` |

Official Go/Rust SDK workers run inside the corresponding service. One private namespace per environment, explicit owner queues. Workflow code is deterministic and performs I/O only through activities. HTTP/activity adapters reuse application functions. No file bytes, credentials or growing traversal arrays in history.

Cross-service activities call internal HTTP. A service idempotently starts its own operation and exposes scoped status; callers use short status activities and workflow timers. No direct Go-to-Rust Temporal activity/child dependency, custom bridge, sidecar or Nexus. Local children use explicit parent-close policies.

## Catalogue

| Workflow | Owner | Durable work |
|---|---|---|
| `OnboardUser` | User | Internal identity, initial workspace/storage, Clerk claim |
| `CreateWorkspace` | Workspace | Workspace/Owner, storage provisioning, activation |
| `DeleteWorkspace` | Workspace | Deny access, freeze bucket, remove every filesystem, finalize tombstone |
| `CopyNode` | letfs | Object/directory staging, traversal, publication or discard |
| `PurgeTrash` | letfs | Directory purge batches |
| `DeleteFilesystem` | letfs | Remove live/trash/staging/upload state |
| `StorageMaintenance` | letfs | Expire uploads, discard failed staging, reclaim objects |
| `ProcessFile` | letfs | One Python `process_file` activity, on `openlet-letfs-processing` |
| `ExportArchive` | letfs | One Rust `export_archive` activity, on the existing letfs queue |

Direct operations: auth, profile/member/invitation mutations, path/stat/list, mkdir, rename/move, inline text edits, inline-file copy, upload transfer/finalize, trash/restore and file purge. Physical object cleanup follows logical deletion asynchronously.

## Activity sequences

### OnboardUser

`EnsureUser` commits unique Clerk-subject identity and a stable initial-workspace provision key. `EnsureInitialWorkspace` calls the Workspace create API; `GetInitialWorkspaceStatus` plus workflow timers waits for activation. `PublishClerkUserID` merges only backend-owned metadata; `CompleteOnboarding` stores IDs and refresh instruction. A Clerk outage resumes publication, without deleting a ready account/workspace. Completed onboarding never recreates a deleted initial workspace.

### CreateWorkspace

`EnsureWorkspaceAndOwner` creates provisioning workspace, member and admission together. `EnsureStorageBucket` and `EnsureDriveFilesystem` call real transactional letfs ensure APIs with stable keys. `ActivateWorkspace` records mapping/active state/result. Partial provisioning stays inaccessible. Lost responses do not allocate duplicates; transient errors do not delete existing resources.

### DeleteWorkspace

`BeginDeletion` rechecks Owner/revision under the Workspace lock and disables public access. `FreezeBucket` prevents new provisioning/growth. Keyset `ListBucketFilesystems`, `EnsureFilesystemDeletion` and status activities remove every filesystem with bounded concurrency. `CompleteBucketDeletion` requires no active filesystem/upload and zero charged usage. `CompleteWorkspaceDeletion` retains tombstone/status binding and removes active memberships/invitations. Physical cleanup records survive. Errors after admission do not reactivate the workspace.

### CopyNode

`PrepareCopy` validates scope/preconditions and creates detached staging. Repeated `CopyBatch` uses bounded item/byte/time budgets and durable source/destination mappings; S3 I/O stays outside DB locks. Frozen per-item revision/keys and result state protect response-loss retries. No tree snapshot, source-retention pins, full manifest or filesystem epoch.

`PublishCopy` validates destination/job, admits aggregate quota and attaches the root atomically. A committed publication wins over response loss: retry returns it. On non-retryable source/name/quota failure, `MarkCopyDiscarding`, shared deletion batches and `CompleteCopyFailure` clean uncharged staging. Cleanup never discards published output. Cancellation uses SDK shielding so cleanup can finish; maintenance continues recorded discarding state.

### PurgeTrash

`BeginPurge` claims the trash entry, excluding restore. Repeated `DeleteNodesBatch` persists bounded postorder traversal, metadata removal, quota debit for exactly the charged nodes removed in that batch and object-deletion records together. Never debit the entire subtree before deletion or repeat a batch debit after response loss. `CompletePurge` removes trash metadata and retains result. File purge uses the same transaction core directly.

### DeleteFilesystem

`BeginFilesystemDeletion` disables access and fences uploads/copy publication. Shared `DeleteNodesBatch` covers all roots, including trash and staging. `AbortFilesystemUploadsAndCopies` preserves immutable-key evidence and cooperates with late attempts. `CompleteFilesystemDeletion` requires no nodes, active uploads or charged bytes; retain tombstone/cleanup records. Do not delete only the live tree or cascade away bookkeeping.

### StorageMaintenance

A finite Schedule with overlap SKIP runs bounded `ExpireUploadsBatch`, `DiscardFailedCopiesBatch` and `DeleteObjectsBatch`. Expiry is terminal before cleanup. Keep records for ambiguous/late object writes and obey deadline/grace rules. Reclaim staging only after explicit discarding or confirmed terminal workflow status; unknown/unavailable history is not proof. CAS staging to discarding before cleanup so stale activities cannot publish.

Inspect S3 per-key errors and retry. Physical GC never debits logical usage again. Keep bucket attribution while cleanup exists. No automatic age-based trash purge or counter repair.

Processing reconciliation runs within existing bounded maintenance work. It starts committed intents missing a workflow, reconciles closed workflows, and cleans unpublished output sessions. Unknown Temporal status never authorizes failing an active job.

### ProcessFile

Eligible PDF/DOCX/PPTX/XLSX upload publication commits a processing intent with immutable source identity. Post-commit dispatch uses `process-file/<operation-id>`; maintenance recovers a lost start. Source upload success is independent of processing success. The Rust workflow schedules exactly one Python activity, with three maximum attempts, heartbeat and execution deadlines. It contains no bytes, URLs, credentials or output lists.

Python registers activities only. Its async parent owns scoped letfs HTTP/direct S3 transfers and supervises a local CPU conversion child. The worker has a separate token and no DB/S3 credentials. Models and dependencies are baked into the image; runtime uses offline models, CPU/memory/scratch bounds, one conversion per container and TERM-then-KILL cleanup.

Attempt generation plus invocation UUID fences stale requests. Same-attempt output paths reuse shared inline/single-PUT/multipart sessions. Outputs stay outside `nodes` until one source-identity/liveness/attempt/quota transaction publishes all children. A committed success reconciles without rerunning Docling. Overwrite and trash fence old work permanently; rename/move preserve source identity. Copy never starts processing.

PDF/DOCX export numbered main-section Markdown with tables inline, PPTX exports ordered slide Markdown, and XLSX exports sheet directories with table CSVs and positional CSVs for uncovered cells. Empty sheets remain directories. Images are optional extracted children. No indexes, manifests, duplicate document Markdown, legacy Office, standalone image processing or text chunking is emitted.

### ExportArchive

Workspace authorizes selection/status/download against current membership. letfs
binds the operation to filesystem, actor and request key, rechecks delegated scope
and lifecycle, and reuses a committed result without rebuilding. The stable workflow
ID is `export-archive/<filesystem>/<actor>/<request-key>`.

One activity captures bounded metadata, streams ZIP64 through a bounded buffer to
native multipart at `exports/<operation>/<attempt>.zip`, then revalidates the input
tree and publishes the current attempt in one short transaction. Inline input is
read in bounded batches; object input streams from its captured immutable key.
Storage I/O runs outside DB locks. A changed source fails the current attempt and
allows retry with newly enumerated inputs. Three bounded attempts rebuild the whole archive;
there are no per-file activities, stored manifests or durable byte checkpoints.

Existing maintenance reconciles terminal export workflows, aborts abandoned native
multipart uploads and reclaims failed/expired objects. Unknown Temporal status does
not fail active work. Attempt fencing and operation-row locking prevent stale or
failed attempts from publishing. Download bytes go directly from S3 to the caller.

## Admission, retry and change safety

Use [API admission](api-contracts.md) for user-requested durable operations: Temporal start precedes their business mutation, and 202 follows durable caller-bound admission. Processing instead starts from an intent committed with a successful source upload. Plain stable workflow identity plus DB uniqueness/results survives duplicate starts/history expiry. No HMAC or generic idempotency framework. Trusted private backend access is mandatory; queues do not authenticate callers. Workspace admits an authorized scoped request; letfs processes it without evaluating workspace roles.

Bound each activity attempt and external call. Retry infrastructure errors with SDK backoff; quota/name/revision/source conflicts are non-retryable for that attempt. State guards fence timed-out attempts. Temporal is at-least-once execution, not exactly-once effects. Never hold DB locks during network I/O.

Closed-before-admission retry uses the explicit running-conflict/closed-run policy in the API contract and is tested in every owning durable-start phase. Direct inline copy retains scoped creation identity/result transactionally, and upload finalize uses its saved upload state. Short trash/restore/file-purge transactions use original identity/revision and state reconciliation, without response receipts. Temporal history replay and retry-safe activity effects remain required.

Keep traversal checkpoints in DB; Continue-As-New carries only operation ID/small cursor before history grows large. Recover destructive work with its existing identity/checkpoint. Operator termination does not erase business state. Workflow changes must preserve deterministic replay through SDK versioning/patching where needed; keep representative histories and replay tests. Test crash-after-commit, cancellation, retries and actual worker/server restart on real domain operations, not a disposable language-interoperability matrix.
