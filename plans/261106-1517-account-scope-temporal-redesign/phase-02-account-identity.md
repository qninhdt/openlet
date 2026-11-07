---
title: "Phase 2: Account identity"
priority: P1
dependencies: [1]
---

# Phase 2: Account identity

## Overview

Implement independent account identities and the identity wire change across existing services/runtimes. Depends on Phase 1. Workflow registration/orchestration is completed in Phase 4; do not create an alternative identity system meanwhile.

## Requirements

- [x] Account service alone owns type and immutable owner; other services consume account IDs.
- [x] Owners read/update owned accounts without inheriting resource access; no disable or ownership-transfer feature.
- [x] Clerk/Envoy/Go/Python agree on the new claim/header; no dual claim/header support.

## Files and actions

- Rename `apps/account/internal/user/` to `internal/account/`; update every import, fixtures, tests and CLI entry using it. Do not retain a forwarding user package.
- Modify `apps/account/internal/transport/http/{server.go,identity.go}`, `internal/transport/grpc/server.go`, `internal/clients/clerk/client.go`, `internal/config/config.go`, `cmd/server/main.go` and their tests.
- Modify `packages/go/clients/account/{client.go,client_test.go}`, `packages/python/src/openlet/clients/account.py` and platform/client tests.
- Modify `packages/go/identity/{gateway.go,gateway_test.go}`, `packages/go/rpc/{identity.go,authentication.go}` and their Go/Python integration tests.
- Modify `packages/python/src/openlet/{identity.py,rpc.py,authz.py}` and `packages/python/tests/{test_platform.py,test_rpc_wire.py,test_authz_wire.py}`.
- Modify `infra/config/envoy.template.json`, account/workspace/LetFS raw-header extraction, `e2e/fixtures/{boundary-server.ts,api-test.ts,native-grpc.py}`, `e2e/tests/external/clerk.spec.ts` and auth gateway tests.

## Implementation Steps

1. Replace storage/profile/summary APIs and types with accounts. Keep clerk lookup for users only; owner relations use account IDs. Preserve exact-set summary response checks in both service clients and invitation trusted-email checks.
2. Implement the minimum managed-account create/read/update operations; managed-create forces type agent and authenticated actor as owner (neither arbitrary owner_id nor user creation from request body). Account type is immutable, self-owner is invalid, and user identity cannot be reassigned by editing a profile. Creating an agent account adds no workspace, runtime or credential. Summaries retain basic-profile and exact-set behavior; no account status field or disabled-account path.
3. Enforce self/owner read/update at Account's boundary. Owner is assigned at creation and cannot change. Remove proposed disable/status/active-userset wiring and transfer branches, command fields and tests; add no replacement lifecycle mechanism.
4. Limit AccountChanges → ApplyAccountChange to managed-account creation and its SQL/graph publication. Retry creation with the same admitted account identity; do not add a receipt table or expected/prior-owner protocol. Acknowledge success after required graph publication. Profile-only changes stay direct; do not retain a generic command controller for removed/future features or split SQL/graph calls into activities.
5. Rename `openlet_user_id` → `openlet_account_id` and `x-openlet-user-id` → `x-openlet-account-id` across publication, trusted header stripping/extraction, gRPC delegation and Python interceptors. Preserve existing authentication/delegation infrastructure; add no per-service credential design.
6. Remove Account's initial-workspace SQL mapping and old polling-client dependency/config. Keep any credential/client configuration still needed for summary/email RPC callers; remove it only after checking actual references.
7. Keep onboarding completion tied to trusted Clerk metadata plus the durable creation request/result. Repeated onboarding after completion must not recreate a deleted initial workspace after history retention.
8. Update fixtures and wire tests together; fake identity fixtures must still prove untrusted headers cannot forge actor identity. Do not rewrite unrelated historical plans/journals.

## Todo

- [x] Account domain and minimal management endpoints replace old user-specific code.
- [x] Identity/owner graph publication works without resource-right inheritance.
- [x] Claim/header/delegation updated in both runtimes and Envoy.
- [x] Summary/email clients, onboarding identity and fixtures match contracts.

## Success Criteria

User and agent have distinct account IDs in one table; agent account can be managed by owner but cannot impersonate owner or use owner's resources. Account has no disable/status or ownership-transfer surface. Old claim/header cannot authenticate. Profile, summary and verified-email boundaries remain correct. No initial workspace field or old package/client alias remains.

## Verification

```sh
pnpm --filter @openlet/account test
pnpm --filter @openlet/account test:integration
pnpm --filter @openlet/go test
pnpm --filter @openlet/python test
```

Focused cases: immutable owner/type, self-owner, invalid type/Clerk combinations, account A managing agent B without acquiring B's scope rights, summary IDs exact match, agent email invitation refusal, Go/Python unary/stream delegated actor, forged/duplicate old/new headers. Run root/E2E after Phase 4.

## Risk and stop rule

There is no agent login/runtime design in scope. If reliable onboarding completion would require a new persistent mapping beyond the reviewed schema, stop for review; do not restore initial_workspace_id or invent an onboarding registry. Keep the existing trusted Clerk integration and stable creation identity.
