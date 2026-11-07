# Openlet backend architecture

Openlet uses Go for Account, Workspace and LetFS, Python CPU/I/O ingest workers, Clerk, Envoy, PostgreSQL, SpiceDB, Temporal and S3-compatible storage. The [implementation plan](../plans/261106-1517-account-scope-temporal-redesign/plan.md) records scope and verification; executable contracts and migrations own the current interface and schema.

## Ownership

| Component | Owns |
|---|---|
| Envoy | JWT/JWKS verification, trusted identity forwarding, public routing and request bounds |
| Account | Independent accounts, immutable user/agent type, Clerk user identity, immutable managed-account owner and profiles |
| Workspace | Membership, invitations, one filesystem mapping, shared scope and each member's personal scope mapping |
| LetFS | Generic filesystem → scope → node, quota/counters, paths, bytes, uploads, trash, processing and cleanup |
| SpiceDB | Fixed resource relations and canonical direct scope grants |
| Temporal | Service-owned durable execution; application databases remain domain authorities |

Each service has its own PostgreSQL database and migrations, with no cross-service SQL/FKs. SpiceDB and Temporal have separate databases. A filesystem owns its byte limit, used bytes and node count. Physical S3 buckets are storage configuration.

## Identity and access

One `accounts` table holds `type=user|agent`. Users have a unique Clerk subject; managed accounts have an immutable `owner_id`. Owners can read/update the managed account profile without gaining its resources. Managed-account creation provisions no credentials, runtime or workspace. Agent execution and login are outside this design.

Onboarding ensures the account, waits for a child Workspace creation, then publishes `openlet_account_id` in backend-controlled Clerk metadata. Envoy forwards `x-openlet-account-id` after stripping caller-supplied trusted headers. Ordinary routes require that identity; only onboarding accepts a verified subject without the application claim. Completed onboarding relies on verified published identity and does not recreate a deleted initial workspace.

Private gRPC retains existing service authentication, allowlists and explicit actor delegation. Temporal runs in the private per-environment namespace with owner queues. Queue names do not authenticate callers.

Workspace roles are owner/admin/member. Scope roles are manager/editor/viewer. The fixed schema and generated [action matrix](../packages/contracts/authz/action-resource-matrix.md) define permissions. LetFS checks actor/resource/action; it never reads Workspace roles or account types. Filesystem administration grants no scope content rights. Metadata responses omit content context, and search/content providers require content-read admission.

One workspace has one filesystem, one shared scope and one personal scope per member. Shared owner/admin usersets grant manager and active members receive editor. Personal access defaults to its member alone. Removal revokes default membership access but retains personal storage; rejoin reuses it. Direct scope grants are canonical SpiceDB state and survive derived-relationship rebuilds.

## Storage and execution

Every node request names filesystem and scope. `/` means that scope's root; IDs, relative paths, cwd and aliases must reach its live root. Copy/move/restore may cross scopes in one filesystem with separate source/destination actions. File operations run directly in requests; processing remains an independent pipeline. No virtual root or path adapter is needed.

Files hold bounded inline bytes or an independent immutable object. Direct signed transfers avoid proxying object bodies. Generated children below a source file remain read-only; source generation and lifecycle fence late publication. Scope-owned `allow_blob_files` and `allow_indexing` options independently control object-backed files and search indexing; both default true. See [data invariants](data-model.md).

Short filesystem-row locks serialize accounting and lifecycle. Publication updates bytes/node count atomically with actual rows. Trash stays charged; actual deletion debits once. Network calls occur outside SQL transactions. Remaining rows and durable cleanup facts support repeat-safe deletion. Physical cleanup may follow logical completion.

Input/permission admission runs before starting workflows. Activities enforce transactional integrity and admitted-command identity. SQL followed by graph failure cannot report success; retries reconcile committed writes using existing receipts. Scope grants stay in SpiceDB. Copy runs synchronously with no automatic retry; partial committed output remains visible on failure.

The [workflow catalogue](workflows.md) specifies owner queues, child workflows and retry behavior. Shared `packages/go/temporal` contains cross-service names/DTOs and transport helpers, with no domain implementation. Workspace calls Account gRPC for bounded summaries/verified email. Account starts a Workspace child; Workspace schedules LetFS activities and deletion children directly. Workspace has no gRPC server.

## Repository and operations

Applications own `internal` feature, transport, config and Temporal packages. Shared Go/Python packages provide generated bindings, destination clients and infrastructure. Ingest owns parser and model/search clients; its CPU role registers parsing and its I/O role enrichment/indexing. Import tests enforce these boundaries.

Compose definitions live under `infra/compose`; contract sources under `packages/contracts`; bootstrap/recovery commands under `scripts`. Dependencies/images remain pinned. Keyset pages, file/body/node/copy bounds, member cap, transfer expiry and cleanup backpressure bound work. There is no workspace-count limit.

Services own graceful shutdown and OpenTelemetry providers. SDK tracing crosses Temporal and gRPC without business trace fields or secrets in payloads. [Setup](setup.md), [operations](operations.md) and [testing](testing.md) document the existing commands and isolated verification.
