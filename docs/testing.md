# Testing strategy

Status: native service integration uses Testcontainers; system E2E/recovery uses Compose; see [setup](setup.md) for commands and [operations](operations.md) for external checks. Use the lowest reliable layer that proves an application invariant; test doubles cannot replace verification of real storage/recovery behavior.

## Three levels

| Group | Environment | Responsibility |
|---|---|---|
| Unit | No infrastructure | Validation, path/name logic, role rules, checked arithmetic, transfer protocol shapes |
| Integration | One service and real relevant dependencies | SQL/transactions, HTTP contracts, storage and trust boundaries |
| System E2E | Public HTTP through real Envoy/Compose stack; native gRPC on private test listeners | A small set of complete backend journeys |

Workflow decision/replay checks belong to their native unit or integration scope; they are not a fourth level. Security, concurrency, contract, recovery and efficiency are scenario categories, not extra frameworks. No arbitrary coverage percentages, test-count targets or unmotivated load/soak suite.

## Required checks

CI runs native build, check, unit, workflow and integration targets in one Turbo
graph with concurrency 1, so shared build prerequisites run once. The contracts
`check` target verifies committed generated code; compiling it does not regenerate
it. Script lint and tests run once separately, followed by native history replay.

| Risk | Lowest reliable proof |
|---|---|
| Gateway | Real Envoy/test JWKS: bad issuer/signature/expiry, missing claim, bootstrap restrictions, spoofed/duplicate trusted headers, internal route isolation |
| Account | Real PG uniqueness, repeat onboarding, lost provisioning response, Clerk failure then success |
| Workspace | Real PG role/Owner transactions, owner removal refusal and concurrent membership changes, invite expiry/revoke/email mismatch, Owner-role rejection and replay after removal; member summaries exclude self-only fields |
| Tree | Real PG sibling uniqueness, same-scope parent, cycle prevention, path traversal, scope/cwd escape and ID ancestry |
| Data | Exact bytes/line endings, caller-selected arbitrary inline bytes, direct object transfer, stale overwrite preserves old data, path replacement with equal revision rejects old expected target/parent ID |
| Artifacts | Hybrid paths/cwd/root aliases, raw-ID readonly enforcement, copy traversal, source/ancestor lifecycle, detached forest cleanup and exact quota |
| Quota | Competing writes cannot overcommit; finalize/copy/purge retry cannot double-account; trash remains charged; repeated deletion batches never debit twice |
| Trash | Restore/purge race, hidden descendants by ID, missing parent/name conflict, Viewer denied, commit then response loss, delayed old trash after restore and delayed old restore after re-trash |
| Copy | Coherent item revision, source ID copied once, documented concurrent-source outcomes, retained partial output and atomic per-item quota/publication, self/descendant rejection, finite traversal under continuous additions and configured job ceilings |
| Objects | Real test S3 put/copy/range/delete, per-key errors, ambiguous/late writes, bounded outstanding/backlog admission and read/GC grace |
| Recovery | Crash after commit/between batches, all filesystem roots deleted, tombstones block recreation |
| Efficiency | SQL/RPC counts bounded independently of list page size; batch enrichment/stat; one path round trip without O(1) claim; node-count boundary and count reconciliation |
| Status | Caller/scope binding, same-key input mismatch, admission timeout, closed-before-first-activity retry, direct ambiguous-response reconciliation and durable retention/deletion retries |

Concurrency cases use barriers/controlled transactions rather than sleeps/random stress. Response-loss tests inject failure at the side-effect/acknowledgment boundary. Use real migrations and dependencies for claims about PostgreSQL locks, S3 or Temporal persistence.

## External integrations

The SQL benchmark runs actual service query shapes against deterministic fixtures in an owned disposable PostgreSQL container (Docker required):

```sh
python scripts/performance/sql-benchmark.py /path/to/source /tmp/openlet-sql-results.json
```

Run it sequentially against before/after source trees, with no concurrent tests. It loads each tree's initial migrations, records one warm-up plus three measured executions, plans/buffers and insert costs. Results are SQL execution time, excluding HTTP, authorization RPC, providers and network; the fixture uses dispersed deterministic UUIDs rather than production UUIDv7 ordering. See the [measurement report](../plans/reports/performance-261107-1204-api-sql.md) for dataset, changes and limits.

To measure each application SQL execution site, use the integration-fixture overlay:

```sh
python scripts/performance/sql-query-benchmark.py .local/sql-performance/per-query selfcheck
python scripts/performance/sql-query-benchmark.py .local/sql-performance/per-query all
python scripts/performance/sql-query-benchmark.py .local/sql-performance/per-query additional
python scripts/performance/sql-query-benchmark.py .local/sql-performance/per-query summary --report plans/reports/per-query-sql.md
```

The overlay leaves application and fixture sources unchanged. Probes use the actual SQL/arguments and roll back each execution; savepoint control statements receive separate client timings. Supplemental cases run verbatim inventoried SQL on seeded datasets and must be updated when their source sites/contracts change. A reused output directory rejects a changed inventory; use a fresh directory for a new source revision. The report keeps missing sites and failed probes visible. Plans can contain synthetic fixture constants. Small integration fixtures establish individual query costs, not load performance; retain the larger workload benchmark above. See the [233-site measurement](../plans/reports/performance-261107-1342-per-query-sql.md).

Clerk error handling uses controlled HTTP responses. A separate development-instance smoke verifies actual backend metadata and refreshed JWT. A test issuer is not evidence live Clerk passed. Never use production accounts/credentials/data.

S3 tests use a dedicated compatible server and bucket. Before release verify the selected provider's actual put/copy/range/delete/version behavior, valid TLS, rejected anonymous reads and object-only credential permissions; local-emulator success is not universal compatibility. Real restart tests use PostgreSQL-backed Temporal.

Check public HTTP OpenAPI and generated protobuf contracts against handlers and explicit Go/Python DTOs: UUIDs, decimal counters/revisions, optional/null values, timestamps, errors and ETags. No schema registry or custom test framework.

## Workflow and system coverage

SDK tests cover branches, retry classifications, timers and replay. Real Temporal tests cover worker/server restart, commit followed by response loss and bounded scope/filesystem deletion. Direct-operation tests cover retained partial-copy output, caller-retried purge and copy/purge while Temporal is unavailable. SDK activity mocks do not prove storage recovery. File bytes stay out of history. API journeys capture fresh `WorkspaceChanges` (running Update history) and `WorkspaceMaintenance` histories alongside onboarding and storage workflows for native replay.

The new Playwright API suite under `e2e/` was authored from scratch before
business refactoring. It covers gateway boundaries and target onboarding,
collaboration, byte/revision/quota contracts, uploads, partial copy, trash, ZIP,
processing/search and worker recovery. Coordinated recovery calls the permanent
operations CLI. The recovery project runs before the API project so adversarial
upload cases cannot leave open capabilities that invalidate its backup precondition.
Current refactor checks and external-provider limits live in the [active implementation record](../plans/261106-1517-account-scope-temporal-redesign/plan.md); the [foundation migration acceptance record](../plans/261102-1059-go-grpc-filesystem-authorization/reports/acceptance.md) preserves earlier delivery evidence. No old Go E2E source/history is retained as coverage.

```sh
pnpm check:e2e
pnpm --dir e2e exec playwright test --project=api --list
pnpm --dir e2e exec playwright test --project=api
pnpm --dir e2e exec playwright test --project=api --grep 'gateway baseline'
```

Playwright owns setup/teardown and public assertions. `infra/compose/e2e.yaml`
owns the real stack. Fault injection pauses or drops acknowledgments at the actual
external storage/provider boundary. Each test owns distinct identities/data.
The runner collects redacted service logs before deleting only its own resources.
No browser suite or browser CORS claim exists until frontend integration.

## Environment and recovery checks

The focused development graph check uses the actual bootstrap generator and Compose
PostgreSQL/SpiceDB services with disposable resources and no published service ports:

```sh
uv run --locked --package letfs-ingest pytest scripts/bootstrap -q
```

It checks dedicated database ownership, native datastore migration and gRPC health,
schema initialization/check/repeated initialization, rejection of an incorrect schema
credential, a failed migration keeping the graph server stopped, and cleanup after canceling graph readiness. It removes its
own containers/volumes in `finally`; diagnostics
redact generated fixture credentials. CI runs this check separately from API E2E.
API E2E starts the real graph, includes it in coordinated recovery and rebuilds relationships through canonical owners before reopening API admission. The recovery test waits for Account and filesystem routes before handing the source stack to the next project. It erases only SQL-derived tuples in the isolated graph, preserves direct scope grants, interrupts rebuilding between canonical owners, and repeats the rebuild before checking retained owner access, revoked membership, deleted resources, exact inline/object bytes and current semantic search.

`node --test --test-concurrency=1 e2e/setup/environment.test.ts e2e/setup/recovery.test.ts`
checks owner-safe lifecycle and the permanent operations CLI with real infrastructure.
It restores a database value and exact S3 bytes into a fresh fenced project,
resumes its services, and rejects a corrupted snapshot. This tool-level proof is
separate from the target API recovery journey that must also resume interrupted
business workflows.

Opt-in live Clerk verification uses a dedicated development session and explicit
`OPENLET_SANDBOX_GATEWAY`, `CLERK_SECRET_KEY` (`sk_test_`), and `CLERK_SESSION_ID`:

```sh
pnpm --dir e2e exec playwright test --config external/playwright.config.ts --project=api
```

It calls Clerk's real session-token endpoint after metadata publication; an
already issued JWT is insufficient. Missing sandbox configuration fails with
NOT RUN; the default local suite does not load provider credentials. The native
`make test-provider` command remains the selected-storage-provider opt-in.

## Placement and execution

Shared Go infrastructure lives in `packages/go`. Its default tests exercise real local
gRPC connections, TLS verification, authentication, message bounds, deadlines,
cancellation and trace propagation without Docker. Integration-tagged tests exercise
PostgreSQL-backed SpiceDB schema readiness/projection and Envoy. Run
`go -C packages/go test ./...` and `go -C packages/go test -tags integration ./... -count=1`.
Generated Go/Python drift is checked with `pnpm contracts:check`; the Python wheel
consumer tests run through `pnpm --filter @openlet/python test:integration`.

Go uses standard `testing`/`httptest` near packages, with app-owned Testcontainers fixtures behind the `integration` tag. Each fixture owns disposable dependencies and applies the app's baseline SQL. Turbo invokes native commands from minimal package manifests; integration tasks run sequentially across apps to bound resources. LetFS fixtures build the pinned MinIO source image from `infra/minio/Dockerfile`. Docker absence fails a requested run; tests never load development/provider credentials.

```sh
pnpm --filter @openlet/letfs check
pnpm --filter @openlet/letfs build
pnpm --filter @openlet/letfs test
pnpm --filter @openlet/letfs test:workflow
pnpm --filter @openlet/letfs test:integration
```

The integration command enables the race detector and tests actual authenticated
gRPC composition, PostgreSQL, SpiceDB, MinIO, Qdrant and disposable Temporal servers.
Copy failure retains committed output with a single activity attempt. Deletion recovery loses an acknowledgement after commit, replaces the worker and checks exact accounting before replay. Purge/delete checks include cancellation after
admission. Generic provisioning uses shared typed workflow payloads and checks creator
scope; processing workflow checks verify CPU/I/O queues, timeouts, retries and
stage ordering. The cross-language fixture runs the actual Python activities
and Docling Word parser against Go gRPC, signed MinIO transfers and Qdrant,
with controlled model responses. It checks committed-response loss, native
error classification, cancellation, index-only replay and public semantic search.
The deployed `letfs-ingest` entrypoint uses generated gRPC only; no application HTTP binding remains.

`OPENLET_HISTORY_DIR` retains fresh histories for a separate native replay check:

```sh
OPENLET_HISTORY_DIR="$PWD/.local/go-histories" pnpm --filter @openlet/letfs test:integration
OPENLET_HISTORY_DIR="$PWD/.local/go-histories" pnpm --filter @openlet/letfs test:replay
```

Replay requires scope/filesystem deletion, maintenance,
processing success/failure/retry/index-only and Python activity histories; missing
coverage fails the command. CI runs native integration before replay; the [current implementation record](../plans/261106-1517-account-scope-temporal-redesign/plan.md) records whole-system acceptance.

Workflow tests stay with their owning application. The new suite exports current
lifecycle and processing histories; deleted E2E histories are not
substituted. Native parser tests and regression corpora remain app-owned.

Native parser tests also generate an image-only PDF and require recovered OCR text.
Word parser regressions retain inline content-control text in multi-cell tables.
Section tests preserve picture-child text and the following section boundary.
Image regressions require relative Markdown targets that resolve to the extracted
bytes; the processing E2E fetches the image through that relative artifact path.
Additional regressions run the real PowerPoint parser on shape-level markup
compatibility branches and assert retained text, math and fallback image pixels.
Exporter tests count actual image writes across sections. Supervisor tests fill
stderr beyond the retained buffer, require bounded typed diagnostics, and verify
that document text is excluded from logs.

`make test-e2e` invokes the new Playwright API project. Use native Playwright
selection rather than old E2E TEST aliases. Native `test-unit`, `test-integration`,
`test-workflow`, `test-replay`, `test-provider` and `check` are thin native shortcuts.
The old scripts and TEST/SERVICE aliases no longer exist. Credential-dependent verification must report NOT RUN
separately from PASS. Tests never load development/provider credentials implicitly.

PRs run unit tests, compilation, lint and relevant integration/workflow checks. Shared HTTP/auth/infrastructure changes also run a small E2E smoke. Storage/workflow lifecycle changes run the relevant recovery checks. Release acceptance includes critical E2E/recovery, actual Clerk/provider smoke and isolated metadata/object backup restore using the selected provider procedure, with all direct/durable writers blocked and drained. Expensive performance experiments need an explicit workload/question and threshold.

## AI search verification

`go -C apps/letfs test -race -tags integration ./internal/filesystem ./internal/transport/grpc` uses PostgreSQL and Qdrant v1.20.0 with controlled provider responses. It checks original-file grouping, current/readiness gating, foreign evidence rejection before rerank, filters and filename cursor binding, one semantic retrieval without continuation, rerank-before-limit and 80/64/3 candidate/evidence bounds, dependency failures, rerank degradation, trash/restore, replacement, rebuild cleanup/retry, purge and filesystem deletion. The new API suite must cover create/upload through the real Temporal/Python chain, filename search during failed/pending processing, current semantic results, and membership revocation before final acceptance. Paid model quality is evaluated separately with supplied credentials; test responses exercise API contracts and orchestration.

The API journeys export fresh Account/Workspace lifecycle, Go filesystem/scope deletion,
processing success/failure/restart histories
to `.local/api-e2e/histories/`. Run the complete suite first. Each Go owner replays the fresh histories with its native SDK:

```sh
pnpm --dir e2e exec playwright test --project=api
OPENLET_HISTORY_DIR="$PWD/.local/api-e2e/histories" pnpm test:replay
```

Processing replay also checks CPU/I/O task queues, Activity order, heartbeat and
retry limits. ZIP uses HTTP streaming and has no workflow to replay.
