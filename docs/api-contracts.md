# API contracts

[Public OpenAPI](../packages/contracts/public/openapi.yaml) owns HTTP shapes. [Protobuf](../packages/contracts/proto/openlet_api/) owns private native RPC; generated Go/Python bindings and the [transport reference](../packages/contracts/generated/letfs.openapi.json) are reproduced by contract generation.

## Protocol and identity

HTTP uses `/v1`, snake_case JSON, UUID strings, RFC3339 timestamps, decimal-string counters/revisions, keyset pages `{items,next_cursor}` and RFC9457 errors. Lists/stat omit bytes and content context. Envoy forwards authenticated `x-openlet-user-id` from the `openlet_user_id` claim; ordinary endpoints require that user. Only onboarding permits subject-only verified sessions.

Node overwrite/rename/move/trash require `If-Match` (428 missing, 412 stale). Workspace metadata/member/deletion has no ETag. Path mutations also validate expected node/parent identity against replacement races. Restore/purge address current trash-entry identity without client retry keys.

Admission validates permissions/input before workflows. SQL/graph commands return success only after acknowledged publication. Workspace creation returns 200 after storage/mapping/graph creation; deletion waits for cleanup and returns 204. Losing HTTP does not cancel accepted durable work. Creation keys replay the immutable result and reject changed input. No workspace-count limit applies; `MAX_MEMBERS` remains atomic policy.

## Account and Workspace

| Route | Action / behavior |
|---|---|
| GET/PUT `/me/onboarding` | Verified subject; user_id, pending/active/failed, refresh_session; PUT returns 202 pending or 200 complete |
| GET/PATCH `/me` | Verified current human profile; local user existence, no graph self/owner grant |
| GET/POST `/workspaces` | Caller memberships / named creation with Idempotency-Key |
| GET/PATCH `/workspaces/{ws}` | `workspace:read/update`; name-only edit |
| DELETE `/workspaces/{ws}` | `workspace:delete`; owner-only deletion |
| GET/POST `/workspaces/{ws}/members` | Read enriched active members / manage_members direct user_id + admin/member admission |
| PATCH/DELETE `/workspaces/{ws}/members/{user}` | manage_members role/remove; explicit self-leave allowed; owner cannot be changed/removed |
| PUT/DELETE `/workspaces/{ws}/scopes/{scope}/access/{user}` | `scope:manage_access`; JSON role manager/editor/viewer grants/revokes a direct relation |
| GET/POST/DELETE `/workspaces/{ws}/invitations[/{invitation}]` | manage_members, verified-email admin/member invitations, token once with no-store |
| POST `/memberships` | Accept token with trusted verified email; replay cannot restore removed membership |

The identity service stores humans only in users. Profiles have no type or owner_id. Managed account creation/read/update routes are removed; Leta resources are implemented separately in the active agent-engine plan. Completed onboarding does not recreate a deleted initial workspace, even after history retention. Discover Workspace `filesystem_id`, `shared_scope_id` and membership `personal_scope_id`; resolve `/` in the selected scope for its root.

Workspace's private [resource RPCs](../packages/contracts/rpc-surface.md#workspace-resource-operations) authenticate the Leta service independently of its delegated user/root actor. They support runtime discovery, canonical home provisioning and resource-owner personal-scope grants. A timed-out grant wait can leave an accepted Temporal Update running; retry the same request key and payload. Responses report current rights, including revoked rights after cleanup.

## Leta product APIs

Leta is a Workspace resource. `/v1/leta-models` lists the supported `model_id` and
`reasoning_effort` catalog. `/v1/letas` creates/lists the caller's resources;
`/v1/letas/{id}` exposes profile/configuration, pause/resume, archive, agent roster,
immutable box canvas, owner chat, inbox inspection, typed history, runs and schedules.
Every resource read/manage checks creator identity and current Workspace access.
Archived history remains readable through retained Leta authorization tuples.
Leti model overrides can be set/reset, while profile, graph and names are immutable.

Owner message POST uses its client-stable body `id` as the domain message and
Temporal Update identity. `201` means PostgreSQL inbox admission completed; a
worker outage/timeout returns `202` with the same resource ID and lookup/retry
instructions. GET message lookup may still return `404` before admission. Reusing
a message UUID with changed content conflicts, including when Temporal returns an
already-completed Update. Only actual owner/root messages appear in chat; typed
inbox, tool, final-note and compaction entries appear in activity history. Hidden
reasoning is absent. Treat all agent-generated renderable text as untrusted.

Lifecycle, box and schedule commands require a nonzero UUID `Idempotency-Key`.
Leta uses its own ordinary `idempotency_keys` table for method/path/body hash and
allocated resource ID, following Workspace's completion/expiry mechanics. Pending
keys retain the resource identity; acknowledged completion starts a 24-hour expiry
once. A completed retry returns current resource state without reapplying a stale
command, independently of Temporal Continue-As-New. No operation resource or
cross-service command journal is exposed. Unacknowledged cross-service work can
still be pending; there is no global exactly-once guarantee.

Creator request management is `/v1/letas/{id}/human-requests`. Global
`/v1/human-requests[/{id}]` exposes only requests addressed to the current human,
with current Workspace membership, and no unrelated Leta history. POST response
accepts/denies personal-scope access or answers the multiple-question form.
Approval is addressed to the personal-scope owner and grants root Leta, including
requests made by Leti; acceptance does not execute a tool. Choice answers allow
empty selection plus note; text questions have only text. Cancellation does not
revoke an accepted grant. Workspace continues to own scope membership/revocation.

Schedules share one product definition for absolute/relative `at`, anchored
`interval`, or timezone/calendar field rules. PostgreSQL serves definitions; native
Temporal Schedules execute them. Calendar occurrences return the complete sorted
`(start,end]` selection, without pagination: at most 366 days, 32 definitions,
32 native matching-time RPCs and 1000 results. Oversized queries fail explicitly;
forecast failure does not hide persisted definitions.

GET `/v1/letas/{id}/events` provides one authorized SSE connection for root and
child AG-UI events. The envelope includes `leta_id`, `agent_id`, nullable `run_id`
and `event`. A fresh connection sends bounded typed history/status plus available
Redis replay. `Last-Event-ID` resumes strictly after the saved cursor and
`state_refresh` preserves the client's partial text/tool arguments. Missing or
trimmed replay emits `resync_required`, then reloads committed state; provisional
prefixes outside the retained log cannot be recovered. Public CUSTOM events carry
typed activity entries or resource references; hidden reasoning is excluded.
Compatible adjacent text/argument deltas merge after Redis at 25ms/16KiB, retaining
the last consumed cursor. This reduces SSE frames, not Redis writes or Temporal
replay. Each root log has a 24-hour touch TTL, 8MiB payload and 20,000-event cap.
Current access is rechecked during live connections; slow/disconnected clients
release their readers and reconnect normally.

## Filesystem and scope routes

GET `/filesystems/{filesystem}` requires `filesystem:read` and returns lifecycle and quota/counters. Scope creation returns its immutable blob/indexing options through private storage administration. Filesystem rights confer no scope content access.

All suffixes below are under `/filesystems/{filesystem}/scopes/{scope}`. LetFS knows actor/resource/action only. Locators select ID or path/cwd within the selected live root. Copy, move and restore accept an optional `destination_scope_id` in the same filesystem; otherwise they use the current scope. A cross-scope move/restore requires an explicit destination parent.

| Suffix | Action / behavior |
|---|---|
| GET `/nodes`, `/nodes:resolve`, `/nodes/{node}` | read_metadata; bounded live metadata/identity resolution |
| POST `/nodes`, PATCH `/nodes/{node}`, PUT `/nodes/{node}/content` | write; ordinary create/edit/move with identity/revision guards |
| POST `/nodes/{node}:copy` | Source read_content + destination write, source If-Match and Idempotency-Key; synchronous 201 Node with destination Location |
| GET `/nodes/{node}/content`, `/nodes/{node}/archive` | read_content; exact bytes/direct signed GET or request-owned ZIP |
| GET `/nodes/{node}/processing` | read_metadata; status only |
| POST `/nodes/{node}/processing-runs` | write; ordinary reprocessing admission |
| GET/POST `/search` | read_content before excerpts, embedding or rerank calls |
| POST `/uploads`, GET/DELETE `/uploads/{upload}`, GET parts, PUT completion | write plus initiating actor/session constraints |
| DELETE `/nodes/{node}` | trash; 201 detached trash entry |
| GET `/trash-entries[/{entry}]` | read_metadata |
| POST `/trash-entries/{entry}:restore` | source restore; explicit destination requires write; optional destination_scope_id, parent_id and name; 200 Node |
| DELETE `/trash-entries/{entry}` | purge; synchronous batched removal; 204 when complete or missing |

Copy/purge use no workflow. Copy returns its completed Node; failure retains committed output and returns the request error. A completed same-key retry returns the saved Node without copying again; no job/progress response or automatic resume exists. `POST /nodes` only creates files/directories and rejects the old source_id copy shape. Move uses PATCH with optional destination_scope_id, parent_id and name; cross-scope move requires source write/trash and destination write, preserves all IDs/S3 keys and has no quota delta. Restore accepts an optional body with the same destination fields; an empty body restores the original location/name. Name collisions reject rather than overwrite.

`POST /filesystems/{filesystem}/files/batch-stat` accepts 1–100 `locators`, each with `scope_id` and the ordinary node_id or path/cwd locator fields. It checks every scope, preserves input order/duplicates, and returns no partial metadata on failure. The former scope-level batch-stat route is removed.

`allow_blob_files` and `allow_indexing` are immutable scope creation options, both defaulting true. Omitted gRPC creation options use those defaults; options apply to each scope in that creation batch. With `allow_blob_files=false`, a scope accepts UTF-8 inline text with tab/CR/LF, refuses object uploads and object-backed copies (including processor output), and routes restricted sources to text processing regardless of extension. Invalid restricted payloads return BLOB_FILES_DISABLED. `allow_indexing=false` preserves parsing/enrichment but skips embedding/index publication; completed files remain enriched, semantic search returns no results, and filename search remains available. Direct indexing calls return INDEXING_DISABLED. Existing byte limits apply; creation option mismatch returns SCOPE_CONFLICT.

Small supported UTF-8 text is stored as PostgreSQL TEXT within the existing inline/file limits. BOM, CRLF, trailing spaces and final fragments are preserved. Invalid UTF-8/NUL and known binary formats remain binary in blob-enabled scopes; object uploads remain object-backed. Existing owner download and processing inline-content responses carry exact UTF-8 bytes, without a new text-transfer variant.

Private `CreateNode.node_id` optionally selects a stable UUIDv7 for a file or directory. It uses the existing request-key receipt and rejects conflicting IDs/names; an expired receipt does not authorize adopting a same-name occupant. Public HTTP creation retains server-generated IDs.

Native Locator `root_id` restricts absolute/relative paths, cwd, IDs and UUID aliases to a live ordinary directory subtree; omission retains the scope root. A supplied root cannot be a generated artifact or be renamed/moved/trashed through that view. `CreateCopy` accepts independent `source_root_id`/`destination_root_id`; `RestoreTrash.root_id` restricts the original parent and its destination Locator can carry its own root. Current scope authorization still applies to each source/destination.

Native `Stat`, `ReadText`, `TextMetrics`, `ReadTree` and `ReadImage` use that same Locator. `Stat` resolves a path in one RPC; `content_check=true` requires current content permission before a cache hit. `ReadText` accepts whole, zero-based byte range, one-based lines, head or tail selections, returning bytes and the matching representation fingerprint from one PostgreSQL snapshot. Optional expected fingerprints reject changed content. LF count counts `\n`; CRLF and unterminated final lines remain exact. Maintained SHA-256 needs no TEXT payload read; other supported metrics are MD5, SHA-1, SHA-384 and SHA-512. An unknown algorithm returns `supported=false` after authorization.

Blob reads return bounded JSON metadata and the actual nested artifact tree, including usable source-relative paths. They expose neither blob bytes nor object keys/URLs. Source files retain FILE kind; `/report.pdf/report.md` and `/@<source-file-id>/report.md` address real readonly children. Fingerprints cover processing state and the current artifact tree. `ReadTree` traverses file-owned children, returns deterministic path/ID pages, and binds cursors to the typed subject, scope, mount root, traversal root and depth. Defaults are 10000 entries and a 4 MiB response ceiling; oversized representations fail explicitly.

Native unary `TextSearch` takes that root-restricted Locator, `mode=files|lines`, a literal UTF-8 string up to 4096 bytes, `ignore_case`, and optional `max_files`/`max_lines`/`max_bytes`. FILES returns sorted relative paths and representation stats; indexed small TEXT is filtered by literal containment, while blob metadata may conservatively remain a candidate. LINES returns original candidate-line bytes for one file, preserving CRLF, long lines and final fragments. Ignore-case/multiline narrowing may return every original file/line; Mirage owns final matching. No raw blob body, regex engine, ranking or semantic cutoff is involved. Results use one read snapshot and recheck current content access before release. Exceeding any result/serialized-response bound returns `complete=false` with no items/content/stat; permission, dependency and cancellation failures remain errors. Default output ceiling is 4 MiB, below the existing RPC limit. Literal access remains available with `allow_indexing=false`.

Native unary `WriteText`, `AppendText`, `PatchText` and `TruncateText` operate only on small TEXT. Their target is either an existing Locator with positive observed revision and optional representation fingerprint, or explicit parent/name absence with a creation key and optional stable UUIDv7. Path targets require the observed node ID; path parents require the observed parent ID. Creation explicitly stores TEXT, with supplied MIME as metadata; text processing follows storage kind rather than a misleading filename. Existing blobs and generated children cannot be edited through these methods.

Append and literal/byte patch execute inside the same backend transaction as quota, revision and processing invalidation. Byte patch overwrites rather than inserts; literal patch requires nonempty old text and `replace_all` for multiple matches. Truncate only shrinks or retains size; missing targets may be created at zero unless `no_create`. Byte patch may create at offset zero. Gaps, truncate growth, NUL, invalid UTF-8 and results above `min(INLINE_LIMIT_BYTES, MAX_FILE_BYTES)` fail without partial changes. Responses return committed stat/fingerprint plus before revision/fingerprint; a no-op still checks every precondition.

Native `CreateDirectories` accepts an observed parent and relative name components. `parents=true` atomically creates missing components and accepts existing ordinary directories; false requires one absent child. `TrashNode.empty_directory=true` atomically requires an ordinary empty directory before trashing it. All agent removals retain quota and use ordinary restorable trash. Copy/move retain no-overwrite behavior; failed directory copy retains already committed output.

`ReadImage` authorizes a backend-only original read, checks dimensions before decode, and returns a PNG preview with dimensions and source/output fingerprints. PNG/JPEG/GIF (first frame) are supported, with at most 40 million input pixels, a 2048-pixel output long edge, 4 MiB encoded output and two concurrent preview slots. The backend rechecks current permission/liveness/fingerprint before releasing the preview. No raw-image fallback or new public HTTP route is added. The native `leta` credential delegates `x-openlet-leta-id` on its explicit data-method allowlist; raw download/archive/upload, owner blob replacement, ingest, administration and purge remain denied.

Normal APIs return 404 for detached content even by ID. No trash preview now. Files retain their original payload and may contain generated read-only children, such as `/report.pdf/1-intro.md`. Listing/traversal/cwd accepts files and trailing container syntax; content reads reject a trailing `/` or `/.`. Root-relative `@<canonical UUID>` aliases remain live-node/scope scoped; nested matching names are ordinary names. Every artifact mutation/write destination is rejected with 403 `ARTIFACT_READ_ONLY`, including raw-ID access. Copying an artifact into an ordinary directory produces writable content.

Upload requests bind initiating actor kind/UUID/scope and recheck the operation action each phase. Upload initialization and copy reject content bodies and batch locators. Inline node create and content replacement enforce decoded-byte and maximum-file limits; larger payloads use object uploads. Download validates one range and rejects invalid/multiple ranges; attachment headers prevent treating uploaded HTML as application content.

Ingest uploads use the same `open`, `completing`, `finalized`, `aborted` transfer states. Their completion result is an immutable `{id,status:"finalized",size_bytes}` receipt; artifact publication and search readiness are separate. Inline transfer records bytes while the session remains open. Publication attaches the result node without changing that receipt; repeat completion returns the same receipt after publication, and finalized sessions cannot be aborted or issue more signed capabilities. Superseded output cleanup retains terminal transfer evidence.

`GET /nodes/{node}/processing` returns `file_id`, `desired_generation` as a decimal string, `publication_status=not_required|pending|parsed|enriched|ready|failed|index_failed` and nullable `error_code`. `enriched` means semantic publication completed; indexing is pending only when the scope allows it; `ready` means indexing completed. `index_failed` retains the distinction from a parse/enrichment failure. Temporal owns execution diagnostics.

`POST /nodes/{node}/processing-runs` requires `scope:write`, an empty JSON object and one UUID Idempotency-Key. It returns 202 with the saved `{file_id,generation,workflow_id}` admission. A same-key retry replays that admission; changed file/content identity conflicts. Active receipts pin; completion, failure or supersession starts the non-extending 24-hour retention. A new key requests a new generation. Original bytes remain intact; generated files are children of the original file, such as `/report.pdf/1-intro.md`.

`GET /search?q=...` finds live original filenames/titles directly in PostgreSQL. Optional parent uses `node_id` or `path`/`cwd_id`; filters use `type`, `media_type`, and created/updated after/before timestamps. Sort is `name|created_at|updated_at`, direction `asc|desc`, limit 1–100. Keyset cursors bind the filesystem, actor/scope, query, filters and sort.

`POST /search` accepts `{query,filters,limit}` with default limit 20 and range 1–50. It returns `{items,degraded}` with no cursor or continuation. One Qdrant request retrieves at most 80 candidates from dense/native BM25 prefetch fused with RRF. DB live/current/ready checks and filters precede reranking of at most 64 evidence documents, with at most three per original. Results group evidence into original files and apply the output limit after reranking. Each result has current metadata and `matched:{file_id,breadcrumb,snippet}`. Filtering, duplicate evidence or concurrent changes can produce fewer results than the limit. Reranker failure returns hybrid order with `degraded=true` and `degraded_reason=RERANK_UNAVAILABLE`; embedding or Qdrant failure returns 503 `DEPENDENCY_UNAVAILABLE`. Filename search retains `{items,next_cursor,degraded}` keyset pages.

Client flows: show filename plus AI title/subtitle when available; track publication and index readiness; keep filename search usable while AI work is pending; open the matched breadcrumb from a semantic card; show a rerank degradation banner; offer manual reprocessing after a reported failure. Lists omit embedding context and file bodies. README may be rendered as an overview through the ordinary content route. Artifact/chunk evidence is grouped into its original file card. Trash, replacement and authorization changes remove stale results through current DB validation.

Conversion failures distinguish `RESOURCE_LIMIT` (including memory/image/output
limits), `DOCUMENT_INVALID` (invalid input or rejected conversion) and
`PROCESSING_FAILED` (unexpected converter failure). Worker logs retain the error
class, cause class and peak resident memory when available; dependency stderr and
document contents are not copied into those diagnostics.

Copy validates selected revisions and commits each destination item independently, without source-tree snapshot semantics; see [data model](data-model.md). Reject cross-filesystem copy/move even in one workspace. An exposed filesystem ID is metadata, not authorization to select arbitrary scope.

## Private communication

Workspace calls Account `GetUserSummaries` and `GetVerifiedEmails` using its existing service credential. Summary IDs must exactly match the bounded unique request; profiles contain only id/display_name/avatar_url. Leta resources have no user row or Clerk email identity. Delegated actor metadata is rejected for these service-only calls.

Account starts Workspace's CreateWorkspace child directly. Workspace schedules LetFS creation activities and DeleteFilesystem children on their owner queue. Workspace exposes its native Leta resource/scope methods; provisioning still uses Temporal rather than a polling API. Private LetFS gRPC supports storage administration, delegated filesystem operations and generation-scoped ingest. LetFS enforces scope actions for delegated actors. See [RPC ledger](../packages/contracts/rpc-surface.md) and [workflow trees](workflows.md).

Workspace can call Leta's private `GetLetaBinding` to validate the canonical root resource, workspace, creator, home scope and lifecycle. The method rejects delegated actors and child IDs, and returns no prompt or conversation. LetFS's private `ListScopes` returns active storage candidates to actor-free Workspace calls only.

`GET /v1/workspaces/{ws}/scopes` returns the current human's permitted scope/root IDs, effective metadata/content/write rights and known scope/owner labels. Optional `leta_id` requires current `leta.read` and exact workspace binding; workspace admin status alone grants no inspection access. The shared discovery implementation checks current SpiceDB permissions before exposing candidates or loading personal-scope owner profiles. Pages scan at most100 candidates; a filtered-empty page can have `next_cursor`. Cursors bind workspace, subject kind/ID and inspector. There is no arbitrary `user_id` inspection parameter. These discovery results never authorize a later content call.

### Direct storage transport

Agent filesystem tools use `apps/leta/src/leta/filesystem/tools.py` through one Mirage session. `read_file` selects bounded text lines, returns blob metadata/artifact trees, or emits an authorized image preview with provenance. It never exposes original blob bytes or signed URLs. Write/edit remain small-text-only; shell removal means trash. Generated artifacts retain ordinary source-relative and `/@<source-file-id>/...` paths and remain read only. Native read/mutation/search hooks use unary RPCs; Mirage owns command parsing and matching. These wrappers are implemented; their LLM-tool registration belongs to the agent runtime phase.

Prepare requires a UUID `Idempotency-Key`, canonical decimal `size_bytes` and `media_type`. Public uploads always use object storage; small inline content uses nodes/content directly. Single PUT requires base64 Content-MD5, enforced by the selected provider. Native multipart signs each part's declared length and accepts ordered opaque part ETags at completion; it does not derive a whole-object MD5 from those ETags. Unsupported whole-object multipart MD5 is rejected. The provider contract check verifies signed-header, checksum, conditional-write and size enforcement against the configured provider before it is considered supported.

Admission stores a caller/scope-scoped `create-upload` receipt in `idempotency_keys` in the same transaction as the session. It remains pinned until finalization, abort or expiration; completion starts a 24-hour TTL once, and retries do not extend it. Replay returns the same session and never renews capabilities after completion starts. Session/result identity remains separate from request deduplication.

Transfer descriptors carry signed required headers, automatic Content-Length and expiry. Object bytes bypass Workspace/Letfs. Completion freezes multipart receipts before remote calls, reconciles a missing completion acknowledgment with HEAD of the unique candidate key, then atomically rechecks quota/destination/revision/lifecycle and saves the terminal result. ETags are opaque validators. No backend-readback SHA-256 receipt is promised. Publication rejection retains durable candidate cleanup, including unresolved late-write evidence. Multi-file callers use independent sessions with bounded concurrency; one failure does not undo siblings.

Ingest descriptors use the internal S3 endpoint; browser descriptors use the configured public signing endpoint. Signed hostnames are never rewritten after signing.

Content responses and redirects use no-store. GET renewal reauthorizes and accepts
`revision=N`; mismatch is 412. Content `If-Match` is rejected because logical
revision is distinct from S3 ETag. Issued URL expiry is the revocation boundary.
Inline bytes use application/octet-stream/attachment; text editing still validates
strings. Private object URLs preserve safe attachment names and Range semantics.

### Directory ZIP streaming

GET `/v1/filesystems/{filesystem}/scopes/{scope}/nodes/{node}/archive` reauthorizes `scope:read_content` and streams a directory as ZIP64, using paths relative to that directory and preserving empty descendants. Traversal stops at file payloads; generated artifact directories can be downloaded by their own directory IDs. Unsafe/case-ambiguous extraction paths and configured metadata limits fail before headers. Selected identity/path/revision or byte failures during delivery abort the body. No snapshot is promised; retry restarts the request.

Responses use `application/zip`, safe attachment disposition and `no-store`. There is no export status resource, request key, temporary object or logical quota charge. The configured LetFS runtime is at most 1800 seconds; the direct archive-only gateway route is 1815 seconds with a 120-second idle bound. Other routes retain their existing deadlines.

### Trash resources

DELETE nodes/{node} requires `scope:trash` and If-Match, detaches the subtree and returns 201 with its trash-entry Location. GET trash-entries and GET trash-entries/{entry} require `scope:read_metadata`. Entries expose id, node_id, nullable original parent_id, name, actor_kind, actor_id, status and created_at; the parent may already have been purged. POST trash-entries/{entry}:restore requires source `scope:restore`; selecting a destination additionally requires its `scope:write`. It defaults to the original live parent/name and rejects name conflicts or purging entries. DELETE trash-entries/{entry} requires `scope:purge`, fences restore and removes the tree in request-owned batches, returning 204 after removal. Interrupted purge is completed by retrying DELETE. No request key or deletion monitor table is required.

Scope grant/revoke uses `/v1/workspaces/{ws}/scopes/{scope}/access/{user}` with `role` and optional `grantee_kind` (`user` by default, or `leta`). The path UUID identifies that selected subject kind. Leta targets must be active roots of the same workspace and support viewer/editor only. The caller still needs scope manage_access; resource approval does not give the Leta creator access to another human’s personal data.
