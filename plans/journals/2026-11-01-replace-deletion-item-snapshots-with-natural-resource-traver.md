---
title: Replace deletion item snapshots with natural resource traversal
date: 2026-11-01
summary: "Delete/purge now resumes from remaining nodes; real recovery, quota, tracing and replay pass."
---

# Replace deletion item snapshots with natural resource traversal

## What happened

Resumed the active simplify-backend-refactor goal from the processing checkpoint. The inherited worker-restart and HTTP/Temporal trace E2E selection passed 2/2. Replaced Letfs deletion operation/item state with filesystem/trash-entry identity and direct bounded leaf batches. Purge admission commits purging before dispatch; maintenance retries the same identity. Removed deletion_items and synchronous file purge, updated the Go/Rust child contract, and delivered public trash entry routes and exact DTOs.

The first Workspace deletion recovery run exposed 409 WORKSPACE_DELETING after deletion. The shared authorization guard now returns NOT_FOUND for nested resources of a deleted Workspace, while its owner can still read the Workspace tombstone. The subsequent gateway selection passed 3/3. A focused purge fixture first failed because it used the wrong existing test helper inputs; correcting those inputs produced the intended real-boundary assertion.

## Evidence

Full PostgreSQL/S3/Temporal integration passed 24/24 (312.57s), including bounded 70-leaf purge, restart, restore fencing and repeat-debit prevention. The dedicated Temporal tracing/Continue-As-New/replay test passed. Current Account, Workspace and Rust filesystem-child histories replay. All-target Clippy/format, Workspace unit/workflow/vet, TypeScript and OpenAPI references/schema/operation IDs pass. A read-only simplifier found no correctness defect and suggested removing one redundant trash-entry fetch; the handler now returns its committed result directly.

## Next work

Goal remains active. Copy is the remaining owner of operations/copy_items/staging: replace it with bounded workflow traversal and per-item publication, stable retry identity and retained partial progress. Then finish full API E2E, current workflow replay, isolated restore and dead-code/docs gates. Live external providers and remote CI were not checked. No commit, publish or existing database reset occurred. AgentWiki publish skipped.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
