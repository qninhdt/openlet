# letfs boundary review

Status: reviewed target plan; application implementation is unchanged. Latest user decisions remove all provision keys and business-owner mappings/projectors from letfs. This record supersedes earlier review recommendations that assigned those relationships to letfs.

## Evidence and disposition

| Concern | Evidence | Target disposition |
|---|---|---|
| Business inheritance stored/projected in letfs | Earlier architecture ownership and Phases 4/5 assigned bindings, intents, projector and rebuild export to letfs. Workspace already persists filesystem/bucket/root references in `apps/workspace/internal/workspace/store.go:151`; its workflow commits them before releasing storage receipts (`apps/workspace/internal/temporal/workflows.go:87`). | Removed from letfs. Workspace persists canonical references and owns native relationship synchronization, revocation and graph rebuild through Temporal. The later authorization correction removes SQL graph intents and acknowledgment framework. The relationship still exists in SpiceDB; letfs checks the filesystem ID directly. |
| Workspace-specific provisioning contracts | `apps/letfs/src/temporal/provisioning.rs:16` registers Workspace-named Activities; `apps/letfs/src/fs/provisioning.rs:29` accepts workspace IDs and derives workspace keys. Phase 5 previously required preserving these contracts. | Generic ID-based bucket/filesystem creation, release, freeze, enumeration and deletion completion. Workspace retains its parent workflow. Both callers and workers switch together in Phase 6. No workspace ID or business resource type/ID in target letfs contracts. |
| Provision key used for idempotency, ownership and late-write fences | Unique columns in `apps/letfs/migrations/0001_initial.sql:58` and `:112`; `fs/provisioning.rs:140` uses stable keys to freeze even when creation result was lost. The existing receipt-expiry test is `apps/letfs/tests/integration.rs:1278`. | Remove provision columns/constraints/contracts. Caller persists bucket/filesystem IDs before remote calls; existing idempotency receipts and immutable resource identity handle retries. Retain primary keys and lifecycle tombstones; generic freeze accepts the preallocated ID to reject late create. IDs/keys never authenticate. |
| Product mount conventions embedded in storage | Workspace injects `/drive` into request scope (`apps/workspace/internal/http/files.go:66`); letfs's current generic resolver validates longest boundary match (`apps/letfs/src/fs/paths.rs:37`). Earlier plan did not assign mount-context ownership clearly. | Integration chooses labels and descriptors; letfs retains generic bounded resolution, ancestry and target-FS checks. No lookup of Workspace mounts, no hardcoded `/drive` discovery, and no business-owner mapping. Aliases never grant access. |
| Whole-bucket authority inferred from one filesystem | Current Workspace usage handler authorizes Workspace, looks up its bucket and calls letfs (`apps/workspace/internal/http/files.go:73`). Earlier Phase 6 left the direct route/permission unresolved. | Direct generic quota-bucket usage with its own bucket read action. Workspace owns bucket references/permission projection and quota policy; letfs enforces numeric limits/accounting. An FS grant cannot expose siblings or grant bucket administration. Remove the old usage relay. |
| Workspace role knowledge in letfs | Current proxy forwards `X-Workspace-Role` (`apps/workspace/internal/http/files.go:156`). The prior plan already assigned removal at cutover. | Preserve that removal. letfs uses explicit filesystem actions such as copy inspect-any, plus local initiating-actor constraints. Repository policy loaded into SpiceDB defines which role grants each action; Workspace owns membership role assignments. |
| Hardcoded business credentials/readiness | Current letfs loads a Workspace-specific service token (`apps/letfs/src/config.rs:174`). | Generic authenticated service principals and method scopes replace special Workspace authority. letfs readiness checks its own dependencies and expected graph schema, never calls Workspace/Account or waits on a per-resource owner projection. Resource access denies until its graph permission exists. |

## Responsibilities retained in letfs

- User/service/job authentication and SpiceDB checks on actual filesystem or quota-bucket IDs.
- Actor-bound uploads, immutable job generation/attempt authority, artifact restrictions, revision checks and local lifecycle guards.
- Tree/path resolution, quota accounting, inline bytes, signed S3 descriptors, copy/trash/purge/ZIP and its own ingest/search pipeline.
- Its own idempotency/resource state, maintenance and processing dispatch/reconciliation. These are not authorization binding projectors.

The reviewed target has no required outbound Workspace/Account/Leti client, cross-owner SQL, owner-domain import, membership cache, role evaluator or owner-domain event subscription. Generic filesystem-to-bucket and node-to-filesystem associations are local storage structure and remain necessary.

## Failure and trust boundaries

Storage creation succeeds independently from owner authorization publication. A publication gap denies access and is repaired by the owning service's Temporal work/reconciliation from canonical references. Workspace completion follows successful relationship synchronization, without SQL graph intents or acknowledgment ledgers. A local frozen/deleted storage row denies access even if graph cleanup is delayed. Restore graph inheritance from the owner's canonical references/tombstones, while restoring letfs storage independently.

Authenticated backend services remain in the accepted trusted backend boundary. This plan does not claim that broad OSS SpiceDB credentials or method allowlists isolate a compromised service from every other backend. Public users cannot call lifecycle/ingest methods or forge delegated actors. IDs and idempotency keys do not establish authority.

## Verification scope

Reviewed current source with CodeGraph followed by targeted source/schema/test reads, then updated architecture, all seven phases and the verification matrix. No application tests, migrations, infrastructure boot or runtime security guarantees were exercised. Implementation acceptance must prove generic callers, receipt expiry/lost acknowledgments/late create, foreign FS/bucket denial and absence of owner-domain clients/contracts.

## Other application boundaries

The follow-up source/target review found no additional required boundary redesign. This conclusion concerns the reviewed contracts, not a claim of runtime security verification.

| Dependency | Finding and execution invariant |
|---|---|
| Account to Workspace during onboarding | `apps/account/internal/temporal/workflows.go:77` calls Workspace's public durable creation contract and stores only the resulting initial workspace reference. Workspace still owns workspace creation, membership and storage policy. Keep orchestration in Account; no new coordinator service is needed. Account does not query Workspace tables or reproduce its role rules. |
| Workspace to Account for profiles/email | `apps/workspace/internal/http/collaboration.go:43` requests bounded profiles; `:181` obtains verified emails before Workspace evaluates invitation rules. Account owns Clerk identity/email verification; Workspace owns membership/invitation authorization. Calls become gRPC. Account must not receive Workspace roles to decide membership. |
| Onboarding dependency cycle | Workspace creation currently performs no Account profile/email callback. Preserve this: initial creation accepts the authenticated internal onboarding contract without calling active-only Account profile/email endpoints or waiting for completed Account onboarding. Otherwise the parent would wait on a child waiting on its parent. This is orchestration/order discipline, not a reason to merge domains. |
| letfs to ingest and back | letfs owns processing generation, outputs and publication. Python workers execute parsing/enrichment/indexing and call scoped letfs APIs; they do not query domain databases or decide memberships/roles. This is the same filesystem pipeline split by runtime/CPU needs. |
| Infrastructure/shared packages | PostgreSQL database credentials are per owner; no cross-service SQL/FKs. Existing Go app imports remain within their own app. Target shared packages contain generated contracts and infrastructure, no app-internal repositories/domain rules. Envoy authenticates/routes, while resource operations authorize at their owning service. |

No additional coordinator, user replica, role cache, Access proxy or business-event platform is required by these findings. Target implementation must still remove the inventoried legacy filesystem proxy, provision keys, Workspace-specific letfs contracts/credentials and role headers.
