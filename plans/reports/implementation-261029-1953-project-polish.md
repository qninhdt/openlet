# Project audit and polish

Scope: audit the existing backend against root `AGENTS.md` and Ponytail, repair
evidenced defects, and preserve the accepted architecture and user decisions.
No dependency upgrades, schema changes or product features were introduced.

## Repairs and evidence

| Area | Defect and repair | Verification |
|---|---|---|
| Gateway | Envoy accepted signed JWTs without `exp`. Require expiration in the native JWT filter. | Real Envoy regression failed before the repair and passed afterward. Field checked against official Envoy 1.37.0 documentation. |
| Profile | A NUL display name reached PostgreSQL and caused an encoding error. Reject it at profile validation. | Real PostgreSQL reproduction, unchanged-profile assertion and public HTTP 400 regression. |
| Paths | A file followed by `/.` resolved as a file. Require a directory for this suffix, retaining existing normalization and recursive SQL. | Real PostgreSQL cases for trailing dot/slash and valid root dots; public HTTP regression. |
| Text size | Inline create/replace could exceed configured maximum file size when it was below the inline threshold. Apply the smaller limit. | Accept four bytes, reject five for both writes, and verify unchanged quota usage. |
| Metadata | Inline copy and upload initialization accepted irrelevant text/batch fields. Reject them before persistence, consistent with durable copy. | Native and public HTTP rejection cases; valid operations still succeed afterward. |
| Verification | Missing/failing `gofmt` could leave `fmt-check` successful; invalid unit-test selectors silently ran nothing. Propagate failures and reject unknown selectors. | Explicit failing/missing formatter and invalid-selector checks; native verification passes. |
| Tool selection | Formatting and workflow targets did not consistently respect selected Go; workflow replay could use cached Go results despite changed external histories. | Use selected GOROOT formatter and Go executable; disable workflow test caching; run both targets with absolute Go path. |
| Test isolation | Exported development JWT settings overrode the Compose test issuer. Fix test identity in test mode. | Configuration regression failed before the repair and passed afterward. |
| Build context | Root dotenv files were not excluded from Docker build context. Add exclusion patterns. | Final ignore-file review; no credential files read or copied into source. |
| Test storage | SeaweedFS's percentage disk floor made the persistent test fixture read-only under host disk pressure. Set a nonzero 512 MiB floor for that fixture. | Diagnosed from storage logs and pinned-image CLI help; full E2E passed after the repair. |

Updated the owning API/setup/architecture documentation and the stale contract
fixture-generation command. Reviewed gateway trust, identity/collaboration,
filesystem/storage accounting and Temporal lifecycle boundaries. Avoided cosmetic
refactors and speculative abstractions where no concrete defect was established.

## Checks actually run

- `GO=/tmp/openlet-tools/go/bin/go CARGO_INCREMENTAL=0 make fmt verify` passed:
  formatting, Go unit tests/vet, Rust unit tests/clippy, configuration regressions,
  OpenAPI schema/reference validation and shell syntax.
- `GO=/tmp/openlet-tools/go/bin/go CARGO_INCREMENTAL=0 make test-integration`
  passed all three services using native Testcontainers fixtures.
- `PATH=/tmp/openlet-tools/go/bin:$PATH CARGO_INCREMENTAL=0 make test-e2e TEST=all`
  passed identity/collaboration, filesystem/query counts, quota, storage/copy,
  lifecycle, rate limiting, isolation and worker/server restart scenarios.
- `python3 scripts/verify-contracts.py --responses` validated 1,334 response DTOs
  after the full E2E run.
- `GO=/tmp/openlet-tools/go/bin/go CARGO_INCREMENTAL=0 make test-workflow`
  passed Go workflow tests/replayers and Rust recorded-history replay.
- After final simplification of the path repair and size-limit error text,
  reran the native `file_input_boundaries` integration regression, `make fmt verify`,
  and `make test-e2e TEST=filesystem-core`: all passed. The final focused capture
  separately validated 301 response DTOs.
- `PATH=/tmp/openlet-tools/go/bin:$PATH CARGO_INCREMENTAL=0 make backup-restore-drill`
  passed against the final revision: coordinated database/object/Temporal backup,
  isolated restore, content verification, paused maintenance and no published
  restore ports. Both test stacks were removed by the harness on exit.

The first full E2E attempt failed because test S3 became read-only under disk
pressure. This was diagnosed and repaired in the fixture, then rerun successfully;
assertions were not weakened. Native regression failures before the associated
fixes established the profile, configuration and file-boundary defects.

Detailed local logs are under `/tmp/openlet-polish-*.log`. They are execution
evidence for this workstation, not portable project dependencies.

## Review and limits

Compared current sources with the saved pre-task archive because all project
files were untracked at entry. The repair changes 21 existing files; no existing
file was deleted. Root instructions, manifests/lockfiles and migrations remain
unchanged. Reviewed the resulting patch and added-line whitespace.
All task-started test processes and containers have exited; retained test volumes
and snapshots remain available for diagnosis. Host disk space remains low (about
1.4 GiB free at completion), which can constrain later builds/test runs.

Source baseline and final source patch:
`/tmp/openlet-polish-baseline-nutm56o9/`. No commit or push was requested.

Live Clerk/R2 smoke and the combined real-Clerk/public-API/R2 upload journey were
not rerun. The R2-specific coordinated object/database recovery release check
remains open; local emulator recovery cannot establish provider recovery.
This audit is evidence of the inspected paths and checks, not a guarantee that
the complete application has no further defects.
