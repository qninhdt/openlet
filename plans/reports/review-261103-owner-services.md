# Account and Workspace owner-service review

Reviewed the accepted service refactor across Account and Workspace business services, Temporal ownership, storage conversion, authorization, cancellation, idempotency, internal gRPC authority, and both composition roots. The two concrete regressions found during review were fixed in scope.

## Findings resolved

1. **High — initial-workspace recovery expired before Account onboarding durability.** Workspace creation receipts normally expire after 24 hours, while Account onboarding and its deterministic initial-workspace workflow can recover for seven days. Once maintenance pruned the receipt, `EnsureInitial` could no longer recover the completed workspace ID and `StartInitial` could not reuse the completed workflow because it deliberately rejects duplicate executions. The initial route now uses the reserved `actor_id == request_key` identity, public workspace creation rejects that reserved key, completed initial receipts remain non-expiring, and `FindInitialCreation` retrieves the durable mapping independently of ordinary receipt TTL. A focused integration test proves ordinary receipts prune while the initial mapping remains recoverable without starting another workflow.

2. **Medium — Account HTTP lost terminal Temporal fault semantics.** `StartOnboarding` returned Temporal `ApplicationError` values directly after the refactor, but Account HTTP no longer decoded them, so terminal workflow failures such as `ONBOARDING_FAILED` became generic `503 DEPENDENCY_UNAVAILABLE`. Temporal starters now translate non-retryable application errors into native Account/Workspace faults and cancellation into `context.Canceled`; Workspace HTTP no longer imports the Temporal SDK for error mapping. Workflow tests cover the native conversion.

## Review result

No further concrete correctness or security findings remain in the reviewed owner-service paths. The implementation preserves:

- Account onboarding order: user/graph ensure, durable initial Workspace completion, Clerk publication, then Account completion; cleanup stays disconnected and does not run on Continue-As-New.
- Workspace provisioning order: reserve stable storage IDs, initialize authorization, validate letfs scope, publish activation relationships, activate SQL, release the provisioning fence, then complete the creation receipt.
- Mutation recovery: SQL receipt and mutation commit remain atomic, lost acknowledgements are reconciled before retrying SQL effects, graph publication precedes receipt completion, and workflows serialize per workspace.
- Destructive cleanup: deletion admission publishes the storage fence, the durable workflow freezes the bucket, waits for every filesystem deletion, completes the bucket, and finalizes Workspace state under a disconnected context.
- Trust boundaries: public ingress remains HTTP-only; internal gRPC handlers require the allowlisted service principal with no delegated actor, and shared clients validate returned resource scope.
- Composition cleanup: workers, clients, listeners, database pools, telemetry, HTTP, and gRPC servers have bounded shutdown/cleanup paths.

The remaining `businessError`/`Provisioning` legacy wrappers noted during review were removed by the concurrent owner changes; this review did not reintroduce them.

## Verification

- `cd apps/account && go test ./...`
- `cd apps/account && go test -tags workflow ./internal/temporal -count=1`
- `cd apps/workspace && go test ./...`
- `cd apps/workspace && go test -tags workflow ./internal/temporal -count=1`
- `cd apps/workspace && go test -tags integration ./internal/workspace -run 'TestIntegrationInitialWorkspaceReceiptRemainsRecoverable|TestIntegrationWorkspaceReceiptAdmissionAndExpiry' -count=1`
- Integration compile checks for both modules: `go test -tags integration -run '^$' ./...`

Full provider-backed and end-to-end journeys were outside this focused owner-service review.

Status: DONE
Summary: Reviewed Account and Workspace owner-service refactors, fixed durable initial-workspace recovery and native Temporal error propagation, and verified native, workflow, focused integration, and integration-compile checks.
Concerns/Blockers: None in the reviewed scope; full external-provider and end-to-end journeys were not run.
