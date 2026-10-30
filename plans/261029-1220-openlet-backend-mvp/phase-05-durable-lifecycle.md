---
phase: 5
title: "Durable Purge, Deletion, and Maintenance"
status: pending
priority: P1
effort: "6d"
dependencies: [4]
---

# Phase 5: Durable Purge, Deletion, and Maintenance

<!-- Updated: Validation Session 1 - apply conditional/state recovery and retain only necessary creation/durable identity. -->

## Goal

Complete recoverable destructive workflows for trash purge, filesystem deletion, workspace deletion, and finite maintenance without automatic trash expiry.

## Files to Create / Modify

Paths below are relative to `/home/qninh/projects/openlet`; all are planned creations or extensions from prior phases.

- Modify: `services/letfs/src/{fs,storage,temporal}/`, `services/letfs/migrations/`
- Modify: `services/workspace/internal/{workspace,temporal,http,letfs}/`, `services/workspace/migrations/`
- Modify: `contracts/{public,internal}/openapi.yaml`
- Modify: `deploy/temporal/`, `deploy/compose.yaml`
- Create: lifecycle, cancellation, replay, and recovery tests

## Workflow Catalogue Completed Here

| Workflow | Owner | Durable responsibility |
|---|---|---|
| `PurgeTrash` | letfs | Owner-authorized detached subtree purge and exactly-once accounting per removed node |
| `DeleteFilesystem` | letfs | Remove live/trash/staging/uploads and usage; retain tombstone |
| `DeleteWorkspace` | Workspace | Freeze access, drive every filesystem deletion, retain tombstone |
| `StorageMaintenance` | letfs | Finite upload expiry, confirmed staging cleanup, object GC |

Together with phases 2 and 4, the seven types are `OnboardUser`, `CreateWorkspace`, `DeleteWorkspace`, `CopyNode`, `PurgeTrash`, `DeleteFilesystem`, and `StorageMaintenance`.

## Data Flow

1. Workspace rechecks Owner/revision, starts the workflow, and waits only for caller-bound admission.
2. The owning workflow marks the resource purging/deleting before enumeration, blocking new publication.
3. Workspace activities call letfs internal HTTP; letfs starts its owner-local workflows, keyset-enumerates rows, commits progress, then deletes objects.
4. Retries read checkpoints/state; a lost response cannot repeat debit or resurrect rows.
5. Completion records logical result/tombstone even when delayed physical cleanup remains.

## Requirements

- [x] Let Editor trash/restore and only Owner purge or permanently delete a workspace.
- [x] Purge one file directly; purge a directory through `PurgeTrash` even if one batch suffices.
- [x] Delete live, trash, staged copy, candidate upload, while retaining physical cleanup ownership after filesystem/workspace deletion.
- [x] Freeze filesystem/bucket publication before enumeration and reject late finalize/copy publish.
- [x] Reuse one bounded deletion core with explicit charged versus uncharged accounting.
- [x] Start letfs workflows inside letfs after authenticated HTTP admission; do not add Go-to-Rust Temporal activity or child calls.
- [x] Persist cursor, lifecycle, cleanup, terminal result, and tombstone in PostgreSQL.
- [x] Make object deletion idempotent and keep network I/O outside locks/transactions.
- [x] Use a finite Temporal Schedule with overlap skipped and later-run continuation.
- [x] Reclaim only explicit discarding state or confirmed closed workflow; unknown is not abandoned.
- [x] Never age-purge user trash or add lease/resume/general reconciliation frameworks.

## Implementation Steps

1. Add purge/deletion checkpoints, lifecycle, tombstones, and cleanup-attempt schema.
2. Implement direct file purge with original identity/revision and lifecycle checks, atomic metadata removal plus one per-node debit, and delayed cleanup; no response receipt.
3. Implement `PurgeTrash`: claim root, delete bounded batches, debit each removed charged node once in its batch transaction, complete when empty.
4. Implement `DeleteFilesystem`: mark deleting, fence publication, remove all node classes/uploads/jobs, tombstone.
5. Implement `DeleteWorkspace`: disable access, freeze the bucket against new provisioning, enumerate every bucket filesystem, request stable letfs deletions over HTTP with bounded concurrency, then tombstone.
6. Make letfs HTTP admission idempotent so Workspace cancellation/shutdown can resume polling the independently admitted operation.
7. Implement maintenance batches for expired uploads, confirmed discarding copies, and due object cleanup.
8. Add finite budgets, heartbeats, Continue-As-New with operation/cursor only, and graceful drain.
9. Separate retryable infrastructure failures from terminal domain outcomes and sanitize status.
10. Expose operation lookup for admitted, running, logical completion, and physical cleanup lag.

## Recovery Invariants

- Deleting resources never reactivate automatically.
- Quota decreases exactly once per charged node in the transaction that removes it; staging never debits.
- Published copies cannot be discarded; staged copies cannot publish during deletion.
- Missing S3 keys are successful cleanup outcomes.
- Temporal history is not the sole admission/progress/completion truth.
- Workspace completion requires every filesystem in the frozen bucket logically deleted; physical GC may lag.

## Test Matrix

| Layer | Evidence |
|---|---|
| Integration | Real PostgreSQL/S3 batches, per-batch debit and final total, missing-key retry, direct purge response loss/repeat with no extra debit, tombstones |
| Workflow | Temporal restart, timeout after commit, cancellation, Continue-As-New, cross-service HTTP resume, closed-before-admission recovery |
| Concurrency | Restore/purge, finalize/delete, copy-publish/filesystem-delete barriers |
| Security/contract | Editor denial, Owner recheck, foreign operation denial, stable status |
| Recovery | Kill worker at each checkpoint and reach one terminal logical result |

## Planned Verification Commands

```bash
make test-integration TEST=lifecycle
make test-integration TEST=lifecycle-races
make test-workflow TEST=destructive-lifecycle
make test-recovery TEST=worker-restarts
make test-integration TEST=destructive-authorization
```

## Failure Modes and Mitigations

| Failure | Risk | Mitigation |
|---|---|---|
| Retry double-debits quota | High | Reference removal and debit in one idempotent transaction |
| Late finalize recreates data | High | Lifecycle fence in every publish/finalize transaction |
| Workspace cancellation loses letfs deletion | High | Stable HTTP operation ID and owner-local letfs workflow status |
| Maintenance deletes uncertain staging | High | Require discarding or confirmed closure |
| Schedule grows without bound | Medium | Keyset batches, finite budget, overlap skip |

## Rollback

- Disable new destructive admission and pause maintenance.
- Drain activities to checkpoints before compatible worker rollback.
- Do not reactivate deleting resources; resume the same operation with prior version or forward fix.
- Restore database and matching objects from a coordinated point if purged content must return.

## Success Criteria

- [x] Purge and deletions finish once across worker/Temporal restarts and lost responses.
- [x] Workspace deletion includes live, trash, staging, uploads, and every filesystem in the frozen bucket.
- [x] Races cannot restore/publish into claimed deletion, and quota never debits twice.
- [x] Maintenance is finite, non-overlapping, observable, and never age-purges trash.
- [x] Recovery tests use real PostgreSQL, S3-compatible storage, and Temporal.

