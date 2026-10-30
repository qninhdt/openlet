# Scope and contract review

Reviewed the plan index, all six phases, the five owning backend documents, and the production-pattern research. This review is limited to scope/complexity and cross-document contract consistency; it does not review implementation code.

## Material findings

### 1. High — Direct trash mutations promise retry keys without defining replay state

The public contract promises a retry key for trash, restore, and both direct/durable purge paths (`docs/api-contracts.md:70`, `docs/api-contracts.md:72`, `docs/api-contracts.md:73`). The workflow contract classifies trash, restore, and file purge as direct operations (`docs/workflows.md:29`), while phase 3 only says to implement trash/list/restore (`plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:67`) and phase 5 describes direct file purge as a single atomic removal/debit (`plans/261029-1220-openlet-backend-mvp/phase-05-durable-lifecycle.md:62`). Neither phase assigns a durable key/fingerprint/result record to these direct mutations. After a lost success response, the resource has moved or disappeared, so the same-key retry cannot reliably replay the promised result and may instead return not-found/stale-state.

Smallest correction: introduce the existing letfs operation record in phase 3 for only trash/restore/direct-file-purge replay, bound to caller/action/scope/key/fingerprint, and require the state change plus terminal result to commit together. Reuse it in phase 5; do not create a generic idempotency framework.

### 2. High — Recursive copy omits its required self/descendant rejection gate

The data contract explicitly requires rejecting a directory copy into itself or a descendant (`docs/data-model.md:80`). Phase 3 correctly specifies this check for move (`plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:65`), but phase 4 has no equivalent copy requirement, implementation step, or test; its copy requirements begin with same-filesystem/quota behavior (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:57`) and its race tests cover source mutation rather than destination ancestry (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:82`). A copy into its own staged descendant can make traversal chase newly created output or produce an invalid result.

Smallest correction: add one phase-4 requirement and integration test that revalidates the destination is not the source or its descendant under the filesystem lock before staging/admission and again before publication if the destination locator can move.

### 3. High — Invitation role is unconstrained despite ownership-by-invite being forbidden

The architecture forbids granting ownership by invitation (`docs/architecture.md:57`), but the public invitation contract accepts a generic `role` (`docs/api-contracts.md:47`) and the invitation schema likewise stores an unconstrained role (`docs/data-model.md:20`). Phase 2 tests mention general role decisions but never require Owner-invite rejection (`plans/261029-1220-openlet-backend-mvp/phase-02-identity-workspaces.md:76`). An implementation following only the route/schema text could accept `owner`, conflicting with the exactly-one-Owner transfer path.

Smallest correction: state `role: editor | viewer` in the API/data contracts and add one phase-2 validation/contract test rejecting `owner`; ownership remains available only through the transfer endpoint.

### 4. Medium — Phase 4 assigns Workspace Temporal changes to a letfs-owned workflow

Phase 4 lists `services/workspace/internal/{letfs,http,temporal}/` for modification (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:22`), but `CopyNode` is owned entirely by letfs (`docs/workflows.md:24`) and cross-service coordination is authenticated HTTP/status polling, not another service's workflow (`docs/workflows.md:15`). No Workspace workflow is introduced in phase 4. Leaving the path in scope invites a second orchestration layer or dead adapter code.

Smallest correction: remove `services/workspace/internal/temporal/` from phase 4. Workspace should authorize and call the letfs admission/status HTTP contract through its existing HTTP/letfs adapters.

### 5. Medium — Local rate limiting and `429` are an isolated, unplanned MVP feature

Envoy ownership includes “basic local rate limiting” (`docs/architecture.md:17`) and the API advertises `429` (`docs/api-contracts.md:11`), but no phase defines a rate-limit policy, configuration, acceptance criterion, or deterministic test. The accepted foundation work covers request/body/concurrency limits and JWT trust boundaries, not a rate-limiting product contract (`plans/261029-1220-openlet-backend-mvp/phase-01-start.md:48`). This adds behavior that can reject valid clients without an owned threshold or verification route.

Smallest correction: remove local rate limiting and `429` from this MVP. Keep bounded body/duration/concurrency controls. Rate limiting can be added later only with an explicit policy and contract tests.

## Contract result

The core accepted shape is otherwise preserved: three services with owner-local official workers, generic quota bucket to many filesystems, adjacency/path/mount semantics, hard logical quota with trash charged, inline/object bytes, same-filesystem copy/move, manual email-bound invitations, exactly-one-Owner transactions, and the stated exclusions. The four test groups remain authoritative; `security`, `concurrency`, `recovery`, `contract`, and `efficiency` are selectors/categories rather than additional frameworks as clarified in `docs/testing.md:14` and `docs/testing.md:53`.

## Unresolved questions

- None. Each finding has a contract-preserving correction that does not require a new product decision, except retaining rate limiting would require explicit user acceptance of its policy.

Status: DONE_WITH_CONCERNS
Summary: Five material plan corrections are needed: durable replay for direct trash mutations, copy ancestry rejection, invitation-role narrowing, removal of an unowned Workspace Temporal edit, and removal or explicit acceptance of rate limiting.
Concerns/Blockers: No blocker to implementation after these document-level corrections; starting phases 3–5 unchanged risks incompatible retry and copy behavior.

## Fix verification

Verification was limited to the five findings above; no broader re-audit was performed.

1. **Direct mutation replay — partially resolved.** The API, data model, phase-3 behavior, and tests now require scoped replay before target lookup and atomic mutation/result commit (`docs/api-contracts.md:21`, `docs/data-model.md:76`, `plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:68`, `docs/testing.md:31`). However, phase 3 calls the letfs `operations` rows “existing” (`plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:32`) while the first explicit migration that adds copy-operation state remains in phase 4 (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:66`). Smallest remaining correction: make phase-3 migration step 1 create the base letfs `operations` table for keyed direct mutations, and make phase 4 extend/reuse it for copy.
2. **Copy ancestry — resolved.** Phase 4 now rejects self/descendant destinations at prepare and final publication and includes the concurrency test (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:57`, `plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:82`); the data model also requires publication-time ancestry recheck (`docs/data-model.md:92`).
3. **Invitation role — resolved.** Phase 2, the API, schema contract, and required tests now restrict invitations to Editor/Viewer and reject Owner (`plans/261029-1220-openlet-backend-mvp/phase-02-identity-workspaces.md:46`, `docs/api-contracts.md:49`, `docs/data-model.md:20`, `docs/testing.md:22`).
4. **Workspace Temporal scope — resolved.** Phase 4 now modifies only Workspace HTTP/letfs adapters (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:22`), preserving letfs ownership of `CopyNode`.
5. **Local rate limiting — resolved by confirmed user scope.** Phase 1 now owns a configurable per-Envoy-instance token-bucket rate/burst policy, explicitly excludes a distributed service, and requires deterministic excess-burst verification (`plans/261029-1220-openlet-backend-mvp/phase-01-start.md:48`, `plans/261029-1220-openlet-backend-mvp/phase-01-start.md:76`).

The added node-count, outstanding upload/copy/cleanup, and per-copy node/byte/runtime safeguards are concrete limits enforced through existing filesystem/bucket/operation rows (`docs/data-model.md:57`, `docs/data-model.md:63`, `docs/data-model.md:90`). They do not introduce a speculative scheduler, reservation ledger, or generic quota framework.

Verification status: DONE_WITH_CONCERNS
Verification summary: Four findings are fully resolved; direct replay semantics are correct but phase 3 still needs explicit ownership of the base letfs `operations` migration.
Verification concerns/blockers: One document dependency correction remains; no new framework-level scope creep was found in the added safety limits.

## Accepted-contract follow-up

This check is limited to the accepted removal of response receipts for short trash/restore/file-purge transactions and the phase-3/phase-4 operations-schema handoff.

- **Prior migration ownership finding — resolved.** Phase 3 now explicitly creates the base letfs `operations` table for direct inline-copy request identity and result IDs (`plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:32`, `plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:61`). Phase 4 explicitly extends that schema for durable object/directory copy rather than introducing a competing table (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:66`) and preserves phase-3 inline-copy deduplication (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:69`).
- **Changed direct-mutation contract — consistent.** The API and data model now omit retry keys/receipt rows for trash, restore, and direct file purge, requiring stable target identity, original revision, lifecycle checks, and authorized reconciliation after ambiguous responses (`docs/api-contracts.md:23`, `docs/data-model.md:76`). Phase 3 implements those guards for trash/restore (`plans/261029-1220-openlet-backend-mvp/phase-03-filesystem-core.md:68`), while phase 5 applies the same contract to direct file purge and tests that repeats cannot debit twice (`plans/261029-1220-openlet-backend-mvp/phase-05-durable-lifecycle.md:62`, `plans/261029-1220-openlet-backend-mvp/phase-05-durable-lifecycle.md:85`). Direct inline copy correctly retains operation identity because repeating it could create duplicate output.

Status: DONE
Summary: The remaining migration-ownership finding is resolved, and the revised no-receipt contract is consistent across API, data model, phases 3–5, and their stated verification.
Concerns: None within this narrow follow-up.
