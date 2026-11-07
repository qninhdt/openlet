---
title: "Account, scoped filesystem and Temporal redesign"
description: "Implement the reviewed account/scope model and twelve service-owned workflows; remove mounting, quota buckets and obsolete contracts."
status: completed
priority: P1
effort: "5 sequential implementation phases"
branch: dev
tags: [account, workspace, letfs, authorization, temporal]
blockedBy: []
blocks: []
created: 2026-11-06
---

# Account, scoped filesystem and Temporal redesign

## Overview

Implemented the user-approved [Design contract](design-contract.md) with ak-cook and ponytail. This is a clean replacement on a non-production system without existing data. All five phases, API/replay acceptance and test-resource cleanup are complete; see [execution evidence](phase-05-cleanup-and-acceptance.md#execution-evidence--2026-11-06).

## Scope lock

- Account owns independent user/agent identities; Workspace owns membership and default storage mappings; LetFS owns filesystem → scope → node and action enforcement.
- Preserve current uncommitted `inline_text_only` work. No new service, credential system, AI runtime, custom-role engine, copy checkpoint/progress engine or compatibility layer. Account disable and ownership transfer are excluded.
- Remove mounting, quota buckets, workspace-count limits and obsolete workflow/API/schema code completely. Preserve filesystem byte quota, existing node/job bounds and `MAX_MEMBERS`.
- Disposable Testcontainers and ownership-checked E2E Compose databases are used for verification. No persistent environment reset/migration, commit, push or deployment is authorized.
- Any change to approved tables/fields, public behavior, service ownership or workflow/activity tree requires review before implementation. Source-backed internal details within that boundary do not reopen product decisions.

## Phases

| # | Phase |
|---|-------|
| 1 | [Schema, authorization and contracts](./phase-01-schema-authorization-contracts.md) |
| 2 | [Account identity](./phase-02-account-identity.md) |
| 3 | [LetFS scopes and filesystem quota](./phase-03-letfs-scopes-and-filesystem-quota.md) |
| 4 | [Workspace and Temporal](./phase-04-workspace-and-temporal.md) |
| 5 | [Cleanup and acceptance](./phase-05-cleanup-and-acceptance.md) |

Phase checklists are the source of phase status; no duplicate status fields are maintained.

Dependencies: 1 → 2 → 3 → 4 → 5. One coherent branch; no partial rollout or compatibility interval. Contracts may intentionally invalidate downstream code until its owning phase; final acceptance permits no unresolved breakage.

## Success Criteria

- [x] Approved schemas, role/action matrix and twelve workflow trees implemented exactly.
- [x] Scope isolation enforced through paths, IDs, search/indexing, uploads, processing, copy, trash and archives.
- [x] Real PostgreSQL/SpiceDB/Temporal tests prove quota, SQL/graph retry, duplicate cleanup and worker-crash cleanup. Copy failure retains partial output without automatic retry.
- [x] SDKs, generated contracts, Envoy, bootstrap/recovery scripts, E2E fixtures and owning docs updated together.
- [x] Removed symbols/routes/config have no executable consumers; full checks pass and existing user changes remain intact.

## Evidence and validation

- [Source inventory and SDK findings](source-evidence.md) distinguishes current behavior from proposed implementation.
- Latest reviewed cuts remove account disable/status/active gating, ownership transfer and copy checkpoint/progress/resume machinery. Duplicate deletion uses natural idempotency. Retain membership active/inactive, roles and compensation; no repeated design interview is required.
- Planning validation and review results are recorded in [Plan review](plan-review.md). Implementation fault-injection tests are acceptance gates, not claimed results.
- Phase checklists and the Phase 5 execution evidence record implementation status.

## Execution

Authorized implementation command: `/ak:cook /home/qninh/projects/openlet/plans/261106-1517-account-scope-temporal-redesign/plan.md`.
Keep existing operations tooling functional, but add no backup/backfill project or production history support. If an actual persistent database operation later enters scope, stop before executing it and follow the applicable database safety instructions.

<!-- slug: account-scope-temporal-redesign -->
