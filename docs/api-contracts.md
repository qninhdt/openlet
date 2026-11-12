# API contracts

[Protobuf sources](../packages/contracts/proto/openlet_api/) own public/internal gRPC contracts and HTTP annotations. `make generate` produces Go/Python clients and the public descriptor consumed by Envoy. No handwritten transport DTOs, REST wrapper, compatibility adapter or separate OpenAPI authority is maintained.

Public Platform routes cover `/v1/me:onboard`, profile, workspaces, members and invitations. LetFS routes are nested under `/v1/workspaces/{workspace_id}/storages/{storage_id}`; workspace quota uses `/v1/workspaces/{workspace_id}/storage-quota`. Envoy routes them directly to their owning service. Tenant IDs are checked against owning SQL metadata.

HTTP uses native ProtoJSON: camelCase fields, enum names, UUID strings, decimal-string int64 values and RFC3339 timestamps. Failures use native `google.rpc.Status` JSON (`code`, `message`, optional `details`), not RFC9457. Standard gRPC-to-HTTP mappings apply, including InvalidArgument→400, PermissionDenied→403, NotFound→404, Aborted→409 and ResourceExhausted→429. JWT/edge rejection may have an Envoy-native error body.

Envoy verifies Clerk JWT/JWKS and strips caller-provided actor/subject headers before inserting verified claims. Onboarding accepts a verified Clerk subject and publishes the application user ID into backend-controlled Clerk metadata. Ordinary methods require the appropriate verified actor. Internal RPCs are absent from the public descriptor/routes. MVP service calls use the private network without custom service credentials; production may add native mTLS.

`x-openlet-zed-token` optionally requests SpiceDB `at_least_as_fresh`; otherwise checks use `minimize_latency`. New onboarding returns the final provisioning token as response metadata. Actor identity and authorization still apply when a token is supplied.

Mutations use requestId where declared, with service-owned PostgreSQL receipts. Text operations use strings and optional expectedVersion. Signed S3 URLs transfer blob bodies directly; text downloads return their PostgreSQL content. ZIP download is a gRPC stream of `google.api.HttpBody`, transcoded as raw ZIP bytes. It is not buffered as a whole archive or wrapped in JSON.

Leta API/runtime remains deferred to its separate rewrite; no legacy Leta HTTP route is a replacement contract.
