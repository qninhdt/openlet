---
phase: 4
title: "Go filesystem core and storage"
status: completed
priority: P1
effort: "56-80h"
dependencies: [1, 2, 3]
---

# Phase 4: Go filesystem core and storage

## Goal

Create the isolated Go `letfs` application core and storage implementation with behaviorally complete parity for provisioning, paths, nodes, uploads, copy state, trash/deletion state, quota, inline PostgreSQL bytes, and signed S3 transfers. Exercise it through generated gRPC contracts and native Go tests while the Rust implementation remains the behavior reference. The user-authorized provider change updates both Go and Rust fixtures to MinIO; application runtime cutover remains deferred. Do not switch Compose, Envoy, Workspace, or public traffic in this phase.

## Context and evidence

- The parity inventory is the behavioral checklist, not permission to simplify the rewrite: [letfs parity report](../reports/scout-261102-1059-letfs-go-parity.md).
- Authorization and caller scope arrive from phases 2-3. Every application operation must call the shared authorization boundary; role strings and trusted payload actor IDs are not admission (`plans/reports/scout-261102-1059-authorization-rpc-inventory.md`, "File facade").
- Current filesystem creation locks the bucket, creates a UUIDv7 filesystem/root once, validates replay scope, and saves the provisioning receipt atomically (`apps/letfs/src/fs/mod.rs:99`).
- Path resolution is a security boundary: trusted actor plus 1-32 mounts, longest segment-boundary match, bounded locators, live ancestry, read-only provenance, and expected target/parent identity (`apps/letfs/src/fs/paths.rs:37`, `apps/letfs/src/fs/paths.rs:100`).
- Nodes retain revision preconditions and artifact immutability (`apps/letfs/src/fs/nodes.rs:62`, `apps/letfs/src/fs/nodes.rs:78`); quota and node counts use checked SQL updates (`apps/letfs/src/fs/nodes.rs:132`, `apps/letfs/src/fs/nodes.rs:139`).
- Storage deliberately disables hidden write retries because durable evidence must distinguish known and ambiguous attempts (`apps/letfs/src/storage/mod.rs:17`). Single PUT signing binds content length, optional Content-MD5, and `If-None-Match: *`; multipart signs opaque part receipts (`apps/letfs/src/storage/transfers.rs:19`).
- Isolated integration uses PostgreSQL 18.6, source-built MinIO RELEASE.2025-10-15T17-29-55Z, and a Temporal dev server (`apps/letfs/tests/integration.rs:30`). The Go suite must own separate containers and databases; it must never point at a live Rust database.

## Key insights

1. Preserve one PostgreSQL canonical model. Port the baseline schema and invariants deliberately; do not introduce a repository framework or a second source of quota/tree truth.
2. Authorize the actual filesystem ID without business-owner mapping or service lookup. Mount selection is path context only. Workspace projects inheritance.
3. Keep transfer phases separate: capability issuance, candidate upload, reconciliation, destination publication, and logical quota accounting. A finalized transfer receipt is not the same as a published node.
4. Use direct signed S3 HTTP for object bytes and PostgreSQL for bounded arbitrary inline bytes. Application metadata/control is gRPC; object transport is not proxied through gRPC.
5. Go and Rust may coexist only as independent test targets during parity work. No shared live schema, dual writer, or shadow mutation is allowed.

## Data flow

1. Generated gRPC handler authenticates the public/service/job principal from phase 2 and validates delegated actor scope.
2. The application service resolves its local filesystem ID and checks the exact filesystem action with SpiceDB (bucket action for bucket-wide APIs), and rejects before mutation on denial or dependency failure.
3. `internal/filesystem` validates locators, revisions, ownership, lifecycle, artifact provenance, and quotas inside PostgreSQL transactions.
4. Inline bytes are stored/published in the same owner transaction. Object uploads first persist immutable candidate evidence, then issue signed S3 capabilities outside SQL locks, reconcile provider results, and finally publish once in PostgreSQL.
5. Generated gRPC responses preserve typed errors, decimal counters/revisions, timestamps, omission/null semantics, pagination, and immutable transfer receipts. Phase 6 later exposes these same application methods through public HTTP/native gRPC.

## Requirements

- Module path is `openlet/apps/letfs`; use Go 1.27.3 and compatible versions already established by `go.work` and phase 2. Any new direct S3 dependency/version requires verification against installed types or current official documentation.
- New application layout is `cmd/server` and `internal/{filesystem,storage,search,temporal,grpc,http,config,telemetry}`. Phase 4 owns `filesystem`, `storage`, the minimum `grpc/config/telemetry/cmd` composition needed for isolated tests, and no phase-5 behavior beyond interfaces.
- Use caller-preallocated UUIDv7 storage IDs and idempotency receipts; remove provision keys and business-resource bindings. Preserve frozen/deleting/deleted fences, bounded keyset enumeration, root tombstones, and dev-reset semantics.
- Preserve path/name/locator limits: 4096-byte paths, 255-byte segments, depth 128, at most 100 locators, 1-32 trusted mounts, exact segment matching, root-only canonical UUID alias, and expected identity guards.
- Preserve node/list/stat/create/rename/move/content/copy-admission/trash/restore/purge-admission/upload/status/parts/finalize/abort/storage-usage behavior, including pagination, omitted metadata, actor-only upload access, and actor-or-current-owner copy-monitor policy through actions rather than roles.
- Preserve quota, node-count, revision, sibling uniqueness, same-filesystem, cycle, read-only artifact, and lifecycle invariants under concurrent transactions.
- Preserve exact byte/range behavior: one validated suffix/open-ended/closed range, empty-file handling, invalid or multiple ranges rejected, inline 206 with logical ETag, object response as a signed direct descriptor/redirect contract.
- Preserve S3 endpoint/path-style/signing-host behavior, finite deadlines, browser and processor signing separation, exact Content-MD5/length/conditional headers, contiguous multipart receipts, terminal abort/expiry/finalization, and cleanup evidence for ambiguous writes.
- Do not implement workflows, search, processing, indexing, ZIP streaming, Python rename, Compose cutover, Workspace proxy removal, Rust deletion, AI agents, or real-LLM E2E here.

## File inventory

| Action | Absolute path | Current/New | Rough size | Test impact |
|---|---|---|---:|---|
| Extend | `/home/qninh/projects/openlet/apps/letfs/go.mod` | Actual `openlet/apps/letfs` module initialized by the Phase 1 provisioning proof | S | Native Go build/test and remaining dependencies |
| Modify | `/home/qninh/projects/openlet/go.work` | Current; phase 2 may already add `packages/go` | S | Workspace resolves `apps/letfs` |
| Create | `/home/qninh/projects/openlet/apps/letfs/cmd/server/main.go` | New Go composition; Rust `src/main.rs` remains | M | Startup/config/readiness tests |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/config/` | New; parity with `src/config.rs` | M | Config validation and secret-file tests |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/filesystem/` | New; ports `src/fs/{mod,provisioning,paths,nodes,ranges,uploads,trash,deletion,copy}.rs` | XL | Unit, SQL integration, race/recovery cases |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/filesystem/authorization.go`, `authorization_integration_test.go`, `provisioning_integration_test.go` in the same directory | Generic action checks and stable-ID idempotency; no business mapping/projector | L | Real graph checks, receipt expiry, late creation and generic service/job authority |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/storage/` | New; ports `src/storage/{mod,transfers,provider_smoke}.rs` | L | Real S3 integration/provider smoke |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/grpc/` | New handlers over phase-2 generated contracts | L | Actual in-process/network gRPC fixtures |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/http/` | New adapter interfaces only where phase-2 contract requires binary/range proof; no public cutover | S-M | Mapping tests, not routing switch |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/telemetry/` | New shared composition using `packages/go` | S | Redaction/trace tests |
| Modify | `/home/qninh/projects/openlet/apps/letfs/migrations/0001_initial.sql` | Existing single baseline; generic identity/lifecycle changes; drop provision columns at cutover | XL | Separate Go/Rust databases apply one canonical SQL file |
| Create | `/home/qninh/projects/openlet/apps/letfs/internal/testfixture/` | New isolated PG/S3/Temporal helpers | M | Prevents shared live DB or Rust HTTP usage |
| Modify | `/home/qninh/projects/openlet/apps/letfs/package.json` | Current Rust scripts; add clearly named Go tasks without removing Rust tasks | S | Turbo can run both references |
| Preserve | `/home/qninh/projects/openlet/apps/letfs/src/` | Current Rust reference | 0 | Remains comparison oracle until phase 7 |
| Preserve | `/home/qninh/projects/openlet/apps/letfs/tests/` | Current Rust reference tests | 0 | Remain runnable; only provider fixture changes are authorized here |

## Implementation steps

1. **Freeze the parity ledger.** Map every phase-4 RPC from phase-1 protobufs to the owning Rust function/test and to an exact authorization action. Record exclusions that belong to phase 5 or 6. Stop if any route, error code, nullable field, decimal counter, ETag, or idempotency input lacks an owner.
2. **Extend the isolated Go module.** Reuse `apps/letfs`, its `go.work` entry and generic provisioning/admin proof from Phase 1. Compose phase-2 shared identity/errors/authz/telemetry packages and validate config without copying app-framework abstractions. Keep the Rust binary and scripts available.
3. **Port the single baseline storage model.** Preserve tree/quota/upload constraints, idempotency receipts, lifecycle and cleanup evidence. The final baseline removes provision columns/constraints and adds no business-owner mapping or graph intent tables. During isolated Rust comparison retain a nullable legacy provision column only if unchanged fixtures require it; Go never uses it, and Phase 6 removes it in the backed-up cutover. One canonical baseline remains; no shared mutable runtime state.
4. **Port generic provisioning and lifecycle.** Create by bucket/filesystem IDs preallocated and persisted by the caller. Scope idempotency receipts to authenticated caller/operation/request key; save immutable create identity, resource/root and receipt atomically. A different request key for the same resource ID cannot allocate a duplicate or change creation parameters. Expired receipts leave resource primary keys and tombstones. Freeze a preallocated bucket ID even if create acknowledgment was lost; late creates fail against frozen/deleted state. Implement generic release/pruning/enumeration/deletion completion without workspace keys. Workspace owns inheritance projection; letfs has no graph acknowledgment wait or business rebuild exporter.
5. **Port generic path resolution.** Integrations choose labels such as `/drive`; letfs never loads workspace mount configuration. Check target filesystem permission independently from aliases. Implement mount validation, longest boundary match, ID/path/cwd locators, batch resolution, ancestry/live/read-only checks, root aliases, expected identity checks, and bounded recursion in one cohesive package.
6. **Port node and trash state transitions.** Implement stat/list/create, exact inline creation, rename/move, inline overwrite, copy admission/receipt state, trash/list/get/restore, purge admission, and deletion batches. Preserve atomic quota/node/revision updates, detached visibility rules, separately trashed parents, and partial-copy publication invariants.
7. **Port upload state machines.** Implement public and processor authority variants, immutable candidate keys, single/multipart/inline paths, capability issuance, HEAD/complete/HEAD reconciliation, terminal states, actor scope, saved results, destination revalidation, and exactly-once publication.
8. **Port S3 signing/control.** Configure path-style endpoints and separate browser/processor signers. Disable hidden write retries or add a proven per-wire-attempt reconciliation mechanism before enabling them. Bind content length and required checksums/conditions; preserve signed host values.
9. **Expose actual gRPC operations.** Implement generated server interfaces and typed error details over the same application methods. Tests must dial a real Go gRPC server with authenticated phase-2 caller credentials; direct package tests alone are insufficient for actor/job scope and protobuf zero-value handling.
10. **Build isolated parity tests.** Port focused Rust assertions into Go unit and Testcontainers tests. Give Go its own PostgreSQL database, S3 bucket/container, Temporal namespace/server, and identifiers. Never aim Go and Rust fixtures at the same database or compare by dual-writing live requests.
11. **Run provider proof without cutover.** Verify real selected-provider put/copy/range/delete, conditional writes, multipart completion, signing host, TLS, anonymous denial, and ambiguous response behavior through the existing opt-in provider route adapted for the Go binary. Report credential-dependent checks as NOT RUN when unavailable.
12. **Review the phase boundary.** Confirm no Compose/Envoy/Workspace runtime points to Go, no Rust source was deleted, no workflow/search/ZIP stub reports success, and every public/service operation reaches the application authorization boundary.

## Todo

- [x] Complete the phase-4 RPC-to-owner/action/error ledger; see [inventory](reports/phase-04-parity-ledger.md).
- [x] Add the Go module and compatible changes to the single existing baseline.
- [x] Use preallocated IDs, idempotency receipts and lifecycle tombstones; no business mapping/projector.
- [x] Port generic provisioning, paths, nodes, quota, trash, deletion state, copy state, and uploads.
- [x] Preserve inline PostgreSQL and signed S3 byte paths exactly.
- [x] Add authenticated real-gRPC fixtures and isolated Testcontainers resources.
- [x] Add concurrency, response-loss, ambiguity, cleanup, and authorization regression cases.
- [x] Keep Rust application sources/scripts runnable as the reference; Go and Rust test fixtures use the user-selected MinIO image.
- [x] Demonstrate that no runtime cutover occurred.

## Scenario matrix

| Severity | Scenario | Expected proof |
|---|---|---|
| Critical | Foreign filesystem/mount, spoofed actor, wrong service/job scope | Denied before mutation through real gRPC; no SQL/S3 side effect |
| Critical | Receipt expiry, different request key for same ID, late create after freeze/delete | IDs/tombstones prevent duplication and resurrection; immutable mismatch conflicts |
| Critical | FS permission without bucket permission; alias selects foreign FS | No bucket-wide or sibling access; check actual target resource |
| Critical | Concurrent quota/node writes and finalize/purge retries | Cannot overcommit or double-account; receipts converge |
| Critical | Crash/timeout after S3 write but before acknowledgment | Candidate remains fenced; reconciliation publishes once or cleans safely |
| Critical | Stale overwrite, replaced target/parent, read-only artifact | Old data remains; precise precondition/error returned |
| High | Finalized/aborted/expired upload capability renewal | Refused; actor-only scope remains, including for Owner |
| High | Copy candidate or cleanup unknown outcome | `open_writes`/ambiguous evidence prevents unsafe reuse or deletion |
| High | Trash restore/purge race and hidden detached descendant by raw ID | Only current entry wins; detached content stays hidden and charged |
| High | Range edge cases and empty inline file | Exact 206/Content-Range or explicit invalid-range error |
| Medium | Pagination/cursor/list metadata omissions | Stable bounded pages; contract-compatible optional fields |
| Medium | Provider host/path-style/header differences | Selected-provider smoke proves signatures and direct transfer behavior |

## Verification commands

### Actual current reference commands

```sh
pnpm --filter @openlet/letfs test
pnpm --filter @openlet/letfs test:integration
make test-provider
```

These currently execute the Rust reference (`apps/letfs/package.json:5`). They are comparison gates, not evidence for Go.

### Planned commands after this phase

```sh
go -C apps/letfs test ./internal/filesystem/... ./internal/storage/... ./internal/grpc/... ./internal/config/...
go -C apps/letfs test -race ./internal/filesystem/... ./internal/storage/...
go -C apps/letfs test -tags integration ./internal/filesystem/... ./internal/storage/... ./internal/grpc/...
go -C apps/letfs build ./cmd/server
```

Add package scripts such as `test:go`, `test:go:integration`, and `build:go` only as **new** scripts in this phase; do not redefine or remove current Rust schedules. The exact package list may be narrowed to created packages, but no passing command may skip the real gRPC or storage boundary.

## Success gate

- Every phase-4 behavior has an owning Go implementation and focused test, with no success placeholder.
- Native Go unit, race, integration, and build commands pass in isolated resources; current Rust unit/integration reference commands still pass.
- Real gRPC tests prove authenticated caller/actor scope, authorization at the application boundary, protobuf/error behavior, and actual Go execution.
- PostgreSQL concurrency tests prove quota, revision, receipt, lifecycle, and deletion invariants; real S3 tests prove direct transfer and ambiguity handling.
- Go and Rust have not shared a live database, bucket, or mutable fixture, and no Compose/Envoy/Workspace cutover has occurred.

## Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Lost invariant during rewrite | High | Critical | Trace each RPC to current source/test; port the smallest complete owner package and add regression cases before moving on |
| AWS SDK automatic retry changes ambiguity semantics | High | Critical | Disable write retries or prove durable per-attempt reconciliation with response-loss tests |
| Authorization enforced only in transport | Medium | Critical | Call one application boundary from gRPC and future HTTP adapters; add direct-adapter bypass tests |
| Go/Rust fixtures corrupt shared state | Medium | Critical | Unique container/database/bucket/namespace per suite; reject externally supplied live URLs in tests |
| Baseline schema drifts from current behavior | Medium | High | Apply the single baseline in separate Go/Rust databases; preserve reference-compatible inserts until cutover |

## Security and data safety

- Treat filesystem/bucket IDs, mounts, actor IDs, upload IDs, object keys, revisions, and signed headers as untrusted inputs.
- Fail closed when identity, SpiceDB, storage, or required consistency checks are unavailable. Never interpret missing graph data as allow.
- Do not log signed URLs, credentials, inline bytes, document content, bearer metadata, or provider response bodies.
- No real-data mutation is authorized by this phase. Before any later reset/cutover against non-disposable data, take and verify PostgreSQL/object backups.

## Rollback

Remove the new Go module/workspace entry and new Go-only package scripts, then continue running the Rust reference with its user-selected MinIO test fixture. Because this phase performs no runtime cutover and uses disposable isolated resources, rollback requires no data conversion. If any non-disposable environment was accidentally targeted, stop both writers, restore the verified pre-mutation PostgreSQL/object backup, and investigate before retrying.

## Next

Phase 5 depends on this gate and adds all durable Go workflows, processing/enrichment/indexing/search, request-owned ZIP streaming, and staged Python gRPC activities in the current app. Phase 6 coordinates the full `letfs-ingest` rename with Compose, CI, recovery, Workspace clients, Envoy, and public runtime cutover.
