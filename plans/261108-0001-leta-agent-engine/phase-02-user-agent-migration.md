---
title: "Phase 02: Human-user identity and agent migration"
status: pending
priority: P1
dependencies: [1]
---

# Phase 02: Human-user identity and agent migration

## Outcome and current execution boundary

Replace mixed accounts with human-only users. Leta is a workspace resource, never a user, member or login. Remove managed-account HTTP/store/Temporal behavior and graph account self/owner relations. Change canonical schemas, callers, generated contracts and tests together.

The user explicitly authorized implementation with no production data, no backup requirement, no backward compatibility, and no retained legacy/dead code. This supersedes the previous production migration/preflight/Clerk rewrite runbook. Update initial SQL and fixtures directly; do not add transitional schemas, conversion CLIs, legacy headers, compatibility workflows or snapshot gates. Do not reset an unrelated running development environment. Real tests own fresh disposable dependencies.

Keep physical apps/account, database/deployment names, ACCOUNT_RPC_ADDRESS and the AccountService descriptor; these identify infrastructure. Domain/public names become users, user_id, UserSummary and GetUserSummaries.

## Read first and caller scope

Consult CodeGraph before indexed code. Inspect these actual owners and all callers/tests of the symbols being changed:

- apps/account/migrations/0001_initial.sql; internal/account/{store,service,relations}.go; internal/temporal/workflows.go; cmd/server/main.go.
- apps/account/internal/transport/{http,grpc}; internal/clients/clerk/client.go.
- apps/workspace/migrations/0001_initial.sql; internal/workspace/{store,service,membership,invitations,relations,authorization}.go; transport and Temporal callers.
- packages/go/{identity,rpc,authz,clients/account}; packages/python/src/openlet/{identity,rpc,authz}.py and clients/account.py.
- apps/letfs/internal/filesystem/authorization.go and actor-bound upload/idempotency/copy/transfer checks.
- packages/contracts/{proto/openlet_api/account/v1/account.proto,authz/schema.zed}; scripts/contracts/generate.py; infra/config/envoy.template.json.
- Shared/service tests, scripts/bootstrap, scripts/operations/recovery.py, e2e fixtures and current docs/OpenAPI/DBML.

## Fixed target contracts

### Humans

users has exactly id UUID PRIMARY KEY, clerk_id TEXT NOT NULL UNIQUE, display_name, avatar_url, created_at and updated_at. Preserve profile validation and UUID behavior. Remove type, owner_id, mixed-shape checks and owner indexes.

Workspace membership/invitation columns become user_id and accepted_user_id. Human personal scopes and ordinary roles remain. Keep generic mutation ActorID/TargetID where appropriate; there is no need to rename an identifier that already describes the correct concept.

Keep /v1/me, GET/PUT /v1/me/onboarding, bounded summaries and verified-email lookup. Self-profile checks current verified user and local existence. Remove managed creation/get/update routes, ManagedCreation/CreateManaged/ApplyAccountChange, AccountChanges/StartManaged and registrations. No success stubs or graph self/owner rebuild remain. Human onboarding still creates its initial workspace once through ordinary Temporal retry semantics.

Within the existing proto package use UserSummary, GetUserSummaries and response users; email request user_id. Summary tags 1–3 and batch bound 100 remain. Generate Go/Python outputs from canonical contracts; never edit generated source manually. Exact response-set checks remain.

### Identity and authorization

Human Clerk metadata/JWT claim is openlet_user_id. Gateway strips untrusted identity headers and injects x-openlet-user-id. Public callers cannot assert Leta.

Native actors are the closed pair (kind user|leta, UUID), independent of service credential and Clerk subject. Mutually exclusive x-openlet-user-id/x-openlet-leta-id carry this pair. Reject duplicates, both headers, malformed/nil UUIDs, legacy account headers and spoofed service headers. Gateway credentials accept humans only. Actor-free service calls remain actor-free. Admit Leta only through explicit service/method allowlists; generic delegation cannot admit it accidentally.

Go/Python Check/BulkCheck emit the actor's actual object type. Change all callers. Retain actor kind in operation ownership wherever a UUID is persisted or compared, so identical human/Leta UUIDs never share uploads, transfers or idempotency ownership. Preserve ordinary error/cancellation/deadline behavior.

Final SpiceDB policy: empty user definition; human workspace/filesystem subjects; workspace.create_leta; leta.workspace/creator; creator membership-gated read/manage; scope.home_of: leta and viewer/editor admitting Leta. Scope managers remain human/workspace usersets. Home read includes home_of->read. No account type/self/owner tuples or bot role/membership remains. Phase04 owns home/default/grant operations; phase03 owns Leta relationship publication. Normal schema startup still rejects a mismatched policy.

## Implementation checklist

- [x] Inventory affected handlers, schemas, durable fields, actor-bound stores, callers and fixtures with CodeGraph/source.
- [x] Replace initial human/member schemas and fixtures; remove actual managed store/API/workflow behavior and graph self/owner publication.
- [x] Rename human summary/email DTOs and shared clients; generate outputs and update exact method allowlists.
- [x] Update Go/Python typed native actors, gateway/Clerk claim and headers, authz callers and actor-bound storage checks together.
- [x] Install final canonical user/Leta policy, generated actions/matrix, and shared authorization tests.
- [x] Update service/E2E/bootstrap/recovery callers and owning docs; remove obsolete identity-specific rebuild steps without removing existing general recovery functionality.
- [x] Run focused tests, real isolated SQL/SpiceDB/native transport checks and affected build/contracts/E2E type checks.

## Validation

Run the narrowest relevant tests while changing each boundary, then:

```sh
go -C packages/go test ./identity ./rpc ./authz ./clients/account
go -C apps/account test ./...
go -C apps/workspace test ./...
go -C apps/letfs test ./...
uv run --locked --package openlet-python pytest packages/python/tests -q
pnpm contracts:generate
pnpm contracts:check
pnpm --filter @openlet/account check
pnpm --filter @openlet/workspace check
pnpm --filter @openlet/python check
pnpm --filter @openlet/account test:workflow
pnpm --filter @openlet/workspace test:workflow
pnpm check:e2e
```

Use actual app-owned integration targets for fresh PostgreSQL/SpiceDB and transport proofs. Check human onboarding/profile isolation; removed routes; invitation/grant/revoke behavior; malformed/spoofed headers; exact Leta admissions; same-UUID subject separation. No legacy-data conversion or old-history replay promise is made.

## Acceptance and handoff

- [x] Human schemas, claims, headers, DTOs, generated clients and fixtures agree; no managed account behavior remains.
- [x] Native actor kind survives authorization and operation ownership; Leti has no subject.
- [x] Final graph has no account policy/tuples; default schema initialization remains fail-closed.
- [x] Focused and real-boundary checks pass; phase04 receives typed actors/human summaries/final policy.

## Rollback

Before deployment, revert only owned code/schema/config changes if necessary. Tests remove only their own disposable dependencies. Do not add a production migration subsystem for this development-only rewrite. General Leta recovery integration remains in phase18.
