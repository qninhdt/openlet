---
phase: 1
title: "Contracts and proof gates"
status: completed
priority: P1
effort: "16-24h"
dependencies: []
---

# Phase 1: Contracts and proof gates

## Goal and context

Complete the behavior/action/RPC inventory and prove graph API and binary transport behavior before rewriting letfs. Read [architecture](architecture-contract.md), [authorization inventory](../reports/scout-261102-1059-authorization-rpc-inventory.md), [filesystem inventory](../reports/scout-261102-1059-letfs-go-parity.md), and current [API](../../docs/api-contracts.md), [data model](../../docs/data-model.md), [workflows](../../docs/workflows.md) and [testing](../../docs/testing.md).

Dependencies: none. This phase is executable preparation, not another product interview. All experiments use isolated owned resources; never reset developer data as test setup.

## Superseded proof design

The original CAS/head/intent/ack/epoch experiments were executed and remain recorded in [proof results](reports/proof-results.md). The November 2 user correction rejects that runtime framework and SQL permission catalogs. These experiments are historical evidence, not current implementation requirements. Phase 3 removes their unused implementation and replaces its coverage with native relationship writes, action checks, current-state retry/reconciliation and fenced rebuild tests. Preserve transport, stable-ID, packaging and trust-boundary work.

## Key insights and requirements

- The real policy includes self-leave, bootstrap, nonactive workspace status, retained Owner tombstones, actor-only upload follow-ups and actor/current-Owner copy status.
- SQL/SpiceDB writes are separate. Native API retries do not imply instantaneous revocation; current-state synchronization must be tested honestly.
- Protobuf mappings must preserve decimal strings, optional/null values, UUIDs, ETags, preconditions, structured errors, raw bytes and streaming.
- Existing OpenAPI is 3.1. Default grpc-gateway OpenAPI v2 output is not a drop-in replacement.
- Preserve actual MIME plus attachment/nosniff behavior; fix the conflicting doc after implementation.
- No new service, production compatibility layer or real-LLM testing is needed.

## Files and ownership

| Action | Absolute source/target | Scope and test impact |
|---|---|---|
| Read/move | `/home/qninh/projects/openlet/packages/contracts/public/openapi.yaml`, `/home/qninh/projects/openlet/packages/contracts/internal/openapi.yaml` | Complete endpoint/schema inventory; original root paths were moved here |
| Read | `/home/qninh/projects/openlet/apps/workspace/internal/http/`, `/home/qninh/projects/openlet/apps/workspace/internal/workspace/` | Exact role, actor and lifecycle behavior |
| Read | `/home/qninh/projects/openlet/apps/letfs/src/`, `/home/qninh/projects/openlet/apps/letfs/tests/` | Full Rust parity reference |
| Move | `/home/qninh/projects/openlet/contracts/` to `/home/qninh/projects/openlet/packages/contracts/` | One shared Turborepo contract package; repair active doc links during the move |
| Create/extend | `/home/qninh/projects/openlet/packages/contracts/buf.yaml`, `/home/qninh/projects/openlet/packages/contracts/buf.gen.yaml`, `/home/qninh/projects/openlet/packages/go/gen/openlet_api/` | Minimal real generation owned here; Phase 2 integrates/extends it |
| Create | `/home/qninh/projects/openlet/packages/python/pyproject.toml`, `/home/qninh/projects/openlet/packages/python/src/openlet_api/`, `/home/qninh/projects/openlet/packages/python/tests/` | Minimal real `openlet-python` wheel, generated RPC types/runtime dependencies and isolated installation/RPC proof |
| Modify through tooling | `/home/qninh/projects/openlet/pyproject.toml`, `/home/qninh/projects/openlet/uv.lock`, `/home/qninh/projects/openlet/apps/letfs-processing/pyproject.toml` | Register shared uv member and current-app dependency; preserve app identity and old entrypoints |
| Modify as needed for the proof dependency | `/home/qninh/projects/openlet/apps/letfs-processing/Dockerfile`, `/home/qninh/projects/openlet/.github/workflows/check.yaml` | Keep old worker/container and CI build inputs valid when shared workspace dependency is introduced; Phase 2 completes integration |
| Create | `/home/qninh/projects/openlet/packages/contracts/authz/action-resource-matrix.md` | Operation/action/resource/role/caller/tuple-owner ledger |
| Create | `/home/qninh/projects/openlet/packages/contracts/rpc-surface.md` | Complete operation-to-public/admin/ingest contract ledger; Phase 2 expands remaining wire shapes |
| Create | `/home/qninh/projects/openlet/packages/contracts/authz/schema.zed` | Initial graph schema; later remove superseded marker definitions |
| Create | `/home/qninh/projects/openlet/packages/contracts/proto/openlet_api/` | Initial real account/workspace/letfs wire contracts |
| Create | `/home/qninh/projects/openlet/packages/go/authz/projection_integration_test.go` | Historical graph API experiment; superseded runtime framework is removed in Phase 3 |
| Create | `/home/qninh/projects/openlet/packages/go/rpc/transport_integration_test.go` | Real HTTP/gRPC bytes, cancellation and identity proof |
| Create/extend for proof | `/home/qninh/projects/openlet/apps/workspace/internal/workspace/projection.go`, `projection_integration_test.go`, owner baseline SQL and shared-module Docker/package inputs | Historical SQL projection experiment; Phase 3 removes the rejected tables/code instead of adopting it |
| Create for proof | `/home/qninh/projects/openlet/apps/letfs/internal/http/content.go`, `requests.go`, `transport_test.go` | Actual target byte/JSON/revision/Location adapters; Phase 4 adopts them |
| Create/extend for proof | `/home/qninh/projects/openlet/apps/letfs/go.mod`, `/home/qninh/projects/openlet/apps/letfs/internal/filesystem/provisioning.go`, `/home/qninh/projects/openlet/apps/letfs/internal/grpc/administration.go`, isolated integration fixtures | Actual generic stable-ID implementation; Phase 4 extends it rather than creating a duplicate prototype |
| Modify for proof | `/home/qninh/projects/openlet/apps/letfs/migrations/0001_initial.sql` | Add immutable Go create identity; retain nullable legacy provision columns only for the unchanged Rust reference, remove at cutover |
| Create | `/home/qninh/projects/openlet/plans/261102-1059-go-grpc-filesystem-authorization/reports/proof-results.md` | Versions, commands, observed results and chosen mappings |

If runnable proofs need a module before Phase 2, initialize the actual `openlet/packages/go` module with only required dependencies. Phase 2 extends it; do not create a temporary framework/module. Minimal pinned Buf/protobuf output, the independent shared Python wheel/runtime dependencies, uv registration and current-app dependency belong to this proof phase; Phase 2 integrates them. Generate Python only into `packages/python/src/openlet_api/`; never put generated code in an app tree. Keep the current Python app name/path until Phase 6. If adding its shared workspace dependency changes Docker/CI resolution, update the minimal source/metadata copies and cache inputs in this phase too; the existing worker must remain rebuildable between phases. Root workspace registration and dependency changes are owned sequentially, not in parallel.

## Implementation steps

1. Re-scout touched paths with CodeGraph before navigation. Move the existing `contracts/` tree into `packages/contracts/` before adding new contracts; update active doc links and record old-to-new source paths. Phase 2 registers its package tasks with Turbo. Map every current route, workflow/Activity, storage behavior and consumer to its new owner and regression. Treat the two inventories as starting evidence, not permission to skip current source.
2. Finalize action identifiers and valid graph permission names. Include all exceptional operations in the architecture table. Separate permission decisions from retained SQL constraints, request/actor identity bindings and artifact restrictions.
3. Assign one writer per business relationship. Workspace synchronizes memberships and its bucket/filesystem references; letfs has no business mapping or graph writer. Generic storage contracts use caller-persisted IDs/idempotency, never provision keys. The original per-event projection ledger and waiter experiment is superseded; Phase 3 uses existing business data and owner Temporal execution.
4. Verify official SDK/types and choose a pinned SpiceDB OSS image compatible with PostgreSQL 18.6 and Go 1.27.3. Record exact version/digest. Pin codegen tools; do not opportunistically upgrade existing runtimes.
5. Record real PostgreSQL-backed SpiceDB atomic-write, consistency and failure behavior. The original marker CAS experiment passed but is not a required runtime architecture after the user correction.
6. Record deletion/reset behavior of the graph API. Phase 3 implements fenced rebuild from canonical business records and current-state retry/reconciliation without custom graph epochs or SQL authorization tables.
7. Prove a successful revoke/transfer is visible to another caller checking inherited filesystem access with initial explicit `fully_consistent` reads. Do not test only the mutator reusing its returned token.
8. Define public/admin/ingest protobuf service boundaries, scope, bounded bytes and download descriptors. Include generic bucket usage with its own read permission; an FS grant cannot expose siblings or grant bucket administration. Mount aliases are integration-provided path context, never permission evidence. Generate Go and Python stubs and test installed-wheel imports without hand-editing generated imports. Build the independent `openlet-python` wheel and the current processor wheel. Install both outside the checkout in a clean environment with no repository `PYTHONPATH`; prove `openlet_api` resolves from the shared distribution and a real Go/Python RPC round trip works. Check generated client and server imports and that no generated package is bundled in the app wheel. The final `letfs_ingest` namespace is checked after the Phase 6 rename. Test native gRPC and public HTTP access to the same authorized operation boundary.
9. Exercise actual HTTP bytes, selected MIME, safe attachment/nosniff, one Range, 307 object redirect, no-store, ETag/If-Match, Location, body limits, slow consumers, cancellation and failure after ZIP headers. Through Envoy, reject duplicate/spoofed actor metadata and public access to private method paths.
10. Select a supported OpenAPI 3.1 generation/conversion route; validate output rather than relabel v2. If generated HttpBody mappings cannot preserve bytes/headers/abort behavior, choose a thin in-process HTTP adapter to the same application function. No Workspace or remote proxy.
11. Write evidence and decisions to `proof-results.md`; propagate any changed technical choice to every phase. Failed proofs stop dependent work. They do not authorize Access, graph-canonical authority, member statuses or a workspace-wide role-change gate.

## Todo

- [x] Complete behavior and action/resource/tuple-owner ledgers.
- [x] Define actual protobuf and initial graph contracts.
- [x] Record compatible SDK/image/codegen pins.
- [x] Record historical CAS/duplicate/lost-response experiment; superseded runtime framework is removed in Phase 3.
- [x] Record historical reset fencing experiment and independent inherited-check proof; epoch framework is superseded.
- [x] Prove HTTP/native-gRPC bytes, errors, cancellation and caller boundaries.
- [x] Prove independent shared Python wheel/client/server imports and real RPC outside the checkout, without app-vendored stubs; validate OpenAPI output.
- [x] Record proof results and reconcile downstream phases.

Measured evidence: [proof results](reports/proof-results.md). Checked items record experiments actually completed. The old SQL waiter/epoch protocol is superseded, not an accepted runtime dependency. Transport, shared Python packaging and generic provisioning evidence remains reusable.

## Verification

Existing commands, useful for baseline discovery:

```sh
pnpm --dir e2e exec playwright test --project=api --list
pnpm check:e2e
```

Planned commands, runnable only after the actual module and proof tests exist:

```sh
go -C packages/go test -tags integration ./authz -count=1
go -C packages/go test -tags integration ./rpc -count=1
```

| Priority | Scenario | Required proof |
|---|---|---|
| Critical | Delayed/in-flight write or retry after newer synchronized revoke/transfer | Phase 3 proves superseded access cannot return; the historical CAS framework is not required |
| Critical | Work resumes after graph rebuild | Drain writers and reread restored canonical records before sync |
| Critical | Public request to internal RPC | Denied before domain work |
| Critical | ZIP midstream error/disconnect | Abort/truncate, no appended JSON or resource leak |
| High | Ambiguous response or concurrent newer mutation | Existing preconditions protect business effects; sync current state |
| High | Successful change then independent Drive check | New effective permission visible |
| High | Range/redirect/ETag/Location/error mismatch | Required transport semantics preserved |
| High | Independent shared Python wheel plus current app wheel | Clean installation outside checkout imports generated messages/client/server types from `openlet-python` and completes real RPC; no app-vendored stubs |
| Medium | Lists/optional fields/limits | Bounded, explicit wire and cursor behavior |

## Success gate

All critical/high proofs pass on the selected real dependencies, every behavior/action has an owner, and the exact protocol/transport choices are recorded. Source reading or a mocked client is not proof of remote atomicity, byte streaming or cancellation.

## Risk, security and rollback

Unsupported API behavior or incompatible transport mappings are observable failures. Resolve against the current accepted relationship-sync design. Public method allowlists and verified principals remain mandatory.

Stop/remove only owned test processes/containers; retain useful proof tests. Back up before mutating existing data. Do not run Rust and Go on shared application state. Phase 2 consumes these contracts and proof tests; no success-returning placeholder handlers are permitted.
