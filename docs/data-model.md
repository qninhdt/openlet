# Data model and consistency

Executable DDL lives in [Platform migrations](../apps/platform/migrations/) and [LetFS migrations](../apps/letfs/migrations/). [SpiceDB](../packages/contracts/authz/schema.zed) is canonical for authorization. No service keeps SQL membership, resource-owner or grant mirrors.

Platform stores users, workspaces, invitations and local idempotency receipts. User rows have Clerk identity and profile fields, with no initial-workspace/onboarding state. Workspace provisioning/deletion state supports its concrete durable lifecycle. Invitations store only hashed tokens, verified-email targets, expiry and accepted user. Add-member and invitation acceptance use the same bounded graph check for the configured member limit; it is not a strict counter across concurrent admissions. A consumed invitation cannot regrant removed membership. A failed consume→graph write requires a new invitation; plaintext tokens are returned only on first creation.

LetFS stores a `workspace_storage` budget keyed directly by workspace ID, many storages per workspace, tree nodes, file payloads/metadata, processing, uploads, trash occurrences and local receipts. Node structural fields are separate from file payloads. A file contains either PostgreSQL text or an S3 object key. Artifacts are ordinary child nodes beneath a blob source, protected as readonly by ancestry.

`files.version` is the sole content version. Blob replacement increments it, discards old artifacts and resets processing in one transaction. Late publication for another version is obsolete. Text mutations support optional expected-version checks and never dispatch ingest.

Quota counts logical bytes, including trash and copies sharing an immutable object. A conditional SQL UPDATE changes usage in the mutation transaction. No reservation/lease exists; upload completion may fail quota even after a successful S3 transfer. Object/index garbage collection follows logical deletion.

ID/path resolution and recursive operations use SQL batches/recursive CTEs. Mount containment, readonly artifacts, name conflicts and cycles are enforced at their owning boundary. A text read-modify-write can lock that file row; quota UPDATE takes its ordinary row lock. No ancestor/storage/workspace-wide application lock is taken.

Each owning database stores request keys scoped by typed caller and method, a deterministic request hash, saved response and expiry. The receipt and local mutation commit together. CreateUpload also checks completed receipts before resolving mutable targets or creating S3 multipart transfers. Repeating a key replays the result; changing its input conflicts. Workflow IDs identify durable lifecycle work. Upload/trash identities supply natural retry boundaries. Cross-service SQL and graph writes are not a distributed transaction.
