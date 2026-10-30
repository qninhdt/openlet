---
title: "Phase 5: Acceptance, Recovery, Operations, and Documentation"
status: completed
priority: P1
effort: 4d
dependsOn: [phase-04-zip-export]
---

# Phase 5: Acceptance, Recovery, Operations, and Documentation

## Objective

Prove the complete direct-storage, hybrid-artifact, Python processing, ZIP export, cleanup, and coordinated recovery behavior through real PostgreSQL/SeaweedFS/Temporal/Workspace/letfs/Python boundaries; update durable contracts/docs from implemented behavior and preserve R2 release gates honestly.

## Completion Evidence

See the [acceptance and recovery implementation report](../reports/implementation-261030-acceptance-recovery.md) and [independent ZIP/recovery review](../reports/review-261030-zip-recovery.md). Current-revision comprehensive E2E, replay and verification passed. The coordinated local drill passed; external R2 coordinated recovery remains NOT RUN and a production gate.

## Baseline Evidence

- Real dependency boundaries are required by `docs/testing.md`; letfs integration starts PostgreSQL/S3/Temporal and E2E pins SeaweedFS. Use those existing harnesses rather than mocks for storage/workflow contracts.
- Current provider smoke covers ordinary object operations, not browser-compatible signed conditional/checksum/multipart/Range behavior (`services/letfs/src/storage/provider_smoke.rs:10`).
- Workflow replay consumes recorded histories. Phases 3 and 4 must introduce real `ProcessFile` and `ExportArchive` history generation and selectors before this phase can broaden them.
- Local backup pauses the storage-maintenance schedule (`scripts/backup-local.sh:15`) and refuses while current writers remain (`scripts/backup-local.sh:19`). Restore is isolated and maintenance remains paused (`scripts/restore-local.sh:53`; `scripts/backup-restore-drill.sh:39`). Extend the writer/drain set for direct capabilities, Python, exports, and existing maintenance.
- `docs/operations.md` currently assumes Envoy-only traffic, 120-second object transfers, and private storage ports. Update it only after direct endpoint/CORS/drain behavior is implemented and verified.

## End-To-End Requirements

- [x] Exercise direct user and Python inline/object uploads through prepare-transfer-complete, including arbitrary binary inline bytes, max inline/max file bounds, independent multi-file results, commit-time quota, overwrite preservation, no Workspace/letfs object-body relay, and no impossible backend SHA-256 receipt.
- [x] Prove browser-compatible single PUT on pinned SeaweedFS and R2: exact size, `Content-MD5`, conditional create, signed header removal/change, concurrent replay, lost response, late PUT, reachable signer host, exact CORS, and no unchecked fallback.
- [x] Prove native multipart create/part retry/order/checksum/frozen intent/complete/abort/list-if-needed, lost completion response, concurrent abort, process death, incomplete-upload lifecycle, and no custom chunking/per-part ledger.
- [x] Verify direct GET descriptor/redirect, safe content disposition, Range, URL expiry/renewal pinned to the same revision/content, overwrite mismatch, and bearer-capability semantics. Inline range/content remains bounded and separate from text-edit strings.
- [x] Run actual Rust `ProcessFile` -> Python `process_file` with pinned Docling/models. Assert original bytes and exact child trees/content for PDF/DOCX/PPTX/XLSX, including tables/images, empty sheets, singleton/isolated cells, and no extra manifest/index/JSON/run output.
- [x] Exercise normal paths, raw IDs, scoped root aliases, cwd/trailing/parent traversal, root collision preflight, every destination operation, cross-scope refusal, and strict-file-ancestor readonly. Source remains writable; copied-out artifacts become writable.
- [x] Cover source/ancestor copy/move/trash/restore/purge, inline/object source with children, empty and >64-node forests, filesystem deletion, publication/copy snapshot ordering, and independent source/artifact quota/node accounting.
- [x] Test ordered processing generations, same-generation UUID conflict, stale source/output/complete/abort, more than sixteen artifact outputs as one admitted job, lost publish response, worker SIGKILL/new scratch, heartbeat/cancellation, Temporal restart/replay, exhausted attempt, overwrite/quota/trash fences, and no restored auto-restart.
- [x] Exercise normal single-file bypass and normal folder/multi-selection ZIP original-only traversal; explicit artifact ZIP, direct artifact file/folder, selected roots/empty dirs, overlap deduplication, deterministic name conflicts, safe paths, inline/object bytes, changed/unavailable input failure, retries, ZIP64/bounds, stale attempts, expiry, direct Range, and no regeneration.
- [x] Assert bounded/set-based DB behavior for multi-file prepare, artifact publish/lifecycle, and ZIP enumeration/inline reads; fail tests on N+1 regressions or missing expected suite/history.

## Recovery, Cleanup, And Backup

- [x] Reuse maintenance/object-deletion evidence across active uploads, copy, processing, and exports. Test issued URL expiry plus documented transfer grace, ambiguous late writes, repeated DELETE/HEAD observations, live-key protection, rejected commit cleanup, native multipart abort, and eventual `exports/` expiry without ordinary `objects/` age deletion.
- [x] Backup closes public mutation/export/processing admission, stops Python and Rust writer execution as appropriate, drains known upload/multipart/export/processing operations and issued capabilities/inflight ambiguity, pauses maintenance, then stops DB/object writers before capture.
- [x] Restore source/children, inline/object data, upload/operation/attempt/result/cleanup state, workflow histories, export expiry, and pinned model/image identity into isolation. No processing/export/maintenance dispatch occurs until explicit resume; readiness checks remain read-only.
- [x] Keep the existing coordinated R2 object-plus-five-database recovery requirement as a production release gate. The automated local drill covers SeaweedFS only. Missing credentials/provider procedure remains `NOT RUN`.

## Acceptance Matrix

| Category | Required evidence |
|---|---|
| Direct transport | User + Python inline/single/multipart, provider evidence, idempotency/reconciliation, hard quota, no proxy bytes. |
| Downloads | Inline and direct GET, Range renewal/content pin, safe headers, expiry/revocation limitation. |
| Artifacts | Four real formats, exact trees/bytes, paths/aliases/readonly, lifecycle/copy/invalidation/accounting, >16 outputs. |
| ZIP | Original-only folders, explicit artifacts, safe deterministic paths, mixed storage, bounds/failure/retry/expiry/Range. |
| Recovery | Lost responses, stale attempts, worker/Temporal restart, late writes, ambiguous deletion, completed-result reuse. |
| Backup | All writers/capabilities drained, isolated restore paused, explicit resume only, external R2 gate separate. |

## Files

Create only the bypass fixtures and recovery tests not already owned by earlier phases:

| File | Purpose |
|---|---|
| `services/letfs/processor/tests/fixtures/image.png`, `note.txt`, `legacy.doc` | Real processing-bypass inputs. |
| `tests/e2e/processing_recovery_test.go` | Deterministic source/attempt/copy/response-loss/restart barriers. |

Modify:

| Files | Change |
|---|---|
| `tests/e2e/storage_test.go`, `processing_test.go`, `zip_export_test.go` | Complete public direct-storage, processing, lifecycle, ZIP and authorization journeys. |
| `services/letfs/tests/integration.rs` | PG/S3 upload, artifact forest, export, provider, cleanup and query-bound regressions. |
| `services/letfs/tests/workflow-replay.rs`, `tests/e2e/history_test.go` | Recovery assertions and mandatory actual ProcessFile/ExportArchive histories. |
| `services/letfs/src/storage/provider_smoke.rs` | R2/SeaweedFS presigned conditional/size/checksum/multipart/CORS/GET Range checks where runnable. |
| `scripts/test-integration.sh`, `scripts/test-workflow.sh`, `scripts/verify-foundation.sh`, `Makefile` | Complete selectors, preserve comprehensive `all`, unknown/zero-selection failure, narrow port exposure, Python gates. |
| `scripts/backup-local.sh`, `scripts/restore-local.sh`, `scripts/backup-restore-drill.sh`, `tests/e2e/backup_test.go` | Direct capability/processing/export drain and paused isolated recovery. |
| `docs/architecture.md`, `docs/data-model.md` | Direct byte flow, upload/session ownership, file-plus-children, export lifecycle and accounting. |
| `docs/api-contracts.md`, `docs/workflows.md` | Caller-selected modes, descriptors, processing/export workflows, idempotency and failure semantics. |
| `docs/testing.md`, `docs/setup.md`, `docs/operations.md` | Actual commands/selectors, endpoints/CORS, limits, provider gates, shutdown/drain/backup/rollback. |
| `docs/README.md` | Navigation only if the existing docs index requires it. |

## Implementation Steps

1. Reuse earlier real fixtures/histories and add only bypass/recovery cases. Add deterministic barriers and wait for observable conditions with deadlines; never use arbitrary sleeps or retries to hide races.
2. Complete direct browser/Python provider tests, object-relay absence assertions, GET Range renewal, multipart/lost-response cleanup, and bounded query measurements.
3. Complete artifact path/lifecycle/copy/invalidation/accounting and cross-language recovery journeys, including more than sixteen outputs.
4. Complete ZIP traversal/path/input-change/attempt/expiry/Range/limit/query journeys and actual ExportArchive replay.
5. Extend backup/restore admission closure, worker/capability drain, paused isolated restore, and explicit resume. Preserve the existing maintenance schedule owner and avoid an extra startup scan.
6. Update the smallest owning docs and public/internal contracts from verified implementation. Run focused gates first, then comprehensive gates once; record external R2 checks separately.

## Acceptance Commands

Focused commands become valid only after their owning phases add selectors/routes:

```sh
uv run --project services/letfs/processor pytest services/letfs/processor/tests
make test-integration SERVICE=letfs TEST=direct-storage
make test-integration SERVICE=letfs TEST=artifacts
make test-integration SERVICE=letfs TEST=zip-export
make test-e2e TEST=processing
make test-e2e TEST=zip-export
make test-workflow TEST=process-file
make test-workflow TEST=export-archive
```

Complete gates:

```sh
make fmt
make verify
make test-integration SERVICE=all TEST=all
make test-e2e TEST=all
make test-workflow
make backup-restore-drill
make test-provider
```

The targets exist in baseline, but the named direct-storage/artifacts/zip-export integration selectors, processing/zip-export E2E routes, Python coverage, and process-file/export-archive workflow selectors do not. Comprehensive `all` must be updated to run them and fail if required histories/suites are missing. External provider checks without credentials/procedure are `NOT RUN`, not release success.

## Todo

- [x] Complete real direct-storage/browser/provider and no-proxy-byte coverage.
- [x] Complete processing/hybrid lifecycle/accounting/recovery and >16-output coverage.
- [x] Complete ZIP traversal/input-change/attempt/expiry/Range/query coverage.
- [x] Complete selectors, actual histories, comprehensive `all`, and provider gates.
- [x] Extend backup/restore drain and explicit-resume recovery.
- [x] Update durable contracts/docs and run focused then complete gates.

## Risks And Rollback

Provider/browser behavior, parser/model variance, archive amplification/path safety, and externally ambiguous writes are high-impact risks. Stop release on any liveness, readonly, final-byte, quota, stale-attempt, Range, cleanup, or paused-restore failure. Retain diagnostic histories and cleanup evidence, close admission, drain capabilities/workers, and preserve read/delete compatibility until safe rollback. Independent code review is required before release.
