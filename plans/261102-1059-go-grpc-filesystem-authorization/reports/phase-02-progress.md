# Phase 2 implementation evidence

Historical evidence note: the November 2 user correction supersedes SQL role catalogs and the head/intent/ack/epoch runtime framework described below. The [current architecture](../architecture-contract.md) and [Phase 3](../phase-03-workspace-authorization-and-durable-projection.md) govern execution. Prior test results remain records of the tested revision, not acceptance of the revised synchronization implementation.

Status: complete. Phases 1–2 are complete; Phases 3–7 remain required. No runtime cutover, deployment to an existing database, commit or push has occurred.

## Shared foundation

- Account/Workspace now use the same file-secret loader and telemetry provider implementation from `packages/go`. App-local configuration validation and shutdown ownership remain unchanged. `_FILE` precedence and no direct-value fallback after an unreadable file are tested.
- Shared native gRPC has verified TLS by default, explicit trusted-local plaintext, authenticated service/method allowlists, user delegation, 8 MiB messages, 16 KiB headers, a 120-second unary ceiling and 1800-second stream ceiling. Caller deadlines can shorten those bounds. Connections remain caller-owned; canceled/terminal streams release timers.
- Account/Workspace HTTP gateway admission now shares `identity.AuthenticateGateway` and installs a verified principal in request context. Only Account's exact GET/PUT onboarding route accepts Clerk-subject-only identity, with no user authority even if a user header is supplied. Duplicate trusted identity, invalid/missing user IDs on ordinary routes, and empty gateway configuration fail closed. Existing HTTP error codes/messages remain; bootstrap duplicate-user headers and unsupported subject-only methods now reject explicitly.
- Explicit method-scoped service credentials are tested separately from gateway identity. Ingest cannot delegate a user or call public filesystem methods; a delegated Workspace caller gains only its configured methods. Actual generation/stage/attempt record checks remain owned by the future ingest handlers, not arbitrary trusted metadata.
- Configured application retries are disabled. Native pre-application transparent retries are not claimed disabled. Trace context propagates without baggage. Health status belongs to the real application and its dependencies.
- Initializer `authz-schema` uses the official SDK: initialize only a genuinely missing schema, verify repeated startup, and reject unknown existing schema. Canonical schema formatting follows the pinned server output without changing definition bodies.
- Independent Go module resolution, Account/Workspace Docker builds and the shared/app Python wheels were verified during foundation work. Generated Go/Python code stays in shared packages. Python client/server interfaces work outside the checkout without editable imports or repository `PYTHONPATH`.

Account/Workspace Docker images were rebuilt successfully after the latest shared-principal adoption. Build logs are local-only at `/tmp/openlet-phase2-account-build.log` and `/tmp/openlet-phase2-workspace-build.log`. All owned test/build processes have exited, and no Compose fixture container remains.

## Contract expansion

The [RPC ledger](../../../packages/contracts/rpc-surface.md) now links every inventoried public filesystem and private ingest operation to generated request/response messages. Source comparison covered node metadata, locators/mounts, copies, processing status, trash, upload receipts/publication/parts, search breadcrumbs, parse/enrichment manifests and exact vector-space identity. Native bytes and int64 retain the required information; HTTP adapters must preserve existing flattening, decimal strings, status and headers.

Node uses optional `media_type`; Download/ArchiveMetadata still use `mime`. Public upload completion returns node ID/revision, private output completion returns upload ID/status/size, and inline output reception does not publish the artifact. Processing status includes the source file ID and processing requests carry generic path context.

These are contracts, not working domain handlers. Only GetNode has a generated HTTP annotation so far; the remaining public mappings and actual permission/domain adoption remain required. No private Ingest method has a public route.

## Actual development Compose graph: PASS

`scripts/bootstrap/configure.py` creates/preserves the dedicated graph key and PostgreSQL owner/database configuration. Dev and E2E Compose definitions include the pinned SpiceDB migration/server and schema job. No graph host port is published; Watch and outbound upstream telemetry are disabled; read/write pools cap at eight each. The E2E harness renders the dedicated database and native configuration, then waits for graph health and schema initialization before application startup.

The real `scripts/bootstrap/test_graph.py` runs the development definition with a unique disposable project, generated fixture configuration and fresh PostgreSQL 18.6. It verified:

1. Native configuration loads for datastore migration and server startup.
2. Migration completes before native gRPC health is ready.
3. Missing schema initialization, read-only check and repeated initialization succeed.
4. `openlet_spicedb` owns its dedicated database.
5. A wrong mounted schema credential fails with PermissionDenied.
6. Revoking the disposable database role's login makes a forced datastore migration fail; the dependent graph server stays stopped and only PostgreSQL remains running.
7. Cleanup removes only the unique fixture resources; logs redact fixture credentials.

CI executes the bootstrap configuration and real Compose graph tests. Configured single-instance runtime pools total a conservative 144 connections: application pools 48, both Temporal stores across four components at most 80, and SpiceDB 16. Operations documents an additional 12-connection transient allowance, leaving 44 for health/operator sessions and server reserve. The full-stack recovery test observed 22 client connections: Account 1, Workspace 1, letfs 2, SpiceDB 4, Temporal persistence 8, Temporal visibility 5, and the PostgreSQL probe 1. It checks live counts against the configured runtime budget. This is startup evidence, not a load benchmark.

## Verified commands on the current contract revision

```sh
pnpm contracts:generate
pnpm contracts:check
go -C packages/go test ./...
go -C packages/go vet -tags integration ./...
go -C packages/go test -race ./identity ./rpc
go -C packages/go test -tags integration ./rpc -count=1
go -C apps/letfs test ./...
GOWORK=off go -C apps/account test ./...
GOWORK=off go -C apps/workspace test ./...
go -C apps/account vet -tags integration ./...
go -C apps/workspace vet -tags integration ./...
pnpm --filter @openlet/go check
pnpm --filter @openlet/python check
pnpm --filter @openlet/python test
pnpm --filter @openlet/python test:integration
uv run --locked --package openlet-processor pytest scripts/bootstrap -q
uv run --locked --package openlet-processor ruff check scripts/bootstrap
uv run --locked --package openlet-processor ruff format --check scripts/bootstrap
uv run --locked --package openlet-processor pytest scripts -q
uv run --locked --package openlet-processor ruff check scripts
uv run --locked --package openlet-processor ruff format --check scripts
node --test --test-concurrency=1 e2e/setup/environment.test.ts e2e/setup/recovery.test.ts
pnpm --dir e2e exec playwright test --project=api
pnpm check:e2e
docker compose -f infra/compose/dev.yaml config --quiet
git diff --check
```

All 17 script tests passed, including real Compose startup, migration failure and cancellation checks plus eight recovery unit cases. Ruff passes over all scripts; its full-tree format check found the new contract generator needed formatting, which was corrected without changing logic. All three Node setup/recovery tests pass. The full API suite passed all 32 cases in six minutes, including exact inline/object bytes, copies, quota, archive cancellation, processing/worker recovery, onboarding, collaboration, telemetry and whole-stack backup/restore with an interrupted workflow. Shared/app tests and integration-tagged vet pass, including independent app module resolution; their unchanged-source evidence is retained from the preceding foundation checks.

Earlier real PostgreSQL-backed schema/initializer tests covered missing/read-only/repeated/mismatched schema, file-backed credentials and incorrect-key rejection. No broad runtime/E2E/recovery acceptance is inferred from those narrower results.

## Recovery and cancellation follow-up

The development Compose fixture injects cancellation while SpiceDB is running but health remains unready, performs owned cleanup, and asserts no fixture container, volume or network survives before fixture teardown. The actual E2E harness separately receives SIGTERM while its SpiceDB health is still starting; it exits 143, cleans its owned resources and releases its OS lock. No owned containers remain.

Recovery inventories all six databases, native configuration and credentials in checksummed version-2 snapshots. It stops graph/schema and application writers, restores only into a fresh isolated target, and runs the pinned vendor operation `datastore repair transaction-ids` before recording completed repair. This is the supported PostgreSQL counter repair, verified against [v1.57.0 source](https://github.com/authzed/spicedb/blob/v1.57.0/internal/datastore/postgres/postgres.go); it does not make graph facts canonical. Missing repair evidence rejects resume. Graph health and read-only schema verification precede storage, boundary, Temporal and application startup. The real recovery test proved all six dumps restore, missing repair evidence fences every writer, valid resume preserves exact object bytes, and corrupt dumps reject.

The conditional simplify review found storage/boundary started before graph schema verification. Stronger assertions reproduced two failures, then all eight recovery units passed after moving every runtime writer behind schema verification and reading the restore marker once. The cancellation concern was rejected from source evidence: the test explicitly removes resources and checks absence before its fixture finalizer, and actual harness cancellation is independently verified. The three Node setup/recovery tests passed again after the ordering fix. Canonical owner rebuild/epoch adoption belongs to Phases 3/7 and remains required.

## Subsequent phase boundaries

The privacy-hook blocker is resolved. Inspection of the installed hook identified its documented `APPROVED:` mechanism. Using the user's existing explicit approval, the E2E source patch applied successfully without disabling the hook or reading any secret file.

Phase 3 must activate Account/Workspace action admission, canonical role catalogs, owner intents/projectors/rebuild and Account gRPC lookups. Phases 4–7 still own full Go filesystem behavior, ingest adoption, direct routes, rename and Rust/proxy removal. Stored job-scope authority must be proved with actual ingest operations. Graph authorization remains unactivated; existing Account/Workspace/Rust behavior passes the current API suite. Existing dev databases were not reset or modified. The native implementation goal is active.
