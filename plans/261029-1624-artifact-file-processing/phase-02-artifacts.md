---
title: "Phase 2: Hybrid Artifacts, Lifecycle, and Durable Intent"
status: completed
priority: P1
effort: 5d
dependsOn: [phase-01-direct-storage]
---

# Phase 2: Hybrid Artifacts, Lifecycle, and Durable Intent

## Objective

Allow source files to contain read-only generated children through existing parent edges, add the scoped ID alias, close file-leaf assumptions across lifecycle operations, and persist processing intent on top of Phase 1's atomic upload publication.

## Baseline Evidence And Consumers

- `nodes` permits a same-filesystem parent of either kind and source bytes live in `file_data` (`services/letfs/migrations/0001_foundation.sql:20`, `services/letfs/migrations/0002_file_core.sql:1`). No new ownership relation or node kind is needed.
- `paths::resolve` batches lookup but assumes directory traversal (`services/letfs/src/fs/paths.rs:88`, `services/letfs/src/fs/paths.rs:109`). Re-enumerate direct and wrapper callers at execution; do not globally weaken writable-directory checks.
- Its pre-transport direct callers are `services/letfs/src/fs/nodes.rs:81`, `services/letfs/src/fs/nodes.rs:235`, and `services/letfs/src/fs/copy.rs:455`. The old `Session::resolve` inventory had sixteen sites across nodes/uploads/trash/copy/content. Re-enumerate both inventories after Phase 1 because the transport rewrite changes upload/HTTP call paths.
- List currently enforces directory kind (`services/letfs/src/fs/nodes.rs:249`); public creation/upload destinations must remain actual directories (`services/letfs/src/fs/nodes.rs:284`, `services/letfs/src/fs/uploads.rs:55`).
- Inline copy treats files as leaves (`services/letfs/src/fs/copy.rs:23`), durable copy enumerates directories (`services/letfs/src/fs/copy.rs:263`), inline purge removes only the file (`services/letfs/src/fs/trash.rs:110`), and durable purge rejects file roots (`services/letfs/src/fs/deletion.rs:92`).
- Removal accounting derives charge from the original publisher success (`services/letfs/src/fs/deletion.rs:131`). Supersession must not rewrite a succeeded operation into failed/discarding.
- Phase 1 makes overwrite publication atomic and owns the shared upload transaction. This phase hooks child invalidation and eligible processing intent into that transaction; it does not recreate a transport path.

## Data And Path Contract

```text
drive/                         directory
  report.pdf                   file: original inline/object payload
    001-introduction.md        readonly artifact file
    images/                    readonly artifact directory
      001.png                  readonly artifact file
```

| Request | Result |
|---|---|
| `stat /drive/report.pdf` | Original file metadata and own byte size. |
| download `/drive/report.pdf` | Original payload using Phase 1 inline/direct-object behavior. |
| `list /drive/report.pdf` | Published direct children; empty before success. |
| `/drive/report.pdf/001-introduction.md` | Artifact metadata/content. |
| `/drive/@<uuid>/images/001.png` | Authorized live node in the current filesystem, then normal child traversal. |

Read traversal/list/cwd may use a file as a container. Trailing `/` or `/.` selects that container view for list/traversal; content reads with directory-style trailing syntax are rejected. `..` follows real parent edges without escaping the filesystem. Source `size_bytes` counts only its own payload; quota counts every file payload once. Processor child attachment leaves source revision/ETag and payload timestamps unchanged. Ordinary source metadata/lifecycle mutations retain their existing revision behavior.

The alias is recognized only in the first filesystem-relative segment at the mount root/root cwd. It accepts canonical hyphenated UUID names case-insensitively, with UUIDv7 the default for new IDs and existing UUIDv4 accepted, remains filesystem-scoped, and never turns nested `@<uuid>` into a jump. Reserve exactly this pattern for actual root children; `@notes` and nested names remain legal. Preflight collisions and fail visibly instead of shadowing or renaming data.

## Requirements

- [x] Reuse `nodes.parent_id`; add no artifact container, ownership FK, materialized path, per-file filesystem, or hybrid node kind.
- [x] Extend batched resolution with strict-file-ancestor provenance. The source itself stays writable; descendants are readonly. Preserve filesystem/liveness/depth/name/expected-ID guards and avoid per-node ancestry queries.
- [x] Enforce readonly for artifact edit, overwrite, rename, move, trash, purge, and write destinations through normal paths, cwd, scoped alias, and raw ID. Enforce contextual root alias-name reservation at create, upload, rename, move, copy, and restore. Only the internal processor publication path may attach children under a file. Copying an artifact into an ordinary directory yields writable content.
- [x] Reuse `operations` for one `process-file` intent per successful eligible upload publication. Persist immutable source upload/key or bounded inline SHA-256 identity, current source intent, workflow-start acknowledgment, active attempt generation/UUID, and supersession separately from accounting state.
- [x] Eligibility is `.pdf/.docx/.xlsx/.pptx`, case-insensitive. Text, images, legacy Office, and generated artifacts bypass processing. Every byte replacement invalidates old output even when the new file is ineligible or uses text edit; rename/move alone does not.
- [x] In the Phase 1 overwrite transaction, checkpoint and detach all immediate published children before replacing bytes, preserve descendants beneath those roots, mark former intent superseded, and create the next eligible intent. Same-bytes replacement still supersedes. Keep old successful publisher state for accounting until deletion.
- [x] Add source-authorized artifact status through Workspace/letfs. Map existing operation state plus workflow/attempt/supersession facts into `pending|running|succeeded|failed`; no intent returns 404. Do not silently add unconstrained operation states such as `queued` or `expired` without an intentional schema change.
- [x] Trash terminally fences every affected unpublished source with `SOURCE_TRASHED` in the same transaction, using bounded set-based active-operation ancestry queries rather than per-node scans. Completion after restore remains refused; restore never restarts the attempt and reports failed for that current intent. Already-published children remain attached and reappear with the source.
- [x] Copy/move/trash/restore/purge/filesystem deletion treat a source payload plus child forest coherently. Durable copy snapshots payload identity and immediate child roots set-wise under the existing filesystem lock; publication after an empty snapshot is excluded. Copy never copies processing intent or triggers processing.
- [x] Leaf copy/purge fast paths run only after atomic no-children checks. Durable deletion accepts file roots, traverses file/directory parent edges, removes children before parents, and debits payloads exactly once.
- [x] Keep unpublished outputs out of `nodes`. Reuse Phase 1 upload/session records for candidate files and bounded completion metadata for directories. Existing maintenance owns invalidated forests; add no cleanup workflow.

## Files

Create the next migration after Phase 1, expected as `services/letfs/migrations/0008_artifact_processing.sql`. It owns only processing intent/attempt/supersession/index fields not already present after `0007`; confirm the live next number during execution.

Create `services/letfs/src/fs/artifacts.rs` for eligibility, byte identity, provenance, intent/status/supersession, and atomic invalidation helpers.

Modify:

| Files | Change |
|---|---|
| `services/letfs/src/fs/mod.rs`, `services/letfs/src/fs/paths.rs`, `services/letfs/src/fs/nodes.rs` | Module, alias, file traversal/list, provenance, readonly, contextual root-name checks. |
| `services/letfs/src/fs/uploads.rs` | Hook intent and unconditional child invalidation into Phase 1 publication; no transport duplication. |
| `services/letfs/src/fs/copy.rs`, `services/letfs/src/fs/trash.rs`, `services/letfs/src/fs/deletion.rs` | Payload-plus-forest snapshot, restore guards, file-root durable purge, exact accounting. |
| `services/letfs/src/fs/maintenance.rs`, `services/letfs/src/temporal/lifecycle_workflow.rs` | Drain invalidated forests and protect referenced source/output keys through existing maintenance. |
| `services/letfs/src/http/mod.rs`, `services/workspace/internal/http/files.go` | Hybrid list/content/status routing with existing auth. |
| `services/workspace/internal/http/server_test.go`, `contracts/internal/openapi.yaml`, `contracts/public/openapi.yaml` | Authorization, alias/readonly/status and hybrid semantics. |
| `services/letfs/tests/integration.rs`, `scripts/test-integration.sh` | Add the `artifacts` selector and real PG/S3 lifecycle/accounting coverage. |

## Implementation Steps

1. Back up, allocate the next migration after Phase 1, and add minimal intent/attempt/supersession fields and indexes plus alias collision preflight.
2. Add centralized artifact eligibility, source identity, provenance, status, supersession, and invalidation helpers.
3. Update resolver callers and mutation boundaries without weakening actual-directory destination guards or public Node serialization.
4. Modify Phase 1's shared publication transaction directly to add invalidation and eligible intent, without requiring a placeholder artifact module or callback abstraction in Phase 1. Keep source success independent from later dispatch/processing failure.
5. Correct copy/purge/deletion leaf assumptions and snapshot ordering; retain existing lock order, depth/cycle checks, and deletion checkpoints.
6. Add status facade, contracts, focused Rust/Go tests, and `artifacts` integration routing before use.

## Focused Acceptance

| Area | Required cases |
|---|---|
| Paths | Original bytes, children, alias/raw ID/cwd, trailing syntax, `..`, nested `@` names, collision preflight, all destination guards. |
| Trust | Strict-ancestor readonly everywhere; source writable; no hidden/trash/detached ID bypass; copied-out artifact writable. |
| Lifecycle | Source/ancestor move/trash/restore/copy/purge, inline/object sources, empty and >64-node forests, filesystem deletion, exact counts/quota. |
| Intent | Eligible case variants, bypass types, every replacement invalidates, metadata-only changes preserve identity, succeeded publisher remains charged until cleanup. |
| Copy races | Publication before snapshot included; publication after empty snapshot excluded; overwrite cannot mix source payload and artifacts. |

Existing gates remain `make fmt`, `make verify`, and `make test-integration SERVICE=letfs TEST=all`. `TEST=artifacts` is planned and unavailable until this phase updates `scripts/test-integration.sh`.

## Todo

- [x] Add artifact intent/attempt/supersession schema and alias collision preflight.
- [x] Implement traversal/list/alias/provenance and centralized readonly guards.
- [x] Hook atomic invalidation and new intent into shared upload publication.
- [x] Correct copy/trash/restore/purge/deletion lifecycle and accounting.
- [x] Update status contracts/callers and focused tests/selectors.

## Risks And Rollback

File-leaf assumptions are the primary regression risk. Bound ancestry, output trees, depth, and set-based queries; do not introduce N+1 traversal. Rollback stops processing admission, removes artifact descendants through normal lifecycle code, proves every file is again a leaf, preserves source bytes and succeeded accounting, and only then reverts hybrid schema/semantics.
