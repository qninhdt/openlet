# Service integration with Testcontainers

Status: complete. Scope: replace Compose-backed service integration execution with native Testcontainers-Go/Rust suites; preserve existing full-stack E2E/recovery and all assertions. No production behavior, storage provider or service API changes.

## Acceptance

- Each service runs integration tests with fresh disposable dependencies, real migrations, dynamic ports, bounded readiness and cleanup on failure.
- User proves identity uniqueness/retry and active-profile persistence. Workspace proves provisioning replay/admission, invitations and ownership. letfs proves path/revision identity, hard quota and exact inline/object upload behavior.
- `make test-integration` selects native service suites; `make test-e2e` retains the existing full-stack scenarios. Workflow history generation points to E2E.
- New test databases are backed up before migrations. Tests cannot select development databases or external Clerk/R2 credentials.
- Run focused tests, affected checks and full-stack smoke; verify no test-owned containers remain. Document limits honestly.

## Tasks

- [x] Implement Go Testcontainers database fixture and service tests.
- [x] Implement Rust Testcontainers dependencies and letfs integration tests.
- [x] Reconcile Make/scripts/docs and validate selection, cleanup and retained E2E coverage.

No existing migration is modified. Rollback: revert test dependencies, fixtures and command routing together; retained Compose suites remain the system recovery authority.

Evidence: [implementation report](../reports/implementation-261029-1834-testcontainers.md). Provider-specific R2 recovery remains outside this test-harness change.
