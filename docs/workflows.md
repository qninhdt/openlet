# Durable execution

Workflows run in the existing private per-environment namespace. Account uses `openlet-account`, Workspace `openlet-workspace`, LetFS `openlet-letfs`; ingest activities use `openlet-letfs-cpu` and `openlet-letfs-io`. Leta uses `openlet-leta` for control and `openlet-leta-runtime` for inference. Each activity registers only on its executing owner's worker. Cross-service names/DTOs live in `packages/go/temporal`; domain code remains service-local.

## Workflow trees

```text
W OnboardUser [account]
├── A EnsureUser [account]
├── child W CreateWorkspace [ws]
└── A PublishUserIdentity [account]

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
├── A ListWorkspaceLeta / StopLetaForWorkspaceDeletion [ws → leta, bounded pages]
├── child W DeleteFilesystem [letfs]
└── A RemoveWorkspace [ws]

W DeleteFilesystem [letfs]
├── A ListScopesForDeletion [letfs]  (write fence + keyset page)
├── child W DeleteScope [letfs] × scopes, bounded concurrency
└── A RemoveFilesystem [letfs]

W DeleteScope [letfs]
└── A DeleteScopeData [letfs]

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

### Agent inbox orchestration

`apps/leta/src/leta/temporal/agent.py` implements a long-lived `AgentWorkflow` per agent on `openlet-leta`. Receive uses Update-with-Start, serializes only the short SQL inbox admission, and acknowledges the committed message ID/sequence while model work remains independent. SQL-only Local Activities bootstrap/reserve the current run, persist inbox items and save run control. Transient SQL failures use Temporal retry; validation and routing failures are nonretryable.

The workflow dispatches one whole `run_agent` Activity on `openlet-leta-runtime`, retains its business run ID over retries/Continue-As-New, and remains idle without polling. Stop awaits Activity cleanup and cancels any still-unfinished reserved run before acknowledging. History guards request cooperative yield during an active invocation and rotate idle/paused executions after handlers drain; stop can break that drain to avoid a circular wait. PostgreSQL retains message bodies, run progress and checkpoints; Workflow state carries IDs, cursors and control flags.

`leta.worker.agent_workers` hosts the two bounded Workers and requires a concrete runner callable. The production entrypoint supplies the checkpointed AgentRunner, native clients, required Redis publisher and all six Workflow types. Private ingress still owns authentication and source/routing admission.

### Leta Workflow catalogue

| Workflow | Local Activities (short owning SQL) | Regular Activities / purpose |
| --- | --- | --- |
| AgentWorkflow | bootstrap_agent, persist_inbox, save_run_control | run_agent on the runtime queue; receive/control remain responsive during inference |
| LetaLifecycleWorkflow | save_leta_change | publish_leta_resource, ensure_leta_home, start_agent/control_agent; deletion also change_schedule, settle_hitl, cleanup_leta_access |
| BoxLifecycleWorkflow | save_box_change | ensure_box_home, start_agent; deletion settles sources, stops children, then trash_box_home |
| HumanRequestWorkflow | open_hitl_request, resolve_hitl_request, save_hitl_outcome | grant_requested_access for accepted resource requests, then deliver_agent_input to the exact requesting agent |
| ScheduleChangesWorkflow | save_schedule_change | apply_temporal_schedule converges native schedule state with the saved definition |
| ScheduleDeliveryWorkflow | load_schedule_occurrence | deliver_agent_input with stable nominal occurrence identity after current lifecycle validation |

Control workflows also publish sparse committed-resource hints through `publish_resource_event`. Publication failure never replays a committed business effect. `change_schedule`, `settle_hitl` and `control_agent` bridge existing coordinators; they introduce no extra Workflow type.

Ordinary root archive stops agent runtimes, requests cancellation of its box coordinators and retains box homes/history. Explicit box deletion instead stops its children before trashing its home. Cancellation request acknowledgement alone does not mean every box Update handler has drained; the runner stop barrier protects storage access.

Human requests have pending/resolved/cancelled/expired status. An ask targets the Leta creator; a personal-scope approval targets the resource owner. Only the finite request Workflow waits or expires. Accepted access grants the root Leta subject and delivers the settled outcome to the requesting Leta/Leti. Rejection, cancellation and expiry also produce typed input. No pending request blocks the agent's unrelated work.

Schedule definitions are product rows in PostgreSQL, queryable for list/calendar APIs. `at` accepts an absolute time or relative seconds; `interval` accepts arbitrary whole-second durations; `calendar` uses timezone and Temporal field ranges. Definition changes normalize relative times once. Native Temporal Schedules wake independent delivery Workflows with BUFFER_ONE; SQL occurrence checks suppress stale/deleted/inactive sources. The calendar endpoint forecasts the native rules for a bounded requested window; it does not create a second scheduler.

HTTP schedule validation runs inside the idempotency reservation transaction, before it commits. Rejected input leaves no new reservation; pending retries validate against the first request timestamp, and completed retries return the current resource without revalidating against later definition changes. Unknown Temporal outcomes retain their pending reservation for reconciliation.

HTTP/gRPC admission validates input and permission before starting work; there are no permission/quota-check activities. Mutation transactions still enforce lifecycle, revision, member cap and hard filesystem accounting. Onboarding carries its trusted verified human user into the initial Workspace child. Workspace allocates opaque filesystem/scope IDs once; LetFS never knows shared/personal purpose.

CreateWorkspace performs generic storage creation followed by SaveWorkspace, which persists the mapping/member and publishes graph relationships. AddMember similarly commits actual membership and acknowledges its graph publication. Existing receipts reconcile lost SQL/graph acknowledgments; a committed or pre-existing resource must never be compensated. Permanent uncommitted admission failure cleans only storage created for that command through the existing deletion child. Transient failures retry.

The identity service runs human onboarding only; profile edits remain direct and managed-account workflows are removed. OnboardUser ends with Clerk identity publication. Verified completion prevents recreation after workspace deletion or Temporal history expiry; Account stores no initial-workspace foreign key.

WorkspaceChanges serializes commands per workspace with a native workflow mutex and Update-With-Start. After 100 completed Updates, Continue-As-New waits for handlers. Membership/access/delete responses wait for their required effects, including graph acknowledgement. Workspace rename and invitation management stay direct.

## Deletion and maintenance

DeleteWorkspace marks deleting, pages all canonical Leta roots and waits for actual producer/HITL/schedule/access cleanup, then waits for its one DeleteFilesystem child and records deletion. Cleanup callbacks use direct owning methods rather than reenter the held WorkspaceChanges mutex. Accepted deletion survives caller disconnect; ABANDON children continue when a parent closes. A terminated parent can be explicitly retried without assuming its child stopped.

DeleteFilesystem fences writes and keyset-pages scopes. It starts at most four DeleteScope children concurrently, waits for them, then removes the filesystem. After 100 pages it continues with its cursor. DeleteScopeData loops bounded SQL batches internally. Request-owned trash purge uses the same local batch deletion logic. Each batch records cleanup, removes actual rows and debits only those rows atomically. Duplicate requests use independent generated child IDs and natural idempotence. Missing/deleted resources are successful cleanup retries. No per-node activities exist.

Deletion blocks uploads/copy/processing publication. Logical completion can precede S3 cleanup. Deleted identity remains only while transfers or cleanup need attribution. Graph removal errors remain retryable. Ambiguous/open-write evidence is retained for late writes, including after NotFound.

StorageMaintenance runs every five minutes with overlap SKIP. Its three activities expire uploads, reconcile durable intents and delete objects; later phases still run if an earlier one fails, and errors are returned together. Reconciliation handles filesystem/scope deletion and processing dispatch. It does not start or resume request-owned copy/purge operations. Unknown Temporal status is not proof of abandonment. WorkspaceMaintenance prunes existing receipts only.

## Direct file operations

Copy and trash purge run synchronously in the API request, without Temporal activities, child workflows or replacement background tasks. Copy traverses locally within existing node/byte/depth limits, commits individual nodes and charges quota on each commit. Inline bytes copy in PostgreSQL; blobs use S3 CopyObject with cleanup evidence recorded before external writes. Source/destination identities, revisions, scope options and lifecycle are revalidated around I/O. Failure returns through the request and retains committed output. Only a completed copy saves a 24-hour receipt containing its resulting Node. No progress, resume or automatic redispatch exists.

Purge marks its existing trash entry purging, then removes bounded SQL batches in the request. A failed/interrupted purge retains its state and remaining nodes; retrying DELETE finishes it naturally. S3/index garbage collection remains separate from logical deletion.

Cross-scope move/restore keep IDs, payloads and filesystem accounting. The filesystem lock and one transaction cover whole-tree policy validation, scope/parent changes, revisions, old-generation/index cleanup and new processing intent. Processing continues independently through the existing pipeline.

## Processing

Eligible source publication commits a monotonic desired generation on `files`. PDF/DOCX/PPTX/XLSX parse first; direct text/CSV/image sources skip parsing. Dispatch starts `process-file/<file-id>/<generation>` with `{source:{file_id,generation},parse_required,enrichment_required}`. Bounded maintenance recovers a lost start and records explicit failure after a closed workflow; unknown Temporal state never authorizes failure. Manual reprocessing commits its caller-scoped receipt and generation before dispatch.

Parse/enrichment requests carry the existing source file ID and generation; the dedicated ingest principal is authenticated independently. Temporal handles retries without a custom attempt number/UUID protocol. Shared upload completion saves transfer evidence. Parse publication selects finalized uploads from the actual worker result, atomically attaches children and charges quota, then discards unused outputs. Completed publication is naturally idempotent and does not hash manifests.

Enrichment classifies leaves, then directory README files from deepest to root, using their own text and completed child-file/README summaries. Directory nodes own no semantic or MIME fields; their names derive from README results. The publication transaction updates final names, Markdown links/README bytes, metadata and quota, then copies root README semantics to the original file. Direct sources keep their original names/bytes and create no artifacts. The single exact family:kind taxonomy is defined in the [protobuf contract](../packages/contracts/proto/openlet_api/letfs/v1/letfs.proto).

Indexing uses full text for overlapping chunks, independently of the enrichment sample. README files carry directory evidence; CSV/image files use context overviews. Qdrant stores dense vectors and native BM25. Immutable point IDs include source generation and full vector space. Readiness commits only after acknowledged writes and a live/current-generation recheck. Index-only rebuilds reuse `process-file/<file-id>/<generation>` with native Temporal duplicate policy, skipping completed parse/enrichment stages. One pipeline status records readiness. Cleanup uses current embedding configuration and file/generation tombstones; no per-file configuration history or space-specific workflow exists.

The Python application has two explicit process roles: `python -m letfs_ingest.worker cpu` registers parsing only and checks offline models/OCR; `python -m letfs_ingest.worker io` registers enrichment/indexing only and does not require parser preflight. Both roles propagate Temporal/gRPC/provider-HTTP trace context and shut down in a bounded time.


## Verification

Workflow tests check activity order, queue ownership, retry policies and child behavior. Real PostgreSQL/SpiceDB/Temporal tests cover publication failures, duplicate cleanup and restart accounting. Replay uses freshly exported histories; no production compatibility histories are required. See [testing](testing.md).
