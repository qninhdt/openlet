> Historical snapshot, superseded on 2026-10-30 by the user-approved [direct-child artifact plan](../261029-1624-artifact-file-processing/plan.md). Its schema, path, ownership and pending-review statements describe the previous draft; do not execute them. Use the current plan and [validation report](./validation-261030-0737-hybrid-artifact-plan.md). General runtime/source evidence remains useful where the current plan retains it.

# Artifact File Processing Plan Review - Failure Modes

Scope: plan-only red-team of `plans/261029-1624-artifact-file-processing/` against the current letfs contracts and the two supporting research reports. No source changes, builds, installs, or runtime tests were performed.

## Findings

### High - Attempt supersession has no ordering authority, so an older retry can supersede a newer worker

The plan says each activity invocation creates a local attempt UUID, letfs activates it, and a later invocation supersedes the old attempt (`phase-02-processing.md:35`, `phase-02-processing.md:54-55`). A UUID identifies an attempt but does not prove which invocation is later. If attempt B reaches `prepare` first and delayed attempt A reaches it afterward, an unconditional "new UUID supersedes active UUID" rule reactivates A and gives the stale worker publication authority. The acceptance matrix mentions "stale/higher attempts" but the plan never defines what "higher" means (`phase-03-acceptance.md:31`). Current durable state supplies no hidden ordering contract: `operations` has one state and request identity but no attempt generation (`services/letfs/migrations/0002_file_core.sql:21-33`), while `uploads` has independent UUID rows and transfer states only (`services/letfs/migrations/0004_uploads.sql:1-16`).

Smallest correction: make activation conditional on a monotonic, server-checked attempt generation (for example the Temporal activity attempt number plus the UUID used for HTTP idempotency), persist the active generation on the processing operation, and require `(operation_id, generation, attempt_uuid)` on every handle/complete/abort call. Add an explicitly reordered `prepare(B) -> prepare(A) -> complete(A/B)` barrier, not only a stale-completion test.

### High - The plan does not prevent abandoned attempt nodes from becoming charged when their shared processing operation later succeeds

The existing deletion contract derives charge status from `nodes.staging_operation_id`: a node is charged when that field is null or its referenced operation is `succeeded` (`services/letfs/src/fs/deletion.rs:131-149`). The plan correctly requires the published processing operation to remain `succeeded` (`phase-01-artifacts.md:22`, `phase-02-processing.md:36`), but it also reuses one processing operation across superseded attempts and leaves the representation of per-attempt staged output open (`phase-01-artifacts.md:27-28`, `phase-02-processing.md:35`, `phase-02-processing.md:106`). If abandoned attempt nodes carry the durable processing operation as `staging_operation_id`, a later successful attempt changes the accounting interpretation of all those old nodes: their subsequent cleanup debits quota that was never charged.

The current copy implementation is safe only because every staged node belongs to the same single attempt and publication outcome (`services/letfs/src/fs/copy.rs:181-183`, `services/letfs/src/fs/copy.rs:392-400`); that assumption does not hold for multiple processor attempts under one operation.

Smallest correction: state an explicit invariant that no per-attempt `nodes` exist before the winning publication transaction (attempt output remains in uploads/object cleanup records), and create only the winning artifact tree with the succeeded processing operation. If prepublication nodes are required, they need attempt-scoped cleanup operation IDs; they cannot share an operation that another attempt may later mark succeeded. Add reconciliation proving abandoned-attempt deletion changes node count but debits zero bytes after another attempt succeeds.

### High - The quota-failure acceptance case contradicts mandatory overwrite invalidation

Phase 1 requires overwrite finalize to clear the old `artifact_dir_id` and admit old-root deletion in the same transaction as the new source bytes (`phase-01-artifacts.md:30`, `phase-01-artifacts.md:44-45`, `phase-01-artifacts.md:85`). That makes the old artifact immediately unresolvable before the replacement processing attempt reaches quota admission. Phase 3 nevertheless requires "quota failure preserves old root" (`phase-03-acceptance.md:45`). The current upload contract only preserves the old *source file* when upload-finalize quota admission itself fails (`services/letfs/src/fs/uploads.rs:209-229`); it does not support restoring an invalidated artifact pointer after a later processor quota failure. The plan's accepted contract also says overwrite clears the pointer and separately deletes the old root (`plan.md:26`).

Smallest correction: replace that Phase 3 assertion with the actual contract: source overwrite commits, the old artifact remains hidden and charged only until its already-admitted deletion removes it once, the replacement attempt fails without publishing/charging a new tree, and status reports failure. Do not restore the old pointer.

### High - Source copy has no snapshot fence for a concurrently attached artifact root

The plan requires copying a source to copy its attached artifact closure and atomically assign the copied pointer (`phase-01-artifacts.md:38`, `phase-01-artifacts.md:88`), but it does not define what happens when artifact publication attaches `artifact_dir_id` while a durable source copy is enumerating. Existing copy fencing captures node revision in each `copy_items` row (`services/letfs/src/fs/copy.rs:161-168`) and rechecks a file's revision (`services/letfs/src/fs/copy.rs:224-240`); artifact ownership is not a `parent_id` child edge and the plan does not require pointer publication to bump the source revision or require copy to capture/recheck `artifact_dir_id`. A copy can therefore enumerate the source with no artifact, race with publication, and still publish a source clone missing the now-attached closure, or observe only part of a newly added ownership edge.

Smallest correction: define the source-copy snapshot contract and fence it directly. Capture the source's `artifact_dir_id` (including null) when copy admission reads the source, insert the ownership closure from that captured root, and recheck the pointer under the publication lock before attaching the copied tree. Add both race orders: artifact publish before copy admission must be included; artifact publish after admission must either make copy fail/retry or be consistently excluded by the documented snapshot rule.

### High - Release backup coverage stops at local SeaweedFS while the repository requires an external-provider recovery point

The plan makes coordinated backup/restore a top-level success criterion (`plan.md:56`) and adds R2 presigned checks as the only external-provider release prerequisite (`phase-03-acceptance.md:34`, `phase-03-acceptance.md:100`, `phase-03-acceptance.md:144`). The files and commands it changes are the local Compose/SeaweedFS backup path (`phase-03-acceptance.md:74-80`, `phase-03-acceptance.md:121`). Current operations authority explicitly says those scripts do not back up external S3 (`docs/operations.md:23-27`) and requires an independently drilled R2 object backup coordinated with the five databases before release (`docs/operations.md:78-82`). Presigned API checks do not prove recovery.

Smallest correction: split the acceptance claim. Keep the automated SeaweedFS drill, and retain an explicit provider-specific coordinated R2 object-plus-database backup/restore gate before release, reporting `NOT RUN` when credentials/procedure are unavailable just as the R2 presigned gate does. If that external recovery work is intentionally outside this feature, narrow `plan.md:56` to the local SeaweedFS profile and list the existing R2 recovery prerequisite as a release blocker rather than implying coordinated recovery is complete.

## Contract Checks

- Accepted choices remain intact: source-owned detached roots, no `content_revision`, one Rust workflow plus one Python activity, and no run/output/FS registry are not challenged.
- The source-identity fence is compatible with rename/move and rejects byte replacement as planned; the findings concern attempt authority, accounting provenance, copy snapshotting, and recovery claims.
- No concrete defect was found in the unique staging-to-unique-final copy rule or the rule that a published processing operation remains succeeded.

## Plan Completion Status

The plan is not implementation-ready until the four in-repository protocol contradictions/races above are resolved. The external R2 recovery item may instead be recorded as an explicit release blocker if it is deliberately outside implementation scope.

## Unresolved Questions

- Is coordinated R2 backup/restore part of this feature's delivery, or should the plan explicitly scope its automated backup acceptance to SeaweedFS and carry R2 recovery as a separate release gate?

Status: DONE_WITH_CONCERNS
Summary: Five concrete plan defects remain: unordered attempt takeover, charged-state contamination across attempts, a contradictory quota-failure expectation, an unfenced artifact-pointer/source-copy race, and incomplete external-provider recovery coverage.
Concerns/Blockers: Resolve the first four before implementation; classify the R2 recovery requirement before claiming release-ready coordinated backup/restore.
