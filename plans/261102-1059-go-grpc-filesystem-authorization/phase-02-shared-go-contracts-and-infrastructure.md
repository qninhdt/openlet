---
phase: 2
title: "Shared Go/Python contracts and infrastructure"
status: completed
priority: P1
effort: "24-32h"
dependencies: [1]
---

# Phase 2: Shared Go/Python contracts and infrastructure

## Outcome and entry gate

Extend the Phase 1 proof into a working shared Go foundation, reusable Python RPC package, generated application contracts and real SpiceDB infrastructure. Account/Workspace HTTP and Rust letfs remain functional; do not enable public Go filesystem routes or remove the facade yet. Generated methods are contracts, not evidence of implemented services.

Dependencies: [Phase 1](phase-01-contracts-and-proof-gates.md) must prove schema validity, relationship APIs, PostgreSQL compatibility and byte/OpenAPI mappings. Read the [architecture contract](architecture-contract.md), [verification matrix](verification-matrix.md) and [source inventory](../reports/scout-261102-1059-authorization-rpc-inventory.md). Failed proof gates block affected implementation, without authorizing a different architecture.

## Requirements

- Extend the same `openlet/packages/go` module if Phase 1 initialized it. Use Go 1.27.3 and current Temporal SDK family initially; pin compatible direct dependencies through tooling.
- Use direct official SpiceDB SDK clients. Share identity, bounded RPC, typed actions/resources and native relationship APIs; no role evaluator, Access proxy, shared domain models or generic framework.
- Extend the Phase 1 `openlet-python` distribution under `packages/python`; ingest and future Python services consume it without depending on each other. Generated `openlet_api` stays outside app trees. Add handwritten Python infrastructure only for concrete common needs, without building a framework or adding Leti.
- Protobuf paths and generated namespaces follow the architecture contract exactly. Account/Workspace public Gin HTTP can remain; public letfs HTTP follows Phase 1's generated/thin-adapter proof.
- SpiceDB OSS uses dedicated database/user `openlet_spicedb` on the existing PostgreSQL 18.6 instance, not a new server. No application SQL against SpiceDB tables, separate canonical auth DB or Watch requirement.
- Preserve provider-native protocols, Temporal child/remote-Activity orchestration, secrets, bounded cancellation and telemetry. Health must report real readiness.

## File inventory

Absolute paths use `/home/qninh/projects/openlet/`. S/M/L describe local, multi-consumer and cross-boundary review size. Companion filenames marked “same directory” share the absolute parent shown. New files are planned, not current APIs.

| Absolute path | Action / current or new | Size / test impact |
|---|---|---|
| `/home/qninh/projects/openlet/packages/go/go.mod`, `/home/qninh/projects/openlet/packages/go/go.sum`, `/home/qninh/projects/openlet/packages/go/package.json` | New/extend proof module and thin native tasks | M; shared checks and independent resolution |
| `/home/qninh/projects/openlet/packages/go/identity/principal.go`, `principal_test.go` in same directory | New verified public/service/job context | M; spoofed, missing and duplicate metadata |
| `/home/qninh/projects/openlet/packages/go/rpc/interceptors.go`, `interceptors_test.go`, `errors.go`, `errors_test.go` in same directory | New authentication, deadline, trace and errors | M; real gRPC caller/server checks |
| `/home/qninh/projects/openlet/packages/go/authz/client.go`, `actions.go`, `projection.go`, `projection_integration_test.go` in same directory | Official SDK checks and schema/policy/relationship helpers only | L; real SpiceDB, no local role evaluator |
| `/home/qninh/projects/openlet/packages/go/config/secrets.go`, `secrets_test.go` in same directory | Extract identical existing secret loading only | S; file/env/config regressions |
| `/home/qninh/projects/openlet/packages/go/telemetry/telemetry.go`, `telemetry_test.go` in same directory | Extract compatible provider lifecycle only | M; trace/baggage/shutdown |
| `/home/qninh/projects/openlet/packages/contracts/proto/openlet_api/account/v1/account.proto` | New bounded summary/verified-email RPCs | M; UUID, limits, presence, scope and errors |
| `/home/qninh/projects/openlet/packages/contracts/proto/openlet_api/workspace/v1/workspace.proto` | New required owner/bootstrap service contract | M; retain durable SDK orchestration |
| `/home/qninh/projects/openlet/packages/contracts/proto/openlet_api/letfs/v1/letfs.proto` | New complete public/admin/ingest contracts | L; public/service descriptors and parity matrix |
| `/home/qninh/projects/openlet/packages/contracts/package.json` | New `@openlet/contracts` task package under `packages/*` | S; codegen/task dependency graph |
| `/home/qninh/projects/openlet/packages/contracts/buf.yaml`, `/home/qninh/projects/openlet/packages/contracts/buf.gen.yaml`, `/home/qninh/projects/openlet/packages/contracts/buf.lock` | Create/extend pinned generation config | M; lint, import and reproducibility |
| `/home/qninh/projects/openlet/packages/go/gen/openlet_api/` | Generated Go tree only | M; compile without duplicate DTOs |
| `/home/qninh/projects/openlet/packages/python/pyproject.toml`, `/home/qninh/projects/openlet/packages/python/src/openlet_api/`, `/home/qninh/projects/openlet/packages/python/tests/`, `/home/qninh/projects/openlet/packages/python/package.json` | Extend shared generated wheel and `@openlet/python` tasks | M; isolated wheel/client/server imports and real gRPC, no app imports |
| `/home/qninh/projects/openlet/pyproject.toml`, `/home/qninh/projects/openlet/uv.lock`, `/home/qninh/projects/openlet/apps/letfs-processing/pyproject.toml`, `/home/qninh/projects/openlet/apps/letfs-processing/package.json`, `/home/qninh/projects/openlet/apps/letfs-processing/Dockerfile` | Register shared uv dependency, lock resolution, Turbo edge and shared-wheel Docker install; keep app name/entrypoints | M; clean locked app/container builds without workspace-path leakage |
| `/home/qninh/projects/openlet/packages/contracts/authz/schema.zed`, `/home/qninh/projects/openlet/packages/contracts/authz/schema_test.yaml` | Extend proven schema/permission fixtures | L; real schema validation and tuple ownership |
| `/home/qninh/projects/openlet/go.work`, `/home/qninh/projects/openlet/go.work.sum`, `/home/qninh/projects/openlet/pnpm-workspace.yaml`, `/home/qninh/projects/openlet/pnpm-lock.yaml` | Register module and `packages/*` discovery through tooling | S; current discovery is only apps/* and e2e |
| `/home/qninh/projects/openlet/package.json`, `/home/qninh/projects/openlet/turbo.json`, `/home/qninh/projects/openlet/.github/workflows/check.yaml` | Add generation/shared tasks and cache inputs | M; clean CI |
| `/home/qninh/projects/openlet/apps/account/Dockerfile`, `/home/qninh/projects/openlet/apps/workspace/Dockerfile` | Include shared module/generated imports | M; clean container builds |
| `/home/qninh/projects/openlet/apps/account/go.mod`, `/home/qninh/projects/openlet/apps/account/go.sum`, `/home/qninh/projects/openlet/apps/workspace/go.mod`, `/home/qninh/projects/openlet/apps/workspace/go.sum` | Add actual shared dependency through tooling | S; independent tidy/build |
| `/home/qninh/projects/openlet/infra/compose/dev.yaml`, `/home/qninh/projects/openlet/infra/compose/e2e.yaml` | Add SpiceDB migrate/serve/schema sequence and secrets | L; boot and dependency failure |
| `/home/qninh/projects/openlet/scripts/bootstrap/configure.py`, `/home/qninh/projects/openlet/scripts/bootstrap/test_configure.py` | Extend DB/credentials without rotating existing secrets | M; ownership, permissions, validation |
| `/home/qninh/projects/openlet/e2e/setup/environment.ts`, `/home/qninh/projects/openlet/e2e/setup/environment.test.ts`, `/home/qninh/projects/openlet/e2e/setup/settings.ts` | Extend SQL/redaction/ordered startup/cleanup | L; canceled startup leaves no orphan |
| `/home/qninh/projects/openlet/scripts/operations/recovery.py`, `/home/qninh/projects/openlet/e2e/setup/recovery.test.ts` | Extend DB/writer inventory and restored-readiness fence | M; rebuild acceptance completes in Phases 3/7 |
| `/home/qninh/projects/openlet/docs/setup.md`, `/home/qninh/projects/openlet/docs/architecture.md`, `/home/qninh/projects/openlet/docs/testing.md`, `/home/qninh/projects/openlet/docs/operations.md` | Update implemented operational routes only | S; claims link owning config/scripts |

Phase 3 owns Account/Workspace adoption; Phase 5 owns target activity preparation; Phase 6 owns Python rename and activation. Do not implement fake successful handlers. Preserve protobuf compiler requirements selected by Phase 1 even when later removing Rust-specific toolchains/cmake.

## Numbered implementation steps

1. **Recheck Phase 1 artifacts.** Read selected image/tool versions and installed SDK types; carry forward schema/OpenAPI/version evidence. Record owner-exclusive business relationships; the later user correction removes the old head/epoch proof framework. Verify supported SpiceDB flags from the pinned binary rather than invent migration/secret options.
2. **Extend one shared module.** Register `openlet/packages/go` in `go.work`, `packages/*` in pnpm workspace and thin library tasks for Turbo. Register `@openlet/contracts` and declare actual workspace package dependencies so Turbo orders contract generation before consumers, including `@openlet/go` and `@openlet/python`. Register `packages/python` in the uv workspace, declare `openlet-python` as a workspace dependency of the current processor, and order consuming app tasks after shared-package generation/checks. Keep Python runtime dependency resolution in uv; pnpm manifests only expose native tasks/dependency edges. Current module names are `openlet/apps/*`; use explicit local replace directives when needed for independent `go mod tidy`/container builds, or prove the chosen workspace-supported workflow resolves them. Update sums/locks through tooling. No root `go test ./...`: there is no root go.mod.
3. **Implement verified caller admission.** Distinguish gateway user, Clerk-subject-only bootstrap, service principal and resource/generation/attempt-bound job. Reject duplicate/missing trusted metadata and disallowed methods. Payload actor/resource IDs cannot authenticate. Separate gateway/service credentials and allowlists; public JWTs cannot invoke internal methods. Keep bearer/file secrets out of logs/history; only explicit trusted local Compose/test allows plaintext, otherwise verify configured TLS.
4. **Implement bounded RPC behavior.** Add deadlines, cancellation, message-size, error-detail and trace-context contracts with explicit connection ownership/shutdown. No blanket mutation retry; ambiguous effects need owner reconciliation. Native health reflects actual startup/dependencies. Preserve no-baggage propagation and bounded telemetry shutdown.
5. **Complete protobuf contracts.** Use Phase 1's full matrix for presence, UUID validation, decimal HTTP strings, pagination, errors, revision/idempotency and byte/download descriptors. Split public/admin/ingest explicitly. Keep Account batches at 100 with exact returned-ID validation. letfs imports only its own generated contracts and shared infrastructure. Generic storage methods take IDs, immutable storage parameters and request keys; no workspace/conversation ownership. Wire no letfs business-service client or graph writer. Replace the workspace-named letfs credential with generic authenticated service identity and explicit method scopes; payload IDs are never credentials. Existing Temporal children/remote Activities are not HTTP; retain them when appropriate.
6. **Make generation deterministic.** Pin Buf/plugins with supported digests/locks. Generate Go and chosen HTTP mappings/reference; keep authored Account/Workspace OpenAPI 3.1 distinct. Never relabel default OpenAPI v2 as 3.1. Extend Phase 1's independent shared-wheel proof. Python output remains `packages/python/src/openlet_api/` throughout all phases; generate messages, client stubs and server interfaces once. Build/install the shared and app wheels in a clean environment outside the checkout, without editable sources or repository `PYTHONPATH`. Update current Python Docker copies/install steps and CI inputs/caches for shared workspace metadata, source and lock resolution while retaining old worker entrypoints. Do not bundle stubs in the app wheel, require app-to-app imports, publish to PyPI or create a future app directory. Add generation/lint/regeneration-diff tasks and shared CI inputs without claiming unimplemented RPCs work.
7. **Bring up real SpiceDB.** Render dedicated random service credential and `openlet_spicedb` DB URI/password in dev/E2E. Mount secrets through supported facilities without exposing them in logs/public config/arguments. Same-version datastore migration precedes serve; native health precedes schema initialization; dependent authorization readiness follows expected schema/policy verification. Schema mismatch fails explicitly rather than blindly overwriting unknown state on restart.
8. **Bound the PostgreSQL budget.** Inventory Account/Workspace pools (16 each), letfs, Temporal persistence/visibility, SpiceDB pools, migrations and operator reserve against current `max_connections=200`. Include transient job overlap. Configure supported maxima whose sum fits the cap; verify actual connections during startup. No benchmark or Watch/commit-timestamp claim is needed.
9. **Integrate process/recovery ownership.** Extend E2E deterministic ports/labels/secrets/start/wait/cleanup; expose no public SpiceDB port. Track and stop owned processes. Add SpiceDB to coordinated writer/DB inventory. Restored graph remains nonready until supported datastore repair or canonical relationship rebuild is verified; pg_dump alone does not address datastore MVCC/transaction-ID recovery. Phases 3/7 finish owner/whole-stack rebuild.
10. **Verify, review and document real behavior.** Run narrow library/config/generation tests, fresh Docker startup and relevant existing suites. Inspect generated/dependency/config diff and redacted logs. Keep Go letfs public routes disabled until Phase 6.

## Todo / success criteria

- [x] Phase 1 proofs pass without weakened assertions.
- [x] Shared/app modules and clean Docker builds resolve identical generated imports.
- [x] Turbo and uv discover the shared Python package and real dependency edges; isolated shared/app wheels import client/server types and complete RPC without checkout/PYTHONPATH leakage.
- [x] Python Docker/CI installs use the shared dependency; no app-local generated copies or premature app rename exist.
- [x] Real gRPC fixture accepts legitimate service and rejects spoofed/public/disallowed callers.
- [x] SpiceDB migration/schema/health works on PG18.6 with dedicated owner and bounded pools.
- [x] Credential/schema/migration failure never reports authorization readiness.
- [x] Existing Account/Workspace/Rust routes work; no premature cutover.
- [x] Startup failure/cancellation cleans owned resources and redacts credentials.
- [x] Recovery inventory/fence covers SpiceDB; no unproved restore-success claim.
- [x] Generation/planned commands are wired into manifests/CI; docs reflect working behavior.

## Critical / high / medium scenario matrix

Completion evidence: [Phase 2 progress](reports/phase-02-progress.md). Development Compose and actual E2E graph startup/cancellation checks pass, all 32 API journeys pass, and six-database restore uses supported transaction-ID repair with schema/readiness fencing. Canonical owner relationship rebuild remains assigned to Phases 3/7.

| Severity | Scenario | Required proof |
|---|---|---|
| Critical | Spoofed actor, public JWT or ingest principal calls Account/admin RPC | Real gRPC/Envoy denial at authenticated method/scope boundary |
| Critical | Credential/schema/migration unavailable | Explicit failure/nonready; no SQL-role fallback or fake endpoint |
| Critical | Retry after restart/newer canonical change | Current-state relationship synchronization; no replay of obsolete grant payloads |
| High | Repeated boot/initializer and mismatched schema | Idempotent valid startup or actionable failure; no partial readiness |
| High | Pools plus Temporal/migration jobs | Configured sum fits 200 with reserve; observe real connections |
| High | E2E canceled during graph startup | Owner-safe cleanup and redacted diagnostics |
| High | Restored canonical DB with incompatible/stale graph | Admission fenced until verified repair/rebuild |
| Medium | Duplicate metadata, oversize data, cancellation/deadline | Typed bounded failure and closed resources |
| High | Shared Python wheel used by independent consumer outside checkout | Generated client/server imports and real RPC work without ingest imports, editable source or PYTHONPATH; no duplicate stubs in app wheel |
| Medium | Clean generation/container builds without caches | Zero generated diff, correct Go/Python namespaces and installed shared wheel |
| Medium | Shared telemetry/config extraction | Validation, trace continuity, no baggage/secrets |

## Verification commands

Current commands, from `/home/qninh/projects/openlet` (not executed by plan authoring):

```sh
pnpm --filter @openlet/account test
pnpm --filter @openlet/workspace test
pnpm --filter @openlet/account check
pnpm --filter @openlet/workspace check
uv run --locked --package openlet-processor pytest scripts/bootstrap/test_configure.py -q
pnpm check:e2e
node --test --test-concurrency=1 e2e/setup/environment.test.ts e2e/setup/recovery.test.ts
pnpm --dir e2e exec playwright test --project=api --grep 'gateway baseline'
```

Planned commands, valid only after packages/tasks and pinned tools exist:

```sh
go -C packages/go test ./...
go -C packages/go test -tags integration ./... -count=1
pnpm contracts:generate
pnpm contracts:check
uv build --package openlet-python
pnpm --filter @openlet/python check
pnpm --filter @openlet/python test
pnpm --filter @openlet/python test:integration
```

`@openlet/python` check/test/test:integration tasks are new: check/test cover generated imports and isolated wheel packaging; test:integration runs the independent consumer/RPC proof, including a server built from generated interfaces. Keep infrastructure-dependent fixtures out of the default unit task. Declare test tooling and locked dependencies explicitly; tests cannot succeed by resolving another app.

`contracts:check` must execute selected standard proto/schema lint, import/compilation and regeneration-diff checks. Discover exact flags during implementation. Use the E2E harness for owned Compose boot; no unscoped reset. Wider gates: [verification-matrix.md](verification-matrix.md).

## Risks, security and rollback

Broad OSS SpiceDB credentials share a backend trust boundary; they do not enforce per-domain graph writes. Document tuple ownership honestly. Shared-PG saturation can become authorization outage; cap connections before enabling callers. Extraction/codegen may alter errors/presence/shutdown, requiring actual consumer checks.

Back up the owned development environment before schema/runtime changes. Before adoption, stop owned processes and revert only this phase's changes when a gate fails. After reset, restore a matching checkpoint into an isolated owned target and fence graph readiness until repair/rebuild verification. Never run old binaries on new tables, add production compatibility work, or use broad `down -v` rollback.
