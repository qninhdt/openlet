> Historical snapshot, superseded on 2026-10-30 by the user-approved [direct-child artifact plan](../261029-1624-artifact-file-processing/plan.md). Its schema, path, ownership and pending-review statements describe the previous draft; do not execute them. Use the current plan and [validation report](./validation-261030-0737-hybrid-artifact-plan.md). General runtime/source evidence remains useful where the current plan retains it.

# Openlet letfs Artifact Integration Research

Conducted: 2026-10-29 (Asia/Ho_Chi_Minh)

## Outcome

The smallest coherent extension is to keep artifacts in the existing `nodes`,
`file_data`, `uploads`, `operations`, quota, and deletion model, but add an
explicit ownership/liveness boundary. A source file owns one nullable
`nodes.artifact_dir_id` pointing to a detached directory in the same
filesystem. Artifact descendants remain ordinary nodes and file-data rows; no
second filesystem and no physical `.artifacts` or `.nodes` nodes are needed.

Expose them only through virtual path aliases:

```text
/.artifacts/<source-id>/...  -> source.artifact_dir_id and descendants
/.nodes/<node-id>/...         -> any scoped file/directory ID
```

`.nodes` is a generic scoped ID alias, not an artifacts-only namespace. Raw
`{node_id}` and both path aliases must use one common visibility predicate: live
ordinary nodes require live-root ancestry; published artifact nodes additionally
require a live source owner. The same predicate must feed readonly checks, so
no ID form can bypass artifact lifecycle or mutability rules.

## Contents

- [Current contracts and evidence](#current-contracts-and-evidence)
- [Minimal storage representation](#minimal-storage-representation)
- [Path visibility and read-only boundary](#path-visibility-and-read-only-boundary)
- [Lifecycle, overwrite, quota, and cleanup](#lifecycle-overwrite-quota-and-cleanup)
- [Upload dispatch and workflow](#upload-dispatch-and-workflow)
- [Concrete change/test surfaces](#concrete-changetest-surfaces)
- [Resolved decisions and remaining risk](#resolved-decisions-and-remaining-risk)

## Current contracts and evidence

Repository docs and current code are the authoritative sources for this
scouting pass; the existing integration and E2E tests are the behavioral
cross-check. There is no existing artifact implementation or Docling/Python
dependency.

- The canonical tree is an adjacency list with stable IDs; live path/ID
  resolution must reach `filesystems.root_id`, and detached trash/staging IDs
  must not bypass visibility ([`docs/data-model.md:44-51`](../../docs/data-model.md#L44),
  [`services/letfs/src/fs/paths.rs:87-126`](../../services/letfs/src/fs/paths.rs#L87)).
- `nodes` currently has only `staging_operation_id` as detached-work metadata;
  parent/name/kind/size/revision and same-filesystem parent FKs are defined in
  [`services/letfs/migrations/0001_foundation.sql:20-34`](../../services/letfs/migrations/0001_foundation.sql#L20).
- Trash detaches a root by setting `parent_id=NULL`, while `trash_entries`
  retains ownership/lifecycle metadata ([`services/letfs/src/fs/trash.rs:39-57`](../../services/letfs/src/fs/trash.rs#L39)).
  Copy staging uses `staging_operation_id` and is published by reattaching its
  root ([`services/letfs/src/fs/copy.rs:146-184`](../../services/letfs/src/fs/copy.rs#L146),
  [`services/letfs/src/fs/copy.rs:350-401`](../../services/letfs/src/fs/copy.rs#L350)).
- Upload finalization currently resolves its saved destination under a row
  lock, charges the byte delta, replaces/creates the node, and marks the upload
  finalized in one transaction ([`services/letfs/src/fs/uploads.rs:188-259`](../../services/letfs/src/fs/uploads.rs#L188)).
- Filesystem deletion enumerates every `parent_id IS NULL` root, but a trash
  purge only traverses the selected root ([`services/letfs/src/fs/deletion.rs:151-218`](../../services/letfs/src/fs/deletion.rs#L151)); this is the key lifecycle gap for a detached artifact directory.
- Quota and node count are commit-time logical accounting. Trash remains
  charged, staging cleanup is uncharged, and all removals use the shared
  `deletion::remove` transaction core ([`services/letfs/src/fs/nodes.rs:86-100`](../../services/letfs/src/fs/nodes.rs#L86),
  [`docs/data-model.md:53-70`](../../docs/data-model.md#L53)).
- The workspace facade forwards locators unchanged and always supplies the
  `/drive` mount; alias grammar therefore belongs in letfs path resolution,
  not in a second Go-side parser ([`services/workspace/internal/http/files.go:17-35`](../../services/workspace/internal/http/files.go#L17),
  [`services/workspace/internal/http/files.go:61-176`](../../services/workspace/internal/http/files.go#L61)).

## Minimal storage representation

Add one migration after `0006`:

```sql
ALTER TABLE nodes ADD COLUMN artifact_dir_id uuid;
ALTER TABLE nodes
  ADD CONSTRAINT node_artifact_dir_same_fs
  FOREIGN KEY (filesystem_id, artifact_dir_id)
  REFERENCES nodes(filesystem_id, id);
CREATE UNIQUE INDEX nodes_one_artifact_owner
  ON nodes(artifact_dir_id) WHERE artifact_dir_id IS NOT NULL;
```

The source file row owns the relationship. The referenced directory is a
detached, same-filesystem node (`parent_id IS NULL`, `kind='directory'`) whose
children are generated artifact files/directories. The unique partial index
prevents two sources from claiming one root. SQL cannot enforce the referenced
row's `kind` or the source's `kind='file'`; creation and publication must check
both under the filesystem lock. Do not add a reverse owner column to every
artifact node: ownership is derived by walking from the artifact root to the
source's `artifact_dir_id`, avoiding duplicate state.

Artifact roots consume node-count capacity and artifact bytes consume the
source filesystem's existing quota bucket. They are not another filesystem,
object namespace, or content-sharing entity. Their object keys can use the
existing bucket-prefixed key format; no `.artifacts`/`.nodes` database rows or
S3 directory markers are required.

For generated output that must be discarded before publication, use the
existing `staging_operation_id`/`operations` state and shared deletion core.
Do not make a detached artifact root visible merely because it has
`parent_id=NULL`; that condition currently also matches trash and copy roots.

## Path visibility and read-only boundary

Extend `paths::resolve` as one bounded SQL resolution path, preserving its
single-statement ancestry check and batch behavior:

1. Parse the first path segment before ordinary `parts` walking. For
   `.artifacts/<uuid>`, resolve the source by ID in the requested filesystem,
   verify it is a live file whose ancestry reaches `filesystems.root_id`, then
   use its `artifact_dir_id` as the virtual root. Missing root or source returns
   the same hidden 404 as a missing path.
2. For `.nodes/<uuid>`, resolve any scoped file/directory ID. Ordinary nodes
   must be live descendants of the filesystem root. Artifact nodes must also
   be below a source's `artifact_dir_id`, with that source currently live.
   Detached trash/staging nodes must not match.
3. Reject `..` from escaping a virtual artifact root. Keep path length/depth,
   NUL, mount-boundary, and directory-suffix checks. Do not change the trusted
   `/drive` mount contract or add an arbitrary filesystem selector.
4. Route `{node_id}` through the same common visibility predicate rather than
   preserving the current live-root-only branch as an incompatible special
   case. Internal artifact workflow code should use the source-aware form of
   that predicate.

The alias result should still return ordinary `Node` metadata. A plain
per-source artifact status endpoint is part of the accepted surface for
checking pending/ready/failed processing; it need not expose detached root IDs
or add artifact metadata to every `Node` response.

Every mutating entry point must reject an artifact-resolved node or parent with
one consistent read-only state error: `nodes::create/modify`, upload target and
finalize, `trash`, `restore`, and copy publication destination. Copying an
artifact *as a source* into a normal live directory is allowed because it only
reads the artifact; its durable recheck must use the owner-aware resolver.
Trash/restore/purge are never public operations on an artifact: source trash
hides the aliases, source restore re-enables them, and source purge removes the
artifact subtree. These checks apply identically through raw IDs, `.nodes`, and
`.artifacts` paths.

## Lifecycle, overwrite, quota, and cleanup

### Source trash/restore/purge

- Trash only detaches the source root. The artifact root remains detached but
  becomes invisible because alias resolution requires a live source. This
  preserves source and artifact identity without moving every artifact row.
- Restore only reattaches the source; aliases become visible after the same
  transaction. No artifact-specific restore table is needed.
- Purging a source (file or directory) must enqueue its artifact roots into the
  same bounded `deletion_items` traversal. Current `deletion::batch` only
  discovers `parent_id` children, so it will otherwise leave detached artifact
  rows charged and count them forever. When a leaf batch contains a node with
  `artifact_dir_id`, insert that root into the operation's deletion checkpoint
  before removing the source. Use `ON CONFLICT DO NOTHING` and stable depth;
  do not perform a recursive per-node Rust loop.
- Filesystem deletion already scans detached roots, but its completion check
  must still include artifact roots and its publication fence must stop any
  artifact completion. The root scan must not be used as the visibility rule.

### Overwrite and source identity

Upload overwrite keeps the source node ID but increments its revision (the
current behavior at [`services/letfs/src/fs/uploads.rs:216-229`](../../services/letfs/src/fs/uploads.rs#L216)). The old artifact root must be invalidated in that same finalize transaction:

1. Lock the source row and saved upload precondition.
2. Clear `nodes.artifact_dir_id` and create a bounded artifact-root deletion
   operation for the old root (or mark the existing artifact operation
   discarding before cleanup).
3. Publish the new file bytes/revision and persist the new artifact dispatch
   intent with the resulting source ID and revision.

The old root must become unresolvable immediately; physical metadata/object
cleanup may finish asynchronously. Do not use `nodes.revision` as the sole
processing version: the current code also bumps it for rename/move/lifecycle
changes, which would make a valid content job fail merely because metadata
changed. Capture source ID plus immutable content identity in the artifact
operation instead. For object-backed input, `file_data.object_key` is already
immutable; for inline input, capture the SHA-256 digest. The successful upload
candidate already stores that digest in `uploads.sha256` at
[`services/letfs/migrations/0004_uploads.sql:1-16`](../../services/letfs/migrations/0004_uploads.sql#L1), so finalize can place it in the operation input/fingerprint without adding
`nodes.content_revision`. At completion, lock the source and compare the
current object key or inline digest; content replacement/overwrite then
supersedes the old operation, while a metadata-only rename/move does not.
Always require the source to be live and the source ID to match. If product
semantics require trash/restore to permanently cancel a run rather than pause
it, mark the operation failed when trashing; otherwise completion after restore
must still recheck liveness.

Use the existing `nodes::Session::usage` and `add_nodes` lock order for final
artifact publication. Artifact staging is bounded and uncharged, matching
existing copy accounting: charge the aggregate generated bytes and attach the
root in one transaction; failed staging deletion debits zero. Reuse
`staging_operation_id` and the shared discard/deletion paths rather than adding
reservations or a second quota ledger.

### Read/delete/object cleanup

Generated files should use existing `file_data` inline/object rules. On source
purge or overwrite invalidation, call the shared `deletion::remove` path so
object keys become `object_deletions` records and quota/node counts change once.
Extend object-GC guards to treat active artifact staging outputs as live just as
they already protect `uploads` and `copy_items`; cleanup remains outside DB
locks. Do not add refcounts, epochs, leases, or a global artifact manifest.

## Upload dispatch and workflow

Auto-processing is eligible only after a successful upload create/overwrite
finalize whose final source name has a case-insensitive extension `pdf`,
`docx`, `xlsx`, or `pptx`. Virtual aliases remain case-sensitive like ordinary
names. Images, text, and legacy Office formats do not create an artifact
operation.

The current finalize transaction is the correct owner for the dispatch intent,
but it currently only updates `uploads` and `nodes`. Reuse `operations` with a
distinct `kind='artifact'`, `request_key=<upload-id>`, source ID, captured
object key or inline digest, validated input/fingerprint, and durable state.
Insert this row in the same transaction as source publication so a committed
upload cannot lose the processing request. Store no file bytes in the row or
Temporal history.

After commit, attempt a stable workflow start such as
`artifact/<filesystem>/<source-id>/<operation-id>` using the existing
Temporal client/reuse policies. If the process dies before start, extend the
existing `StorageMaintenance` path to find running artifact intents and retry
the stable start. The operation row is the recovery record; do not introduce a
separate dispatch outbox/replay framework. Treat a running row with no started
workflow as pending dispatch in status/maintenance, not as successful work.

The workflow should carry only operation/source IDs; the operation row holds
the captured content identity. It invokes
exactly one Python activity whose bounded contract performs:

```text
download source -> Docling conversion -> export -> upload staged outputs -> complete
```

The completion operation, implemented in Rust, must lock the operation, source,
filesystem and bucket; verify source liveness, source ID, captured object
key/inline digest, and operation state; publish/link one artifact root; and
mark the operation succeeded atomically.
Any mismatch marks the old operation failed/discarding and cleans its staged
outputs. This is the only place that may set `source.artifact_dir_id`.

Current Rust workers register only `CopyNode`, `PurgeTrash`,
`DeleteFilesystem`, and `StorageMaintenance` ([`services/letfs/src/main.rs:63-79`](../../services/letfs/src/main.rs#L63)); there is no Python activity registration or cross-language activity contract. The requested Rust-workflow/Python-activity boundary is therefore an explicit architecture addition, not an existing capability to wire by name. Keep it one activity, bounded, and free of AI; do not split it into download/convert/export/upload activities or place bytes in workflow history.

## Concrete change/test surfaces

Production implementation should touch these owners, with no unrelated
framework additions:

- `services/letfs/migrations/0007_*.sql`: `artifact_dir_id`, same-FS FK, and
  unique owner index. Prefer the existing `operations.input`/fingerprint for
  captured source object key/digest; do not add a `nodes.content_revision`
  column unless later evidence requires a queryable version index.
- `services/letfs/src/fs/paths.rs`: virtual alias parsing, live-source/root
  ownership query, virtual-root `..` fence, and batch resolution.
- `services/letfs/src/fs/nodes.rs`: explicit artifact-aware read-only and
  lifecycle helpers; preserve quota/node-count lock order.
- `services/letfs/src/fs/uploads.rs`: final source classification, overwrite
  invalidation, same-transaction artifact intent, and internal staged-output
  completion path; keep normal uploads unchanged for ineligible suffixes.
- `services/letfs/src/fs/trash.rs`, `deletion.rs`, `copy.rs`,
  `maintenance.rs`: source lifecycle propagation, artifact-root deletion,
  artifact source recheck, orphan dispatch, and object-GC protection.
- `services/letfs/src/temporal/{mod.rs,*.rs}` and `main.rs`: one Rust artifact
  workflow, stable admission/retry, one Python activity contract, registration,
  and replay coverage. Existing workflow admission helpers are in
  [`services/letfs/src/temporal/mod.rs:76-196`](../../services/letfs/src/temporal/mod.rs#L76).
- `services/letfs/src/http/mod.rs` and `services/workspace/internal/http/files.go`:
  add the plain per-source artifact status route, while keeping aliases
  forwarded verbatim. Contract tests must preserve readonly errors and status
  scope; update OpenAPI for the status route only.
- `services/letfs/tests/integration.rs` and `tests/e2e/`: real PG/S3 tests for
  alias visibility, quota/count reconciliation, source trash/restore/purge,
  filesystem deletion, overwrite races, object cleanup, and response-loss
  dispatch. Add workflow replay/history tests alongside existing
  `services/letfs/tests/workflow-replay.rs`.

Minimum regression matrix:

| Case | Required assertion |
|---|---|
| Alias stat/list/content | `.artifacts`, `.nodes`, and raw IDs use the same source-liveness predicate; no physical root names are needed. |
| Artifact ID scope | A live published artifact ID is readable through either ID alias but remains readonly; trashed/invalidated owners are hidden. |
| Mutations | Create/replace/upload/move/trash/restore/purge reject artifact targets/parents; copy source is read-only-safe. |
| Source lifecycle | Trash hides aliases; restore reveals; file/directory purge removes all artifact rows, objects, quota, and node count exactly once. |
| Overwrite race | Old aliases disappear immediately; old workflow cannot publish; new content identity can publish exactly once. |
| Dispatch | PDF/DOCX/XLSX/PPTX create one durable intent; image/text/legacy Office create none; committed intent is recovered by maintenance after start failure. |
| Recovery | Activity/workflow retries and response loss do not duplicate roots/files or charge twice; filesystem deletion fences late completion. |

These are aligned with the existing required tree, quota, trash, object,
recovery, and efficiency checks ([`docs/testing.md:16-33`](../../docs/testing.md#L16)). Use set-based bounded SQL; no N+1 artifact-owner queries.

## Resolved decisions and remaining risk

The following are accepted choices for implementation, not questions to reopen:

- Virtual aliases are case-sensitive; eligibility extensions are
  case-insensitive for `pdf`, `docx`, `xlsx`, and `pptx`.
- `.nodes/<id>` resolves all scoped file/directory IDs. `.artifacts/<source>`
  resolves the source-owned root. Raw IDs and both paths share one
  source-liveness/readonly predicate for published artifacts.
- A plain per-source artifact status endpoint is part of the API surface; it
  reports pending/ready/failed state without exposing detached root internals.
- Generated staging is bounded and uncharged, using existing copy accounting;
  aggregate bytes are charged only when the artifact root publishes.
- Copying an artifact into a normal live directory is allowed. Direct edits,
  upload targets, moves, trash, restore, purge, and artifact destinations are
  readonly-rejected.
- Source fencing uses source ID plus immutable object key or inline digest.
  `uploads.sha256` supplies the finalize digest; no `content_revision`, global
  epoch, lease, refcount, or source pin is needed.
- The Python activity worker/queue/runtime is accepted integration scope. The
  Rust workflow still invokes exactly one bounded Python activity and keeps
  bytes out of Temporal history.

Implementation remains scoped to the detached same-FS root, unique owner
index, owner-aware alias SQL, `operations` dispatch intent, maintenance retry,
and shared deletion/object/quota paths. No container, database, or production
mutation was performed for this report.

Status: DONE
Summary: Existing letfs can host artifacts with one ownership pointer and detached ordinary nodes, but path liveness, readonly enforcement, source purge/overwrite cleanup, and reliable post-finalize dispatch all require explicit adaptations. The report identifies the smallest owners and regression surfaces.
Concerns/Blockers: No product blocker remains; implementation risk is concentrated in preserving one common alias visibility predicate and bounded set-based cleanup across source lifecycle races.
