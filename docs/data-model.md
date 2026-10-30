# Data model and consistency

Status: implementation contract, not executable DDL. Service-local migrations must implement these invariants and the focused tests in [testing](testing.md). Fields below are the minimum responsibilities, not a requirement for extra ORM/framework layers.

## Common conventions

UUIDv7 entity IDs, UTC timestamps, checked signed 64-bit byte counters/revisions, nonnegative sizes. API byte counts and revisions are decimal strings. Mutations use revision ETags. File revisions change for content/name/location/lifecycle changes; directory revisions also change when their child set changes. No filesystem-wide mutation epoch.

Multi-step operations retain scope, initiator, request identity, validated-input fingerprint, state/result and checkpoints. Direct inline-file copy retains a scoped key/fingerprint and result ID to prevent duplicate creation; short trash/restore/file-purge transactions need no receipt rows. Uniqueness protects committed effects after Temporal retention expires. Ordinary reads/profile edits do not need operation records. Do not persist secrets or file bodies in workflow history or general operation responses.

## User and Workspace databases

| Table | Fields / invariant |
|---|---|
| User `users` | ID, unique Clerk subject, profile, onboarding state, stable initial-workspace provision key/result |
| User `operations` | Onboarding operation, subject binding, progress/result |
| Workspace `workspaces` | ID, name, state `provisioning/active/deleting/deleted`, revision, unique provision key |
| Workspace `workspace_members` | PK workspace/user, role `owner/editor/viewer`; unique partial index allows at most one Owner |
| Workspace `workspace_storage` | Workspace, opaque quota bucket and drive filesystem IDs |
| Workspace `workspace_invitations` | ID, workspace/email, role restricted to editor/viewer, unique token hash, expiry, revoked/accepted state, accepted user |
| Workspace `operations` | Initiator, workspace/provision scope, unique request identity, fingerprint, state/result |

Exactly one Owner is preserved by creating the workspace/member together and serializing all member/owner mutations on the workspace row. Re-read actor authorization and lifecycle after acquiring it. Transfer demotes the old Owner and promotes an existing member in the same transaction; the partial index blocks duplicates. Owner cannot leave/be removed until transferred, except final workspace deletion. No duplicated owner column or custom owner-consistency trigger.

Invitation tokens are 32 random bytes; store SHA-256 only and return the raw link once with no-store responses. Replace/revoke a lost invitation rather than persist a plaintext replay response. Normalize email conservatively and consistently; no provider-specific dot/plus rewrites. Accept checks trusted verified email, token validity and configured member cap under workspace/invitation locks, then creates membership and records acceptance together. A repeated token must never restore a removed member or overwrite a changed role.

## letfs tables

| Table | Fields / responsibility |
|---|---|
| `quota_buckets` | ID, unique provision key, logical limit/used, lifecycle |
| `filesystems` | ID, bucket FK, unique provision key, root ID, lifecycle, transactional node count and configured maximum |
| `nodes` | ID, filesystem, parent, name, kind, logical size, revision, optional staging operation, timestamps |
| `file_data` | Node PK/FK, storage kind, inline bytes XOR immutable object key; directories have no row |
| `trash_entries` | ID, filesystem, unique detached root, original parent/name, deletion actor/time, state |
| `uploads` | ID, scope, initiating actor, destination/overwrite precondition, candidate key, transfer state/deadline, actual size/checksum, final result |
| `operations` | Scope, kind, initiator, request identity/fingerprint, state/result, bounded progress; processing source identity, supersession and active attempt |
| `copy_items` | Operation/source-node unique mapping, destination node, captured source revision/data key, frozen immediate file-child IDs, enumeration cursor, item state and registered target object key |
| `deletion_items` | Operation/node unique traversal/checkpoint state for bounded postorder deletion |
| `object_deletions` | Unique immutable object key (and version if applicable), bucket attribution, eligibility time, retry/completion state |

Copy/deletion items are concrete recovery state, not a generic job framework. `file_data` is one-to-one with a file, not shared storage content. Staging is unreachable from the live root and uncharged until publication. Keep a terminal operation marker so staging rows do not need a bulk rewrite at publication.

## Tree and paths

- Unique `(filesystem_id,id)` supports same-filesystem parent/root FKs. Ordinary writes require a writable directory parent. Internal artifact publication attaches read-only children beneath a source file. Sibling names are unique by `(filesystem_id,parent_id,name)` with deterministic case-sensitive comparison.
- Root is immutable as a tree root; only filesystem deletion can remove it. Detached trash/staging roots have no parent; a null parent alone does not imply live root.
- Reject empty ordinary names, slash, NUL, `.` and `..`; validate byte/depth bounds. No symlink interpretation or Unicode normalization that silently changes names/content.
- A single recursive statement walks indexed parent/name edges from the selected filesystem root. ID/cwd reads verify ancestry reaches that live root in the same statement snapshot. Trash/staging IDs cannot bypass visibility.
- File nodes support traversal, listing and cwd while retaining their own payload. Strict descendants of files are read-only, including raw-ID access. Root-relative `@<canonical UUID>` aliases resolve live nodes within the selected filesystem; only that exact root-name pattern is reserved. Nested matching names and `@notes` remain ordinary names.
- Mounts expose whole filesystem roots from a trusted internal context. Normalize paths, apply longest segment-boundary mount match and prevent `..`/cwd escape. Unknown mount, cross-filesystem destination or foreign ID is rejected. Public clients cannot provide mount contexts.
- Mutation handlers resolve or revalidate all locators after taking locks. Check cycles, same filesystem, directory parent, name conflicts, revisions and lifecycle within the transaction. Existing-node path mutations compare `expected_node_id` and revision; path-selected destination parents compare `expected_parent_id`. A replacement node may have the same revision value but is never the old target.

## Locking and quota

Order: bucket (when accounting/lifecycle needs it), filesystem, operation, affected nodes in stable ID order. Pure structural operations may lock only the filesystem and must never acquire the bucket afterward. Network I/O always occurs outside transactions. All writers follow this policy, including activity batches and cleanup admission.

For `delta = new_size - old_size`, metadata/data publication and a checked conditional usage update occur in one transaction. All node creations also check/update the filesystem node count under its existing lock; the configured cap includes roots, empty files/directories, trash and staging. Deletion decrements only actually removed nodes in its batch, and tests reconcile count with actual rows. This is an operational metadata bound, not billing or a generic quota engine. Positive delta requires active bucket/filesystem and available limit; zero/shrinking operations still validate allowed lifecycle and counter bounds. Locking/conditional update prevents concurrent oversubscription. Limit reductions below usage allow reads and size reduction but no positive growth.

Trash, restore and same-filesystem move have zero delta. Published copy charges full logical bytes. Purge subtracts only charged nodes actually removed in that transaction. Unpublished staging cleanup has zero debit. Maintain charged/staging context from the operation state so retries cannot double-charge/debit. A maintenance/test SQL reconciliation sums charged live and trash nodes and compares counters; no automatic repair workflow.

## Upload, overwrite and cleanup

Before new object-producing admission, check configured per-bucket outstanding upload/copy counts and pending-cleanup backlog using existing rows under the bucket lock. Keep failed/ambiguous work outstanding until safe cleanup. File-size, per-copy byte/node ceilings, deadlines and finite slots bound each admitted job; pause new admission if cleanup stalls. This is backpressure, not reserved logical bytes or an exact physical-storage quota. Previously admitted work can add a bounded cleanup tail.

1. Persist an idempotent upload session, caller-selected inline/object mode, expected size and destination precondition. Inline has no object key. Objects use `objects/<quota-bucket-id>/<upload-id>`; overwrites always get a fresh immutable key.
2. Transfer bounded inline bytes through the API, or object bytes directly to signed conditional PUT/native multipart. Bind exact size and Content-MD5; freeze ordered multipart completion receipts. Backend services neither classify storage mode nor relay object bodies.
3. Finalize verifies provider size/ETag evidence outside locks, then revalidates scope, source revision, destination, lifecycle and hard quota under bucket/filesystem/upload locks. Publication and saved result commit once. Overwrite queues old bytes, detaches/checkpoints old artifacts, supersedes former intent and records eligible new intent in the same transaction. Quota/revision refusal preserves the old file.
4. Abort/expiry is terminal and fences late finalize. Keep records of timed-out/ambiguous writes after attempted cleanup: a network timeout is not proof S3 stopped writing. Enforce I/O deadlines and periodically retry terminal-key cleanup; do not erase the last key record on one NotFound response. Configure provider incomplete-multipart cleanup if multipart is used.
5. GC retains candidate evidence past issued write-URL expiry plus transfer grace, and protects old downloads with the configured GET lifetime and deletion grace. Atomically claim only keys with no current file-data reference, live upload candidate or active copy-item target. Publication and GC claims use owning row locks to prevent a deleted key from being published.
6. S3 delete happens outside DB locks; inspect per-key errors even on HTTP success. Missing objects are successful deletes, but ambiguous in-flight writes retain cleanup evidence. Versioned stores require exact version handling/provider retention policy; key-only deletion may leave physical versions. Physical GC can lag logical deletion and must remain observable.

Inline-to-object and object-to-inline swaps use the same revision/quota transaction. Read inline bytes in one statement snapshot. Object reads use the selected immutable key; the deadline/grace rule protects old readers without per-download leases.

## Trash, restore and deletion

Short trash/restore/file-purge mutations atomically check lifecycle, stable identity and original revision, without request-response receipt rows. Repeated requests may return 404/409/412 and require authorized live/trash-state reconciliation. Do not upgrade the revision and reapply old intent. A new trash cycle creates a fresh trash-entry identity; node revisions remain monotonic across trash and restore, so old requests cannot affect a later cycle.

Trash records original parent/name and detaches only the subtree root. Descendants/IDs remain intact and charged. Restore claims the entry under the filesystem lock, rejects purging, verifies original or explicitly supplied live destination and name availability, then reattaches atomically. No automatic rename/overwrite. A separately trashed child does not reappear when its former parent is restored. Purging the original parent must not cascade away a separate trash entry; preserve a nullable original-parent reference.

Purge claims `trashed -> purging`, then uses durable bounded postorder batches through either node kind. Checkpoints, removed nodes, quota debit and object-deletion rows commit together. A childless file can use one direct transaction; files with artifacts use durable traversal. Trash permanently fails affected pending processing intents; restore preserves attached published children but does not restart failed processing. Filesystem deletion disables lifecycle, fences work, then removes all live/trash/staging roots and uploads. Tombstones/cleanup evidence outlive logical removal.

## Temporary archives

Archive jobs reuse `operations` with `kind=export-archive`. `export_attempts` owns
each immutable temporary key, native multipart ID, execution deadline, result size
and retention expiry. The operation points to its current generation/invocation;
publication locks that row and the owning bucket/filesystem, compares the captured
tree with current metadata, and records only a fully completed winner. Maintenance
cannot race a failed operation back to success.

Entries and inline data batches stay in bounded worker memory. No archive manifest,
node tree or quota charge is persisted. Cleanup evidence is created before writes,
protects live/current unexpired results and survives ambiguous remote outcomes.
Ordinary `objects/` never receives an age-based expiry policy.

## Recursive copy: no whole-tree snapshot

Copy/move is within one filesystem only. Reject copying a container into itself/descendant. A childless inline-file copy is one transaction. Object files, directories and files with children use a durable operation with detached destination, independent data and final quota admission. Copy captures each file's payload and immediate artifact-root IDs together, including an empty set; later artifact publication is excluded. Copy does not inherit processing intent. A copied-out artifact becomes writable when no file ancestor remains.

Replacement detaches old artifact roots into an existing deletion checkpoint operation. Maintenance drains these forests without a new cleanup workflow. Successful copy/processing publishers stay succeeded so charged descendant removal debits usage exactly once. Source revisions and payload timestamps do not change when artifacts are attached.

Prepare records source/destination and starts durable traversal. On first opening a directory, persist its maximum observed child ID as a finite upper bound, then enumerate children by stable node ID up to that bound, not mutable name, and persist source-to-destination mappings with uniqueness per operation. Re-read source liveness/parent/revision when processing an item. For object copy, capture an immutable source key and register the destination key before I/O; after I/O, validate that source version and job state before committing the staged item. Missing/changed source returns `SOURCE_CHANGED`; infrastructure response loss retries the same frozen item. Timed-out attempts cannot switch that item's key/source or publish after discard.

Directory copy does not promise one instant's tree: concurrently added entries may be omitted, moved-out unobserved entries may be absent, and each directory is enumerated at the times its pages run. Already encountered moved/deleted/changed items fail when detected; each source ID appears at most once. Do not claim all source mutations are detected or that success proves a snapshot. If snapshot semantics become required, explicitly redesign rather than adding hidden global fencing.

Enforce a finite configured per-copy node/byte and overall execution budget as well as per-batch budgets, failing and cleaning staging on exhaustion. Per-directory ID upper bounds alone do not stop continually nested new directories. Bytes need never exceed the captured maximum copy allowance (no larger than the bucket limit for an operation that could publish).

When traversal is done, lock bucket/filesystem/operation, validate destination and operation state, admit aggregate logical bytes and attach the staging root in one transaction. Recheck destination ancestry against the source as well as name/liveness at publication; concurrent destination moves must not make a self/descendant copy valid. Concurrent finalizers observe a single published result. On failure mark discarding before cleanup; a retry after successful publication must return the published result and never discard it. Discarded staging is removed in batches with no quota debit; retain cleanup keys for late object writes. Unknown workflow status is not proof of abandonment.
