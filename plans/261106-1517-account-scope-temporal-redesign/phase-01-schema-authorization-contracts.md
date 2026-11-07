---
title: "Phase 1: Schema, authorization and contracts"
priority: P1
dependencies: []
---

# Phase 1: Schema, authorization and contracts

## Overview

Replace the fresh-install SQL/authz/API contract with the exact [reviewed model](design-contract.md). Source inventory: [evidence](source-evidence.md). Do not run migrations or reset any database while writing this plan.

## Requirements

- [x] SQL fields/constraints match the contract; no quota bucket or additional registry/progress/role table.
- [x] Authorization has exactly the approved resource/action pairs and fixed role behavior.
- [x] Public/protobuf/SDK contracts express filesystem+scope and account identity without old aliases.

## Files and actions

| Action | Existing owner |
|---|---|
| Rewrite fresh schema | `apps/account/migrations/0001_initial.sql`, `apps/workspace/migrations/0001_initial.sql`, `apps/letfs/migrations/0001_initial.sql` |
| Preserve inline-only schema | `apps/letfs/migrations/0002_inline_text_only.sql` and `apps/letfs/internal/testfixture/postgres.go`; retain the existing chain instead of deleting user work |
| Replace graph policy | `packages/contracts/authz/schema.zed`, `roles.json`, `action-resource-matrix.md` |
| Update contract sources | `packages/contracts/proto/openlet_api/{account,workspace,letfs}/v1/*.proto`, `packages/contracts/public/openapi.yaml`, `packages/contracts/openapi-base.yaml`, `packages/contracts/rpc-surface.md` |
| Update generator first | `scripts/contracts/generate.py`, `scripts/contracts/test_generate.py` |
| Update authz contract readers | `packages/go/authz/{actions.go,client.go,contract.go,schema.go,policy.go}` and associated tests; `packages/python/src/openlet/{authz.py,_authz_actions.py}` |
| Regenerate; never hand-edit outputs | `packages/go/gen/openlet_api/`, `packages/python/src/openlet_api/`, `packages/contracts/generated/letfs.openapi.json`, generated action files |

Brace/glob notation denotes files under the stated existing owner; new APIs/messages are proposed changes, not claims that those symbols already exist.

## Implementation Steps

1. Read current diffs before editing. Keep `inline_text_only` validation/default/fingerprint behavior. Change baseline DDL only; do not add conversion migrations for nonexistent old data. Retain the existing inline-only migration and adjust it only if the fresh chain needs it.
2. Replace users with accounts, add reviewed type/owner constraints without account status, remove initial workspace FK. Convert workspace membership/invitation identifiers and add inactive/personal mapping. One-active-owner index and transaction invariants remain; remove workspace revision/provisioning fields and workspace-count policy.
3. Move byte counters/limit to filesystems, create scopes and scope roots, replace node ownership/FKs/uniqueness. Update uploads/trash/cleanup identity and indexes. Keep file payload/generation, upload sessions, receipts and cleanup evidence. Cleanup references must survive logical deletion; do not cascade them away.
4. Replace graph user/quota_bucket/role/role_grant definitions and global role-policy initialization. Encode roles in resource relations. Use account subjects directly; remove account:disable/account#active and all account-status gating. Remove ownership-transfer actions and contracts. Establish no inherited private-content rights from filesystem/workspace administration.
5. Use resource/action pairs in Go/Python validation and generation. Remove globally unique action assumptions. Retain same-resource check inputs for Check/BulkCheck and do not add API-specific permissions.
6. Remove Mount/PathContext/path_context/mount_path and bucket services/messages/routes. Add scope-aware request/response fields; keep Locator/cwd/expected identity semantics. Specify two scopes for cross-scope copy; keep filesystem identity explicit and validate their parent filesystem.
7. Replace user summaries/verified-email IDs with account naming; agent email lookup returns no verified emails. Return basic profiles for requested existing accounts with exact-set validation; no disabled-account behavior or status field. Remove EnsureInitialWorkspace polling contract; cross-service workflow DTOs are handled in Phase 4.
8. Specify managed-account create/read/update with immutable owner/type, and direct account-ID member admission required by the approved model. Do not introduce account credentials, agent execution endpoints or UI. Preserve email invitation workflow and upload/processing operation semantics.
9. Run contract generation, inspect the generated diff, update schema/contract tests and fresh DB fixtures. Final compilation of changed consumers is gated by their owning later phases; do not add temporary old-contract stubs to make this phase artificially green.

## Todo

- [x] Account/Workspace/LetFS baseline DDL and fixtures updated.
- [x] Fixed role/action graph and generator updated; obsolete policy path removed.
- [x] Source contracts updated and generated artifacts reproduced.
- [x] Fresh-schema and action-pair tests cover actual invalid states.

## Success Criteria

Fresh disposable databases accept the reviewed schema; cross-scope parent/root references and invalid account/member states fail. Generated code has no Mount/PathContext/quota bucket or user subject. Action names shared between resource types work; an invalid pair is rejected. No schema/data command is executed against persistent environments by this phase.

## Verification

```sh
pnpm contracts:generate
pnpm contracts:check
uv run --locked --package letfs-ingest pytest scripts/contracts -q
```

Use focused Go contract/schema tests in `packages/go/authz/` and fresh migration tests through existing service fixtures. Run affected tests narrowly first, then widen after all consuming phases compile. Record intentional intermediate contract breakage; final acceptance requires zero unresolved failures.

## Risk and stop rule

No live rollout/backup/backfill or production replay support. If extra schema fields, a new generic access table or a changed permission catalogue becomes necessary, stop for review instead of adding it. New node/scope FKs must not break independently trashed trees or lose cleanup facts.
