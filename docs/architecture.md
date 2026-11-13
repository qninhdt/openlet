# Architecture

Each service owns its database. Services communicate through generated gRPC contracts, with no cross-service SQL or foreign keys.

| Component | Owns |
|---|---|
| Platform | Human identity, Clerk onboarding, workspace metadata, invitations and membership commands |
| LetFS | Workspace storages, access commands, quota/usage, nodes, text/blob content, uploads, trash and processing publication |
| Leta | Root/Leti configuration, boxes, inbox, runs, canonical history, HITL and schedules |
| Ingest CPU | Offline Docling/Office conversion and parse manifests |
| Ingest IO | Model enrichment and Qdrant indexing |
| Redis | Disposable Leta event suffixes and native Mirage content/index cache |
| SpiceDB | Canonical membership, ownership and grants |
| Temporal | Durable provisioning, workspace deletion, blob processing and maintenance |
| Envoy | JWT/JWKS validation, trusted actor headers, routing and public gRPC JSON transcoding |

Workspace is the tenant. Storage, agent and future computer are sibling resources. Platform does not proxy storage operations or depend on a running agent service. Leta owns its own resources and agent graph edges; it uses core gRPC APIs as an independent actor.

Storage visibility is private/public. Public grants eligible workspace actors read access; writing requires owner/editor. Workspace owner/member and storage owner/editor/viewer are defined in the [SpiceDB schema](../packages/contracts/authz/schema.zed). Domain SQL has no role/grant mirror. UI role lists read native graph relations and bulk-hydrate domain metadata.

Checks default to `minimize_latency`; callers can send `x-openlet-zed-token` for `at_least_as_fresh`. Onboarding returns the final provisioning write token. Member-storage provisioning carries the membership write token into its activity and LetFS reads. Revocation may take time to propagate for callers using the default consistency, and signed URLs remain usable until expiry.

Text is UTF-8 in PostgreSQL. Blobs use immutable S3 objects and direct signed transfers. Only blobs are ingested; artifacts live below their source file and are readonly. SQL publication validates the source's single content version. No filesystem/scope entity, whole-storage lock, lease or distributed fencing service exists. See [data model](data-model.md) and [workflows](workflows.md).

Semantic search combines dense vectors and native BM25 over Qdrant text payloads using RRF, validates current file versions and ancestry in SQL, then reranks. Both retrieval branches use the workspace filter. Bootstrap creates the BM25 text index; no second embedding model is needed.

Go services expose gRPC only. Envoy serves ProtoJSON and raw streamed ZIP responses; blob bytes bypass applications through signed S3 URLs. Native OpenTelemetry instruments gRPC, PostgreSQL, Temporal and outbound provider calls. Optional OTLP export adds no application HTTP metrics server.

Leta exposes FastAPI HTTP/JSON and AG-UI SSE behind Envoy. One image supplies API and worker processes; the worker serves orchestration, runtime and bridge queues. Each agent has a native LangGraph checkpoint thread and Langfuse session. Model/tools use the native agent loop; Temporal sees orchestration events, not individual model/tool steps. PostgreSQL stores canonical history and native checkpoints; Redis contains bounded provisional events and filesystem caches. See [observability](observability.md) and the [approved Leta design](../plans/261111-2010-leta-rewrite/design.md).
