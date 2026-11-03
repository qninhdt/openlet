---
phase: 7
title: "Rust removal, recovery and acceptance"
status: completed
priority: P1
effort: "24-40h"
dependencies: [6]
---

# Phase 7: Rust removal, recovery and acceptance

## Goal and context

Delete the retired Rust implementation and obsolete integration surfaces, prove clean setup and canonical authorization rebuild, and reconcile the smallest owning documentation. Read [architecture](architecture-contract.md), [verification matrix](verification-matrix.md), [operations](../../docs/operations.md), [testing](../../docs/testing.md) and all prior phase evidence.

Dependency: Phase 6 direct Go runtime and all real consumers pass. No old Rust history/data compatibility is required; do not substitute old fixtures as proof of current Go replay.

## File inventory and ownership

| Action | Absolute files | Scope and test impact |
|---|---|---|
| Delete | `/home/qninh/projects/openlet/Cargo.toml`, `/home/qninh/projects/openlet/Cargo.lock`, `/home/qninh/projects/openlet/rust-toolchain.toml`, `/home/qninh/projects/openlet/apps/letfs/Cargo.toml` | Retire project Rust workspace/toolchain |
| Delete after port verification | `/home/qninh/projects/openlet/apps/letfs/src/`, Rust files under `/home/qninh/projects/openlet/apps/letfs/tests/` | Preserve SQL, fixtures and every meaningful parity assertion in Go |
| Verify | `/home/qninh/projects/openlet/packages/python/pyproject.toml`, `/home/qninh/projects/openlet/packages/python/src/openlet_api/`, `/home/qninh/projects/openlet/packages/python/package.json`, `/home/qninh/projects/openlet/apps/letfs-ingest/pyproject.toml`, `/home/qninh/projects/openlet/apps/letfs-ingest/Dockerfile` | Shared generated wheel remains independent of renamed app; clean installs/imports and real RPC, no app-local copies |
| Modify | `/home/qninh/projects/openlet/.github/workflows/check.yaml`, `/home/qninh/projects/openlet/Makefile`, `/home/qninh/projects/openlet/package.json`, `/home/qninh/projects/openlet/turbo.json`, `/home/qninh/projects/openlet/pnpm-workspace.yaml` | No Rust build/check paths; discover shared module and renamed ingest |
| Modify through tooling | `/home/qninh/projects/openlet/pnpm-lock.yaml`, `/home/qninh/projects/openlet/uv.lock`, `/home/qninh/projects/openlet/go.work`, `/home/qninh/projects/openlet/go.work.sum`, app/shared `go.mod` and `go.sum` | Reproducible canonical dependency locks |
| Modify | `/home/qninh/projects/openlet/scripts/operations/recovery.py`, `/home/qninh/projects/openlet/e2e/setup/recovery.test.ts`, `/home/qninh/projects/openlet/e2e/tests/api/backup-recovery.spec.ts` | Fence/drain all projectors/writers and safe graph restore/rebuild |
| Modify | `/home/qninh/projects/openlet/scripts/bootstrap/configure.py`, `/home/qninh/projects/openlet/scripts/bootstrap/test_configure.py`, `/home/qninh/projects/openlet/e2e/setup/environment.ts` | Six database inventory, secrets, schema order and owner-safe reset |
| Modify | `/home/qninh/projects/openlet/e2e/fixtures/temporal-control.ts`, Go replay tests in Account/Workspace/letfs | Export/replay fresh current histories, with Account/Workspace projection histories |
| Modify | `/home/qninh/projects/openlet/docs/README.md`, `architecture.md`, `api-contracts.md`, `data-model.md`, `workflows.md`, `setup.md`, `testing.md`, `operations.md`, `openlet-monolith.dbml` in the same docs directory | Correct current behavior/setup/security/data/operations contracts |
| Create | `/home/qninh/projects/openlet/plans/261102-1059-go-grpc-filesystem-authorization/reports/acceptance.md` | Actual commands, results and material external limits |

Phase file inventory shorthand expands to the absolute parent directory shown. Read every doc before updating; do not rewrite historical reports or journals to pretend the migration existed earlier.

## Implementation steps

1. Review the behavior ledger and final Go implementation against every Rust module/test family. Confirm copy partial progress, byte ambiguity, quotas, tombstones, search readiness and parser regressions have real evidence before deleting the reference.
2. Remove Rust files, Cargo manifests/lockfile and toolchain integration. Preserve language-independent migrations and fixtures. Remove `.cargo` configuration only if it actually exists and belongs to this project. Third-party Python wheels implemented in Rust do not mean project Rust remains.
3. Verify no provision key or business mapping/projector remains in letfs schema/contracts/code. Reject business-service clients/imports, workspace fields in target provisioning, hardcoded drive labels and role headers; generic actor/service IDs and local filesystem invariants remain valid. Verify the complete Phase 6 rename and remove any remaining obsolete active references; this is an audit, not a delayed consumer migration: app path `apps/letfs-ingest`, Python distribution/module, pnpm package, subprocess, wheel, model-prefetch, image/service/config/secret/queue references and doc commands. Internal domain terms such as `processing_status` remain valid; do not mechanically rename every occurrence of “processing.”
4. Run native Go build/check/test tooling for all four modules including `packages/go`; do not use root `go test ./...` without a root module. Keep compatible public Gin handlers and genuine third-party HTTP clients. Remove obsolete private HTTP routes/specs and proxy configuration.
5. Verify the shared `openlet-python` wheel builds independently and the renamed app installs it outside the checkout. The sole generated Python tree remains `packages/python/src/openlet_api/`; no app vendors stubs or imports another app. Ensure uv workspace resolution, Docker copies, Turbo dependencies and codegen drift checks cover this boundary. Update CI to install only required Go/Python/codegen tools, include shared module sums in caches, regenerate/check contracts and run real SpiceDB integration. Remove Rust toolchain/clippy/fmt/build steps and Rust-core-only CMake/native requirements, but retain protoc if selected generation needs it.
6. Complete the deeper graph rebuild/recovery drill using the inventory already updated in Phases 2/3/6 for `openlet_spicedb`, all graph writers and ingest names. Phase 6 must already drain/restart actual renamed workers for its full API gate. Block/drain public mutation and Temporal projectors before capturing a coherent recovery point. Preserve outstanding signed-upload capability/grace checks; a stopped API alone does not stop issued S3 writes.
7. Implement the architecture's fenced graph recovery/rebuild procedure. Verify supported PostgreSQL datastore restore handling for SpiceDB transaction IDs; do not assume a copied DB dump is healthy. Rebuild graph facts from canonical Account/Workspace state and retained storage references; restore letfs storage/lifecycle independently, load repository role/action policy and verify current business relationships before opening readiness.
8. Drill a fresh isolated restore: identities/memberships/roles, exact inline/object bytes, Qdrant state/current filtering, interrupted file workflow and projection. Verify deleted/revoked resources do not reappear, and restarted synchronization derives restored canonical state instead of replaying old role payloads. Stop midway and resume the rebuild to prove convergence.
9. Perform a backed-up development reset only if needed to exercise clean installation. Use the existing owner-safe tool and a matching snapshot; do not issue broad Docker prune or delete another worktree's volumes. Record commands and the restore location without secrets.
10. Update owning docs and DBML from actual schema/contracts. Explain canonical versus derived permission state, direct FS API, action matrix, gRPC identity, timeout semantics, shared PostgreSQL and recovery procedure. Remove stale “five databases,” Rust and processor-package claims from active docs. Historical plans stay historical.
11. Run narrow checks first, then the complete required acceptance sequence below. Record FAIL/NOT RUN separately from PASS. Fix regressions; never weaken assertions or hide omitted scenarios behind an overall success.
12. Update implementation checkboxes and evidence only for work actually completed. AI-agent implementation remains blocked until this plan's required local gates pass. External provider release checks remain explicitly separate.

## Todo

- [x] Confirm all Rust behavior families have current Go evidence before deletion.
- [x] Delete Rust and retire obsolete build/toolchain/private HTTP surfaces.
- [x] Audit the Phase 6 complete ingest rename and canonical locks; no delayed consumer switch.
- [x] Update CI and codegen/shared-module discovery, including independent shared Python wheel and renamed-app dependency checks.
- [x] Extend and test coordinated backup/restore/projector fencing.
- [x] Prove fenced graph rebuild, current-state resynchronization and interrupted recovery.
- [x] Verify backed-up clean setup/reset and updated owning docs/DBML.
- [x] Run required local acceptance and record exact evidence/limitations.

## Verification commands

Existing command entry points to retain and adapt, executed after previous phases have implemented the new scripts/packages:

```sh
pnpm install --frozen-lockfile
uv sync --locked --package letfs-ingest
uv build --package openlet-python
uv build --package letfs-ingest
pnpm --filter @openlet/python check
pnpm --filter @openlet/python test
pnpm --filter @openlet/python test:integration
pnpm build
pnpm check
pnpm test
pnpm exec turbo run test:workflow
pnpm exec turbo run test:integration --concurrency=1
pnpm --filter @openlet/letfs-ingest run test:parser
pnpm check:e2e
node --test --test-concurrency=1 e2e/setup/environment.test.ts e2e/setup/recovery.test.ts
pnpm --dir e2e exec playwright test --project=api
OPENLET_HISTORY_DIR="$PWD/.local/api-e2e/histories" pnpm test:replay
```

Also run the new contract generation/lint/drift checks introduced in Phase 2, and appropriate per-module Go race checks for auth/projector/FS concurrency. Use the model cache documented by the ingest package for parser checks; unavailable required models are NOT RUN, not skipped success. No credentials-dependent provider smoke is implicitly run.

After removing Rust, inspect active-source references with a scoped search rather than treating history/docs research as failures:

```sh
rg -n -g '*.yaml' -g '*.yml' -g '*.json' -g '*.toml' -g '*.py' -g '*.ts' -g '*.go' -g 'Dockerfile' -g 'Makefile' -g '!**/node_modules/**' -g '!**/.venv/**' 'openlet_processor|openlet-processor|letfs-processing|processor-(cpu|io)|PROCESSOR_[A-Z0-9_]+|processor_service_token|cargo[[:space:]]|rust-toolchain' apps packages scripts infra e2e .github package.json pyproject.toml pnpm-workspace.yaml turbo.json Makefile
```

Also search the exact old image, secret, environment and task-queue strings recorded in the Phase 1/5 ledgers; the family scan cannot replace that inventory. Include Buf destinations, recovery start/drain lists and restart fixtures. Expected result: no obsolete active references; investigate exceptions instead of deleting strings blindly. Inspect root Cargo/toolchain file absence independently. A no-match `rg` exit 1 is expected for this cleanup check.

## Scenario matrix and success gate

| Priority | Scenario | Required result |
|---|---|---|
| Critical | Fresh install without Rust | All Go/shared/ingest builds, generators and actual runtime start |
| Critical | Canonical permission commit then crash before dispatch | Reconciliation projects it; no lost grant/revoke |
| Critical | Graph erased/restored; sync work resumes | Writers are drained; policy/current business relations are restored before admission |
| Critical | Restore interrupted workflow and exact S3/inline bytes | Correct continuation and data, no duplicate quota/effects |
| Critical | Concurrent transfer/removal/finalize/purge | Canonical invariants and effective graph permissions remain valid |
| High | Missing/corrupt backup, foreign worktree resources | Fail before destructive action; existing safety behavior preserved |
| High | Fresh Go history replay across Continue-As-New | Deterministic replay with current registered names/queues |
| High | Locked dependencies/codegen drift | Clean reproducible install; regeneration leaves no diff |
| Medium | Active docs/packages/contracts/tool commands | No obsolete routes, language or package names |

Completion requires all required local gates in the verification matrix, no unresolved critical/high regression, no hidden skipped acceptance, and a clean scoped diff. A plan-authoring check is not an implementation test.

## Risks, security and rollback

Shared PostgreSQL is a shared resource/failure domain; keep connection budgets and readiness explicit. Restored SpiceDB data must be repaired/rebuilt before permission checks become available. Invalid or unavailable graph checks fail closed without SQL-role fallback.

Rollback uses an isolated verified snapshot with a matching checkout/dependency/schema set. Do not run old Rust against the new baseline or use old histories as compatibility proof. Missing real Clerk/provider credentials are reported as external release limits, not blockers manufactured for this local migration. Stop owned processes/containers on completion and retain only the intended development environment.

## Acceptance evidence

Completed local gates and external limits are recorded in [acceptance](reports/acceptance.md). Fresh Go native and complete API histories replay successfully. The graph-erasure/interrupted-rebuild drill and independent environment/recovery tooling pass; all owned test resources were cleaned up.
