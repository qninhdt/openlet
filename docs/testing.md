# Testing strategy

Status: native service integration uses Testcontainers; system E2E/recovery uses Compose; see [setup](setup.md) for commands and [operations](operations.md) for external checks. Use the lowest reliable layer that proves an application invariant; test doubles cannot replace verification of real storage/recovery behavior.

## Four groups

| Group | Environment | Responsibility |
|---|---|---|
| Unit | No infrastructure | Validation, path/name logic, role rules, checked arithmetic, transfer protocol shapes |
| Integration | One service and real relevant dependencies | SQL/transactions, HTTP contracts, storage and trust boundaries |
| Workflow | SDK test environment plus selected real Temporal tests | Decisions, timers, retry, determinism, persistence and recovery |
| System E2E | Public HTTP through real Envoy/Compose stack | A small set of complete backend journeys |

Security, concurrency, contract, recovery and efficiency are scenario categories, not extra frameworks. No arbitrary coverage percentages, test-count targets or unmotivated load/soak suite.

## Required checks

| Risk | Lowest reliable proof |
|---|---|
| Gateway | Real Envoy/test JWKS: bad issuer/signature/expiry, missing claim, bootstrap restrictions, spoofed/duplicate trusted headers, internal route isolation |
| User | Real PG uniqueness, repeat onboarding, lost provisioning response, Clerk failure then success |
| Workspace | Real PG role/Owner transactions, concurrent transfer/removal, invite expiry/revoke/email mismatch, Owner-role rejection and replay after removal; member summaries exclude self-only fields |
| Tree | Real PG sibling uniqueness, same-FS parent, cycle prevention, path traversal, mount/cwd escape and ID ancestry |
| Data | Exact bytes/line endings, caller-selected arbitrary inline bytes, direct object transfer, stale overwrite preserves old data, path replacement with equal revision rejects old expected target/parent ID |
| Artifacts | Hybrid paths/cwd/root aliases, raw-ID readonly enforcement, snapshot inclusion/exclusion, source/ancestor lifecycle, detached forest cleanup and exact quota |
| Quota | Competing writes cannot overcommit; finalize/copy/purge retry cannot double-account; trash remains charged; repeated direct purge never debits twice |
| Trash | Restore/purge race, hidden descendants by ID, missing parent/name conflict, Viewer denied, commit then response loss, delayed old trash after restore and delayed old restore after re-trash |
| Copy | Coherent item revision, source ID copied once, documented concurrent-source outcomes, staging invisibility and atomic quota/publication, self/descendant rejection, finite traversal under continuous additions and configured job ceilings |
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

SDK tests cover branches, retry classifications, timers and replay. Real Temporal tests cover worker/server restart, commit followed by response loss, checkpoint continuation and failed-copy cleanup. SDK activity mocks do not prove storage recovery. File bytes stay out of history.

E2E journeys: onboarding and fresh identity; invitation/roles; text ID/path edit/read; upload/finalize/download and quota rejection; trash/restore/purge; copy/usage; permanent workspace deletion with physical cleanup. Most use a local test issuer for reproducibility; live Clerk smoke is labelled separately. Chromium exercises the direct S3 upload/download and CORS contract without a frontend.

## Processing recovery

`make test-e2e TEST=processing-recovery` blocks the actual S3 source GET, kills the Python worker, restarts it and releases the transfer. It requires a higher processing generation, one complete child tree and unchanged source/output bytes. A second case fails source GET through all three activity attempts, then verifies maintenance records terminal failure without children or source changes. Comprehensive E2E includes both journeys; comprehensive replay requires `ProcessFileRecovery` and `ProcessFileExhausted` histories. Child-process cancellation and output-limit reaping are covered by real local subprocess tests.

## ZIP verification

`make test-integration SERVICE=letfs TEST=zip-export` checks original-only traversal,
explicit artifacts, empty roots, Unicode/name collisions, ZIP64 across native
multipart parts, stale/changed inputs, failed-publication races, admission/output
limits, expiry, Range and cleanup. `make test-e2e TEST=zip-export` uses the public
Workspace facade and real Python-generated artifacts. Go's independent ZIP reader
checks the Rust-produced archive's paths and bytes. `make test-workflow
TEST=export-archive` replays the recorded native history and requires one activity.
A source-GET barrier test renames an input during attempt one, requires generation two, and independently verifies the current filename and bytes. Replay checks both `ExportArchive` and `ExportArchiveRetry` histories. Comprehensive `all` routes include these suites.

## Placement and execution

Go: standard `testing`/`httptest` near packages, with Testcontainers-Go integration tests gated by the `integration` build tag. The shared PostgreSQL fixture is in `tests/testinfra/`. Rust: `cargo test`, module unit tests and a Testcontainers-Rust integration binary in `services/letfs/tests/integration.rs`, explicitly selected by the integration target. Both use fresh containers, dynamic ports and the real backup/migration script. Rust integration defaults to two concurrent fixture cases via the standard `RUST_TEST_THREADS` setting; each case owns three dependency processes. The letfs S3 fixture uses a 256 MiB tmpfs; persistent-storage recovery stays in the Compose suite. No development database or Clerk/R2 credentials are loaded. Docker absence fails the requested integration run.

Workflow tests stay with their owner; system tests in `tests/e2e/` retain the Compose harness for real gateway, cross-service, restart, backup and replay coverage. Run `make test-e2e TEST=all` to capture workflow histories. This separates service-level database/storage checks from complete application journeys without removing existing scenarios.

`make test-integration SERVICE=letfs TEST=artifacts` selects real PostgreSQL/S3 tree, readonly, lifecycle, copy snapshot, accounting, stale-processing-attempt and atomic output-publication tests. Its privileged fixture attaches published children to isolate filesystem behavior from parser execution. `TEST=all` includes these cases. `make test-e2e TEST=processing` runs real Rust → Temporal → Python → letfs/S3 conversions for PDF/DOCX/PPTX/XLSX, captures their histories, and checks original bytes, artifact content and readonly behavior. `make test-workflow TEST=process-file` replays all four histories and requires exactly one scheduled Python activity per workflow.

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

Make targets: `test-unit`, `test-integration`, `test-workflow`, `test-e2e`, `test-recovery`, `test-provider`, `test-clerk`, `verify`. They select native suites, not a new runner. Fail if a requested suite selects zero cases. Credential-dependent smoke reports not-run distinctly, never silent success. Test project/databases/object namespace are separate and guarded against development/production targets.

PRs run unit tests, compilation, lint and relevant integration/workflow checks. Shared HTTP/auth/infrastructure changes also run a small E2E smoke. Storage/workflow lifecycle changes run the relevant recovery checks. Release acceptance includes critical E2E/recovery, actual Clerk/provider smoke and isolated metadata/object backup restore using the selected provider procedure, with all direct/durable writers blocked and drained. Expensive performance experiments need an explicit workload/question and threshold.
