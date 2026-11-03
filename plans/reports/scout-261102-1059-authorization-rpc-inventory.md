# Authorization and RPC inventory

Date: 2026-11-02, Asia/Saigon. Read-only planning evidence; no implementation or test execution. Source references below are repository-relative `file:line` references. CodeGraph was used before code navigation; current source, migrations, tests and existing docs were then inspected.

## Accepted boundary

The target follows `brainstorm-261102-1032-go-grpc-filesystem-authorization.md`: official SpiceDB SDK clients directly in owning apps, no Access service; per-owner PostgreSQL canonical facts and durable projection intent/version/ack; Temporal projection/reconciliation; built-in role-to-action catalog; action/resource checks at actual application boundaries; no membership status or projection-lag workspace-wide gate. API success waits for graph acknowledgment, while a timeout may follow a committed canonical change. Dev reset and fresh histories are allowed. This report inventories behavior that the plan must preserve; proposed action names below are coverage labels, not a newly approved schema.

## Current Account operations and identity

All route registrations: `apps/account/internal/http/server.go:60`. `/v1/*` trusts only a single matching gateway credential and a single nonempty Clerk subject; normal routes additionally require a single valid non-nil internal UUID (`server.go:82`). Bootstrap exemption is exactly `/v1/me/onboarding` (`server.go:94`), not an arbitrary missing-ID allow path.

| Current operation | Actual admission/ownership | Source and migration implication |
|---|---|---|
| PUT `/v1/me/onboarding` | Verified Clerk subject; internal UUID optional | `internal/http/identity.go:63`: ensure user, return 202 while provisioning; dispatch failure is deferred, not rollback. Bootstrap identity must exist before graph user relations. |
| GET `/v1/me/onboarding` | Same verified subject; caller-only | `identity.go:55`, `internal/user/store.go:32`: lookup by Clerk subject; active status signals session refresh. |
| GET `/v1/me` | Authenticated internal user, own profile | `identity.go:80`, `store.go:88`: active Account row only. |
| PATCH `/v1/me` | Same own-user scope | `identity.go:89`, `store.go:96`: validates display name/avatar; no login email mutation. |
| GET `/internal/v1/users?ids=...` | Workspace service credential, no end-user identity required | `identity.go:110`, `identity.go:118`, `store.go:114`: unique non-nil IDs, 1..100 at store; active-user summaries only. |
| GET `/internal/v1/users/{id}/verified-emails` | Workspace service credential | `identity.go:149`: resolves active user's Clerk subject, calls Clerk for verified addresses. Trusted email authority must remain Account/Clerk. |
| GET `/live`, `/ready` | No user authorization | `server.go:46`: readiness checks PostgreSQL and Temporal with 3s deadline. Migrate internal health to standard gRPC health as agreed. |

Account's DB, not graph, protects unique Clerk subject and initial-workspace lifecycle (`apps/account/migrations/0001_initial.sql:2`). `EnsureUser` uses unique insert to converge concurrent first logins (`internal/user/store.go:41`). Profile/summary/subject methods restrict to active rows (`store.go:88`, `store.go:114`, `store.go:133`). Those lifecycle predicates are invariants, not role checks.

Bootstrap is already durable cross-owner orchestration, **not an internal Account→Workspace HTTP call**. `OnboardUser` calls child `CreateWorkspace` on `openlet-workspace` with stable `initial-workspace/<user>` and `{actor_id,request_key,name}` (`apps/account/internal/temporal/workflows.go:50`, `:77`), saves the returned ID, publishes backend-controlled Clerk metadata, then completes Account (`:83`). Keep authenticated service/job authority for this non-public path. It cannot require ordinary membership in a workspace that does not exist yet, and must not interpret missing graph data as permission. Existing native Temporal child orchestration can remain; only genuine synchronous app calls need gRPC conversion.

## Current Workspace non-file operations

Routes: `apps/workspace/internal/http/server.go:61`. Every `/v1/*` operation requires the gateway credential, Clerk subject and internal user UUID (`server.go:86`). Membership absence is hidden as `NOT_FOUND`; insufficient current role is `FORBIDDEN` (`internal/workspace/store.go:184`). Most operations also require active lifecycle (`store.go:206`); this lifecycle rule is separate from the rejected projection-lag gate.

| Operation | Owner | Editor | Viewer | Other / invariant | Evidence |
|---|---|---|---|---|---|
| POST `/workspaces` | Yes | Yes | Yes | Any onboarded user; owner-count limit + idempotency; new actor becomes Owner | `internal/http/workspaces.go:132`; `internal/workspace/store.go:70`, `:113`, `:127` |
| GET `/workspaces` | Own memberships | Own memberships | Own memberships | Nondeleted workspaces only; includes nonactive lifecycle states, keyset by workspace ID | `http/workspaces.go:170`; `workspace/store.go:245` |
| GET `/workspaces/{ws}` | Yes | Yes | Yes | Membership required; **no active-state check**; retained Owner can read deleted tombstone | `http/workspaces.go:190`; `workspace/store.go:219`; `workspace/deletion.go:92` |
| PATCH `/workspaces/{ws}` name | Yes | No | No | Active + current revision + name validation | `workspace/store.go:269`, `:286` |
| PATCH `/workspaces/{ws}` owner_id | Yes | No | No | Current member target, not self; target owned-workspace limit; old Owner becomes Editor atomically | `workspace/store.go:293` |
| DELETE `/workspaces/{ws}` | Yes | No | No | Active **or failed** may begin deletion; repeated deleting/deleted accepted before revision recheck | `workspace/deletion.go:20`, `:41`, `:44`, `:51` |
| GET `/workspaces/{ws}/members` | Yes | Yes | Yes | Active; bounded list plus one Account batch summary call | `http/collaboration.go:12` |
| PATCH `/workspaces/{ws}/members/{user}` | Yes | No | No | Active/current workspace revision; only editor/viewer; cannot change existing Owner via this route | `workspace/store.go:352` |
| DELETE `/workspaces/{ws}/members/{user}` | Yes | Self only | Self only | Active/current revision; cannot remove Owner, including Owner self | `workspace/store.go:361`, `:368`, `:377` |
| POST `/workspaces/{ws}/invitations` | Yes | No | No | Editor/viewer grant only; normalized email; raw token once | `workspace/invitations.go:34`, `:48` |
| GET `/workspaces/{ws}/invitations` | Yes | No | No | Active; **all statuses**, not only pending; metadata, no raw token | `http/collaboration.go:121`; `workspace/invitations.go:81` |
| DELETE `/workspaces/{ws}/invitations/{id}` | Yes | No | No | Active; pending only; scope bound to workspace | `workspace/invitations.go:97` |
| POST `/memberships` | Any onboarded user | Any onboarded user | Any onboarded user | Invitation token + trusted matching verified email, active destination, limits and replay rules | `http/collaboration.go:168`; `workspace/invitations.go:115` |
| GET `/live`, `/ready` | N/A | N/A | N/A | Unauthenticated process health; DB + Temporal readiness | `http/server.go:44` |

**Do not implement the illustrative matrix as exhaustive.** It omits self-leave, workspace create/list, invitation acceptance, account self access, copy-monitor actor/owner scope, upload ownership and bootstrap/job authority. Model self-leave as an action checked on the caller's own membership (for example `membership.leave`) separately from Owner member administration, retaining the SQL Owner invariant. Never grant Editors arbitrary member removal because they can leave themselves.

The implementation deliberately distinguishes discovery/status reads from active operation admission. Replacing `Get`/`List` with the current `Authorize("viewer")` would break provisioning/failure/deletion status and terminal tombstones. Preserve this distinction when replacing SQL authorization joins with graph checks and filtered list candidates.

## File facade: exhaustive public routes and role evidence

All registrations are in `apps/workspace/internal/http/files.go:117`. File-scope mapping helper `http/nodes.go:24` currently authorizes role, then reads Workspace's filesystem mapping. Direct public letfs removes that facade; it must preserve each action, resolve the typed filesystem/resource binding, then authorize the resolved target.

| Public suffix under `/v1/workspaces/{ws}` | Actual minimum role / additional scope | Owning check |
|---|---|---|
| POST `/nodes` create directory/inline file | Editor | `http/nodes.go:42` |
| POST `/nodes` source_id copy | Editor; source revision and idempotency; same FS | `http/nodes.go:58` |
| GET `/nodes` list | Viewer | `http/nodes.go:90` |
| GET `/nodes:resolve` | Viewer | `http/files.go:121`; `http/nodes.go:90` |
| GET `/nodes/{node}` stat | Viewer | `http/nodes.go:90` |
| GET `/nodes/{node}/content` | Viewer; detached/trash descendants remain hidden | `http/nodes.go:90`; `docs/api-contracts.md` |
| GET `/nodes/{node}/processing` | Viewer | `http/nodes.go:90` |
| POST `/nodes/{node}/processing-runs` | Editor; idempotency key | `http/nodes.go:163` |
| PATCH `/nodes/{node}` rename/move | Editor; If-Match | `http/nodes.go:117` |
| PUT `/nodes/{node}/content` | Editor; If-Match; bounded inline bytes | `http/nodes.go:117`, `:150` |
| DELETE `/nodes/{node}` trash | Editor; If-Match | `http/trash.go:12` |
| GET `/trash-entries` and `/{entry}` | Viewer; metadata only | `http/trash.go:29` |
| POST `/trash-entries/{entry}:restore` | Editor; current entry identity | `http/trash.go:31`, `:44` |
| DELETE `/trash-entries/{entry}` purge | Owner; current entry identity | `http/trash.go:34` |
| GET `/search` filename; POST `/search` semantic | Viewer | `http/search.go:28`, `:45` |
| POST `/files/batch-stat` | Viewer; 1..100 locators | `http/files.go:49` |
| GET `/nodes/{node}/archive` | Viewer | `http/archive.go:10` |
| POST `/uploads` | Editor; create/overwrite validation, overwrite revision | `http/uploads.go:19` |
| GET `/uploads/{upload}` status | Editor **and originating actor** | `http/uploads.go:70`; `apps/letfs/src/fs/uploads.rs:154` |
| GET `/uploads/{upload}/parts` | Editor **and originating actor** | Same as above |
| PUT `/uploads/{upload}/completion` | Editor **and originating actor** | Same as above |
| DELETE `/uploads/{upload}` abort | Editor **and originating actor** | Same as above |
| GET `/copies/{copy}` | Current Viewer plus original actor **or current Owner** | `http/nodes.go:187`; `apps/letfs/src/http/nodes.rs:129`; `apps/letfs/src/temporal/copy_workflow.rs:273` |
| GET `/storage` | Viewer | `http/files.go:73` |

Owner includes all Editor/Viewer permissions; Editor includes Viewer. Critical nuance: Owner does not inherit another actor's upload capability. letfs upload lookup requires `actor_id` equality and excludes processing uploads (`apps/letfs/src/fs/uploads.rs:160`). Copy monitor is actor-or-current-Owner, not every Viewer and not historical Owner. The target must replace the forwarded role string with an action/resource decision (e.g. copy read-own versus read-any) while preserving current membership admission and actor binding. Candidate actions beyond the brainstorm include `file.list`, `file.stat`, `file.resolve`, `file.processing.read`, `file.archive`, `copy.read_own`, `copy.read_any`, `upload.create`, `upload.read`, `upload.sign_parts`, `upload.finalize`, `upload.abort`, `storage.read`; consolidate only if the full behavioral contract remains explicit.

## Permission checks versus invariants

Replace role decisions and membership visibility with graph action/resource checks: SQL membership joins in `Get`/`List`; role comparisons in `checkAccess`, `ChangeMember`, `BeginDeletion`; `Authorize` at public handlers; trusted `X-Workspace-Role` copy-monitor bypass. Keep canonical membership/roles for domain mutation, display and rebuild; removing them is incompatible with the accepted authority model.

Keep these owner-owned rules, including under concurrent mutation:

- Exactly one Owner: unique partial index provides **at most one** (`apps/workspace/migrations/0001_initial.sql:83`); transaction creation/transfer/removal protocols preserve **at least one** (`store.go:127`, `:315`, `:377`). Do not claim the index alone proves exactly one.
- Workspace mutation revision, workspace locks, owned-workspace/member limits, lifecycle transitions and owner-readable tombstone (`store.go:184`, `:290`, `:298`; `deletion.go:20`). Graph network calls must not occur while retaining SQL locks. Planning must explicitly preserve the desired concurrent authorization/revision ordering; a precheck alone is not a SQL transaction.
- Invitation validity: cryptographic random 32-byte token; SHA256 only stored; role cannot grant Owner; normalized verified email from trusted Account; pending/expiry/revocation/accepted-user checks; active Workspace; member capacity (`invitations.go:26`, `:65`, `:115`). Existing member acceptance keeps their existing role (`:173`); accepted replay is valid only for the same still-member actor and cannot recreate removed membership (`:157`).
- Pending invitation duplicate: same normalized email/role returns existing metadata without token; different role conflicts; expired pending record is expired before replacement (`invitations.go:51`, `:55`). Listing returns every status (`:82`).
- Filesystem/bucket ownership, same-FS source/destination, path/mount/cwd and node ancestry, artifact immutability, generation/attempt fences, transfer actor scope, quota/accounting, expected target/parent identity, revisions, bounded limits and cleanup must stay with letfs. A workspace permission does not validate an arbitrary FS/mount supplied by a client.
- Authenticated caller principal and scope validation cannot be replaced by trusting payload actor/job IDs. Shared trust-boundary credentials do not provide per-domain SpiceDB write isolation; document that accepted trust assumption accurately.

## Actual internal transports and callers

| Caller → owner | Current operation and source | Required migration |
|---|---|---|
| Workspace → Account | `Summaries`: GET `/internal/v1/users?ids=...`; members and accepted-membership response | `apps/workspace/internal/user/client.go:40`; callers `http/collaboration.go:43`, `:196`; generated bounded batch RPC |
| Workspace → Account | `VerifiedEmails`: GET `/internal/v1/users/{id}/verified-emails`; invitation accept | `user/client.go:76`; caller `http/collaboration.go:181`; authenticated service RPC; no untrusted caller-provided verified addresses |
| Workspace → letfs | Storage usage GET `/internal/v1/quota-buckets/{bucket}` | `http/files.go:89`; authenticated gRPC with bucket scope |
| Workspace → letfs | Every file route above; `/internal/v1/filesystems/{fs}/nodes`, copies, uploads, trash, files/batch-stat, files/search, files/semantic-search, archive | `http/files.go:146` and listed handler files; eliminate public proxy; expose filesystem-scoped public letfs methods directly |
| Account → Workspace | `CreateWorkspace` child workflow, initial owner provisioning | `apps/account/internal/temporal/workflows.go:77`; keep durable SDK orchestration, use authenticated owner application/RPC boundaries as needed |
| Workspace → letfs | Named remote Activities for provision/release/freeze/list/complete bucket; filesystem-delete child workflows | `apps/workspace/internal/letfs/client.go:5`; `internal/temporal/workflows.go`; `internal/temporal/deletion.go`; these files are JSON Temporal contracts, **not HTTP clients** |

`user.Client.request` uses Workspace bearer, 10s timeout, no redirects and bounded 1 MiB response (`internal/user/client.go:23`). Summaries verifies returned IDs exactly: no unexpected/duplicate/missing items (`:57`). Preserve this contract through protobuf handling; Account itself returns only active rows and may omit nonexistent/inactive users. Avoid treating proto zero values as successful absent identities.

Workspace's generic proxy forwards service bearer + validated actor, optional trusted current-owner role, Range/If-Match/Idempotency-Key, bounded body/response headers, and rewrites internal Location (`http/files.go:146`). Normal deadline is 2 minutes, archive 1810s with response-write deadline; no redirect follow (`:171`). It streams body and aborts incomplete responses (`:198`). Direct letfs HTTP/native gRPC parity needs concrete byte/range/redirect/ZIP/cancel mappings rather than deleting these contracts with the proxy.

Current credentials: `WORKSPACE_SERVICE_TOKEN` is shared by Workspace→Account and Workspace→letfs (`apps/workspace/internal/config/config.go:33`); Account checks it in `http/identity.go:110`. Trusted public identity uses a different `GATEWAY_TOKEN`. gRPC must authenticate caller principal separately from user/job delegation and allow only the caller's legitimate methods/scopes. Public native gRPC and HTTP must invoke the same authorization-enforcing application functions, even if an in-process HTTP gateway bypasses server interceptors.

## Exact existing app files affected

These are verified paths, not proposed filenames for new modules:

- Workspace transport removal/replacement: `apps/workspace/internal/http/{server,workspaces,collaboration,deletion,files,nodes,uploads,trash,search,archive}.go` (brace notation expands to ten exact existing files); `apps/workspace/internal/user/client.go`; `apps/workspace/cmd/server/main.go`.
- Workspace canonical authorization/lifecycle/projection integration: `apps/workspace/internal/workspace/{store,invitations,deletion,reconciliation}.go`; `apps/workspace/migrations/0001_initial.sql`; `apps/workspace/internal/temporal/{workflows,deletion,reconciliation}.go`; `apps/workspace/internal/letfs/{client,deletion}.go`. Reset permission permits baseline rewrite; record that choice rather than silently assuming production migration compatibility.
- Account RPC/identity/bootstrap: `apps/account/internal/http/{server,identity}.go`; `apps/account/internal/user/store.go`; `apps/account/internal/temporal/workflows.go`; `apps/account/cmd/server/main.go`; `apps/account/migrations/0001_initial.sql` if canonical account projection intent is required. Clerk's external HTTP client is preserved.
- Shared Go foundation/config/build: `go.work`, `go.work.sum`, `apps/{account,workspace}/go.mod`, their `go.sum`, `apps/{account,workspace}/internal/config/config.go`, corresponding `config_test.go`, app `Dockerfile` and `package.json`. Both modules currently target Go 1.27.3. gRPC v1.83.2, protobuf v1.36.11 and grpc-gateway v2.29.0 are already transitive/available through current modules; direct dependencies and shared module need canonical tooling updates, not invented independent versions.
- Boundary/regression tests: `apps/account/internal/http/{server,routing,tracing}_test.go`, `apps/account/internal/user/store_integration_test.go`, `apps/account/internal/temporal/{workflows,replay}_test.go`; `apps/workspace/internal/http/{server,routing,tracing}_test.go`, `apps/workspace/internal/workspace/{policy,store_integration}_test.go`, `apps/workspace/internal/temporal/{workflows,deletion,replay}_test.go`; telemetry package/test extraction as actual shared contract requires.
- Public/system callers and contracts: `contracts/public/openapi.yaml`, `contracts/internal/openapi.yaml`; `e2e/tests/api/{gateway,onboarding,workspaces,files,uploads,streaming,processing,recovery,backup-recovery,telemetry}.spec.ts`; `e2e/fixtures/api-test.ts`, `e2e/setup/{environment,settings}.ts`; `infra/config/envoy.template.json`; `infra/compose/{dev,e2e}.yaml`; `scripts/bootstrap/{configure,test_configure}.py`; `.github/workflows/check.yaml`; root package/build task configuration. Infrastructure and letfs/Python rename scope are inventoried by the controller's other scouting work.
- Smallest owning docs to reconcile after implementation: `docs/architecture.md`, `docs/api-contracts.md`, `docs/workflows.md`, `docs/data-model.md`, `docs/setup.md`, `docs/testing.md`, `docs/operations.md` (operational route changes require source-backed updates).

New protobuf source/codegen configuration, `libs/go` module, SpiceDB schema and projection implementation do not exist in these apps today; assign concrete new filenames in the implementation plan after choosing the contract layout. Do not pretend `apps/workspace/internal/letfs/client.go` is a synchronous lifecycle client that can merely swap HTTP transport.

## Existing checks and missing acceptance evidence

Per-app `package.json`: `go test ./...`; `go test -tags integration ./...`; `go test -tags workflow ./internal/temporal -count=1`; `go test -tags replay ./internal/temporal -count=1`; `go build -o bin/<app> ./cmd/server`; `check` is gofmt validation plus `go vet -tags integration ./...`. Run from the app directory or use repository package scripts. Native Testcontainers integration uses actual `0001_initial.sql` and PostgreSQL 18.6, not mocked SQL (`apps/account/internal/user/store_integration_test.go:91`).

Existing evidence to preserve/update:

- Role hierarchy/lifecycle unit table: `apps/workspace/internal/workspace/policy_test.go:9`.
- Workspace collaboration/transfer/owner-removal/tombstone test: `store_integration_test.go:19`; concurrent owner limit `:95`; concurrent invitation one-token/expiry/replay-after-removal `:159`; receipt expiry `:221`; failed provisioning deletion `:285`.
- Account concurrent first-login/profile/lifecycle: `apps/account/internal/user/store_integration_test.go:19`.
- Gateway/bootstrap/unknown-path authentication: Account `internal/http/server_test.go:11`, `:43`; corresponding Workspace tests; duplicate headers and recovery in `routing_test.go`.
- Redirect versus object-byte relay and incomplete ZIP/cancellation: Workspace `internal/http/server_test.go:94`, `:132`.
- System checks in `docs/testing.md`: `pnpm check:e2e`; `pnpm --dir e2e exec playwright test --project=api`; exported current histories with `OPENLET_HISTORY_DIR` and native replay. Shared auth/transport changes require real Envoy smoke and public/native-gRPC bypass tests.

Required new proof cannot be supplied by current SQL tests: complete role/action/resource matrix on real SpiceDB; denied foreign FS/mount and native/direct-HTTP bypass; bootstrap principal restrictions; authenticated caller/job scope; actor-only uploads and copy actor/current-owner behavior; transfer preserves exactly one canonical Owner plus atomic graph role swap; self-leave; grant/revoke timeout after SQL commit and successful API followed by fresh inherited checks; duplicate/stale/late projection fencing; SpiceDB check outage fails closed; projection outage never reports the pending mutation as successfully synchronized (old graph grants may persist under the accepted no-gate design); startup/reconciliation after commit-start gap; delete/revoke during rebuild; graph reset and rebuild from each owner DB without reverse-importing graph facts.

## Unresolved design checks for the plan

1. Final action identifiers and typed resources must cover the exceptional operations above; the brainstorm's matrix is illustrative only.
2. Define list semantics during projection lag (canonical membership candidates versus effective graph visibility), bounded pagination after graph filtering, and tombstone/status access. No added membership status or workspace-wide projection gate.
3. Define native gRPC versus public HTTP error mapping for hidden scope, preconditions, ambiguous committed timeout, copy-expired status and streamed abort; verify binary/range/ZIP mappings empirically.
4. Spike source-aggregate graph write fencing and consistency, including inherited filesystem checks. Stable workflow identity or an SQL version precheck alone does not fence a late SDK write.
5. Assign explicit bootstrap, owner-service provisioning and Temporal job authorities. No unauthenticated/missing-graph allow fallback.

Status: DONE_WITH_CONCERNS
Summary: Inventoried all current Account/Workspace public routes, internal HTTP calls, durable cross-owner paths and role/scope exceptions with source evidence. Listed existing owner files/tests and mandatory migration acceptance gaps.
Concerns/Blockers: No blocker to planning; list consistency, graph fencing and transport mappings require explicit contract/spike gates. No code, tests, services or live provider behavior were changed or executed.
