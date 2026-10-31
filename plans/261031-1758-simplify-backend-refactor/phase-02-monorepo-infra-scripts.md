---
phase: 2
title: "Monorepo, infrastructure, scripts, and migration baselines"
status: completed
priority: P1
effort: "3–4 days"
dependencies: [1]
---

# Phase 2: Monorepo, infrastructure, scripts, and baselines

## Goal and mandatory scout

Apply the [accepted repository architecture](../261031-1738-refactor-three-notes/inputs/openlet-architecture-decisions.md), remove every old standalone automation script, and squash application migrations. Re-read manifests, Makefile, Compose, Dockerfiles, migration callers, bootstrap/recovery behavior, and setup docs. Preserve existing user edits to Dockerfiles and docs.

## Target ownership

```text
apps/account/             # Go; renamed from services/user
apps/workspace/           # Go
apps/letfs/               # Rust
apps/letfs-processing/    # Independently built Python app
e2e/                     # Newly written Playwright suite
infra/{compose,config,bootstrap}/
scripts/{bootstrap,operations}/
contracts/  docs/  .github/
```

No empty web app, common/shared framework, speculative Rust crates, or cloud deployment tree. Each app owns its Dockerfile and application migrations. Infra owns wiring; use upstream tooling for Temporal schemas rather than rewriting it as application SQL.

## File inventory

| Action | Files or group | Size | Test impact |
|--------|----------------|------|-------------|
| Move/update | Current Go/Rust applications and processor into the four apps above | Large, mainly paths | Module/import/build paths and native commands |
| Rewrite | Old deploy configuration into infra and app Dockerfiles | Medium | Correct local/E2E wiring without legacy fallback |
| Delete/rewrite | All remaining standalone scripts in scripts/deploy/processor | Medium | No script code copied or moved |
| Modify/create | go.work, native Cargo/uv workspaces and locks, pnpm config/lock, turbo.json, Makefile, CI | Medium | Native execution and task discovery |
| Replace/delete | tests/testinfra module and native integration imports | Small/medium | Minimal app-owned Testcontainers setup |
| Replace | Old application SQL chains with one migrations/0001_initial.sql per app DB | Medium | Fresh installation, no upgrade chain |
| Update | Owning architecture/setup/testing/operations docs and README navigation | Medium | Accurate paths, commands, recovery |

## Steps and execution checklist

- [x] Record actual old→new path mapping and all manifests/Compose/test/doc consumers. Moving production logic is allowed; E2E and scripts must be written anew.
- [x] Move apps and update Go module/import paths/go.work, Cargo workspace/lock, and uv workspace/lock using native conventions. Do not rewrite unrelated business logic for directory aesthetics.
- [x] Pin pnpm/Turbo and verify current supported task discovery. If native-workspace integration is unsuitable, use minimal package manifests declaring native commands. Do not build a polyglot task runner. Native commands must work independently.
- [x] Delete the remaining original scripts: configure.py, configure-test.py, migrate.sh, backup-temporal-schema.sh, test-integration.sh, test-workflow.sh, verify-database-isolation.sh, backup-local.sh, restore-local.sh, requirements-dev.txt. Phase 1 deletes the E2E-related scripts.
- [x] Also remove deploy/postgres/init.sh, deploy/temporal/schema.sh, deploy/temporal/namespace.sh, and processor/prefetch-models.py. Inventory tracked executable/shebang files before closing to catch additional standalone automation. Application Python modules are business code, not blanket script-deletion targets.
- [x] Write only necessary permanent automation from scratch: configuration/secrets bootstrap when native tooling cannot express it, and coordinated backup/restore. No wrappers for build/test/Compose/migrate. If model prefetch remains required, expose an application package command instead of a loose script. No temporary script files.
- [x] Rebuild dev/E2E Compose configuration around existing resource needs. Use native init/migration jobs for database/users/Temporal namespace. Retain separate app database users, private storage, gateway trust rules, and E2E-only fault controls.
- [x] Squash each application migration chain into one baseline matching code at this phase; delete every old SQL migration. Later phases edit this baseline and validate on fresh databases. No backfill, legacy checks, dual schema, or migration preserving operations after final delivery. Do not squash upstream Temporal migration history.
- [x] Update all migration callers together: Compose init jobs, Makefile, Go integration currently using tests/testinfra/postgres.go, Rust tests/integration.rs, and docs. Use native migration tooling, not a replacement custom ledger. Back up existing DB state before schema/data changes; prove a database is new before treating it as empty.
- [x] Place unit/integration/replay with their owning app and native runner. Replace the root shared Go testinfra module with minimal app-local Testcontainers fixtures, then delete its module/imports. Keep meaningful native regression tests; remove tests asserting discarded contracts.
- [x] Makefile stays a thin shortcut; Turbo orchestrates native tasks. Separate unit, integration, replay, and expensive parser execution. Do not cache mutable integration/E2E/recovery runs.
- [x] Add CI invoking commands validated locally, collecting diagnostics and always cleaning owned resources. Update E2E build paths from phase 1, remove obsolete services/deploy paths when unused, and update owning docs. No compatibility symlinks.

## Verification and acceptance

Commands below are planned after workspace creation; confirm exact package/task names from manifests before running. Replace the ellipses with the actual owned paths/targets recorded during the phase scout; they are not executable copy/paste commands as written.

| Scope | Planned native check | Required observation |
|-------|----------------------|----------------------|
| Go unit | go test ./apps/account/... ./apps/workspace/... | Native package tests pass without E2E infrastructure |
| Go quality/integration | go vet on the affected packages; go test -tags integration on the actual app-owned integration targets | Correct scopes, real isolated PostgreSQL and permissions |
| Rust format | cargo fmt --check | Workspace formatting valid |
| Rust quality | cargo clippy --locked --workspace --all-targets -- -D warnings | All current targets compile cleanly |
| Rust tests | cargo test --locked with explicit library/integration targets | Unit and real-boundary scopes remain distinguishable |
| Python dependencies | uv sync --locked | Workspace lock is sufficient, no hidden legacy install step |
| Python quality/tests | uv run --package openlet-processor ruff check ... and pytest with explicit parser/non-parser selection | Current package paths and fixture ownership work |
| Task discovery | pnpm exec turbo run ... --dry=json, verified against the pinned version | Every declared task resolves to a supported native command |
| Runtime | docker compose config/build/up using new config; new Playwright API baseline | Every app builds, dependencies become ready, gateway connectivity works |
| Migrations | Native baseline application against fresh DB, then a repeated migration run | Correct schema/permissions, no duplicated SQL effects |

Do not replace a missing executable by silently using another runtime/version. Discover supported toolchains from manifests and installation first, and report an actual environment blocker if one remains.

### Automation acceptance

Bootstrap must preserve existing valid generated secrets, validate inputs, avoid exposing credentials, and reject unsafe test/dev identity mixing. Backup/restore must retain writer fencing, matching application/Temporal/object recovery points, integrity checks, isolated-target guards, and explicit resume behavior where the current operational contract requires them. One focused behavior test for a meaningful branch is enough; do not mirror every helper implementation in tests.

Preserve the original secret-boundary guarantees explicitly in the rewrite: private output directories (0700 where applicable), secret-bearing generated files readable only by their intended owner/container users, no secret values in diagnostics, and no credentials in committed files. Require HTTPS for external JWT/JWKS/Clerk/S3 endpoints; local plaintext exceptions are restricted to the isolated test network. Reject URL userinfo/query/fragment where the existing contract prohibits them. Fresh bootstrap tests must prove permissions, endpoint validation and preservation of valid secrets; do not reuse configure-test.py.

The new recovery test belongs to Playwright and calls permanent operations automation. It is not another shell test runner. Native OpenAPI tooling plus response assertions replaces the removed contract recorder/postprocessor; do not introduce a schema registry or contract framework for this refactor.

- [x] Native workspaces/locks/build contexts resolve only current paths.
- [x] No old standalone scripts or callers remain; new automation has meaningful validation, errors, cleanup, and focused behavior tests.
- [x] Every application DB has one baseline and correct isolation/permissions.
- [x] The API baseline remains green; outstanding target failures are still reported accurately.
- [x] Backup/restore preserves coordinated recovery semantics rather than only wrapping pg_dump.

## Risk and recovery

If Turbo cannot discover native tasks, correct registration using supported manifests rather than adding an orchestration framework. Do not report recovery acceptance until the phase-6 restore drill proves it. Never remove development volumes as E2E cleanup. Recover reset databases from the matching backup, not by applying a new baseline as an upgrade to an old schema.

Continue to [phase 3](./phase-03-gin-opentelemetry.md).

## Execution inventory and evidence

- Old User → apps/account; Workspace → apps/workspace; Rust → apps/letfs; nested Python processor → apps/letfs-processing. No compatibility symlinks. Imports, configuration, queue, containers, tests and active docs follow the new owners.
- Root Go/Cargo/uv/pnpm workspaces and locks; Turbo 2.11.10 pinned. Minimal app manifests invoke native commands and disable mutable task caching. Discovery verified.
- Dockerfiles preserve the user's compiler, dependency and model cache improvements. Goose 3.29.0 applies app baselines; Temporal retains upstream tooling. Schema flattening used a fresh isolated PostgreSQL container, stopped afterward; developer DBs were untouched.
- One 0001_initial.sql per app DB reflects the current applied schema. Old application structures remain pending the owning phase-4/5 rewrites; no upgrade chain remains. Removed the upgrade-only artifact migration assertion.
- Every original standalone script, shared Go testinfra and deploy tree deleted. New permanent automation: bootstrap configuration and coordinated recovery. No temporary executable files. Bootstrap tests passed 6/6; real recovery validation is in progress.
- Go unit/workflow/PostgreSQL integration passed; Python 65 non-parser tests passed; Rust 13 library tests and all-target Clippy passed. pnpm check passed across apps, E2E and scripts. Container rebuild and four gateway E2E tests passed after moves/baselines.
- CI authored, not remotely executed. Full target API, fresh workflow replay, providers and processing acceptance remain open.

### Foundation gates closed

All 20 Rust integration cases passed using fresh real PostgreSQL/S3/Temporal/Qdrant boundaries. The 11 native parser cases passed after explicitly preparing offline models; the initial missing-model environment failure is recorded in validation.md. Permanent recovery passed its real isolated restore/fencing/resume/integrity test, and environment lifecycle passed 2/2. Full API execution remains honestly red: 4 gateway passes and 22 target-onboarding failures, assigned to phases 4–6.

Fresh business workflow history capture/replay and interrupted-workflow restore remain final acceptance gates as the target workflows replace current contracts. Remote CI and external providers have not run. No current phase-2 artifact claims those checks passed. No developer database was changed.
