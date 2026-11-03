# Data model and consistency

Status: implementation contract, not executable DDL. Service-local migrations must implement these invariants and the focused tests in [testing](testing.md). Fields below are the minimum responsibilities, not a requirement for extra ORM/framework layers.

## Common conventions

UUIDv7 entity IDs, UTC timestamps, checked signed 64-bit byte counters/revisions, nonnegative sizes. API byte counts and revisions are decimal strings. Mutations use revision ETags. File revisions change for content/name/location/lifecycle changes; directory revisions also change when their child set changes. No filesystem-wide mutation epoch.

Non-natural creation admissions retain scoped key/hash and immutable result identity in `idempotency_keys`. Copy receipts contain admission identities and ceilings, never traversal/progress. Temporal owns bounded copy traversal and execution results. Trash/restore/purge use resource identity without receipt rows. Unfinished receipts stay pinned; completion starts a non-extending 24-hour TTL. Keep secrets and file bodies out of workflow history.

## User and Workspace databases

| Table | Fields / invariant |
|---|---|
| Account `users` | ID, unique Clerk subject, profile, onboarding state, stable initial-workspace result |
| Workspace `workspaces` | ID, name, `provisioning/active/failed/deleting/deleted` lifecycle, revision, owner-generated storage mapping and limit |
| Workspace `workspace_members` | PK workspace/user, role `owner/editor/viewer`; unique partial index allows at most one Owner |
| Workspace `workspace_invitations` | ID, workspace/email, role restricted to editor/viewer, unique token hash, expiry, revoked/accepted state, accepted user |
| Workspace `idempotency_keys` | Actor/key/request hash and admitted workspace identity; completed receipts expire after 24 hours |

Exactly one Owner is preserved by creating the workspace/member together and serializing all member/owner mutations on the workspace row. Check the specific SpiceDB action before acquiring the row lock, then re-read canonical actor membership, revision and lifecycle under the lock. No graph RPC runs while holding that lock. Transfer demotes the old Owner and promotes an existing member in the same transaction; the partial index blocks duplicates. Owner cannot leave/be removed until transferred, except final workspace deletion. No duplicated owner column or custom owner-consistency trigger.

Invitation tokens are 32 random bytes; store SHA-256 only and return the raw link once with no-store responses. Replace/revoke a lost invitation rather than persist a plaintext replay response. Normalize email conservatively and consistently; no provider-specific dot/plus rewrites. Accept checks trusted verified email, token validity and configured member cap under workspace/invitation locks, then creates membership and records acceptance together. A repeated token must never restore a removed member or overwrite a changed role.

## letfs tables

| Table | Fields / responsibility |
|---|---|
| `quota_buckets` | Caller-chosen stable ID, logical limit/used, lifecycle |
| `filesystems` | Caller-chosen stable ID, bucket FK, root ID, lifecycle and transactional node count; maximum comes from runtime configuration |
| `nodes` | ID, filesystem, parent, name, kind, logical size, revision, timestamps |
| `files` | Node PK/FK, storage kind, inline bytes XOR immutable object key, MIME/title/description/semantic type/context; current source generation and one pipeline status; directories have no row |
| `trash_entries` | ID, filesystem, unique detached root, original parent/name, deletion actor/time, state |
| `uploads` | ID, scope, initiating actor, captured destination/revision, immutable candidate, open/completing/finalized/aborted lifecycle, expiry/deadline, expected size verified at completion and immutable completion result; processor publication attaches a separate result-node reference |
| `idempotency_keys` | Scoped admission key/hash/result identity; active upload/copy receipts pinned, terminal receipts expire after 24 hours without retry extension |
| `index_deletions` | File/generation cleanup identity and next eligibility; survives removal of source rows |
| `object_deletions` | Unique immutable object key (and version if applicable), bucket attribution, eligibility time, retry/completion state, unresolved presigned ambiguity and backend open-write count |

`files` is one-to-one with a file. Structural reads join metadata only for files; directories have no MIME or semantic fields. Every copied node is ordinary, visible and charged in its own commit. There is no operation/item/staging table or aggregate copy publication.

## Tree and paths

- Unique `(filesystem_id,id)` supports same-filesystem parent/root FKs. Ordinary writes require a writable directory parent. Internal artifact publication attaches read-only children beneath a source file. Sibling names are unique by `(filesystem_id,parent_id,name)` with deterministic case-sensitive comparison.
- Root is immutable as a tree root; only filesystem deletion can remove it. Detached trash/artifact roots have no parent; a null parent alone does not imply live root.
- Reject empty ordinary names, slash, NUL, `.` and `..`; validate byte/depth bounds. No symlink interpretation or Unicode normalization that silently changes names/content.
- A single recursive statement walks indexed parent/name edges from the selected filesystem root. ID/cwd reads verify ancestry reaches that live root in the same statement snapshot. Detached IDs cannot bypass visibility.
- File nodes support traversal, listing and cwd while retaining their own payload. Strict descendants of files are read-only, including raw-ID access. Root-relative `@<canonical UUID>` aliases resolve live nodes within the selected filesystem; only that exact root-name pattern is reserved. Nested matching names and `@notes` remain ordinary names.
- Mounts expose whole filesystem roots from validated request context. Normalize paths, apply longest segment-boundary mount match and prevent `..`/cwd escape. Unknown mount, cross-filesystem destination or foreign ID is rejected. HTTP callers choose a virtual label for the requested filesystem; native callers supply bounded descriptors. Every selected filesystem requires its own action check.
- Mutation handlers resolve or revalidate all locators after taking locks. Check cycles, same filesystem, directory parent, name conflicts, revisions and lifecycle within the transaction. Existing-node path mutations compare `expected_node_id` and revision; path-selected destination parents compare `expected_parent_id`. A replacement node may have the same revision value but is never the old target.

## Locking and quota

Order: bucket (when accounting/lifecycle needs it), filesystem, affected nodes in stable ID order. Pure structural operations may lock only the filesystem and must never acquire the bucket afterward. Network I/O always occurs outside transactions. All writers follow this policy, including activity batches and cleanup admission.

For `delta = new_size - old_size`, metadata/data publication and a checked conditional usage update occur in one transaction. All node creations also check/update the filesystem node count under its existing lock; the configured cap includes roots, empty files/directories, trash and detached artifacts. Deletion decrements only actually removed nodes in its batch, and tests reconcile count with actual rows. This is an operational metadata bound, not billing or a generic quota engine. Positive delta requires active bucket/filesystem and available limit; zero/shrinking operations still validate allowed lifecycle and counter bounds. Locking/conditional update prevents concurrent oversubscription. Limit reductions below usage allow reads and size reduction but no positive growth.

Trash, restore and same-filesystem move have zero delta. Each committed copy item charges its logical bytes once. Purge subtracts only nodes actually removed in that transaction. A reconciliation query can sum all file bytes, including detached forests and trash, against usage; no automatic counter-repair workflow.

## Upload, overwrite and cleanup

Before new object-producing admission, check configured per-bucket outstanding upload/copy counts and pending-cleanup backlog using existing rows under the bucket lock. Incomplete copy receipts count as outstanding work; unresolved write evidence counts against cleanup backlog, even after a successful delete. File-size, per-copy byte/node ceilings, deadlines and finite slots bound each admitted job; pause new admission if cleanup stalls. This is backpressure, not reserved logical bytes or an exact physical-storage quota. Previously admitted work can add a bounded cleanup tail.

1. Commit the upload session and caller/filesystem-scoped `create-upload` receipt together. Public upload selects object transport by declared size; small inline content uses the node API without a session. Processor output can still use the shared bounded inline transport. Objects use `objects/<quota-bucket-id>/<upload-id>`; overwrites always get a fresh immutable key.
2. Transfer object bytes directly to a signed conditional PUT or native multipart. Single PUT binds exact size and provider-enforced Content-MD5. Multipart binds each part's size and freezes ordered opaque ETag receipts before completion; no whole-object MD5 is synthesized. Browser signing uses the public endpoint and processor signing uses the internal endpoint.
3. Finalize checks provider size and unique candidate ownership outside locks, reconciling a lost multipart acknowledgment with HEAD. Revalidate scope, revision, destination, lifecycle and hard quota under bucket/filesystem/upload locks. Publication, saved result and receipt completion/24-hour expiry commit once. Overwrite queues old bytes, detaches old artifacts, supersedes former intent and records eligible new intent in the same transaction. Quota/revision refusal preserves the old file. Abort/expiry also completes the receipt; repeated completion never extends expiry.
   For processor sessions, finalize saves only the verified transfer result. Artifact publication separately validates its source generation, attaches the output and charges quota atomically. It preserves the transfer result. Finalized sessions issue no new capabilities and do not expire back into an active state. Discarded, unattached outputs retain their terminal result while durable cleanup removes unused bytes; repeated completion returns the saved result after attachment.
4. Abort/expiry is terminal and fences late finalize. Keep records of timed-out/ambiguous writes after attempted cleanup: a network timeout is not proof S3 stopped writing. Enforce I/O deadlines and periodically retry terminal-key cleanup; do not erase the last key record on one NotFound response. Configure provider incomplete-multipart cleanup if multipart is used.
5. GC claims only keys without current file references or active upload candidates under the bucket lock. Copy registers cleanup intent and increments `open_writes` before external I/O; a known successful response closes only that request's count in the publication/rejection transaction. Process death or an unknown response leaves its count pinned. Once a cleanup delete has been attempted, copy cannot reuse or publish that candidate key, preventing delayed cleanup from deleting newly published bytes. Presigned-write ambiguity and unresolved backend writes remain compact tombstones, deleted again daily without a guessed expiry. Count them against `MAX_CLEANUP_BACKLOG`.
6. S3 delete happens outside DB locks; inspect per-key errors even on HTTP success. Missing objects are successful deletes, but ambiguous in-flight writes retain cleanup evidence. Versioned stores require exact version handling/provider retention policy; key-only deletion may leave physical versions. Physical GC can lag logical deletion and must remain observable.

Inline-to-object and object-to-inline swaps use the same revision/quota transaction. Read inline bytes in one statement snapshot. Object reads use the selected immutable key; the deadline/grace rule protects old readers without per-download leases.

## Trash, restore and deletion

Trash checks lifecycle, node identity and original revision without request-response receipt rows. Restore and purge claim the current trash-entry identity under the filesystem lock. Repeated trash/restore may return 404/409/412 and require authorized live/trash-state reconciliation; repeated purge returns 202 or 204. Do not upgrade the revision and reapply old trash intent. A new trash cycle creates a fresh trash-entry identity; node revisions remain monotonic across trash and restore, so old requests cannot affect a later cycle.

Trash records original parent/name and detaches only the subtree root. Descendants/IDs remain intact and charged. Restore claims the entry under the filesystem lock, rejects purging, verifies original or explicitly supplied live destination and name availability, then reattaches atomically. No automatic rename/overwrite. A separately trashed child does not reappear when its former parent is restored. Purging the original parent must not cascade away a separate trash entry; preserve a nullable original-parent reference.

Replacing original bytes atomically detaches obsolete artifact roots. A detached root outside the filesystem root and trash is durable cleanup intent; no artifact-discard operation or item table is created. Maintenance follows one branch of at most 128 edges and removes at most 64 leaf siblings per root transaction. Remaining nodes are the retry checkpoint. Object cleanup intent, actual node removal and quota debit commit together; published bytes stay charged until removed.

Purge claims `trashed -> purging` before dispatch, then follows a branch of at most 128 edges and removes at most 64 leaf siblings per transaction through either node kind. The remaining nodes are its durable checkpoint; quota debit and object-deletion intent commit with actual removal. All purges use the same workflow; no operation/item row is allocated. Repeated entry DELETE returns 202 while admitted or 204 after removal. Maintenance redelivers purging entries when dispatch was lost. Trash permanently fails affected pending processing intents; restore preserves attached published children but does not restart failed processing. Filesystem deletion disables lifecycle, fences work, then removes all live/trash/artifact roots and uploads. Tombstones/cleanup evidence outlive logical removal.

## Directory archives

ZIP downloads have no database entity, receipt, workflow, stored archive or quota charge. The request preflights bounded metadata, then validates selected identities/revisions/paths against live ancestry while streaming bytes. The response body owns the producer, storage reads, concurrency slot and deadline; disconnect drops them together. Missing or changed input aborts the archive body.

## Recursive copy: no whole-tree snapshot

Copy/move stays within one filesystem and rejects copying into the source or its descendant. POST nodes with source_id commits one scoped receipt and immutable admission before dispatching `copy/<filesystem>/<copy-id>`. Destination UUIDv8 identities derive from copy ID and source ID. Both inline and object files use this one workflow.

Workflow input/history carries at most 128 traversal frames, one selected child and cumulative acknowledged node/byte counts. Each selected container captures a high-water child ID; keyset reads select one child at a time. Continue-As-New after 100 steps preserves that state. Captured per-copy node/byte limits, destination depth and a one-hour deadline bound traversal despite concurrent additions.

Each selected item's source identity/revision and destination-parent revision stay fixed across retries. A file's object key is immutable; inline bytes are reread only after source validation. Copy registers candidate evidence before S3 I/O, then revalidates source, parent/ancestor liveness, lifecycle and quota before committing an ordinary visible node. Repeated acknowledgment-loss attempts recognize the deterministic destination and charge nothing again. Changed/missing selected sources fail with SOURCE_REPLACED; destination mutation/deletion fails without recreating it. Counts advance only when a logical effect is acknowledged and can be lower bounds if an unacknowledged result was subsequently changed or deleted.

A failed copy keeps committed nodes and bytes. There is no rollback, detached staging, item mapping table or final aggregate publication. A new request key targeting an occupied name conflicts. A same-key request always returns its original admission handle. Temporal-backed GET copies checks current read permission and the admission actor or `copy_inspect_any` action; removed members fail the filesystem action check with 403. Unavailable retained history returns 410 COPY_EXPIRED. Ordinary copied nodes outlive monitor history.

File-child artifact structure and read-only ancestry are preserved. Completing a logical file subtree admits its processing generation once, reusing copied parsed artifacts before enrichment/indexing; derived descendants do not become independent processing roots. A file copied out of artifact ancestry becomes writable. If traversal stops before that subtree completes, its visible partial content stays available; manual reprocessing can replace incomplete derived content.

Concurrent additions may be omitted, moved-out unobserved children may be absent, and success does not prove a whole-tree snapshot. No source-retention pins, full manifest or filesystem epoch is introduced.

## Semantic metadata and search index

Semantic metadata and MIME belong to `files`. Direct sources are classified from their own bytes. Parsed files preserve their original bytes and attach generated children directly below the original file, without an intermediate directory. Enrichment classifies actual leaf files, then each directory README from its own text and already enriched child files/READMEs, deepest first. Directories never own semantic metadata. Folder slugs use their README result. One transaction publishes metadata, final names, Markdown links/replacements, revisions, quota deltas and publication readiness; the root README result is copied to the original file.

`files.desired_generation` increases for content replacement and manual reprocessing; rename/move preserves it. Source writes and generation changes commit together. Every output operation checks this generation and the current source lifecycle. Temporal owns Activity retries; there is no accepted-attempt counter or UUID protocol. Publication selects completed upload IDs returned by the worker and discards unused outputs. Repeated publication returns the committed result without rechecking a manifest hash.

`publication_status` is the single pipeline state: `not_required`, `pending` (parse needed), `parsed` (enrichment needed), `enriched` (index needed), `ready`, `failed` or `index_failed`. The last state preserves the distinction between failed semantic publication and failed indexing of already enriched content. Embedding configuration belongs to the running system, not file or cleanup rows.

Qdrant is rebuildable derived state. Immutable point IDs derive from source file, generation, full vector space, evidence file, point kind and ordinal. Payload contains `filesystem_id`, `source_id`, `file_id`, numeric `generation`, `embedding_model`, `vector_dimension` and `text`; the collection scopes the remaining space identity. PostgreSQL validates current metadata, authorization scope, ancestry, generation and pipeline readiness before reranking. Filename search remains independent of AI readiness.

Source supersession/deletion enqueues file/generation cleanup in `index_deletions` in the same transaction as invalidation/removal. Cleanup uses current system embedding configuration, waits for the source producer, rechecks current serving identity under lifecycle locks and retains compact tombstones for uncertain late writes. Explicit index rebuild reuses the source workflow ID and preserves parse/enrichment. Concurrent old/new embedding configurations and automatic configuration migration are outside the current scope. A restored ready source may reuse its current index; failed processing does not restart merely because it was restored.
