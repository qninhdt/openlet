# Temporal workflows

Temporal uses PostgreSQL persistence and native SDK workers. Each owner registers its workflows/activities on the queues in the common YAML; no shared workflow implementation or callback bridge exists.

| Owner | Workflow | Behavior |
|---|---|---|
| Platform | ProvisionWorkspace | Admit SQL identity/workspace, provision graph/storage, activate workspace |
| Platform | ProvisionMemberStorage | Create a member's storage through LetFS when needed |
| Platform | DeleteWorkspace | Revoke workspace graph, delete owning LetFS storage data, delete workspace row |
| Platform | Maintenance | Expire receipts/invitations and redispatch admitted deletion |
| LetFS | UpdateStorageVisibility | Converge local metadata and canonical graph visibility |
| LetFS | ProcessBlob | CPU ParseBlob when required, then IO EnrichAndIndex; report failure after retries |
| LetFS | Maintenance | Expire uploads, recover pending dispatch and collect unreferenced objects/index points |

Platform and LetFS maintenance run from native Schedules with overlap Skip. Workspace deletion has no Leta stop/ACK dependency.

Processing carries file ID/content version and queue/timeout settings. Contents, manifests and chunks stay outside Temporal history. CPU downloads a signed source, converts it in a bounded subprocess with offline assets and publishes a manifest through LetFS. Text artifacts stay in PostgreSQL; binary artifacts upload through signed S3 URLs. IO enriches leaves then folder READMEs, indexes full text with ancestor context, and marks readiness only after acknowledged Qdrant writes.

Activities resume from committed parse/enrichment stages. Publication checks the current source version; late work cannot replace current content. Parser invalid-input errors are terminal; transient transfers/provider failures use native Temporal retries. There is no second generation counter, supervisor, leasing framework or automatic reprocessing on permission/configuration changes.

File copy, move, text mutations, trash and purge run directly in owning SQL transactions. They do not create a Temporal workflow per node.

Native Temporal SDK interceptors propagate traces. Both Python roles heartbeat and drain on shutdown. See executable registrations in [Platform](../apps/platform/internal/platform/provisioning.go) and [LetFS](../apps/letfs/internal/storage/jobs.go).
