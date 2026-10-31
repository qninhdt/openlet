# API contracts

Status: implemented public/internal routes are documented in OpenAPI 3.1 at `contracts/public/openapi.yaml` and `contracts/internal/openapi.yaml`. Verification checks local references, schemas and captured real response DTOs against those contracts.

## Common protocol

Public prefix `/v1`; internal prefix `/internal/v1`. JSON snake_case, UUID strings, RFC3339 UTC timestamps, decimal-string bytes/revisions, bounded cursor pages `{items,next_cursor}` and RFC9457 `application/problem+json` application errors. Envoy authentication errors remain gateway-owned. Cursors bind scope/filter/sort. Lists/stat exclude file bodies.

`If-Match` is required for overwrite, rename/move/trash and workspace rename/delete. Missing is 428; stale is 412. Restore and purge address the current trash-entry identity; they need no request key or If-Match. Creates fail on name conflict, never implicitly overwrite. Upload initialization captures the overwrite precondition for finalize. Existing-node path mutations also require `expected_node_id`; return 412 `TARGET_MISMATCH` if the path now resolves to another node, even when its revision matches. Resolve and check identity/revision under the mutation lock. ID locators already carry that identity. Creation has no existing target; destination parent paths carry `expected_parent_id` so retries cannot select a replacement directory.

Use 400 validation, 401 authentication, 403 known-scope role denial, 404 hidden/foreign/missing resource, 409 quota/name/state conflict (including `RESOURCE_LIMIT` for configured node/copy/cleanup capacity), 413 request limit, 416 invalid/unsupported range, 429 rate limit and 503 dependency unavailable. Machine codes include `QUOTA_EXCEEDED`, `NAME_CONFLICT`, `SOURCE_REPLACED`, `REVISION_MISMATCH`, `TARGET_MISMATCH`, `CROSS_FILESYSTEM_UNSUPPORTED` and `WORKSPACE_DELETING`. Never reveal foreign-resource metadata.

## Durable admission and status

Account onboarding commits a user keyed by unique Clerk subject before dispatch and needs no request key. Workspace creation commits its provisioning resource, owner and `idempotency_keys` receipt in one transaction, then dispatches the stable Workflow ID. Return 202 with the resource and `Location`; duplicate admission returns the same resource, and a changed normalized payload returns 409. Create receipts complete after the returned mapping is durable and the remote results are released, then expire after 24 hours. Failed provisioning remains visible on the resource. Owner-managed native schedules reconcile bounded pending admissions at startup and every five minutes, without an extra dispatch table or daemon.

Workspace deletion uses resource identity, current Owner authorization, If-Match and a deleting tombstone committed before dispatch. It needs no client idempotency key. Repeated accepted deletion returns 202 while deleting and 204 when deleted. The retained owner can read its terminal tombstone. Failed provisioning can be deleted through the same owner/precondition path; missing storage mappings are resolved and fenced by the Letfs owner. No operations table or Workspace operation-status API remains.

Letfs generates storage IDs. Remote provisioning receipts remain pinned until the result is consumed and Workspace's mapping is durable, then expire after 24 hours. Natural provision-key uniqueness and tombstones prevent an old internal Activity from allocating replacements after receipt expiry. The trusted Temporal control plane carries long child orchestration and short named owner Activities; HTTP remains for public resource access, the facade, processor bytes and external providers.

Copy commits a caller/filesystem-scoped `copy-node` receipt with immutable admission before dispatch. Same-key retry returns 202 with the same copy/destination identity and monitor Location; changed input conflicts. A fresh key targeting an occupied name also conflicts. There is no copy progress table. Unfinished admissions remain pinned; terminal completion starts their 24-hour TTL. Upload finalize uses its own saved transfer state/result.

Trash uses the original node identity and `If-Match`; restore/purge use the current trash-entry identity without retry keys. Every purge commits the entry's purging state before dispatch and follows the same bounded deletion workflow for files and directories. Refresh authorized live/trash state to reconcile an ambiguous response. Never treat every 404 as success or fetch a new revision and blindly repeat an old destructive intent.

## User

| Method / route | Identity | Behavior |
|---|---|---|
| PUT `/me/onboarding` | Verified Clerk subject; internal claim optional | Ensure account, initial workspace/storage and Clerk claim; 202 pending, 200 completed |
| GET `/me/onboarding` | Same bootstrap subject | Caller-only status, IDs and instruction to obtain a fresh session JWT |
| GET `/me` | Internal user claim | Application profile |
| PATCH `/me` | Internal user claim | Profile update; no Clerk login-email change |

No credential is returned. Completed onboarding never recreates a later-deleted first workspace.

## Workspace

| Method / route | Authorization | Behavior |
|---|---|---|
| POST `/workspaces` | Onboarded user | Name and request key; durable provisioning |
| GET `/workspaces` | Onboarded user | Paginated caller memberships/workspaces |
| GET `/workspaces/{ws}` | Viewer | Details and caller role |
| PATCH `/workspaces/{ws}` | Owner | Conditional name change and/or atomic ownership transfer |
| DELETE `/workspaces/{ws}` | Owner | Conditional permanent delete, natural resource identity, 202 or completed 204 |
| GET `/workspaces/{ws}/members` | Viewer | Page plus one batch profile lookup |
| PATCH `/workspaces/{ws}/members/{user}` | Owner | Editor/Viewer role change |
| DELETE `/workspaces/{ws}/members/{user}` | Owner or self | Remove/leave; reject Owner |
| GET `/workspaces/{ws}/storage` | Viewer | Logical used/limit and cleanup backlog from letfs |
| POST `/workspaces/{ws}/invitations` | Owner | Email and `editor|viewer` role only, raw token/link once, no-store |
| GET `/workspaces/{ws}/invitations` | Owner | Paginated metadata, no token |
| DELETE `/workspaces/{ws}/invitations/{id}` | Owner | Revoke |
| POST `/memberships` | Onboarded user | Token and trusted verified-email check; never accept on GET |

Manual link sharing only. Backend clients can use a documented token representation; no fake frontend. Redact tokens from logs/traces. Existing-member acceptance does not overwrite roles; accepted-token replay cannot re-add a removed member. Limits come from Workspace policy config, not a public numeric quota endpoint or billing engine.

## Public files

All routes below are under `/workspaces/{ws}`. Workspace reauthorizes membership and supplies the mapped filesystem and `/drive` mount. A locator selects `{node_id}` or `{path,cwd_id?}`; clients cannot provide arbitrary filesystem mounts.

| Method / suffix | Role | Behavior |
|---|---|---|
| POST `/nodes` | Editor | Directory/exact base64 inline-file create (201), or source_id copy with source If-Match (202); caller-scoped Idempotency-Key; occupied name conflicts |
| GET `/nodes` | Viewer | Bounded direct-child page selected by parent_id or path/cwd |
| GET `/nodes:resolve` | Viewer | Resolve a scoped mounted/relative/ID-alias path |
| GET `/nodes/{node}` | Viewer | Metadata with revision ETag |
| PATCH `/nodes/{node}` | Editor | Conditional rename/move |
| PUT `/nodes/{node}/content` | Editor | Conditional exact inline-byte replacement; Content-Type becomes the file MIME |
| GET `/nodes/{node}/content` | Viewer | Exact inline bytes or direct S3 307, optional revision pin and one byte range |
| GET `/nodes/{node}/archive` | Viewer | Request-owned directory ZIP stream |
| POST `/uploads` | Editor | Object upload admission with Idempotency-Key, canonical size and MIME; parent_id/name creates, node_id/If-Match replaces |
| GET `/uploads/{id}` | Editor and initiator | Transfer status and saved publication result |
| GET `/uploads/{id}/parts?numbers=1,2` | Editor and initiator | Sign 1–64 distinct native multipart part numbers; no-store |
| PUT `/uploads/{id}/completion` | Editor and initiator | Freeze ordered part receipts, verify object evidence and publish once from saved preconditions |
| DELETE `/uploads/{id}` | Editor and initiator | Abort an unpublished candidate; finalized uploads cannot be aborted |
| DELETE `/nodes/{node}` | Editor | Conditional trash admission; returns a detached trash-entry resource |
| GET `/trash-entries` | Viewer | Bounded page of current detached entries |
| GET `/trash-entries/{id}` | Viewer | Current entry metadata and trashed/purging status |
| POST `/trash-entries/{id}:restore` | Editor | Restore the same node at its original parent/name, rejecting conflicts |
| DELETE `/trash-entries/{id}` | Owner | Admit permanent purge (202); already removed entry returns 204 |

GET `/copies/{copy}` requires current Viewer membership plus admission actor/current Owner and exposes destination_root_id, running/succeeded/failed status, decimal-string committed_nodes/committed_bytes and nullable error_code. Missing/expired retained Temporal history returns 410 COPY_EXPIRED. Counters reflect acknowledged effects across workflow runs; they may be lower bounds after an unacknowledged result was subsequently mutated/deleted. Every completed item is immediately visible; failures keep partial content. POST replay returns the stable accepted admission, not a progress snapshot. POST `/files/batch-stat` remains a bounded read resource; old copy and operations action routes are removed.

Normal APIs return 404 for detached content even by ID. No trash preview now. Files retain their original payload and may contain generated read-only children, such as `/drive/report.pdf/artifacts/1-intro.md`. Listing/traversal/cwd accepts files and trailing container syntax; content reads reject a trailing `/` or `/.`. Root-relative `@<canonical UUID>` aliases remain live-node/filesystem scoped; nested matching names are ordinary names. Every artifact mutation/write destination is rejected with 403 `ARTIFACT_READ_ONLY`, including raw-ID access. Copying an artifact into an ordinary directory produces writable content.

Upload requests bind initiator/workspace/filesystem and recheck membership each phase. Upload initialization and copy reject content bodies and batch locators. Inline node create and content replacement enforce decoded-byte and maximum-file limits; larger payloads use object uploads. Download validates one range and rejects invalid/multiple ranges; attachment headers prevent treating uploaded HTML as application content.

Processor uploads use the same `open`, `completing`, `finalized`, `aborted` transfer states. Their completion result is an immutable `{id,status:"finalized",size_bytes}` receipt; artifact publication and search readiness are separate. Inline transfer records bytes while the session remains open. Publication attaches the result node without changing that receipt; repeat completion returns the same receipt after publication, and finalized sessions cannot be aborted or issue more signed capabilities. Superseded output cleanup retains terminal transfer evidence.

`GET /nodes/{node}/processing` returns file-owned `desired_generation`, nullable `published_generation` and `indexed_generation` as decimal strings, `artifact_root_id`, `publication_status=not_required|pending|parsed|ready|failed`, `index_status=not_required|pending|ready|failed` and nullable `error_code`. These are publication/serving facts; Temporal owns execution diagnostics. Unsupported content uses `not_required`.

`POST /nodes/{node}/processing-runs` requires Editor, an empty JSON object and one UUID Idempotency-Key. It returns 202 with the saved `{file_id,generation,workflow_id}` admission. A same-key retry replays that admission; changed file/content identity conflicts. Active receipts pin; completion, failure or supersession starts the non-extending 24-hour retention. A new key requests a new generation. Original bytes remain intact; generated files live below an `artifacts` directory.

`GET /search?q=...` finds live original filenames/titles directly in PostgreSQL. Optional parent uses `node_id` or `path`/`cwd_id`; filters use `type`, `media_type`, and created/updated after/before timestamps. Sort is `name|created_at|updated_at`, direction `asc|desc`, limit 1–100. Keyset cursors bind the filesystem, actor/scope, query, filters and sort.

`POST /search` accepts `{query,filters,limit,cursor}` with limit 1–50. Dense and native BM25 prefetch fuse with RRF; DB live/current/ready checks and filters precede bounded reranking. A result is one original file with current metadata and `matched:{file_id,breadcrumb,snippet}`. Both searches return `{items,next_cursor,degraded}`. Reranker failure returns hybrid order with `degraded=true` and `degraded_reason=RERANK_UNAVAILABLE`; embedding or Qdrant failure returns 503 `DEPENDENCY_UNAVAILABLE`. Semantic cursors carry bounded offsets/seen source IDs, bind query/filter/vector-space context, and may drift as ranking changes. Work is bounded to three candidate pages per request, 10,000 candidate positions and 256 unique sources per cursor chain. Clients should follow `next_cursor` even when filtering produces an empty page.

Client flows: show filename plus AI title/subtitle when available; track publication and index readiness; keep filename search usable while AI work is pending; open the matched breadcrumb from a semantic card; show a rerank degradation banner; offer manual reprocessing after a reported failure. Lists omit embedding context and file bodies. README may be rendered as an overview through the ordinary content route. Artifact/chunk evidence is grouped into its original file card. Trash, replacement and authorization changes remove stale results through current DB validation.

Conversion failures distinguish `RESOURCE_LIMIT` (including memory/image/output
limits), `DOCUMENT_INVALID` (invalid input or rejected conversion) and
`PROCESSING_FAILED` (unexpected converter failure). Worker logs retain the error
class, cause class and peak resident memory when available; dependency stderr and
document contents are not copied into those diagnostics.

Copy validates selected revisions and commits each destination item independently, not source-tree snapshot semantics; see [data model](data-model.md). Reject cross-filesystem copy/move even in one workspace/bucket. An exposed filesystem ID is metadata, not authorization to select arbitrary scope.

## Internal HTTP

Account serves `GET /internal/v1/users?ids=<comma-separated UUIDs>` with bounded member summaries `{id,display_name,avatar_url}`, plus a separate trusted verified-email lookup. Summaries exclude email and onboarding fields; Workspace validates that response IDs belong to its requested membership page. Resource/byte HTTP calls still authenticate service callers and validate delegated resource scope.

Workspace storage mutations use named Activities on `openlet-letfs`: `ProvisionWorkspaceBucket`, `ProvisionWorkspaceFilesystem`, `ReleaseWorkspaceProvisioning`, `FreezeWorkspaceBucket`, `ListWorkspaceFilesystems`, and `CompleteWorkspaceBucketDeletion`. The owner derives provision keys from Workspace identity and validates bucket/filesystem scope against its database. `DeleteWorkspace` awaits Rust `DeleteFilesystem` children directly. No HTTP create/provision-status/delete-poll contract remains. The private same-team Temporal namespace is the trust boundary; queues alone are not authorization and carry no service tokens or bytes. See [workflows](workflows.md) for lifecycle and replay behavior.

### Direct storage transport

Prepare requires a UUID `Idempotency-Key`, canonical decimal `size_bytes` and `media_type`. Public uploads always use object storage; small inline content uses nodes/content directly. Single PUT requires base64 Content-MD5, enforced by the selected provider. Native multipart signs each part's declared length and accepts ordered opaque part ETags at completion; it does not derive a whole-object MD5 from those ETags. Unsupported whole-object multipart MD5 is rejected. The provider contract check verifies signed-header, checksum, conditional-write and size enforcement against the configured provider before it is considered supported.

Admission stores a caller/filesystem-scoped `create-upload` receipt in `idempotency_keys` in the same transaction as the session. It remains pinned until finalization, abort or expiration; completion starts a 24-hour TTL once, and retries do not extend it. Replay returns the same session and never renews capabilities after completion starts. Session/result identity remains separate from request deduplication.

Transfer descriptors carry signed required headers, automatic Content-Length and expiry. Object bytes bypass Workspace/Letfs. Completion freezes multipart receipts before remote calls, reconciles a missing completion acknowledgment with HEAD of the unique candidate key, then atomically rechecks quota/destination/revision/lifecycle and saves the terminal result. ETags are opaque validators. No backend-readback SHA-256 receipt is promised. Publication rejection retains durable candidate cleanup, including unresolved late-write evidence. Multi-file callers use independent sessions with bounded concurrency; one failure does not undo siblings.

Processor descriptors use the internal S3 endpoint; browser descriptors use the configured public signing endpoint. Signed hostnames are never rewritten after signing.

Content responses and redirects use no-store. GET renewal reauthorizes and accepts
`revision=N`; mismatch is 412. Content `If-Match` is rejected because logical
revision is distinct from S3 ETag. Issued URL expiry is the revocation boundary.
Inline bytes use application/octet-stream/attachment; text editing still validates
strings. Private object URLs preserve safe attachment names and Range semantics.

### Directory ZIP streaming

GET `/v1/workspaces/{ws}/nodes/{node}/archive` reauthorizes current viewer membership and streams a directory as ZIP64, using paths relative to that directory and preserving empty descendants. Traversal stops at file payloads; generated artifact directories can be downloaded by their own directory IDs. Unsafe/case-ambiguous extraction paths and configured metadata limits fail before headers. Selected identity/path/revision or byte failures during delivery abort the body. No snapshot is promised; retry restarts the request.

Responses use `application/zip`, safe attachment disposition and `no-store`. There is no export status resource, request key, temporary object or logical quota charge. The configured Letfs runtime is at most 1800 seconds; the Workspace proxy/write deadline is 1810 seconds and the archive-only gateway route is 1815 seconds with a 120-second idle bound. Other routes retain their existing deadlines.

### Trash resources

DELETE nodes/{node} requires Editor and If-Match, detaches the subtree and returns 201 with its trash-entry Location. GET trash-entries and GET trash-entries/{entry} require current Viewer access. Entries expose id, node_id, nullable original parent_id, name, actor_id, status and created_at; the parent may already have been purged. POST trash-entries/{entry}:restore requires Editor and the current entry identity, restores the original live parent/name and rejects name conflicts or purging entries. DELETE trash-entries/{entry} requires Owner, commits purging before dispatch, and returns 202 plus Location or 204 after removal. No request key or deletion monitor table is required.
