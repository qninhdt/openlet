# Processing implementation evidence

Plan: [Direct Storage, Artifact Processing, and ZIP Export](../261029-1624-artifact-file-processing/plan.md), Phase 3. Date: 2026-10-30.

## Delivered

One Rust `ProcessFile` workflow schedules exactly one Python `process_file` activity. Python registers no workflows and has no database or long-lived S3 credentials. Upload publication commits source identity and processing intent together; post-commit dispatch and bounded existing maintenance reconcile workflow starts and terminal attempts.

Generation plus invocation UUID fences source access, output sessions, publication and abort. Shared upload logic supports bounded inline, conditional object PUT and native multipart. Output sessions do not consume an ordinary outstanding-job slot each. All children and aggregate quota commit in one transaction, with no partially visible tree or source revision change. More than sixteen outputs, retries after committed publication, stale attempts and quota rejection have real dependency tests.

The locked activity-only image contains offline Docling models. A supervised CPU child converts local PDF/DOCX/PPTX/XLSX files into the accepted Markdown/CSV/image layout. The parent owns HTTP, direct storage transfer, heartbeat, cancellation and scratch cleanup. Container and child resource bounds remain enabled.

## Verification

- Full Python suite: **12 passed**, including all four real parsers, actual supervised conversion, child cancellation/output-limit reaping, committed-result reconciliation, redacted terminal errors and shutdown versus requested-cancellation behavior.
- `make test-integration SERVICE=letfs TEST=artifacts`: **5 passed** with real Testcontainers PostgreSQL, S3 and Temporal. Rust application code is unchanged since this run. Coverage includes twenty inline outputs plus an object output under one ordinary outstanding-job slot, stale attempts, readonly children, atomic quota refusal and existing hybrid lifecycle cases.
- Final `make test-e2e TEST=processing`: passed through real Envoy, Workspace, Rust Temporal workflow, Python container and SeaweedFS. **PDF, DOCX, PPTX and XLSX all passed**, preserving exact original bytes, expected child content and readonly behavior. The harness also passed readiness, gateway, provisioning, rate limits, database isolation, node counts and service restart checks, then removed its containers.
- `make test-workflow TEST=process-file`: passed SDK replay of the **four histories from that E2E run**; each history contains exactly one scheduled `process_file` activity on `openlet-letfs-processing`.
- Final `make verify`: passed formatting, Go/Rust/Python unit checks, vet, clippy, configuration, contracts and shell syntax. A separate post-E2E contract check validated **511 captured response DTOs**.
- Changed documentation links resolve. Backup script syntax passes; a coordinated backup/restore drill was **not** run for this change.

Evidence remains under ignored `.local/`: `processing-python-tests.log`, `processing-integration.log`, `processing-e2e.log`, `processing-replay.log`, `processing-verify.log`, `processing-contracts.log` and real histories under `test/histories/`.

Local verified worker image ID: `sha256:1655b809d78d9d168a31df6a4cd79893aadeaf140c02f4b3a12a0ecbe84ecc2e`. This is a local image identity, not a published registry digest or production deployment claim.

## Review and repairs

Inline review followed Ponytail's correctness, trust-boundary, resource-lifetime and minimal-change rules, comparing existing files with `.local/implementation-baseline/pre-processing.tar.gz` because the repository has no Git HEAD. It traced processor-only HTTP authentication, source/attempt ownership, shared upload completion, aggregate publication, stale cleanup, workflow retry and child supervision. This is not an independent release review.

Real container execution found a malformed YAML flow sequence: unquoted tmpfs options became separate mount paths. Quoting the single mount fixed startup without changing hardening.

The minimal child environment also lacked `HOME` and `USER`. Docling failed at `Path.home()`, and the PDF PyTorch import failed at `getpass.getuser()` for UID 65532. `HOME` now points at per-job scratch and `USER` is a fixed non-secret value. No caller environment or credentials are inherited. Environment assertions, real container conversion and E2E cover the repair.

SDK ActivityEnvironment tests reproduced a separate bug: worker shutdown called the terminal processing abort path. Abort now runs only for explicit requested cancellation. Shutdown/timeout leaves the operation retryable; supervision still reaps the child and cleans scratch. The regression failed before the repair and passes afterward.

Local backup now stops and checks the Python worker, and the documented source-resume command includes it. Full capability-aware backup/restore acceptance remains in Phase 5.

## Remaining work

Phase 4 ZIP export and Phase 5 complete recovery/operations acceptance remain pending. Real parser fixtures are deliberately small; large-document bounds, worker SIGKILL during a real conversion, processing-aware coordinated recovery, export behavior and independent final review must not be claimed from these checks. External R2 coordinated object-plus-five-database recovery is still **NOT RUN**. Two upstream Docling/Pydantic deprecation warnings remain; no checks were disabled.
