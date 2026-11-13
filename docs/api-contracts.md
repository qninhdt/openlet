# API contracts

Core [Protobuf sources](../packages/contracts/proto/openlet_api/) own public/internal gRPC contracts and HTTP annotations. `make generate` produces Go/Python clients and the public descriptor consumed by Envoy. Core services use these contracts directly, without a REST wrapper or compatibility adapter.

Public Platform routes cover `/v1/me:onboard`, profile, workspaces, members and invitations. LetFS routes are nested under `/v1/workspaces/{workspace_id}/storages/{storage_id}`; workspace quota uses `/v1/workspaces/{workspace_id}/storage-quota`. Envoy routes them directly to their owning service. Tenant IDs are checked against owning SQL metadata.

HTTP uses native ProtoJSON: camelCase fields, enum names, UUID strings, decimal-string int64 values and RFC3339 timestamps. Failures use native `google.rpc.Status` JSON (`code`, `message`, optional `details`), not RFC9457. Standard gRPC-to-HTTP mappings apply, including InvalidArgument→400, PermissionDenied→403, NotFound→404, Aborted→409 and ResourceExhausted→429. JWT/edge rejection may have an Envoy-native error body.

Envoy verifies Clerk JWT/JWKS and strips caller-provided actor/subject headers before inserting verified claims. Onboarding accepts a verified Clerk subject and publishes the application user ID into backend-controlled Clerk metadata. Ordinary methods require the appropriate verified actor. Internal RPCs are absent from the public descriptor/routes. MVP service calls use the private network without custom service credentials; production may add native mTLS.

`x-openlet-zed-token` optionally requests SpiceDB `at_least_as_fresh`; otherwise checks use `minimize_latency`. New onboarding returns the final provisioning token as response metadata. Actor identity and authorization still apply when a token is supplied.

Mutations use requestId where declared, with service-owned PostgreSQL receipts. Text operations use strings and optional expectedVersion. Signed S3 URLs transfer blob bodies directly; text downloads return their PostgreSQL content. ZIP download is a gRPC stream of `google.api.HttpBody`, transcoded as raw ZIP bytes. It is not buffered as a whole archive or wrapped in JSON.

Leta uses direct HTTP JSON and SSE. Its [FastAPI declarations](../apps/leta/src/leta/api.py) own the transport schema; native `/openapi.json` is available on its private HTTP listener. Envoy forwards the approved `/v1/workspaces/{workspace_id}/letas` and `/v1/hitl-requests` routes without transcoding. Leta JSON fields use snake_case; UUIDs and timestamps are strings, and HTTP errors use FastAPI `detail`.

Under a Leta resource, routes cover configuration, messages, boxes, operators, HITL requests and schedules. Agent routes provide history previews/entry content, run state and cancel. Incoming HITL cards/answers use `/v1/hitl-requests` and require the exact addressed user. There is no separate chat transport: posting to `messages` admits work; `events` streams native AG-UI events plus namespaced Openlet state notifications.

A fresh event connection returns a bounded snapshot, history previews/references and the Redis cursor. A valid reconnect cursor reads the retained suffix; an expired cursor requests canonical refresh. Full tool output is read by history entry. Token chunks are provisional Redis events, not PostgreSQL writes. Stable request/message IDs preserve durable admission; request IDs cannot be reused for different input. See the [streaming contract](../plans/261111-2010-leta-rewrite/streaming.md) and [execution status](../plans/261111-2010-leta-rewrite/execution.md).

Leta model choices are available at `GET /v1/workspaces/{workspace_id}/letas/models`
after workspace participation authorization. The response exposes logical `model_id`
and verified `reasoning_efforts` only; deployments and credentials remain private.
PATCH keeps omitted selections, but changing `model_id` without an effort clears the
old effort. `model_id: null` resets both fields to defaults/inheritance. An effort-only
update requires an existing explicit model; null effort omits a provider override.
