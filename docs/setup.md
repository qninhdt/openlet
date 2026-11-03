# Setup and verification

The backend services implement onboarding, collaboration, generic file operations, S3 uploads, durable copy/deletion and finite maintenance. [Operations](operations.md) records shutdown, backup/restore and release checks; the plan retains verification state.

## Requirements

- Docker with Compose, Make and Python 3.10+ for the existing development setup. API E2E requires Node.js 24, pnpm 12.9.1 and the Linux `flock` utility; install its locked dependencies with `pnpm install --frozen-lockfile`.
- Go 1.27.3 for native verification and protobuf Go tools, plus `protoc` for contract generation. Go modules and tool versions are pinned in the workspace. Put the toolchain bin directory on `PATH` so both `go` and `gofmt` are available (for this environment: `export PATH=/usr/local/go/bin:$PATH`).
- Native ingest checks need `uv` and Python 3.12 or 3.13; the worker image supplies its own locked Python environment.

## Configure and start

Export Clerk/JWT, S3 and OpenRouter settings using the non-secret examples in `.env.example` (Compose also reads that file when configured), then run:

```sh
make up
```

External issuer/JWKS URLs require HTTPS. The generator renders native Envoy, Temporal and SpiceDB configuration and generates random credentials under ignored `.local/`. Its parent directory is private; individual mounted secret files are readable by the non-root containers. It preserves existing credentials across repeated setup. Never commit or publish that directory or rendered configuration. Changing credential files alone does not rotate an existing database role.

`OPENROUTER_REASONING_EFFORT` optionally controls generation/vision reasoning: `none`, `minimal`, `low`, `medium`, `high`, or `xhigh`. Leave it empty to use the selected model's default; the selected model must support the requested effort. Set `none` for GPT-6 Luna generation without reasoning tokens.

Only Envoy binds a host port, `127.0.0.1:8080`. Application, database, Temporal and admin-tool ports stay private. External access requires the deployment's trusted HTTPS termination. Temporal's no-authorizer setting is confined to the private backend network; do not publish its port.

Account calls Workspace gRPC at `WORKSPACE_RPC_ADDRESS` with `ACCOUNT_SERVICE_TOKEN`. Workspace calls Account gRPC at `ACCOUNT_RPC_ADDRESS` and letfs storage administration at `LETFS_RPC_ADDRESS` with its distinct `WORKSPACE_SERVICE_TOKEN`; ingest uses `LETFS_RPC_ADDRESS` and `INGEST_SERVICE_TOKEN`. Each secret also accepts `_FILE`. Owner-local Temporal Activities make these calls. Native listeners use `RPC_LISTEN_ADDR` (default `:9090`). RPC requires TLS by default using `RPC_TLS_CERT_PATH` and `RPC_TLS_KEY_PATH`; Compose explicitly enables `ALLOW_PLAINTEXT_RPC=true` on its private backend network. Internal listeners are not published. Envoy exposes public HTTP only. All native gRPC, including filesystem operations, storage administration and ingest, stays on the backend network.

All Go services start their owner Temporal workers and check required dependencies during readiness. LetFS configuration is owned by [config.go](../apps/letfs/internal/config/config.go). Clients discover filesystem/root/bucket references through Workspace, then call LetFS directly; no Workspace filesystem proxy remains.

`make up` builds the app-owned Dockerfiles and initializes a fresh deployment using native Goose application-migration jobs and upstream Temporal schema/namespace tools. Each application owns one baseline migration. There is no upgrade chain for the old schema: retain a verified backup before an intentional reset, and never apply the new baseline over existing development data. Startup does not automatically back up existing databases.

The development Compose definition also starts pinned SpiceDB on the private backend network, with a dedicated `openlet_spicedb` database/user on the same PostgreSQL instance. Datastore migration must succeed before gRPC health becomes ready; the `authz-schema` job initializes a missing schema or verifies the existing expected schema. Unknown schema is rejected. The same deployment job loads built-in role capabilities from [roles.json](../packages/contracts/authz/roles.json) directly into SpiceDB; application PostgreSQL keeps membership role assignments and other business records, with no permission catalog. Run this initializer while application/graph writers are fenced. Its `--check` mode verifies both schema and role policy without repairing drift. No SpiceDB port is published, Watch is disabled and read/write pools are capped at eight connections each. Existing PostgreSQL volumes do not rerun init SQL or automatically acquire the new database. Account and Workspace require `SPICEDB_ADDRESS` and `SPICEDB_GRPC_PRESHARED_KEY` (or its `_FILE` secret). Their images include the expected schema and role policy under `/contracts`; startup and readiness verify both without repairing drift. Account profile access uses native self-resource checks. Final recovery acceptance is tracked in the [active migration plan](../plans/261102-1059-go-grpc-filesystem-authorization/plan.md).

Use `make down` to stop the stack while preserving its named volume. Do not remove volumes as routine rollback. To migrate an existing deployment, stop application/Temporal writers before applying a schema upgrade and retain the pre-change backups.

## Verification

The API suite under `e2e/` was written from scratch; the previous Go harness,
issuer, browser launcher and custom contract recorder are deleted.
See [testing](testing.md) for scenarios and the [foundation migration plan](../plans/261102-1059-go-grpc-filesystem-authorization/plan.md) for execution evidence.

```sh
pnpm install --frozen-lockfile
pnpm check:e2e
pnpm --dir e2e exec playwright test --project=api
pnpm --dir e2e exec playwright test --project=api --grep 'gateway baseline'
pnpm check
pnpm test
make test-integration
make test-workflow
```

Playwright setup builds current sources and starts a dedicated Compose project from
`infra/compose/e2e.yaml`. It owns real PostgreSQL, persistent Temporal, MinIO,
Qdrant and application containers. Newly written Clerk/model boundary doubles
provide deterministic external responses; they do not replace application behavior.

E2E binds gateway/control/storage ports 18200/18201/18202 on loopback, separate from
development port 8080. An occupied port or concurrent project owner fails setup;
the runner never kills another process or picks a different port. It refuses
preexisting project resources for inspection/backup instead of deleting them.
Generated configuration and redacted logs live under private `.local/api-e2e/`.
Owned containers and volumes are removed after tests or partial setup failure.

Use native Playwright file/grep selection. An unknown selection must fail;
a filtered baseline pass does not mean the full suite passes. The API project
depends on the coordinated-recovery project, which runs first from clean state.

Native integration uses app-owned Testcontainers and the same baseline SQL. The shared testinfra module and standalone test/migration scripts are deleted. Put the supported Go executable on PATH before using native commands or Turbo.

## OpenTelemetry

Account and Workspace use Gin `otelgin`; LetFS uses Go HTTP `otelhttp`. All Go services use native gRPC `otelgrpc`, pgx instrumentation and Temporal's Go interceptor. Python instruments HTTPX/HTTPX2 provider traffic, generated gRPC calls and Temporal Activities.

Every app writes JSON logs to stdout with `trace_id` and `span_id` when a span
is active. W3C `traceparent`/`tracestate` propagate through HTTP, gRPC and Temporal;
arbitrary baggage is excluded. Signed URL queries, request bodies, SQL parameters
and model prompts are excluded from application telemetry.

An empty `OTEL_EXPORTER_OTLP_ENDPOINT` starts no exporter. To export to your own
receiver, set that endpoint and `OTEL_EXPORTER_OTLP_PROTOCOL` to `grpc` (default)
or `http/protobuf`; use an HTTP base URL for the latter, including `/v1/traces`
only when setting a trace-specific endpoint natively. Compose forwards the common
endpoint/protocol/headers, sampler settings, resource attributes and SDK-disable
setting from `.env.example`. Signal-specific overrides work when supplied directly
to an app process. No Collector, Grafana or Prometheus service is required or added.

`OTEL_TRACES_SAMPLER` supports `always_on`, `always_off`, `traceidratio` and
their `parentbased_` forms. Ratios use `OTEL_TRACES_SAMPLER_ARG` between 0 and 1.
Use `OTEL_RESOURCE_ATTRIBUTES` for `deployment.environment.name` and other
deployment attributes. Apps supply their build/version attribute. Native `OTEL_SERVICE_NAME` overrides the app default;
do not give all services the same name. The processing worker also records its
worker role. Export queues are bounded, export calls time out after three seconds,
and providers are shut down after HTTP/worker drain. Unavailable receivers do not
turn a business operation into a failure.

## Clerk onboarding

Use a Clerk development instance. Set the Clerk session token custom claims to
`{"openlet_user_id":"{{user.public_metadata.openlet_user_id}}"}` and configure its
accepted audience to match `JWT_AUDIENCE`. The backend owns this public metadata
field; clients cannot set it. On first login, call `PUT /v1/me/onboarding` with the
session bearer JWT, then poll `GET /v1/me/onboarding`. No request key is needed:
Clerk identity admits one user. `workspace_id` is null until the Workspace child
workflow returns its resource ID. Once status is `active`, refresh the Clerk session token (Clerk SDK `getToken({skipCache:true})`)
and verify the refreshed claim before calling normal routes. Do not reuse the old
bootstrap JWT. The backend updates only its field via Clerk's metadata merge endpoint.

For a live development smoke, verify the initial bootstrap denial, successful
onboarding, stable user/workspace IDs on retry, preservation of unrelated metadata,
and access with a newly minted session. Live development evidence is recorded in
the [external configuration report](../plans/reports/implementation-261029-1822-external-configuration.md). Deterministic CI uses
an isolated controllable Clerk HTTP boundary, real Envoy verification and real workers.

Workspace policy settings are `MAX_OWNED_WORKSPACES`, `MAX_MEMBERS`,
`DEFAULT_QUOTA_BYTES` and `INVITE_TTL` (see service config defaults).
Invitations return a token once; share it manually and submit it in JSON to
`POST /v1/memberships`. Acceptance requires a matching verified Clerk email.
There is no email sender or frontend link route.

## Object storage

Set `S3_ENDPOINT` (HTTPS), `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID` and
`S3_SECRET_ACCESS_KEY` for an existing private bucket before starting the normal
stack. Credentials require object read/write/copy/delete and the list permissions
needed for operational checks; normal application code does not create buckets.
TLS certificate verification stays enabled. Configure incomplete multipart-upload
expiry in the provider and select its version-retention/restore policy before release.
Logical deletion is separate from physical version cleanup on versioned providers.

Only the isolated API E2E configuration starts MinIO internally. Its image is built
from the fixed upstream source release in [infra/minio/Dockerfile](../infra/minio/Dockerfile);
Go integration fixtures use the same image. The community edition is
unmaintained and source-only, so upstream maintenance remains an operational limitation. Its
presigned endpoint is reachable by the host at `http://127.0.0.1:18202`;
internal control requests use the boundary proxy on the private network.
Do not rewrite signed hostnames. Plaintext storage/provider exceptions are
confined to the isolated E2E configuration. The local storage volume is owned
by the test run; external S3 remains the normal development route.

Clients choose bounded inline node/content APIs or object upload sessions. Read `GET /v1/quota-buckets/{bucket}` for `{bucket,upload_limits}`. Defaults are 256 KiB inline, 100 MiB max file, 16 MiB multipart threshold and 8 MiB parts. Inline content accepts arbitrary bytes, including empty/binary data.

Prepare with `POST /v1/filesystems/{filesystem}/uploads`, a UUID `Idempotency-Key`, decimal `size_bytes`, `media_type`, and destination parent/name (or `node_id` plus `If-Match` for overwrite). Public upload sessions always use object storage. Single PUT additionally requires base64 `content_md5`. Repeating the same request key/parameters returns the same session; changed parameters conflict. Object bytes go directly to the returned signed URL with required headers. Browsers set Content-Length automatically. Upload URLs default to fifteen minutes, bounded by session expiry.

For native multipart, prepare returns the part size/count. Sign batches of up to
64 part numbers via `/uploads/{id}/parts`, PUT directly to each URL,
and submit ordered `{part_number,etag}` receipts to `/uploads/{id}/completion`.
Only letfs completes/aborts native multipart. Completion freezes receipts, checks
provider evidence, then publishes atomically under quota/revision/lifecycle locks.
The old file stays visible until publication; overwrite always uses a fresh key.
Retry finalize or poll `/uploads/{id}` after a lost reply. After the first multipart
completion request, retries may omit receipts. A rejected publication retains
cleanup evidence. No quota reservation or Temporal upload workflow is used.

Downloads return bounded inline bytes or a no-store 307 to a signed private S3 GET.
Issue/renew through the authorized content route with `revision=N` to pin content;
preserve Range on the direct GET. Do not forward a logical `If-Match` as an S3 ETag.
GET URLs default to five minutes and remain bearer capabilities until expiry.

Configure exact-origin bucket CORS for PUT/GET/HEAD, required signed headers,
and exposed ETag/range headers before browser use. `S3_SIGNING_ENDPOINT` may
separate caller-reachable and internal control endpoints; never rewrite a signed
hostname. Set the exact deployed UI origin when a frontend exists. The old standalone
browser/CORS fixture and launcher have been removed; API checks do not prove
browser CORS behavior. Do not age-expire ordinary `objects/`. Configure native
incomplete-multipart cleanup; abandoned remote creates can exist after a lost reply.

## Document processing

Compose builds one Python image with pinned Docling dependencies and offline
models. The CPU process runs one conversion at a time with CPU, memory and
scratch limits from `infra/compose/dev.yaml`; no runtime model download is required.
The locked `docling[rapidocr]` dependency supplies the ONNX OCR runtime; the CPU worker
checks that it imports before connecting to Temporal and accepting activities.
`INGEST_IMAGE` selects a prebuilt image; use a registry digest and Compose
`up --no-build` when deploying that image. Compose starts `ingest-cpu` and `ingest-io` from the same image using the `cpu` and `io` worker arguments. CPU parsing polls `openlet-letfs-cpu`; enrichment/indexing polls `openlet-letfs-io`. The I/O process starts without model/OCR preflight. Both use the dedicated Letfs token and trace propagation; only I/O work uses OpenRouter/Qdrant credentials.

For native parser verification, download models explicitly before the offline run:

```sh
uv sync --locked --package letfs-ingest
uv run --locked --package letfs-ingest python -m letfs_ingest.prefetch_models "$PWD/.local/ingest-models"
DOCLING_MODELS_PATH="$PWD/.local/ingest-models" uv run --locked --package letfs-ingest pytest apps/letfs-ingest/tests
```

Run the API suite before native workflow replay; [testing](testing.md) documents
fresh history capture and native replay commands.

`pnpm check` and `pnpm test` include ingest lint, formatting and tests without model-dependent
parser cases. `PROCESSING_MAX_OUTPUTS` and `PROCESSING_MAX_OUTPUT_BYTES` bound one
job's published tree. Input/resource bounds are defined in the processor; output
transport reuses the same configured inline/multipart limits as user uploads.

The parser chooses one document-wide layout before exporting: a single root
`README.md` for short or unstructured documents, Markdown sections for longer
documents, or section folders when two substantial outline levels justify them.
Every folder has a README. Structural names start as `1-untitled`; images and
tables use independent `untitled-1.png` / `untitled-1.csv` counters in their semantic
container. Counters pad only when their own count reaches ten. Excel always uses
one folder per sheet; sheet README files retain outside-table cells and coordinates.
PPTX currently uses one README with slide boundaries; advanced presentation layout,
Excel formula evaluation and merged-cell interpretation are deferred.

`MIN_LEAF_TOKENS` (default `256`) controls adjacent small-section merging;
`SPLIT_TOKENS` (default `4096`) controls layout selection. The worker requires
`0 < MIN_LEAF_TOKENS <= SPLIT_TOKENS`. Layout, sampling and chunking estimate
tokens as `ceil(character_count / 4)`, following the common English-text heuristic.
These budgets are approximate, particularly for multilingual text and code.
No tokenizer data or download is required.

PDF conversion uses one-page OCR/layout/table batches and a two-page stage queue
within the existing worker memory limit. Extracted images are written once and
referenced by relative paths. Docling's image-byte decoding limit is bounded by
the job's output-byte limit and the existing pixel budget; pixel, input, scratch,
deadline and output-count limits still apply. PowerPoint compatibility shapes
preserve supported text/math branches and embedded fallback pictures. A slide
containing hundreds of individual ink pictures can exceed the configured
`PROCESSING_MAX_OUTPUTS`; the job fails without publishing a partial tree.
Word table cells containing content controls use Docling's rich-cell parser so
the controls' visible text is retained.

### ZIP downloads

`ARCHIVE_*` values in [.env.example](../.env.example) bound entries, source/output bytes, per-process concurrency and runtime. Letfs streams ZIP64 directly over HTTP with a 64 KiB pipe and no temporary ZIP object. Runtime defaults to 1200 seconds and is capped at 1800; only the direct archive gateway route have extended write/route deadlines. Other request timeouts remain bounded as before. Preserve provider incomplete-multipart abort rules for uploads and never age-expire `objects/`.

```sh
go -C apps/letfs test -race -tags integration ./internal/filesystem ./internal/transport/grpc -run Archive -count=1
```

## AI enrichment and search

Set `OPENROUTER_API_KEY` before `make configure`; the generator preserves it in the private secret directory and generates the internal Qdrant key. Generation/vision, embedding and reranker model IDs plus resource budgets are in [.env.example](../.env.example). OpenRouter defaults to its HTTPS API; `ALLOW_LOCAL_AI=true` is reserved for explicit local testing. Qdrant v1.20.0 runs on the private backend network with a persistent `qdrant-data` volume and no host port. The API E2E environment uses controlled model endpoints and the real Qdrant service.

Keep embedding model, dimension and collection consistent. Select a new collection when changing the vector space, then use the admin backfill command. It processes one bounded page, prints counts and a resume cursor, and writes only with `--apply`:

```sh
docker compose -f infra/compose/dev.yaml exec -T letfs letfs --backfill-processing --mode missing --limit 100
docker compose -f infra/compose/dev.yaml exec -T letfs letfs --backfill-processing --mode missing --limit 100 --apply
docker compose -f infra/compose/dev.yaml exec -T letfs letfs --backfill-processing --mode rebuild-index --limit 100 --apply
```

Pass `--after UUID` to resume. Rebuild skips currently running workflows and retains committed enrichment; rerun from the beginning after those workflows close. It marks index readiness pending. Vector-space reconciliation records old generation/space cleanup intent before adopting the new model/collection/dimension, and dispatches index-only work. Search immediately rejects old-space results; bounded maintenance deletes obsolete points without touching current ones. Qdrant may be recreated and rebuilt from authoritative source/artifact content. Filename search remains available during AI/index outages.

```sh
go -C apps/letfs test -race -tags integration ./internal/filesystem ./internal/transport/grpc -run Search -count=1
```
