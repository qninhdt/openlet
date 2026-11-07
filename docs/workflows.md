# Durable execution

Workflows run in the existing private per-environment namespace. Account uses `openlet-account`, Workspace `openlet-workspace`, LetFS `openlet-letfs`; ingest activities use `openlet-letfs-cpu` and `openlet-letfs-io`. Each activity registers only on its executing owner's worker. Cross-service names/DTOs live in `packages/go/temporal`; domain code remains service-local.

## Workflow trees

```text
W OnboardUser [account]
├── A EnsureAccount [account]
├── child W CreateWorkspace [ws]
└── A PublishAccountIdentity [account]

W AccountChanges [account]
└── A ApplyAccountChange [account]

W CreateWorkspace [ws]
├── A CreateFilesystem [letfs]
├── A CreateScopes [letfs]
└── A SaveWorkspace [ws]

W WorkspaceChanges [ws, serialized per workspace]
├── Add/join: A CreateScopes [letfs] → A AddMember [ws]
├── Role/remove: A UpdateMembership [ws]
├── Scope grant: A UpdateScopeAccess [ws]
└── Delete: child W DeleteWorkspace [ws]

W DeleteWorkspace [ws]
├── A MarkWorkspaceDeleting [ws]
├── child W DeleteFilesystem [letfs]
└── A RemoveWorkspace [ws]

W DeleteFilesystem [letfs]
├── A ListScopesForDeletion [letfs]  (write fence + keyset page)
├── child W DeleteScope [letfs] × scopes, bounded concurrency
└── A RemoveFilesystem [letfs]

W DeleteScope [letfs]
└── A DeleteScopeData [letfs]

W PurgeTrash [letfs]
└── A PurgeTrashData [letfs]

W CopyTree [letfs]
└── A CopyTreeData [letfs]

W ProcessFile [letfs]
├── A process_file [letfs-ingest / CPU]  (if required)
├── A enrich_file [letfs-ingest / IO]    (if required)
└── A index_file [letfs-ingest / IO]  (if scope allows indexing)

W StorageMaintenance [letfs, scheduled]
├── A ExpireUploads [letfs]
├── A ReconcileResources [letfs]
└── A DeleteObjects [letfs]

W WorkspaceMaintenance [ws, scheduled]
└── A PruneReceipts [ws]
```

## Admission and publication

HTTP/gRPC admission validates input and permission before starting work; there are no permission/quota-check activities. Mutation transactions still enforce lifecycle, revision, member cap and hard filesystem accounting. Onboarding carries its trusted verified account into the initial Workspace child. Workspace allocates opaque filesystem/scope IDs once; LetFS never knows shared/personal purpose.

CreateWorkspace performs generic storage creation followed by SaveWorkspace, which persists the mapping/member and publishes graph relationships. AddMember similarly commits actual membership and acknowledges its graph publication. Existing receipts reconcile lost SQL/graph acknowledgments; a committed or pre-existing resource must never be compensated. Permanent uncommitted admission failure cleans only storage created for that command through the existing deletion child. Transient failures retry.

AccountChanges handles managed-account creation and graph publication; ordinary profile edits remain direct. OnboardUser ends with Clerk identity publication. Verified completion prevents recreation after workspace deletion or Temporal history expiry; Account stores no initial-workspace foreign key.

WorkspaceChanges serializes commands per workspace with a native workflow mutex and Update-With-Start. After 100 completed Updates, Continue-As-New waits for handlers. Membership/access/delete responses wait for their required effects, including graph acknowledgement. Workspace rename and invitation management stay direct.

## Deletion and maintenance

DeleteWorkspace marks deleting, waits for its one DeleteFilesystem child, then removes Workspace relationships and records deletion. Accepted deletion survives caller disconnect; ABANDON children continue when a parent closes. A terminated parent can be explicitly retried without assuming its child stopped.

DeleteFilesystem fences writes and keyset-pages scopes. It starts at most four DeleteScope children concurrently, waits for them, then removes the filesystem. After 100 pages it continues with its cursor. DeleteScopeData and PurgeTrashData loop bounded SQL batches internally. Each batch records cleanup, removes actual rows and debits only those rows atomically. Duplicate requests use independent generated child IDs and natural idempotence. Missing/deleted resources are successful cleanup retries. No per-node activities exist.

Deletion blocks uploads/copy/processing publication. Logical completion can precede S3 cleanup. Deleted identity remains only while transfers or cleanup need attribution. Graph removal errors remain retryable. Ambiguous/open-write evidence is retained for late writes, including after NotFound.

StorageMaintenance runs every five minutes with overlap SKIP. Its three activities expire uploads, reconcile durable intents and delete objects; later phases still run if an earlier one fails, and errors are returned together. Reconciliation handles lost purge/deletion/processing dispatch and a copy admission that never started. It never restarts a started or terminal failed copy. Unknown Temporal status is not proof of abandonment. WorkspaceMaintenance prunes existing receipts only.

## Copy

CopyTree runs one CopyTreeData activity with `MaximumAttempts: 1`. Traversal is local and bounded by captured node/byte/depth/runtime limits. Each ordinary node is visible and charged on commit. Source/destination identity, revisions, lifecycle and cleanup evidence are revalidated around S3 I/O. Failure keeps committed output and returns an error; there is no automatic rollback or resume guarantee. Admission returns stable copy/destination identities, with no monitor or progress surface. Test harness history export is solely verification tooling.

## Processing

Eligible source publication commits a monotonic desired generation on `files`. PDF/DOCX/PPTX/XLSX parse first; direct text/CSV/image sources skip parsing. Dispatch starts `process-file/<file-id>/<generation>` with `{source:{file_id,generation},parse_required,enrichment_required}`. Bounded maintenance recovers a lost start and records explicit failure after a closed workflow; unknown Temporal state never authorizes failure. Manual reprocessing commits its caller-scoped receipt and generation before dispatch.

Parse/enrichment requests carry the existing source file ID and generation; the dedicated ingest principal is authenticated independently. Temporal handles retries without a custom attempt number/UUID protocol. Shared upload completion saves transfer evidence. Parse publication selects finalized uploads from the actual worker result, atomically attaches children and charges quota, then discards unused outputs. Completed publication is naturally idempotent and does not hash manifests.

Enrichment classifies leaves, then directory README files from deepest to root, using their own text and completed child-file/README summaries. Directory nodes own no semantic or MIME fields; their names derive from README results. The publication transaction updates final names, Markdown links/README bytes, metadata and quota, then copies root README semantics to the original file. Direct sources keep their original names/bytes and create no artifacts. The single exact family:kind taxonomy is defined in the [protobuf contract](../packages/contracts/proto/openlet_api/letfs/v1/letfs.proto).

Indexing uses full text for overlapping chunks, independently of the enrichment sample. README files carry directory evidence; CSV/image files use context overviews. Qdrant stores dense vectors and native BM25. Immutable point IDs include source generation and full vector space. Readiness commits only after acknowledged writes and a live/current-generation recheck. Index-only rebuilds reuse `process-file/<file-id>/<generation>` with native Temporal duplicate policy, skipping completed parse/enrichment stages. One pipeline status records readiness. Cleanup uses current embedding configuration and file/generation tombstones; no per-file configuration history or space-specific workflow exists.

The Python application has two explicit process roles: `python -m letfs_ingest.worker cpu` registers parsing only and checks offline models/OCR; `python -m letfs_ingest.worker io` registers enrichment/indexing only and does not require parser preflight. Both roles propagate Temporal/gRPC/provider-HTTP trace context and shut down in a bounded time.


## Verification

Workflow tests check activity order, queue ownership, retry policies and child behavior. Real PostgreSQL/SpiceDB/Temporal tests cover publication failures, duplicate cleanup and restart accounting. Replay uses freshly exported histories; no production compatibility histories are required. See [testing](testing.md).
