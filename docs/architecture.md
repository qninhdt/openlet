# Openlet backend architecture

Openlet uses Go for Account, Workspace and LetFS, Python Leta API/agent and CPU/I/O ingest workers, Redis, Clerk, Envoy, PostgreSQL, SpiceDB, Temporal and S3-compatible storage. The [implementation plan](../plans/261108-0001-leta-agent-engine/plan.md) records scope and verification; executable contracts and migrations own the current interface and schema.

## Ownership

| Component | Owns |
|---|---|
| Envoy | JWT/JWKS verification, trusted identity forwarding, public routing and request bounds |
| Account | Human-only users, Clerk onboarding/identity, self-profile and private human summaries/emails |
| Workspace | Membership, invitations, one filesystem mapping, shared scope and each member's personal scope mapping |
| LetFS | Generic filesystem → scope → node, quota/counters, paths, bytes, uploads, trash, processing and cleanup |
| Leta | Workspace-owned agents, immutable communication boxes, inbox/history, human requests, schedules and checkpointed inference |
| Redis | Disposable Mirage cache and per-root-Leta replay streams |
| SpiceDB | Fixed resource relations and canonical direct scope grants |
| Temporal | Service-owned durable execution; application databases remain domain authorities |

Each service has its own PostgreSQL database and migrations, with no cross-service SQL/FKs. SpiceDB and Temporal have separate databases. A filesystem owns its byte limit, used bytes and node count. Physical S3 buckets are storage configuration.

## Identity and access

The identity service stores human users with unique Clerk subjects. Leta is a separate workspace resource, with no user row, login or workspace membership; Leti inherits its root Leta subject. Every root has an ordinary LetFS home scope; Leti has no independent identity. Managed-account routes and self/owner graph relations are removed.

Onboarding ensures the human user, waits for a child Workspace creation, then publishes `openlet_user_id` in backend-controlled Clerk metadata. Envoy forwards `x-openlet-user-id` after stripping caller-supplied trusted headers. Ordinary routes require that identity; only onboarding accepts a verified subject without the application claim. Completed onboarding relies on verified published identity and does not recreate a deleted initial workspace.

Private gRPC retains service credentials and exact method allowlists. Delegation carries a typed user/Leta UUID in mutually exclusive trusted headers. Gateway credentials accept humans only; Leta requires an explicit per-method delegation allowlist. Authorization and upload/idempotency/cursor ownership retain the subject kind even when UUIDs match. Temporal runs in the private per-environment namespace with owner queues. Queue names do not authenticate callers.

Workspace roles are owner/admin/member. Scope roles are manager/editor/viewer. The fixed schema and generated [action matrix](../packages/contracts/authz/action-resource-matrix.md) define permissions. LetFS checks actor/resource/action; it never reads Workspace roles or user/agent ownership. Filesystem administration grants no scope content rights. Metadata responses omit content context, and search/content providers require content-read admission.

One workspace has one filesystem, one shared scope and one personal scope per member. Shared owner/admin usersets grant manager and active members receive editor. Personal access defaults to its member alone. Removal revokes default membership access but retains personal storage; rejoin reuses it. Direct scope grants are canonical SpiceDB state and survive derived-relationship rebuilds.

## Storage and execution

Every node request names filesystem and scope. `/` means that scope's root; IDs, relative paths, cwd and aliases must reach its live root. Copy/move/restore may cross scopes in one filesystem with separate source/destination actions. File operations run directly in requests; processing remains an independent pipeline. Native callers address scope roots directly; agent paths use the Mirage mount adapter below.

Files hold bounded inline bytes or an independent immutable object. Direct signed transfers avoid proxying object bodies. Generated children below a source file remain read-only; source generation and lifecycle fence late publication. Scope-owned `allow_blob_files` and `allow_indexing` options independently control object-backed files and search indexing; both default true. See [data invariants](data-model.md).

Short filesystem-row locks serialize accounting and lifecycle. Publication updates bytes/node count atomically with actual rows. Trash stays charged; actual deletion debits once. Network calls occur outside SQL transactions. Remaining rows and durable cleanup facts support repeat-safe deletion. Physical cleanup may follow logical completion.

Input/permission admission runs before starting workflows. Activities enforce transactional integrity and admitted-command identity. SQL followed by graph failure cannot report success; retries reconcile committed writes using existing receipts. Scope grants stay in SpiceDB. Copy runs synchronously with no automatic retry; partial committed output remains visible on failure.

The [workflow catalogue](workflows.md) specifies owner queues, child workflows and retry behavior. Shared `packages/go/temporal` contains cross-service names/DTOs and transport helpers, with no domain implementation. Workspace calls Account gRPC for bounded summaries/verified email. Account starts a Workspace child; Workspace schedules LetFS activities and deletion children directly. Workspace exposes a Leta-only native gRPC server for workspace/member/scope discovery, home provisioning, personal-scope grants and direct access cleanup. Normal changes share WorkspaceChanges serialization; cleanup/status callbacks stay outside that queue to avoid deletion recursion.

## Agent execution and public history

Each agent keeps one lifetime LangGraph thread. Its async runtime checkpoints complete tool groups, a bounded working history/current summary and the inbox cursor in PostgreSQL. Temporal coordinates wake-up and recovery; completed checkpoint output is resumed or finalized without restarting the model solely to regenerate history.

The independently queryable public transcript contains typed inbox inputs, assistant output, tool calls/results, short final notes and compaction entries. Inbox cards and summary cards use persisted metadata, without parsing internal prompt text. Compaction preserves the complete selected older prefix and records the exact checkpointed summary before the next model call. A pending inbox batch can force earlier compaction and remains intact; later arrivals wait for the next boundary. Provider-private reasoning is excluded before summary inference and public persistence. History tools select only the current agent's transcript; creator APIs and live Redis publication expose this typed history.

One `send_message` tool resolves recipients from the server-provided roster: Leta addresses its creator or a box, Leti addresses adjacent peers, and the representative returns to its parent through the same box ID. Agent delivery waits for an inbox SQL commit through Temporal Update-with-Start, independently of the recipient's model execution. Final text remains a note. Leta's list/read inbox tools expose grouped sources and bounded details; read markers commit with saved tool results and do not complete work or advance the checkpoint cursor.

LetaLifecycleWorkflow and BoxLifecycleWorkflow serialize resource commands separately from each agent's working loop. Their Local Activities perform short SQL; regular Activities provision native homes, publish Leta-owned access relationships and start/control independent AgentWorkflows. Box creation saves its entire immutable graph before provisioning and starts idle agents without sending work. Deletion waits for runtime cleanup before trashing the reserved home ID; ordinary Leta archive retains files/history and resource tuples. Canonical delete targets are retained in the existing public tool-call record so retry cannot delete a replacement that reused a name. Workspace deletion closes admission, waits for all canonical Leta resources to stop and settle HITL/schedules, then deletes storage. Cleanup callbacks avoid reentering the mutex-held WorkspaceChanges coordinator.

## Agent filesystem

Leta's invocation-owned Mirage workspace borrows native service clients and mounts `/home`, `/shared` and approved `/users/<user-id>` scopes. Leti uses the same root Leta authority with its box directory as the backend-enforced home root. Tools and Monty use the same session; all paths, including original-file ID aliases and both copy endpoints, retain their mount roots. Original blobs expose metadata and real artifact children, while `read_file` can return a bounded image preview.

The adapter maps Mirage's native read, text mutation, listing, search and copy hooks to bounded LetFS RPCs. Redis FRESH caching checks current native permissions and representation fingerprints before cache reuse, including repeated reads inside a command. Session mounts refresh between tools; native authorization already enforces revocation before refresh. Shells execute in Mirage and Python in Monty without host filesystem or network access. `tail -f` polls unary range reads for the lifetime of its command; it opens no backend subscription.

## Repository and operations

Applications own `internal` feature, transport, config and Temporal packages. Shared Go/Python packages provide generated bindings, destination clients and infrastructure. Ingest owns parser and model/search clients; its CPU role registers parsing and its I/O role enrichment/indexing. Import tests enforce these boundaries.

Compose definitions live under `infra/compose`; contract sources under `packages/contracts`; bootstrap/recovery commands under `scripts`. Dependencies/images remain pinned. Keyset pages, file/body/node/copy bounds, member cap, transfer expiry and cleanup backpressure bound work. There is no workspace-count limit.

Services own graceful shutdown and OpenTelemetry providers. SDK tracing crosses Temporal and gRPC without business trace fields or secrets in payloads. [Setup](setup.md), [operations](operations.md) and [testing](testing.md) document the existing commands and isolated verification.
