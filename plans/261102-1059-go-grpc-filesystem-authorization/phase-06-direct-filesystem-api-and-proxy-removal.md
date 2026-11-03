---
phase: 6
title: "Direct filesystem API and proxy removal"
status: completed
priority: P1
effort: "24-40h"
dependencies: [3, 4, 5]
---

# Phase 6: Direct filesystem API and proxy removal

## Goal and context

Atomically rename and activate the prepared ingest app, switch the complete Go filesystem runtime into the real stack, expose direct public filesystem APIs, migrate every existing consumer, then delete the Workspace file facade and obsolete internal HTTP. Read [architecture](architecture-contract.md), [verification matrix](verification-matrix.md), and both source inventories linked from [plan](plan.md).

Dependencies: Phases 3–5 pass their own integration gates. Phase 5 produced a complete Go implementation in isolation; this phase owns the coordinated Compose/client switch. No frontend app exists in the current repo; update the actual Playwright API consumers rather than inventing a UI.

## Requirements and architecture

- Public filesystem routes are `/v1/filesystems/{filesystem}/...`; native gRPC exposes only public methods through Envoy.
- Workspace details/discovery provide stable filesystem/root references. Workspace retains domain/lifecycle APIs and durable provisioning; it never forwards file bytes or file requests after cutover.
- HTTP, native gRPC and internal callers enter the same authorization-enforcing application boundary.
- Generic mount resolution and filesystem permission checks prevent arbitrary scope; integrations choose mount labels. letfs has no business-owner mapping, domain-service lookup or graph writer.
- Signed S3 object transfers and inline PostgreSQL bytes stay unchanged. No compatibility proxy is needed for this pre-production route change.
- Existing health, service authentication, error, deadline, cancellation and trace behavior must be preserved or intentionally mapped.
- Phase 5's `activity.py` already uses generated protobuf requests/responses. At cutover, bind `worker.py` to `Processor` instead of `LegacyProcessor`, configure its gRPC address/credentials, and delete the temporary `legacy_http.py` binding and its reference-only tests. Retain the shared processing logic and native RPC regression tests.

## Files and ownership

| Action | Absolute files | Scope and test impact |
|---|---|---|
| Move/modify | `/home/qninh/projects/openlet/apps/letfs-processing/` to `/home/qninh/projects/openlet/apps/letfs-ingest/`; `src/openlet_processor/` to `src/letfs_ingest/` inside it | One app tree; distribution `letfs-ingest`, pnpm `@openlet/letfs-ingest`, dependency on shared `openlet-python`; activate prepared gRPC path and remove old application HTTP |
| Modify | `/home/qninh/projects/openlet/pyproject.toml`, `/home/qninh/projects/openlet/uv.lock`, `/home/qninh/projects/openlet/package.json`, `/home/qninh/projects/openlet/pnpm-lock.yaml`, `/home/qninh/projects/openlet/Makefile`, `/home/qninh/projects/openlet/.github/workflows/check.yaml` | Rename app uv/pnpm/task/CI, subprocess/module/wheel/Docker paths together; preserve shared Python dependency and codegen destination; regenerate locks through tooling |
| Modify | `/home/qninh/projects/openlet/scripts/bootstrap/configure.py`, `/home/qninh/projects/openlet/scripts/bootstrap/test_configure.py`, `/home/qninh/projects/openlet/scripts/operations/recovery.py`, `/home/qninh/projects/openlet/e2e/setup/recovery.test.ts`, `/home/qninh/projects/openlet/e2e/tests/api/backup-recovery.spec.ts` | Rename env/secrets plus writer-drain/start inventories and assert actual new workers are quiesced/restarted |
| Modify | `/home/qninh/projects/openlet/apps/letfs/Dockerfile`, `/home/qninh/projects/openlet/apps/letfs/package.json` | Switch runtime/build to complete Go server; native provider/health flags |
| Modify | `/home/qninh/projects/openlet/apps/letfs/internal/grpc/`, `/home/qninh/projects/openlet/apps/letfs/internal/http/`, `/home/qninh/projects/openlet/apps/letfs/cmd/server/` | Register proven public/admin/ingest surfaces and shared operation authorization |
| Modify | `/home/qninh/projects/openlet/apps/workspace/internal/http/server.go`, `/home/qninh/projects/openlet/apps/workspace/internal/http/workspaces.go`, `/home/qninh/projects/openlet/apps/workspace/internal/config/` | Remove facade routes/config; expose filesystem reference and use actual gRPC clients |
| Delete after consumer switch | `/home/qninh/projects/openlet/apps/workspace/internal/http/files.go`, `nodes.go`, `uploads.go`, `trash.go`, `search.go`, `archive.go` in that same absolute directory | Remove all forwarding; migrate useful tests first |
| Modify | `/home/qninh/projects/openlet/apps/workspace/internal/letfs/`, `/home/qninh/projects/openlet/apps/workspace/internal/temporal/` | Preserve/align existing Temporal contracts and scope; gRPC for genuine synchronous calls |
| Modify | `/home/qninh/projects/openlet/infra/config/envoy.template.json`, `/home/qninh/projects/openlet/infra/compose/dev.yaml`, `/home/qninh/projects/openlet/infra/compose/e2e.yaml` | letfs public route/HTTP2 upstream, private RPC isolation, runtime/ingest switch |
| Modify | `/home/qninh/projects/openlet/e2e/fixtures/api-test.ts`, `restart-service.ts`, `temporal-control.ts`, `filesystem-lock.ts` in the same fixture directory | Session FS ID, direct routes, new names/current histories and failure control |
| Modify | `/home/qninh/projects/openlet/e2e/setup/environment.ts`, `/home/qninh/projects/openlet/e2e/setup/settings.ts`, `/home/qninh/projects/openlet/e2e/tests/api/` | Actual API consumers and native boundaries, not a wholesale test rewrite |
| Modify/delete | `/home/qninh/projects/openlet/packages/contracts/public/openapi.yaml`, `/home/qninh/projects/openlet/packages/contracts/internal/openapi.yaml` | Update public navigation/generated letfs reference; delete obsolete private HTTP specification |
| Modify | `/home/qninh/projects/openlet/apps/account/internal/http/`, `/home/qninh/projects/openlet/apps/workspace/internal/user/client.go` | Remove any transitional internal HTTP after generated gRPC clients pass |

The fixture filenames above expand under `/home/qninh/projects/openlet/e2e/fixtures/`. Source families are sequential ownership from previous phases, not disjoint parallel tasks.

## Implementation steps

1. Re-read current Go code, generated services, Rust facade, Envoy and every actual E2E consumer. Confirm Phases 3–5 have complete parity evidence, including Workspace-owned inheritance projection/rebuild, stable-ID provisioning and local deletion fences; do not switch a partial server into the stack.
2. Finish the public letfs HTTP/native-gRPC adapter using Phase 1's selected mappings. Make actor/principal verification explicit even for in-process gateway calls. Public methods cannot obtain ingest/admin authority by choosing a protobuf method path or sending caller/job metadata.
3. Activate generic ID-based provisioning/lifecycle and remove provision columns/constraints/contracts in the backed-up baseline cutover. Workspace saves IDs before remote creation, saves returned references and waits for its Temporal relationship synchronization before reporting completed Workspace creation. letfs returns storage creation independently and denies public requests without graph permission. Replace all old workspace-named letfs Activities and workspace payload fields together in callers/workers. Expose generic quota-bucket usage with its own read check; one FS grant never implies bucket administration. Integrations supply mount labels; letfs validates paths and checks target FS without business lookup. Test two generic callers without adding chat/user products.
4. Replace the current `X-Workspace-Role` copy monitor override with the explicit action check. Keep upload follow-ups initiating-actor-bound, current read membership for copy status and raw-ID artifact restrictions. Preserve service-scoped generation/attempt enforcement for ingest.
5. Update Workspace-to-Account synchronous calls to generated gRPC if not already cut over in Phase 3. Keep Account's Clerk HTTP and existing native cross-owner Temporal orchestration. Expose usage through the generic direct quota-bucket API with a bucket read action; Workspace returns bucket references and projects permissions. Remove the old Workspace usage relay with its file proxy.
6. Atomically move the existing Python app to `apps/letfs-ingest`, rename the distribution to `letfs-ingest`, module to `letfs_ingest` and pnpm package to `@openlet/letfs-ingest`. Keep the app dependent on the shared `openlet-python` wheel; generated `openlet_api` stays in `packages/python/src/openlet_api/` and Buf output does not move. Update app wheel/import/subprocess/model-prefetch/Docker references and activate the prepared gRPC activities. Prove clean shared-plus-renamed-app wheel installation with no duplicate generated package. Remove old application HTTP clients/entrypoints. Switch letfs runtime/build to Go and Compose to `ingest-cpu`/`ingest-io` with CPU/IO separation. Update root uv/pnpm tasks, workspace/locks, Makefile, CI uv selector/cache paths, bootstrap env/secrets, startup/restart fixtures, recovery writer-drain and restored-start lists in this same change. Apply exact Phase 5 queue/Activity contracts consistently; never leave a runnable stage dependent on cached images or defer consumers to Phase 7.
7. Migrate E2E Session to carry `filesystemId` returned by Workspace. Change all file/upload/search/trash/archive/status requests to direct FS routes, preserve JSON/header/byte assertions, and update service restart and temporal-history controls. Keep workspace collaboration routes unchanged.
8. Add Envoy filesystem HTTP routes and public native-gRPC service/method routing with HTTP/2. Move archive-only deadline to the direct route while preserving runtime/idle limits. Retain verified Clerk/gateway identity and deny every private admin/ingest path at ingress and application layers.
9. Delete Workspace facade handlers/routes/body forwarding and their internal Location rewriting. Remove obsolete letfs HTTP/auth config and Account private HTTP endpoints only after all corresponding callers use gRPC. Preserve genuinely public HTTP and vendor-native calls.
10. Refresh public OpenAPI/transport references from the proven generator and actual handlers. Preserve OAS3.1 validity for the existing authored surface; do not manually duplicate generated message schemas. Remove `packages/contracts/internal/openapi.yaml` and update every owning link after no private HTTP consumer remains.
11. Run real Envoy/Compose public journeys plus native-gRPC boundary tests. For ambiguous response, revoked member, foreign FS, artifact alias and wrong ingest job, assert no mutation or metadata leak. The complete API suite includes backup/recovery: prove the renamed workers and all projectors are drained before capture and restarted after restore, then processing resumes to ready. Capture new Go histories for final replay.

## Todo

- [x] Verify all prerequisite Go/ingest parity gates before runtime switch.
- [x] Expose verified public HTTP/native gRPC with shared operation checks.
- [x] Activate generic stable-ID provisioning/mounts; Workspace owns inheritance synchronization; remove provision columns/contracts.
- [x] Atomically rename app/distribution/module/package and switch runtime/clients/queues, CI/app paths, bootstrap secrets and recovery drain/start controls; preserve the shared Python dependency and codegen destination.
- [x] Migrate every actual API fixture/test consumer.
- [x] Remove Workspace facade, internal HTTP handlers/clients and obsolete spec.
- [x] Prove gateway isolation, direct bytes, all permissions and new histories.

## Verification

Existing commands retained with updated implementations/configuration:

```sh
uv sync --locked --package letfs-ingest
uv build --package letfs-ingest
pnpm --filter @openlet/letfs-ingest check
node --test --test-concurrency=1 e2e/setup/environment.test.ts e2e/setup/recovery.test.ts
pnpm check:e2e
pnpm --dir e2e exec playwright test --project=api --list
pnpm --dir e2e exec playwright test --project=api --grep 'gateway baseline'
pnpm --dir e2e exec playwright test --project=api
```

Run the narrow actual test title discovered by `--list` when a grep above no longer exists; never call a zero-test selection a pass. Add/run real native-gRPC integration tests through an Envoy route in addition to public HTTP. The new Go test packages from prior phases must pass before full E2E.

| Priority | Scenario | Required result |
|---|---|---|
| Critical | JWT caller selects private gRPC method / spoofed delegated actor | Denied in both ingress and application entry points |
| Critical | Foreign FS by ID, mount, cwd, root alias or search cursor | No scope expansion or metadata leak |
| Critical | User writes artifacts by alternate route/raw ID | Same read-only rejection |
| Critical | Storage exists before Workspace inheritance synchronization | letfs denies public access; Workspace completion waits for its own projector |
| Critical | Revoked membership after synchronized role change | Direct HTTP and native gRPC both deny inherited FS access |
| High | Owner uses another actor's upload / Viewer reads another actor's copy monitor | Existing actor constraints preserved |
| High | Inline, signed single/multipart, 307, Range, ZIP cancellation | Exact byte/headers and cleanup behavior; no Workspace relay |
| High | Full API backup/recovery after worker rename | Actual ingest/projector writers drained and restarted; interrupted processing reaches ready |
| High | Restart ingest/Go worker between commit and acknowledgment | Current job resumes safely with bounded effects |
| Medium | Workspace nonactive/status/tombstone and filtered lists | Visibility/lifecycle contract preserved |
| Medium | Old proxy/private HTTP URLs | No forwarding remains; expected denied/not-found response |

## Success criteria

All file functionality works through the direct public service, generated internal clients use gRPC, no private application HTTP or Workspace file facade is reachable, and fresh real system histories come from the Go runtime. The renamed Python workers install the independent shared RPC wheel, with no generated code under the app and no codegen destination change, and execute the actual gRPC chain; provider mocks cannot stand in for letfs RPC.

## Risks, security and rollback

Biggest risks are direct-method authorization bypass, missing consumers and lost stream semantics. A working HTTP happy path is insufficient; require the native-gRPC/private-method and cancellation cases. Fail closed on SpiceDB check outage; never restore a role fallback to keep tests green.

Before touching an existing dev environment, back up with the permanent owner-safe recovery tool and stop/drain its writers. First validate the switch in an isolated E2E project. If cutover fails, stop new writers and return to a matching pre-cutover checkout/snapshot; do not attach Rust to reset Go state. Phase 7 begins only after these runtime/consumer gates pass.
