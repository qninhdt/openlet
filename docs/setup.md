# Setup and verification

The backend services implement onboarding, collaboration, generic file operations, S3 uploads, durable copy/deletion and finite maintenance. [Operations](operations.md) records shutdown, backup/restore and release checks; the plan retains verification state.

## Requirements

- Docker with Compose, Make and Python 3.10+ for container-based setup/tests. Install contract-check dependencies with `python3 -m pip install -r scripts/requirements-dev.txt`.
- Go 1.27.3 and Rust 1.96.1 for native verification. Rust is pinned by `rust-toolchain.toml`; dependencies are locked per service.
- Native Rust builds need a C/C++ toolchain, CMake, `protoc` and protobuf headers. Container builds install these dependencies.
- Native processor checks need `uv` and Python 3.12 or 3.13; the worker image supplies its own locked Python environment.

## Configure and start

Export Clerk/JWT and S3 settings using the non-secret examples in `.env.example` (Compose also reads that file when configured), then run:

```sh
make up
```

External issuer/JWKS URLs require HTTPS. The generator renders native Envoy and Temporal configuration and generates random credentials under ignored `.local/`. Its parent directory is private; individual mounted secret files are readable by the non-root containers. It preserves existing credentials across repeated setup. Never commit or publish that directory or rendered configuration. Changing credential files alone does not rotate an existing database role.

Only Envoy binds a host port, `127.0.0.1:8080`. Application, database, Temporal and admin-tool ports stay private. External access requires the deployment's trusted HTTPS termination. Temporal's no-authorizer setting is confined to the private backend network; do not publish its port.

Compose supplies only the dependency URLs each service calls: `WORKSPACE_URL`
for User, and `USER_URL`/`LETFS_URL` for Workspace. Native startup requires those
URLs; a service does not require its own URL or an unused downstream URL.

`make up` waits for PostgreSQL, backs up and applies application migrations, builds services, and starts Temporal with separate persistence/visibility credentials and the `openlet` namespace. Initial Temporal schema setup also makes verified database dumps before changes. These pre-migration dumps are not a coordinated application/object recovery point; use the coordinated procedure in [operations](operations.md) for that purpose.

Use `make down` to stop the stack while preserving its named volume. Do not remove volumes as routine rollback. To migrate an existing deployment, stop application/Temporal writers before applying a schema upgrade and retain the pre-change backups.

## Verification

```sh
make verify
make test-integration
make test-e2e TEST=all
make test-workflow
make test-recovery TEST=worker-restarts
make backup-restore-drill
```

Service integration uses Testcontainers-Go and Testcontainers-Rust with fresh PostgreSQL databases, dynamic ports and automatic container cleanup. Select `SERVICE=user`, `workspace` or `letfs`; the default runs all three sequentially. Docker must be available. The letfs fixture also starts private test S3 and a Temporal dev server; it does not use external credentials. Migrations run through the production backup/migration script before exercising service behavior. The Compose test generator also fixes JWT identity to its internal issuer, ignoring exported development issuer/JWKS/audience values.

The complete E2E suite (`make test-e2e TEST=all`) covers real Envoy/JWKS, controlled Clerk HTTP, all services, PostgreSQL, native Temporal workers and SeaweedFS S3. It includes authorization, invitation replay, ID/path equivalence, quota/restore races, upload/copy/lifecycle tests, query counts and worker/server restart. `TEST=foundation`, `identity-files`, `storage-copy`, `copy-races`, `lifecycle`, `processing`, `processing-recovery` or `zip-export` selects a narrower group. Histories and response shapes are captured under ignored `.local/test/histories/` for replay and contract checks. The suite stops its containers on exit and retains volumes/backups. Tests use barriers for concurrency, with polling deadlines only for observable readiness/completion.

Service integration does not reserve port 8080. Port 8080 must be free before running the Compose E2E suite; stop the development stack with `make down` if needed. Do not change ports to hide an existing owner. Native `make verify` runs formatting, Go tests/vet, Rust tests/clippy and configuration checks. `SERVICE=user|workspace|letfs` restricts `make test-unit`; unknown service selectors fail. Set `GO` to the supported Go executable if it is outside `PATH`; formatting and workflow targets respect that selection too.

The test issuer proves gateway behavior only. Envoy returns its native authentication errors (401, or 403 for a disallowed audience); application errors use the documented JSON envelope. Live Clerk configuration and the actual selected S3 provider are separate release checks described in [operations](operations.md). No test endpoint or issuer is included in the normal Compose stack.

## Clerk onboarding

Use a Clerk development instance. Set the Clerk session token custom claims to
`{"openlet_user_id":"{{user.public_metadata.openlet_user_id}}"}` and configure its
accepted audience to match `JWT_AUDIENCE`. The backend owns this public metadata
field; clients cannot set it. On first login, call `POST /v1/onboarding` with the
session bearer JWT and a UUID `Idempotency-Key`, then poll `GET /v1/onboarding`.
Once succeeded, refresh the Clerk session token (Clerk SDK `getToken({skipCache:true})`)
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
`POST /v1/invitations/accept`. Acceptance requires a matching verified Clerk email.
There is no email sender or frontend link route.

## Object storage

Set `S3_ENDPOINT` (HTTPS), `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID` and
`S3_SECRET_ACCESS_KEY` for an existing private bucket before starting the normal
stack. Credentials require object read/write/copy/delete and the list permissions
needed for operational checks; normal application code does not create buckets.
TLS certificate verification stays enabled. Configure incomplete multipart-upload
expiry in the provider and select its version-retention/restore policy before release.
Logical deletion is separate from physical version cleanup on versioned providers.

Only the isolated Compose test override starts SeaweedFS S3 internally, with pinned
image, persistent test volume and generated test credentials. Its volume server
keeps a 512 MiB free-disk floor instead of a percentage of the host disk; below
that floor it refuses writes. The Compose test profile publishes only its test S3
proxy at `127.0.0.1:8333` in addition to Envoy. For manual host-browser use, set
`OPENLET_TEST_S3_SIGNING_ENDPOINT=http://127.0.0.1:8333` before starting that profile.
Automated Docker testers use the default `http://issuer:8333` signing hostname;
these are separate caller environments, so select the endpoint before issuing URLs.
Native Testcontainers publishes an isolated dynamic S3 port to its host browser.
Isolated restores reset both published ports. `ALLOW_LOCAL_S3=true` is confined to that override. External S3 is the
normal route; local storage is not a runtime requirement.

Clients choose `inline` or `object`; the backend does not classify bytes. Read
`GET /v1/workspaces/{ws}/usage` for effective `upload_limits`. Defaults are
256 KiB inline, 100 MiB max file, 16 MiB multipart threshold and 8 MiB parts.
Inline accepts arbitrary bytes, including empty/binary data; text editing remains
a separate validated string API.

Prepare with `POST /files/uploads`, a UUID `Idempotency-Key`, `storage`, decimal
`size_bytes`, and destination parent/name (or locator plus `If-Match` for overwrite).
Object single PUT additionally requires base64 `content_md5`. Repeating the same
request key/parameters returns the same session; changed parameters conflict.
Inline uses the bounded `/uploads/{id}/bytes` receiver. Object bytes go directly
to the returned signed URL with its required headers. Browsers set Content-Length
automatically; do not try to set it from JavaScript. The old object-body relay is
removed. Upload URLs default to fifteen minutes, bounded by session expiry.

For native multipart, prepare returns the part size/count. Sign batches of up to
64 part numbers/checksums via `/uploads/{id}/parts`, PUT directly to each URL,
and submit ordered `{part_number,etag}` receipts to `/uploads/{id}/finalize`.
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
hostname. [The browser smoke CORS fixture](../tests/storage/cors.json) permits only
`http://127.0.0.1:8765`; replace it with the real UI origin for a deployment.
Do not age-expire ordinary `objects/`. Configure native incomplete-multipart
cleanup; abandoned remote creates can exist after a lost creation reply.

For browser checks install `scripts/requirements-dev.txt` into your test Python
environment and run `python -m playwright install chromium`. AWS CLI is required
for the isolated test fixture's S3 CORS setup. `STORAGE_BROWSER_PYTHON` selects that
Python executable. Run `make test-integration SERVICE=letfs TEST=direct-storage`;
it includes real Chromium PUT/replay/Range/CORS checks. To include the same browser
check in a native external-provider smoke, set `STORAGE_BROWSER_CHECK=true` when
running `cargo run --manifest-path services/letfs/Cargo.toml -- --provider-smoke`
with the normal private provider environment and configured smoke origin.

`make test-e2e TEST=uploads` exercises real PostgreSQL and SeaweedFS S3
through Envoy and both service facades, including multipart data and stale overwrite.

## Document processing

Compose builds an activity-only Python worker with pinned Docling dependencies and
offline models. Each container runs one conversion at a time with CPU, memory and
scratch limits from `deploy/compose.yaml`; no runtime model download is required.
The locked `docling[rapidocr]` dependency supplies the ONNX OCR runtime; the worker
checks that it imports before connecting to Temporal and accepting activities.
`PROCESSOR_IMAGE` selects a prebuilt image; use a registry digest and Compose
`up --no-build` when deploying that image. The worker receives only its dedicated
letfs token, scoped source/output APIs and temporary storage URLs.

For native parser verification, download models explicitly before the offline run:

```sh
uv sync --project services/letfs/processor --locked
uv run --project services/letfs/processor --locked python services/letfs/processor/prefetch-models.py "$PWD/.local/processor-models"
DOCLING_MODELS_PATH="$PWD/.local/processor-models" uv run --project services/letfs/processor --locked pytest services/letfs/processor/tests
make test-e2e TEST=processing
make test-workflow TEST=process-file
```

`make verify` includes processor lint, formatting and tests without model-dependent
parser cases. `PROCESSING_MAX_OUTPUTS` and `PROCESSING_MAX_OUTPUT_BYTES` bound one
job's published tree. Input/resource bounds are defined in the processor; output
transport reuses the same configured inline/multipart limits as user uploads.

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

### ZIP exports

`EXPORT_*` values in [.env.example](../.env.example) configure root/entry/input/output
bounds, global concurrency, runtime and retention. The Rust worker streams ZIP64
to native multipart with a 64 KiB pipe and at most 8 MiB part buffers. Default
retention is 24 hours. Export storage is temporary and separate from logical quota.

Configure provider lifecycle only on `exports/`, with an age longer than maximum
configured retention plus execution time. This deployment caps retention at seven
days; its development R2 fallback expiry is eight days. Application maintenance
handles logical expiry and normal cleanup. Preserve native incomplete-multipart
abort rules, and never age-expire `objects/`.

```sh
make test-integration SERVICE=letfs TEST=zip-export
make test-e2e TEST=zip-export
make test-workflow TEST=export-archive
```
