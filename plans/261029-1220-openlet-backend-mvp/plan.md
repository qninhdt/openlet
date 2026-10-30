---
title: "Openlet backend MVP"
description: "Build the agreed cloud-file backend using established infrastructure and explicit storage invariants."
status: in-progress
priority: P1
effort: "33 engineer-days; rough planning estimate, not a delivery commitment"
branch: main
tags: [backend, database, api, auth, infra]
blockedBy: []
blocks: []
created: 2026-10-29
---

# Openlet backend MVP

## Overview

Deliver User/Workspace Go/Chi and generic letfs Rust/Axum behind Envoy, with Clerk identity, PostgreSQL, native Temporal workers and configurable S3 storage. Redis is omitted. The backend supports profiles, collaboration, ID/path file operations, inline text, uploads, quota and durable deletion/copy. All backend components are implemented and local acceptance has passed, including full integration, native workflow replay and an isolated metadata/object/Temporal restore. Real Clerk development and Cloudflare R2 smoke checks also passed; R2-specific coordinated recovery remains open.

Scope is HOLD: preserve the accepted backend MVP; add no speculative techniques. No frontend, billing, agents, file processing, automatic email/trash purge or cross-filesystem copy/move. Reuse [architecture](../../docs/architecture.md), [data invariants](../../docs/data-model.md), [API contracts](../../docs/api-contracts.md), [workflows](../../docs/workflows.md) and [testing](../../docs/testing.md).

## Research and existing state

[Primary-source research](../reports/research-261029-1220-production-patterns.md) records what is reused and what Openlet must prove. Initial repository inspection found docs and plan scaffolds only: no services, migrations, manifests, tests, committed HEAD or task-owned background processes. Old executable plans were removed at the user's request. Historical reports/journals do not override this plan.

## Phases

| # | Phase | Status |
|---|---|---|
| 1 | [Foundation and real provisioning](phase-01-start.md) | Pending |
| 2 | [Identity and workspace collaboration](phase-02-identity-workspaces.md) | Pending |
| 3 | [Filesystem, inline text and path operations](phase-03-filesystem-core.md) | Pending |
| 4 | [Object storage and independent copy](phase-04-storage-and-copy.md) | Pending |
| 5 | [Durable deletion and maintenance](phase-05-durable-lifecycle.md) | Pending |
| 6 | [System integration and operational acceptance](phase-06-integration-operations.md) | Pending |

## Dependencies and execution

Execute sequentially, 1 through 6. Each phase extends real behavior; phase 1 provides actual bucket/filesystem/root provisioning needed by phase 2. Files/commands in phase files are planned creations unless marked existing. Six phases separate integration and data-safety gates, not additional services/frameworks. Estimates are summed after phase reconciliation; exact SDK/server/provider compatibility remains an implementation check.

Native workers belong to their service. Cross-service activities use internal HTTP, without direct Go/Rust Temporal interoperability requirements. Ordinary transactions stay direct. Recursive directory copy is coherent per file with one destination publication; it does not snapshot a concurrently changing source tree.

## Success criteria

- [ ] Onboarding reuses one internal UUID and initial workspace, publishes the Clerk claim and supports token refresh.
- [ ] Membership/invitation/Owner rules and Envoy/service trust boundaries reject unauthorized access.
- [ ] ID/path file operations, exact inline/object bytes, conditional writes and trash/restore work consistently.
- [ ] Concurrent quota admission and copy/purge retries preserve accounting; no N+1 list/query pattern.
- [ ] Copy/deletion/maintenance survive worker/server restart and crash after committed effects.
- [ ] Compose setup, actual Clerk/S3 provider smoke and isolated metadata/object restore pass.

## Review and validation

Planning mode: hard, reusing completed primary-source research rather than repeating searches. Four independent review lenses and whole-plan verification are recorded in the [review report](../reports/validation-261029-1220-openlet-backend-mvp.md). Plan-format validation is distinct from unrun application tests. User scope was approved before authoring; routine technical repairs stay inside that scope.

No live task-management surface is available; phase checklists are the durable todo list. The checked phase tasks and implementation evidence reports record completed checks. Historical planning validation below does not describe the current implementation state.

## Red Team Review

Four independent lenses produced 17 initial findings (13 High, 4 Medium), grouped into 14 issues after overlap. Disposition: 11 accepted, 3 accepted with modified remedies; no unresolved planning blocker. The [adjudication report](../reports/validation-261029-1220-openlet-backend-mvp.md) retains evidence and follow-up verification. User-selected conditional/state recovery replaces the proposed direct response receipts; operational backpressure uses existing rows, and native Envoy local limiting remains owned by phase 1.

### Whole-Plan Consistency Sweep

Reread this index and all six phases against the owning docs. Checked retry contracts, path identity, migration ownership, batch accounting, durable admission, backup freeze and bounded resources. Unresolved contradictions: 0.

## Validation Log

### Session 1 — 2026-10-29

Trigger: user accepted the [researched retry recommendation](../reports/research-261029-1344-file-operation-retries.md) and instructed continuation of ak-plan. New questions asked: 0; no material product decision remains. User answer: “ok toi chon cai nay tiep tuc workflow cua akplan di”.

Confirmed: short trash/restore/file-purge has no response receipt; original identity/revision and authorized reconciliation remain. Inline copy, upload and durable work retain their necessary creation/progress identity. Path mutations guard expected target/parent IDs. Propagated to docs and phases 3–6. Clerk claim configuration and the selected provider's restore method are assigned acceptance prerequisites, not assumed verified integrations.

### Whole-Plan Consistency Sweep

Full document verification covers all six phases, sequential dependencies, file ownership, planned commands, test selectors, links and current scope. No application exists to trace or test. Mechanical results and external verification boundaries are recorded in the validation report. All implementation checkboxes remain unchecked; no task completion is inferred from plan validation. CLI validation passed; parsing reports 6 phases and 96 pending phase tasks. Thirty-six document assertions passed, and 43 relative links across 25 Markdown files resolved. Failed document checks: 0; runtime checks remain unrun.

## Handoff

Local implementation is complete. See [final local acceptance](../reports/implementation-261029-1737-local-acceptance.md); real Clerk/R2 smoke checks are recorded in [external configuration evidence](../reports/implementation-261029-1822-external-configuration.md), with only provider-specific recovery acceptance remaining open in phase 6. Earlier reports describe their historical implementation state. Phase-table labels are retained CLI-generated text; checked tasks and `ak plan status` show current progress. Implementation entry: `/ak:cook /home/qninh/projects/openlet/plans/261029-1220-openlet-backend-mvp/plan.md`. The user has authorized full implementation; no routine phase approval is pending.
