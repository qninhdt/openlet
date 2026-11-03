# Foundation migration acceptance

Status: completed. All seven phases and required local acceptance gates passed. External release checks remain separately listed below.

## Implementation and review

- Removed the project Rust source, Cargo manifests/lock and toolchain after Go parity checks in the Phase 4–6 reports. SQL migrations and parser fixtures remain owned by their current applications.
- Canonical scripts build/check/test Go letfs; CI no longer installs Rust or Rust-only native tooling. One integration run exports native Go histories and replay consumes those histories. Turbo explicitly forwards the history directory.
- Shared Python generation remains only in `packages/python/src/openlet_api`; independent wheel/app installation and real RPC pass. Active workers and consumers use `letfs-ingest`.
- Inline PostgreSQL and direct signed S3 transfers remain. Workspace owns canonical storage references and authorization synchronization; letfs contains no business mapping/projector or provision keys.
- Go search uses the official OpenRouter SDK; no handwritten OpenRouter request transport remains. The retained HTTP JSON helper serves Qdrant.
- Scoped final review corrected stale OpenAPI `artifact_root_id`, DBML provision keys and obsolete Rust commands in setup documentation. Protobuf reserves the removed field name/number to prevent reuse; the API test asserts its absence.
- Final independent simplifier pass over the recovery test, replay tests and CI/Turbo ran clean without edits. Inline review checked deletion scope, graph fault injection/fencing, current history requirements, role/provision-key cleanup and direct transport contracts. No unresolved concrete critical/high finding remains in this review slice.
- Recovery exercises actual PostgreSQL-backed Temporal, SpiceDB, MinIO and Qdrant. The final drill erases only the isolated derived graph, interrupts between canonical owners, repeats rebuild and verifies revoke/delete parity, exact bytes, search and interrupted processing.

## Measured checks

All commands run from repository root with `/usr/local/go/bin` on PATH for native Go tools.

| Command / contract | Result and evidence |
|---|---|
| `pnpm install --frozen-lockfile` | PASS; `.local/final-install.log` |
| `uv sync --locked --package letfs-ingest` | PASS; `.local/final-uv-sync.log` |
| `uv build --package openlet-python`; `uv build --package letfs-ingest` | PASS; `.local/final-python-build.log`, `.local/final-ingest-build.log` |
| `pnpm build` | PASS, 7 tasks; `.local/final-build.log` |
| `pnpm check` | PASS, 11 tasks plus script lint/format; `.local/final-check.log` |
| `pnpm test` | PASS, package tests plus 21 script tests; `.local/final-test.log` |
| `pnpm exec turbo run test:workflow` | PASS, 3 owners, letfs race enabled; `.local/final-workflow.log` |
| `pnpm contracts:check` | PASS; `.local/final-contracts-with-go.log` |
| `pnpm check:e2e` | PASS; `.local/final-e2e-check.log` |
| Current API histories before final recovery extension | PASS, all three owners; `.local/final-replay.log` |
| Actual parser corpus, cached offline models | PASS, 11 tests, 95 non-parser cases deselected; `.local/go-migration-parser.log` |
| Renamed ingest + independent shared wheel real RPC | PASS, 1 integration test, 2 unit cases deselected; `.local/go-migration-python-rpc.log` |
| Provider smoke transfer contract against actual MinIO | PASS, race enabled; `.local/go-provider-smoke.log` |
| `OPENLET_HISTORY_DIR="$PWD/.local/final-native-histories" pnpm exec turbo run test:integration --concurrency=1` | PASS, 8 tasks, 6m15s; `.local/final-integration.log` |
| Fresh native Go letfs replay | PASS; `.local/final-native-replay.log` |
| `pnpm --dir e2e exec playwright test --project=api` | PASS, 34 cases, 8.5m; `.local/final-api.log` |
| Fresh complete API histories, all three Go owners | PASS, 3 tasks; `.local/final-api-replay.log`; retained under `.local/final-api-histories` |
| `node --test --test-concurrency=1 e2e/setup/environment.test.ts e2e/setup/recovery.test.ts` | PASS, 3 tests, zero skipped, 95.5s; `.local/final-environment-recovery.log` |

The first final codegen invocation failed because Go was absent from the shell PATH (`.local/final-contracts.log`); rerunning with the supported Go path passed. Earlier phase failures and their corrections remain recorded in the phase reports; they are not passing evidence.

Additional source checks passed: all four Go modules verify; DBML columns match every table in the three application baselines; current documentation links resolve; active Rust/manifests, Workspace file proxy and app-local Python stubs are absent. The only remaining removed-field references are the deliberate protobuf reservation and regression assertion.

## External limits

Live Clerk and selected external S3 HTTPS smoke/recovery are NOT RUN for this revision. MinIO success does not establish external-provider behavior. Paid LLM evaluation and browser/frontend testing are outside this plan. Remote CI has not run; no deployment, commit or push is claimed.

Final owned-process reconciliation found no remaining test containers or application background processes. No existing developer volume was reset. The worktree contains the intended migration changes and retained historical planning records; no commit or push was requested.
