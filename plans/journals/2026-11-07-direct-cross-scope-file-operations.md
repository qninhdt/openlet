---
title: Direct cross-scope file operations
date: 2026-11-07
summary: "Move file operations into requests and enable scoped copy, move, restore and batch metadata."
---

# Direct cross-scope file operations

Implemented the accepted API in LetFS, HTTP/gRPC contracts and Go/Python SDKs. Copy returns a completed Node; purge completes bounded SQL batches in the request. Removed copy/purge Temporal dispatch, registrations, activity wrappers, recovery redispatch and old result types. Filesystem/scope deletion and content processing keep their workflows.

Cross-scope move/restore preserve IDs, object keys and filesystem accounting in one transaction, validate the entire destination tree and fence old processing/index generations. Batch-stat accepts scoped locators at filesystem level.

Verification passed: monorepo check/build/unit tests, full LetFS race integration, workflow tests, fresh Account/Workspace/LetFS history replay, and all 35 API E2E cases. Python import ordering found during final checks was corrected. Disposable test stacks were cleaned automatically.

No new dependency, schema, compatibility path or replacement job. Copy failure retains committed partial output and interrupted purge requires caller retry. External Clerk, paid-model and production-provider smoke were not run. No commit or push performed.

Implementation and verification record: [plan](../261107-1114-direct-cross-scope-file-operations/plan.md).

AgentWiki publish skipped.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
