---
title: Move blob and indexing options to scopes
date: 2026-11-07
summary: Replace filesystem inline-text configuration with immutable scope-owned allow_blob_files and allow_indexing.
---

# Move blob and indexing options to scopes

## Change

Scopes own `allow_blob_files` and `allow_indexing`, both default true. The former
filesystem option and its unshipped additive migration were removed. SQL, gRPC,
Temporal creation DTOs, Go/Python SDKs and current docs agree.

Blob-disabled scopes retain inline UTF-8 validation and text routing. Uploads,
processor object outputs and cross-scope copies enforce the destination setting.
Index-disabled scopes retain parse/enrichment and skip index publication. No
workflow, activity, table or mutable configuration API was added.

## Verification

Focused PostgreSQL/SpiceDB regressions, SDK tests, contract generation, formatting,
static checks, compilation, unit tests, E2E typecheck, LetFS/Workspace workflow
suites and the full LetFS race-enabled integration suite passed. Independent
review found no changes needed. Test-owned resources were removed. API E2E was not
rerun; no persistent database operation, commit, push or deployment was performed.
Code generation initially lacked Go on PATH and was rerun successfully with the
documented toolchain. The journal command was retried after a context filter
misinterpreted a slash-separated description as a file path.

Execution detail: [scope options plan](../261107-1000-scope-file-options/plan.md).
AgentWiki publish skipped.

## Pre-push review

The subsequent review reproduced and fixed two membership defects: receipt lookup
held a transaction while requesting another pool connection, and a workspace role
change restored a revoked default personal-scope grant. Receipt lookup now uses
the same transaction; role-only changes preserve direct personal grants. Both new
regressions failed before the fixes and passed afterward.

Workspace static checks, unit tests and its full integration suite passed. The
final API E2E run passed all 34 tests, including recovery and worker restarts.
Fresh exported histories replayed successfully for Account, Workspace and LetFS.
The test harness removed its containers; existing user containers were untouched.
The staged secrets scan found no leaks. Real Clerk and paid-provider smoke tests
were not run. No persistent database operation or deployment was performed.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
