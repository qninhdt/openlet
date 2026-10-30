# Identity, collaboration and filesystem implementation evidence

Status: in progress, 2026-10-29. This is an execution record, not a release approval.

## Implemented

- Native Go Temporal onboarding and workspace provisioning; stable internal UUIDv7s, captured policy input, real letfs storage, Clerk field merge, caller-bound admission/results and explicit start policies.
- Profiles, workspace/member pages with one bounded profile batch, locked role changes/ownership, manual email-bound hashed invitations.
- Rust adjacency tree and scoped recursive SQL for ID/path/batch resolution, inline byte-preserving text, conditional rename/move, hard quota, trash/restore, direct file purge and deduplicated inline copy.
- Workspace file facade supplies trusted mapped mount context and authorizes each request. Rust knows no workspace, Clerk or role rules.
- Incremental public/internal OpenAPI describes implemented routes. Object/directory copy, uploads and workspace deletion are not advertised as implemented yet.

## Verified evidence

- `make verify`: formatting, Go tests/vet, Rust unit tests/clippy and config checks passed after correcting one clippy finding.
- `make test-workflow`: native Go SDK tests passed, including post-admission failure-state persistence and completed-onboarding no-recreation.
- `make test-integration TEST=identity-workspace`: real Envoy, PostgreSQL, letfs and Temporal passed onboarding/Clerk outage, metadata preservation, invitations/ownership, closed-before-admission replacement, mismatched original input and a PostgreSQL-lock-barrier ownership recheck.
- `make test-integration TEST=filesystem-core`: first real suite passed exact bytes/ranges, ID/path/batch scope, stale/equal-revision identity guards, cycle denial, trash/restore/copy and shared-bucket quota admission. Expanded role, directory visibility, direct-purge and DB-barrier cases are still being verified.
- Config simplifier and identity simplifier ran with scoped behavior-preserving edits; native Go tests passed afterward. No independent reviewer is claimed.

## Outstanding

- Complete expanded identity/filesystem tests, contract fixtures and incremental acceptance reconciliation.
- Implement phases 4–6 (S3 uploads/durable copy, destructive lifecycle, final integration/operations).
- Live Clerk development smoke, selected external S3 provider and coordinated provider-specific restore are not run without those credentials/provider decisions. Deterministic external-boundary tests are distinct from release smoke checks.
