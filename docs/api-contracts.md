# API contracts

Status: implemented public/internal routes are documented in OpenAPI 3.1 at `contracts/public/openapi.yaml` and `contracts/internal/openapi.yaml`. Verification checks local references, schemas and captured real response DTOs against those contracts.

## Common protocol

Public prefix `/v1`; internal prefix `/internal/v1`. JSON snake_case, UUID strings, RFC3339 UTC timestamps, decimal-string bytes/revisions, bounded cursor pages `{items,next_cursor}` and errors `{error:{code,message,request_id}}`. Cursors bind scope/filter/sort. Lists/stat exclude file bodies.

`If-Match` is required for overwrite, rename/move/trash/restore/purge and workspace rename/delete. Missing is 428; stale is 412. Creates fail on name conflict, never implicitly overwrite. Upload initialization captures the overwrite precondition for finalize. Existing-node path mutations also require `expected_node_id`; return 412 `TARGET_MISMATCH` if the path now resolves to another node, even when its revision matches. Resolve and check identity/revision under the mutation lock. ID locators already carry that identity. Creation has no existing target; destination parent paths carry `expected_parent_id` so retries cannot select a replacement directory.

Use 400 validation, 401 authentication, 403 known-scope role denial, 404 hidden/foreign/missing resource, 409 quota/name/state conflict (including `RESOURCE_LIMIT` for configured node/staging capacity), 413 request limit, 416 invalid/unsupported range, 429 rate limit and 503 dependency unavailable. Machine codes include `QUOTA_EXCEEDED`, `NAME_CONFLICT`, `SOURCE_CHANGED`, `REVISION_MISMATCH`, `TARGET_MISMATCH`, `CROSS_FILESYSTEM_UNSUPPORTED` and `WORKSPACE_DELETING`. Never reveal foreign-resource metadata.

## Durable admission and status

Durable starts use a client UUID `Idempotency-Key` (v7 recommended). Plain workflow identity is action/scope/caller/key, not a capability or HMAC. The first activity persists caller/scope/action/key uniqueness and validated-input fingerprint with its initial effect. Conflicting input reuse fails; retries return existing results after Temporal retention too. Onboarding deduplicates by verified Clerk subject independently of client keys.

Start Temporal before business mutation. Return 202 `{operation_id,status_url}` after acknowledged start AND durable caller-bound admission. Bounded wait without locks may return 503/Retry-After; retry must use the same key, because work may be running. For an existing running execution, attach to it. After a closed run, first return/poll any durable admission/result; if none exists, recheck it and allow a replacement run under the same workflow ID (explicit allow-duplicate-after-close semantics). Compare retained original input when available and reject mismatches. The first activity still atomically deduplicates any late prior attempt; pin/test the equivalent Go/Rust SDK conflict/reuse options rather than relying on defaults. No dispatch outbox/replay framework.

Status reads the owning DB caller/scope binding before Temporal, returning pending/running/succeeded/failed, bounded progress and result IDs. A deleted resource is never recreated by replay. No public cancellation API now. A deletion initiator can inspect its retained operation after ordinary workspace access is blocked.

Direct inline-file copy uses a scoped request key/fingerprint in letfs `operations`, committed with the new node/result ID to prevent duplicate output. Reauthorize retries before returning the saved outcome; no generic HTTP payload/header replay. Upload finalize uses its own upload state/result.

Short trash/restore/file-purge transactions do not store request-response receipts or require retry keys. Retry with the original stable identity and `If-Match`; success may instead be 404 (absent/hidden), 409 (lifecycle conflict) or 412 (stale identity/revision). Refresh authorized live/trash state to reconcile an ambiguous response; none of these errors proves who caused the state. Never treat every 404 as success or fetch a new revision and blindly repeat an old destructive intent. Directory purge retains durable admission/status.

## User

| Method / route | Identity | Behavior |
|---|---|---|
| POST `/onboarding` | Verified Clerk subject; internal claim optional | Ensure account, initial workspace/storage and Clerk claim; 202 pending, 200 completed |
| GET `/onboarding` | Same bootstrap subject | Caller-only status, IDs and instruction to obtain a fresh session JWT |
| GET `/me` | Internal user claim | Application profile |
| PATCH `/me` | Internal user claim | Profile update; no Clerk login-email change |

No credential is returned. Completed onboarding never recreates a later-deleted first workspace.

## Workspace

| Method / route | Authorization | Behavior |
|---|---|---|
| POST `/workspaces` | Onboarded user | Name and request key; durable provisioning |
| GET `/workspaces` | Onboarded user | Paginated caller memberships/workspaces |
| GET `/workspaces/{ws}` | Viewer | Details and caller role |
| PATCH `/workspaces/{ws}` | Owner | Conditional name change |
| DELETE `/workspaces/{ws}` | Owner | Conditional permanent delete, request key, 202 |
| GET `/workspaces/{ws}/members` | Viewer | Page plus one batch profile lookup |
| PATCH `/workspaces/{ws}/members/{user}` | Owner | Editor/Viewer role change |
| DELETE `/workspaces/{ws}/members/{user}` | Owner or self | Remove/leave; reject Owner |
| POST `/workspaces/{ws}/ownership` | Owner | Atomic transfer to existing member |
| GET `/workspaces/{ws}/usage` | Viewer | Logical used/limit from letfs |
| GET `/workspaces/{ws}/operations/{op}` | Scoped caller or Owner | Authorized status, no file bodies |
| POST `/workspaces/{ws}/invitations` | Owner | Email and `editor|viewer` role only, raw token/link once, no-store |
| GET `/workspaces/{ws}/invitations` | Owner | Paginated metadata, no token |
| DELETE `/workspaces/{ws}/invitations/{id}` | Owner | Revoke |
| POST `/invitations/accept` | Onboarded user | Token and trusted verified-email check; never accept on GET |

Manual link sharing only. Backend clients can use a documented token representation; no fake frontend. Redact tokens from logs/traces. Existing-member acceptance does not overwrite roles; accepted-token replay cannot re-add a removed member. Limits come from Workspace policy config, not a public numeric quota endpoint or billing engine.

## Public files

All suffixes below are under `/workspaces/{ws}/files`. Workspace authorizes and supplies mapped filesystem/mount scope. A locator is exactly `{node_id}` or `{path,cwd_id?}`. Initial mount `/drive`; generic whole-root mounts are trusted internal context, not client input. `cwd` must be live and cannot escape its mount.

| Method / suffix | Role | Behavior |
|---|---|---|
| GET `/stat` | Viewer | Metadata and revision ETag |
| GET `/list` | Viewer | Keyset direct-child page for a directory or file |
| GET `/processing-status` | Viewer | Current source processing status; 404 when no intent exists |
| POST `/exports` | Viewer | UUID `Idempotency-Key`, bounded `locators` and optional `artifacts`; 202 after durable admission, 200 for an existing result |
| GET `/exports/{export}` | Viewer | Initiator-bound archive state, name, decimal-string size and expiry |
| GET `/exports/{export}/download` | Viewer | Ready result plus direct object download descriptor; reauthorizes each issuance |
| POST `/batch-stat` | Viewer | Bounded set-based locator batch |
| GET `/content` | Viewer | Bounded inline bytes or direct S3 307; optional revision pin and one byte range |
| POST `/directories` | Editor | Parent/name |
| POST `/text` | Editor | Create bounded exact UTF-8 text |
| PUT `/text` | Editor | Conditional whole-file text replacement |
| POST `/rename` | Editor | Conditional name change |
| POST `/move` | Editor | Conditional same-filesystem move |
| POST `/copy` | Editor | Source precondition/request key; 201 childless inline file, 202 object/container |
| POST `/trash` | Editor | Conditional detach; original identity/revision on retry |
| GET `/trash` | Editor | Paginated trash roots; Viewer forbidden |
| POST `/trash/{entry}/restore` | Editor | Conditional restore, optional destination/name; original entry/revision on retry |
| DELETE `/trash/{entry}` | Owner | Conditional purge; 204 childless file, 202 container with durable request key |
| POST `/uploads` | Editor | Idempotent prepare with caller-selected storage/size and captured overwrite precondition |
| PUT `/uploads/{id}/bytes` | Editor | Bounded inline bytes only; identical transfer retry is safe |
| POST `/uploads/{id}/parts` | Editor | Sign up to 64 native multipart parts with MD5/size bounds |
| GET `/uploads/{id}` | Editor | Initiator-scoped state and saved publication result |
| POST `/uploads/{id}/finalize` | Editor | Idempotent publish from saved precondition |
| DELETE `/uploads/{id}` | Editor | Abort unpublished upload |

Normal APIs return 404 for trash/staging even by ID. No trash preview now. Files retain their original payload and may contain generated read-only children, such as `/drive/report.pdf/1-intro.md`. Listing/traversal/cwd accepts files and trailing container syntax; content reads reject a trailing `/` or `/.`. Root-relative `@<canonical UUID>` aliases remain live-node/filesystem scoped; nested matching names are ordinary names. Every artifact mutation/write destination is rejected with 403 `ARTIFACT_READ_ONLY`, including raw-ID access. Copying an artifact into an ordinary directory produces writable content.

Upload requests bind initiator/workspace/filesystem and recheck membership each phase. Upload initialization and copy reject text bodies and batch locators. JSON text helpers enforce body, decoded-byte and maximum-file limits; larger text uses an explicitly chosen object upload. Download validates one range and rejects invalid/multiple ranges; attachment headers prevent treating uploaded HTML as application content.

`GET /processing-status` returns `{operation_id,source_id,stages:{parse,enrichment,index}}`; each stage contains `state=pending|running|succeeded|failed`, nullable `error_code` and `retryable`. `POST /processing-retry` requires Editor and `{locator,stage:enrichment|index}`. It returns 202 while work remains and 200 when already complete; successful earlier stages are retained. Processing preserves original bytes and publishes each artifact-tree update atomically.

`GET /search?query=...` finds live original filenames/titles directly in PostgreSQL. Optional parent uses `node_id` or `path`/`cwd_id`; filters use `type`, `media_type`, and created/updated after/before timestamps. Sort is `name|created_at|updated_at`, direction `asc|desc`, limit 1–100. Keyset cursors bind the filesystem, actor/scope, query, filters and sort.

`POST /semantic-search` accepts `{query,filters,limit,cursor}` with limit 1–50. Dense and native BM25 prefetch fuse with RRF; DB live/current/ready checks and filters precede bounded reranking. A result is one original file with current metadata and `matched:{file_id,breadcrumb,snippet}`. Both searches return `{items,next_cursor,degraded}`. Reranker failure returns hybrid order with `degraded=true` and `degraded_reason=RERANK_UNAVAILABLE`; embedding or Qdrant failure returns 503 `DEPENDENCY_UNAVAILABLE`. Semantic cursors carry bounded offsets/seen source IDs, bind query/filter/vector-space context, and may drift as ranking changes. Work is bounded to three candidate pages per request, 10,000 candidate positions and 256 unique sources per cursor chain. Clients should follow `next_cursor` even when filtering produces an empty page.

Client flows: show filename plus AI title/subtitle when available; track each processing stage; keep filename search usable while AI work is pending; open the matched breadcrumb from a semantic card; show a rerank degradation banner; offer retry for the reported failed stage. Lists omit embedding context and file bodies. README may be rendered as an overview through the ordinary content route. Artifact/chunk evidence is grouped into its original file card. Trash, replacement and authorization changes remove stale results through current DB validation.

Conversion failures distinguish `RESOURCE_LIMIT` (including memory/image/output
limits), `DOCUMENT_INVALID` (invalid input or rejected conversion) and
`PROCESSING_FAILED` (unexpected converter failure). Worker logs retain the error
class, cause class and peak resident memory when available; dependency stderr and
document contents are not copied into those diagnostics.

Copy has coherent per-file revisions and final destination publication, not source-tree snapshot semantics; see [data model](data-model.md). Reject cross-filesystem copy/move even in one workspace/bucket. An exposed filesystem ID is metadata, not authorization to select arbitrary scope.

## Internal HTTP

User provides bounded member summaries `{id,display_name,avatar_url}` and a separate trusted verified-email lookup to Workspace. Never reuse `/me` or include email, Clerk IDs or onboarding/internal fields in member summaries; validate returned IDs belong to the requested membership page. letfs provides idempotent bucket/filesystem ensure, freeze/usage/configured-limit policy, lifecycle/status and scoped file primitives. Provision-key reuse with inconsistent immutable scope is conflict. All internal routes authenticate/allowlist service callers and validate resource scope.

Each service starts its own workflows through its API; cross-service activities call small HTTP request/result/status contracts, not another language's Temporal activity/child type. Local activities call application functions directly. Actor context is audit/context, not letfs role authority. Verify UUIDs, decimal counters, timestamps, optional/null fields and errors using explicit DTO tests plus actual Go/Rust HTTP. No schema registry/custom codec/code-generation framework.

### Direct storage transport

Prepare requires a UUID `Idempotency-Key`, `storage=inline|object` and canonical
decimal `size_bytes`. Single object PUT requires base64 Content-MD5; multipart
checksums belong to individual parts. Transfer descriptors carry required headers,
auto-generated Content-Length and expiry. No object body crosses Workspace/letfs.
MD5 checks transfer integrity; no backend-readback SHA-256 receipt is promised.
Completion checks provider evidence outside locks, then atomically enforces quota,
destination/revision/lifecycle and saves the terminal result. Multipart receipt
intent is immutable. Multi-file callers use independent sessions with bounded
concurrency and existing batch-stat metadata lookup; one failure does not undo siblings.

Content responses and redirects use no-store. GET renewal reauthorizes and accepts
`revision=N`; mismatch is 412. Content `If-Match` is rejected because logical
revision is distinct from S3 ETag. Issued URL expiry is the revocation boundary.
Inline bytes use application/octet-stream/attachment; text editing still validates
strings. Private object URLs preserve safe attachment names and Range semantics.

### ZIP exports

Ordinary single-file content reads use the existing content route. Folder and
multi-selection exports include original payloads, stopping at file nodes.
`artifacts=true` requires one source file and exports only its published children
as `<source-name>-artifacts.zip`. Direct artifact directories may also be selected.
Selected directory roots and empty directories remain; overlapping selections are
deduplicated. Top-level name collisions receive deterministic suffixes in the ZIP.
Unsafe or ambiguous extraction paths fail the request.

Status uses `running|succeeded|failed|expired`; no download descriptor exists until
the complete ZIP publishes. The download route returns `download` containing
`transport=object`, `url` and `expires_at`. Range/retry and URL renewal use the same
completed object. Retention defaults to 24 hours; URL validity cannot exceed its
remaining lifetime. Exports do not create nodes or consume logical quota. A source
change fails an attempt; retries may enumerate the current tree rather than a
historical snapshot.
