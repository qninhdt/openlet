---
title: "Simplify Openlet backend from the three architecture notes"
description: "Rewrite API E2E first, remove duplicate orchestration state, migrate to Gin, and fix file processing ownership."
status: completed
priority: P1
effort: "25–36 engineering days"
branch: dev
tags: [refactor, backend, api, testing, observability]
blockedBy: []
blocks: []
created: 2026-10-31
---

# Simplify Openlet backend

## Outcome

Deliver the complete accepted three-note design while removing unnecessary machinery. Implementation and local acceptance are complete; execution evidence and external-provider/remote CI limits are recorded in [validation.md](./validation.md). Earlier brainstorm reports are historical; current product contracts live in the owning documentation.

## Mandatory constraints

- No production compatibility requirement: replace APIs/schema directly. Keep no dead code, legacy adapters, duplicate implementations, or upgrade migrations.
- Delete ALL existing E2E tests, harnesses, issuer code, helpers, and fixtures. Write their replacements from scratch in TypeScript/Playwright; do not move, copy, or mechanically port their code. Reading old tests to identify required behavior is allowed.
- API E2E comes first, using real backend/database/Temporal/storage/search dependencies. No fake backend, skipped target tests, empty browser project, or meaningless coverage targets.
- Delete every existing standalone automation script. Write only necessary permanent bootstrap/backup/restore automation from scratch. No temporary scripts, command wrappers, custom test/job framework, or speculative abstractions.
- Squash application migrations to one baseline per database. Later phases edit that baseline. Back up before actual database schema/data changes; reset only explicitly identified environments.
- Preserve authorization, revisions, atomic quota accounting, retry safety, processing fences, cleanup evidence, and unrelated working-tree changes.

## Phases

| # | Phase | Depends on | Estimate | Status |
|---|-------|------------|----------|--------|
| 1 | [Rewrite API E2E from scratch](./phase-01-api-e2e-from-scratch.md) | — | 4–6 days | Completed |
| 2 | [Monorepo, infra, scripts, and migration baselines](./phase-02-monorepo-infra-scripts.md) | 1 | 3–4 days | Completed |
| 3 | [Complete Gin migration and OpenTelemetry](./phase-03-gin-opentelemetry.md) | 2 | 3–4 days | Completed |
| 4 | [Account/Workspace and direct Temporal orchestration](./phase-04-account-workspace-temporal.md) | 3 | 4–6 days | Completed |
| 5 | [Letfs schema, file lifecycle, and ZIP streaming](./phase-05-letfs-schema-file-lifecycle.md) | 4 | 6–8 days | Completed |
| 6 | [Processing, search, and final acceptance](./phase-06-processing-search-final-gates.md) | 5 | 5–8 days | Completed |

Execute sequentially. Phase 1 is detailed; scout the current source before executing each later outline and record its concrete affected-file list. Estimates are planning ranges, not measured delivery promises.

## Sources and accepted decisions

- [Architecture decisions](../261031-1738-refactor-three-notes/inputs/openlet-architecture-decisions.md) owns repository/testing/infra.
- [Final architecture](<../261031-1738-refactor-three-notes/inputs/openlet-final-architecture-status-to-processing (1).md>) owns APIs/lifecycle.
- [Numbered note](<../261031-1738-refactor-three-notes/inputs/1. xóa bảng operation của user và workspace, quá.md>) owns semantic pipeline details and worker separation.
- Accepted: no whole-tree copy/ZIP snapshot; retain committed partial progress without rollback; child workflows for long processes, remote Activities for short internal mutations; receipts retained 24h after logical completion; invitation tokens returned once.
- Gin/OTel is approved. Collector, Grafana, Prometheus, frontend, billing, Nexus, cloud IaC, and unrelated parser rewrites are outside scope.

## Acceptance criteria

- [x] New API E2E runs through the real gateway from clean state; no legacy E2E/script code or concealed test failures remains.
- [x] Native workspaces, Docker builds, task discovery, CI, commands, and docs agree; one baseline migration per application database.
- [x] No Chi remains; every app and both Python workers support context propagation, correlated logs, optional OTLP, and bounded shutdown.
- [x] No generic operations, copy_items, deletion_items, export_attempts, whole-tree copy staging, or internal workflow HTTP start/poll remains.
- [x] Concurrent retry/crash cannot duplicate effects/quota or lose admitted work; partial copy/delete outcomes are explicit.
- [x] nodes/files, uploads, trash, cleanup, ZIP, README enrichment, taxonomy, and versioned search satisfy their contracts.
- [x] Meaningful native checks, integration, replay, and E2E pass; external-provider verification limits are recorded accurately.

## Red Team Review and Validation Log

[Validation and review evidence](./validation.md) records accepted decisions, findings, and the consistency sweep. Phase checkboxes are the execution tracker; unchecked gates are not acceptance claims.

<!-- slug: simplify-backend-refactor -->
