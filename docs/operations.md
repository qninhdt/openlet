# Operating Openlet

All application metadata and inline traffic enters Envoy at `127.0.0.1:8080`. Keep service ports, PostgreSQL and Temporal private. Generated configuration and credentials are under ignored `.local/`, with a private parent directory. Do not copy snapshots or test histories into Git.

## Health and limits

`/live` tests the HTTP process. Account `/ready` checks PostgreSQL and Temporal; Workspace and LetFS also verify the expected SpiceDB schema/role policy. Leta readiness checks domain/saver migration versions, PostgreSQL, Temporal, Redis and private service connectivity; startup also validates persisted model selections. Native Compose health checks do not prove Clerk or the selected S3 provider is reachable. Inspect `docker compose -f infra/compose/dev.yaml ps` and service logs for startup failures.

Account, Workspace and LetFS use at most 16 database connections each. Temporal persistence and visibility pools each allow 10 connections per server component, with 2 idle. Conservatively allowing both stores for all four Temporal components gives 80; the three Go applications add 48. SpiceDB read/write pools add at most 16, including its pooled GC work. Leta API and worker each add an eight-connection application pool; the worker also holds at most eight run-scoped saver/advisory-lock connections. The resulting runtime budget is 168 against PostgreSQL's 200 connections. Allowing another 13 for the four application migration jobs, datastore migration and repair leaves 19 for health/operator sessions and server reserve. Normal startup orders these jobs, and restore repair runs while runtime writers are stopped. This assumes one API and one worker process per service; revisit it before adding replicas or concurrent operator jobs. The recovery API test records startup connections; that observation is not a saturation benchmark.

Envoy uses local rate limiting, bounded headers and a 120-second route/stream deadline. Go HTTP servers bound reads/writes to 125 seconds; internal S3 control I/O is bounded to 120 seconds. Object upload/download bytes transfer directly between caller and S3, outside those HTTP deadlines. Go workers have fixed task slots, bounded pages and finite copy limits. Compose grants 155 seconds to Go shutdown (HTTP drain then worker drain) and 135 seconds to letfs (concurrent HTTP/worker drain). A hard kill relies on durable activity state and Temporal retry.

The authoritative quota is logical bytes in letfs. Trash remains charged, committed copies charge full bytes, and deleting a charged node releases its bytes in the same transaction. Physical cleanup can lag. GET filesystem metadata exposes usage under filesystem:read; scope operations enforce their own actions. Cleanup logs contain outcome categories, without object keys or file contents. PostgreSQL lock-wait logging is enabled; test-only `pg_stat_statements` proves bounded query counts.

Leta control/runtime slots are 16/8; the control worker caches at most 100 Workflows. Worker shutdown requests a checkpoint yield and drains for 15 seconds; Compose grants 45 seconds. SSE has its own unlimited route timeout with heartbeat/disconnect handling; ordinary API deadlines remain bounded.

`leta-models.json` is part of the coordinated configuration snapshot and is restored into the new state directory. Resume validates saved model choices before reopening the API/worker. Redis is stopped with writers and restarts empty (no persistence or volume); its stream cursors require resync from PostgreSQL after restore. Rebuild preserves archived home/history visibility in active workspaces and removes resource bindings in deleting/deleted workspaces without restoring revoked direct grants.

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

`workspace-maintenance` only expires completed Workspace receipts. Account has no maintenance schedule; neither owner periodically scans SpiceDB membership. Terminal authorization/provisioning executions require explicit inspection in Temporal; a terminated run cannot execute its SQL failure handler. Retry admitted Workspace deletion through DELETE to resume a closed child.

Do not reactivate deleting resources or repair counters manually. Workspace deletion retries use its resource identity; purge retries use its trash-entry identity. Durable deleting/purging resources and remaining nodes preserve progress, without operation/checkpoint tables. Current owner authorization still applies. Unknown workflow status does not authorize destructive cleanup. Lost responses do not undo committed effects; failed copies retain ordinary partial content.

Native small-text writes are bounded unary calls. After a lost acknowledgement, an existing-target retry carries the same observed identity/revision and conflicts if the mutation committed; inspect current authorized stat/content before choosing a new action. Creation keys replay their saved result while retained. Never retry append without its observation or delete a replacement path occupant to emulate overwrite. Empty-directory removal uses `TrashNode.empty_directory`, remains restorable, and releases no quota. There is no text-mutation stream, ledger, extra worker or larger payload setting.

Workflow replay remains app-owned. [Testing](testing.md) documents fresh histories
captured by the rewritten API suite and their native replay commands.

## Coordinated backup and isolated restore

Permanent local recovery is implemented in `scripts/operations/recovery.py`.
SpiceDB is included in the coordinated inventory. Application PostgreSQL owns business facts; repository files own role/action policy. Account and Workspace rebuild derived relationships without a SQL graph mirror.

Its `backup`, `restore`, and `resume` commands require explicit `--compose`,
`--project`, and `--state`; backup also requires `--output`, restore `--snapshot`.
It checks resource ownership, fences writers, rejects unfinished storage
capabilities, dumps Account, Workspace, LetFS, Leta (domain and LangGraph checkpoints), Temporal persistence/visibility and SpiceDB databases, archives stopped managed MinIO and
Qdrant volumes, and records checksums. Restore refuses existing target resources
or state and leaves application/workflow writers stopped until explicit resume. Version 3 snapshots include native graph configuration, graph credentials and managed MinIO data in the private snapshot. Older snapshots are rejected before restore: SeaweedFS volume archives cannot be loaded into MinIO.
Restore runs the pinned SpiceDB command `datastore repair transaction-ids` against the isolated target after loading the seven dumps. This repairs PostgreSQL transaction-ID progress that logical dumps do not restore; it does not import graph facts into canonical tables. Resume rejects a restored deployment without completed repair, stops existing writers, starts PostgreSQL/SpiceDB, verifies schema/policy and runs each owner's `--rebuild-authorization` command before starting remaining dependencies and application/workflow writers. These owner commands need their database and SpiceDB only; they start no listeners or Temporal workers. Repair, schema or rebuild failure keeps admission fenced.
Resume builds application services from the current checkout, preventing a restored
Compose project from reusing obsolete project-named images. Use the checkout and
dependencies matching the snapshot's baseline schema. The API recovery journey
erases the isolated authorization projection, interrupts and repeats its canonical rebuild, then verifies revoked/deleted access, exact inline/object bytes, current search and resumption of an interrupted processing workflow;
the [acceptance record](../plans/261102-1059-go-grpc-filesystem-authorization/reports/acceptance.md) records current graph recovery evidence.

`rebuild-authorization` takes the same `--compose`, `--project` and `--state` arguments. It stops public and owner writers, initializes/verifies repository graph policy and rebuilds Workspace relationships and Leta resource/home relationships from their owning databases. It leaves admission stopped until explicit `resume`; interrupted runs can be repeated from the beginning. Leta consumes Workspace-owned lifecycle inventory on stdin and never restores direct scope grants from HITL history. Each owner scans keyset pages, includes retained lifecycle tombstones and bounds each resource call. Rebuild does not change canonical membership or role records.

Automatic object recovery currently supports managed local MinIO only.
An external S3 deployment is rejected before writers stop; its verified object
snapshot procedure is still a release requirement. Do not reset existing
development databases without a verified backup. E2E creates fresh owned volumes
and never resets developer volumes.

## Agent filesystem integration check

Run the pinned Mirage/Monty adapter against owned PostgreSQL, SpiceDB and Redis fixtures with `OPENLET_MIRAGE_INTEGRATION=1 go -C apps/letfs test -race -tags integration ./internal/transport/grpc -run '^TestIntegrationMirageLetFS$' -count=1 -v`. The Go fixture starts a private authenticated native service and supplies its isolated connection details to Python tests; direct execution of those Python tests without the fixture skips them. Fixtures clean up their own dependencies.

Redis is required for agent workspaces. Cache outage returns an explicit error; it does not serve stale bytes or switch to a local cache. Cache hits still perform current native permission/fingerprint checks. Invocation shutdown closes Mirage sessions and running commands while leaving borrowed application RPC clients open. Current tool limits are 300 seconds maximum command timeout, 4 MiB collected command output, and a 16 MiB Monty memory ceiling. These do not increase LetFS's configured inline-text limit. Guest networking is disabled; Mirage's internal Redis connection is separately allowed.

## Native text search experiment

LetFS migration `0003_inline_text_search.sql` adds PostgreSQL's pg_trgm extension and a partial GIN index over small TEXT. Use the normal transactional migrator; original S3/blob bytes are not loaded into this index. Native literal search is independent of semantic indexing. PostgreSQL may correctly choose scans for short/common literals, small relations, or heavily toasted data; no planner hints are required.

Run the opt-in current-schema experiment on disposable PostgreSQL fixtures:

```sh
OPENLET_TEXT_SEARCH_BENCHMARK_OUTPUT=/tmp/openlet-text-search-plans.json \
  go -C apps/letfs test -tags integration ./internal/filesystem \
  -run '^TestTextSearchQueryPlans$' -count=1 -v
```

It seeds synthetic documents/logs, real nested artifacts, an unrelated scope and a narrow box. It compares the exact production query before/after GIN with server planner defaults, one warmup and five samples, raw EXPLAIN ANALYZE/BUFFERS plans, ordered-result equality, heap/TOAST/index sizes and a concurrent reader with a rolling-back 16-row writer. It never targets a persistent database. The output path is a local generated evidence file; the ordinary integration suite skips this expensive experiment unless the variable is set.

The recorded PostgreSQL18.6 experiment showed selective document-query medians of 98.718→6.106 ms (4096×8 KiB), 94.717→3.016 ms (512×64 KiB), and 363.772→25.671 ms (16384×8 KiB), with actual default GIN plans and nonoverlapping warm sample ranges. The high-entropy log query kept a sequential scan. Its GIN occupied 53,338,112 bytes for 34,603,008 logical text bytes; document indexes were much smaller. The controlled writer was roughly 2–5× slower with GIN. These synthetic warm-cache measurements establish the selective-query gate, not a universal latency or storage-overhead promise. Raw evidence and workload limitations are linked from the current implementation plan's phase07 execution report.

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
and drill an independent object backup together with the seven-database backup
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

Application baselines now describe account/scope storage directly. There is no compatibility migration from the former model. LetFS’s fresh baseline owns `allow_blob_files` and `allow_indexing` on scopes; the obsolete filesystem-option migration is removed. Use fresh isolated databases for acceptance; do not apply a rewritten baseline over an existing development environment. Persistent reset/migration requires explicit authorization.
