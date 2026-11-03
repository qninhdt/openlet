---
title: "Go filesystem, gRPC and SpiceDB authorization foundation"
description: "Complete the shared authorization and filesystem foundation before implementing Leti agents."
status: completed
priority: P2
effort: "240-360h"
branch: dev
tags: [refactor, backend, auth, infra, database]
blockedBy: []
blocks: []
created: 2026-11-02
---

# Go filesystem, gRPC and SpiceDB authorization foundation

## Overview

Deliver full letfs behavior in Go, a shared Go module and reusable Python protobuf/gRPC package, action/resource authorization using self-hosted SpiceDB, relationships derived from PostgreSQL business records and synchronized through Temporal, application gRPC, direct public letfs APIs, and the `letfs-ingest` rename. Remove Rust, Workspace filesystem proxies and internal application HTTP. This plan blocks Leti implementation; no AI-agent code is included.

Scope is HOLD: preserve all requested work and current behavior. No Access service, policy engine, production compatibility bridge, custom-role UI, personal/chat filesystem product or real-LLM E2E. Development reset is allowed only after the required backup. Estimates are engineering ranges, not delivery commitments.

## Accepted authorization correction

Role-to-action policy belongs in version-controlled `packages/contracts/authz/schema.zed` and `roles.json`, loaded directly into SpiceDB. Application PostgreSQL stores existing business facts only: users, workspaces, membership role assignments and storage references. Temporal synchronizes their relationships; services use native action/resource checks. Remove the four SQL catalog tables and the head/intent/ack/epoch framework introduced during implementation. Existing business revisions/If-Match, receipts, lifecycle constraints and safe retry/reconciliation remain. Older delayed/retried writes must not restore access after synchronized revoke/transfer success; Phase 3 must prove that behavior without the rejected framework. The November 2 user correction supersedes earlier proof-framework requirements and historical reports; Phase 3 owns the cleanup and implementation.

## Execution contract

Read the [architecture contract](architecture-contract.md), [verification matrix](verification-matrix.md), [authorization source inventory](../reports/scout-261102-1059-authorization-rpc-inventory.md), and [filesystem source inventory](../reports/scout-261102-1059-letfs-go-parity.md). They carry ownership, exceptional permissions, transport semantics, recovery and authoritative source paths. Every phase is detailed; re-scout its touched sources before execution because this is a large rewrite.

Phases are sequential. Do not run Rust and Go against the same database/task queues. Phase 6 switches runtime, consumers and routes together. The initial authoring was documentation-only; implementation changes and measured results are tracked in the phase evidence reports. Latest decisions remove all provision keys and letfs business mapping/projector: callers persist stable storage IDs; Workspace owns inheritance relationships/projection. See the [boundary review](reports/letfs-boundary-review.md).

## Phases

Current execution evidence: [Phase 1 proofs](reports/proof-results.md), [Phase 2 progress](reports/phase-02-progress.md), [Phase 3 progress](reports/phase-03-progress.md), [Phase 4 progress](reports/phase-04-progress.md), [Phase 5 progress](reports/phase-05-progress.md), [Phase 6 progress](reports/phase-06-progress.md), and [final acceptance](reports/acceptance.md).

| # | Phase | Dependencies | Effort | Status |
|---|---|---|---|---|
| 1 | [Contracts and proof gates](phase-01-contracts-and-proof-gates.md) | None | 16-24h | Completed |
| 2 | [Shared Go/Python contracts and infrastructure](phase-02-shared-go-contracts-and-infrastructure.md) | 1 | 24-32h | Completed |
| 3 | [Workspace authorization and relationship synchronization](phase-03-workspace-authorization-and-durable-projection.md) | 1, 2 | 40-56h | Completed |
| 4 | [Go filesystem core and storage](phase-04-go-filesystem-core-and-storage.md) | 1, 2, 3 | 56-80h | Completed |
| 5 | [Go workflows, ingest and search](phase-05-go-workflows-ingest-and-search.md) | 4 | 56-88h | Completed |
| 6 | [Direct filesystem API and proxy removal](phase-06-direct-filesystem-api-and-proxy-removal.md) | 3, 4, 5 | 24-40h | Completed |
| 7 | [Rust removal, recovery and acceptance](phase-07-rust-removal-recovery-and-acceptance.md) | 6 | 24-40h | Completed |

## Completion criteria

- [x] Go letfs preserves all inventoried storage, tree, upload, quota, copy, ZIP, trash, cleanup, ingest and search behaviors.
- [x] Every application role-based allow/deny is replaced by action/resource checks; identity, scope and business invariants remain enforced.
- [x] Real SpiceDB tests prove role sets, inherited checks, atomic transfer, timeout, stale retries, outage and canonical rebuild.
- [x] All application-to-application RPCs use gRPC; public HTTP/native gRPC cannot bypass the same operation authorization.
- [x] No provision keys or business mapping/projector remain in letfs; generic ID-based idempotency/lifecycle checks pass.
- [x] Clients access letfs directly; Workspace returns filesystem references and owns lifecycle, without a file proxy.
- [x] Generated Python messages/client stubs/server interfaces live only in `packages/python/src/openlet_api/`; the independent `openlet-python` wheel and ingest dependency pass isolated installation and real RPC tests.
- [x] Python app/distribution/module/package and every active consumer use the chosen ingest names; the shared Python output path remains unchanged by the rename.
- [x] Clean builds, checks, unit/integration/workflow/replay/API/recovery tests pass; Rust and obsolete HTTP packages/contracts/tooling are removed.

## Dependencies and proof gates

Reuse existing Go/Python runtimes, Temporal, PostgreSQL 18.6, Envoy, S3 and Qdrant. Add SpiceDB OSS with its own database/user on the same PostgreSQL instance. Pin new dependency/image/codegen versions only after compatibility checks. Phase 1 established the schema, dependency and HTTP binary mappings. The former graph-marker proof is historical after the authorization correction; implement current-state relationship synchronization and its retry/recovery tests in Phase 3. Failed proof gates stop progression; they do not authorize scope cuts or architecture substitutions.

## Review and validation

Plan format, source grounding, cross-phase consistency and adversarial review are tracked in the [plan review record](reports/plan-review.md). Product decisions reuse the completed brainstorm; do not reopen reset, storage byte paths, no-Access, ingest naming or membership status. Implementation is complete; [proof results](reports/proof-results.md) record measured Phase 1 gates and later application acceptance limits.

## Handoff

All seven phases and required local gates are complete. Go letfs, shared Go/Python contracts, self-hosted SpiceDB, direct HTTP/native gRPC and renamed ingest are active; Rust and the Workspace file proxy are removed. Final integration passed (8 tasks), full API/recovery passed (34 cases), fresh native/API replay passed, and environment/recovery tooling passed (3 tests, zero skipped). The recovery drill erases the derived graph, interrupts/repeats canonical rebuild and proves revoke/delete parity, exact bytes, current search and interrupted processing. See [acceptance](reports/acceptance.md) for commands, logs, review and external-provider limits. No Leti code, deployment, commit or push is included.
