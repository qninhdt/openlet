# Account and Workspace architecture scout

Read-only source review, 2026-11-03. Scope: Account, Workspace, their transport adapters, workers, data/authorization contracts, tests and immediate service callers. Read `AGENTS.md` and `docs/architecture.md`; used `codegraph explore` before scoped file discovery. No production code changed and no test execution was necessary for this source map.

Controller update after source review: execution plan is `plans/261103-architecture-service-boundaries/plan.md`; transport moved to `internal/transport/{http,grpc}`, external clients to `internal/clients/{clerk,account,letfs}`, Temporal package to `internal/jobs`. Source paths/line numbers below identify the reviewed baseline; apply those prefix mappings when implementing. The controller confirmed the accepted direction is to remove cross-service Temporal calls in favor of gRPC while preserving owner workflow durability.

## Finding and recommended boundary

The service ownership in `docs/architecture.md` is already reflected in separate databases and service modules. The important missing boundary is a reusable application service: HTTP handlers and Temporal Activities each orchestrate parts of business behavior, while `Store` combines SQL transactions, policy, authorization and graph publication. Renaming folders alone will leave this coupling intact.

Smallest complete improvement: create one application package per service, keep transport DTO conversion in HTTP/gRPC, preserve durable workflow algorithms and their serialized contracts, and move SQL/graph/provider work behind specific dependencies. Do not introduce a generic repository, framework, shared database model, or interface per method. Transaction-sensitive checks remain together with the atomic transaction that enforces them; moving all checks into a preflight would create races.

## Responsibility inventory

| Responsibility | Current owner / source | Required final owner |
|---|---|---|
| Account gateway authentication, onboarding-only subject bootstrap | `apps/account/internal/http/server.go` (`Gateway`, `Router`) | HTTP; keep shared `identity.AuthenticateGateway` |
| Profile HTTP parsing/status/representation | `apps/account/internal/http/identity.go:91`, `:103` | HTTP; explicit DTOs |
| Profile active-user lookup, self-action graph admission, patch validation/update | `identity.go:91`, `:103`, `:132`; `user/store.go:65`, `:73` | Account application service plus atomic Postgres write |
| Onboarding PUT existing-state/retry reconciliation and start | `identity.go:67` | Account application service with workflow starter dependency |
| Clerk identity mapping, concurrent ensure, lifecycle and initial-workspace binding | `user/store.go:32`, `:41`, `:51`, `:61`; `migrations/0001_initial.sql` | Postgres adapter enforcing account policy |
| Durable first workspace creation, Clerk publication order, compensation | `temporal/workflows.go:57` | Account Temporal workflow; Activities call application functions |
| Account self-relationship sync and offline paged rebuild | `user/relations.go:13`, `:50`, `:59` | Account application/rebuild operation; graph and Postgres adapters |
| Native Account service authority, ID decoding, protobuf encoding, gRPC faults | `rpc/server.go:37`, `:45`, `:64`, `:92` | gRPC transport boundary; retain in-process authority check |
| Active batch summaries, active Clerk subject to verified emails | `rpc/server.go:64`, `:92`; `user/store.go:91`, `:110`; `clerk/client.go` | Account application service; Postgres and Clerk adapters |
| Workspace HTTP identity, strict JSON, ID/header/cursor parsing and response headers | `apps/workspace/internal/http/server.go`; `http/workspaces.go:22`–`:136` | HTTP |
| Create-workspace receipt lookup, validation, Temporal admission and lost-start reconciliation | `http/workspaces.go:137` | Workspace application service |
| Workspace actor limit, durable create receipt, owner row, reserved storage IDs | `workspace/store.go:68`, `:134`, `:399` | Postgres atomic operations; policy owned by Workspace |
| Storage provisioning, reply scope validation, activation and provisioning-fence release | `temporal/workflows.go:42`, `:57`, `:85` | Durable workflow and Workspace application functions; storage client adapter |
| Workspace read action and lifecycle checks | `workspace/authorization.go:13`; `http/workspaces.go:227` | Workspace application service |
| Workspace list candidate loading, bulk graph filtering and cursor progression | `http/workspaces.go:188`; `workspace/store.go:210` | Application list operation returns visible items plus last scanned candidate; HTTP encodes cursor |
| Name changes/ownership transfer, two-action admission, limits, revision/owner invariants | `workspace/store.go:234` | Application admission/policy plus atomic Postgres operation |
| Member list authorization, bounded page, one batch Account lookup and join | `http/collaboration.go:15`; `workspace/store.go:328`; `user/client.go` | Workspace application list operation; Account client adapter |
| Member change/leave/remove policy, owner protection and revision mutation | `workspace/store.go:344`; `http/collaboration.go:61` | Workspace application service plus atomic Postgres operation |
| Invite normalize/role/token/hash/expiry/conflict/revoke/list | `workspace/invitations.go:27`, `:35`, `:86`, `:102`; `http/collaboration.go` | Workspace application/policy and Postgres adapter; HTTP returns secret once |
| Accept token shape/hash/scope, verified email fetch, lifecycle/replay/member limit and response enrichment | `http/collaboration.go:171`; `temporal/relationships.go:56`; `workspace/invitations.go:124`, `:210` | Workspace application operations; durable serialized mutation remains Temporal |
| Per-workspace durable serialization, receipt recovery, targeted graph sync | `temporal/relationships.go:16`, `:33`, `:56`, `:108`, `:155`; `workspace/mutation_receipt.go` | Temporal serialization; application mutation operation; atomic SQL receipt and graph adapters |
| Delete admission/tombstone, graph storage fence, letfs freeze/list/child deletion, final graph cleanup | `http/deletion.go`; `workspace/deletion.go`; `temporal/deletion.go` | Application admission/completion plus existing durable workflow |
| Receipt prune bounded batch and scheduled execution | `workspace/maintenance.go`; `temporal/maintenance.go` | Postgres maintenance operation and Temporal schedule/workflow |
| Offline workspace relationship reconstruction including lifecycle tombstones | `workspace/relations.go:131`, `:140`, `:173`; `cmd/server/main.go --rebuild-authorization` | Application recovery entry point; graph/Postgres adapters |
| Config validation, providers, readiness and bounded shutdown | both `internal/config`, both `cmd/server/main.go`, router readiness; Account native health | Composition roots plus transport health callbacks |

## Concrete coupling to remove

1. **Account authorization is a Gin-only operation.** `authorizeAccount` receives `*gin.Context`, calls SpiceDB, and writes HTTP failures. `user.Store.Profile` and `UpdateProfile` do not enforce it. Extract application `GetProfile`/`UpdateProfile` that preserve the current active-user lookup before graph permission check. Keep profile validation in shared account policy so alternate callers cannot accept invalid names/avatars. Do not move `workspaceCaller` out of the RPC boundary: service authority is a transport trust requirement, whereas active-user/verified-email orchestration belongs in application code.
2. **HTTP currently decides durable retry behavior.** Account `onboardingPut` resolves races between workflow start and existing completed state. Workspace `startCreate` does the equivalent receipt reconciliation. Put this logic in reusable application operations that return admission/existing state. HTTP still decides `200`/`202`, `Location`, `ETag` and representation. Preserve their different failure fallback semantics rather than creating a generic helper.
3. **List visibility and enrichment live in handlers.** Workspace list graph checks use `s.Store.Graph` directly (`workspaces.go:188`). Member handlers construct IDs, call Account, and join profiles; acceptance performs hash/scope/start/permission/profile orchestration. Application methods should own these sequences and return transport-neutral results. Keep cursor scope/base64 formatting in HTTP, but return the scanned boundary separately from filtered visible items.
4. **Temporal adapters own application work and direct SQL.** Account `Activities.EnsureUser` combines Postgres plus graph. Workspace prepare/complete/fail Activities combine SQL plus graph plus storage administration. `PrepareMutation` queries `a.Store.DB` to discover the previous owner (`temporal/relationships.go:44`); `ApplyMutation` owns receipt recovery, verified-email fetching, SQL mutation, affected-user selection, graph sync, receipt completion and return lookup. Extract these into application functions; preserve Activity names, inputs, error conversion and retry boundaries.
5. **The Store abstraction has no single responsibility.** Workspace `Store` carries graph client, pgx pool and policy settings. `Authorize` performs graph I/O; `relations.go` both queries canonical rows and writes SpiceDB. Split graph publication from SQL storage. Keep lock/revision/lifecycle recheck and update/receipt writes in one repository transaction. Service calls graph first and hands the observed version to the transaction; no graph/Clerk/Temporal calls while holding SQL locks.
6. **Domain data doubles as transport payload.** `user.Profile`, `user.Onboarding`, `workspace.Workspace`, `Storage`, `UpdateInput` contain JSON tags and are directly emitted/decoded by HTTP; several are also workflow payloads. Add explicit HTTP request/response types and conversion at the transport edge. Retain existing JSON field names/nulls, decimal strings, omitted role/error behavior, and Temporal payload schema during migration. Do not change money/byte/revision types merely for aesthetic consistency.

## Actual cross-service paths

| Path | Current mechanism | Evidence / preservation implication |
|---|---|---|
| Account -> Workspace initial create | Child Temporal workflow named `CreateWorkspace`, queue `openlet-workspace`, duplicate JSON-compatible `InitialWorkspace` struct | `account/internal/temporal/workflows.go:50`, `:90`. Workflow ID is `create-workspace/<user>/<user>`, 7-day timeout, reject-duplicate policy. There is deliberately no Account import of Workspace internals. |
| Workspace -> Account summaries/emails | Authenticated generated gRPC client | `workspace/internal/user/client.go`, `workspace/cmd/server/main.go`. Batches max 100, 10-second deadline, exact response scope/uniqueness/completeness checks; verified email lookup preserves caller context. |
| Workspace -> letfs create | Remote Temporal `CreateStorage` Activity with caller string `workspace` and generated protobuf payload | `workspace/internal/temporal/workflows.go:118`; constants in `internal/letfs/client.go`. Service authority is derived from trusted workflow caller string in `letfs/internal/temporal/provisioning.go:27`. Queues themselves are not auth boundaries. |
| Workspace -> letfs release provisioning fence | Direct authenticated gRPC from Workspace completion Activity | `workspace/internal/temporal/workflows.go:64`, `Activities.Storage`. Preserve publication -> SQL activation -> remote release -> creation receipt expiry order. |
| Workspace -> letfs deletion | Remote freeze/list/prepare/complete Activities plus `DeleteFilesystem` child workflow | `workspace/internal/temporal/deletion.go:34`; local duplicated `letfs.DeletionInput`. Freeze before enumeration, await every filesystem child, cursor/continue-as-new after 100, disconnected cancellation and abandoned child policy matter. |

This is not a uniform gRPC service boundary today. The accepted migration to gRPC should put calls in owner-local Activities invoking generated clients, and let Workspace/letfs own durable creation/deletion behind explicit admission/status contracts. Replacing a remote child workflow with a single synchronous delete RPC would lose durable wait/restart semantics. Account must start or retrieve the same deterministically keyed initial Workspace through gRPC, then durably wait for completion before Clerk publication. Workspace must admit deletion in letfs and durably observe its completion before bucket/workspace finalization. Old in-flight histories require compatible registered bridges or a recorded versioning/cutover strategy even when all newly started work uses gRPC.

## Real duplication and limits of deduplication

- Account and Workspace `http/server.go` duplicate request-ID normalization, recovery/logging, trusted-header authentication glue, problem JSON, readiness checks and Gin setup. Shared `packages/go/identity`, `telemetry`, `config` and `rpc` already exist. A small shared Gin HTTP utility can own only common mechanics; keep service router registrations, onboarding exception and health dependencies local.
- Recovery implementations differ: Workspace propagates `http.ErrAbortHandler`, Account currently swallows every panic. Do not silently choose one behavior while deduplicating; preserve it first or explicitly treat the correction as a bugfix with a regression test.
- Both services duplicate strict JSON/response helpers and Temporal ApplicationError unpacking, but Account oversized JSON is `VALIDATION`/400 whereas Workspace decoder has `REQUEST_LIMIT`/413. Domain fault-to-status mappings differ. Share low-level decode/problem construction only if these mappings remain explicit.
- Profile/summary fields are intentionally repeated across protobuf, Account and Workspace views; they are service DTOs, not a reason for shared database structs. The Workspace Account client performs essential response scope validation, not redundant conversion.
- `InitialWorkspace` and `DeletionInput` are duplicated cross-service Temporal wire shapes. Constants/DTOs can be centralized if the bridge remains. Do not import another app's `internal` package.
- Workspace `getInTransaction`, `Get` and `List` repeat projections/scanning, and activation/storage relationship methods repeat canonical SQL reads. A local typed scan/helper or one projection constant can reduce accidental field drift; no generic repository is justified.

## Practical target layout

Keep current transport package names to reduce churn; one business/application package per app, concrete infrastructure packages, no layer folders for one file:

```text
apps/account/internal/
  account/          # service, policy, types/errors, small dependency contracts
  postgres/         # SQL account/lifecycle/relationship-source operations
  authorization/    # self check/publication/rebuild graph adapter
  clerk/            # existing provider adapter
  http/ rpc/        # explicit transport DTOs, identity, errors, health
  temporal/         # deterministic workflows, starter, thin Activities
  config/
apps/workspace/internal/
  workspace/        # service/policy/types/errors, mutation/create/deletion use cases
  postgres/         # atomic transactions, receipts, keyset candidates
  authorization/    # graph checks, targeted writes and offline rebuild writes
  account/          # renamed existing user gRPC client; external Account API adapter
  letfs/            # storage adapter and any retained Temporal contracts
  http/ temporal/ config/
```

Dependencies: HTTP/RPC/Activities -> application; application -> narrow dependency contracts; concrete Postgres/graph/provider adapters implement those contracts and are wired by `cmd/server`. Workflows depend only on stable payload types and Activity names. Specific repository transactions such as `UpdateWorkspace(observed, command, receipt)` may enforce pure domain policy under lock; do not export pgx transaction handles into the application. Do not make services import Temporal just to return domain faults; the starter adapter owns Temporal SDK errors/conversion.

## Implementable change order and acceptance

1. Extract plain types/errors/policies and explicit HTTP DTO conversions without changing wire contracts; introduce application services and wire them in both `cmd/server/main.go`. Keep existing APIs temporarily only when needed to migrate callers within the same change.
2. Move handler orchestration into application methods: Account profile/self permission and onboarding; Workspace create/list/member list/invite accept/update route selection/deletion admission. Handlers retain only authenticated principal extraction, strict parsing, application call and response mapping.
3. Move Activity application sequences and direct previous-owner SQL into application methods. Preserve local-Activity preparation recording before regular mutation, receipt fingerprint of the exact prepared input, SQL commit-loss reconciliation, graph synchronization before normal success and self-removal response behavior.
4. Split concrete SQL and graph adapters, moving the existing transaction blocks largely intact. Graph-before-lock and observed revision/lifecycle recheck are acceptance conditions, not cleanup candidates. Retain advisory locks for per-owner workspace limits, one-owner DB index, late-create storage identity fences and tombstones.
5. Deduplicate proven HTTP mechanics after service behavior is isolated. Keep domain mappings/transport differences explicit. Update only the owning architecture/layout docs and affected test fixtures/imports, not historical reports.
6. Run unit tests, workflow tests, integration tests and replay checks according to each app's `package.json`: `go test ./...`; `go test -tags workflow ./internal/temporal -count=1`; `go test -tags integration ./...`; `go test -tags replay ./internal/temporal -count=1` with valid `OPENLET_HISTORY_DIR`. `check` requires gofmt and `go vet -tags integration ./...`. Build both modules and run affected e2e onboarding/workspace flows when integrating service contracts.

Preservation tests already available:

- Account: `http/server_test.go`, `routing_test.go`, `identity_integration_test.go` prove bootstrap method/path restriction, duplicate-header rejection, active-user versus graph permission and outages. `user/store_integration_test.go` proves concurrent identity convergence, immutable initial workspace binding and profile validation. `rpc/server_integration_test.go` proves workspace-only service authority, no delegated actor, active-only lookups and secret-safe failures. `temporal/workflows_test.go` proves workspace -> Clerk -> complete ordering and failure retention. `clerk/client_test.go` preserves metadata ownership and verified-only emails.
- Workspace: `workspace/store_integration_test.go` proves creation/idempotency/limit races, storage ID convergence/no rebinding, one invitation token, replay after removal, expiry and failed-workspace deletion. `authorization_integration_test.go` proves graph is authoritative, combined update needs both actions, graph calls hold no SQL lock and revision recheck rejects races. `http/authorization_integration_test.go` proves denied empty pages advance cursor and name-only update works without Temporal. `temporal/relationships_integration_test.go` proves committed SQL + lost graph acknowledgement cannot repeat transfer or increment revision twice. Workflow `relationships_test.go`, `workflows_test.go`, `deletion_test.go`, `maintenance_test.go` cover serialization/retries/continue-as-new, storage scope rejection, child waits and prune scheduling. `user/client_integration_test.go` proves exact response scope, missing/duplicate rejection, deadlines and cancellation.
- Both replay test files load histories from `OPENLET_HISTORY_DIR` and register workflows by current names. A package/folder rename is safe only while registration names and command sequences remain compatible, or versioning/migration is supplied. Mock workflow tests alone do not establish compatibility with recorded production histories.

## Unresolved questions / limits

- Cross-service Temporal removal is accepted by the controller; exact create/delete admission/status RPC shapes and in-flight history cutover remain implementation decisions. Do not discard owner durability while replacing the bridge.
- Live history fixtures and stack readiness were not inspected or executed. This report establishes source contracts, not runtime/refactor verification.

Status: DONE
Summary: Mapped every Account/Workspace responsibility, concrete transport/application/data coupling, existing duplication, cross-service mechanisms and a behavior-preserving extraction sequence.
Concerns/Blockers: Durable workflow histories and mixed Temporal/gRPC lifecycle contracts must be preserved or deliberately migrated; no source-discovery blocker.
