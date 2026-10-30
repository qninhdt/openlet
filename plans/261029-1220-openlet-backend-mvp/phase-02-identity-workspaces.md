---
phase: 2
title: "Identity, Workspaces, and Membership"
status: pending
priority: P1
effort: "5d"
dependencies: [1]
---

# Phase 2: Identity, Workspaces, and Membership

## Goal

Deliver retry-safe Clerk onboarding, unified collaborative workspaces, membership authorization, and manual email-bound invitations on real letfs provisioning.

## Files to Create / Modify

Paths below are relative to `/home/qninh/projects/openlet`; all are planned creations or extensions from prior phases.

- Create: `services/user/migrations/`, `services/user/internal/{user,clerk,http}/`
- Create: `services/user/internal/temporal/{workflows,activities}/`
- Create: `services/workspace/migrations/`, `services/workspace/internal/{workspace,http,user}/`
- Create: `services/workspace/internal/temporal/{workflows,activities}/`
- Modify: `services/workspace/internal/letfs/`
- Create/extend: `contracts/public/openapi.yaml`; modify: `contracts/internal/openapi.yaml`
- Create: focused tests under each owning service

## Data Flow

1. A bootstrap JWT exposes only verified Clerk `sub` to onboarding and caller-scoped status.
2. `OnboardUser` persists a UUIDv7 user and stable first-workspace identity, calls Workspace's idempotent create API and waits with status activities/timers, then publishes backend-controlled `openlet_user_id` to Clerk.
3. `CreateWorkspace` commits workspace and Owner membership, ensures real letfs storage, records opaque IDs, and activates the workspace.
4. The client refreshes its Clerk token; normal routes receive both verified subject and internal ID without per-request mapping.
5. Workspace authorizes from its own live workspace and membership rows on every request.

## Requirements

- [x] Use UUIDv7 for user, workspace, operation, membership-related resource, and invitation IDs.
- [x] Store Owner, Editor, and Viewer in memberships; allow exactly one Owner per workspace.
- [x] Enforce one Owner with a partial unique constraint and lock the workspace before role changes.
- [x] Recheck actor role and target membership inside each membership/ownership transaction.
- [x] Keep workspace-to-bucket/filesystem mapping outside letfs; Rust has no Clerk, role, or workspace logic.
- [x] Publish only backend-controlled `openlet_user_id` and preserve unrelated Clerk metadata; configure/document the environment-specific Clerk session claim mapping so refresh actually includes that field.
- [x] Keep provisioned data when Clerk publication is temporarily unavailable.
- [x] Bind operations to caller, action, target, idempotency key, and request fingerprint.
- [x] Store only invitation token hashes, accept only editor/viewer invitation roles and bind acceptance to verified matching email.
- [x] Do not add an email sender, workspace variants, roles in JWTs, or authorization caching.

## Implementation Steps

1. Add User tables for users and caller-bound operations, including unique Clerk subject and onboarding state.
2. Add Workspace tables for workspaces, memberships, storage mappings, invitations, and operations.
3. Encode one-owner invariants in PostgreSQL and lock the workspace before role checks.
4. Implement `OnboardUser` with durable IDs, Workspace internal HTTP start/status, Clerk publication, and completion.
5. Implement `CreateWorkspace` with first-activity admission, Owner membership, real letfs ensures over internal HTTP, mapping, and activation.
6. Start Temporal before mutation; the first activity atomically admits the caller/fingerprint and initial state.
7. Return 202 only after durable admission; bounded-wait expiry returns 503 and requires the same key.
8. Implement profile, workspace, membership, ownership-transfer, and invitation routes.
9. Add narrow internal User routes for verified email and bounded `{id,display_name,avatar_url}` summaries; never return Clerk IDs, emails or self-only fields in member enrichment.
10. Add OpenAPI and JSON fixtures for identity, roles, UUIDs, errors, and operation status.

## Authorization Matrix

| Action | Owner | Editor | Viewer |
|---|---:|---:|---:|
| Read workspace/members/live files | Yes | Yes | Yes |
| Modify files or trash/restore | Yes | Yes | No |
| Manage workspace/members/invites | Yes | No | No |
| Transfer ownership | Yes | No | No |
| Purge trash/delete workspace | Yes | No | No |

## Test Matrix

| Layer | Evidence |
|---|---|
| Unit | Email normalization, invitation expiry, fingerprints, role decisions |
| Integration | Real constraints, owner races, transfer/remove locking, invite replay/wrong email |
| Workflow | Retry after each commit, Clerk outage, duplicate start, lost response, closed-before-first-admission restart with explicit running-conflict/closed-run reuse policy |
| Contract | Bootstrap restrictions, refresh instruction, stable errors, UUIDv7 serialization |

Use a controllable Clerk HTTP test server at the external boundary. Keep live Clerk as a separate credential-dependent development smoke, required before release and distinctly not-run if credentials are absent; it is not a deterministic CI dependency.

## Planned Verification Commands

```bash
make test-unit SERVICE=user
make test-unit SERVICE=workspace
make test-integration TEST=identity-workspace
make test-workflow TEST=onboarding
```

## Failure Modes and Mitigations

| Failure | Risk | Mitigation |
|---|---|---|
| Concurrent transfers violate Owner invariant | High | Workspace lock, partial unique constraint, invariant recheck |
| Clerk response is lost | High | Field merge and idempotent publication retry |
| Workflow lacks authorized admission | High | First activity persists caller/action/fingerprint and scope |
| Removed member starts a new request | High | Authorize from current DB state every time |
| Invitation token leaks | High | Store hash only and redact links/headers/bodies |

## Rollback

- Disable onboarding/workspace mutations before reverting services.
- Stop new workflows and let admitted work reach a stable checkpoint.
- Preserve users, workspaces, mappings, invitation hashes, and operations; do not orphan letfs storage.
- Revert Clerk claims only through an explicit administrative procedure, never compensation.

## Success Criteria

- [x] First login creates one user, active workspace, Owner, and storage mapping across retries/restarts.
- [x] A refreshed token carries the backend-controlled internal ID; pre-refresh normal routes stay denied.
- [x] Deterministic transfer/remove races never violate exactly one Owner.
- [x] Owner, Editor, and Viewer match the matrix, including Viewer denial from trash.
- [x] Invitation acceptance succeeds once only for the verified email and never exposes its hash.

