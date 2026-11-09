---
title: "Phase 18: Deployment wiring, migrations and coordinated recovery"
status: pending
priority: P1
dependencies: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
---

# Phase 18: Deployment wiring, migrations and coordinated recovery

## Overview

Run Leta API/worker alongside existing Openlet services with explicit migration/schema readiness, private RPCs, bounded Redis, observable execution and a complete backup/restore path. Do not introduce Kubernetes, another scheduler deployment or a chat service.

## Current evidence and affected files

| Existing owner | Required update |
| --- | --- |
| `infra/compose/dev.yaml`, `infra/compose/e2e.yaml` | Add Leta DB migration/API/worker and Redis; Workspace private RPC listener; secrets, health and dependency ordering. |
| `infra/config/envoy.template.json` | Public Leta/model/request routes and SSE streaming timeout/buffering; preserve trusted-header/JWT rules. |
| `scripts/bootstrap/configure.py` | Add leta DB/role/URL, leta service token, Redis credential/config and generated model settings reference. Existing secrets remain stable. |
| `scripts/bootstrap/test_configure.py`, `test_graph.py` | Generated wiring, exact schema migration/readiness and startup failure checks. |
| `scripts/operations/recovery.py`, `test_recovery.py` | Add leta to DATABASES and Leta API/worker to writer stop/drain/restore; Redis is disposable, not a backup source. |
| `e2e/setup/environment.ts`, `settings.ts`, `environment.test.ts`, `recovery.test.ts` and `e2e/tests/api/backup-recovery.spec.ts` | Owned resource setup, configuration/secret names, log collection, current histories and restore readiness. |
| `.github/workflows/check.yaml`, root `package.json`, `pyproject.toml`, `uv.lock`, `turbo.json`, app manifests | Locked build/test/workflow/replay commands and CI integration for new package. |
| `docs/{README,architecture,setup,operations,data-model,api-contracts,workflows,testing}.md`, `docs/openlet.dbml`, root README | Update owning product/operations descriptions; link contracts rather than duplicate them. |

Proposed new packaging file: `apps/leta/Dockerfile`; complete the existing worker entrypoint from Phases 1/9 and migration CLI from Phase 3. Add a health CLI only if the supported health route cannot serve container checks. Use existing shared config/RPC/telemetry helpers.

Current bootstrap owns DBs account/workspace/letfs/temporal/temporal_visibility/spicedb. Recovery has an explicit DATABASES/WRITERS list; merely adding a Compose container would omit durable Leta state from backups. Current authz readiness compares the exact schema text and does not overwrite mismatches.

## Implementation steps

1. Build one locked Leta image with API, worker and migration entrypoints; use nonroot user, supported Python/uv versions and workspace package installation. Keep models/provider keys in existing secret/config channels, not image layers. Do not copy agent-lab dependencies or its Deep Agents runtime wholesale.
2. Add a dedicated `openlet_leta` database/role and generated private URL to bootstrap, preserving every existing credential on rerun. Include the database in ownership/recovery manifests and tests. The user waived backup prerequisites for this development-only implementation. Fresh disposable fixtures use app migrations rather than ad hoc domain schemas; the saver compatibility fixture may use its own tiny test-effect table.
3. Use app-owned SQL migrations and an explicit `leta-migrate` command that also runs the pinned AsyncPostgresSaver schema setup/migrations once. API/worker verify required schema/version readiness but never silently migrate at startup. Keep saver migrations owned by upstream setup and domain migrations owned by Goose. Both use their nonconflicting table names in the dedicated Leta database; do not add a search_path adapter.
4. Deploy the human-only identity/claim/header and final resource permission contracts from phases02/04 together. This development rewrite uses fresh canonical SQL/authz schemas, with no legacy conversion CLI, transitional schema, dual headers or backup gate. Tests own fresh isolated environments; do not reset unrelated running stacks. Normal schema startup still rejects mismatches. Remove identity-specific self/owner rebuild calls from recovery.
5. Add Redis with a supported version pinned by image digest during implementation compatibility checks, private network only, authentication and a memory bound (initial 256 MiB). Both contents are disposable, so persistence is not required for correctness; avoid a durable-volume recovery obligation. Set a cache-appropriate eviction policy only after verifying the SDK's TTL behavior and the stream cap/resync tests. Prefer bounded allkeys eviction to unbounded RAM when not all Mirage keys expire. Namespace Mirage cache/index and per-Leta streams separately.
6. Create `leta-api` and `leta-worker` Compose services from the same image. Start one worker process initially with two SDK Worker objects: control queue `openlet-leta`, runner queue `openlet-leta-runtime`, as defined by Phases 1 and 9. Register exactly the six Workflow types and accepted Activities. Local SQL remains on control Workflow workers; runner capacity cannot consume receive/HITL/control slots.
7. Start API/worker only after DB migrations, authz readiness and Temporal namespace readiness. Workspace private RPC and Account/LetFS endpoints must be reachable under explicit method/service allowlists. Redis is required for API/worker startup and readiness. Liveness reflects process health; transient publication failure cannot replay committed effects or prevent required cleanup. No optional stream/cache-bypass startup mode.
8. Set bounded initial concurrency, PG pool sizes, RPC/SQL deadlines, heartbeat/shutdown and Workflow cache limits from Phase 1/9/10 evidence. Count per-active-run advisory lock plus saver connections and normal SQL pool; avoid exhaustively allocating a pool per idle agent. Do not use Postgres transaction-pooling mode for session advisory locks. Publish effective safe settings, not another runtime-budget product.
9. Wire Envoy `/v1/letas`, `/v1/leta-models` and `/v1/human-requests` routes before catch-all. Ensure SSE streams do not inherit a short request timeout; retain heartbeat/idle disconnect bounds, disable response buffering, preserve JWT/header sanitation and set trusted gateway token upstream. Internal RPCs remain private and cannot be reached through public routes.
10. Propagate trace context API→Temporal→Activity→model/tool→RPC with existing telemetry interceptors. Log safe agent/run/request/schedule IDs and error classifications, not prompts, file bodies, answers, tool secrets or hidden reasoning. Record useful bounded metrics for inbox admission, run retries, checkpoints, history rotation, active slots, stream resets/cache misses and native schedule failures. Do not use each ID as an unbounded metric label.
11. Graceful shutdown: stop new admissions, drain control Updates, request runner cooperative yield at checkpoint boundary, release Mirage sessions/PG locks and stop workers. Configure Compose grace period longer than this bounded drain. A forced process kill is handled by checkpoint/Temporal recovery, not a reason to retain orphan sessions.
12. Extend coordinated recovery: block public admission; stop/drain Leta API/worker before temporal/DB snapshots; include domain/checkpointer tables and Temporal schedule/workflow state in the same coordinated capture. Add the nonsecret model catalog and generated Leta/Redis configuration to recovery.py's explicit CONFIGURATION capture/manifest/restore validation. Restore them to the new owned state path, update LETA_MODEL_CATALOG_PATH to that copy and verify every persisted model_id/reasoning_effort choice before reopening; do not depend on the original checkout/state directory still existing. Secrets retain the existing protected credential-source procedure. Restore all DBs and existing blob/index sources into a fenced owned project, rebuild canonical user/Workspace/Leta resource tuples through each owning service, clear Redis, start dependencies/migrations in the approved order and resume workflows. Do not rebuild direct grants from HITL history.
13. Test restore with pending HITL, accepted-but-unsettled grant, paused run continuation, future schedule, box home, compacted context and owner-visible history. Old stream cursors return resync; no assumption Redis contents were backed up. Exclude production credentials and avoid public port collisions through existing deterministic test project ownership.
14. Add Leta to Turbo/CI native build/check/test/workflow/integration and fresh history replay. Preserve sequential integration concurrency to avoid exhausting Docker/PG resources. Update CI deadlines only based on measured new work, not by hiding hangs. Keep paid-model/provider smoke explicit and separate from deterministic local acceptance.
15. Update the smallest owning docs and DBML, in English and below 800 lines each. Remove obsolete statements that Redis/agent execution are not requirements of the completed product, while preserving old plans as historical records. Document model configuration, lifecycle/approval recipient rules, schedule semantics, new API paths, VFS limits/cache and recovery commands.

## Requirements

- [x] API/worker, DB/saver migrations, Workspace RPC and private Redis run through existing Compose/bootstrap patterns.
- [x] Exact SpiceDB schema rollout and recovery preserve owner visibility without resurrecting revoked grants.
- [x] Coordinated backup includes Leta/checkpoints/Temporal schedules and excludes disposable Redis state.
- [x] CI and owning docs cover the completed service without duplicate deployment infrastructure.

## Verification and acceptance

Run narrow bootstrap/recovery script tests first, then build the owned E2E Compose stack. Existing commands include `uv run --locked --package letfs-ingest pytest scripts/bootstrap scripts/operations -q`, `pnpm check:e2e`, and `node --test --test-concurrency=1 e2e/setup/environment.test.ts e2e/setup/recovery.test.ts`. Extend their fixtures; do not bypass existing ownership guards.

- Repeated bootstrap preserves secrets; rendered Compose/Envoy contains all new services/routes and no unintended public RPC/Redis ports.
- Missing migration, wrong schema and wrong service token fail readiness/authorization explicitly; an unavailable Redis fails required startup/readiness.
- Worker stop/restart releases run resources and resumes the same run/checkpoint; no duplicate process is started on a busy port.
- Full owned backup/restore restores Leta, box, files, compacted context, pending/accepted HITL, schedules and public history. No new grant after resource cleanup or duplicate schedule input appears.
- Generated contracts, locked wheels and container builds work without app-local imports from the lab.

## Rollout and rollback

This is a coordinated schema/contract release across Account, Workspace, LetFS and Leta, not independently rolling old/new exact-schema binaries. Use fresh owned development state for the incompatible identity rewrite; the user waived backup and backward-compatibility prerequisites. Retain the existing general recovery feature and add Leta to its coverage. Content conversion must retain binary bytes; do not attempt a destructive down-migration after new writes. If rollback requires old representations, restore the coordinated backup into a separate fenced project and verify it before switching admission.

Stop and remove only resources created by this implementation/test run. No production migration, deployment or live-provider request is authorized by writing this plan.

## Execution checkpoint

See [final acceptance evidence](reports/acceptance.md) for the complete API/recovery regression, exact checkpoint/product-state restore and fresh replay. The [deployment/recovery checkpoint](reports/phase-18-execution.md) preserves earlier increments.
