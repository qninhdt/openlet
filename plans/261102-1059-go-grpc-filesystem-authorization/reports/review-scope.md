# Scope and Contract Review

## Findings

### High — Phase 5's atomic ingest rename leaves the native CI job on the removed distribution name

- **Plan location:** `plans/261102-1059-go-grpc-filesystem-authorization/phase-05-go-workflows-ingest-and-search.md:55`, `plans/261102-1059-go-grpc-filesystem-authorization/phase-05-go-workflows-ingest-and-search.md:76`, `plans/261102-1059-go-grpc-filesystem-authorization/phase-05-go-workflows-ingest-and-search.md:99`, and `plans/261102-1059-go-grpc-filesystem-authorization/phase-07-rust-removal-recovery-and-acceptance.md:40`.
- **Failure:** Phase 5 moves the directory and renames the uv distribution to `letfs-ingest`, but `.github/workflows/check.yaml` is not in that phase's inventory and CI cleanup is deferred to Phase 7. The native job will still execute `uv sync --locked --package openlet-processor` after Phase 5 has removed that package, so the branch cannot satisfy normal CI between Phases 5 and 7 despite the phase claiming a complete atomic rename.
- **Source evidence:** `.github/workflows/check.yaml:33` selects `openlet-processor`; `apps/letfs-processing/pyproject.toml:2` defines the current distribution that Phase 5 replaces; `pyproject.toml:2` shows the workspace member that is moved in the same phase.
- **Within-scope fix:** Add `.github/workflows/check.yaml` to Phase 5 ownership and update its uv package name/path (and any renamed package cache inputs) in the same atomic rename. Leave Phase 7 responsible only for removing Rust-specific CI/tooling and final reproducibility acceptance.

### High — Phase 6 renames live worker services but defers the recovery coordinator that its own full API gate invokes

- **Plan location:** `plans/261102-1059-go-grpc-filesystem-authorization/phase-06-direct-filesystem-api-and-proxy-removal.md:51`, `plans/261102-1059-go-grpc-filesystem-authorization/phase-06-direct-filesystem-api-and-proxy-removal.md:76`, and `plans/261102-1059-go-grpc-filesystem-authorization/phase-07-rust-removal-recovery-and-acceptance.md:26`.
- **Failure:** Phase 6 switches Compose services from `processor-cpu`/`processor-io` to `ingest-cpu`/`ingest-io` and then runs the complete Playwright API project. That project includes the backup/recovery journey, but `scripts/operations/recovery.py` remains assigned to Phase 7 and still drains/restarts only the old service names. The Phase 6 recovery test can therefore snapshot while ingest writers remain active and can restore without restarting the renamed workers, violating both backup coherence and workflow-resume assertions.
- **Source evidence:** `scripts/operations/recovery.py:19` defines the writer drain list with `processor-cpu` and `processor-io`; `scripts/operations/recovery.py:455` defines the restored application start list with the same names; `e2e/tests/api/backup-recovery.spec.ts:36` and `e2e/tests/api/backup-recovery.spec.ts:46` invoke that coordinator during the API suite; `e2e/tests/api/backup-recovery.spec.ts:66` requires processing to resume to `ready` after restore.
- **Within-scope fix:** Move the service-name portions of `scripts/operations/recovery.py` and the corresponding recovery assertions into Phase 6's coordinated cutover. Keep Phase 7 ownership for the deeper graph epoch/rebuild drill and final recovery acceptance.

## Unresolved Questions

None.

Status: DONE
Summary: Reviewed the plan-only scope and current consumers; found two high-severity phase-boundary contract failures.
Concerns/Blockers: None.
