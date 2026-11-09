---
title: "Phase 01: Dependencies and service foundation"
status: complete
priority: P1
effort: 12h
dependencies: []
---

# Phase 01: Dependencies and service foundation

## Outcome and boundaries

Create the Python Leta application, its validated configuration and owned resources, and lock the accepted upstream engine combination before domain implementation. API and worker are separate processes in one package/image. This phase adds no product workflow, fake endpoint, database domain table, model-call budget, polling reconciliation service, or alternative agent engine. Human migration is phase 02, domain schema phase 03, runtime phases 09–10 and deployment phase 18.

Acceptance means the package builds independently, configuration rejects invalid authority/model settings, resource initialization/cleanup is testable, and a bounded compatibility test proves the actual upstream APIs without paid inference. The accepted `create_agent` factory remains the graph runner; no wrapper engine or DeepAgents migration is introduced.

## Read first and current evidence

- [Accepted workspace-resource design and all review decisions](../reports/design-261108-0148-leta-workspace-resource.md), plus [canonical execution rules](design-contract.md).
- [Current implementation/source inventory](research/service-contracts.md).
- `/home/qninh/projects/openlet/pyproject.toml`, `uv.lock`, `pnpm-workspace.yaml`, `turbo.json`, `packages/python/pyproject.toml` and `apps/letfs-ingest/{pyproject.toml,package.json}`.
- `/home/qninh/projects/openlet/packages/python/src/openlet/{identity.py,rpc.py,authz.py,httpapi.py,telemetry.py,temporal.py}` and `packages/python/tests/{test_wheel.py,test_rpc_wire.py}`.
- `/home/qninh/projects/openlet/apps/letfs-ingest/src/letfs_ingest/{config.py,worker.py}`, `docs/{architecture.md,setup.md,testing.md}`.

The uv workspace now contains `leta`, ingest and `openlet-python`, using Python 3.14.10 and Temporal 1.35.0. Phase01 implementation and compatibility evidence are recorded in its execution report. The later repository-wide upgrade updates the pins below and reruns compatibility gates; earlier results do not establish acceptance of the changed dependency set.

## Fixed contracts

| Concern | Contract |
| --- | --- |
| Package | Directory `apps/leta`; Python distribution/module `leta`; pnpm package `@openlet/leta`; shared dependency `openlet-python` from uv workspace. |
| Processes | `python -m leta.api` and `python -m leta.worker`; API owns HTTP commands/queries/SSE, worker owns Temporal and runtime effects. |
| Storage | A separate `openlet_leta` application database with app migrations and upstream checkpointer tables. No identity/Workspace/LetFS database credentials or cross-service SQL joins. |
| Temporal | Existing SDK 1.35.0 and namespace; queues `openlet-leta` for coordination and `openlet-leta-runtime` for run_agent. Real registration lands in phase 09. |
| Identity | Trusted gateway principal for HTTP; Leta service credential plus explicit delegated actor for native downstream calls. Closed user/leta native actor; Leti uses root resource subject leta:L and never receives a user/member/token. Phase 02 updates existing shared helpers; phase 04 supplies owning contracts. |
| Model config | Server-owned catalog of model IDs and supported reasoning_effort values. Owner selects one allowed pair for Leta; only owner APIs configure Leti overrides, otherwise root inheritance. No arbitrary model/effort from tool input and no per-run model-call budget. |
| Streaming/cache | One Redis deployment with separate namespaces and clients where needed. Stable per-Leta stream/reconnect/coalescing defaults are owned by [phase 16](phase-16-redis-agui-streaming.md); Redis service pin/wiring is owned by [phase 18](phase-18-deployment-and-recovery.md). |
| Lifecycle | FastAPI lifespan and async context managers own pool/client lifetime. Close resources after partial initialization, cancellation and SIGTERM. Never keep one Mirage session per idle agent. |

Config fields: `LISTEN_ADDR`, `DATABASE_URL`, `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `REDIS_URL`, `GATEWAY_TOKEN`, `LETA_SERVICE_TOKEN`, `ACCOUNT_RPC_ADDRESS`, `WORKSPACE_RPC_ADDRESS`, `LETFS_RPC_ADDRESS`, `RPC_LISTEN_ADDR`, `WORKSPACE_SERVICE_TOKEN`, `SPICEDB_ADDRESS`, `SPICEDB_GRPC_PRESHARED_KEY`, `ALLOW_PLAINTEXT_RPC`, existing OTEL settings, provider endpoint/key, and the catalog file path `LETA_MODEL_CATALOG_PATH`. Secrets support the existing `_FILE` convention. Require verified TLS except an explicit private-test/development plaintext setting. Keep provider credentials and selected model prompts out of logs/errors.

The JSON catalog contains `models:[{model_id,reasoning_efforts,context_window_tokens,max_output_tokens}]` and `default:{model_id,reasoning_effort}`. model_id is the exact configured provider model identifier; do not add an internal alias or a second field naming the same model. Validate unique IDs, supported efforts (explicit null/default only when configured), selected/default pairs and positive token counts with output below context. Those counts support compaction/request sizing, not a product model-call budget. Loading/catalog readiness never performs inference. Initial provider adapter is OpenRouter; credentials/endpoints are private and not part of choice DTOs.

## Files to create or modify

| Action | Absolute path | Purpose |
| --- | --- | --- |
| Modify | `/home/qninh/projects/openlet/pyproject.toml` | Add apps/leta uv workspace member. |
| Modify | `/home/qninh/projects/openlet/uv.lock` | Resolve and lock actual accepted app dependency combination. |
| Create | `/home/qninh/projects/openlet/apps/leta/pyproject.toml` | App dependencies, wheel config, pytest markers and Ruff settings. |
| Create | `/home/qninh/projects/openlet/apps/leta/package.json` | Native build/check/test/integration/replay commands and @openlet/python edge. |
| Create | `/home/qninh/projects/openlet/apps/leta/src/leta/__init__.py` | Package boundary. |
| Create | `/home/qninh/projects/openlet/apps/leta/src/leta/config.py` | Environment/secrets/catalog parsing and typed settings. |
| Create | `/home/qninh/projects/openlet/apps/leta/src/leta/lifespan.py` | Own pool, downstream RPC clients, Redis, Temporal and telemetry lifecycle. |
| Create | `/home/qninh/projects/openlet/apps/leta/src/leta/api.py` | FastAPI app factory, identity/error boundary, live/ready and entry point. |
| Phase 09 | `/home/qninh/projects/openlet/apps/leta/src/leta/worker.py` | Deliver the real entrypoint together with registrations/polling; no nonfunctional stub in phase01. |
| Create | `/home/qninh/projects/openlet/apps/leta/tests/conftest.py` | Isolated dependency fixtures with owned teardown. |
| Create | `/home/qninh/projects/openlet/apps/leta/tests/test_config.py` | Config/catalog/secrets rejection and selection tests. |
| Create | `/home/qninh/projects/openlet/apps/leta/tests/test_lifespan.py` | Partial startup, health, cancellation and cleanup tests. |
| Create | `/home/qninh/projects/openlet/apps/leta/tests/test_engine_compatibility.py` | Small real-factory/saver/Mirage/AG-UI compatibility gate. |
| Modify | `/home/qninh/projects/openlet/packages/python/tests/test_wheel.py` | Build Leta wheel and prove shared package ownership. |

Do not edit infra/Compose or database migrations here. Queue registrations and engine DTO/store files belong to phases 03/09–13. Operational docs/config examples land with phase 18 wiring; avoid documenting an already runnable service before it exists.

## Detailed implementation steps

1. [x] Confirm workspace/toolchain scope.
   1. Read current package scripts/image runtime; use uv and pnpm while preserving existing service dependencies.
   2. Verify Python3.14.10 and deployment-architecture Mirage/Monty wheel support. Do not patch dependency source or silently choose an alpha release.
   3. Keep engine dependencies app-owned. Add the app to uv workspace; pnpm apps/* already discovers it.
2. [x] Resolve the accepted stack and lock versions.
   1. Pin `langchain==1.4.9`, `langgraph==1.2.20`, `langgraph-checkpoint-postgres==3.2.0`, `mirage-ai[monty,redis]==0.0.8`, `ag-ui-langgraph==0.0.47` and `langchain-openrouter==0.2.9`; preserve shared `temporalio==1.35.0`. Mirage Monty pins `pydantic-monty==1.4.0`.
   2. Add FastAPI/Uvicorn, `psycopg[binary,pool]`, Redis asyncio client and needed FastAPI telemetry only. Resolve compatible stable versions with uv, inspect installed metadata/types, pin chosen direct versions and keep transitive hashes in uv.lock.
   3. Respect Mirage0.0.8 minimums: Python>=3.12, FastAPI>=0.135.1, Uvicorn>=0.41.0, OTel API>=1.45.1. Reconcile with existing OTel SDK1.45.2 without unrelated upgrades.
   4. Do not install Mirage all/OpenAI/DeepAgents extras. If resolution fails, isolate conflicting constraints and stop dependent work; do not replace the accepted engine silently.
3. [x] Establish commands and independent wheel boundary.
   1. Define build as `uv build --package leta`; check as app Ruff check/format; test as pytest excluding integration/replay; test:integration as pytest integration; test:replay as pytest replay.
   2. Register markers, async fixture mode, supported Python range and wheel package src/leta using the existing Hatchling pattern.
   3. Extend wheel tests: Leta depends on openlet-python and contains no generated openlet_api tree. Install into a temporary environment and import with python -I without repository PYTHONPATH.
4. [x] Implement typed settings/catalog.
   1. Parse `_FILE` secrets without logging values; reject invalid DSNs/addresses/tokens and conflicting TLS/plaintext settings using platform patterns.
   2. Reject duplicate ids, empty reasoning choices, missing/unknown defaults, malformed provider settings and invalid selected pairs. Loading never calls a model.
   3. Provide one effective selection resolver: root explicit/default pair; Leti override or current root pair. Distinguish missing, explicit null/default and invalid values. Persistence lands in phase 03.
5. [x] Wire owned resources and health.
   1. Reuse shared telemetry, Temporal connect, RpcClient, authz and problem_json. Open bounded psycopg/Redis clients and register cleanup immediately for partial-startup safety.
   2. `/live` checks process health; `/ready` checks required DB/Temporal/Redis/native/authz dependencies within deadlines. Redis is mandatory: fail readiness/startup dependency validation when unavailable, no optional/degraded startup or cache bypass. No provider inference or schema mutation in readiness. During a later publication outage, do not replay committed business effects; phase16 owns reconnect/error semantics.
   3. Authenticate `/v1` with shared gateway user identity; phase02 replaces human claim/header names without changing UUIDs. Never trust actor/owner JSON for authority; preserve cancellation and safe application errors.
   4. Add API CLI/help and lifespan-owned graceful cleanup. Deliver the worker CLI and stop hooks together with real registrations/polling in phase09, avoiding a nonfunctional stub. Never claim an empty worker ready.
6. [x] Prove actual dependency APIs in bounded tests.
   1. Fixture postgres_dsn owns disposable PostgreSQL18.6; redis_url owns disposable Redis matching phase 18's image pin. Never default to a developer DATABASE_URL/REDIS_URL. Use app-owned subprocess/Docker patterns, deadlines, redacted logs and finally cleanup; requested integration checks fail if Docker is absent.
   2. Fixture temporal_environment uses SDK time skipping for unit tests only. Persistent temporal_address/temporal_namespace fixtures land in phases 09/19 and are required for restart claims.
   3. Use actual create_agent and a scripted BaseChatModel only at the inference boundary. Observe assistant tool-call checkpoint before a real test effect with durability="sync"; reopen saver and prove saved tool results are not executed again and messages remain typed.
   4. Exercise public async before-model hooks and SummarizationMiddleware with deterministic output; prove compacted messages and inbox_cursor reload together. Keep this a compatibility proof, not another production runner.
   5. Import Update-with-Start and required Workflow info APIs from installed Temporal1.35 and exercise a minimal SDK handler. Do not claim persistent restart coverage.
   6. Create/close actual pinned Mirage Workspace/session with a tiny deterministic VFS fixture. Stat the original blob as FILE, expose its real child nodes, and exercise BOTH `/home/docs/report.pdf/report.md` and `/home/@<original-file-id>/report.md` through public session/read_file-equivalent dispatch and actual supported shell reads/listing. Include nested artifact directories and no child-ID requirement. Keep this early gate before broad LetFS implementation. Source inspection alone is not PASS; do not relabel all source files DIRECTORY, add /artifacts mounts, fork Mirage or change accepted paths if it fails. Capture the concrete failing call for the smallest supported-adapter correction.
   7. Execute Monty only on announced mounts, deny host files/env/network, exercise required Redis cache and serialize AG-UI envelope with agent_id/run_id on one root stream. Confirm native-wheel architecture support. LetFS integration remains phase08.
   8. Verify cleanup after saver/Redis/client startup failure and cancellation. Leave no background process; add no general fixture framework.
7. [x] Hand off installed API evidence.
   1. Record resolved versions and actual compatibility results during execution, including any evidence-backed pin adjustment.
   2. Give later phases the resource/fixture names. Keep schema, scheduling and public product commands in their owning phases.

## Verification commands and pass conditions

Run from repository root during implementation; these checks were not run while drafting.

```sh
uv lock --check
uv sync --locked --package leta
uv run --locked --package leta pytest apps/leta/tests/test_config.py apps/leta/tests/test_lifespan.py -q
uv run --locked --package leta pytest apps/leta/tests/test_engine_compatibility.py -m integration -q
pnpm --filter @openlet/leta check
pnpm --filter @openlet/leta build
pnpm --filter @openlet/leta test
pnpm --filter @openlet/python test:integration
pnpm contracts:check
```

Pass means reproducible resolution, isolated wheel imports, configuration/cleanup tests and actual saver/Monty/Redis/AG-UI checks without provider calls. Run replay checks once phase 09 supplies real histories; zero collected tests is not success. Saver integration owns only its disposable database.

## Acceptance checklist

- [x] Accepted upstream versions resolve and run on supported Python with uv --locked.
- [x] Independent app wheel uses shared clients; other packages gain no engine dependencies.
- [x] Server catalog enforces owner choice/Leti inheritance without inference or a call budget.
- [x] HTTP identity/error/health and all resource cleanup paths are tested.
- [x] Real factory/saver proves sync ordering and typed-state recovery.
- [x] Pinned Mirage FILE-parent named/original-ID artifact traversal, Monty, required Redis and AG-UI envelope gates pass.
- [x] No placeholder Workflow or early worker deployability claim.

## Risks and rollback

Resolution conflicts stop dependent work until a small reproducer supports a compatible pin adjustment. Mirage native wheels must match the deployment architecture. Pool initialization failure must not leave a partially ready process.

Before deployment, revert only the app's package/manifest/lock additions; preserve unrelated edits and database volumes. Once later phases persist Leta state, use phase 18's coordinated rollback. This phase changes no existing service data.
