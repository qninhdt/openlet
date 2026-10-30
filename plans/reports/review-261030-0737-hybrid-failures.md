# Hybrid Artifact Plan Review - Failure Modes

Scope: revised four-file plan only, checked against current `paths.rs`, `copy.rs`, `trash.rs`, and `deletion.rs`. The retired detached artifact-root/ownership-pointer design was not used as review authority. No source edits, builds, installs, or runtime tests were performed.

## Findings

### Resolved - Empty-child copy snapshot and source revision fence

The plan requires a source copy to snapshot its payload and immediate children atomically, then succeed without later output: publication before the snapshot is included and publication after an empty snapshot is excluded (`phase-01-artifacts.md:63`, `phase-01-artifacts.md:109`; `phase-03-acceptance.md:31`). Current durable copy records `source_revision` for every item (`services/letfs/src/fs/copy.rs:161-167`) and rechecks a file's revision before completing object payload work (`services/letfs/src/fs/copy.rs:224-240`, `services/letfs/src/fs/copy.rs:326-346`). Existing child-set writers bump the parent revision (`services/letfs/src/fs/nodes.rs:296-306`, `services/letfs/src/fs/copy.rs:393-399`).

At initial review, the plan did not state whether atomic processor publication bumped the source file revision. Following the existing child-insertion convention would make an object-backed source copy that captured an empty child set fail when output published before its payload copy finished, rather than publishing the accepted empty snapshot. The latest plan now resolves this as recorded below.

The requested correction was to state that processor-only child attachment does **not** bump the source file revision, retain byte-replacement fencing, and add the object-backed empty-snapshot race barrier. Those requirements are now present.

### Resolved - Trash during processing terminal behavior

Completion must recheck a live source (`phase-02-processing.md:52`), while trash currently detaches the source from the live tree and bumps its revision (`services/letfs/src/fs/trash.rs:39-56`); raw-ID/path resolution only succeeds when ancestry reaches the filesystem root (`services/letfs/src/fs/paths.rs:103-117`). At initial review, bounded activity retries plus general trash/restore coverage did not define what `complete` or maintenance did when the source was trashed during conversion.

That gap could have made the same bytes succeed or fail based only on restore timing. The latest plan now chooses terminal cancellation and supplies the missing acceptance cases.

The requested correction was to choose one lifecycle rule, make it atomic with trash, and test trash-during-conversion through restore and status. The plan now does so without adding another artifact container, workflow, or registry.

## Verified Corrections

- Ordered attempt generations, abandoned-output accounting, replacement quota behavior, local-versus-R2 backup scope, and restore admission are now explicit in the revised plan.
- Unpublished output creates no nodes, so the prior shared-operation charged-state contamination does not apply (`phase-02-processing.md:48-55`).
- Direct parent edges let existing deletion batches remove children before a file parent once file-root admission and leaf fast paths are corrected (`services/letfs/src/fs/deletion.rs:151-179`).
- Original source bytes remain independently represented by `file_data`; allowing child traversal does not require changing content lookup (`services/letfs/src/http/mod.rs:363-383`).

## Plan Completion Status

The direct-child design is coherent. The latest plan revisions resolve both timing contracts identified above; no remaining concrete failure-mode blocker was found in the requested file-leaf, copy snapshot, overwrite-forest, readonly/liveness, or original-byte scope.

## Resolution Update

- **Copy snapshot finding resolved:** processor-only child attachment explicitly leaves source revision/ETag and payload timestamps unchanged (`phase-01-artifacts.md:46`, `phase-02-processing.md:54`). The object-backed empty-snapshot success race is now an explicit acceptance case (`phase-01-artifacts.md:109`, `phase-03-acceptance.md:31`). Byte replacement and ordinary metadata/lifecycle mutations retain existing revision behavior, so this does not weaken overwrite fencing.
- **Trash-during-processing finding resolved:** trash atomically and terminally fences affected unpublished intents with `SOURCE_TRASHED`, cleans unpublished handles, and restore neither resumes nor recreates processing (`phase-01-artifacts.md:62`, `phase-02-processing.md:57`). Acceptance now covers completion after restore, failed restored status, ancestor trash across several active sources, and preservation/reappearance of already-published children (`phase-01-artifacts.md:107`, `phase-03-acceptance.md:34`).

## Unresolved Questions

None in the reviewed scope.

Status: DONE
Summary: The revised plan now resolves the previously identified copy-snapshot revision and trash-during-processing contracts. No remaining concrete blocker was found in the assigned failure-mode scope.
Checks skipped: no builds, tests, installs, migrations, containers, or runtime/provider checks, per delegated scope.
