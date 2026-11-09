# Application RPC surface

Protobuf under `proto/openlet_api` owns native interfaces; [public OpenAPI](public/openapi.yaml) owns HTTP. Native calls authenticate existing service credentials and explicit actor delegation. [Action pairs](authz/action-resource-matrix.md) are validated at the resource owner.

| Service | Caller and purpose |
|---|---|
| AccountService | Workspace-only bounded GetUserSummaries/GetVerifiedEmails; no delegated actor; exact requested profile IDs, human Clerk verified emails; no bot identity |
| WorkspaceService | Leta-only seven resource/scope methods; explicit user/root delegation for normal reads, human creator provisioning, root personal resolution, human scope grants, and narrowly admitted actor-free cleanup |
| LetaService | Workspace-only actor-free GetLetaBinding, ListWorkspaceLeta and StopLetaForWorkspaceDeletion; canonical binding/inventory and acknowledged lifecycle cleanup before storage deletion; no prompt, model or history |
| FilesystemService | Allowed delegated actor; scoped node/content/search/upload/trash/processing operations |
| StorageAdministrationService | Allowed storage owner; generic CreateFilesystem/CreateScopes and admitted DeleteFilesystem; ListScopes is actor-free Workspace-only and returns bounded active scope/root candidates without permission decisions |
| IngestService | Dedicated ingest principal; stored file/generation/stage authority for processing outputs |

Workspace owns a native RPC listener for Leta. Account starts a Workspace Temporal child. Workspace schedules storage creation activities and deletion children on LetFS's queue. Queue routing contains no Workspace business metadata in LetFS. Existing standard gRPC health and provider-native Clerk/S3/Qdrant/OpenRouter protocols remain.

Workspace deletion enumerates canonical root resources and waits for stopped agents, settled HITL/schedules and exact access cleanup before invoking LetFS storage deletion. Direct cleanup callbacks do not enter the mutex-held WorkspaceChanges handler.

Leta's API process owns its native listener. It binds before downstream readiness checks so Workspace can read canonical bindings without a startup health cycle. Standard health Check is public; application methods require their exact service credential and reject delegated actors. Native TLS is required unless plaintext is explicitly enabled for development.

## Workspace resource operations

`GetWorkspace`, `ListMembers` and `ListAccessibleScopes` share current user/root admission. A root uses its canonical active Leta binding, never a human membership or workspace role. Human scope inspection of a Leta additionally checks current `leta.read`. Only an actor-free cleanup lookup can return deleting/deleted Workspace storage identity, without a name/member view or a Workflow Update.

`EnsureLetaHomeAccess` requires the delegated canonical creator, current `create_leta`, exact home binding and Leta-owned creator/workspace relations. The existing serialized `WorkspaceChanges` queue provisions the persisted scope and publishes exactly home `home_of`, home editor and shared editor for the root. Supplied mutation keys survive caller retries; storage/publication errors are never success.

`ResolvePersonalScope` resolves an active human owner's canonical scope for a verified root without granting content access. `ChangeScopeAccess` accepts typed user/Leta grantees, viewer/editor for Leta, and an optional `personal_owner_user_id` equal to the delegated human for access-request approval. The owning service revalidates that exact active personal owner. Approval grants the root, never its creator or a Leti. The reply reports current effective rights; retained completion/current sufficient access can recover a lost acknowledgement without creating a new grant after deletion.

`CleanupLetaAccess` runs directly outside `WorkspaceChanges`: canonical deleting/archived root plus exact delegated creator, or actor-free cleanup while its Workspace is deleting/deleted. It pages storage scopes and removes only that root's viewer/editor relations. It retains `home_of` and unrelated grants. Native authentication permits no root delegation for provisioning, grants or cleanup. Health Check is public; application calls require the exact Leta credential.

## Filesystem operations

Filesystem metadata uses filesystem identity/action. Every tree operation carries filesystem and scope; BatchStat carries a scope on each locator. Both source and destination scopes of copy/move/restore must belong to the same filesystem and pass their own actions. Locators support live ID/path/cwd/expected identity without virtual path descriptors.

| Operations | Contract |
|---|---|
| GetFilesystem | Filesystem metadata and accounting; independent of content rights |
| CreateNode, ListNodes, GetNode, ResolveNode, BatchStat | Typed bytes/metadata, bounded pages, scoped cursors and live ancestry; optional UUIDv7 CreateNode identity with existing receipt/collision rules |
| Stat, ReadText, TextMetrics | Root-restricted metadata or selected small TEXT/blob-metadata bytes from one snapshot; optional content permission/expected fingerprint; maintained SHA-256 or supported byte digests |
| ReadTree | Actual hierarchy including file-owned artifacts; path/ID order, typed-subject/scope/root/depth-bound cursor, bounded explicit completeness |
| TextSearch | Unary root-restricted literal FILES/snapshot LINES over small TEXT or blob metadata; safe supersets, original line bytes and current content permission; incomplete means no partial payload, not a top-K result |
| ReadImage | Backend-only original read to bounded PNG preview; source/output fingerprints, current permission and publication recheck, no original bytes/URL fallback |
| WriteText, AppendText, PatchText, TruncateText | Unary small-TEXT mutation; observed ID/revision/fingerprint or guarded absent creation, exact UTF-8 and existing byte limits; atomic quota/processing updates, no blob conversion or zero-filled growth |
| CreateDirectories | Atomic relative directory components beneath an observed/root-restricted parent; parents=true accepts existing ordinary directories |
| UpdateNode, ReplaceContent | Identity/revision, cross-scope move, cycle/depth/artifact/quota guards |
| GetDownload, StreamArchive | Content-read; inline or signed object descriptor; bounded ZIP stream invalidated by terminal error |
| CreateCopy | Source content-read/destination write; synchronous completed Node response; no job, monitor or progress RPC |
| SearchFiles, SemanticSearch | Filename keyset pages; semantic top-K with no cursor, one retrieval and bounded reranking |
| GetProcessing, ReprocessNode | Metadata status / write action; generation intent and request identity |
| CreateUpload, GetUpload, AbortUpload | Write plus initiating actor/session authority; immutable completed result |
| GetUploadParts, CompleteUpload | Bounded native parts, opaque ETags, verified size/checksum and saved publication preconditions |
| TrashNode, ListTrash, GetTrash, RestoreTrash, PurgeTrash | Scoped entries, detached content hidden, distinct trash/restore/purge actions; TrashNode.empty_directory atomically refuses files/nonempty directories |
| CreateFilesystem, CreateScopes | Caller-chosen stable UUIDv7 IDs; generic storage, roots created only by CreateScopes |
| ListScopes | Private read-only candidate pages, active filesystem/scopes with valid directory roots, filesystem-bound cursor and limit 1–100; Workspace must filter current rights before exposing metadata |
| DeleteFilesystem | Previously admitted storage cleanup, lifecycle fence and child scope deletion |

## Ingest operations

PrepareParse/PrepareParseOutput/CompleteParse/AbortParse, enrichment preparation/publication/failure and index preparation/completion/failure use source file/generation checks. No custom processing-attempt registry exists. Output sessions additionally bind stage and relative path. GetOutputUpload/GetOutputUploadParts/CompleteOutputUpload/WriteOutputBytes reuse the same transfer receipts and direct signed endpoints.

Transfer completion saves an immutable upload result; artifact publication separately attaches the verified bytes and charges quota. Index readiness requires acknowledged writes and a current-generation/lifecycle recheck. Scope identity flows through index input, Qdrant payload/filter and candidate validation.

The independent `openlet-python` wheel contains generated `openlet_api` and handwritten destination clients. Go/Python clients validate response identity and exact-set requests; applications do not import app-local bindings. Protobuf carries native int64/bytes; public HTTP retains decimal strings, explicit status/headers and raw-byte/ZIP adapters.
