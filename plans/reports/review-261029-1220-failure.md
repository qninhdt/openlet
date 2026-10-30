# Failure-Mode Review: Openlet Backend MVP

## Scope and verdict

Reviewed the plan, all six phase files, and the architecture, data-model, API-contract, workflow, and testing contracts. This is a document review only; planned application commands were not run. The plan has four material safety/implementation gaps that should be repaired before execution.

## Findings

### 1. High — Retry-key trash, restore, and direct file purge have no durable replay contract

**Evidence:** The public contract requires a retry key for trash, restore, and purge (`docs/api-contracts.md:70`, `docs/api-contracts.md:72`, `docs/api-contracts.md:73`), while phase 3 implements trash/restore before letfs operation storage is introduced for copy in phase 4 (`plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:67`, `plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:30`). Direct file purge is deliberately a single transaction (`plans/261029-1220-openlet-backend-mvp/phase-05-durable-lifecycle.md:62`), but only multi-step operations are explicitly required to retain request identity and result (`docs/data-model.md:9`).

**Failure path:** A trash transaction commits, or restore/file purge commits, but the HTTP response is lost. The client retries with the required key. The original locator is now hidden, reattached, or deleted, so normal lookup returns not-found/conflict instead of the committed result. For purge this also makes it impossible to distinguish a successful lost response from a request that never committed; for trash/restore it violates the promised same-key behavior.

**Smallest fix:** In phase 3, define a letfs synchronous-operation row (the existing `operations` responsibility is enough; no new framework) for keyed trash/restore, and reuse it for direct file purge. Bind caller/scope/action/key/fingerprint and commit the terminal result in the same transaction as the mutation. Specify that identical retries replay the result and mismatched fingerprints conflict, including after the resource changes visibility.

### 2. High — Directory purge quota accounting is specified as both one debit and per-batch debit

**Evidence:** Phase 5 describes `PurgeTrash` as making “one quota debit” and repeats “debit once” in its implementation and tests (`plans/261029-1220-openlet-backend-mvp/phase-05-durable-lifecycle.md:30`, `plans/261029-1220-openlet-backend-mvp/phase-05-durable-lifecycle.md:63`, `plans/261029-1220-openlet-backend-mvp/phase-05-durable-lifecycle.md:85`). The authoritative data invariant instead says each purge batch subtracts the charged nodes actually removed in that transaction (`docs/data-model.md:59`), and the workflow commits removed nodes, quota debit, and cleanup rows together per batch (`docs/workflows.md:53`).

**Failure path:** An implementer follows the phase wording and debits the entire subtree once before bounded deletion. A crash then leaves undeleted charged nodes while usage has already fallen, allowing quota overcommit. Alternatively, later batches follow the shared deletion core and debit again, undercounting usage. Avoiding both would require an unplanned aggregate snapshot/fencing scheme.

**Smallest fix:** Replace “one debit/debit once” in phase 5 with “each charged node is debited exactly once, transactionally in the batch that removes it.” Make the test assert final delta plus crash/retry correctness across multiple batches, not a single counter update.

### 3. High — Same-key retry after a workflow closes before first-activity admission is an unresolved protocol decision

**Evidence:** The API contract explicitly says a run that closes before admission needs an “explicit reuse policy and a durable-admission recheck” (`docs/api-contracts.md:17`). The plan otherwise requires starting Temporal before mutation and returning only after first-activity admission (`plans/261029-1220-openlet-backend-mvp/phase-02-identity-workspaces.md:56`, `plans/261029-1220-openlet-backend-mvp/phase-02-identity-workspaces.md:57`), while workflow identity includes the same request key (`docs/api-contracts.md:15`). No phase chooses whether the same workflow ID may be reused, receives a new run ID, or is permanently terminal when no DB admission row exists.

**Failure path:** Temporal accepts the start, the workflow fails or is terminated before its first activity commits admission, and the caller receives a timeout. A same-key retry finds a closed workflow but no authoritative DB operation. Depending on SDK reuse defaults, it can be rejected forever or start a second run without a specified correlation rule, making 503 retry behavior provider/version dependent.

**Smallest fix:** Add one rule to the admission contract and phase-2/phase-4 workflow tests: after a closed run, recheck the caller-bound DB admission row; if absent, start a new run under a deterministic retry/run policy for the same logical operation, and if present, return/poll that operation. Pin the exact Temporal workflow-ID reuse/conflict option during implementation.

### 4. High — The backup maintenance gate can still admit direct writes

**Evidence:** “Admission” is defined elsewhere as the durable Temporal start/first-activity protocol (`docs/api-contracts.md:13`, `docs/workflows.md:65`), but many mutations are intentionally direct, including text edits, move, upload finalize, trash/restore, and file purge (`docs/workflows.md:29`). The backup procedure says to stop “admission/Schedules” and drain writers (`plans/261029-1220-openlet-backend-mvp/phase-06-integration-operations.md:51`, `docs/architecture.md:103`) without explicitly rejecting these direct public/internal mutations.

**Failure path:** Operators disable durable workflow admission and pause schedules, then begin sequential dumps of the separate databases and object inventory. A direct upload finalize, overwrite, trash, or purge commits during the window. The letfs dump and preserved object set can then represent different points, or the Workspace and letfs dumps can disagree, despite every durable workflow being stopped.

**Smallest fix:** Define backup maintenance mode as rejecting **all mutating public and internal HTTP routes**, not only durable starts; allow only health/read/status as documented. Wait for active HTTP streams/transactions, activities, and S3 writes to reach zero, then stop workers/Temporal writers and capture every service/Temporal database plus the immutable object inventory before reopening mutations.

## Unresolved questions

- Which exact Temporal workflow-ID reuse/conflict option will implement finding 3 for the pinned Go and Rust SDK versions?
- Will the selected S3 provider preserve the drained object inventory by versioning/snapshot or by a guarded immutable copy during the maintenance window?

Status: DONE_WITH_CONCERNS

Summary: Four concrete plan defects remain: missing replay state for keyed direct mutations, contradictory purge debit semantics, an unresolved pre-admission retry policy, and an incomplete backup write gate.

Concerns/Blockers: Resolve these document contracts before phase 1 execution; otherwise response loss, crash recovery, or backup timing can produce observable inconsistency or quota undercount.

## Fix verification

Rechecked only the four findings against the revised contracts and phases.

- **Finding 1 — Partially resolved.** The replay contract is now explicit and correct: keyed inline copy/trash/restore/file purge commit scoped fingerprint/result with the mutation and check replay before target lookup (`docs/api-contracts.md:21`, `docs/data-model.md:76`, `plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:68`, `plans/261029-1220-openlet-backend-mvp/phase-05-durable-lifecycle.md:62`). One phase-ordering prerequisite remains: phase 3 calls these `operations` rows “existing” (`plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:32`) but does not explicitly create the table, while phase 4 still says to add the copy-operation migration (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:66`). Smallest repair: state in phase 3 migration step that it creates the generic letfs `operations` table; phase 4 only extends/uses it for durable copy fields/items.
- **Finding 2 — Resolved.** Purge now debits each charged node exactly once in the transaction/batch that removes it, with matching workflow and integration-test language (`plans/261029-1220-openlet-backend-mvp/phase-05-durable-lifecycle.md:63`, `plans/261029-1220-openlet-backend-mvp/phase-05-durable-lifecycle.md:75`, `docs/workflows.md:53`).
- **Finding 3 — Resolved.** Running executions are attached; closed executions check durable state before an explicit same-ID replacement, and first-activity uniqueness fences late attempts. Owning phases include recovery tests (`docs/api-contracts.md:17`, `plans/261029-1220-openlet-backend-mvp/phase-02-identity-workspaces.md:78`, `plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:83`, `plans/261029-1220-openlet-backend-mvp/phase-05-durable-lifecycle.md:86`).
- **Finding 4 — Resolved.** Backup maintenance now rejects all mutating public/internal HTTP, drains HTTP/DB/activity/S3 writers, stops service and Temporal writers, and requires a provider-specific preservation/restore procedure (`plans/261029-1220-openlet-backend-mvp/phase-06-integration-operations.md:51`, `plans/261029-1220-openlet-backend-mvp/phase-06-integration-operations.md:64`, `docs/architecture.md:103`).

Verification status: DONE_WITH_CONCERNS

Remaining blocker: make phase 3 the explicit creation owner of the generic letfs `operations` table so its keyed direct operations do not depend on a phase-4 migration.

## Revised retry-contract verification

The accepted contract changed after targeted research: short trash/restore/file-purge operations no longer promise stored-response replay. Rechecking only that decision and the prior migration concern:

- **The prior operations-migration blocker is resolved and superseded.** Phase 3 now explicitly creates the base letfs `operations` table for direct inline-copy duplicate prevention, and states that phase 4 extends it for durable copy (`plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:32`, `plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:61`). Trash/restore/file purge correctly do not depend on those rows.
- **Direct destructive retry behavior is consistently specified.** The API requires the original stable identity and `If-Match`, permits 404/409/412 after an ambiguous response, and requires authorized state reconciliation rather than claiming exact replay (`docs/api-contracts.md:23`, `docs/api-contracts.md:74`, `docs/api-contracts.md:77`). The data model preserves monotonic revisions and fresh trash-entry identity across cycles so delayed old intent cannot affect a later cycle (`docs/data-model.md:76`).
- **Path reuse is fenced.** Existing path targets require `expected_node_id`; path-selected parents require `expected_parent_id`, both checked with revisions under the mutation lock (`docs/api-contracts.md:9`, `docs/data-model.md:51`, `plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:62`). This closes the equal-revision replacement case identified by the research.
- **Phase behavior and tests match the contract.** Phase 3 covers ambiguous trash/restore responses and delayed stale retries; phase 5 makes direct file purge atomic with no receipt and tests response loss/repeat without another quota debit (`plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:68`, `plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:78`, `plans/261029-1220-openlet-backend-mvp/phase-05-durable-lifecycle.md:62`, `plans/261029-1220-openlet-backend-mvp/phase-05-durable-lifecycle.md:85`). The central testing contract covers the same race and reconciliation cases (`docs/testing.md:24`, `docs/testing.md:31`).
- **Research alignment is explicit.** The contract follows the researched distinction between idempotent effects and identical response replay, while retaining durable operation state for long-running work (`plans/reports/research-261029-1344-file-operation-retries.md:7`, `plans/reports/research-261029-1344-file-operation-retries.md:26`).

Status: DONE

Summary: The revised retry contract and phase ownership are consistent. The stale requirement for receipt rows on trash/restore/file purge and the associated phase-ordering blocker no longer apply.

Concerns: No implementation or runtime tests were run; this verification covers plan/contract consistency only.
