# Testing strategy

Status: native service integration uses Testcontainers; system E2E/recovery uses Compose; see [setup](setup.md) for commands and [operations](operations.md) for external checks. Use the lowest reliable layer that proves an application invariant; test doubles cannot replace verification of real storage/recovery behavior.

## Three levels

| Group | Environment | Responsibility |
|---|---|---|
| Unit | No infrastructure | Validation, path/name logic, role rules, checked arithmetic, transfer protocol shapes |
| Integration | One service and real relevant dependencies | SQL/transactions, HTTP contracts, storage and trust boundaries |
| System E2E | Public HTTP through real Envoy/Compose stack | A small set of complete backend journeys |

Workflow decision/replay checks belong to their native unit or integration scope; they are not a fourth level. Security, concurrency, contract, recovery and efficiency are scenario categories, not extra frameworks. No arbitrary coverage percentages, test-count targets or unmotivated load/soak suite.

## Required checks

| Risk | Lowest reliable proof |
|---|---|
| Gateway | Real Envoy/test JWKS: bad issuer/signature/expiry, missing claim, bootstrap restrictions, spoofed/duplicate trusted headers, internal route isolation |
| Account | Real PG uniqueness, repeat onboarding, lost provisioning response, Clerk failure then success |
| Workspace | Real PG role/Owner transactions, concurrent transfer/removal, invite expiry/revoke/email mismatch, Owner-role rejection and replay after removal; member summaries exclude self-only fields |
| Tree | Real PG sibling uniqueness, same-FS parent, cycle prevention, path traversal, mount/cwd escape and ID ancestry |
| Data | Exact bytes/line endings, caller-selected arbitrary inline bytes, direct object transfer, stale overwrite preserves old data, path replacement with equal revision rejects old expected target/parent ID |
| Artifacts | Hybrid paths/cwd/root aliases, raw-ID readonly enforcement, copy traversal, source/ancestor lifecycle, detached forest cleanup and exact quota |
| Quota | Competing writes cannot overcommit; finalize/copy/purge retry cannot double-account; trash remains charged; repeated deletion batches never debit twice |
| Trash | Restore/purge race, hidden descendants by ID, missing parent/name conflict, Viewer denied, commit then response loss, delayed old trash after restore and delayed old restore after re-trash |
| Copy | Coherent item revision, source ID copied once, documented concurrent-source outcomes, committed partial progress and atomic per-item quota/publication, self/descendant rejection, finite traversal under continuous additions and configured job ceilings |
| Objects | Real test S3 put/copy/range/delete, per-key errors, ambiguous/late writes, bounded outstanding/backlog admission and read/GC grace |
| Recovery | Crash after commit/between batches, all filesystem roots deleted, tombstones block recreation |
| Efficiency | SQL/RPC counts bounded independently of list page size; batch enrichment/stat; one path round trip without O(1) claim; node-count boundary and count reconciliation |
| Status | Caller/scope binding, same-key input mismatch, admission timeout, closed-before-first-activity retry, direct ambiguous-response reconciliation and durable retention/deletion retries |

Concurrency cases use barriers/controlled transactions rather than sleeps/random stress. Response-loss tests inject failure at the side-effect/acknowledgment boundary. Use real migrations and dependencies for claims about PostgreSQL locks, S3 or Temporal persistence.

## External integrations

Clerk error handling uses controlled HTTP responses. A separate development-instance smoke verifies actual backend metadata and refreshed JWT. A test issuer is not evidence live Clerk passed. Never use production accounts/credentials/data.

S3 tests use a dedicated compatible server and bucket. Before release verify the selected provider's actual put/copy/range/delete/version behavior, valid TLS, rejected anonymous reads and object-only credential permissions; local-emulator success is not universal compatibility. Real restart tests use PostgreSQL-backed Temporal.

Check public/internal OpenAPI against handlers and explicit Go/Rust DTOs: UUIDs, decimal counters/revisions, optional/null values, timestamps, errors and ETags. No schema registry or custom test framework.

## Workflow and system coverage

SDK tests cover branches, retry classifications, timers and replay. Real Temporal tests cover worker/server restart, commit followed by response loss, checkpoint continuation and retained partial-copy results. SDK activity mocks do not prove storage recovery. File bytes stay out of history.

The new Playwright API suite under `e2e/` was authored from scratch before
business refactoring. It covers gateway boundaries and target onboarding,
collaboration, byte/revision/quota contracts, uploads, partial copy, trash, ZIP,
processing/search and worker recovery. Coordinated recovery calls the permanent
operations CLI. The recovery project runs before the API project so adversarial
upload cases cannot leave open capabilities that invalidate its backup precondition.
Full-suite results and external-provider limits live in the completed plan's validation
record. No old Go E2E source/history is retained as coverage.

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

Go: standard `testing`/`httptest` near packages, with app-owned PostgreSQL
Testcontainers fixtures behind the `integration` tag. Rust storage integration is
`apps/letfs/tests/integration.rs`; `tests/telemetry.rs` runs a real Temporal server
and proves trace continuity across Continue-As-New, then replays both runs without
exporting duplicate spans. Each uses fresh containers and the app's single
baseline SQL; no shared module or migration shell script remains. Turbo invokes
native commands from minimal app package manifests; native commands work alone.
Integration tasks run sequentially across apps and Rust cases to bound resources.
The letfs S3 fixture uses a 256 MiB tmpfs. Docker absence fails a requested run;
no test implicitly loads development/provider credentials.

Workflow tests stay with their owning application. The new suite exports current
lifecycle, copy, purge and processing histories; deleted E2E histories are not
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

`cargo test --locked --package letfs --test integration search -- --ignored --test-threads=1` uses PostgreSQL and Qdrant v1.20.0 with controlled provider responses. It checks original-file grouping, current/readiness gating, foreign evidence rejection before rerank, filters/cursor binding, dependency failures, rerank degradation, trash/restore, replacement, rebuild cleanup/retry, purge and filesystem deletion. The new API suite must cover create/upload through the real Temporal/Python chain, filename search during failed/pending processing, current semantic results, and membership revocation before final acceptance. Paid model quality is evaluated separately with supplied credentials; test responses exercise API contracts and orchestration.

The API journeys export fresh Account/Workspace lifecycle, Rust filesystem/purge,
copy continuation/partial failure and processing success/failure/restart histories
to `.local/api-e2e/histories/`. Run the complete suite first. The Go owner uses
official protobuf JSON/binary APIs to convert CLI histories before the Rust replay:

```sh
pnpm --dir e2e exec playwright test --project=api
OPENLET_HISTORY_DIR="$PWD/.local/api-e2e/histories" go test -tags replay ./apps/account/internal/temporal ./apps/workspace/internal/temporal
OPENLET_HISTORY_DIR="$PWD/.local/api-e2e/histories" cargo test --locked --package letfs --test workflow-replay -- --ignored
```

Processing replay also checks CPU/I/O task queues, Activity order, heartbeat and
retry limits. ZIP uses HTTP streaming and has no workflow to replay.
