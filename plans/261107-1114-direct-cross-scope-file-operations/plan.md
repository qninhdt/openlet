---
title: Direct cross-scope file operations
status: completed
---

# Direct cross-scope file operations

Implement the accepted API. File/folder CRUD, copy and purge run in the request; copy/move/restore support other scopes in the same filesystem. Keep separate content processing and filesystem/scope workflows. No operation engine, replacement background task, progress API, compatibility layer or persistent database changes.

- [x] Domain: direct copy with completed-node receipt, direct retry-safe purge, atomic cross-scope move/restore preserving identities and quota, destination policy enforcement and generation/index fencing.
- [x] Contracts/callers: explicit node copy route returning 201 Node; move/restore destination fields; filesystem batch-stat with scoped locators; update gRPC, OpenAPI, Go/Python SDKs and fixtures together.
- [x] Cleanup/verification: remove copy/purge workflow dispatch, registration, DTOs and replay expectations; preserve filesystem/scope deletion and processing; update owning docs; run integration, workflow, contract, SDK and API acceptance checks.

Acceptance: unauthorized or foreign-filesystem references never publish/read content; moved trees remain structurally consistent; destination restrictions apply to the entire tree; stale processing/index output cannot publish after scope change. Copy failure retains committed output and returns an error; interrupted purge is retried by the caller. No maintenance redispatch of file operations remains.

## Verification

- `pnpm check`, `pnpm build` and `pnpm test` passed. The final unit run includes 29 Python package tests, 100 ingest tests and 22 script tests.
- Full LetFS integration passed with `go test -race -tags integration -p 1 ./...`, using disposable PostgreSQL, SpiceDB and object/search fixtures. Focused cross-scope/direct-copy race tests passed again after final domain edits.
- LetFS workflow tests passed; fresh API E2E histories replayed successfully in Account, Workspace and LetFS.
- API E2E: 35/35 passed, including cross-scope copy/move/restore/batch-stat, copy/purge without Temporal, retained partial copy after source mutation, worker recovery and coordinated backup/restore.
- Review removed obsolete copy/purge dispatch, result types and local traversal serialization. Python copy destination/name defaults match the API. `git diff --check` passed. No schema, migration, dependency or replacement job was added.

External Clerk, paid model and production storage-provider smoke were not run. Copy errors may leave committed partial output; interrupted purge needs a caller retry. Changes are uncommitted and unpushed.
