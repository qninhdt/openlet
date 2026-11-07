# API contracts

[Public OpenAPI](../packages/contracts/public/openapi.yaml) owns HTTP shapes. [Protobuf](../packages/contracts/proto/openlet_api/) owns private native RPC; generated Go/Python bindings and the [transport reference](../packages/contracts/generated/letfs.openapi.json) are reproduced by contract generation.

## Protocol and identity

HTTP uses `/v1`, snake_case JSON, UUID strings, RFC3339 timestamps, decimal-string counters/revisions, keyset pages `{items,next_cursor}` and RFC9457 errors. Lists/stat omit bytes and content context. Envoy forwards authenticated `x-openlet-account-id` from the `openlet_account_id` claim; ordinary endpoints require that account. Only onboarding permits subject-only verified sessions.

Node overwrite/rename/move/trash require `If-Match` (428 missing, 412 stale). Workspace metadata/member/deletion has no ETag. Path mutations also validate expected node/parent identity against replacement races. Restore/purge address current trash-entry identity without client retry keys.

Admission validates permissions/input before workflows. SQL/graph commands return success only after acknowledged publication. Workspace creation returns 200 after storage/mapping/graph creation; deletion waits for cleanup and returns 204. Losing HTTP does not cancel accepted durable work. Creation keys replay the immutable result and reject changed input. No workspace-count limit applies; `MAX_MEMBERS` remains atomic policy.

## Account and Workspace

| Route | Action / behavior |
|---|---|
| GET/PUT `/me/onboarding` | Verified subject; account_id, pending/active/failed, refresh_session; PUT returns 202 pending or 200 complete |
| GET/PATCH `/me` | Account self read/update profile |
| POST `/accounts` | Create managed agent account; server fixes owner to actor and type to agent |
| GET/PATCH `/accounts/{account}` | `account:read/update`; self or immutable owner; profile fields only |
| GET/POST `/workspaces` | Caller memberships / named creation with Idempotency-Key |
| GET/PATCH `/workspaces/{ws}` | `workspace:read/update`; name-only edit |
| DELETE `/workspaces/{ws}` | `workspace:delete`; owner-only deletion |
| GET/POST `/workspaces/{ws}/members` | Read enriched active members / manage_members direct account_id + admin/member admission |
| PATCH/DELETE `/workspaces/{ws}/members/{account}` | manage_members role/remove; explicit self-leave allowed; owner cannot be changed/removed |
| PUT/DELETE `/workspaces/{ws}/scopes/{scope}/access/{account}` | `scope:manage_access`; JSON role manager/editor/viewer grants/revokes a direct relation |
| GET/POST/DELETE `/workspaces/{ws}/invitations[/{invitation}]` | manage_members, verified-email admin/member invitations, token once with no-store |
| POST `/memberships` | Accept token with trusted verified email; replay cannot restore removed membership |

Account owns type/owner; profile management provides no resource inheritance. Creating an agent account adds no credentials/runtime/storage. Completed onboarding does not recreate a deleted initial workspace, even after history retention. Discover Workspace `filesystem_id`, `shared_scope_id` and membership `personal_scope_id`; resolve `/` in the selected scope for its root.

## Filesystem and scope routes

GET `/filesystems/{filesystem}` requires `filesystem:read` and returns lifecycle and quota/counters. Scope creation returns its immutable blob/indexing options through private storage administration. Filesystem rights confer no scope content access.

All suffixes below are under `/filesystems/{filesystem}/scopes/{scope}`. LetFS knows actor/resource/action only. Locators select ID or path/cwd within the selected live root. Move stays in scope; copy may select destination_scope_id in the same filesystem.

| Suffix | Action / behavior |
|---|---|
| GET `/nodes`, `/nodes:resolve`, `/nodes/{node}`, POST `/files/batch-stat` | read_metadata; bounded live metadata/identity resolution |
| POST `/nodes`, PATCH `/nodes/{node}`, PUT `/nodes/{node}/content` | write; ordinary create/edit/move with identity/revision guards |
| POST `/nodes` with source_id | Source read_content + destination write, source If-Match; 202 `{id,destination_root_id}` without monitor Location |
| GET `/nodes/{node}/content`, `/nodes/{node}/archive` | read_content; exact bytes/direct signed GET or request-owned ZIP |
| GET `/nodes/{node}/processing` | read_metadata; status only |
| POST `/nodes/{node}/processing-runs` | write; ordinary reprocessing admission |
| GET/POST `/search` | read_content before excerpts, embedding or rerank calls |
| POST `/uploads`, GET/DELETE `/uploads/{upload}`, GET parts, PUT completion | write plus initiating actor/session constraints |
| DELETE `/nodes/{node}` | trash; 201 detached trash entry |
| GET `/trash-entries[/{entry}]` | read_metadata |
| POST `/trash-entries/{entry}:restore` | restore; current entry identity |
| DELETE `/trash-entries/{entry}` | purge; 202 while admitted, 204 missing |

Copy uses one activity with no automatic retry. Partial committed nodes remain readable and charged after failure. Same-key admission returns its stable identities; no progress endpoint or exact resume guarantee exists.

`allow_blob_files` and `allow_indexing` are immutable scope creation options, both defaulting true. Omitted gRPC creation options use those defaults; options apply to each scope in that creation batch. With `allow_blob_files=false`, a scope accepts UTF-8 inline text with tab/CR/LF, refuses object uploads and object-backed copies (including processor output), and routes restricted sources to text processing regardless of extension. Invalid restricted payloads return BLOB_FILES_DISABLED. `allow_indexing=false` preserves parsing/enrichment but skips embedding/index publication; completed files remain enriched, semantic search returns no results, and filename search remains available. Direct indexing calls return INDEXING_DISABLED. Existing byte limits apply; creation option mismatch returns SCOPE_CONFLICT.

Normal APIs return 404 for detached content even by ID. No trash preview now. Files retain their original payload and may contain generated read-only children, such as `/report.pdf/1-intro.md`. Listing/traversal/cwd accepts files and trailing container syntax; content reads reject a trailing `/` or `/.`. Root-relative `@<canonical UUID>` aliases remain live-node/scope scoped; nested matching names are ordinary names. Every artifact mutation/write destination is rejected with 403 `ARTIFACT_READ_ONLY`, including raw-ID access. Copying an artifact into an ordinary directory produces writable content.

Upload requests bind initiating actor/scope and recheck the operation action each phase. Upload initialization and copy reject content bodies and batch locators. Inline node create and content replacement enforce decoded-byte and maximum-file limits; larger payloads use object uploads. Download validates one range and rejects invalid/multiple ranges; attachment headers prevent treating uploaded HTML as application content.

Ingest uploads use the same `open`, `completing`, `finalized`, `aborted` transfer states. Their completion result is an immutable `{id,status:"finalized",size_bytes}` receipt; artifact publication and search readiness are separate. Inline transfer records bytes while the session remains open. Publication attaches the result node without changing that receipt; repeat completion returns the same receipt after publication, and finalized sessions cannot be aborted or issue more signed capabilities. Superseded output cleanup retains terminal transfer evidence.

`GET /nodes/{node}/processing` returns `file_id`, `desired_generation` as a decimal string, `publication_status=not_required|pending|parsed|enriched|ready|failed|index_failed` and nullable `error_code`. `enriched` means semantic publication completed; indexing is pending only when the scope allows it; `ready` means indexing completed. `index_failed` retains the distinction from a parse/enrichment failure. Temporal owns execution diagnostics.

`POST /nodes/{node}/processing-runs` requires `scope:write`, an empty JSON object and one UUID Idempotency-Key. It returns 202 with the saved `{file_id,generation,workflow_id}` admission. A same-key retry replays that admission; changed file/content identity conflicts. Active receipts pin; completion, failure or supersession starts the non-extending 24-hour retention. A new key requests a new generation. Original bytes remain intact; generated files are children of the original file, such as `/report.pdf/1-intro.md`.

`GET /search?q=...` finds live original filenames/titles directly in PostgreSQL. Optional parent uses `node_id` or `path`/`cwd_id`; filters use `type`, `media_type`, and created/updated after/before timestamps. Sort is `name|created_at|updated_at`, direction `asc|desc`, limit 1–100. Keyset cursors bind the filesystem, actor/scope, query, filters and sort.

`POST /search` accepts `{query,filters,limit,cursor}` with limit 1–50. Dense and native BM25 prefetch fuse with RRF; DB live/current/ready checks and filters precede bounded reranking. A result is one original file with current metadata and `matched:{file_id,breadcrumb,snippet}`. Both searches return `{items,next_cursor,degraded}`. Reranker failure returns hybrid order with `degraded=true` and `degraded_reason=RERANK_UNAVAILABLE`; embedding or Qdrant failure returns 503 `DEPENDENCY_UNAVAILABLE`. Semantic cursors carry bounded offsets/seen source IDs, bind query/filter/vector-space context, and may drift as ranking changes. Work is bounded to three candidate pages per request, 10,000 candidate positions and 256 unique sources per cursor chain. Clients should follow `next_cursor` even when filtering produces an empty page.

Client flows: show filename plus AI title/subtitle when available; track publication and index readiness; keep filename search usable while AI work is pending; open the matched breadcrumb from a semantic card; show a rerank degradation banner; offer manual reprocessing after a reported failure. Lists omit embedding context and file bodies. README may be rendered as an overview through the ordinary content route. Artifact/chunk evidence is grouped into its original file card. Trash, replacement and authorization changes remove stale results through current DB validation.

Conversion failures distinguish `RESOURCE_LIMIT` (including memory/image/output
limits), `DOCUMENT_INVALID` (invalid input or rejected conversion) and
`PROCESSING_FAILED` (unexpected converter failure). Worker logs retain the error
class, cause class and peak resident memory when available; dependency stderr and
document contents are not copied into those diagnostics.

Copy validates selected revisions and commits each destination item independently, not source-tree snapshot semantics; see [data model](data-model.md). Reject cross-filesystem copy/move even in one workspace. An exposed filesystem ID is metadata, not authorization to select arbitrary scope.

## Private communication

Workspace calls Account `GetAccountSummaries` and `GetVerifiedEmails` using its existing service credential. Summary IDs must exactly match the bounded unique request; profiles exclude private identity/owner fields. Agents have no verified Clerk emails. Delegated actor metadata is rejected for these service-only calls.

Account starts Workspace's CreateWorkspace child directly. Workspace schedules LetFS creation activities and DeleteFilesystem children on their owner queue. No Workspace RPC server/polling API remains. Private LetFS gRPC supports storage administration, delegated filesystem operations and generation-scoped ingest. Existing authentication/allowlists remain; LetFS still enforces scope actions for delegated actors. See [RPC ledger](../packages/contracts/rpc-surface.md) and [workflow trees](workflows.md).

### Direct storage transport

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

DELETE nodes/{node} requires `scope:trash` and If-Match, detaches the subtree and returns 201 with its trash-entry Location. GET trash-entries and GET trash-entries/{entry} require `scope:read_metadata`. Entries expose id, node_id, nullable original parent_id, name, actor_id, status and created_at; the parent may already have been purged. POST trash-entries/{entry}:restore requires `scope:restore` and the current entry identity, restores the original live parent/name and rejects name conflicts or purging entries. DELETE trash-entries/{entry} requires `scope:purge`, commits purging before dispatch, and returns 202 plus Location or 204 after removal. No request key or deletion monitor table is required.
