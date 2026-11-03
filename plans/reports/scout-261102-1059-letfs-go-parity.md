# letfs Rust-to-Go parity scout

Execution note: current-source facts below are historical evidence. Target suggestions are superseded by the [reviewed plan](../261102-1059-go-grpc-filesystem-authorization/plan.md): use `packages/go` and `packages/contracts`; remove provision keys; letfs has no business-owner mapping/projector. Workspace owns storage inheritance projection. Generic caller-persisted IDs, idempotency receipts and storage lifecycle fences replace provision keys.

Date: 2026-11-02 (Asia/Saigon). Read-only source investigation for the accepted Go/gRPC/SpiceDB architecture. This report changes no product code. CodeGraph was consulted before file navigation. Existing untracked design/research reports were preserved.

## Accepted scope carried into planning

Replace Rust completely after proving full letfs parity; Go service and shared `libs/go`; direct official SpiceDB SDK calls; authenticated application gRPC between apps; public HTTP and native gRPC terminate directly at letfs. Workspace returns its drive filesystem reference and orchestrates lifecycle, but its file proxy disappears. Filesystems bind to typed resources rather than being intrinsically Workspace-owned. Trusted mounts, read-only artifacts, inline PostgreSQL bytes and direct signed S3 HTTP transfers remain. Python becomes `apps/letfs-ingest`, distribution `letfs-ingest`, module `letfs_ingest`, pnpm package `@openlet/letfs-ingest`. Development reset and fresh Go workflow histories are allowed; no old Rust-history compatibility. No AI agent implementation.

## Current runtime and dependencies

| Surface | Verified current source |
|---|---|
| Rust | Edition 2024; crate minimum Rust 1.96, toolchain/Docker 1.96.1 (`apps/letfs/Cargo.toml:4`, `rust-toolchain.toml:2`, `apps/letfs/Dockerfile:1`) |
| Rust HTTP/SQL/storage | Axum 0.8.9, Tokio 1.54.1, SQLx 0.9.0, object_store 0.14.2, reqwest 0.13.5, aws-sigv4 1.6.4, async_zip 0.0.19 (`apps/letfs/Cargo.toml:8`) |
| Rust Temporal | client/common/sdk/macros/workflow 1.1.0; SDK explicitly enables `experimental` and OTel (`apps/letfs/Cargo.toml:19`) |
| Existing Go | Go 1.27.3, pgx/v5 5.8.0, UUID 1.6.0, Testcontainers 0.44.0; Temporal SDK 1.50.0/API 1.63.5/OTel 0.8.1; protobuf 1.36.11 (`go.work:1`, `apps/workspace/go.mod:5`). grpc-gateway 2.29.0 is currently indirect, not an existing application API foundation (`apps/workspace/go.mod:65`). |
| Python | >=3.12,<3.14, Docker 3.13.18; Temporal 1.35.0, httpx 0.28.1, Docling/RapidOCR 2.144.0, torch 2.12.0, torchvision 0.27.0, pytest 9.2.0, Ruff 0.17.3, uv 0.10.7 (`apps/letfs-processing/pyproject.toml:4`, `apps/letfs-processing/Dockerfile:1`) |
| Real dependency fixtures | PostgreSQL 18.6; SeaweedFS 4.19 with 256 MiB tmpfs; real Temporal CLI dev server from admin-tools 1.32.1 (`apps/letfs/tests/integration.rs:31`, `:66`, `:128`). Search integration uses real Qdrant 1.20.0 (`docs/testing.md:128`). |

Do not turn this table into automatic target pins. Reuse compatible existing Go dependencies; verify official Go S3/SpiceDB/gRPC packages and codegen versions during implementation. Go was absent from this scout shell PATH, although installed Temporal module source exists under `/home/qninh/go/pkg/mod/go.temporal.io/sdk@v1.50.0`; no compile/runtime claim is made.

## Concrete module parity inventory

All paths below are current Rust source unless stated otherwise. The Go replacement should retain cohesive application boundaries, without inventing a generic repository framework.

| Current owner | Required Go behavior and critical evidence |
|---|---|
| `fs/mod.rs` | Idempotent quota-bucket/filesystem creation, UUIDv7 IDs, root creation, provision-key/name validation, scope equality on replay, transactional provisioning receipt. `ensure_filesystem` locks active bucket, preserves unique key identity and validates returned root/name (`:99`). |
| `fs/provisioning.rs` | Workspace owner-key derivation, remote receipt release, frozen bucket tombstone, bounded keyset FS enumeration, final bucket deletion requires all resources gone, receipt pruning (`:60`, `:84`, `:120`, `:140`, `:157`, `:180`, `:193`). Generalize resource binding at this owner boundary; do not discard receipt/tombstone behavior. |
| `fs/paths.rs` | Trusted scope with actor and 1–32 mounts; segment-boundary longest mount; ID/path/cwd variants; exact bytes; 4096-byte path/255-byte segment/128-depth bounds; root-only canonical UUID alias; live ancestry and read-only provenance in one recursive batch SQL; max 100 locators; mutation expected identity guard (`:7`, `:37`, `:46`, `:100`, `:157`). |
| `fs/nodes.rs` | File-vs-directory metadata; read-only artifact guard; revision preconditions; bucket/FS locking and repeatable-read reads; checked quota and node counts; scoped creation receipts; exact canonical base64 inline creation; rename/move/cycle/depth checks; inline overwrite preserves old data on refusal, detaches artifacts and queues old objects before recording new intent (`:15`, `:62`, `:132`, `:148`, `:336`, `:432`). Read/list/batch-stat pagination and metadata omission must remain bounded. |
| `fs/uploads.rs` | Outstanding uploads plus unfinished copy/backlog admission; user/parse/enrichment authority variants; immutable candidate keys; single/multipart selection; exact size/checksum validation; saved immutable results; no capability renewal after completing/finalized; explicit abort/expiry; HEAD reconciliation; atomic destination/revision/quota publication (`:21`, `:32`, `:210`, `:424`, `:434`, `:468`, `:536`, `:641`, `:737`). |
| `fs/ranges.rs` | One validated byte range including suffix/open-ended forms and empty-file behavior; invalid/multiple ranges fail rather than silently falling back (`:4`, HTTP guard `http/mod.rs:332`). |
| `fs/trash.rs` | Detach root only, preserve descendants and charged usage; current trash-entry identity; original-parent/name restore with no rename/overwrite; purging excludes restore; raw detached IDs hidden (`:37`, `:59`). |
| `fs/deletion.rs` | Purge claim and filesystem deleting fence; abort unattached uploads with cleanup evidence; nullable separately-trashed original parent; actual removed-row quota/node-count debit; branch <=128, leaf batch <=64; all live/trash/artifact roots removed; deleted FS tombstone (`:35`, `:93`, `:124`, `:137`). |
| `fs/copy.rs` | One admission receipt, deterministic SHA-256-derived UUIDv8 destination per copy/source, no content in history, high-water child ID and keyset traversal, captured source/destination revision and immutable payload identity; one-hour deadline and job ceilings; candidate evidence registered before S3 I/O; revalidate afterward; visible per-node commits and partial success; no retry resurrection or recharge (`:25`, `:43`, `:60`, `:88`, `:133`, `:313`, `:430`). File subtree finish admits processing exactly once and can reuse copied parsed artifacts; derived descendants remain read-only (`:458`). |
| `fs/artifacts.rs` | Eligible formats, committed generation intent, invalidation/detached artifact cleanup, trash fencing, processing status, caller-scoped manual-reprocess receipt, bounded detached-forest drain (`:8`, `:61`, `:86`, `:109`, `:130`, `:146`, `:193`). |
| `fs/processing.rs` | File/generation plus retry number/UUID authority; immutable object-key or inline hash identity; live/writable source; newer accepted attempts fence old work; per-stage output ownership; exact finalized output manifest; all-at-once parse artifact attach/quota/node count; manifest-hash replay; lifecycle cleanup and conservative workflow-status reconciliation (`:13`, `:51`, `:70`, `:84`, `:120`, `:128`, `:151`, `:232`, `:355`, `:415`). |
| `fs/enrichment.rs` | Validated family:kind semantic taxonomy, file-only metadata, exact whole-tree node/path manifest, original payload immutability, no reparent/type change, README rewriting, bounded replacement uploads, one transaction for renames/links/metadata/quota/revisions/ready facts (`:16`, `:108`, `:192`, `:341`). |
| `fs/indexing.rs` | Full model/collection/dimension identity; readiness only after complete acknowledgment and current generation/live/publication/space checks; configuration change schedules index-only rebuild; durable obsolete-index tombstones; cleanup waits for producers and cannot remove current serving identity (`:14`, `:39`, `:64`, `:106`, `:133`, `:186`). |
| `fs/search.rs` | Filename/title SQL search independent of AI readiness; filters and sort; cursor binds actor/mount/FS/query/filter/sort/space; hybrid dense+native BM25 RRF; live/current/ready database hydration before rerank; original-file grouping; degraded rerank fallback only; finite candidate/cursor work (`:18`, `:55`, `:190`, `:328`). |
| `fs/backfill.rs` | Existing CLI `--backfill-processing`, default dry run, modes `missing` and `rebuild-index`, `--after`, `--limit` 1–1000, explicit `--apply`, live originals only; preserve original bytes and active-work guards (`:8`, `:41`, `:44`, `:65`). |
| `fs/archive.rs`, `storage/archive.rs` | Request-owned ZIP64, directory-only selected root, stop traversal at file payloads, empty dirs, unsafe Windows/path names and case/NFC collision preflight, bounded entries/source/output/runtime/concurrency, selected identity/path/revision revalidation, exact bytes, disconnect cancellation owns stream/storage work/permit; no entity, receipt, workflow, S3 archive write or quota (`fs/archive.rs:28`, `:49`; `storage/archive.rs:57`, `:122`). |
| `fs/maintenance.rs` | Upload expiry and multipart abort retries, detached artifact drain, purging-entry redelivery, processing/index reconciliation, incomplete-copy start/finish recovery; bounded object cleanup outside DB transactions, active reference/candidate exclusion, ambiguous tombstones retried daily (`:6`, `:24`, `:62`). |
| `config.rs`, `main.rs`, `telemetry.rs` | Validated secret/file configuration, limits, external endpoint trust, telemetry redaction, shared trace propagation, finite readiness, bounded HTTP/worker graceful shutdown, CLI health/provider/backfill modes; DB pool max 16 and finite worker concurrency/cache are current deliberate bounds (`config.rs:156`; `main.rs:38`, `:67`, `:101`). |

## Endpoint / RPC inventory

`http/mod.rs:178` currently authenticates either Workspace or processor bearer token, selected by path. This is service authentication, not user authorization. It must become authenticated gRPC caller identity plus trusted actor/job scope, and direct public identity plus permission checks at the application operation boundary. Public callers must never choose trusted mounts or service/job authority.

Current application HTTP families to replace, mapped to typed RPC operations:

| Current route family | Complete operation set |
|---|---|
| `GET /internal/v1/quota-buckets/{id}`; `GET /internal/v1/filesystems/{id}` | Get bucket usage/limit/upload limits; get FS/root/lifecycle/binding. `http/mod.rs:204`, `:233`, `:251`. |
| `/internal/v1/filesystems/{fs}/nodes` | Create directory/exact inline file/admit copy; list. Resolve at `/nodes/resolve`. Get/patch/trash by node ID. Content get/put. Processing get/reprocess post. Copy status get. `http/nodes.rs:95`. |
| `/internal/v1/filesystems/{fs}/nodes/{node}/archive` | Stream archive with request lifetime/cancellation, safe attachment and no-store. `http/archive.rs:19`. |
| `/internal/v1/filesystems/{fs}/files/{action}` | `batch-stat`, `search`, `semantic-search`; other actions 404 (`http/mod.rs:269`). |
| `/internal/v1/filesystems/{fs}/uploads` | Create; get status; delete/abort; get part URLs; put completion. `http/uploads.rs:13`. |
| `/internal/v1/filesystems/{fs}/trash-entries` | List; get entry; restore; purge. `http/trash.rs:14`. |
| `/internal/v1/processing/{file}/{generation}/index/{action}` | Prepare, complete with exact vector space, fail. `http/processing.rs:73`. |
| `/internal/v1/processing/{file}/{generation}/{stage}/{number}/{attempt}/{action}` | Parse prepare/outputs/complete/abort; enrichment prepare/outputs/complete/fail. `http/processing.rs:99`. |
| Processing `.../uploads/{upload}/{action}` and `.../bytes` | Status, part URL batch, complete, bounded inline transfer. Scope includes stage and accepted attempt; no arbitrary file upload. `http/processing.rs:140`, `:174`. |
| `/live`, `/ready`, `--healthcheck` | Replace or adapt to standard gRPC health and Compose checks without routing health through public identity auth (`http/mod.rs:218`, `main.rs:8`). |

Current public facade contract covers nodes resolve/stat/list/create/copy/move/rename/content/archive; upload/status/parts/completion/abort; trash/list/get/restore/purge; copy monitor; processing status/reprocess; basic and semantic search (`docs/api-contracts.md:56`). The target HTTP route base changes to direct filesystem scope. Port every shape, omission/null, decimal int64, timestamps, ETag, Location, no-store and machine error code deliberately into protobuf + generated HTTP mapping. gRPC needs native typed error details that preserve the existing codes without relying on HTTP status alone.

Two concrete old authorization assumptions must disappear: `/drive` is hardcoded by HTTP scope construction and default list locator (`http/nodes.rs:29`, `:72`); copy monitor receives `x-workspace-role == owner` (`http/nodes.rs:129`). Generic FS binding and explicit permission must replace them, while current initiator-or-owner copy-monitor restriction and initiator-only upload-session access remain behaviorally defined.

## S3 and PostgreSQL byte behavior must not change

- Browser signing and processor signing use distinct endpoints; do not rewrite signed hosts (`storage/mod.rs:8`, `:41`, `:54`; `docs/api-contracts.md:121`). Public single PUT signs size, provider-enforced Content-MD5 and conditional `If-None-Match:*`; multipart signs each part length and accepts contiguous ordered opaque ETags, never a synthesized object MD5 (`storage/transfers.rs:19`, `:34`, `:69`; `fs/uploads.rs:518`).
- Rust currently deliberately disables hidden object-store retries because write evidence tracks each request (`storage/mod.rs:31`). Go S3 SDK defaults are a migration hazard: disable hidden write retries or prove every wire attempt is reconciled with the same invariant. Configure exact endpoint/path-style, headers/checksums, signed length, finite deadlines and compatible completion semantics. Real selected-provider smoke is the acceptance gate.
- Finalize freezes completion receipts, marks completing, releases SQL locks, HEADs/completes/HEADs the unique candidate, then rechecks stored scope/destination/preconditions/quota and publishes once (`fs/uploads.rs:536`). Aborted/expired is terminal; finalized transfers cannot issue more capabilities or be aborted. Public result and processor transfer receipt are different contracts (`:641`, `:652`, `:713`, `:737`).
- Processor completion is immutable transfer evidence `{id,status:finalized,size_bytes}`. Parse/enrichment separately attach a result node and charge quota, preserving that receipt. Same-byte inline replay uses retained SHA-256 even after attachment (`fs/uploads.rs:468`; `fs/processing.rs:151`, `:232`). Do not collapse transfer, publication and index readiness.
- S3 copy increments `open_writes` in durable cleanup evidence before I/O and only closes known successful calls; process death/unknown response stays pinned. Any attempted cleanup fences future reuse/publication of that candidate. GC does not debit logical quota and never drops final evidence merely on NotFound (`fs/copy.rs:313`; `fs/maintenance.rs:62`).
- Inline arbitrary bytes stay in PG. Object content returns HTTP 307 to direct S3; inline supports 206 with Content-Range and logical revision ETag; object ETag is distinct (`http/mod.rs:303`, `:348`). Reauthorization precedes issuing a renewed descriptor; issued URL expiry is the existing revocation boundary.

## Temporal port and SDK friction

Required owner registrations are `CopyNode`, `ProcessFile`, `PurgeTrash`, `DeleteFilesystem`, `StorageMaintenance`, lifecycle/copy activities and six named Workspace provisioning activities (`main.rs:77`; `temporal/provisioning.rs:16`). Register explicit wire names rather than depending on Go function-name inference. Existing Workspace already schedules these named remote activities and `DeleteFilesystem` child; migrating language does not remove those control-plane contracts (`docs/workflows.md:38`).

| Workflow | Required deterministic state/options |
|---|---|
| Copy | Bounded State includes admission, <=128 frames, one pending selection, acknowledged node/byte counts, terminal status/error; query `progress`; 100 steps then Continue-As-New; short activity timeout 30s, storage 150s + heartbeat 30s, max attempts 3; error becomes explicit partial result; complete receipt (`temporal/copy_workflow.rs:55`, `:95`, `:100`). Start uses UseExisting + RejectDuplicate, execution 1h (`temporal/mod.rs:85`). Monitor checks retained admission plus actor/current authority, queries running progress or terminal result, handles expiration 410 (`temporal/copy_workflow.rs:210`). |
| Purge / FS deletion | Shared beginning + leaf batch sequence; 30s activities under cancellation-independent scope, 200 batches then Continue-As-New; immutable deletion identity only, seven-day execution; stable logical keys and duplicate-resume policy (`temporal/lifecycle_workflow.rs:79`; `temporal/mod.rs:114`). Go must explicitly implement disconnected cancellation scope, not merely omit a cancellation token. |
| Maintenance | Native schedule `openlet-storage-maintenance`, 300s interval, overlap Skip; finite expire->reconcile->delete sequence; short 30s and bounded 240s/heartbeat30/max3 options (`temporal/lifecycle_workflow.rs:143`, `:174`). |
| Processing | Optional parse CPU, optional enrich I/O, then index I/O only after required earlier stages succeed; 7200s schedule-to-close, 1800s start-to-close, heartbeat30, max3; base workflow 22500s execution; index-only identity includes exact vector-space hash and allows closed duplicates (`temporal/process_file_workflow.rs:7`, `:30`, `:64`, `:75`). |
| All activity adapters | ApiError client failures become non-retryable typed application failures; infrastructural errors retry; Go must preserve code classification and periodic heartbeat ownership (`temporal/mod.rs:17`, `:25`). |

Go SDK 1.50.0 installed source exposes query handlers, Continue-As-New, schedules, history iteration and replay (`workflow/workflow.go:641`, `:883`; `client/client.go:1264`, `:1679`; `worker/worker.go:289` in that module). This is source feasibility, not a successful cross-language experiment. Key friction is semantic, not a need to preserve Rust Core APIs: explicit registration names; deterministic clock/maps; JSON number/UUID/timestamp/null encoding; retry/cancellation defaults; UseExisting vs duplicate-closed behavior; current-run lookup after Continue-As-New; heartbeat details; trace propagation with replay suppression. Fresh Go histories remove old Rust replay compatibility, but Python remains a real cross-language activity boundary and must decode/encode the new workflow payloads exactly. No file bytes or credentials enter history.

Current replay covers CopyNode/continuation/recovery, purge, FS delete, maintenance and parsed/direct/failed/recovery ProcessFile; it asserts process activity order, CPU/I/O queues, heartbeat and max attempts (`tests/workflow-replay.rs:29`). Port these assertions and generate fresh histories from the Go stack, rather than deleting replay coverage with Rust.

## Python application RPC versus signed byte HTTP

`activity.py` deliberately has two clients: authenticated letfs `api` (30s, no redirects), and unauthenticated signed-object `storage` (120s, no redirects), at parse/enrich/index entry points (`:137`, `:254`, `:359`).

Application calls that become generated gRPC methods: parse/enrich/index prepare/outputs/complete/fail; upload status/parts/complete; inline source/output payloads, including the current `api.put(.../bytes)` (`activity.py:408`, `:508`, `:543`). Preserve bounded 3-attempt transient handling, terminal semantic code classification without leaking response data, per-stage generation/attempt fencing, cancellation/shutdown distinction and publication reconciliation.

HTTP calls that remain supported provider protocol: signed GETs for source/evidence; signed single PUT/multipart-part PUTs; Qdrant/OpenRouter provider requests (`activity.py:181`, `:327`, `:467`, `:560`, `:579`). Rename does not entail parser/converter redesign. Preserve CPU-only offline model/OCR preflight; I/O worker without models; activity concurrency 1 CPU/4 I/O; 20s graceful shutdown and 5s heartbeat throttling (`worker.py:21`, `:65`). Preserve minimal subprocess environment, process-group termination/reaping, 660s converter supervision, typed bounded diagnostics that exclude document stderr (`activity.py:28`, `:43`, `:76`).

Rename scope is all 16 `src/openlet_processor/*.py` modules and their imports, all eight test modules and fixtures as applicable, subprocess `-m` strings, Docker copy/build/model-prefetch/entrypoint, wheel package config, root uv workspace + lock, root scripts, pnpm lock/workspace discovery, Compose build paths/image/env/service references, CI uv commands and docs. Verified source: `pyproject.toml:2`, root `package.json:9`, Python package `pyproject.toml:2`, `:47`, `package.json:2`, Dockerfile `:6`, `:10`, `:27`, CI `check.yaml:33`, Compose dev `:225` and E2E `:233`.

## Meaningful regression inventory and execution gates

Tests should port behavior, not imitate Rust implementation details. Existing real fixtures execute baseline migrations directly; most core Rust integration helpers call application functions, so they do not prove a future gRPC boundary on their own (`tests/integration.rs:23`, `:127`). Add real Go and Python generated-client tests, both HTTP/native-gRPC public auth paths, and actual gateway spoofed-header checks.

| Test owner | Existing scenarios that must survive |
|---|---|
| `tests/integration.rs:256`, `:364`, `:595`, `:835`, `:1144` | Input limits, exact bytes, tree/mount/revision/quota, download/range, provider contract, multipart/session/finalize/abort, old-data preservation. |
| `tests/integration.rs:1278`, `:1421`, `:1482` | Pinned provisioning results/owner scope, failed provisioning tombstones/fencing, atomic scoped create receipts/expiry without recreation. |
| `tests/copy/mod.rs:5`, `:163` | Retry cannot recharge or resurrect; rejected object copy closes only known write, cleanup prevents candidate reuse. |
| `tests/deletion/mod.rs:5` | Bounded purge progress and no double debit on repeated completion. |
| `tests/artifacts/mod.rs:7`, `:472`, `:591`, `:831` | Large forest copy/lifecycle, every logical file dispatch/media type, invalidation/accounting/trash terminality, hybrid path/cwd/alias and raw-ID read-only enforcement. |
| `tests/artifacts/processing.rs:134`, `:187`, `:416`, `:558`, `:721` | Superseded finalized receipts retained/cleaned, whole-output publication once, stale attempt/quota atomicity, enrichment atomic/idempotent tree rename, foreign/obsolete manifest rejection. |
| `tests/artifacts/archive.rs:57`, `:126`, `:235` | Inline/object/empty ZIP without storage writes; mutation/unsafe-path/limit rejection; body-owned slot/deadline and cleanup. |
| `tests/search/mod.rs:138`, `:614` | Real PG/Qdrant current/live/ready filtering, grouping, cursor binding, foreign evidence excluded before rerank, degradation/dependency failures, trash/restore/replacement/purge/deletion, index rebuild and byte-preserving backfill. |
| `tests/telemetry.rs:68`, `tests/workflow-replay.rs:12` | Real Temporal trace across Continue-As-New and replay with no duplicate exports; representative current business histories. |
| Python `tests/test_activity.py` | Converter process cleanup/cancellation/output limit; committed-result reconcile skips converter; terminal transfer retry does not resend bytes; safe error classification; worker shutdown retryable; typed diagnostics; report semantic failure only after retries exhausted. |
| Python parser/exporter/layout/semantic/indexing/worker tests | Real PDF/DOCX/PPTX/XLSX/OCR and embedded-image regressions; exact text/layout/link preservation; minimal Qdrant payload/immutable IDs/BM25 confirmation; offline CPU vs model-free I/O. See `docs/testing.md:107`, test module inventories. |

Current executable baseline commands (not run by this scout):

```sh
cargo test --locked --package letfs --lib
cargo test --locked --package letfs --test integration --test telemetry -- --ignored --test-threads=1
cargo test --locked --package letfs --test integration search -- --ignored --test-threads=1
uv run --locked --package openlet-processor pytest apps/letfs-processing/tests -m 'not parser'
uv run --locked --package openlet-processor pytest apps/letfs-processing/tests -m parser
pnpm check:e2e
node --test --test-concurrency=1 e2e/setup/environment.test.ts e2e/setup/recovery.test.ts
pnpm --dir e2e exec playwright test --project=api
OPENLET_HISTORY_DIR="$PWD/.local/api-e2e/histories" go test -tags replay ./apps/account/internal/temporal ./apps/workspace/internal/temporal
OPENLET_HISTORY_DIR="$PWD/.local/api-e2e/histories" cargo test --locked --package letfs --test workflow-replay -- --ignored
make test-provider
```

Discover target commands from the new Go manifest and renamed Python app; do not leave obsolete package names or add skipped compatibility suites. Target gates should include gofmt/vet/compile/unit, app-owned `integration` tests with real PG/S3/SpiceDB/Qdrant/Temporal as relevant, deterministic workflow SDK branches + fresh-history replay, renamed Python lint/unit/parser, reproducible proto/OpenAPI/stub generation, small gateway E2E then complete API/recovery, and provider opt-in reported separately. Real restart/recovery must use PostgreSQL-backed Temporal from Compose, not claim persistence from the integration dev-server fixture (`docs/testing.md:39`, `:45`, `:124`). Controlled AI providers remain appropriate; paid model quality is separate.

Concurrency uses barriers; response loss at effect/ack boundary; actual transactions for quota/lock claims. Add parity-specific cases for int64 limits/decimal JSON, protobuf unset/empty/null, HTTP 201/202/204/307/206/416/428/412 mappings, streamed cancellation/backpressure/error-after-headers, actor/service/job impersonation, generic bindings and nested mounts, direct public permission changes, and both RPC access paths. Quota reconciliation includes live/trash/detached data and node counts, with no automatic repair.

## Concrete file scope for plan authors

### Replace/delete after equivalent Go behavior is verified

- Entire Rust-only implementation `apps/letfs/src/` (all 36 `.rs` files), Rust tests `apps/letfs/tests/` (integration + telemetry + workflow-replay and artifacts/copy/deletion/search modules), `apps/letfs/Cargo.toml`.
- Root `Cargo.toml`, `Cargo.lock`, `rust-toolchain.toml` when the last Rust crate is removed; root Cargo workspace currently contains only letfs (`Cargo.toml:2`). Remove Rust CI/toolchain/build steps and stale Rust docs. Preserve SQL and meaningful scenario coverage in their new owner.
- Workspace file proxy implementations `apps/workspace/internal/http/{archive,files,nodes,search,trash,uploads}.go` and `apps/workspace/internal/letfs/` transport wrappers after route/caller cutover; related tests/router/dependencies must be rewritten in the same delivery. Preserve Workspace storage-reference and lifecycle responsibilities.

### Existing files to update rather than duplicate

- `apps/letfs/migrations/0001_initial.sql` remains canonical SQL owner; preserve all payload/state/generation/unique/same-FS/receipt/cleanup constraints and indexes while adding generic binding/projection facts. Dev reset permits baseline restructuring, not relaxed invariants.
- `apps/letfs/package.json`, `apps/letfs/Dockerfile`, `go.work`, Go sums/manifests, root `package.json`, pnpm/uv workspace/locks, `.github/workflows/check.yaml`, Compose dev/E2E, gateway routes, health/ops/recovery scripts, contracts and docs.
- Python rename tree and transport changes listed above; use tooling to regenerate lockfiles.
- E2E clients/routes and history-export/replay runners must address letfs directly and assert current inherited permissions rather than route through Workspace.

### Proposed new Go owner boundaries (plan proposals, not existing paths)

`apps/letfs/go.mod`, `cmd/letfs/main.go`, `internal/{config,fs,storage,temporal,grpc,http,telemetry}/`; use kebab-case filenames for multiword names. Small Go `fs` files corresponding to current behavior (`nodes.go`, `paths.go`, `uploads.go`, `copy.go`, `trash.go`, `deletion.go`, `artifacts.go`, `processing.go`, `enrichment.go`, `indexing.go`, `search.go`, `archive.go`, `backfill.go`, `provisioning.go`, `maintenance.go`) give clear parity ownership without fake service scaffolds. Integration fixtures/tests belong to the app and use canonical SQL. Existing Go patterns and final contract routing may justify fewer packages/files.

`libs/go` owns shared identity/caller credentials, gRPC interceptors/errors/telemetry and authz SDK/action-resource contracts as accepted. Protobuf source/generation, Go/Python generated outputs and OpenAPI need one canonical contract location chosen with repository contract owners; no alternate hand-maintained DTO family. The Python transport wrapper must consume generated stubs, not old HTTP endpoints behind gRPC.

## Source discrepancies and remaining proof obligations

1. Inline content MIME differs between docs and implementation: `docs/api-contracts.md:126` says application/octet-stream, while `http/mod.rs:382` returns file MIME plus attachment/nosniff. Preserve the current file-MIME plus attachment/nosniff behavior explicitly in the target contract and parity tests; update the inaccurate documentation instead of silently changing behavior.
2. `docs/workflows.md:84` says never hold DB locks during network I/O. Current `fs/indexing.rs:158` holds a lifecycle transaction around `delete_points` at `:175`. A naive unlock introduces a current-space deletion race; target needs a race-safe cleanup design that honors the intended lock/I/O boundary, with real concurrency proof.
3. Full current transport is private service-auth HTTP, so public direct gRPC + SpiceDB inheritance is new behavior requiring real boundary tests; existing Rust parity tests alone cannot prove it.
4. Official Go S3 signing/provider behavior, public HTTP streaming adapter behavior, Python generated gRPC compatibility, source-aggregate SpiceDB fencing and PostgreSQL/SpiceDB image compatibility remain implementation spikes, not established runtime results here.

No tests, containers, server processes, network provider smoke or benchmarks were run. No product files were changed. Unresolved product questions: none; current inline MIME behavior is preserved, and implementation proof obligations remain explicit.

Status: DONE_WITH_CONCERNS
Summary: Complete source-grounded letfs module/endpoint/storage/workflow/search/processor parity inventory, affected file scope and executable regression gates for the Go migration.
Concerns/Blockers: Inline MIME doc/source discrepancy and index-cleanup lock/I/O discrepancy require explicit plan treatment; target SDK/transport spikes remain unverified. Go CLI was absent from this scout shell PATH.


## Post-scout planning corrections

The final target layout follows user steering: `packages/go` and `packages/contracts`, replacing the earlier `libs/go` suggestion above; factual current-source paths remain historical evidence. ProcessFile propagates required parse/enrichment errors before scheduling indexing; index-only remains valid. The seven-phase plan stages generated Python gRPC in the current app and performs the full ingest rename with runtime, CI and recovery consumers in Phase 6.
