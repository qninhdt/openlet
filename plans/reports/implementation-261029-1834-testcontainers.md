# Testcontainers service integration

Completed the authorized separation: `make test-integration` uses Testcontainers-Go 0.44.0 and Testcontainers-Rust 0.28.0; Compose retains system E2E/recovery. No production handlers, migrations or storage provider were changed.

## Scope and evidence

- User integration: concurrent first login converges on one identity and initial workspace; UUIDv7, completion retry, active profile persistence, summaries and invalid avatar rejection.
- Workspace integration: provisioning replay/fingerprint, verified invitation acceptance, ownership transfer/removal, revision checks, deletion admission replay, concurrent owner workspace limit.
- letfs integration: ID/path equivalence, stale revision/expected-ID rejection, sibling conflict, path escape/foreign filesystem denial, shared hard quota across filesystems and trash accounting. Exact inline/binary/6 MiB multipart upload bytes, finalize replay, ranges, terminal transfer denial, actor binding and node/accounting reconciliation.
- Dependencies are created by the tests with dynamic ports. PostgreSQL runs the production backup/migration script against fresh disposable databases. Fixtures do not accept development database or Clerk/R2 credentials. Requested runs fail if Docker is unavailable or no tests are selected.
- The Rust App has a concrete Temporal client, so its fixture starts a real in-memory Temporal dev server. No workflow persistence or recovery claim is made by that fixture. The S3 fixture uses a bounded 256 MiB tmpfs; persistent-storage recovery remains in Compose.

Verification: User and Workspace final integration runs passed through the new Make entry point; letfs final `make test-integration SERVICE=letfs` passed. `make verify` passed, followed by final formatting, Go integration vet and Rust integration clippy checks after simplification. `make test-e2e TEST=foundation` passed with rebuilt Go services, real gateway/provisioning/rate limits, all twenty forbidden cross-database connections denied, restart/readiness and accounting checks. Invalid selectors fail explicitly. Updated documentation links resolve. All task-owned containers were removed.

## Corrections and review

Initial Rust PostgreSQL readiness observed only stderr while its two startup messages span stdout/stderr; selecting both streams fixed the bounded startup wait. An accidentally duplicated Compose setting was removed before the successful E2E run.

The final repeated letfs run initially failed because host disk space dropped below SeaweedFS's one-percent safety threshold following builds. Its logs showed read-only volume admission and no writable volumes. Isolating disposable S3 data in bounded tmpfs resolved the failure without lowering the provider's safety threshold. Final letfs integration passed afterward.

The skill-required simplifier reviewed the four fixture/test files and made readability-only edits. Controller performed inline review of dependency ownership, command selectors, no-zero-case checks, production Docker build paths, isolation and cleanup. No independent full code-review claim is made.

## Limits

Full system E2E, workflow replay and backup/restore suites were not rerun; foundation E2E was the affected harness/build regression gate, and their scenario code remains intact. Historical plan reports keep the command names used at their execution date; current docs and replay instructions point to `test-e2e`. Real R2 coordinated recovery remains a separate open release prerequisite. AgentWiki publishing was skipped.
