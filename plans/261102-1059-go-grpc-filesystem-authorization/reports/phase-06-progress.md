# Direct Go filesystem cutover

Status: completed. Runtime and consumer cutover passed the whole-system gate; Phase 7 owns Rust removal and final recovery acceptance.

## Implemented

- Compose and the letfs Dockerfile now build/run Go. Envoy routes direct filesystem and quota-bucket HTTP plus public native gRPC; private administration/ingest stay isolated. Public HTTP authenticates the gateway before in-process application calls.
- Workspace returns filesystem/root/bucket references and no longer proxies filesystem operations. Account summaries/verified-email callers use generated gRPC. Generic storage Activities retain owner orchestration without business fields or reverse clients in letfs.
- The existing Python app is now `apps/letfs-ingest`, distribution `letfs-ingest`, module `letfs_ingest`, pnpm package `@openlet/letfs-ingest`; actual workers use generated gRPC. The legacy HTTP binding is removed. Generated Python remains exclusively under `packages/python/src/openlet_api/`.
- Actual Playwright consumers use direct filesystem IDs. Compose, CI, bootstrap, worker restart and recovery inventories use ingest names and MinIO. Controlled provider fixtures accept the official OpenRouter SDK embedding string input and required rerank response model.
- Copy creation returns stable `accepted` admission; its monitor reports running/terminal state. Recovery injection locks the root node so deletion admission can finish before the child is blocked. Explicit test reconciliation uses Temporal `BufferOne`, because the default `Skip` can discard a trigger during an existing scan.

## Verification

| Check | Evidence |
|---|---|
| `pnpm check`, `pnpm test`, contract drift check | Passed; `.local/direct-check.log`, `.local/direct-test.log`, `.local/direct-contract-check.log` |
| Direct HTTP actual PostgreSQL/SpiceDB authorization and bytes | Passed after adapter fixes; `.local/direct-http-fixed.log`, `.local/direct-http-mounted.log` |
| Copy admission over authenticated RPC, race enabled | Passed; `.local/direct-copy-admission-integration.log` |
| Four previously failing API cases | All passed; `.local/direct-api-focused.log` |
| Latest E2E typecheck and diff whitespace | Passed |
| Whole system including coordinated restore/native gRPC | 34 passed (5.5m); `.local/direct-api-final.log` |
| Actual parser/OCR/document corpus | 11 passed, 95 deselected; `.local/go-migration-parser.log` |
| Independent renamed ingest/shared wheel RPC | 1 passed, 2 deselected; `.local/go-migration-python-rpc.log` |
| HTTPS provider-smoke implementation against actual MinIO, race enabled | Passed; `.local/go-provider-smoke.log`; external provider NOT RUN |
| All package builds | 7 successful tasks; `.local/go-migration-build.log` |

The preceding full run had 30 passes and four failures, recorded in `.local/direct-api-recovery.log`. The subsequent full run passed all 34 cases after those fixes. Current Go histories were exported and all three owner replayers passed in `.local/final-replay.log`. Phase 7 retains final native acceptance, deeper graph rebuild recovery and Rust deletion.
