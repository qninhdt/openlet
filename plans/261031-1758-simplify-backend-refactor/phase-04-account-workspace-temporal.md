---
phase: 4
title: "Account/Workspace, idempotency receipts, and direct Temporal orchestration"
status: completed
priority: P1
effort: "4–6 days"
dependencies: [3]
---

# Phase 4: Account/Workspace, receipts, and Temporal orchestration

## Goal and mandatory scout

Remove Account/Workspace operations tables, merge workspace_storage into workspaces, and replace workflow-internal HTTP start/poll adapters with child workflows and remote Activities. Apply the [final API/lifecycle architecture](<../261031-1738-refactor-three-notes/inputs/openlet-final-architecture-status-to-processing (1).md>).

Re-scout the moved source before implementation: Account internal/user, http, temporal, clerk; Workspace internal/workspace, http, temporal, letfs, user; Letfs provisioning domain and Temporal registration; gateway routes; OpenAPI and tests. Current onboarding starts Workspace over HTTP and polls status. Current DeleteWorkspace polls individual filesystem deletion. Delete these paths, rather than tuning polling intervals.

## System-wide idempotency contract

| Owner | Mechanism and durable responsibility |
|-------|-------------------------------------|
| Account | clerk_id UNIQUE; provisioning/active user lifecycle; no receipt table for onboarding |
| Workspace | idempotency_keys for workspace creation and genuinely nonnatural mutations |
| Letfs | idempotency_keys for strict create/copy/upload-session/provisioning and manual reprocessing admission without natural identity; completed in phase 5 |
| Workspace filesystem facade | Authorize, resolve filesystem, forward the SAME key; do not duplicate Letfs receipts |
| Temporal | Stable Workflow IDs identify executions; stable logical Activity identities protect repeated effects |

A receipt contains only authenticated caller scope, operation semantics, key, canonical request hash, resource/result or workflow handle, immutable admission input when recovery needs it, and completion/expiry timestamps. It is not execution history, a checkpoint store, a queue, or a progress table.

- Unique scope + operation + key prevents concurrent double admission. Scope comes from authenticated identity and validated resource access, never an arbitrary caller_id in the request body.
- Same key with a different normalized payload returns 409. Define how omitted/default fields and semantically equivalent requests are canonicalized.
- For a database mutation, receipt, business effect, and any quota change commit in the SAME transaction.
- A concurrent in-flight request waits within a bound or receives the documented in-progress/retry response. It must not receive a fabricated success.
- Receipts are retained for **24 hours after logical operation completion**. Do not prune active work. Once TTL expires, an old client key has no guaranteed replay contract.
- A remote provisioning receipt needed by an active parent remains pinned until its result is consumed and resource mapping is durably recorded. An Activity retry after 24h must not create another bucket/filesystem.
- Natural transitions use resource identity, uniqueness, revisions, and terminal-state guards. Move/rename/finalize/abort/delete are not made safe merely by carrying an ID.
- Workflow ID is not exactly-once side-effect delivery. An Activity key must remain stable across retries; if a logical operation crosses Continue-As-New, carry its identity explicitly rather than deriving it only from the changing Run ID.

## Durable admission without a new job framework

1. Commit resource lifecycle or an admitted receipt containing stable workflow ID and immutable start input.
2. Start the workflow immediately after commit. An AlreadyStarted result resolves to the same handle. A temporary start failure must not erase admitted work.
3. Return 202 only when durable admission exists; distinguish accepted/provisioning from an active resource. If admission never committed, return an actual failure.
4. Reconcile pending lifecycle rows/receipts at worker startup and periodically while the service remains healthy. Letfs reuses its existing maintenance schedule. Account and Workspace currently have no equivalent schedule: each registers one small owner-managed Temporal reconciliation workflow/Activity on a native five-minute schedule, with overlap prevention and bounded scans of its own database. This is configuration on the existing Temporal service, not a new scheduler process or generic framework. Start the same logical workflow identity only when reconciliation proves no execution/effect exists.
5. Do not create a broker, dispatch table, generic jobs service, lease service, or another polling daemon. Account/Workspace use their own database state; Letfs uses its own maintenance owner.
6. Resolve terminal outcomes deliberately. Never use AllowDuplicate to blindly restart a workflow that already failed or completed. Preserve failure information required by the API without copying Temporal history into SQL.
7. Before a restart beyond Temporal retention, reconcile against durable completion/resource state. Retention cannot silently turn a completed deletion into resource recreation.
8. Processing admission is owned by file generation state in phase 6; copy admission is owned by its receipt in phase 5. No accepted operation relies on a memory-only start.

## Target orchestration

| Process | Mechanism |
|---------|-----------|
| OnboardUser → CreateWorkspace | Child workflow on Workspace queue, await completion |
| CreateWorkspace → create quota bucket/filesystem | Short remote Activities on Letfs queue |
| DeleteWorkspace → DeleteFilesystem | Child workflow on Letfs queue |
| Freeze/complete bucket and other short internal mutations | Remote Activities at the resource owner |
| Clerk/model providers | HTTP inside Activities |
| Public requests, filesystem facade, processor resources/bytes | HTTP remains the appropriate transport |

Letfs generates bucket/filesystem IDs. Workspace stores returned mappings; it does not allocate Letfs-owned IDs or access Letfs database tables.

Deletion order: mark workspace deleting, freeze its bucket, list bounded pages of ALL filesystems belonging to that bucket, run child DeleteFilesystem for each, then complete bucket/workspace deletion. Include filesystems beyond the primary drive mapping.

All current workers use the trusted openlet Temporal namespace. Activity names, task queues, JSON payloads, error classification, and internal service identity must be explicit. Queue selection is not authorization; worker code must not trust arbitrary public actor/scope values. File bytes stay out of Temporal payload/history.

The security boundary is the existing same-team private deployment control plane: Temporal has no public/host listener, its backend network stays isolated, and untrusted/tenant publishers are prohibited. No per-Activity MAC/capability protocol, custom crypto, or service-token fields in Temporal payload/history. Owning Activities derive authorization-sensitive scope from durable owner state and validate resource identity/lifecycle; facade requests still enforce current user membership. Revisit native Temporal access controls only if this control plane crosses an untrusted/team/namespace boundary; that is not part of this nonproduction refactor.

For admitted destructive work, client disconnect or parent closure must not strand cleanup. Await child start, use a deliberate parent-close policy such as ABANDON where destruction must continue, and handle cancellation through the SDK-supported disconnected/cancellation scope. Onboarding still waits for its child result. Check Continue-As-New against running child lifetimes; never assume default termination is safe.

No Nexus deployment, workflow wrapper per small mutation, HTTP start/get-status polling, or cross-service SQL access.

## Resource API and lifecycle contract

- Public prefix /v1; internal /internal/v1. Use plural resources, typed inputs, JSON snake_case, RFC9457 application/problem+json, ETags and required If-Match.
- Use 201 + Location for completed creation, 202 + Location for admitted async work, 204 for no-body success, 409 for semantic conflict, 412 for revision mismatch, and 428 for missing required preconditions.
- Framework/router changes cannot normalize Envoy's own authentication response automatically. Either normalize at its owner or document the precise gateway exception; never claim universal RFC9457 while leaving that unexplained.
- Keep onboarding/me resource semantics; use workspace POST/GET/PATCH/DELETE, membership resources, and invitation resources from the note.
- Ownership transfer is a workspace PATCH with dedicated authorization/transaction rules, not unrestricted assignment of an owner field.
- Fold quota bucket/filesystem/root IDs and storage limit into workspaces. Incomplete mappings are allowed during provisioning; lifecycle checks prevent premature access.
- Use resource-specific status CHECK constraints, not a global status enum. Do not add status columns to nodes/files merely to copy Temporal execution state.
- Workspace reads expose provisioning/deletion lifecycle. No operations API remains. File copy monitoring is a small Temporal-backed read adapter in phase 5, not a new database entity.
- Client-side polling of resource readiness remains valid. The removed polling is workflow-to-service orchestration.

### Invitation contract

Enforce one pending invitation per workspace/normalized email under concurrency. Store the token hash only. Return plaintext only on the first successful creation response; a retry returns existing invitation metadata without the token. A lost plaintext token requires revoke/recreate, not reversible token storage or an email feature.

Retain expiry checks, verified-email matching, accept/revoke terminal guards, membership uniqueness, and authorization after membership removal. Do not add email delivery.

## File inventory

| Action | Target files/group | Size | Test impact |
|--------|--------------------|------|-------------|
| Modify/delete | apps/account/internal/user, http, temporal, clerk | Medium | Natural onboarding, child result, Clerk retries |
| Modify/delete | apps/workspace/internal/workspace, http, temporal, letfs, user | Large | Receipts, storage merge, roles, deletion |
| Modify | account/workspace migrations/0001_initial.sql | Medium | No operations/workspace_storage; receipt constraints |
| Modify | Letfs provisioning functions and remote Activity registration | Medium | Resource ownership and Go↔Rust serialization |
| Modify | contracts, Envoy routing, new API E2E, native tests | Medium | All affected callers use the target API |
| Update | Owning data-model/API/workflow docs and existing DBML | Medium | Read documents first; describe only completed behavior |

## Implementation steps and checklist

- [x] Enumerate every operations/workspace_storage SQL query, DTO, handler, Activity, and caller. Map each required responsibility to a receipt, resource field, or Temporal history before deleting it.
- [x] Edit baselines, domain transactions, lifecycle checks, and constraints. No upgrade migration, legacy schema branch, or renamed generic job table.
- [x] Implement natural Account onboarding and Workspace receipt admission. Preserve Clerk metadata merge and refreshed-session behavior.
- [x] Implement resource-oriented Gin handlers, invitations, memberships/ownership, errors, and ETags together with contracts and facade callers.
- [x] Register child workflows and named remote Activities with explicit task queues, compatible payloads, deadlines, retryable/nonretryable errors, and stable logical identities.
- [x] Implement durable start reconciliation and receipt completion/TTL pinning. Cover commit-before-start and effect-before-lost-ack boundaries.
- [x] Replace internal orchestration HTTP clients and polling Activities. Delete unused methods, old operation handlers/types/SQL and dependencies in the same change.
- [x] Produce new owner-managed workflow replay fixtures for the target definitions where SDK-supported. Do not preserve old workflow versions for compatibility.
- [x] Make identity/workspace API E2E green. Run native integration for races/roles/TTL/isolation and real Temporal Go↔Rust registration/payload behavior.
- [x] Update owning docs, contract references, and DBML after verifying source; do not mark unfinished phase-5/6 behavior as current.

## Validation matrix

| Risk | Meaningful proof |
|------|------------------|
| Repeated/concurrent onboarding | Same user/initial workspace; Clerk identity unique |
| Same-key workspace create and lost response | One workspace/storage mapping; replayed handle |
| Same key/different payload | 409 without another effect |
| DB commit before Temporal start | Real crash/restart resumes the admitted resource |
| Committed admission, Temporal start fails while service stays alive | Owner schedule dispatches the intent after Temporal recovers, without a service restart |
| Activity committed, response lost, retry after 24h active parent | Existing resource returned; receipt not prematurely pruned |
| Cross-language Activity/child workflow | Real worker registration, JSON result/error mapping, no HTTP poll |
| Cancellation/parent close during delete | Admitted deletion continues to durable outcome |
| Extra filesystems in bucket | Workspace deletion removes all owned filesystems |
| Invitation/role/owner races | Native DB transactions reject privilege/lost-update violations |
| Terminal workflow or expired history | No blind duplicate execution or resource resurrection |

## Acceptance, risks, and recovery

- [x] Account has neither operations nor an onboarding receipt table.
- [x] Workspace has no operations/workspace_storage and no internal HTTP start/poll loop.
- [x] Concurrent retries create one resource set, correct TTL behavior, and explicit conflicts.
- [x] Admitted work survives start gaps/restarts; deletion cannot recreate a tombstoned resource.
- [x] Native checks, actual cross-language Temporal integration, and identity/workspace API E2E pass.

SQL and Temporal have no distributed transaction; reconciliation is required, not an exactly-once claim. Verify cancellation/serialization with actual SDKs. If registration fails, repair the contract instead of restoring polling. Recover by reverting the phase and restoring the correct database backup when state was reset; do not keep dual schemas.

Next: [phase 5](./phase-05-letfs-schema-file-lifecycle.md).

References: [Child workflows](https://docs.temporal.io/child-workflows), [task queues](https://docs.temporal.io/task-queue), [Activity idempotency](https://docs.temporal.io/activity-definition), [RFC9457](https://www.rfc-editor.org/rfc/rfc9457).

## Current implementation checkpoint

The Account/Workspace schema, lifecycle, receipts, public handlers and direct Temporal orchestration are implemented. Workspace has no operations or workspace_storage table. Its create admission commits before dispatch; Letfs returns owner-generated storage IDs through named Activities. Mapping is durable before remote receipt release; the create receipt completes only after release, and the existing reconciliation workflow recovers that gap. Natural deletion is admitted by an owner/revision-checked resource tombstone, without a request receipt or SQL cursor.

A failed provision can be deleted even if its storage result was lost: the Letfs owner resolves or creates a frozen owner-keyed bucket tombstone, fences late provisioning, deletes all remaining filesystems and releases partial receipts. A terminated deletion resumes only after checking both the durable deleting lifecycle and an explicitly closed Temporal execution. Recovery uses separate child execution IDs with the same logical deletion key; already-deleted filesystems are omitted from frozen-bucket enumeration. No additional execution-state table or scheduler was added.

Verification includes 10 passing gateway/onboarding/Workspace/deletion E2E cases, plus a passing real Temporal-outage/schedule-dispatch case. Fresh Go Account/Workspace and Rust filesystem-child histories replay. Native PostgreSQL tests cover admission concurrency, payload conflict, receipt pin/completion/expiry, mapping guards, failed-resource deletion, roles and invitation races. Rust integration proves owner-generated retry identity, scope rejection, receipt lifetime, partial cleanup and late-provisioning fences.

The invitation journey now passes through the resource-node API: viewer writes are denied, removing membership hides file resources, and replaying an accepted invitation cannot rejoin. The direct ZIP/invitation gateway run passed 2/2. Together with the earlier identity/Workspace/deletion/outage runs and current native/replay evidence, phase-4 acceptance is complete. Additional provisioning-release response-loss and extra-filesystem failure injection remain identified validation limits; active remote-release recovery has native owner-state coverage. File copy/status adapters remain phase-5 work.
