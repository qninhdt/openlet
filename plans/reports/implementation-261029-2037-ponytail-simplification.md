# Ponytail simplification review

This follow-up addresses structural simplification that the preceding bug-fix
audit did not demonstrate. The user authorized scouting, polishing and repairing
the project while preserving the accepted backend scope.

## Inspected scope

Reviewed production source and call sites across User identity/profile/Clerk,
Workspace HTTP/collaboration/storage/provisioning, letfs tree/path/quota/object
operations and Temporal lifecycle code. Inspected Compose, configuration/test
scripts, backup/restore scripts, native Testcontainers fixtures and representative
unit/workflow/system tests. Reused the preceding audit's evidence for unchanged
gateway behavior. There is no CodeGraph index in this repository.

## Changes made

| Finding | Simplification | Preserved contract |
|---|---|---|
| `PurgeTrash` and `DeleteFilesystem` duplicated the complete deletion algorithm. | Keep the two registered workflow identities and call one concrete deletion routine. | Activity names/order/options, cancellation shielding, 200-batch continuation and input/output schema; old-history replay passed. |
| Copy duplicated the lifecycle heartbeat loop. | Reuse one heartbeat helper and place shared activity-error mapping with it in the Temporal module. | Ten-second interval, immediate first tick, UUID/unit heartbeat payloads, retry classification and failure propagation. |
| Each letfs readiness probe opened another Temporal connection. | Issue the existing namespace check over the application's existing SDK connection. | Three-second deadline and health status mapping. |
| The file facade cloned a request and rewrote its query just to ignore its cursor. | Share limit parsing directly with ordinary pagination; remove the clone/re-encode wrapper. | Default 50, bounds 1–100, letfs cursor ownership and scoped Workspace cursors. |
| Locked and ordinary Workspace authorization duplicated state/role policy. | Apply one policy method after each existing database read. | Membership checks, lock-before-membership ordering, lifecycle-error precedence and role matrix. |
| Unused state and injection points remained in runtime structs. | Remove Session's unread node counters, Workspace HTTP's unused letfs client and the unused custom-client field in the letfs HTTP adapter. | Database node accounting and admission remain enforced by SQL; client deadlines and redirect refusal remain. |
| Both Go services required all service URLs despite calling only their own dependencies. | User requires Workspace URL; Workspace requires User/letfs URLs. Update Compose placement, validation tests and setup docs together. | All actual downstream URL checks remain; existing extra environment variables are harmless. |
| Node operations cloned locators, and the HTTP adapter cloned the complete JSON response before setting ETag. | Borrow locators and compute the small optional ETag before moving the response. | Lookup/guard behavior, response body/status and header calculation. |

No service, API operation, schema, dependency or new shared framework was added.
The reviewed source patch changes 19 existing files and reduces service production
source by 42 lines. New role/pagination tests account for 67 additional test lines;
line count was not the acceptance criterion.

## Complexity deliberately retained

- Separate Go service configuration/authentication adapters keep their independent
  trust and deployment boundaries. A new shared module would add coupling.
- Copy preflight and transactional revalidation serve different snapshots; guards
  before and after remote storage effects are required for concurrent-source safety.
- Quota admission, bucket/filesystem locks, staging publication, revision checks,
  idempotency identity and durable checkpoints prevent data/accounting errors.
- Similar workflow admission paths compare different retained inputs and expose
  different errors. They were not forced into a generic callback-based runner.
- Temporal activity methods remain explicit registration/remote-effect boundaries.
  Direct metadata transactions remain direct.
- Backup and restore retain their own isolation, checksum and writer-stop guards.
  Testcontainers and Compose continue to cover different boundaries; no test
  framework or broad formatting/naming rewrite was introduced.

## Verification

- Focused Go config/HTTP/letfs-client tests passed.
- `GO=/tmp/openlet-tools/go/bin/go CARGO_INCREMENTAL=0 make fmt verify` passed:
  formatting, Go unit tests/vet, Rust unit tests/clippy, configuration tests,
  OpenAPI checks and shell syntax. Added explicit role/lifecycle expectations and
  pagination boundary/cursor-scope cases.
- `GO=/tmp/openlet-tools/go/bin/go CARGO_INCREMENTAL=0 make test-integration`
  passed User, Workspace and letfs with real Testcontainers dependencies.
- `GO=/tmp/openlet-tools/go/bin/go CARGO_INCREMENTAL=0 make test-workflow`
  passed against the histories captured before this refactor, including both
  deletion workflow types, successful/failed/recovery copy and maintenance.
- `PATH=/tmp/openlet-tools/go/bin:$PATH CARGO_INCREMENTAL=0 make test-e2e TEST=all`
  passed gateway, onboarding, membership/admission, paths, query counts, quota,
  storage/copy races and bounds, lifecycle, worker/server restart, rate limiting
  and database isolation.
- `python3 scripts/verify-contracts.py --responses` validated 1,328 response DTOs
  captured by the final full E2E run.
- Reran `make test-workflow` with the selected Go executable against the newly
  captured histories: Go workflow tests/replayers and Rust replay passed again.

The initial Rust check found a private trait import in the refactor. Switched to
the public re-export verified in installed SDK source; subsequent compilation,
clippy and replay passed. No check was disabled or assertion weakened.

Compared the complete patch against the independent pre-refactor source archive
because all project files were untracked. Instructions, migrations, manifests,
lockfiles and public schema files are unchanged. No existing file was deleted.
Local evidence: `/tmp/openlet-ponytail-*.log`; source archive and patch:
`/tmp/openlet-ponytail-baseline-jfmifdrw/`.

## Limits

No live Clerk/R2 smoke, provider-specific recovery or performance benchmark was
run. Local coordinated backup/restore passed in the preceding audit and was not
repeated because its scripts, persisted schema and backup format did not change.
The combined real-Clerk/public-API/R2 upload and R2 recovery release checks remain
open. Removing obvious copies/connections is not a measured latency claim.

Host disk pressure was addressed by removing only two private, reclaimable Docker
build-cache records produced by this run, after their builds completed; images,
volumes and snapshots were retained. About 1.3 GiB remained free. No commit or push
was requested. All task-started test processes and containers exited. This review
does not guarantee that every application defect has
been found.
