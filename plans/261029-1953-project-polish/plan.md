# Project audit and polish

Status: completed. Evidence and verification limits are in the
[implementation report](../reports/implementation-261029-1953-project-polish.md).

## Outcome and constraints

Audit the backend against root `AGENTS.md` and Ponytail. Fix evidenced correctness,
security, resource-lifetime, verification and maintenance defects with focused
regressions. Preserve accepted architecture, public contracts, unrelated work and
development credentials. Do not add features, speculative abstractions or dependencies.

## Work

- [x] Read instructions, accepted architecture, existing plans and test commands.
- [x] Inspect working tree/processes and save a source baseline outside the repo.
- [x] Trace gateway, identity, collaboration, file/storage and Temporal lifecycles.
- [x] Reproduce and fix concrete findings, including affected tests/contracts/docs.
- [x] Run focused checks, native verification, integration and relevant system tests.
- [x] Review changes against baseline and record remaining verification limits.

## Acceptance and rollback

Every repair has a concrete failure case and appropriate verification. No known
regression is hidden by weakened tests or silent checks. Record commands actually
run, failures, coverage limits and release prerequisites in the final report.
No schema change is planned. Test migrations require backups through existing
fixtures. Restore only task-owned edits from the saved baseline if rollback is needed.

Source baseline: `/tmp/openlet-polish-baseline-nutm56o9/source.tar.gz`.
All files were untracked at entry; Git alone cannot identify this task's diff.
