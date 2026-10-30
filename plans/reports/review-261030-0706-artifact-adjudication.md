> Historical snapshot, superseded on 2026-10-30 by the user-approved [direct-child artifact plan](../261029-1624-artifact-file-processing/plan.md). Its schema, path, ownership and pending-review statements describe the previous draft; do not execute them. Use the current plan and [validation report](./validation-261030-0737-hybrid-artifact-plan.md). General runtime/source evidence remains useful where the current plan retains it.

# Artifact Processing Plan — Review Adjudication

Status: Draft complete; review complete; proposed corrections await the user review gate. The plan has not been changed by this review and is not ready for implementation.

Plan: [Artifact File Processing](../261029-1624-artifact-file-processing/plan.md).

## Scope and evidence

The three independent reviews covered security, assumptions, and failure modes:

- [Security review](./review-261030-0706-artifact-security.md)
- [Assumption review](./review-261030-0706-artifact-assumptions.md)
- [Failure-mode review](./review-261030-0706-artifact-failures.md)

Review concerns are proposals, not changes to accepted product decisions. No implementation, database mutation, build, install, container, or runtime test occurred. Severity below reflects controller adjudication rather than copying reviewers' ratings.

## Proposed decisions

### 1. Order activity attempts — High — Accept

The plan activates a new UUID without defining which invocation is newer (`phase-02-processing.md:35`, `phase-02-processing.md:54`). Existing operations and uploads provide no ordering (`services/letfs/migrations/0002_file_core.sql:21`, `services/letfs/migrations/0004_uploads.sql:1`). A delayed old prepare request can otherwise replace the current attempt.

Use the Temporal activity attempt number as a monotonic generation for this operation's single scheduled activity, plus an invocation UUID for HTTP idempotency. Persist and compare the generation under the operation lock. Equal generation must match the UUID; lower generations are rejected. Every output/complete/abort call must match the active tuple. No workflow retry/reset mechanism is introduced. Test reordered prepare requests as well as stale completion.

### 2. Keep attempt output out of nodes before publication — High — Accept

The plan leaves prepublication node representation unspecified (`phase-01-artifacts.md:27`, `phase-02-processing.md:35`). Existing deletion considers every node referencing a succeeded operation charged (`services/letfs/src/fs/deletion.rs:131`, `services/letfs/src/fs/deletion.rs:141`). Abandoned nodes must never become charged merely because a newer attempt succeeds under the same operation.

Keep unpublished output in bounded uploads/cleanup records; create only the winning node tree in the atomic publication transaction. Preserve the existing succeeded-publisher invariant for published output. Superseded output handles and object cleanup must never debit published quota or filesystem node counts. Explicit empty directories require bounded metadata, not fake zero-byte upload files. Do not add an attempt registry or user-visible run history.

### 3. Correct quota-failure expectations — High — Accept

Phase 3 says quota failure preserves the old root (`phase-03-acceptance.md:45`), contradicting overwrite invalidation (`phase-01-artifacts.md:30`). Upload-finalize quota failure and later processing quota failure are distinct (`services/letfs/src/fs/uploads.rs:209`).

After a successful source overwrite, old artifacts stay hidden. If replacement processing cannot acquire quota, publish no replacement tree; retain the new source and failed status. Old output remains charged only until its separately admitted cleanup removes it once. Never restore the old pointer.

### 4. Make deletion safe for the ownership FK — High — Accept

Phase 1 proposes the FK without a deletion-order invariant (`phase-01-artifacts.md:26`, `phase-01-artifacts.md:88`). Current leaf selection only follows parent edges and deletes batches of up to 64 (`services/letfs/src/fs/deletion.rs:141`, `services/letfs/src/fs/deletion.rs:166`). A root can be selected while its owner still references it.

Persist the ownership-edge deletion work before severing that edge. Explicitly clear the owning pointer in the same transaction before removing the referenced artifact root. Cover source/ancestor purge, filesystem deletion, and copy-discard paths. Add a multi-batch case where owner and artifact root cannot be removed together. Preserve durable checkpoints so clearing the pointer cannot orphan the tree.

### 5. Define source-copy snapshot behavior — Medium — Accept as clarification

The plan promises attached-artifact copying without saying when the association is captured (`phase-01-artifacts.md:38`). Existing copy snapshots file metadata/revision and reads batches (`services/letfs/src/fs/copy.rs:161`, `services/letfs/src/fs/copy.rs:224`). Artifact ownership is a new edge, so future publication must not change an already enumerated closure.

Capture the artifact pointer, including absence, when each source file is enumerated under existing filesystem locks; enqueue that captured root through copy checkpoints in that transaction. Include artifacts attached before that snapshot. A later attachment is consistently excluded from that source copy. Existing content/source checks still reject conflicting byte replacement; add both publication race orders. This does not introduce global filesystem snapshots or require copying output that did not exist at the copy's snapshot.

### 6. Update storage consumers in the same phase — Medium — Accept

Phase 2 changes `storage::build` but defers two affected consumers (`phase-02-processing.md:104`, `phase-03-acceptance.md:70`). The three actual callers are `services/letfs/src/main.rs:43`, `services/letfs/tests/integration.rs:192`, and `services/letfs/src/storage/provider_smoke.rs:10`. `make verify` compiles all Rust targets (`Makefile:48`).

Put mechanical caller adaptations in Phase 2. Phase 3 adds provider assertions rather than repairing a prior type migration. Also make the producer/workflow dependency explicit: introduce runnable dispatch/start-recovery wiring together with the registered workflow in Phase 2; Phase 1 may establish durable intent/schema without references to undefined Phase 2 Rust symbols. No placeholder workflow or silent no-op is permitted.

### 7. Bring real exporter fixtures into Phase 2 — Medium — Accept

Phase 2 claims exact XLSX export while the first actual workbook is assigned to Phase 3 (`phase-02-processing.md:47`, `phase-03-acceptance.md:59`). Research verifies table export but has not demonstrated that the pinned Docling model exposes empty sheets and isolated cells (`plans/reports/research-261029-2317-processor-runtime.md:93`, `plans/reports/research-261029-2317-processor-runtime.md:178`).

Create tiny real format fixtures with the exporter tests in Phase 2, especially empty/singleton/isolated XLSX cells. Verify the accepted outputs against the pinned parser before considering that phase complete. Resolve any representation gap using the actual installed backend/source and existing dependencies; do not silently drop content, weaken the layout contract, or add an unproven API. Phase 3 retains full Temporal/E2E/recovery coverage. These are permanent behavior tests, not a disposable SDK spike.

### 8. Scope backup claims precisely — Medium — Accept

Automated coordinated recovery in this feature is local SeaweedFS (`phase-03-acceptance.md:74`). Existing operations authority separately requires a coordinated external R2 recovery point (`docs/operations.md:23`, `docs/operations.md:78`). A presigned API smoke test cannot prove recovery.

State explicitly that the automated drill covers SeaweedFS. Carry forward the existing R2 object-plus-five-database recovery requirement as a production release gate, alongside new presigned checks. Report unavailable external checks as NOT RUN. Do not expand this feature into a new provider backup platform.

### 9. Require a separate sandbox for the Docling child — High as submitted — Reject as a blocker

The security review proposes per-child network/filesystem isolation and exploit fixtures. The accepted child process is for CPU supervision, heartbeat responsiveness, and resource cleanup (`phase-02-processing.md:38`); it was not a separate trust boundary. The worker already belongs to the internal file-service domain. Shared backend access exists today (`deploy/compose.yaml:54`), but the review identifies no enabled document-triggered code execution or remote-fetch path proving a new sandbox is necessary for this feature.

Do not add a sandbox service, custom namespace runtime, or adversarial exploit fixture suite on this evidence. Retain standard non-root/container limits, local-file parsing, disabled runtime model/remote enrichment downloads, URL redaction, and normal subprocess environment/descriptor hygiene. Document honestly that a supervised subprocess is not a security sandbox: an arbitrary-code-execution defect in parser dependencies would execute with the worker's trust. Do not claim credential or network isolation that the deployment does not enforce.

### 10. Make direct PUT length enforcement a gate — Medium — Accept with narrower fix

The plan makes exact upload-length binding optional (`phase-02-processing.md:31`), whereas the current proxied transfer enforces a byte ceiling and deadline (`services/letfs/src/fs/uploads.rs:129`). Detecting oversize only after an uncharged staging upload does not enforce that ceiling at the storage boundary.

Require provider-proven signed length enforcement for direct PUT; keep provider checksum and conditional-create support separately evaluated. If the selected provider cannot enforce the required length, block that direct-upload acceptance gate and report the incompatibility. Do not preemptively implement another transfer path. Keep the agreed worker/API/presigned architecture and add provider oversize rejection assertions.

### 11. Invalidate artifacts for ineligible replacements too — Medium — Accept

Parent review found `phase-01-artifacts.md:44` says ineligible finalize is unchanged, despite mandatory invalidation for every byte replacement at lines 30–31. The actual overwrite path replaces data without a processing hook today (`services/letfs/src/fs/uploads.rs:216`).

Make invalidation and supersession unconditional for replacements. Only creation of a new processing intent depends on eligibility. Ineligible new files retain ordinary upload behavior; ineligible overwrite/text replacement must not retain artifacts from old bytes.

## Summary

- Eleven adjudicated items: ten accepted corrections/clarifications and one rejected mandatory sandbox expansion.
- Severity after adjudication: five High (one rejected), six Medium; no Critical findings.
- All accepted product decisions remain: one Rust workflow, one Python activity, no Python DB/long-lived S3 credentials, source-owned artifacts in the same filesystem, readonly output, virtual aliases, agreed layouts, no content history/revision field, and no output manifest/index/run registry.
- No plan corrections have yet been applied. The skill's user review gate is the next step, followed by whole-plan reconciliation, final validation, task indexing, and handoff.

## Mechanical checks completed

- `ak plan validate plans/261029-1624-artifact-file-processing --json`: valid, no structural errors.
- Four plan files checked: no broken relative Markdown links.
- Thirty sampled baseline source anchors still found. This checks existence, not runtime correctness or parser/provider compatibility.
- Sixty phase checkboxes and five plan acceptance checkboxes remain unchecked.
- No live task-management API is exposed; Markdown checklists remain the task source.
- No task-owned background process was found or started in this continuation.

## User review gate

The installed `ak-plan/references/red-team-workflow.md`, Step 7, requires a user choice before accepted review findings are applied: “Looks good, apply accepted findings”, “Let me review each one”, or “Reject all, plan is fine”.

Unresolved product questions: none. The outstanding choice is whether to apply the concrete plan corrections above. Runtime package/model/provider verification remains implementation work.
