# Direct storage, processing and ZIP plan validation

Date: 2026-10-30, Asia/Ho_Chi_Minh. Scope: documentation-only revision requested after the user accepted the transport, inline selection and ZIP design.

Plan: [Direct Storage, Artifact Processing, and ZIP Export](../261029-1624-artifact-file-processing/plan.md).

## Scope and accepted decisions

HOLD SCOPE. Update the existing plan rather than create a duplicate. Preserve hybrid parent-edge artifacts, root UUID aliases, readonly ancestry, source-copy snapshots, terminal trash fencing, invalidation accounting and agreed Docling layouts. Add the approved direct transfer and ZIP work, without product implementation.

1. Callers choose inline/object. Inline is bounded bytea; no server content sniffing, storage fallback or relocation. Separate text-edit string validation remains intact.
2. Ordinary object transfer bypasses HTTP backends. Persist prepare/session before URL issuance, verify provider evidence, and publish metadata/quota/result once. No upload/download workflow or physical staging-to-final copy.
3. Shared transport supports conditional single PUT and native multipart, provider-validated integrity, new keys on overwrite, independent multi-file completion, and hard commit-time quota without reservations.
4. One Rust ProcessFile workflow invokes one Python activity using scoped letfs APIs and direct S3. Output admission is grouped, and the complete child tree publishes atomically.
5. Folder ZIP traversal includes ordinary file payloads and stops at files, excluding attached generated children. Explicit artifact export uses the same ZIP engine. One ExportArchive workflow/activity writes a temporary S3 object, then authorized clients download it directly. Default retention is 24 hours; physical lifecycle expiry is eventual.
6. Reuse maintenance, native multipart abort and existing operation state. Correct URL-expiry/inflight cleanup, reachable signing endpoints, CORS, API/checksum contracts, tests and backup/restore.

No new interview was needed: these decisions were explicitly discussed and accepted before the instruction to update the plan. Implementation questions about pinned providers, ZIP/parser APIs and numeric limits remain execution gates, not claimed verification.

## Phase and file changes

The skill's planner authored the revision in its assigned plan directory. Two phase stubs were scaffolded using `ak plan add-phase`, read, then renamed/reordered because the installed CLI only appends phases. The controller reviewed all resulting files and corrected integration gaps.

| Phase | Current file | Ownership |
|---|---|---|
| 1 | [Direct storage](../261029-1624-artifact-file-processing/phase-01-direct-storage.md) | Existing transport/schema/config/contracts/provider checks |
| 2 | [Hybrid artifacts](../261029-1624-artifact-file-processing/phase-02-artifacts.md) | Existing hybrid plan, adjusted to shared publication |
| 3 | [Processing](../261029-1624-artifact-file-processing/phase-03-processing.md) | Python/Docling and atomic output completion |
| 4 | [ZIP export](../261029-1624-artifact-file-processing/phase-04-zip-export.md) | Archive workflow/activity and temporary delivery |
| 5 | [Acceptance](../261029-1624-artifact-file-processing/phase-05-acceptance.md) | Real boundaries, recovery, provider gates, backup and docs |

All implementation remains pending. Phase ordering is sequential; migrations are allocated in execution order without conflicting owners. Prior reports retain historical paths and decisions; the old validation report is explicitly historical in the current index.

## Source verification

Five-phase review used the fact, flow, scope and contract lenses. Seventy-five existing baseline anchors were mechanically checked, fifteen per phase, all found. This establishes source surfaces, not future behavior.

| Phase | Verified baseline anchors |
|---|---|
| 1 | uploads create/receive/finalize/abort; storage builder; inline/max-file configuration; Workspace upload handler; content handler; upload candidate-key schema; file_data bytea; expiry; provider-smoke storage consumer; upload E2E; integration selector guard |
| 2 | path resolver; Node; read/create/modify; inline/durable copy; restore/purge; durable deletion prepare/batch; parent schema; copy source fields; deletion items; name validation |
| 3 | installed dependency manifest versions; main storage consumer/App; start_copy; typed activity scheduling; maintenance workflow/schedule; config generator/tests; integration storage consumer; history writer; replay; workflow selector script; pinned Temporal image |
| 4 | operations and deadline schema; operation lookup; stable workflow identity; heartbeat wrapper; object cleanup; filesystem session; App; Workspace operation facade; both OpenAPI files; history writer/replay; E2E selector guard; S3 builder |
| 5 | verify/provider/backup Makefile targets; Testcontainers integration; zero-selection/history guards; query instrumentation; dump/isolation/drill scripts; contract validator; testing/operations docs; pinned SeaweedFS image; backup E2E |

Additional contracts checked directly:

- Storage builder has three current consumers: main, integration harness and provider smoke; Phase 1 owns all three.
- Current defaults are 256 KiB inline, 100 MiB max file and sixteen outstanding jobs. The plan does not silently increase max-file size or count every artifact output as another admitted job.
- Upload key is currently mandatory; expiry and abort assume a string. Keyless inline migration explicitly updates these callers.
- Operations currently allow running/succeeded/discarding/failed. Export status meanings cannot silently bypass that constraint.
- Tests currently assume backend SHA-256 receipts and Envoy-only port exposure. The plan assigns their intentional transport-contract updates.
- Existing integration and workflow/E2E scripts do not implement the new named selectors. Each phase must introduce its selectors and actual replay histories before using them.

## Whole-plan sweep and corrections

Reread the index and all five phases. Checked sixteen decision groups: caller-selected bytes, inline safety, direct transfer, sessions/idempotency, conditional single PUT, multipart, overwrite/quota, GET/Range, artifact ownership, attempt/source fencing, grouped admission, ZIP traversal, ZIP publication/expiry, cleanup, endpoints/CORS and backup/test routing.

The sweep corrected missing main-worker registration ownership, ZIP E2E script/config ownership, explicit archive start/result reconciliation and heartbeat/cancellation, Workspace membership authorization versus letfs filesystem scope, retained trailing-path/alias/trash details, and removed an unnecessary future callback/transaction-hook abstraction. No active physical-copy/readback or server-classification requirement remains. Bounded inline SHA-256 identity is retained for processing source identity; it is distinct from rejected full-object S3 readback.

No unresolved design contradiction was found. The plan is an implementation specification; runtime compatibility is still unverified.

## Mechanical results and task state

`ak plan validate` passed. `ak plan parse` reports five phases and 99 phase tasks with zero complete; five index acceptance items also remain pending. A full read/link/dependency check covered the index, all five phase files and this report: all thirteen local links exist, dependencies form one ordered chain, and no retired phase filenames or checked implementation tasks remain in the active plan. `ak plan reindex --apply` synchronized the local index after a SQLite backup, and the existing worktree-local pointer selects this plan. No live task CRUD API is exposed; Markdown remains task authority.

No product code, migration, application schema/data, dependency, provider resource or evergreen documentation was changed. Only plan documents, the local plan-index projection/pointer and a [local journal](../journals/2026-10-30-openlet-direct-storage-and-zip-plan-update.md) changed. No background process/container was started, and no runtime test/build/provider check ran. The existing untracked workspace was preserved. AgentWiki publication was skipped.

## Handoff

Implementation starts at Phase 1 only when requested, with `/ak:cook /home/qninh/projects/openlet/plans/261029-1624-artifact-file-processing/plan.md`. Before builds/models/containers, recheck disk; prior research observed roughly 507 MiB free. R2 direct-transfer and coordinated object-plus-five-database recovery remain explicit release gates; unavailable checks are NOT RUN.

Unresolved product questions: none.
