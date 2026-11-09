# Accepted direction: human users and workspace-owned Leta resources

Status: all design-review groups are settled, including the subsequent SSE/Redis corrections recorded below. The user now requests a coherent rewrite of the full implementation plan and an explicit user/agent migration phase. This authorizes planning/documentation only; no production implementation or migration has started.

## Outcome and boundaries

- Human identity is stored in users only. Remove managed agent accounts and account ownership.
- Leta is a long-lived workspace resource created by a human member. Leti remains a runtime child inside a box, with no independent scope grants.
- Preserve the accepted agent engine, asynchronous inbox/HITL/schedules, owner-only MVP conversation, public history/compaction and Mirage integration where independent of account provisioning.
- Scope discovery serves ordinary users as well as Leta. Large text remains an S3/object blob; agents access inline text and permitted metadata/artifacts.
- No source/config/schema/database/Clerk change, deployment or persistent migration occurs in this design turn. No automatic data deletion or extra infrastructure.

Acceptance for this design: identify removed account/membership machinery, propose a human-only user schema and resource-runtime schema, explain independent resource permissions/storage/HITL and generic scope discovery, and identify the actual cross-service contracts that change. This is not a passed runtime acceptance claim.

## Latest review decisions

| Previous item | New disposition |
| --- | --- |
| 19 | Typed native service interfaces accepted in principle. Managed-account provisioning/membership methods are now obsolete; derive the actual method set from this redesign. |
| 20 | Accessible-scope API must serve users and Leta, not agents only. |
| 21 | Small inline UTF-8 TEXT accepted, subject to the existing small/large storage boundary. |
| 22 | Large canonical TEXT and new download/ingest text streams rejected. Large text uses existing blob/S3 handling; the agent does not edit/read its raw body. |
| 23 | Backend mount-root restriction accepted. |
| 24 | Native metadata/tree/selected small-text reads accepted. This does not require a new large-content streaming transport. |
| 25 | Accepted after explanation: ordinary text write/edit/append works; positional writes with zero-filled gaps, truncate growth and invalid UTF-8 byte cuts are unsupported. No padding emulation. |
| 26 | Existing trash/copy/no-overwrite/partial-copy semantics accepted. |

The former plan's provisioning/permission design is superseded. Its independent engine decisions remain useful context. Original items 27–42 remain a saved review inventory, not accepted by silence; some require reframing after this redesign.

## Current source evidence

| Owner/source | Current fact |
| --- | --- |
| `apps/account/migrations/0001_initial.sql` | accounts mixes user/agent using type, nullable clerk_id, owner_id and owner index/checks. |
| `apps/account/internal/account/store.go::EnsureAccount/CreateManaged/Profile` | Human onboarding inserts type=user; managed creation inserts type=agent and checks immutable owner. Profile exposes both type and owner_id. |
| `apps/account/internal/account/service.go::CreateManaged/GetAccount/UpdateAccount` | Public managed creation and cross-account owner access are real implemented behavior, not just the pending Leta plan. |
| `apps/account/internal/temporal/workflows.go::AccountChanges/StartManaged` | Separate managed-account creation Workflow exists. Human OnboardUser creates a workspace and publishes identity. |
| `apps/workspace/migrations/0001_initial.sql` | workspace_members stores account_id and personal_scope_id; invitations store accepted_account_id. No implemented managed_owner_id column exists. |
| `packages/contracts/authz/schema.zed` | account has self/owner; workspace roles reference account; scope grants reference account and workspace usersets. |
| `packages/go/authz/client.go::Check/BulkCheck`, `packages/python/src/openlet/authz.py::_request` | Both hardcode subject object type account. |
| `packages/go/identity/principal.go`, `packages/go/rpc/authentication.go` | Principal carries actor UUID but no subject kind; native delegation uses x-openlet-account-id. |
| `apps/letfs/internal/filesystem/provisioning.go::CreateScopes` | A scope is independent storage identified by filesystem/scope/root. It does not require an Account record. |
| `apps/letfs/internal/filesystem/authorization.go::authorize` | LetFS uses the shared hardcoded-account check today; supporting Leta subjects needs a real typed-authority change here. |
| `apps/letfs/internal/config/config.go` | Default InlineLimit is 262144 bytes (256 KiB), configurable with an existing maximum of 1 MiB; default MaxFileBytes is 100 MiB. |
| `apps/letfs/internal/filesystem/upload_publication.go::publishUpload` | Existing object publication stores object_key and uses the current processing/transfer path. |
| `apps/account/internal/clients/clerk/client.go::PublishAccountIdentity/AccountIdentity`, `infra/config/envoy.template.json` | Human UUID is published as openlet_account_id and propagated by gateway; a user-field rename reaches both writer and reader. |

No live database was queried. A previous completed account/scope plan described an originally non-production replacement, but that historical statement is not proof of today's data contents.

## Compared authority choices

1. Execute as the creator user. This minimizes subject-type changes but depends on the creator's full permission set. Without extra filtering it grants owner personal access by default, and another user's approval grants to the creator rather than to Leta. It fails the already requested independent grant boundary first.
2. Use Leta's resource ID as a SpiceDB subject. This requires the small explicit user/leta subject distinction in trusted native calls and existing authz clients. It preserves independent scope grants, no agent login/member/account, and inherited Leti rights. The implementation risk is a caller selecting an unauthorized subject kind, addressed at the native credential boundary, not by trusting model arguments.

Recommendation: option 2. Better approaches: none beyond the requested workspace-resource direction; using existing SpiceDB resource subjects is the smallest way to preserve the requested independent access behavior. No generic principal registry, account replacement table or per-agent credential is needed.

## Human identity schema

Proposed users table in the existing identity service database:

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    clerk_id TEXT NOT NULL UNIQUE
        CHECK (length(clerk_id) BETWEEN 1 AND 200),
    display_name TEXT NOT NULL DEFAULT ''
        CHECK (length(display_name) <= 100),
    avatar_url TEXT NOT NULL DEFAULT ''
        CHECK (length(avatar_url) <= 2048),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

This is a target schema sketch, not a command to run. Preserve current human UUIDs and profile validation. Remove accounts.type, owner_id, accounts_by_owner, self-referencing owner FK and mixed human/agent constraints. Do not add a new user lifecycle/status, bot flag, ownership field or role here. Roles stay in workspace_members.

Workspace uses workspace_members.user_id and workspace_invitations.accepted_user_id. Personal scopes still belong to human memberships. Idempotency table names/retention are unchanged; ordinary mutation actor IDs remain authenticated human IDs. Do not add a receipt table.

Remove managed profile routes and methods: POST /v1/accounts, GET/PATCH /v1/accounts/{id}, ManagedCreation, CreateManaged, StartManaged, ApplyAccountChange and AccountChanges. Keep /v1/me, onboarding, verified-email lookup and bounded user-summary lookup. Native summary messages no longer need proposed agent type/owner enrichment. Profile self-access can use the verified current user; no account-owner authorization traversal or self-tuple publication is required.

Use UserSummary/GetUserSummaries and user_id in the corresponding new contracts, generated clients and responses. A coordinated rename of human claim/header fields to openlet_user_id/x-openlet-user-id must update Clerk publication/readback, Envoy sanitation/claim mapping, Go/Python gateway/native helpers and fixtures together, preserving UUIDs. The existing identity deployment can remain apps/account; renaming the physical deployment is not required for the domain change. No dual identity model or new login system.

## Leta and Leti runtime schema

Keep the existing proposed **single agents table** for both runtime kinds, rather than introducing a second identity registry. A root row is the Leta resource itself. Its UUID is a resource ID, unrelated to any users row.

| Field/group | Root Leta | Leti |
| --- | --- | --- |
| id | Resource/runtime ID | Child runtime ID |
| kind | leta | leti |
| leta_id | Same as id | Root resource ID |
| workspace_id | Required, immutable | Derived through root |
| created_by_user_id | Required human creator | Derived through root |
| home_scope_id | Required ordinary LetFS scope | None; uses box home |
| box_id | Null | Required |
| name, description, system_prompt | Leta profile/config | Immutable graph-provided identity/prompt |
| model_id, reasoning_effort | Server-supported owner choice | Inherits unless owner API overrides |
| status, timestamps | Existing resource lifecycle | Existing child lifecycle |
| paused | Root control | Effective root pause |
| inbox_seq, activity_seq | Existing ordered counters | Existing ordered counters |

Retain root/child checks, box/edge integrity, cursor indexes and run/history/checkpoint contracts where still applicable. No cross-service FK to users or workspaces; validate through owning APIs. Remove root Account-ID equality, owner_account_id, membership_key and leave_key. Replace personal_scope_id with home_scope_id. A normal stable storage-create request key, if required by the existing CreateScopes call, is part of that effect's retry, not a new operation entity.

Other domain changes:

- boxes/edges stay under root Leta; shared box home remains .leti/<derived-box-slug>.
- messages replaces human recipient_account_id with recipient_user_id. Agent routes remain real Leta/Leti/box IDs, never users IDs for bots.
- hitl_requests uses approver_user_id; access approval grantee is root leta_id, not an Account. Ask still targets the creator and returns to the original requester.
- runs/activity_log/schedules and LangGraph thread ID remain agent-based. No membership or role is added to these tables.
- Frontend shows Leta in workspace resources/agents, separate from the human member list. Profile/config comes from Leta, not the user service.

## Proposed SpiceDB schema

This excerpt is a proposed policy to validate against the actual schema generator/SpiceDB; it has not been executed:

```zed
definition user {}

definition workspace {
    relation owner: user
    relation admin: user
    relation member: user
    permission read = owner + admin + member
    permission update = owner + admin
    permission manage_members = owner + admin
    permission create_leta = owner + admin + member
    permission delete = owner
}

definition leta {
    relation workspace: workspace
    relation creator: user
    permission read = creator & workspace->read
    permission manage = creator & workspace->read
}

definition scope {
    relation manager: user | workspace#owner | workspace#admin
    relation editor: user | leta | workspace#member
    relation viewer: user | leta
    relation home_of: leta
    permission read_metadata = viewer + editor + manager + home_of->read
    permission read_content = viewer + editor + manager + home_of->read
    permission write = editor + manager
    permission trash = editor + manager
    permission restore = editor + manager
    permission purge = manager
    permission manage_access = manager
}
```

Filesystem reader/deleter relations likewise replace human account subjects with user; preserve current workspace usersets. Do not add Leta to workspace.member or grant automatic human profile access. There is no account definition/self/owner tuple.

Default MVP human access stays creator-only conversation/history/control while the creator is a current workspace member, preserving the prior owner-only product requirement. No automatic all-member transcript sharing or additional admin data access is inferred. Workspace deletion still owns resource teardown. Broadening resource sharing is a separate product choice.

Example relationships (W workspace, U creator, L Leta, H home scope, S shared scope):

```text
leta:L#workspace@workspace:W
leta:L#creator@user:U
scope:H#home_of@leta:L
scope:H#editor@leta:L
scope:S#editor@leta:L
```

Home read for creator follows home_of->read, including current workspace membership; there is no permanent owner-viewer grant/repair/leave exception. Home scope is ordinary storage, not a personal membership for Leta. Personal scope P granted by another user uses scope:P#viewer@leta:L or editor@leta:L. No home_of edge is written on P, so creator ownership does not confer direct access to P.

Leta owns its resource rows and corresponding leta relationships. Workspace continues to own default scope-access/grant mutations and storage provisioning integration. Do not turn Leta into a general writer of foreign scope permissions. A narrow internal home/default-access operation can reuse existing LetFS CreateScopes and Workspace relationship publication, validating the trusted Leta service, creator/create_leta authority and exact workspace/resource binding. This replaces managed-account provisioning rather than adding another resource engine.

## Trusted native identity

- Browser/gateway requests identify user only. Users cannot supply a Leta actor through public payloads or forwarded headers.
- Leta runtime authenticates with the existing Leta service credential, then supplies its server-selected root resource ID as subject kind leta. No per-Leta token, JWT, account or login.
- Go/Python authz helpers accept the closed subject distinction user/leta instead of hardcoding account. Native actor parsing preserves verified service identity and restricts Leta subjects to the appropriate service/methods. LetFS content/search/mutation checks use the actual subject kind.
- Leti requests use the root Leta subject plus the accepted backend root-restricted Locator; no Leti authz subject/tuples.
- Human approval grants use the recorded resource-owner user as actor and the Leta resource as grantee. Do not run filesystem calls under the creator/approver after approval.

This transport/authz change is necessary work, not an assertion that the existing code already accepts typed subjects. Do not add arbitrary subject strings or credentials to model tool arguments.

## Accessible scopes for users and Leta

One proposed Workspace API serves both:

```text
GET /v1/workspaces/{workspace_id}/scopes
    Current authenticated user's accessible scopes.

GET /v1/workspaces/{workspace_id}/scopes?leta_id={id}
    That resource's accessible scopes; caller must be allowed to inspect it.
```

The native equivalent accepts a verified user/leta subject. Runtime calls do not require a human session. Do not expose arbitrary users' accessible scopes simply because a query accepts an ID.

Candidate scopes must include more than shared + human personal scopes now that Leta homes exist. Recommended small backend addition: a private, paginated LetFS scope listing for the workspace filesystem, reusing the existing scopes_by_filesystem index. Workspace obtains candidate metadata, BulkChecks current subject permissions and returns only accessible results. No cross-service SQL join, grant mirror table or agent-only endpoint. Root metadata can be returned from that listing and filtered before publication; no file content/tree is loaded to discover mounts. Human labels use existing membership mappings; Leta already knows its own home_scope_id.

Return scope/root IDs, current read/write rights, relevant ownership/labels where known, and cursor. Mount layout remains ~/ for resource home, /shared/ and /users/<human-id>/ for approved personal scopes. User file browser and agent mount builder consume the same access logic.

## Small text versus blob

Preserve the existing InlineLimit boundary (currently default 256 KiB, not a new 100 MiB canonical text limit). Small supported UTF-8 text is stored in TEXT; legacy inline binary stays binary; larger text uses the existing object/blob transfer/processing path. MIME text/plain does not imply agent-editable inline storage.

- Small text: native stat/selected read/tree/grep/edit hooks; unary bounded read/write results are enough for the normal inline payload ceiling.
- Large text: agent gets blob metadata and artifact tree, just like other blobs. No original S3 URL/raw object body is returned through Mirage. Permitted small artifacts remain usable.
- Agent text writes/append/edit that exceed the inline limit return a clear size error; they do not silently turn an editable file into a blob or upload a large body behind the tool's back.
- Existing owner blob uploads/downloads and original binary ingest remain. Do not migrate object-backed text into PostgreSQL solely because its MIME is textual.
- Remove the previous plan's new large-text Download/Inventory refs, ReadProcessingText, client-streamed large mutations, large canonical-text migration and their special concurrency buffer setting. Existing unrelated archive streams or future bounded search transport are not redefined by this rejection.
- GIN indexes small TEXT/artifact TEXT, not S3 original payloads. Semantic search remains independently authorized and existing large-source processing is not agent raw access.

No full old-plan rewrite is claimed in this design turn; those old large-text/provisioning phases must not be executed.

## Explain item 25 without another subsystem

The restrictions apply only to low-level positional writes/truncate, not ordinary write/edit/append:

- File is 10 bytes; writing at byte 100 leaves a gap. Traditional filesystems fill the gap with zero bytes. PostgreSQL TEXT cannot store NUL, so that gap-write is unsupported.
- File is 10 bytes; truncate to 100 grows it with zero bytes, so that growth is unsupported. Shrinking remains supported.
- A byte operation cutting a UTF-8 character in half is invalid; ordinary string edit avoids that issue.

Do not add padding emulation or a second byte store. Keep honest Mirage errors for those uncommon operations, as already agreed for unsupported library/backend behavior. The user accepted this exact limitation after the zero-padding explanation.

## Engine and lifecycle changes

Keep the six Leta-service Workflow types, Local/regular principle, per-agent LangGraph runner, independent inbox/HITL/schedule behavior, bounded Temporal history and accepted replay trade-offs. No new generic workspace-resource Workflow.

Create Leta: authorize workspace.create_leta; save root resource/config/home identity; publish resource relationship and provision ordinary home/default scope access through the owning service boundary; activate/start AgentWorkflow. No user/account creation, profile sync, AddAccount or member slot.

Delete Leta: close admission, cancel schedules/settle HITL, stop root/Leti runtimes, remove that resource's received scope grants and archive resource/history/files as selected by the existing lifecycle. No user deletion or membership removal. Retained home read is still governed by creator membership through the resource relation. No special creator-leave workflow is added.

Workspace deletion must enumerate/stop its Leta resources before storage teardown, using the existing deletion orchestration and an explicit Leta service boundary. Do not rely on membership enumeration now that Leta is not a member. This is required integration work; no background reconciliation process is proposed.

Remove ensure_leta_account, ensure_leta_membership, leave_leta_workspace and account-name synchronization from the old Activity map. Replace their actual storage/access work with narrow resource-home/access operations; detailed Activity boundaries are to be revised after this direction is accepted. Do not retain obsolete Activities just to preserve the old count.

Resource approval: requester can be Leta/Leti; exact human personal-scope owner approves; recipient of viewer/editor is leta:L. Response enters the exact requester inbox. Acceptance grants access only, not a held tool execution. Ask-user forms remain addressed to creator, with the existing active-workspace visibility rule. No computer provisioning or broader request kind is added.

## Deletion/change inventory

| Surface | Remove | Change/keep |
| --- | --- | --- |
| Identity SQL/profile | Agent account rows/model, type, owner_id, owner index/FK | users with required Clerk ID; preserve human UUIDs/profiles |
| Identity API/Temporal | Managed creation/profile-owner routes, AccountChanges/StartManaged, identity tuple publication | Human onboarding/me/summary/email paths |
| Workspace SQL | Old proposed managed_owner_id/backfill/single-workspace constraints and bot membership rows | Human user_id memberships; existing roles/personal scopes/idempotency_keys |
| SpiceDB | account/self/owner and bot workspace-member tuples | user, workspace resources, leta resource relation and direct scope grants |
| Shared auth/native | Hardcoded account subject, ambiguous human/bot actor assumption | Closed user/leta subject support and trusted service/method checks |
| Leta schema | Account-ID equality, owner_account_id, membership/leave keys | Root workspace/creator/home scope; existing runtime domain tables |
| HITL | Account grantee/agent-membership validation | Human approver, Leta grantee and exact workspace-resource binding |
| LetFS | Previous proposed large canonical text/ingest stream extension | Small TEXT native hooks, blob/artifact path, scope root checks; private scope candidates listing |
| UI | Bot as member/account profile | Workspace agent resource profile; generic user accessible-scope browser |
| Operations/contracts | Obsolete managed-account authz/rebuild fixtures and method allowlists | Generated clients/claims/headers/recovery/docs and coordinated schema verification |

## Rollout and verification boundaries

Before an actual persistent change, back up using the existing recovery route and inspect real rows. Human rename preserves UUIDs and existing member/scope mappings. If agent account rows exist, do not silently drop them or coerce them into humans; inspect their actual workspace/resources and explicitly map or remove them as authorized. No speculative conversion engine/backfill project is proposed.

The old account/scope plan is completed historical implementation context, not authority to keep managed accounts against this new instruction. The pending Leta plan is superseded for provisioning/identity/storage and must be rewritten after review, not patched with two conflicting models or implemented unchanged.

Required future checks: human onboarding/identity contract, user/leta subject isolation, active creator resource access, default home/shared grants, resource-owner approval/revoke, Leti subtree restriction, user+Leta scope discovery, inline/blob boundary, deletion/workspace deletion and existing engine journeys. No tests/migrations/provider calls or live data changes were performed while writing this report.

## Accepted confirmation and next review

The user approved all ten redesign points, including human-only users, the shared agents runtime table, independent leta:L subject, creator-gated resource/home access, generic accessible-scope API, Leta-grantee HITL, inline TEXT versus large blob storage and removal of account/membership lifecycle work. Use model_id and reasoning_effort consistently, including inherited Leti configuration and catalog choices. No separate naming layer for these fields is permitted.

The subsequent “ok chot” accepts the zero-padding limitation as explained: ordinary edits/appends are supported, but no zero-filled gaps/growth in TEXT. Do not reopen that limitation or add a workaround subsystem.

The obsolete account-based 18-phase plan still needs a coherent rewrite after this remaining review; status banners deliberately prevent execution of old provisioning/large-text phases. Naming has been normalized in the old plan's retained Markdown, but this does not make its superseded architecture current.

The original inventory remains available at ../261108-0001-leta-agent-engine/reports/design-additions-review.md. Its artifact-namespace and command-specific backend recommendations are superseded by the latest feedback below.

## Latest review: items 27–34

| Item | User disposition |
| --- | --- |
| 27 | Accepted correction: artifacts are ordinary child file/nodes. Access through absolute source-file path plus artifact relative path, or /@<original-file-id>/<artifact-relative-path>. No separate artifact ID concept, required child-ID addressing or /artifacts namespace. |
| 28 | Accepted on-demand bounded image previews/read_file behavior and stated initial format limits. This does not require a separate preview path namespace; read_file can request the preview of the source image. |
| 29 | Accepted current permission/fingerprint checks for Redis cache hits. |
| 30 | Explicitly accepted: LetFS owns native data APIs; adapter implements Mirage hooks; Mirage owns commands. No command-specific backend behavior. |
| 31 | Accepted actual-query/default-planner GIN verification. |
| 32 | Accepted HITL edge rules under the resource model; human resource owner grants to Leta. |
| 33 | Accepted native second-precision schedule conversion and described update limits. |
| 34 | Accepted one-shot edits: metadata/pause changes do not rearm; an explicit new time/spec can schedule a new occurrence. |

### Corrected artifact addressing — user-confirmed

- Artifacts are ordinary file/directory nodes below their original source file. Each has the existing node/file ID; there is no separate artifact-ID entity or ID type. Preserve parent_id, the actual hierarchy and backend readonly provenance.
- Canonical agent paths retain the source and relative artifact path: `/shared/docs/report.pdf/report.md` or `/shared/@<original-file-id>/report.md`, and equivalent paths under home or an approved user mount. Nested artifact directories remain part of that relative path. No child ID is needed to read an artifact.
- Blob metadata returns the existing nested artifact tree and those usable paths. Do not replace them with mandatory direct child-node aliases, a separate /artifacts hierarchy or synthetic preview directories. Original blob bytes/S3 URLs remain unavailable through agent filesystem reads.
- The native resolver already traverses children beneath file nodes. Preserve this requirement at the Mirage adapter boundary; test both named and original-ID-prefixed paths. Library source inspection does not establish a passed end-to-end file-parent traversal test. Do not invent a namespace workaround merely to avoid that test; if actual pinned runtime behavior blocks it, report the concrete failure before changing the accepted paths or forking Mirage.
- Normal file kind and source metadata read semantics remain truthful; do not silently pretend every blob is a directory. The adapter integration must reconcile those calls with the accepted native hierarchy using supported hooks.
- Aliases and descendant reads retain current scope authorization, accepted mount-root restriction, liveness/generation and readonly checks. Knowing a source file ID does not escape a Leti's box root.
- Bounded image preview remains a read_file operation, not an extra hierarchy. Remove obsolete sibling artifact mounts/projection-only configuration from the later rewritten plan.

### Verified evidence and implementation boundary

- `apps/letfs/internal/filesystem/paths.go::nodeAlias` (line 23) recognizes @UUID, and `session.resolve` (lines 105–108) applies it at the scope root. Its recursive query checks live ancestry and computes artifact_readonly from file ancestry (lines 119–137).
- `apps/letfs/internal/filesystem/paths_integration_test.go` creates report.md under report.pdf and explicitly resolves the child file by its ordinary node ID, then asserts ARTIFACT_READ_ONLY (lines 41 and 58–60). This is an existing test's source, not a test executed in this turn.
- Pinned Mirage 0.0.8 source: `mirage/types.py::PathSpec` exposes mount-relative vfs_path/mount_path; `mirage/utils/key_prefix.py::mount_key` strips the mount prefix; `mirage/workspace/mount/mount.py::_keyed_paths` passes backend keys. The library does not require the proposed /artifacts namespace or prohibit an @UUID literal component. Alias semantics belong to the custom LetFS adapter/backend.
- `mirage/vfs/base.py::files_containing` and `lines_containing` document literal candidate/line contracts. Fulfill those contracts through generic LetFS text data APIs. Library-owned command behavior is not a separate Openlet product decision or LetFS concern.
- Current documentation lookup through Context7 resolved /websites/mirage_strukto_ai and confirmed the custom VFS stat/read/readdir boundary. Pinned release source is the version-specific evidence; no real Mirage–LetFS adapter test ran here.

## Final accepted review: items 35–42

- 35: pause stops future production; already admitted delivery may finish; delete checks current source/target and never retracts committed inbox input.
- 36: no public calendar pagination in MVP. Query a bounded date range and return the complete sorted result or a clear request-too-large error requiring a narrower range/filter. Internal native matching-times continuation may be necessary for its 1000-result cap; it is not a product cursor. Default 31 days, max 366 and result/request bounds remain tunable.
- 37: actual chat and public activity remain typed distinct records; owner box APIs use the same domain operations. No prompt parsing, global cross-agent commit sequence or bot membership.
- 38: ordinary disconnect does not delete unfinished text. Worker keeps writing Redis; reconnect uses Last-Event-ID to replay after the last received cursor. Only expired/trimmed/lost data requires explicit PG reset; committed history is preserved, provisional tokens outside available replay are not guaranteed. Do not discard a valid cursor solely because a connection restarted.
- 39: replace per-run Redis streams and PG discovery polling with one stable Redis Stream per Leta, including root and all Leti events. Each event carries agent_id/run_id and an AG-UI payload. One SSE connection covers the complete Leta; API waits using XREAD BLOCK. Route to separate agent/run UI state. No WebSocket requirement or second event bus.
- 40: Redis is required. Startup/readiness requires it; do not implement optional/degraded startup or a cache-bypass subsystem. Redis still is not canonical product/permission history. A stream publication outage must not replay already applied tools/domain effects.
- 41: accepted tunable infrastructure values remain, excluding superseded large-text buffers, periodic runner segmentation, PG polling and public calendar pagination. Replay cap now applies per Leta stream, not per run: initial 24h touch TTL, 8MiB payload/20000 events. No Redis semaphore or custom distributed SSE connection quota. Use ordinary server/gateway connection limits and bounded per-connection output buffering. The old 32-agent subscription selector is unnecessary when one stream covers a Leta; do not impose a 32-Leti product limit.
- 42: extend existing Compose/bootstrap/migration/gateway/CI/recovery. One API/worker image, dedicated Leta DB/checkpoints, private required Redis. Back up durable state/model config, discard Redis during restore and explicitly reset old cursors. No new platform or scheduler deployment.

Coalescing remains at the API SSE proxy, after Redis. Merge only adjacent compatible text/tool-argument deltas with the same agent/run/block identity, flush across start/end/custom/identity boundaries, and use the last consumed Redis event ID for the emitted SSE cursor. Redis stores original events; this reduces SSE frames, not Redis writes. Initial 25ms/16KiB flush bounds are operational defaults.

Resource/schema/naming/path constraints and all rejected additions earlier in this checkpoint remain in force. The new full plan must incorporate these decisions directly rather than leave obsolete execution instructions under warning banners. Historical review documents are evidence, not current plan authority.

## Plan rewrite completion checkpoint

The full English [19-phase implementation plan](../261108-0001-leta-agent-engine/plan.md) now incorporates every accepted review above. It includes explicit [phase02 human-user/agent migration](../261108-0001-leta-agent-engine/phase-02-user-agent-migration.md), resource/domain authorization, full LetFS/Mirage integration, the six Workflow/Activity map, HITL, schedules, typed UI/history and stable per-Leta SSE. Obsolete execution phase files were removed; older reviews are explicitly historical. Earlier paragraphs saying the old plan still needs rewriting describe the previous checkpoint state.

Resume from the current plan, design-contract.md, tool-contracts.md and reports/plan-review.md. All implementation phases remain pending. No application source, dependency, schema, database, provider or deployed service was changed. Static document validation does not replace the early Mirage path/factory/saver compatibility gates or later integration/recovery checks. Begin implementation only when requested.

## Accepted native transport simplification

After the streaming/overengineering review, the user approved updating the plan directly without subagents. TextSearch is a bounded unary request–response RPC, returning complete file candidates or intact candidate-line bytes. Explicit output-limit incompleteness returns no partial results and lets the adapter use Mirage's None fallback; real errors remain errors. Remove search framing, chunk reconstruction and completion frames. Mirage's ByteSource/iterator interfaces do not require backend streaming for text read/write/search.

The follow hook serves tail -f by invocation-local polling of unary Stat/ReadText range APIs at the requested interval, ending on command timeout/cancellation. No backend changefeed, follow subscription or streaming RPC. Existing ZIP/blob-transfer streaming and the accepted AI/event Redis–SSE path remain. Removing the existing published StreamArchive RPC is not part of this approval. These changes are incorporated in phases07/08, the shared contracts and index; no implementation has started.
