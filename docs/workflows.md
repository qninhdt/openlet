# Temporal workflows

Temporal uses PostgreSQL persistence and native SDK workers. Each owner registers its workflows/activities on the queues in the common YAML; the shared workspace-cleanup activities use a minimal JSON payload.

| Owner | Workflow | Behavior |
|---|---|---|
| Platform | ProvisionWorkspace | Platform admits SQL identity/workspace and provisions access; LetFS provisions initial storages; Platform activates |
| Platform | ProvisionMemberStorage | LetFS worker checks membership and provisions personal storage in-process when needed |
| Platform | DeleteWorkspace | Revoke access, dispatch LetFS storage and Leta agent cleanup, delete workspace row after storage ACK, await agents |
| Platform | Maintenance | Expire receipts/invitations and redispatch admitted deletion |
| LetFS | ProcessBlob | CPU ParseBlob when required, then IO EnrichAndIndex; report failure after retries |
| LetFS | Maintenance | Expire uploads, recover pending dispatch and collect unreferenced objects/index points |

Platform and LetFS maintenance run from native Schedules with overlap Skip. Storage cleanup and Platform SQL deletion do not wait for Leta. The workflow remains pending until agent cleanup completes, including while Leta is offline. Both cleanup activities use native retries without a total lifetime limit. Storage visibility is immutable after provisioning; UpdateStorage only renames.

Workspace cleanup activities receive `{"workspace_id":"<uuid>"}`. Platform routes `DeleteWorkspaceStorage` to the LetFS queue and `DeleteWorkspaceAgents` to `leta_bridge`. Provisioning activities also run on the owning LetFS worker and call feature functions directly.

Deployment changes workflow command sequences and inputs. Drain or recover old open executions before switching workers; do not deploy the new definitions into old running histories or reset an existing namespace. Leta cutover uses a fresh database and namespace as described in its plan.

Processing carries file ID/content version and queue/timeout settings. Contents, manifests and chunks stay outside Temporal history. CPU downloads a signed source, converts it in a bounded subprocess with offline assets and publishes a manifest through LetFS. Text artifacts stay in PostgreSQL; binary artifacts upload through signed S3 URLs. IO enriches leaves then folder READMEs, indexes full text with ancestor context, and marks readiness only after acknowledged Qdrant writes.

Activities resume from committed parse/enrichment stages. Publication checks the current source version; late work cannot replace current content. Parser invalid-input errors are terminal; transient transfers/provider failures use native Temporal retries. There is no second generation counter, supervisor, leasing framework or automatic reprocessing on permission/configuration changes.

File copy, move, text mutations, trash and purge run directly in owning SQL transactions. They do not create a Temporal workflow per node.

Native Temporal SDK interceptors propagate traces. Both Python roles heartbeat and drain on shutdown. See executable registrations in [Platform](../apps/platform/internal/platform/provisioning.go) and [LetFS](../apps/letfs/internal/storage/jobs.go).
