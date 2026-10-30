---
title: Openlet hybrid artifact plan update
date: 2026-10-30
summary: Replaced detached artifact ownership with direct source children and a scoped UUID alias.
---

# Openlet hybrid artifact plan update

## What changed

Updated all four files in plans/261029-1624-artifact-file-processing. Original file bytes remain in file_data; artifacts become children through parent_id. Source paths traverse artifacts, and a root-scoped @<uuid> alias addresses live nodes. Previous ownership/namespace design is removed from execution instructions; six historical reports are marked superseded.

## Decisions

Artifact descendants remain readonly through strict file ancestry. Copy snapshots payload plus children, and derived-child publication preserves source revision/ETag. Trash terminally fences unpublished processing; restored published artifacts reappear. Keep one Rust workflow, one Python activity, bounded staging, atomic publication/quota, and the agreed output layouts.

## Verification and next step

Three independent document/source reviews completed; four revised-plan findings were corrected and reread. Structural validation, links, retired-term sweep, caller checks and thirty baseline source anchors passed. Three phases and sixty implementation tasks remain pending. Plan index refreshed and current worktree plan selected.

No implementation, compilation, runtime tests, database migration or dependency/model installation performed. Recheck disk space before execution. Implement only when requested using the current plan. AgentWiki publish skipped; this journal is local history.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
