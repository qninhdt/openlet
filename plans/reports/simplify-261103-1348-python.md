# Python shared services and letfs-ingest simplification

Date: 2026-11-03, Asia/Ho_Chi_Minh

## Delivered

- Replaced the app-local `jobs.py`/`activity.py` boundary with `letfs_ingest.temporal.activities`; the worker owns one shared RPC channel and injects a native processing client.
- Split parser, processing and provider clients by real responsibility. Parser and processing contain no protobuf, gRPC or Temporal imports.
- Moved the ingest RPC adapter and remote contract models into `openlet.clients.letfs.ProcessingClient` with native immutable DTOs. Idempotent processing operations explicitly retain the proven three-attempt transient retry; generic shared RPC calls make one attempt.
- Added native shared Account, Workspace and letfs clients. The letfs surface covers all current RPCs: 27 Filesystem, 8 Storage Administration and 15 Ingest methods, with native immutable DTOs and no protobuf values in public results.
- Added bounded filesystem path contexts with a root mount default, native upload destination/replacement variants and response-scope validation for filesystem, node, search, bucket and ID-bearing results.
- Added shared identity/gateway verification, authenticated RPC client/server primitives, allowlists, explicit actor delegation, deadlines, trace propagation, safe gRPC error details, RFC 9457-style problem responses, file-backed secrets, Authzed Check/BulkCheck, telemetry and Temporal client setup.
- Promoted the existing worker telemetry implementation into the shared package rather than duplicating it. Worker configuration is now validation-only and does not dial services.
- Added static import-boundary tests, shared platform behavior tests, native real-gRPC retry/error tests, worker lifecycle/failure-budget tests and isolated wheel assertions.
- Added an actual shared Python gRPC server/client boundary test covering duplicate credentials, duplicate actors, spoofed service identity, required gateway actor, forbidden delegation, method allowlists and safe structured application errors.
- Wrapped every Python gRPC server cardinality (unary, server-streaming, client-streaming and bidi) with the same authenticated principal, trace context, bounded deadline and safe error contract. Denials preserve the requested cardinality; native aborts are not rewritten.
- Preserved structured transient server reasons after the final explicit retry and added `OUT_OF_RANGE` parity instead of collapsing either case to a generic dependency failure.
- Added Authzed Check/BulkCheck regressions for response reordering, strict request matching, per-item dependency failure and cancellation preservation without leaking provider details. The official client uses TLS by default, explicit plaintext for local testing, two-second call deadlines and caller-owned cleanup.
- Added real wire tests for filesystem path-context streaming, storage creation/scope validation and the explicit plaintext Authzed boundary, plus a descriptor contract test that requires native methods for every current letfs RPC.
- Updated the lock with `authzed==1.25.0` and promoted reusable Temporal/OpenTelemetry dependencies into `openlet-python`.

## Verification

- `ruff format` and `ruff check` over handwritten shared Python, letfs-ingest and their tests: passed; 54 files were already formatted.
- `pnpm --dir packages/python check`: passed; the package check now covers handwritten `src/openlet` and tests while excluding generated `openlet_api`.
- shared Python suite, including actual unary/streaming gRPC, Authzed, letfs client wire tests, shared VectorSpace validation and early stream cancellation: 21 passed.
- letfs-ingest suite excluding parser-marked offline cases: 100 passed, 11 deselected.
- `git diff --check`: passed.
- Static searches and AST regressions confirm processing/parser do not import protobuf/gRPC/Temporal and handwritten shared code does not import the app.

## Final controller verification

- The duplicated processing `VectorSpace` model was removed; shared clients and indexing now use one native type with validation. The real Python processing/enrichment/index/replay integration passed after this correction.
- Closing an archive iterator explicitly closes its nested iterator and cancels the underlying RPC. A real blocked-server regression failed before the fix and passed afterward.
- Offline model artifacts from the current Docker image enabled all parser/OCR-marked cases: 11 passed, 100 deselected. The ordinary application suite separately passed all 100 nonparser cases.
- Full cross-service integration passed through the root Turbo integration target. Final system E2E/replay evidence is tracked in the service refactor verification record.

Status: DONE
Summary: Python application boundaries and complete shared clients are implemented and verified with native DTOs, explicit retry/auth semantics, deterministic stream cleanup, real processing/replay and offline parser/OCR tests.
Concerns/Blockers: Live external-provider acceptance remains an operational check; system E2E results belong to the controller verification record.
