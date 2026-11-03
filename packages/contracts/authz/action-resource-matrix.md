# Action, resource and tuple ownership

This is the migration contract for built-in roles. Built-in role/action policy lives in repository `roles.json` and is loaded directly into SpiceDB. PostgreSQL owns existing business facts (users, workspace memberships/assigned roles and storage references); Temporal synchronizes their derived relationships. No SQL permission catalog or graph mirror exists. Supported action identifiers are the exact SpiceDB permission names in `schema.zed` and typed Go constants in `packages/go/authz/actions.go`. Services check actions, never role names. Role names remain domain/display data.

## Public operations

`V/E/O` means Viewer, Editor and Owner. `E/O` means Editor and Owner. All file operations resolve and check the actual filesystem ID; path aliases, mounts, payload workspace IDs and guessed UUIDs supply no permission.

| Operation | Action | Resource | Built-in grants | Additional invariant |
|---|---|---|---|---|
| Read own account | `account_read` | `account:<user>` | Own subject | Active account |
| Update own account | `account_update` | `account:<user>` | Own subject | Display name/avatar validation; no email mutation |
| Get workspace, status, list candidate | `workspace_read` | `workspace:<id>` | V/E/O | Candidate discovery is bounded canonical SQL plus graph filtering; status includes provisioning/failed; retained Owner can read deleted tombstone |
| Update name | `workspace_update` | workspace | O | Active lifecycle, revision |
| Begin deletion | `workspace_delete` | workspace | O | Active/failed admission; repeated deleting/deleted behavior preserved |
| Transfer ownership | `workspace_transfer` | workspace | O | Exactly one Owner in SQL; atomic graph write; target member/limits/revision |
| List members | `member_read` | workspace | V/E/O | Active; bounded Account summaries |
| Change/remove another member | `member_manage` | workspace | O | Cannot remove/change Owner through member routes |
| Leave own workspace | `member_leave` | workspace | V/E/O | Target must equal actor; Owner must transfer first |
| List invitations | `invitation_read` | workspace | O | All statuses, no raw token |
| Create invitation | `invitation_create` | workspace | O | Editor/Viewer grant only; normalized verified email; one-time raw token |
| Revoke invitation | `invitation_revoke` | workspace | O | Scoped pending invitation |
| List nodes | `node_list` | filesystem | V/E/O | Live ancestry; bounded pagination |
| Stat and batch-stat | `node_read` | filesystem | V/E/O | Bound IDs to FS, maximum 100 locators |
| Resolve path | `node_resolve` | filesystem | V/E/O | Mount/cwd/alias bounds and same-FS validation |
| Create directory/inline file | `node_create` | filesystem | E/O | Writable ancestry, scoped receipt, quota, canonical bounded bytes |
| Rename/move | `node_update` | filesystem | E/O | Revision, expected identities, cycle/depth, immutable artifact rules |
| Trash node | `node_trash` | filesystem | E/O | Revision; detach root, retain charged bytes |
| Download content | `content_read` | filesystem | V/E/O | Live file payload; revision query; bounded signed URL capability |
| Replace inline content | `content_write` | filesystem | E/O | If-Match, size/quota, immutable artifact restrictions |
| List/get trash metadata | `trash_read` | filesystem | V/E/O | No detached-content read authority |
| Restore trash | `trash_restore` | filesystem | E/O | Current entry identity, original parent/name, no overwrite |
| Purge trash | `trash_purge` | filesystem | O | Current entry identity; durable purge fence |
| Create upload | `upload_create` | filesystem | E/O | Immutable initiating actor and destination/revision |
| Read upload status | `upload_read` | filesystem | E/O | Initiating actor only; excludes ingest uploads |
| Sign upload parts | `upload_sign` | filesystem | E/O | Same actor; immutable candidate/size/checksum; no capability renewal after completion |
| Complete upload | `upload_complete` | filesystem | E/O | Same actor; receipt and exact storage evidence; atomic publish |
| Abort upload | `upload_abort` | filesystem | E/O | Same actor; cleanup evidence retained |
| Copy/admit tree | `copy_create` and source `node_read` | filesystem | E/O | Same-FS only; source/destination revision and artifact rules; scoped receipt |
| Read copy progress | `copy_read` | filesystem | V/E/O | Initiating actor, otherwise also require `copy_inspect_any` |
| Inspect another actor's copy | `copy_inspect_any` | filesystem | O | Current permission, not former/historical Owner |
| Read processing status | `processing_read` | filesystem | V/E/O | Live source and current generation |
| Reprocess | `processing_run` | filesystem | E/O | Scoped receipt, writable original, generation fence |
| Filename/semantic search | `search` | filesystem | V/E/O | Current/live/ready evidence hydration before rerank; bounded work and cursor scope |
| Download ZIP | `archive` | filesystem | V/E/O | Directory preflight; request-owned bounded stream/cancellation |
| Read bucket usage | `bucket_read` | `quota_bucket:<id>` | V/E/O | Independent bucket grant; filesystem grant alone is insufficient |
| Change bucket configuration | `bucket_admin` | quota_bucket | O | Workspace owns requested policy/limit; private storage methods additionally require explicit service authority |

Filesystem and bucket permissions additionally require workspace `enabled` in the graph. Workspace status permission does not: ordinary provisioning/deletion lifecycle gates remain owner invariants, independent of permission-projection lag.

## Exceptional caller authorities

| Operation family | Authority and owner |
|---|---|
| Onboard/get onboarding | Account verifies gateway credential and Clerk subject on the exact bootstrap routes before an internal user/graph exists; missing identity is never general allow |
| Create workspace | Workspace verifies authenticated onboarded Account identity; owns count/creation idempotency, preallocated storage IDs and initial Owner grant |
| Accept invitation | Workspace verifies actor plus token, expiry, pending/replay state and Account-sourced verified email; cannot require membership before creation or recreate removed membership on replay |
| Account summaries/verified emails | Explicit Workspace service-method credential; bounded active-user queries; verified addresses come from Account/Clerk |
| Storage create/freeze/list/delete | Named owner-service/job authority and stable bucket/FS IDs; no business owner lookup, provision key or public-user override |
| Ingest prepare/output/complete/fail | Authenticated ingest service plus recorded file/generation/stage/attempt authority; no arbitrary user impersonation |
| Copy/purge/delete/maintenance | Registered Temporal job authority plus saved resource/lifecycle/generation fences; file bytes and credentials stay out of histories |
| Liveness/readiness | Process/standard gRPC health; no user action; readiness fails on required dependency/migration/schema failure |

## Relationship writers

| Graph relationship | Source and sole writer | Scope |
|---|---|---|
| `account:<id>#subject@user:<id>` | Account user record; Account Temporal worker | User self relationship |
| `role:<id>#<action>@user:*` | Repository `roles.json`; deployment policy initializer | Built-in role capabilities; no SQL catalog |
| `role_grant:<workspace>/<role>#role@role:<id>` | Repository role IDs and Workspace identity; Workspace Temporal worker | Three stable groups per Workspace; no revision/status snapshots |
| `role_grant:<workspace>/<role>#member@user:<id>` | Workspace membership; Workspace Temporal worker | Touch the affected member role and delete its other role tuples |
| `workspace:<id>#grant@role_grant:<id>` | Workspace membership; Workspace Temporal worker | Stable group links created during provisioning; owner transfer writes both members atomically |
| `workspace:<id>#enabled@user:*` | Workspace lifecycle; Workspace Temporal worker | Active storage access |
| `filesystem:<id>#workspace@workspace:<id>` | Workspace storage references; Workspace Temporal worker | Filesystem inheritance |
| `quota_bucket:<id>#workspace@workspace:<id>` | Workspace storage references; Workspace Temporal worker | Bucket inheritance |

letfs and ingest never write graph tuples. letfs stores no filesystem-to-business-resource mapping and has no projection binding table, intent or rebuild exporter. The same graph deployment is trusted internal infrastructure: SDK credentials do not create per-type writer isolation. Application ownership plus explicit method/job authority enforce the accepted boundary.

## Behavior and regression owners

The full current behavior inventory is recorded in the [filesystem parity inventory](../../../plans/reports/scout-261102-1059-letfs-go-parity.md) and [Account/Workspace source inventory](../../../plans/reports/scout-261102-1059-authorization-rpc-inventory.md). These are source maps; the tables above and reviewed architecture supersede historical target suggestions.

| Behavior | Implementation and regression owner |
|---|---|
| Bootstrap, unique subject, active-user profile, verified-email authority | Account; generated Account RPC and onboarding integration |
| Built-in role/action policy | Repository policy and deployment initializer; real SpiceDB action matrix tests |
| Memberships, invitations, lifecycle, storage references and relationship sync/rebuild | Workspace; existing business SQL, SpiceDB and persistent Temporal integration |
| Generic provisioning, tombstones/idempotency, tree/path/cwd/mounts, revision, quota | letfs core/storage; actual SQL concurrency and application/gRPC tests |
| Inline/object/single/multipart uploads, signed bytes, ambiguous transfer cleanup | letfs storage; actual PostgreSQL/S3 and immutable transfer receipts |
| Trash/purge/FS deletion/copy, bounded progress and recovery | letfs Temporal worker and local core; workflow/replay plus real restart histories |
| Processing/enrichment/indexing/maintenance/backfill/search | letfs jobs/search and ingest activities; real PG/Qdrant/Python-to-Go fixtures |
| DOCX/PDF/PPTX/XLSX/OCR/image parsing, diagnostics, subprocess shutdown | Ingest; existing real parser corpus and activity tests |
| HTTP/gRPC shape, raw bytes, Range/ETag/redirect/error/stream cancel | letfs application adapters; real HTTP/HTTP2, Envoy and native generated clients |
| Gateway JWT/service/delegation/private-method isolation | Shared RPC identity and Envoy; actual application entry-point denial and gateway proof |
| Rename, route cutover, recovery writer drain, build/discovery/codegen | Runtime/CI/recovery tooling; coordinated phase-6 switch, phase-7 acceptance |

No role fallback, authorization cache, public projection-status API or workspace-wide projection-lag gate is part of this contract.
