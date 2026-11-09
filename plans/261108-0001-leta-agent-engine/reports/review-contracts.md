# Final contract and operations review

> Historical review of the superseded draft. All items 1–42 have since been reviewed; accepted corrections are incorporated in the [current 19-phase plan](../plan.md) and [design contract](../design-contract.md). Old phase numbers, line references and recommendations below describe that earlier draft and must not be implemented as current requirements. Navigation links now point to replacement owning phases.


Status: DONE

Reviewed the current English plan, design/tool contracts, Phases 01–03 and 14–18, plus the Phase 11 compaction contract where it consumes Phase 01 metadata. This is a read-only source/plan review; no implementation, database access, migration, dependency installation, service startup, commit or deployment was performed.

No unresolved implementation-blocking finding remains in this reviewed slice after the corrections described below. Dependency compatibility and crash/restart guarantees remain implementation acceptance gates, not results established by this review.

## Resolved during final review

### Model catalog supplies compaction limits

- Phase 01:42 now requires positive `context_window_tokens` and `max_output_tokens`, with output strictly smaller than context, instead of guessing the model's limits.
- Phase 11:93 derives the usable input budget from those fields and system/tool overhead, makes trigger/retention tunable, and requires a verified complete older-prefix summarization path if the pinned middleware cannot disable its default summarization tail limit.
- Phase 15:29 exposes safe context metadata while keeping provider credentials private.
- This resolves the missing producer for Phase 11's model-aware context contract. The configured model request and deterministic boundary tests still need to prove that the output reservation is actually applied.

### Native one-shot retries preserve consumed state

- Phase 14:45–46 now treats an already matching native definition as success, preserves a consumed one-shot allowance through metadata/pause edits and Activity acknowledgement loss, and uses the native conflict-retry update callback rather than deleting/recreating a schedule.
- The already-due path reuses the saved occurrence Workflow/result; a metadata edit does not compare newly edited content with a previously delivered body or rerun a completed snapshot read.
- Pinned SDK evidence: `temporalio/client/_schedule.py` at tag `1.35.0`, lines 240–263 defines callback-based update and possible callback re-execution; lines 1009–1020 defines limited/remaining actions and the consumed-zero behavior.
- Source: <https://github.com/temporalio/sdk-python/blob/1.35.0/temporalio/client/_schedule.py>.

### Matching-times continuation is explicit and bounded

- Phase 14:49 recognizes the silent 1,000-result server cap, marks a full result potentially truncated, and continues at the last returned timestamp using the exclusive start. It binds the cursor to caller/root/filter/range and limits definitions, calls and concurrency.
- Temporal Server `v1.32.1` scheduler source sets `maxListMatchingTimesCount = 1000` at lines 92–94. Its `handleListMatchingTimesQuery` at lines 1165–1189 starts from the request start, repeatedly obtains the next match, and stops only after the end or the cap; the end comparison is inclusive.
- Nominal schedule metadata is source-backed: the same file's lines 1586–1599 sets `TemporalScheduledStartTime` from nominal time and `TemporalScheduledById` from the schedule identity. Phase 14:44 correctly requires real deployed-server/SDK verification instead of substituting delivery wall time.
- Source: <https://github.com/temporalio/temporal/blob/v1.32.1/service/worker/scheduler/workflow.go>.

### Snapshot/replay suppresses both orphan suffixes and duplicate completed content

- Phase 16:38 now distinguishes fully materialized snapshot block IDs from fresh post-head START IDs. It suppresses all replayed text/argument protocol for the former and unknown CONTENT/ARGS/END for the latter, while allowing distinct tool-result/domain updates.
- This covers both races: the captured head falls inside an unfinished block, or that block completes and enters PostgreSQL while the initial snapshot is being fetched. Merely accepting IDs present in the snapshot would append the already complete suffix again.
- AG-UI's event contract requires concatenating text/argument deltas in order: `docs/concepts/events.mdx` lines 184–212, 231–246 and 315–354. Source: <https://github.com/ag-ui-protocol/ag-ui/blob/main/docs/concepts/events.mdx>.
- Phase 16:34 now separates best-effort stream publication from Mirage cache-dependent filesystem failure handling, referring to Phase 07 rather than promising an unverified automatic cache bypass.

### Recovery includes model/deployment configuration

- Phase 17:44 now explicitly extends the existing `CONFIGURATION` capture, manifest and restore validation with the model catalog and generated Leta/Redis configuration. It relocates the catalog to the restored owned state path, updates `LETA_MODEL_CATALOG_PATH`, and validates persisted selections before reopening.
- This closes a concrete gap in the earlier DATABASES/WRITERS-only wording: current `scripts/operations/recovery.py:25–30` enumerates captured nonsecret configuration, and `:293–301` copies only that fixed set plus protected secrets. A restored domain/checkpoint database alone could not supply the Phase 01:40–42 required catalog.
- The smallest fix remains an extension of existing recovery ownership and fixtures, with no extra backup service.

## Verified current-service boundaries

| Concern | Source evidence | Current plan consequence |
| --- | --- | --- |
| Managed account identity | `apps/account/internal/account/store.go:61–77` accepts a stable UUIDv7 and rejects conflicting type/owner. `apps/account/internal/account/service.go:118–135` separates owning SQL/relationship application from the public path's fresh ID. | Phase 02:35–40 and :81–101 reuse owning behavior, require the verified human delegated owner, keep public creation intact and repair relationship acknowledgement under the same identity. |
| Native caller scope and errors | `apps/account/internal/transport/grpc/server.go:35–59` currently allows Workspace-only lookup and maps only lookup-specific faults. | Phase 02:38–42 and :90–97 add exactly two Leta methods with actor delegation and permanent conflict classification; Workspace lookup remains separate. |
| Workspace command identity | `apps/workspace/internal/temporal/relationships.go:82–91` currently replaces the key. `apps/workspace/internal/workspace/mutation_receipt.go:17–46` currently records presence/hash and completes for 24 hours. | Phase 03:81–87 and :143–147 preserve supplied keys, hash stable ingress fields, distinguish pending/complete and retain completed internal receipts indefinitely, preventing an old grant from undoing a later revoke across Continue-As-New. |
| Scope ownership and cleanup | `apps/workspace/internal/workspace/relations.go:28–59` handles member defaults; :112–143 rebuilds with `defaults=false`; :166–202 currently requires manage_access and directly applies scope effects. | Phase 03:39–48 and :85–91 add exact own-agent admission, retained binding, revoke-only self/owner exception, W-bounded target cleanup and mandatory owner viewer while preserving discretionary grants. |
| Archived owner files | `apps/letfs/internal/filesystem/nodes.go:175–189` checks scope authority for node reads; :197–211 checks each BatchStat scope, without requiring filesystem.read. | Phase 03:76–77's retained owner self-view and scope-root BatchStat route can preserve personal files after owner workspace leave without granting shared workspace access. |
| Bounded view authorization | `packages/go/authz/client.go:43` owns fully consistent BulkCheck with bounded resource identities; `apps/letfs/internal/filesystem/nodes.go:197–211` validates filesystem/scope binding and actual metadata permission. | Phase 03:70–77 separately pages candidates, checks the three actions in bounded calls, advances by scanned candidates and treats cached/view results as nonauthoritative. |
| Coordinated capture | `scripts/operations/recovery.py:16–44`, :201–212 and :251–271 enumerate databases/writers and verify dumps. | Phase 17 extends this owner with Leta/checkpoints/native schedule state; Redis remains disposable. |
| CI execution ownership | `.github/workflows/check.yaml:31–40` executes locked native Turbo tasks sequentially and a distinct fresh-history replay. | Phase 17:46 and Phase 18:62–65 extend existing commands and required histories instead of introducing another test framework or treating absent histories as success. |

## Scope and document consistency

- The reviewed contract preserves the accepted resource-owner approval rule, six Workflow types, current-agent history tools and exactly one schedule product. No outbox, global poller, operation/delivery entity, dangerous-tool policy or model-call budget was reintroduced.
- Canonical `read_history(entry_id,start_line,max_lines)` now agrees between tool-contracts.md:14 and Phase 11:111.
- Reviewed phase files contain concrete boundaries, target files, acceptance checks and rollback details; no stale implementation skeleton was found in the assigned phases. The root reviewer separately owns the whole-plan link/frontmatter sweep and other phases.

## Verification limits

The requested `/tmp/leta-research` source cache was absent. Current repository symbols were inspected through CodeGraph before direct source reads; pinned upstream schedule source and the published AG-UI event contract were fetched directly. No paid-model call or runtime integration test was performed. The plan's explicit compatibility, one-shot/native metadata, restart, authorization and restore experiments must still pass during implementation.

Status: DONE
Summary: Assigned account/workspace, model, scheduler, streaming and operations contracts are coherent after the targeted final corrections. No additional subsystem or product decision is needed.
Concerns/Blockers: No unresolved plan blocker found in this slice; implementation acceptance remains unexecuted.
