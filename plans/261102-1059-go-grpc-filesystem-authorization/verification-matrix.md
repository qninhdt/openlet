# Verification and acceptance matrix

This matrix defines implementation evidence. Plan authoring has not run these application, infrastructure or provider checks. Read the [architecture contract](architecture-contract.md) and phase-specific commands first. Start with the narrowest meaningful test; broaden only for affected contracts and final acceptance.

## Levels and dependencies

| Level | Real subject | Appropriate controlled boundary |
|---|---|---|
| Unit | Go validation/workflow decisions, Python parser/state logic | Time/SDK activity boundaries where nondeterminism is irrelevant |
| Native integration | Real owner application, migrations, PG, SpiceDB, S3, Qdrant, gRPC as applicable | Controlled Clerk/OpenRouter/rerank responses; never fake the graph or SQL for their invariants |
| System API/recovery | Real Envoy, Go services, Python workers, PostgreSQL-backed Temporal, storage and graph | Existing authenticated external-provider fixture server |
| External release smoke | Actual chosen Clerk/S3 deployment | No claim that local fixtures prove provider TLS, permissions or disaster recovery |

Workflow replay belongs to native verification. A Temporal dev server or SDK activity mock does not prove persisted restart recovery. Use the current Compose PostgreSQL-backed server for those claims. There is no browser frontend suite today and no paid LLM requirement.

## Required scenario owners

| Priority | Contract and discriminating scenario | Lowest reliable proof | Implementation owner |
|---|---|---|---|
| Critical | Viewer/Editor/Owner action matrix; foreign workspace/FS denial | Real SpiceDB role/grant/binding fixtures and actual gRPC/application calls | 1, 3, 4, 6 |
| Critical | Account bootstrap before UUID/graph; missing claim is never general allow | Real gateway/JWKS and Account lifecycle | 2, 3, 6 |
| Critical | Public native gRPC calls admin/ingest method, duplicate/spoofed metadata | Real Envoy HTTP/2 plus application entry-point denial | 1, 2, 6 |
| Critical | Two concurrent ownership transfers/removal | Real Workspace SQL constraints/transactions and one atomic graph aggregate write | 3 |
| Critical | API success followed by independent inherited FS revoke check | Real graph with explicit consistency, different client context | 1, 3, 6 |
| Critical | Commit business mutation then die before dispatch, including Workspace storage inheritance | Real Account/Workspace records + native sync/reconciliation + persistent Temporal | 3, 6, 7 |
| Critical | Workspace storage-reference commit, graph publication gap and rebuild | Workspace records/native relationship sync; completion waits, letfs denies missing access | 3, 6, 7 |
| Critical | Stable create ID across expired receipt/lost response/freeze/delete | Real generic letfs SQL/Temporal; no duplicate allocation or resurrection without provision key | 1, 4, 5, 6 |
| High | letfs business imports/clients/payloads or graph-writer registration | Source/config/contract audit and two generic caller fixtures; no reverse domain dependency | 4, 5, 6, 7 |
| High | One FS grant used to inspect sibling or quota bucket | Independent target filesystem/bucket permission checks reject scope expansion | 1, 4, 6 |
| Critical | Older graph write remains in flight or loses its response, then newer revoke/transfer succeeds | Real controlled remote-write race; release/retry old work and independently check inherited FS permission before reconciliation: superseded access must not return | 3 |
| Critical | Graph rebuild followed by resumed sync | Drain writers; load repository policy and synchronize restored canonical relationships before admission | 3, 7 |
| High | Newer business mutation while older sync is pending | Preserve existing If-Match; synchronize current owner records without saved obsolete grant commands or SQL acknowledgment ledgers | 3 |
| Critical | Mutation timeout after canonical commit/client disconnect | API does not claim rollback or cancel durable work; safe retry identity | 3, 6 |
| Critical | Competing quota/node writes/finalize/purge | Real PG barriers; exact accounting and no overcommit/double debit | 4, 5 |
| Critical | S3 response lost/late copy or upload write | Real S3 candidate evidence, saved finalize preconditions and cleanup grace | 4, 5, 7 |
| Critical | Artifact mutation by raw ID, alias, cwd, copied forest or hidden descendant | Actual path/application/gRPC checks; immutable provenance and lifecycle | 4, 6 |
| Critical | ZIP error after headers, cancellation/slow reader | Actual streaming body/HTTP2 cancellation; no JSON appended and no resource leak | 1, 5, 6 |
| Critical | Restore while graph/canonical/object writers or signed capabilities remain | Existing owner-safe recovery extended to projectors, new DB and actual renamed workers | 2, 3, 6, 7 |
| High | Editor/Viewer self-leave; Owner must transfer; foreign member removal denied | Real graph + Workspace transaction/errors | 3, 6 |
| High | Invitation same-email duplicate, role mismatch, expiry/revoke/verified-email mismatch | Real PG and generated Account RPC; existing fixtures | 3 |
| High | Accepted invitation replay after removal / existing member role | Cannot re-add removed member or overwrite current role | 3 |
| High | Workspace provisioning/deleting/failed status and Owner tombstone | Actual graph/status/candidate list semantics, no active-only shortcut | 3, 6 |
| High | Filtered discovery produces empty page with more candidates | Bounded SQL/bulk checks, cursor progresses without skipped/repeated candidates | 3 |
| High | Owner accesses another actor's upload session | Denied; upload actor binding is not Owner override | 4, 6 |
| High | Copy monitor: initiator, ordinary Viewer and current/new/former Owner | Current read permission plus actor or inspect-any action; retained history expiry 410 | 3, 5, 6 |
| High | Same revision reused after target/parent replacement | Expected identity prevents modifying replacement content | 4 |
| High | Public object-only uploads; inline arbitrary bytes; native multipart | Exact size/checksum/header/part receipt and immutable completion rules | 4, 6 |
| High | Trash restore/purge, repeated batches and all roots deleted | Exactly accounted retained/trash data; terminal tombstones and no recreation | 4, 5 |
| High | Copy retries/continuation/source mutation/ceiling/partial failure | Bounded traversal and visible partial results; no recharge/resurrection | 4, 5 |
| High | Parse/enrichment terminal failure versus index-only workflow | Required prior failure schedules no index; independent index-only path still runs | 5 |
| High | Ingest supersession/attempt replay/manifest/immutable transfer receipt | Actual Python-to-Go gRPC; all-at-once artifact publication, no repeated byte send | 5 |
| High | Delayed obsolete Qdrant deletion versus new current index | Real PG/Qdrant controlled race; old cleanup cannot remove newly valid points | 5 |
| High | Filename search during failed/pending AI; foreign stale semantic evidence | Live/current/ready validation before rerank/grouping; bounded work/cursor scope | 5, 6 |
| High | Rerank-only failure versus embedding/Qdrant failure | Documented degradation only for rerank; required dependencies fail explicitly | 5 |
| High | Backfill missing/rebuild-index with source replacement | Correct generation/vector space, no original-byte mutation | 5 |
| High | Parser/OCR/document/image regressions and subprocess shutdown | Existing actual PDF/DOCX/PPTX/XLSX/OCR/image corpora and bounded typed diagnostics | 5, 7 |
| High | Worker/server restart mid-copy/purge/processing/projection | Real PG-backed Temporal continuation; fresh current histories | 5, 7 |
| High | Independent shared Python RPC wheel, independent consumer and renamed ingest | Clean install outside checkout imports messages/client/server types and completes real RPC without app imports, vendored stubs or PYTHONPATH; stable output path across rename | 1, 2, 5, 6, 7 |
| High | Fresh dependency install/codegen/Docker without Rust | Locked Go/Python/pnpm and generated imports compile; zero generation drift | 2, 7 |
| Medium | UUIDs, decimal strings, nullable/present fields, machine errors | Protobuf/public OpenAPI and actual response contract checks | 1, 2, 6 |
| Medium | Health/startup/migrations/schema/pool budget | Real configured dependencies; failed setup never returns ready | 2, 7 |
| Medium | Trace across Go/Python/Continue-As-New and replay | Existing telemetry contract; no secret/baggage leakage or duplicate replay exports | 2, 5 |

## Commands and sequencing

All root commands below run from `/home/qninh/projects/openlet`. Native commands target their owning module; there is no root Go module. New commands are explicitly identified and must be implemented before being used as a gate.

| Stage | Command or manifest entry | Classification |
|---|---|---|
| Baseline/discovery | `pnpm --dir e2e exec playwright test --project=api --list` | Existing; verify actual selected titles |
| Typecheck | `pnpm check:e2e` | Existing |
| Shared proof | `go -C packages/go test -tags integration ./authz ./rpc -count=1` | New packages/tests in 1–2 |
| Codegen | `pnpm contracts:generate`, `pnpm contracts:check` | New scripts in 2; pin tools and include schema/format/import/drift checks |
| Go native | App `test`, `check`, `test:integration`, `test:workflow`, `test:replay` package scripts | Existing Account/Workspace contracts, new Go letfs/shared implementations |
| Shared Python packaging/RPC | `uv build --package openlet-python`; `pnpm --filter @openlet/python check`; `pnpm --filter @openlet/python test`; `pnpm --filter @openlet/python test:integration` | New in 1–2; clean-wheel messages/client/server imports and actual RPC outside checkout, consumed by current/renamed app without duplicate stubs |
| Ingest unit/lint | `uv run --locked --package letfs-ingest pytest apps/letfs-ingest/tests -m 'not parser'`; package check | Current-name staging in 5; renamed existing entry points in 6 |
| Parser | `pnpm --filter @openlet/letfs-ingest run test:parser` | Current task in 5, renamed in 6; actual parser/model fixtures required |
| Narrow gateway smoke | `pnpm --dir e2e exec playwright test --project=api --grep 'gateway baseline'` | Existing selection; use `--list` to detect stale zero-test grep |
| Owned environment/recovery tooling | `node --test --test-concurrency=1 e2e/setup/environment.test.ts e2e/setup/recovery.test.ts` | Existing, extended for graph/ingest |
| Whole system | `pnpm --dir e2e exec playwright test --project=api` | Existing, migrated direct routes and real gRPC chain |
| Current histories | `OPENLET_HISTORY_DIR="$PWD/.local/api-e2e/histories" pnpm test:replay` | Existing root task; new letfs Go replay in 5–7 |
| Final native set | `pnpm build`; `pnpm check`; `pnpm test`; `pnpm exec turbo run test:workflow`; `pnpm exec turbo run test:integration --concurrency=1` | Existing entry points adapted to all modules |
| Provider | `make test-provider` and documented opt-in Clerk smoke | Existing opt-in; never load production/developer credentials implicitly |

Run final replay after the complete current suite exports its histories. During Phase 5, use separate native fixtures/history paths so old Rust histories are never presented as Go acceptance. Keep model-dependent parser work separate from inexpensive unit checks, but it remains required local acceptance when its model fixture is available.

## Recovery acceptance

1. Verify backup ownership and writer/capability drain before touching existing data.
2. Capture canonical databases, relevant Temporal state, object data and Qdrant using the current permanent recovery tool with new graph/projector inventory.
3. Restore into a fresh fenced project and a matching checkout/dependency/schema set. Fix or rebuild SpiceDB datastore MVCC state by the supported route; drain old writers and restart sync from restored current business records.
4. Verify repository role/action policy, canonical membership assignments and Workspace-owned storage references, grant/revoke/delete parity, exact inline/object bytes, current search and interrupted workflow continuation.
5. Delete the projection in an isolated test, rebuild from canonical owners, interrupt/resume rebuild, and verify restored current grants/revocations after synchronization drains. Only then reopen admission.
6. Reject corrupt snapshots, unsupported external-object backup, mismatched ownership and incomplete restores before unsafe resume.

Adding the sixth database to a dump list alone does not satisfy these steps. External provider object backup remains the existing separate release requirement; local MinIO success is not evidence for R2 restore.

## Evidence recording

Each executing phase records exact commands, dependency versions and observed pass/fail results in its evidence report. Use PASS, FAIL and NOT RUN distinctly. Never mark a scenario complete from test count, zero-test selection, a mocked database/graph, old histories or inspection alone. Keep signed URLs, tokens, private env and document contents out of logs/artifacts.

Final acceptance records required local gates separately from opt-in real Clerk/S3 smoke. Paid LLM quality/evaluation is outside this plan. Do not weaken tests, hide parser/model absence or claim deployment/performance was tested during planning.
