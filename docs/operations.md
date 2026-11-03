# Operating Openlet

All application metadata and inline traffic enters Envoy at `127.0.0.1:8080`. Keep service ports, PostgreSQL and Temporal private. Generated configuration and credentials are under ignored `.local/`, with a private parent directory. Do not copy snapshots or test histories into Git.

## Health and limits

`/live` tests the HTTP process. Account/Workspace `/ready` checks PostgreSQL, Temporal and the expected SpiceDB schema/role policy; Account native gRPC health also verifies the graph contract. Native Compose health checks do not prove Clerk or the selected S3 provider is reachable. Inspect `docker compose -f infra/compose/dev.yaml ps` and service logs for startup failures.

Account and Workspace use at most 16 database connections each; letfs uses 16. Temporal persistence and visibility pools each allow 10 connections per server component, with 2 idle. Conservatively allowing both stores for all four Temporal components gives 80; the three applications add 48. SpiceDB read/write pools add at most 16, including its pooled GC work, for a runtime budget of 144 against PostgreSQL's 200 connections. Budget another 12 for three Goose jobs (one each), datastore migration (up to four), and repair (two read, two write, one direct connection). This conservative total of 156 leaves 44 for health/operator sessions and server reserve. Schema verification uses the existing graph pools. Normal startup orders these jobs; restore repair runs while runtime writers are stopped. This budget assumes one instance of each runtime; revisit it before adding replicas or concurrent operator jobs. A full-stack startup observed 22 client connections, including four for SpiceDB; the recovery API test records and bounds that observation. This is startup evidence, not a saturation benchmark.

Envoy uses local rate limiting, bounded headers and a 120-second route/stream deadline. Go HTTP servers bound reads/writes to 125 seconds; internal S3 control I/O is bounded to 120 seconds. Object upload/download bytes transfer directly between caller and S3, outside those HTTP deadlines. Go workers have fixed task slots, bounded pages and finite copy limits. Compose grants 155 seconds to Go shutdown (HTTP drain then worker drain) and 135 seconds to letfs (concurrent HTTP/worker drain). A hard kill relies on durable activity state and Temporal retry.

The authoritative quota is logical bytes in letfs. Trash remains charged, committed copies charge full bytes, and deleting a charged node releases its bytes in the same transaction. Physical cleanup can lag. The direct quota-bucket resource exposes usage and effective upload limits under its own action check. Cleanup logs contain outcome categories, without object keys or file contents. PostgreSQL lock-wait logging is enabled; test-only `pg_stat_statements` proves bounded query counts.

## Local Docker build cache

Application Dockerfiles cache Go modules/compiler output separately from source. Ingest installs locked dependencies independently
of its application wheel; model downloads depend on the prefetch script and pinned model
definitions. Source changes reuse the large dependency/model layers. The new API E2E environment builds these current sources independently of development state.

For one-off cleanup of unused build cache with current Docker Buildx:

```sh
docker buildx prune --builder default --max-used-space 20GB
```

This targets least-recently-used cache across projects using the default builder. It
does not delete service images, containers, volumes or snapshots. Image-shared/in-use
data may prevent reaching the target; evicted cache must be rebuilt when needed.

## Maintenance and recovery

`openlet-storage-maintenance` is a native Temporal Schedule running every five minutes with overlap Skip. Each run makes finite upload-expiry, resource/processing reconciliation, detached-forest and object/index cleanup passes. It never ages user trash. Ambiguous writes retain their key evidence and get periodic deletion attempts even after NotFound. Configure incomplete-multipart cleanup and version retention with the chosen provider; key deletion alone does not remove historical object versions.

Do not reactivate deleting resources or repair counters manually. Workspace deletion retries use its original identity/revision; purge retries use its trash-entry identity. Durable deleting/purging resources and remaining nodes preserve progress, without operation/checkpoint tables. Current owner authorization still applies. Unknown workflow status does not authorize destructive cleanup. Lost responses do not undo committed effects; failed copies retain ordinary partial content.

Workflow replay remains app-owned. [Testing](testing.md) documents fresh histories
captured by the rewritten API suite and their native replay commands.

## Coordinated backup and isolated restore

Permanent local recovery is implemented in `scripts/operations/recovery.py`.
SpiceDB is included in the coordinated inventory. Application PostgreSQL owns business facts; repository files own role/action policy. Account and Workspace rebuild derived relationships without a SQL graph mirror.

Its `backup`, `restore`, and `resume` commands require explicit `--compose`,
`--project`, and `--state`; backup also requires `--output`, restore `--snapshot`.
It checks resource ownership, fences writers, rejects unfinished storage
capabilities, dumps Account, Workspace, letfs, Temporal persistence/visibility and SpiceDB databases, archives stopped managed MinIO and
Qdrant volumes, and records checksums. Restore refuses existing target resources
or state and leaves application/workflow writers stopped until explicit resume. Version 3 snapshots include native graph configuration, graph credentials and managed MinIO data in the private snapshot. Older snapshots are rejected before restore: SeaweedFS volume archives cannot be loaded into MinIO.
Restore runs the pinned SpiceDB command `datastore repair transaction-ids` against the isolated target after loading the six dumps. This repairs PostgreSQL transaction-ID progress that logical dumps do not restore; it does not import graph facts into canonical tables. Resume rejects a restored deployment without completed repair, stops existing writers, starts PostgreSQL/SpiceDB, verifies schema/policy and runs each owner's `--rebuild-authorization` command before starting remaining dependencies and application/workflow writers. These owner commands need their database and SpiceDB only; they start no listeners or Temporal workers. Repair, schema or rebuild failure keeps admission fenced.
Resume builds application services from the current checkout, preventing a restored
Compose project from reusing obsolete project-named images. Use the checkout and
dependencies matching the snapshot's baseline schema. The API recovery journey
erases the isolated authorization projection, interrupts and repeats its canonical rebuild, then verifies revoked/deleted access, exact inline/object bytes, current search and resumption of an interrupted processing workflow;
the [acceptance record](../plans/261102-1059-go-grpc-filesystem-authorization/reports/acceptance.md) records current graph recovery evidence.

`rebuild-authorization` takes the same `--compose`, `--project` and `--state` arguments. It stops public and owner writers, initializes/verifies repository graph policy and rebuilds Account/Workspace relationships from their databases. It leaves admission stopped until explicit `resume`; interrupted runs can be repeated from the beginning. Each owner scans keyset pages, includes retained lifecycle tombstones and bounds each resource call. Rebuild does not change canonical membership or role records.

Automatic object recovery currently supports managed local MinIO only.
An external S3 deployment is rejected before writers stop; its verified object
snapshot procedure is still a release requirement. Do not reset existing
development databases without a verified backup. E2E creates fresh owned volumes
and never resets developer volumes.

## External release checks

Earlier Clerk development and Cloudflare R2 checks are [historical evidence](../plans/reports/implementation-261029-1822-external-configuration.md). The refactored source requires explicit live-provider verification before release. Provider-specific coordinated recovery remains unverified.

- Live Clerk smoke uses the opt-in Playwright external configuration documented in [testing](testing.md#environment-and-recovery-checks). It verifies backend metadata and a newly minted development-session JWT through Envoy; controlled fixture responses are not live-provider evidence.
- `make test-provider`: verify actual HTTPS/private S3 put/copy/get/range/delete using dedicated `smoke/<uuid>/` keys. Supply normal S3 configuration and scoped development-bucket credentials. The smoke also checks signed conditional PUT, exact size/MD5, native multipart and signed GET/Range. Provider version-retention, multipart cleanup and full disaster recovery still require the provider-specific procedure.

Missing provider configuration must be recorded as NOT RUN, never PASS. Controlled Clerk HTTP tests and MinIO integration tests do not replace these checks.

### Local external-service configuration

For development on this machine, source the ignored `.env` before `make up`; load
`.local/provider/clerk.env` as well when regenerating the Clerk secret. Generated
service credentials remain under `.local/secrets/`. These files are local secret
sources, not portable deployment configuration; never copy them into Git or reports.

The private `.local/provider/clerk-app.json` identifies the dedicated development
application. Select that application explicitly with Clerk CLI `--app` and
`--instance dev`; do not modify another application's configuration. Its saved
pre-change configuration is `.local/provider/clerk-before.json`.

The R2 endpoint and bucket are selected by `.local/provider/r2.env`. Use that
account and bucket explicitly when inspecting R2; verify them against the
Cloudflare CLI account selection before changes. The application token permits
object access only in its development bucket. Administrative changes require the
Cloudflare CLI identity. Managed and custom public domains must stay disabled.
The provider's default incomplete-multipart abort rule remains seven days. The
development bucket retains its historical eight-day `exports/` expiry rule; current ZIP streaming writes no objects under that prefix. Ordinary `objects/` has no age expiry. The previous/current rule evidence is private under
`.local/provider/r2-lifecycle-before-export.json` and
`.local/provider/r2-lifecycle-after-export.json`. Envoy's JWKS DNS uses IPv4 for
the IPv4 Compose network.

R2 credentials do not provide an object recovery point. Before release, establish
and drill an independent object backup together with the six-database backup
while application and maintenance writers are stopped. A MinIO volume backup cannot capture R2. Do not claim historical-object recovery or promote an
external restore until the provider-specific procedure has been verified.

### Direct-transfer operations

`UPLOAD_URL_TTL_SECONDS` defaults to 900 and `UPLOAD_TRANSFER_GRACE_SECONDS`
to 3600. Retain unpublished candidate evidence until issued write URLs and this
transfer grace have elapsed; terminal ambiguous candidates continue cleanup attempts.
Abort/expiry of inline sessions has no object key. Native multipart aborts retry
through finite maintenance. Never apply ordinary object TTL deletion as a cleanup
shortcut. Maximum GET lifetime is bounded below the existing fifteen-minute old-key
cleanup delay; clients needing renewal must reauthorize the same logical revision.

The development R2 browser smoke permits only `http://127.0.0.1:8765` with its privately recorded CORS rule. It does not enable
public bucket reads. The previous absent CORS configuration and applied rule are
recorded privately under `.local/provider/r2-cors-before.json` and
`.local/provider/r2-browser-cors.json`. Configure a real application origin before
frontend integration. Provider endpoints remain in `.local/provider/r2.env`.

Application migration history has been squashed into one baseline per database.
There is no upgrade migration from the previous schema. Back up before an explicit
reset; restore only into an isolated target and resume writers deliberately.
