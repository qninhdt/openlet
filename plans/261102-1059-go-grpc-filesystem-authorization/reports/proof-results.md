# Foundation proof results

Historical evidence note: the November 2 user correction supersedes SQL role catalogs and the head/intent/ack/epoch runtime framework described below. The [current architecture](../architecture-contract.md) and [Phase 3](../phase-03-workspace-authorization-and-durable-projection.md) govern execution. Prior test results remain records of the tested revision, not acceptance of the revised synchronization implementation.

Status: Phase 1 proof gates passed. These results are implementation evidence, not final acceptance of the migration. The Rust runtime, public routes and Temporal registrations remain active and unchanged; no existing environment data was reset or migrated.

## Selected versions

| Component | Pin and observed compatibility |
|---|---|
| Go | Existing 1.27.3; native modules compile and run |
| PostgreSQL | Existing `18.6-trixie@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336`; fresh Testcontainers fixtures |
| SpiceDB | `v1.57.0@sha256:2e0cd20aa923ccfd96eb285756ec10a5d7bbe387e4b29c26bd6447435d2328de`; migration and actual PostgreSQL datastore checks/writes passed on amd64; this is a platform digest |
| Official Go authorization SDK | `github.com/authzed/authzed-go v1.11.0`; native preconditions, fully-consistent reads and schema validated |
| Go application transport | Existing-compatible grpc `v1.83.2`, protobuf `v1.36.11`, grpc-gateway `v2.29.0` |
| Go codegen tools | `protoc-gen-go v1.36.11`, `protoc-gen-go-grpc v1.6.2`, `protoc-gen-grpc-gateway v2.29.0`, `protoc-gen-connect-openapi v0.24.0`; module/tool/sum pins |
| Buf | `@bufbuild/buf 1.69.0`; googleapis dependency locked in `packages/contracts/buf.lock` |
| Python contracts | grpcio/grpcio-tools `1.85.1`, protobuf `7.36.2`, googleapis-common-protos `1.76.0`; shared wheel imports and locked installs passed |
| Envoy | Existing `v1.37.0@sha256:d9b4a70739d92b3e28cd407f106b0e90d55df453d7d87773efd22b4429777fe8`; actual JWT/RBAC/HTTP2 container fixture passed |
| SQL driver and fixtures | Existing pgx `v5.8.0`, Testcontainers Go `v0.44.0` |

The OpenAPI generator version was selected to retain the established protobuf runtime; its native 3.1 output is parsed and its V3 model built with `libopenapi`. Generation enables only `google.api.http` and the public filesystem service. It does not advertise unimplemented Connect, administration or ingest routes. Authored Account/Workspace HTTP and generated letfs transport documents remain separate.

## Authorization graph: PASS

Command: `go -C packages/go test -tags integration ./authz -count=1 -v`.

Real PostgreSQL-backed SpiceDB proves:

- Atomic expected-head plus current-epoch preconditions and business relationship updates in one `WriteRelationships` transaction.
- A delayed old attempt fails after a newer revoke; duplicate delivery cannot reapply effects.
- Lost acknowledgment can observe the graph head consistently; an older event sees a later gap-free head.
- First-create races with competing grant payloads have exactly one winner and no losing grant leak.
- Erasing business tuples and heads followed by a new rebuild epoch rejects an old create/revoke.
- An independent client sees inherited filesystem revoke using `fully_consistent`, without receiving the writer's token.
- Representative role/grant intersections, foreign filesystem/bucket denial and atomic role transfer updates.
- Canceled authorization returns an error and never permits access.
- An explicit version-2-before-version-1 delivery is rejected without leaking its grant.
- Stopping the real SpiceDB server after a successful permission check makes the next check fail closed; no previous grant is reused.

This is the native graph protocol proof. The canonical waiter proof below extends it; full built-in role catalog fixtures, API adoption and persistent Temporal recovery remain later-phase acceptance. A head observation alone is not treated as an acknowledgment of missing canonical events.

## Canonical acknowledgment and waiter: PASS

Commands:

```sh
go -C apps/workspace test -tags integration ./internal/workspace -run Projection -count=1
go -C apps/workspace test -race -tags integration ./internal/workspace -count=1
go -C apps/workspace test ./...
go -C apps/workspace vet -tags integration ./...
docker build -f apps/workspace/Dockerfile .
```

The actual Workspace owner baseline and projection implementation are initialized here for the required SQL proof; Phase 3 wires them into domain operations and Temporal. `AppendProjection` runs inside the caller's domain transaction, serializes the canonical aggregate version and stores immutable tuple payload plus requested response. No network call holds its SQL lock.

Observed with real canonical PostgreSQL and PostgreSQL-backed SpiceDB:

- Two stored intents commit through graph CAS; SQL first acknowledges the observed N+1 head. The N waiter returns its saved N response with current canonical high-water. A delayed N acknowledgment cannot regress version or opaque token.
- Unknown-ahead heads and missing canonical events reject acknowledgment; observing a graph head cannot hide a log gap.
- Transaction rollback removes the head as well as the event.
- Maintenance installs a fresh graph epoch/snapshot head; the owner marks previously unacknowledged events superseded. Their waiters return `PROJECTION_SUPERSEDED` and current version. Already-acknowledged results retain success evidence.
- A stale epoch cannot commit to the graph or acknowledge SQL. New-epoch events continue from the snapshot high-water.
- Request timeout stops waiting; later acknowledgment and a new waiter still succeed.
- The complete existing Workspace SQL integration suite and race checks pass. Its Docker build resolves the real shared module through the same relative module path.

Current public role mutation handlers do not dispatch or await projection yet; that adoption is Phase 3. Account must reuse the same completion rule for its own canonical projection.

## Transport and shared packaging: PASS for the measured boundaries

Commands:

```sh
pnpm contracts:generate
pnpm contracts:check
go -C packages/go test ./rpc
go -C packages/go test -tags integration ./rpc ./authz -count=1
pnpm --filter @openlet/python check
pnpm --filter @openlet/python test
pnpm --filter @openlet/python test:integration
docker build --target package -f apps/letfs-processing/Dockerfile .
```

Observed:

- Reproducible Go/Python generation into shared package paths; no app-local stubs or manual import patches.
- OpenAPI 3.1 model validation, explicit public annotated route and no inferred internal/Connect routes.
- Clean shared/app wheel installation outside the checkout and isolated Python generated client to generated Go server RPC.
- Generated in-process JSON mapping preserves decimal int64 and optional-field absence. Thin HTTP byte adapters call the same fixture application operation and explicitly authenticate because in-process registration bypasses gRPC interceptors.
- Exact arbitrary inline bytes, single/suffix/open-ended Range, metadata, 307 signed-object redirect, ETag, MIME, attachment, nosniff and no-store through real HTTP.
- Native gRPC cancellation reaches a running handler; ZIP error after flushed headers truncates the body without appended JSON; disconnect releases the request-owned slot.
- Native archive streams authenticate through the streaming interceptor, emit metadata before <=64KiB data frames, reconstruct an actual ZIP and sanitize terminal trailer errors. An unread 32MiB producer is blocked by real gRPC flow control; cancellation releases it.
- An actual Envoy fixture derived from the current JWT/header/RBAC template verifies JWTs, replaces spoofed/duplicate actor headers, denies absent claims and public administration method paths, forwards HTTP ranges and propagates native cancellation.
- The initial private Ingest contract has no public route; both application method authority and actual Envoy deny it. Native archive passes the exact public allowlist.
- Shared application faults retain machine codes and map precondition-required/revision mismatch/expired copy/body limit/range to HTTP 428/412/410/413/416.
- The current processor Docker package stage installs locked dependencies and builds both wheels, without invoking model download or changing default worker registration.

The actual target letfs HTTP adapters additionally pass exact bytes and selected MIME/attachment/nosniff, empty/suffix/open-ended/clamped/duplicate/malformed/overflow/unsatisfied Range with structured `INVALID_RANGE`, object redirect validation, revision query, bounded/streamed oversized JSON, strict If-Match and 201/202 relative Location/ETag/decimal-string mappings. Commands: `go -C apps/letfs test ./internal/http` and `go -C apps/letfs test -race ./internal/http`.

Transport fixtures and adapters prove selected mapping and lifetime primitives, not eventual storage, full public permission or complete archive traversal. Later application parity tests must exercise these same adapters with real domain operations. Full public/admin/ingest ownership and remaining wire expansion are explicit in the [RPC ledger](../../../packages/contracts/rpc-surface.md); initial generated boundaries include all three service classes without pretending every handler exists.

## Stable provisioning identity: PASS for the implemented core

Commands:

```sh
go -C apps/letfs test ./...
go -C apps/letfs test -tags integration ./internal/filesystem ./internal/grpc -count=1 -v
go -C apps/letfs test -race -tags integration ./internal/filesystem ./internal/grpc -count=1
cargo test --locked --package letfs --test integration workspace_provisioning -- --ignored --test-threads=1
```

The Phase 1 proof uses the actual target `github.com/qninhdt/openlet/apps/letfs` module, generic provisioning implementation, generated administration server and the single baseline SQL. Phase 4 extends this implementation; there is no separate prototype module or duplicate storage schema.

Observed with fresh owned PostgreSQL fixtures:

- Concurrent retries converge on one bucket/filesystem/root, including a different request key for the same admitted resource ID.
- Request-key/input conflicts roll back the entire transaction, including a just-inserted resource.
- Caller namespaces do not collide, and a second generic caller cannot administer the first caller's bucket.
- Immutable create fingerprints compare input after receipt pruning and mutable quota changes; they are never lookup keys and carry no business-resource mapping.
- Freeze may tombstone an unknown preallocated bucket ID. Both serialization orders of concurrent create/freeze end frozen; late create cannot resurrect frozen/deleted IDs, including after receipt expiry.
- Root identity release is naturally idempotent; wrong-root release fails. Bucket deletion is blocked by an active filesystem or wrong local lifecycle.
- Actual gRPC calls preserve int64 limits and stable IDs; missing/spoofed service identity and public gateway authority fail before storage mutation.
- The unchanged Rust provisioning integration test passes against the compatible baseline. Legacy provision columns are nullable solely to preserve that reference; Go never writes/reads them. Their final removal remains mandatory at cutover.

This does not prove full filesystem deletion/cleanup, node/upload/quota parity or final public operation authorization. Those remain planned owner work.

## Review correction

The conditional simplify review identified one concrete defect: native gRPC forwarded raw handler errors while HTTP sanitized them. Shared `NormalizeError` now retains trusted Openlet fault details, maps context errors and hides raw driver/dependency messages consistently. Native interceptor regression cases cover raw secrets, dependency status secrets, trusted faults, cancellation and deadline. This correction does not add another policy layer.

## Completion review and downstream scope

The required conditional simplify review examined SQL acknowledgment, saved response, supersession, locking, HTTP ranges/body bounds and native streaming authority/lifetimes. No unresolved concrete defect remains. A suggestion to add inline attachment filenames was rejected against the verified Rust `http/mod.rs::inline_content` behavior (`Content-Disposition: attachment`) and accepted preservation contract; archive filename encoding remains separately required.

Final observed checks include native/Envoy RPC race tests, generated drift checks, Python shared/app clean-wheel installation and client/server imports after adding Ingest, and both owner/shared integration-tagged vet checks. All required Phase 1 protocol/transport proof gates now pass. Phase 2 extends contracts/infrastructure; Phase 3 adopts the existing Workspace canonical proof implementation; Phase 4 adopts the existing Go provisioning and HTTP adapters.

No production/provider performance claim, existing-data restore, runtime cutover, full E2E/replay/parser suite or final migration acceptance is asserted here. Phases 2–7 remain incomplete.
