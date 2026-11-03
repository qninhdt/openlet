# Phase 4 implementation evidence

Status: completed for the isolated Go core/storage scope; no runtime, gateway or Workspace cutover occurred. All Go SQL/graph fixtures were isolated from Rust and developer resources.

## Implemented core

The [parity ledger](phase-04-parity-ledger.md) maps phase-4 generated RPCs to their Rust behavior owners, native actions and error/shape requirements. The existing generic provisioning proof remains and passed the complete Go integration run.

Go letfs now implements filesystem metadata and independent bucket usage admission; node reads, bounded batch resolution, ID/path/cwd/root aliases, longest segment-boundary mount matching, live ancestry and artifact provenance; node listing with scoped keyset pagination and omitted context. User actors come only from verified context; no business mapping, graph writer or owner-service RPC lookup exists in letfs.

Directory and exact inline-byte creation use the existing idempotency table, actor/FS scope, parent guards, locked quota/node counts and immutable saved results. Empty protobuf byte representations normalize before fingerprinting. Processing generation intent is persisted with source identity and the existing supported-format rules; workflow dispatch/reconciliation remains Phase 5, before any runtime adoption.

Rename/move enforce revision/expected identities, immutable root/artifacts, sibling uniqueness, cycle and full subtree depth. Inline replacement preserves old content on rejection, detaches derived forests without releasing their logical usage, expires processing receipts, fences outstanding outputs and records object/index cleanup evidence before the next generation. Trash detaches one root, retains charged descendants, fences processing and exposes metadata through independent actions. Restore uses the original live writable parent/name, preserves node identity and rejects occupied destinations, missing parents, concurrent repeats and purging entries.

Downloads independently require `content_read`, resolve live same-filesystem ancestry, preserve optional positive revisions and logical ETags, and return an explicit bytes oneof for empty inline files or a browser signed URL for objects. The metadata snapshot closes before signing. The existing HTTP Range adapter remains staged.

S3 control/signing now uses the pinned AWS SDK with separate browser/internal endpoints, path-style requests, required Content-MD5/Content-Length/If-None-Match binding and disabled SDK retries. Public object uploads implement admission receipts, actor-bound status and capabilities, multipart winner persistence, frozen ordered opaque receipts, HEAD/complete/HEAD reconciliation, exact-once publication, overwrite revalidation and quota accounting, terminal results, abort and signed-transfer cleanup deadlines. Receipt replay reads the original admission before applying new transfer-size/threshold configuration. Publication records the existing processing intent; workflow dispatch and ingest authority variants remain Phase 5.

Generated gRPC handlers execute these application methods over actual authenticated connections. Remaining operations retain generated Unimplemented errors; none return placeholder success, and no Go server is on the running route. Copy/deletion core and server/config composition are now accepted below. Durable dispatch/monitoring, processor authority variants, maintenance, search and ZIP remain Phase 5 work.

## Measured checks

- PASS: native read/path SQL+SpiceDB race-enabled integration (10.944s), including detached raw-ID/alias/cwd denial, read-only ancestry, scoped pagination, atomic batches and graph outage.
- PASS: native creation/move SQL+SpiceDB race-enabled integration (10.134s; fresh helper-refactor run 10.037s). Eight concurrent receipt replays converge; shared-bucket quota and node limits cannot overcommit; exact binary/empty bytes and depth 128 boundaries are checked.
- PASS: native replacement/trash SQL+SpiceDB race-enabled integration (9.022s): quota rollback preserves metadata/artifacts, cleanup honors signed transfer deadlines, detached bytes stay charged, generation/index cleanup is retained, and concurrent restore commits once.
- PASS: real authenticated gRPC application operations (9.250s): exact bytes, int64 max JSON representation, optional metadata/revision, action-specific admission, forged/duplicate/missing actor, nondelegating service, direct-adapter denial, creation/replay/update/replace/trash/restore.
- PASS: complete current Go letfs race-enabled integration run: filesystem 36.131s, gRPC 15.909s, HTTP transport 1.174s; `.local/letfs-go-core-integration.log`.
- PASS: full Go letfs unit race checks, integration-aware vet, gofmt and `git diff --check`.
- PASS: S3 signing/control unit wire checks: bound headers and endpoints, invalid input, sanitized dependency errors, cancellation, one write attempt after a lost response/503, and multipart HTTP-200 error-body handling.
- PASS: real disposable SeaweedFS direct transfers: empty/one-byte/binary PUT, MD5 rejection, immutable candidates, multipart, copy, Range, response overrides, anonymous denial, abort and delete. Initial tests exposed the provider's documented master warmup (three five-second heartbeat intervals); HTTP fixture deadlines now cover that startup behavior. No application retry was enabled.
- PASS: public upload through authenticated real gRPC plus isolated PostgreSQL/SpiceDB/S3: action-specific admission, actor ownership, receipt conflict/replay under changed transfer configuration, six concurrent completions, readback through the application's signed download, successful/stale overwrite, quota rejection without publication, frozen multipart receipts, successful completion with its response deliberately dropped, expiry and abort after bucket freeze.
- PASS: latest complete Go letfs race-enabled integration run: filesystem **39.177s**, gRPC **54.467s**, HTTP **1.170s**, storage **29.260s**; `.local/letfs-go-phase-04-integration.log`. This includes the simplified download implementation and all new upload regressions.

These are core/application and local S3 boundary proofs, not external selected-provider/TLS, workflow, complete-build or runtime acceptance. Rust application source/scripts remain unchanged; its isolated provider fixture now uses the user-selected MinIO image. External provider checks are not run in this slice. No developer database reset, commit, push or deployment occurred.

## MinIO provider replacement

The user selected MinIO instead of SeaweedFS during Phase 4. Both native Go/Rust test fixtures and managed API E2E storage now build the same exact source release from `infra/minio/Dockerfile`. The image runs as UID 65532 and uses native secret-file configuration in Compose. Normal development continues to use its configured external S3 bucket. No existing developer volume was converted or reset.

MinIO community edition is unmaintained/source-only. The fixed release is `RELEASE.2025-10-15T17-29-55Z`, commit `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a`; its build and version check passed. Managed recovery now writes/requires snapshot version 3 and rejects incompatible earlier provider snapshots before effects. Historical SeaweedFS checks above remain previous-provider evidence.

- PASS: MinIO Go race-enabled integration: storage 4.923s, filesystem 52.782s, gRPC 32.308s, HTTP unchanged/cached; `.local/letfs-go-minio-integration.log`.
- PASS: recovery unit tests (12 cases), E2E TypeScript check, Rust formatting, operation-script lint/format and diff whitespace.
- PASS: all 26 Rust reference integration cases (177.99s), all 33 API/recovery journeys (5.8m), and all three environment/recovery checks (102.177s). The first API attempt exposed a missed snapshot-version assertion; corrected to version 3 before the passing run. Logs: `.local/letfs-rust-minio-integration.log`, `.local/api-e2e-minio.log`, `.local/minio-environment-recovery.log`.
- PASS: Rust integration-fixture Clippy with warnings denied; Go integration-aware vet.

Deletion admission and bounded batch core are staged in Go, with local workflow-state methods unexposed publicly until Phase 5 schedules real durable work. Trash admission checks `trash_purge`; full-filesystem deletion verifies the bucket's creating service. Batches retain index/object/processing cleanup before atomically removing leaves and debiting actual quota/node counts, fence uploads and receipts, clear root references and preserve filesystem tombstones.

Copy admission captures the actor, source/parent identity, payload fingerprints, deterministic destination IDs, child upper bounds and job budgets in the existing idempotency receipt. Its local state core recognizes committed effects before source revalidation, counts each unresolved S3 write, revalidates publication after provider I/O, preserves cleanup on quota rejection, enumerates bounded children and records logical-file processing intent with readonly derived forests. Public job RPCs remain unimplemented until Phase 5 adds actual Temporal dispatch/monitoring; staged core admission is not exposed as a fake successful job.

- PASS: deletion race-enabled integration (11.872s), including 70-child batches, concurrent retry, no double debit, foreign-service denial, freeze, upload fencing, cleanup and retained tombstones; `.local/letfs-go-deletion-integration.log`.
- PASS: copy admission race-enabled integration (9.289s), including six simultaneous receipt replays, separate source-read admission, changed limits, quota/node non-mutation, source revisions and immutable replay; `.local/letfs-go-copy-integration.log`.
- PASS: copy publication race-enabled integration (latest 14.007s), including exact empty/binary payloads, captured child bounds, derived-forest provenance, one processing generation, replay after source changes, purged-result non-resurrection, lost S3 copy response with retained open-write evidence, and known quota-rejected write cleanup; `.local/letfs-go-copy-state-integration.log`.
- PASS: combined Go integration after core copy/deletion additions: filesystem 84.262s, gRPC 40.759s, unchanged storage/HTTP reused; `.local/letfs-go-phase-04-integration.log`. The later derived-forest test also passed separately.

## Final composition and acceptance

The staged `cmd/server` composes the actual Go store, S3 client, shared telemetry/PG tracing, native gRPC authentication/TLS, real filesystem/admin handlers and dependency readiness. Gateway credentials can invoke filesystem unary/stream methods; the Workspace credential can invoke only generic administration. Startup and health verify the versioned SpiceDB schema/role policy without repair. Bounded graceful shutdown owns the listener/server/connections. Go execution is not selected by any existing deployment.

Config preserves native storage defaults/bounds, validates endpoint trust, distinct service credentials, PostgreSQL and TLS configuration, and respects secret-file precedence without falling back from unreadable files. The new Go commands and workspace dependency are wired in the app manifest, lockfile and CI while retaining Rust tasks.

- PASS: final complete Go race-enabled integration: composition 16.836s, config passed, filesystem 69.790s, gRPC 32.968s, storage 4.767s, unchanged HTTP reused; `.local/letfs-go-phase-04-final.log`.
- PASS: fresh composition/config after the final configuration adjustment: 9.542s / 1.012s; `.local/letfs-go-composition-integration.log`. Startup rejects missing role policy; real owner/public RPCs enforce distinct allowlists and graph admission; health reports NOT_SERVING on policy drift without repairing it; cancellation drains the server.
- PASS: native Go unit checks, integration-aware vet, gofmt, staged binary build and E2E TypeScript check. Native stream-allowlist regression passes.
- PASS: Rust reference unit tests (14), integration tests (26) and telemetry integration (1), formatting and fixture Clippy with warnings denied. No Rust application/runtime source was changed.

Phase 4 is complete for its isolated core/storage scope. Copy/purge API job responses remain generated Unimplemented until Phase 5 supplies actual Temporal dispatch/monitoring; they never report fake workflow success. Ingest authority variants, workflow dispatch/reconciliation, search and ZIP retain their Phase 5 ownership. Full migration acceptance and runtime adoption are still pending; external selected-provider/TLS checks are not claimed.
