# Whole-code cleanup and review

Status: complete.

What this change does: removes unused application contracts, obsolete delegation and migration scaffolding from the completed Go/SpiceDB backend. Current direct filesystem APIs, durable owner workflows, supported document formats and SDK integrations remain implemented and tested.

## Scope

Reviewed first-party Go across Account, Workspace, letfs and the shared Go module; Python ingest, shared Python packaging and operational scripts; TypeScript API fixtures; protobuf/code generation, CI, containers and owning documentation. Used CodeGraph and caller searches before removing code, production/test call-graph analysis, Staticcheck, Vulture, strict TypeScript unused checks, and manual tracing of authentication, authorization, owner synchronization, filesystem publication, cancellation and recovery boundaries.

Assumed the existing deployment: multiple service/worker processes and concurrent requests/activities against shared PostgreSQL, SpiceDB, Temporal, object storage and Qdrant. Reviewed limits and synchronization at that boundary; no throughput benchmark was performed. Static analysis is evidence for the selected build configurations, not proof that every possible conditional branch is unnecessary or correct.

## Should fix — all addressed

1. **Workspace retained filesystem authorization routing** (`apps/workspace/internal/workspace/authorization.go`).
   - What this is: Workspace admission previously translated filesystem and bucket actions into storage-resource checks.
   - Problem: The filesystem proxy was deleted; every production caller now requests a Workspace action. Only obsolete tests exercised this routing.
   - Fix: Removed the routing. Updated tests to exercise membership actions and assert that a filesystem action is rejected as an invalid Workspace check.
   - If skipped: Workspace would retain storage-specific behavior after storage operations moved to letfs.

2. **Unused service-user delegation option** (`packages/go/rpc/authentication.go`).
   - What this is: A credential option allowed a nongateway service to carry user metadata.
   - Problem: No production credential enabled it; a synthetic test was its only consumer.
   - Fix: Removed the option. Tests retain scoped service access and verify that services cannot impersonate a user. The gateway still carries its verified public actor.
   - If skipped: An unused identity mode would remain available to configure and maintain.

3. **Generated HTTP gateway existed only for a test fixture** (`packages/go/rpc/errors.go`, `packages/contracts/buf.gen.yaml`, shared RPC integration fixtures).
   - What this is: Generated gateway bindings, a gateway-specific error callback and handwritten fixture HTTP byte/ZIP handlers.
   - Problem: Production HTTP uses the actual letfs adapters. Tests of the alternate adapters exercised fixture implementation instead of production behavior.
   - Fix: Removed that generator/tool, regenerated outputs, deleted the callback and alternate fixture handlers. Retained native gRPC/Envoy tests and actual letfs HTTP byte, Range, redirect, archive and cancellation tests. The shared fixture now uses standard-library unencrypted HTTP/2 instead of deprecated h2c.
   - If skipped: A second unused transport implementation and its generated code would need maintenance.

4. **Workspace RPC contract had no implementation or caller** (`packages/contracts/proto/openlet_api/workspace/v1/workspace.proto`, removed).
   - What this is: A generated `WorkspaceService.GetWorkspace` service in both languages.
   - Problem: There was no registered server or production client. Workspace lookup is public HTTP; Account creates workspaces through Temporal.
   - Fix: Deleted the source contract and regenerated Go/Python outputs. Updated packaging tests and the Account caller-isolation fixture to use an existing application RPC identity. The independent Python wheel test still passes.
   - If skipped: Consumers would receive an API that the system does not serve.

5. **Small obsolete surfaces remained after migration** (ingest worker, E2E setup, tracing tests, README and RPC/API guides).
   - What this is: HTTP-prefix stripping on the native Temporal address, an unused TypeScript import, deprecated OTel formatting, a staging comment and stale Rust/artifacts-directory documentation.
   - Problem: Current configuration uses `host:port`; the import has no consumer; the documentation contradicted current runtime and direct generated-child paths.
   - Fix: Removed prefix compatibility and the unused import, replaced deprecated test formatting, and corrected the owning documents/comments.
   - If skipped: Obsolete input handling and misleading setup/API instructions would remain.

## Kept after verification

- Document-format compatibility handles real supported DOC/PPTX inputs; parser regressions depend on it.
- Protobuf reservations prevent reuse of deleted wire field numbers; they expose no obsolete request mode or executable fallback.
- `ReleaseProvisioning` is called by Workspace creation/reconciliation to end pinned idempotency receipt retention. It is not a provision key.
- The grpc-gateway runtime import still supplies its official gRPC-to-HTTP status mapping. The generated HTTP gateway and its tool are removed.
- The Go `genproto` replacement resolves a transitive module split; it is dependency resolution, not application backward-compatibility behavior.
- Historical plans and ignored compiler caches are not active source. No application dependency was replaced with a handwritten provider client.

## Validation

Logs are local execution evidence under `.local/review-*`; durable outcomes are recorded here after completion.

- `pnpm contracts:generate` and `pnpm contracts:check`: pass; removed outputs are reproduced from the remaining contracts.
- `pnpm check`: pass, all 11 tasks plus script Ruff checks.
- `pnpm test`: pass, all 9 tasks plus 21 operational/bootstrap tests; ingest unit suite includes 95 passing tests.
- `pnpm build`: pass, all 7 tasks including both Python distributions.
- Strict E2E TypeScript unused-local/parameter check: pass.
- Current Staticcheck correctness/deprecation/unused checks across four Go modules and integration/workflow/replay tags: pass. Style and quick-fix suggestions are excluded.
- Production Go deadcode analysis: no unreachable first-party functions. Test-inclusive analysis with integration/workflow/replay tags: no findings.
- Python Vulture at 80% and 100% confidence: no findings.
- Shared native RPC/Envoy race integration: pass.
- Workspace full integration: pass. Account full integration: pass after correcting the fixture method allowlist.
- Independent Python wheel integration: pass. Focused ingest-worker tests: 2 pass.
- Full letfs race integration: pass across server, config, filesystem, gRPC, HTTP, search, storage and Temporal packages.
- Native workflow tests: all 3 tasks pass.
- Full API/recovery journey: all 34 tests pass (8.2 minutes).
- Fresh integration-history replay for letfs and fresh API-history replay for Account, Workspace and letfs: pass.
- Final diff whitespace check: pass. Test processes completed and owned Docker containers were removed.

The preinstalled Go analyzers could not parse Go 1.27; current versions were installed into ignored local tooling without changing repository dependencies. One Account fixture initially selected the public health method in an application-only allowlist; it was corrected to the existing filesystem RPC and the full Account integration run passed.

## Verdict

Verdict: Ship. All verified findings above are fixed; no additional verified unresolved defect was found in the inspected scope. No commit, push or deployment was performed.

Not checked: live Clerk, external storage-provider behavior, paid LLM quality and remote CI. Local provider fixtures exercise transport/orchestration contracts without claiming those external checks.
