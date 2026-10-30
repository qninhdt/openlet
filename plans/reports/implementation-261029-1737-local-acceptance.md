# Openlet backend local acceptance

Date: 2026-10-29. Local implementation is complete; external release acceptance remains open. This record supersedes the outstanding implementation lists in earlier evidence reports. No commit, push or deployment was performed.

## Delivered

User and Workspace run Go/Chi; generic letfs runs Rust/Axum. Envoy validates JWTs and supplies trusted identity headers. PostgreSQL databases and credentials are isolated by owner. Native Temporal workers implement all seven accepted workflow types. No Redis or custom gateway was added.

The backend includes stable Clerk/internal identity and onboarding, profiles, workspace roles and ownership, manually shared verified-email invitations, ID/path/mount file access, exact editable inline text, bounded S3 uploads/downloads/ranges, hard workspace-bucket quota, trash/restore, independent copy keys, detached copy publication, durable purge/filesystem/workspace deletion, and finite scheduled storage maintenance. Trash never expires automatically.

Deletion shares a bounded postorder core. Each removal transaction updates metadata, node count and charged usage together; failed-copy staging is uncharged, while succeeded copy nodes retain their charge. Publication is fenced before deletion enumeration. Tombstones and operation checkpoints survive process restart. Object cleanup retains uncertain-write evidence and performs network calls outside database locks.

## Verified on the final implementation

| Command/check | Result |
|---|---|
| `make verify` | Passed formatting, native Go tests/vet, Rust unit tests/clippy, generated config checks, shell syntax and owned OpenAPI checks. |
| `make test-integration TEST=all` | Passed against real Envoy, PostgreSQL, SeaweedFS S3, Temporal and all three services; controlled Clerk HTTP boundary. |
| `make test-workflow` | Passed Go SDK workflow tests and native Go/Rust replay of real histories for seven workflow types, including failed and recovered copy histories. |
| `python3 scripts/verify-contracts.py --responses` | Passed 1,354 captured public JSON response DTOs. Checks local schema/references and response shapes; it is not a complete OpenAPI specification validator. |
| `make backup-restore-drill` | Passed coordinated capture and isolated restore of all five databases, inline/object bytes, accounting and persisted onboarding history. Schedule remained paused with overlap Skip; no restored host ports were published. |
| PostgreSQL efficiency/isolation | Batch-stat 1/100 each used one recursive resolve statement; list limits 1/100 each used one page statement. All 20 cross-owner database connections were denied. Node counts reconciled after integration/restart. |
| Captured logs | No generated secret value appeared in the captured service/infrastructure logs. Logging uses bounded allowlisted fields; no exhaustive production log audit is claimed. |

Recovery used an actual S3-copy barrier: the harness killed letfs and Temporal, restarted PostgreSQL, resumed the original workflow, and verified byte equality, the original destination ID and a single quota charge. Other integration checks covered source edit/move/trash during copy, failed publication quota, lost S3 acknowledgment, upload stale writes, bounded copy cleanup, shared quota contention, restore/purge contention, large directory purge, extra filesystems during workspace deletion, late-finalize/provision rejection and maintenance preserving old trash. This is representative fault-boundary coverage, not an exhaustive kill at every instruction.

## Repairs and review

The conditional cook simplifier ran over owned lifecycle files and preserved behavior; native checks passed afterward. Final review was performed inline using the installed code-review skill, acceptance documents, affected callers and concrete integration/replay evidence. No independent review is claimed.

Confirmed defects repaired during implementation included purge facade decoding a successful 204 as JSON, accounting for published copy nodes with staging markers, native history serialization differences, and restore-volume initialization. Final acceptance exposed additional operational/verification defects:

- SeaweedFS images seed an empty data directory into new Docker volumes. Restore now extracts into a guarded fresh volume with `volume-nocopy`, before storage starts.
- The test-only `pg_stat_statements` extension cannot be restored by a restricted service database owner. Local dumps now exclude that instrumentation extension; application data remains included and service privileges remain restricted.
- Public contract capture includes an intentional probe of an internal route through Envoy. Validation asserts its 404 denial instead of treating it as an advertised public endpoint.

The full final restore drill passed after these repairs. Current docs and active-plan relative links resolved. The CLI still leaves historical Pending labels in the phase table/frontmatter; checked phase tasks and `ak plan status` are the verified progress projection.

## Artifacts and shutdown

The final isolated target was `openlet-restore-20261029104133-29428`. Its snapshot is recorded by ignored `.local/test/last-snapshot`; its target is recorded by `.local/test/last-restore`. Native test histories and response captures remain under `.local/test/histories/`. Snapshots/configuration contain sensitive credentials and remain ignored/private. A separate pre-verification metadata/object backup was taken before the final suite.

All task-owned test and restore containers stopped; source and restored volumes remain intact. No global pruning, volume removal, source overwrite or promotion was performed.

## Remaining release prerequisites

The user confirmed no real Clerk development instance or external S3 provider is configured. `make test-clerk` and `make test-provider` were not run. The chosen provider's version retention, multipart cleanup and coordinated object-restore method must also be verified. SeaweedFS restore proves only the documented local provider route. The active plan remains in progress solely for these two external prerequisite tasks (96/98 tasks verified).
