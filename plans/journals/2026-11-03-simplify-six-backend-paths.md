---
title: Simplify six backend paths
date: 2026-11-03
summary: "Removed repeated authorization, reconciliation, transport and CI work while preserving API and recovery behavior."
---

# Simplify six backend paths

## What happened

Implemented the six accepted findings in `plans/261103-0905-simplify-backend-paths/plan.md`. Name-only Workspace changes no longer depend on Temporal. Account scans publish one relationship batch per canonical page. HTTP ZIP streams its reader directly with one reusable buffer. Search uses typed HTTP JSON instead of a protobuf/map roundtrip. Qdrant only repairs missing or mismatched indexes. CI runs one native Turbo graph and one script test pass.

## Evidence

Focused regressions passed, including real PostgreSQL/SpiceDB 100+3 account batches and Workspace updates with no Temporal client. A disposable pinned Qdrant verified creation, matching GET-only checks, repair and repeat checks. The CI-equivalent native graph passed all 28 tasks; contract checking and shared builds each executed once. All 21 script tests, 3 real setup/recovery tests, 34 API/recovery journeys and fresh workflow replay for Account, Workspace and letfs passed. ZIP disconnect and late storage failure tests retained cancellation/abort behavior. The required simplifier made no code edits; inline review found no unresolved issue in this scope.

## Boundary

Preserved the preexisting uncommitted migration. No schema change, dependency, cache, commit or deployment. Tests used disposable local services and controlled model/provider responses; remote CI and live Clerk/paid models/external S3 provider were not exercised. Test containers were cleaned up. AgentWiki publish skipped.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
