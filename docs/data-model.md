# Data model and consistency

Service migrations own executable DDL; [DBML](openlet.dbml) describes Go service tables and logical cross-service references. Leta's schema is linked below. Entity IDs use UUIDv7, timestamps UTC, byte counters/revisions checked int64. API counters/revisions are decimal strings. Node mutations use ETags; Workspace has no revision field.

## Account and Workspace

| Table | Responsibility |
|---|---|
| Account `users` | Human ID, mandatory unique Clerk identity, profile and timestamps |
| Workspace `workspaces` | ID/name, active/deleting/deleted status, one filesystem ID and shared scope ID |
| `workspace_members` | Workspace/user key, owner/admin/member role, active/inactive membership and retained personal scope ID |
| `workspace_invitations` | Normalized email, admin/member role, hashed random token, expiry and acceptance/revocation state |
| Workspace `idempotency_keys` | Existing creation/membership receipts, captured affected IDs and graph acknowledgement retry facts |

Users have mandatory unique Clerk subjects and no type/owner fields. Leta resources are independent of users and human memberships. No user lifecycle/status or initial-workspace mapping is stored.

Exactly one active owner is enforced by creation/member transactions and the partial unique index. Membership is workspace-wide; scope grants can differ independently. Shared usersets derive from active roles. Creation/add/join commands publish personal manager defaults; role-only changes preserve direct personal grants. Removal revokes the default and retains the scope. Rejoin reuses its mapping. Rebuild only recreates SQL-derived facts and preserves direct scope grants.

Invitations store SHA-256 token hashes, return raw links once with no-store, and require trusted verified email on acceptance. Acceptance/member cap and receipt commit atomically. Token replay cannot restore a removed member or overwrite a role. Direct user-ID admission accepts humans only; Leta is never a workspace member.

## Leta persistence

The [Leta migration](../apps/leta/migrations/0001_agent_domain.sql) owns eight product tables: agents, boxes, box_edges, messages, runs, activity_log, hitl_requests and schedules. LangGraph owns its saver tables in the same service database. There are no cross-service SQL foreign keys or duplicated scope-grant tables.

Root Leta rows bind workspace, creator and home scope; Leti rows bind the root and a box. Incoming messages are the inbox, while activity_log is the independently queryable public transcript. Inbox/history sequences allocate and commit with their rows under an agent lock. A detail-read timestamp is separate from checkpoint input progress. Whole-box graphs insert atomically with deferred representative/child constraints. Archive retains rows and history.

`python -m leta.migrate` explicitly runs Goose and saver setup. API readiness checks both applied versions and never migrates. The [Leta implementation record](../plans/261108-0001-leta-agent-engine/plan.md) links runtime, access, scheduler and streaming verification.

## LetFS tables

| Table | Responsibility |
|---|---|
| `filesystems` | Limit/used bytes, node count and active/deleting/deleted state |
| `scopes` | Filesystem ID, own root ID, lifecycle and immutable `allow_blob_files` / `allow_indexing` options |
| `nodes` | Scope ID, same-scope parent, name, kind, size, revision and timestamps |
| `files` | File payload, MIME/semantic metadata, desired generation and processing publication state |
| `trash_entries` | Scoped detached root, original parent/name, actor/time and trashed/purging state |
| `uploads` | Scope/initiator, captured input, transfer evidence, terminal result, deadline and processor source/generation |
| `idempotency_keys` | Scoped request hash and completed result; no copy traversal/progress state |
| `object_deletions` | Immutable key, filesystem attribution, eligibility/state and unresolved write evidence |
| `index_deletions` | Source file/generation cleanup identity surviving node deletion |

Scope roots and parents use composite scope/node FKs. Sibling names are case-sensitive unique within scope/parent. Files hold exactly one payload: bounded UTF-8 `text_content`, binary `inline_bytes`, or an independent immutable `object_key`. TEXT stores exact bytes without newline/BOM normalization, plus checked LF count and SHA-256. Text candidates must fit the existing inline/file limits and contain no NUL; invalid UTF-8 and known binary formats keep binary storage in blob-enabled scopes. Object-backed text stays object-backed. Owner downloads, archives, copy and processing inventories encode TEXT as exact UTF-8 bytes. Directories have no file metadata row. No cross-service SQL FK or SQL ACL mirror exists.

The sibling-name index resolves paths; `(scope_id,parent_id,id)` supports child keyset pages and copy traversal. Processing uploads are indexed by source/generation. Pending processing/upload receipts have partial expression indexes on their result identities, so completion does not scan unrelated receipts. Scope-wide upload cleanup and user-upload admission counts have separate indexes; filesystem object cleanup and trash original-parent cleanup are indexed. Executable definitions remain in the LetFS migration.

`files_text_content_trgm` is a partial pg_trgm GIN index on small `storage_kind='text'` payloads, including published artifact TEXT. It updates with the owning content transaction; no indexing worker or semantic `allow_indexing` switch controls this physical access index. Native literal candidates join current live scope/subtree nodes, so trash, detachment and movement change visibility immediately. Object/binary originals are not indexed; their permitted metadata representation remains a conservative candidate. Index space and write overhead depend strongly on content entropy; see the reproducible experiment in [operations](operations.md#native-text-search-experiment).

## Paths and mutations

Every request names filesystem and scope. `/` is its root; relative paths/cwd and root aliases `@<UUID>` resolve only within live ancestry. Above-root traversal and foreign/detached nodes fail. Ordinary names reject slash, NUL, empty, `.` and `..`; byte/depth limits remain. ID/cwd/alias access cannot bypass scope or read-only artifact ancestry.

Native Locators optionally carry `root_id` to narrow traversal to a live ordinary directory. Absolute paths start there; IDs, cwd and UUID aliases remain inside it, and `..` cannot leave then re-enter. Generated directories cannot become mount roots. The bound root cannot be renamed, moved or trashed. Copy carries separate source/destination roots through every traversal/publication step; same-scope moves/restores inherit an omitted destination root. Restore also validates the original parent under its source boundary. This boundary narrows current scope permission and never grants it.

File nodes retain payloads and may contain generated children. Strict descendants are read-only. Existing-node path mutations compare expected identity as well as revision so a replacement with the same revision cannot receive an old command. Mutation resolution/revalidation occurs under the owning lock. Copy/move/restore can cross scopes within one filesystem with separate source/destination actions. Move/restore change the entire subtree atomically, preserving IDs and payloads; destination content restrictions apply to every file, including artifacts. Generation changes fence old processing and queue obsolete index cleanup; completed semantic metadata is reused for destination indexing.

## Quota and cleanup

Native small-TEXT mutations derive final bytes inside the existing owning transaction. Exact UTF-8 content, size/hash/LF metrics, quota delta, revision and processing invalidation commit together. Unchanged bytes do not change revision/generation after all observations pass. New native text targets use the existing creation receipts, not a new mutation ledger. An explicit TEXT source enters text processing regardless of filename; CSV retains its format. Atomic directory-chain creation and empty-directory trash share the same filesystem/scope locks as ordinary child writes.

Filesystem-row locking serializes lifecycle, byte quota and node count. Node/file publication and checked usage deltas commit together. Roots, trash and detached artifacts count; trash/restore/move have no byte delta. Positive growth requires capacity, while shrinking still enforces lifecycle/counter bounds. Deletion debits actual removed rows once. Network I/O occurs outside SQL locks. Upload/trash attribution includes actor_kind=user|leta with actor_id. Upload sessions, caller-scoped receipts and search cursors distinguish equal UUIDs across actor kinds; processor transfers instead bind their stored source/generation/stage.

Upload creation and direct copy validate outstanding-work/cleanup bounds using existing rows under the filesystem lock. No reservation ledger exists. New objects use `objects/<filesystem-id>/<identity>`. Upload finalize verifies provider evidence outside locks, then revalidates initiator, scope, revision, destination and quota while atomically saving the terminal result. Multipart completion reconciles lost acknowledgement with HEAD. Processor uploads save transfer evidence before generation-fenced artifact publication.

Replacement queues old bytes and detaches artifacts transactionally; detached bytes stay charged until actual removal. Abort/expiry fences finalize and preserves candidate evidence through transfer grace. GC only claims unreferenced keys, outside-network I/O follows the SQL claim, and copy candidates cannot publish after cleanup starts. Ambiguous writes/open backend calls retain compact periodic-cleanup tombstones rather than assuming a timeout stopped S3. Physical GC never debits usage again.

Deleted scopes can be removed once their transfers are terminal and no longer require them. Filesystem identity remains while scopes or object cleanup reference it. Safe completed cleanup facts can be removed; unresolved late-write evidence remains. No automatic counter repair or age-based trash purge is introduced.

Each scope owns immutable `allow_blob_files` and `allow_indexing` booleans, both default true. A scope with blob files disabled accepts UTF-8 inline text with tab/CR/LF but no other controls and refuses object uploads/copies, including processor output. Restricted sources enter text processing regardless of filename; MIME is metadata. Indexing is independent: disabling it preserves parse/enrichment but skips embeddings/index publication and index backfill; enriched is the completed state for those files. Existing inline/file bounds still apply. Creation retries must match both options.

## Trash, copy and archives

Trash detaches one root without deleting descendants or releasing quota. Restore claims the current entry, validates live destination/name and reattaches atomically. Purge claims purging and loops bounded leaf batches synchronously in the request; interrupted removal requires a caller retry. Separately trashed children survive original-parent purge through the nullable original-parent reference. Filesystem deletion fences and deletes all scopes, including detached/trash/artifact roots. See [workflow trees](workflows.md).

Copy traverses locally in the request, captures source/high-water/revision guards and commits nodes independently. Each blob uses a new independent S3 key with publication/cleanup evidence. Failure keeps partial output and returns an error; there is no automatic retry, progress/checkpoint state or job. A completed copy saves its Node response under the existing scoped request key with a 24-hour TTL. Copied derived children remain read-only, and completing a logical file records processing intent once.

ZIP is request-owned streaming with bounded preflight, live identity/revision checks and safe relative paths. It has no database entity, workflow, stored archive or quota charge. Disconnect releases storage reads/concurrency; an in-flight mutation can abort the stream.

## Semantic metadata and search index

Semantic metadata and MIME belong to `files`. Direct sources are classified from their own bytes. Parsed files preserve their original bytes and attach generated children directly below the original file, without an intermediate directory. Enrichment classifies actual leaf files, then each directory README from its own text and already enriched child files/READMEs, deepest first. Directories never own semantic metadata. Folder slugs use their README result. One transaction publishes metadata, final names, Markdown links/replacements, revisions, quota deltas and publication readiness; the root README result is copied to the original file.

`files.desired_generation` increases for content replacement and manual reprocessing; same-scope rename/move preserves it. Cross-scope move/restore increases the generation and rebuilds scope-specific indexing while preserving completed semantic metadata. Source writes and generation changes commit together. Every output operation checks this generation and the current source lifecycle. Temporal owns Activity retries; there is no accepted-attempt counter or UUID protocol. Publication selects completed upload IDs returned by the worker and discards unused outputs. Repeated publication returns the committed result without rechecking a manifest hash.

`publication_status` is the single pipeline state: `not_required`, `pending` (parse needed), `parsed` (enrichment needed), `enriched` (index needed), `ready`, `failed` or `index_failed`. The last state preserves the distinction between failed semantic publication and failed indexing of already enriched content. Embedding configuration belongs to the running system, not file or cleanup rows.

Qdrant is rebuildable derived state. Immutable point IDs derive from source file, generation, full vector space, evidence file, point kind and ordinal. Payload contains `filesystem_id`, `scope_id`, `source_id`, `file_id`, numeric `generation`, `embedding_model`, `vector_dimension` and `text`; the collection scopes the remaining space identity. PostgreSQL validates current metadata, authorization scope, ancestry, generation and pipeline readiness before reranking. Filename search remains independent of AI readiness.

Semantic hydration walks candidate ancestors to the selected search root and separately verifies evidence ancestry; it excludes detached nodes and generated originals without traversing unrelated scope nodes. Filename search still traverses the selected live subtree for substring matches, carrying node metadata in that traversal rather than fetching every node a second time. No materialized path or additional search store is maintained.

Source supersession/deletion enqueues file/generation cleanup in `index_deletions` in the same transaction as invalidation/removal. Cleanup uses current system embedding configuration, waits for the source producer, rechecks current serving identity under lifecycle locks and retains compact tombstones for uncertain late writes. Explicit index rebuild reuses the source workflow ID and preserves parse/enrichment. Concurrent old/new embedding configurations and automatic configuration migration are outside the current scope. A restored ready source may reuse its current index; failed processing does not restart merely because it was restored.

## Leta product and checkpoint data

Leta owns eight product tables: agents, boxes, box_edges, messages, runs, activity_log, hitl_requests and schedules. The additional idempotency_keys table provides ordinary expiring HTTP request keys. [The domain migration](../apps/leta/migrations/0001_agent_domain.sql) owns exact constraints; [API key migration](../apps/leta/migrations/0002_api_idempotency.sql) owns request retention. No account/member row represents an agent, and no cross-database FK is used.

Root agent rows carry workspace, creator and home-scope references; Leti rows point to their root and immutable box. Undirected edges are sorted endpoint pairs and authorize messaging only. Messages store both inbox inputs and explicit recipient-facing sends, with a per-recipient inbox sequence. Runs retain the consumed cursor and checkpoint continuation. The typed activity log is the queryable public transcript, independent of private provider reasoning.

LangGraph's async PostgreSQL saver owns checkpoint tables alongside product tables in the dedicated Leta database. An invocation reuses its lifetime agent thread; checkpointed state contains working messages, inbox metadata/cursor and the exact current compaction summary. The public compaction card retains that summary and covered history range. Full transcript queries do not load the whole checkpoint history. Temporal histories carry coordination references/control state and rotate with Continue-As-New; Redis retains bounded disposable per-root replay events and Mirage cache entries.

Human requests store ask forms or personal-scope resource requests, their designated human recipient, decision and actual grant outcome. Direct scope permissions remain canonical in SpiceDB, never reconstructed from accepted HITL history. Schedules store canonical normalized rules and lifecycle; native Temporal Schedules are the execution projection.
