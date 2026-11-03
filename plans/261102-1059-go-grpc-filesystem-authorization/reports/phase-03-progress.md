# Phase 3 implementation evidence

Status: in progress. The authorized seven-phase migration is incomplete. No deployment, existing database mutation, commit or push occurred in this slice; SQL/graph fixtures and the bootstrap Compose project were isolated and cleaned up.

## Authorization correction implemented

Removed all six rejected SQL authorization catalog/ledger tables and their role foreign key from the Workspace baseline. Removed their catalog, journal, waiter and Temporal projector implementations, shared `authz.Projection`, its implementation-specific tests and the four projection marker schema definitions. Existing business revisions, receipts and lifecycle constraints remain. Native role/inheritance/atomic-transfer coverage is retained in `packages/go/authz/relationships_integration_test.go`.

Repository `packages/contracts/authz/roles.json` owns built-in capabilities. The existing `authz-schema` initializer validates it before connecting, initializes/verifies schema and synchronizes only `role` capability tuples. `--check` detects drift without changing it. Policy changes are one native graph transaction under the documented deployment writer fence. Membership/resource tuples survive policy repair. Oversized unexpected policy drift fails explicitly before exceeding the pinned server's 1,000-update limit. The bootstrap image carries both contract files; no SQL policy catalog exists.

Shared `BulkCheck` uses native `CheckBulkPermissions`, fully consistent reads and bounded candidates. It matches each returned request to the requested resource/action/subject, preserves candidate order and rejects missing, duplicate, foreign, partial-error or malformed results without returning partial allows.

## Workspace native synchronization primitive

`Store.SyncRelationships` reads published grant links before taking a read-only repeatable SQL snapshot. It stages role groups identified by existing workspace ID/business revision/lifecycle/role, then atomically switches effective grants, enabled state and storage inheritance using native relationship preconditions. No new SQL state, graph marker type, saved grant command, event ledger or acknowledgment record is introduced. Staging is split at the native update bound, permitting existing large memberships. Retired groups lose access before deletion.

Real PG/SpiceDB tests delay an older SDK write before native publication, publish a newer downgrade/transfer, then release the old request: its precondition fails and independently checked access remains revoked. A graph write with a deliberately lost response is also replayed after a newer removal and rejected; a fresh synchronization reads current SQL instead. Lifecycle status distinguishes deleting/deleted even when existing business code does not increment revision on completion. More than 1,000 members stage without partial access, and a fenced erased graph rebuilds idempotently from business rows.

Review reproduced a defect where lowering `MAX_MEMBERS` blocked synchronization of existing members (`STATE_CONFLICT` in the large-membership test). Fixed the owner snapshot to preserve existing membership data and the exactly-one-Owner invariant; the configured limit remains an admission rule. The same regression test remains required.

The primitive is now wired into Workspace creation/deletion, failed-creation cleanup, post-mutation synchronization workflows and periodic canonical reconciliation. Public Update/ChangeMember/AcceptInvite wait for a current-state sync workflow before normal success. The workflow ID uses the existing workspace/revision/lifecycle; concurrent callers can join a covering run and later runs may repeat idempotently. The only activity input is workspace ID; every retry rereads business state. A request that times out after mutation receives an explicit committed/incomplete-sync error, while durable work continues. Whole-system stale-write/restart acceptance for all mutations remains required.

Canonical owner scans read IDs in keyset pages of 100, including nonactive identities and workspace tombstones. Continue-As-New carries only the last ID and an aggregate failure flag. A bad resource does not starve later IDs; the full scan fails if any item failed. The former four-minute whole-execution deadline is removed so later pages can actually run. Startup updates an existing schedule's owned action while preserving operator timing/state. No SQL sync cursor or permission ledger is added.

Workspace reconciliation cleans abandoned role-group staging in bounded native pages/deletions. Cleanup excludes groups belonging to the current canonical revision/lifecycle and uses a native MUST_NOT_MATCH grant precondition on each deletion. A concurrently published group survives; partial deletion retries find member-only remnants. Real tests cover >1,000 abandoned relationships, foreign-resource isolation, idempotent cleanup, publication concurrent with cleanup and canonical staging awaiting publication.

## Account and dependency runtime adoption

Account derives the immutable self relationship from an existing user ID. Onboarding writes it before publishing Clerk metadata and completing active status; the already-active workflow path repairs it without recreating Workspace. Profile GET/PATCH use native AccountRead/AccountUpdate checks. Missing/inactive resources retain 404 semantics; active users without the relationship get 403, and graph outage returns 503 before any profile effect. Verified subject-only onboarding remains available.

Both app runtimes load expected schema/policy from their image, connect directly to SpiceDB with the existing native RPC transport, and verify contracts at startup/readiness without repairing them. Account native gRPC health also fails on policy drift. Compose supplies the private endpoint and credential. Account's standalone Go module explicitly declares authzed-go; this avoids relying on go.work to hide a missing image dependency.

Workspace role/action admission, stable preallocated storage IDs, full mutation restart/replay evidence and complete rebuild CLI adoption remain unfinished. Do not interpret the runtime work above as Phase 3 completion.

## Verification

- PASS: shared authz/initializer unit tests, including policy parsing and bulk-result scope/error cases.
- PASS: `go -C packages/go test -tags integration ./authz ./cmd/authz-schema -count=1` against PG18.6/SpiceDB1.57.0; the later policy-bound regression also passed its focused real integration run.
- PASS: shared authz/initializer unit race checks and integration-aware vet.
- PASS: Workspace existing SQL integration suite after removing rejected tables; the new relationship tests have separate real race-enabled evidence.
- PASS: `go -C apps/workspace test -race -tags integration ./internal/workspace -run TestIntegrationRelationshipSync -count=1` (16.429s), including the reproduced/fixed lower-admission-limit regression.
- PASS: native Account RPC integration and Workspace summary/email client integration; migrated Account private HTTP remains removed.
- PASS: actual development graph bootstrap build/start/initializer/check/credential failure, using `uv run --locked --package openlet-processor pytest scripts/bootstrap/test_graph.py -q -k native_graph_startup` (1 passed, 1 unrelated case deselected).
- PASS: `PATH=/usr/local/go/bin:$PATH pnpm contracts:check`; the initial attempt lacked Go in PATH and was rerun with the installed toolchain.
- PASS: `git diff --check` and scoped source scan for rejected SQL/graph framework identifiers.
- PASS: Workspace full unit/compile suite, integration-aware owner vet and plan validation/parse; progress at that earlier checkpoint was 22/65 tasks, 2/7 phases complete. The self/bootstrap criterion is now checked: 23/65 tasks; phases remain 2/7 complete.

Cook's conditional simplifier reviewed the policy/shared-check slice without edits; its native write-limit concern was fixed and tested. The owner primitive received an inline source/security review using `ak-code-review`; no independent owner-runtime review or complete API/restart/replay suite is claimed for this unfinished phase. Current full-migration acceptance remains pending.

## Additional owner-runtime evidence

- PASS: real Account SQL/SpiceDB self-relationship identity/scope/idempotency/rebuild checks; native RPC readiness detects role policy removal.
- PASS: real Account profile HTTP checks (including unknown identity 404, missing self relationship, revoke, graph outage, no denied writes and bootstrap availability), race-enabled.
- PASS: real canonical owner keyset scans crossing 100 IDs and including failed/deleted records.
- PASS: race-enabled Account/Workspace workflow suites for onboarding sync ordering/failure, creation ordering, deletion ordering/failure, scan continuation/failure aggregation and native current-state activity retry.
- PASS: real abandoned-group cleanup/in-flight publication/canonical-staging tests; native partial deletion/page behavior is verified against the pinned server.
- PASS: standalone GOWORK=off Account and Workspace unit/compile suites; integration-aware vet, shared contract unit tests and E2E TypeScript check.
- PASS: real public onboarding and Clerk retry journeys, with their dependent coordinated recovery test: 3 passed (3.1m). This includes actual image build/start, PG-backed Temporal and graph. An initial image build exposed Account's missing explicit authzed-go module entry; tidy fixed it. An initial gateway setup exposed unknown Account ID returning 403; resource-first admission restored the existing 404 contract and gained a regression test.
- PASS: latest Workspace/onboarding/gateway suite plus dependent coordinated recovery: 11 passed (3.2m). Actual journeys include transfer, membership acceptance, concurrent admission, Temporal outage and owner reconciliation. This run includes the new post-mutation sync workflow, initial provisioning sync and cleanup-aware reconciliation. It is not acceptance for Workspace graph action admission, which remains unfinished.
- Cook conditional simplifier reviewed the scoped owner-runtime slice read-only: no concrete defect or worthwhile simplification. Later staging cleanup and mutation dispatch changes have inline review/tests; no second independent pass is claimed.

Owned fixtures: all tool-started Go test processes completed; the API runner removed its disposable Compose resources. A stopped storage fixture left by the deliberately interrupted earlier gateway-readiness run was verified as belonging to that run and removed with its disposable networks/volumes before retry. No existing development database was reset.

## Workspace action admission and offline rebuild

Workspace reads, mutations and the transitional file facade now use typed SpiceDB actions. SQL role-based allow/deny helpers are removed. Resource resolution precedes the graph check; mutations recheck membership/revision/lifecycle under the Workspace row lock without a graph RPC inside the transaction. Combined rename/transfer requires both actions; copy admission requires both `copy_create` and source `node_read`. Canonical role reads remain for membership data, one-Owner invariants and admission limits. The transfer transaction demotes the actual canonical Owner, independent of the actor's displayed role.

List candidates are bulk-checked and cursors advance by the last scanned candidate, including empty filtered pages. File handlers reuse the IDs returned by their authorization check instead of querying storage again. Copy monitoring sends the temporary Rust inspection assertion only after native `copy_inspect_any` succeeds; a SQL Owner cannot manufacture it.

`ReserveStorage` persists bucket/filesystem UUIDv7 identities in the existing Workspace row. Concurrent reservations return the same IDs; activation rejects a different bucket/filesystem/root and deletion retains the references. This is staged for the coordinated Go cutover: the current Rust remote provisioning Activities remain unchanged and do not invoke reservation. No new reservation table, provision key, graph catalog or mapping in letfs was added.

Account and Workspace support `--rebuild-authorization` in their existing binaries. These commands scan canonical keyset pages and synchronize relationships without starting listeners, Temporal workers or cross-owner RPC clients. Workspace also cleans retired groups. The existing recovery CLI adds `rebuild-authorization`, fences writers before rebuild, initializes repository schema/policy and leaves API admission stopped until explicit resume. Resume itself fences existing writers, verifies graph policy and runs both owner rebuilds before starting remaining dependencies/writers. Failures do not reopen admission.

Measured checks for this slice:

- PASS: Account full race-enabled integration suite (profile HTTP, native RPC, SQL and graph); self/rebuild tests also independently pass with more than 100 identities.
- PASS: Workspace owner/HTTP/Account-client race-enabled integration packages (75.206s / 10.562s / 1.054s). Later source-node copy admission has a fresh HTTP integration pass (14.560s).
- PASS: real concurrent transfer/transfer, transfer/self-leave and transfer/removal (8.929s), preserving one canonical Owner and synchronized graph capability parity.
- PASS: storage reservation concurrency/rebinding/lifecycle proof (4.490s).
- PASS: erased-graph rebuild crosses 100 canonical records, includes tombstones, survives a deliberately interrupted third publication and repeats idempotently; Account/Workspace rebuilds reject canceled contexts.
- PASS: Account/Workspace race-enabled workflow suites (1.408s / 8.084s); owner readiness/vet, TypeScript, recovery CLI unit tests (10) and diff whitespace checks.
- API E2E and new synchronization/reconciliation replay histories are being verified. A previous full run passed 31/32 cases; its only failure was Workspace gateway warming after recovery. The recovery handoff now waits for both owner routes. That added assertion exposed a subject-only fixture token; it now explicitly carries the existing session's internal user ID. No application authorization assertion was weakened.

Full Phase 3 completion still requires the current E2E/replay results, including the added public committed-role-change/Temporal-outage reconciliation scenario. Phases 4–7 have not been accepted.

## Phase 3 acceptance

Status: complete for this phase; the full seven-phase migration remains in progress. Earlier pending notes above describe their checkpoints and are superseded by the evidence here.

- PASS: complete real API/recovery suite, 32/32 (6.5m), `.local/authorization-api-e2e.log`. Includes copy/upload/provider ambiguity, worker restarts, gateway scope, onboarding, transfers, invitation authority and provisioning/deletion recovery.
- PASS: added committed-role-change/Temporal-outage/reconciliation journey, 1/1 (44s including setup), `.local/authorization-role-outage-e2e.log`. SQL commit is reported honestly before graph synchronization; reconciliation grants the new action.
- PASS: fresh Account replay (OnboardUser, ReconcileAccounts), 0.051s, and Workspace replay (CreateWorkspace, DeleteWorkspace, SyncWorkspace, ReconcileWorkspaces), 0.068s. Histories were exported by the just-completed persistent-Temporal API run, not old fixture histories.
- PASS: unchanged Rust reference workflow replay against newly converted current histories, 1/1 (0.74s), `.local/rust-phase3-replay.log`.
- Inline review inspected the latest action/mutation/identity/recovery diff and remaining role branches. Remaining SQL role uses implement canonical assignments, limits, exactly-one-Owner and tombstones; the temporary copy-monitor header follows native inspect-any admission. No concrete additional defect was found in this pass. No separate new independent review is claimed.

API runners and replay processes exited, and their disposable Compose resources were removed. No developer data reset, runtime cutover, deployment, commit or push occurred. Phase 4 begins in separate native fixtures.
