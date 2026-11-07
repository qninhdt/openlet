# Application RPC surface

Protobuf under `proto/openlet_api` owns native interfaces; [public OpenAPI](public/openapi.yaml) owns HTTP. Native calls authenticate existing service credentials and explicit actor delegation. [Action pairs](authz/action-resource-matrix.md) are validated at the resource owner.

| Service | Caller and purpose |
|---|---|
| AccountService | Workspace-only bounded GetAccountSummaries/GetVerifiedEmails; no delegated actor; exact requested profile IDs, user Clerk verified emails, empty agent email set |
| FilesystemService | Allowed delegated actor; scoped node/content/search/upload/trash/processing operations |
| StorageAdministrationService | Allowed storage owner; generic CreateFilesystem/CreateScopes and admitted DeleteFilesystem |
| IngestService | Dedicated ingest principal; stored file/generation/stage authority for processing outputs |

Workspace has no RPC server. Account starts a Workspace Temporal child. Workspace schedules storage creation activities and deletion children on LetFS's queue. Queue routing contains no Workspace business metadata in LetFS. Existing standard gRPC health and provider-native Clerk/S3/Qdrant/OpenRouter protocols remain.

## Filesystem operations

Filesystem metadata uses filesystem identity/action. Every tree operation carries filesystem and scope. Both source and destination scopes of copy must belong to the same filesystem and pass their own actions. Locators support live ID/path/cwd/expected identity without virtual path descriptors.

| Operations | Contract |
|---|---|
| GetFilesystem | Filesystem metadata and accounting; independent of content rights |
| CreateNode, ListNodes, GetNode, ResolveNode, BatchStat | Typed bytes/metadata, bounded pages, scoped cursors and live ancestry |
| UpdateNode, ReplaceContent | Identity/revision, same-scope move, cycle/depth/artifact/quota guards |
| GetDownload, StreamArchive | Content-read; inline or signed object descriptor; bounded ZIP stream invalidated by terminal error |
| CreateCopy | Source content-read/destination write; stable copy/destination identity; no monitor or progress RPC |
| GetProcessing, ReprocessNode | Metadata status / write action; generation intent and request identity |
| CreateUpload, GetUpload, AbortUpload | Write plus initiating actor/session authority; immutable completed result |
| GetUploadParts, CompleteUpload | Bounded native parts, opaque ETags, verified size/checksum and saved publication preconditions |
| TrashNode, ListTrash, GetTrash, RestoreTrash, PurgeTrash | Scoped entries, detached content hidden, distinct trash/restore/purge actions |
| CreateFilesystem, CreateScopes | Caller-chosen stable UUIDv7 IDs; generic storage, roots created only by CreateScopes |
| DeleteFilesystem | Previously admitted storage cleanup, lifecycle fence and child scope deletion |

## Ingest operations

PrepareParse/PrepareParseOutput/CompleteParse/AbortParse, enrichment preparation/publication/failure and index preparation/completion/failure use source file/generation checks. No custom processing-attempt registry exists. Output sessions additionally bind stage and relative path. GetOutputUpload/GetOutputUploadParts/CompleteOutputUpload/WriteOutputBytes reuse the same transfer receipts and direct signed endpoints.

Transfer completion saves an immutable upload result; artifact publication separately attaches the verified bytes and charges quota. Index readiness requires acknowledged writes and a current-generation/lifecycle recheck. Scope identity flows through index input, Qdrant payload/filter and candidate validation.

The independent `openlet-python` wheel contains generated `openlet_api` and handwritten destination clients. Go/Python clients validate response identity and exact-set requests; applications do not import app-local bindings. Protobuf carries native int64/bytes; public HTTP retains decimal strings, explicit status/headers and raw-byte/ZIP adapters.
