---
title: Simplify application schema and remove dependent mechanisms
status: completed
branch: dev
---

# Outcome and scope

Implement the accepted schema review: remove 30 redundant columns and merge index status into the existing publication status. Keep all eight metadata timestamps. No replacement tables, columns, attempt identifiers, provisioning keys or configuration registries. Keep real user authorization, idempotency receipts, content generation, atomic quota/publication and direct S3 transfer/cleanup behavior.

Evidence: [schema review](../reports/review-261103-1006-schema-minimality.md). Its recommendation to delete eight metadata timestamps is superseded by the user's explicit decision to retain them. Target: 14 application tables and 119 columns.

# Execution

- [x] Workspace admission and onboarding use existing admission once; provision/reconcile by workspace ID. Remove stored workflow IDs/input/constant operation and duplicate completion timestamp.
- [x] letfs provisioning removes service ownership, creation fingerprints and copied max-node configuration; receipts retain request hashes and lifecycle safety.
- [x] Processing removes custom attempt protocol, redundant hashes/generation markers and persisted embedding configuration; merge linear pipeline status. Update Go/Python RPC and generated contracts together.
- [x] Upload/cleanup remove copied size/write expiry/counter; use existing size/deadline/lifecycle without replacement state.
- [x] Remove obsolete code/tests/contracts; preserve meaningful retry, stale generation, publication, quota and S3 cleanup checks.
- [x] Verify affected build/check/unit/workflow/integration/contracts; update owning docs and DBML, review final diff.

# Validation and data

Source and existing changes backed up privately under `.local/schema-cleanup-backup/`. No Docker containers were running at task start; no existing database is being reset or migrated. Tests use disposable databases. Back up any persistent database before changing it. Existing development schema reset is authorized, but unnecessary for source-only baseline changes.

Start with focused native tests, then shared-contract and real boundary suites. Do not keep removed mechanisms to satisfy obsolete tests. Existing historical Temporal histories need new recordings for changed workflow contracts; no production history compatibility is required. Preserve pre-existing uncommitted OpenAPI deletion and DBML/report edits. No commit/push in this request.

# Verification evidence

- Schema inventory: 14 tables, 150 → 119 columns; no new columns or tables. All eight retained metadata timestamps verified. DBML column sets match all three baseline migrations exactly.
- `pnpm test`: eight tasks passed, including 100 Python tests; 21 operation-script tests passed. Native Go workflow suites passed.
- `pnpm check`: ten tasks passed, including generated-contract drift, Go vet/format and Ruff; `pnpm check:e2e` passed.
- Workspace/Account unit and workflow suites passed; Workspace HTTP/store integration passed against real PostgreSQL/SpiceDB.
- `go test -race -tags integration ./apps/letfs/... -p 1 -count=1`: all packages passed, including native Python worker/gRPC and real storage boundaries.
- `pnpm e2e:api`: 34/34 passed against real PostgreSQL, SpiceDB, Temporal, MinIO and Qdrant; model responses use the existing controlled test provider. Recovery covers database/object restore and real worker restarts.
- `OPENLET_HISTORY_DIR=.local/api-e2e/histories pnpm test:replay`: all three Go owners passed against fresh recordings. An initial invocation ran before SyncWorkspace history existed; rerunning after recording completed passed.
- Initial integration failures were obsolete service-ownership/manifest-conflict assertions and fixtures carrying the old two-status model; updated them to the accepted behavior and reran the affected suites.
- Owned E2E/test processes exited and Compose test containers were removed. Existing development databases remain untouched; applying the changed baseline to an existing dev installation requires its authorized reset.
- Inline ponytail review traced admission, processing, publication and cleanup callers. Removed stale public OpenAPI fields and recovery-fixture inserts found during the final reference scan. No references to removed schema/protocol names remain in active application code/contracts/scripts/E2E/docs.
