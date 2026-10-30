# Assumption and Scope Review: Openlet Backend MVP

Scope: plan-only review of the accepted three-service MVP and its supporting architecture, data, API, workflow, testing, and research documents. No implementation, lint, build, or runtime checks were performed. The review preserves the accepted exclusions, including non-snapshot recursive copy, no epochs/refcounts/leases, and no SDK spike.

## Findings

### High — Clerk publication alone does not make the internal ID appear in refreshed session tokens

`plans/261029-1220-openlet-backend-mvp/phase-02-identity-workspaces.md:31` publishes `openlet_user_id` and line 33 assumes the refreshed token contains it, while the success criterion at line 113 requires that behavior. The research explicitly identifies Clerk session customization as a separate capability (`plans/reports/research-261029-1220-production-patterns.md:14`), but no phase owns the external Clerk session-template/claim configuration, its environment-specific setup, or a check that Envoy receives the intended claim. Metadata publication can succeed while refreshed tokens still omit the claim, blocking every normal route.

Smallest fix: add a phase-2 deliverable that documents and configures the Clerk session claim mapping from backend-controlled metadata, names the required external dashboard/API prerequisite, and verifies publication → refresh → Envoy forwarded internal ID with the credential-dependent Clerk smoke. Keep the exact Clerk configuration and commands marked as implementation work until tested.

### High — Dynamic directory enumeration has no finite completion boundary

The copy flow keyset-enumerates source IDs (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:46`) and permits concurrent additions to be omitted (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:47`), but it does not define when enumeration of a directory is complete. If entries continue to arrive above the current cursor, a durable copy can keep discovering work indefinitely and never reach the atomic publication promised at line 48. This is not a request for a tree snapshot, source retention, manifest, or epoch.

Smallest fix: define a finite per-directory enumeration boundary, such as recording the maximum stable child ID when that directory is first opened and scanning only through that bound. Entries after the boundary are intentionally omitted; encountered items retain the existing per-file recheck behavior. Add a deterministic concurrent-add test proving termination and the documented omission semantics.

### High — Closed-before-admission Temporal runs are specified in the API contract but unowned by the phases

The common contract requires an explicit workflow-ID reuse policy and durable-admission recheck when a run closes before its first activity admits the request (`docs/api-contracts.md:17`). Phase 2 only states start-before-mutation, first-activity admission, and same-key retry (`plans/261029-1220-openlet-backend-mvp/phase-02-identity-workspaces.md:54`), and the later durable-operation phases rely on the same pattern without assigning this failure case. A start can therefore be acknowledged but leave no DB operation row, while subsequent same-key retries remain blocked or create ambiguous new executions depending on Temporal reuse settings.

Smallest fix: add the closed-before-admission rule and a focused test to each owning durable-start phase: recheck the owning DB after closure, apply a pinned Temporal reuse/conflict policy, and allow the same caller/action/scope/key to recover without admitting different input. Treat the exact SDK/server option names as implementation-time pins, not verified runtime facts.

### High — Coordinated backup/restore depends on an unselected provider-specific object preservation method

Phase 6 promises scripts that capture all databases plus objects and an isolated restore (`plans/261029-1220-openlet-backend-mvp/phase-06-integration-operations.md:51`, `plans/261029-1220-openlet-backend-mvp/phase-06-integration-operations.md:64`), but storage is provider-configurable and the research leaves provider selection until acceptance (`plans/reports/research-261029-1220-production-patterns.md:45`). A generic shell script cannot guarantee a matching external-S3 recovery point without a selected versioning, snapshot, replication, or inventory/copy procedure. The phase also says to drain writers but does not explicitly own stopping service workers and Temporal Server writers before independently dumping the databases, which the architecture requires (`docs/architecture.md:103`).

Smallest fix: make selected-provider backup capability a phase-6 prerequisite and record the exact object preservation/restore mechanism. Specify the freeze sequence through stopped admissions, schedules, services/workers, and Temporal Server writers before database dumps and object capture; then prove that exact provider procedure in the isolated restore drill. Keep provider commands and guarantees pending until runtime-tested.

## Scope Audit

No finding requires Redis, a custom gateway, cross-language Temporal calls, snapshots, epochs, refcounts, source-retention pins, leases, or a standalone SDK experiment. The plan correctly labels paths, commands, version pins, and provider/runtime compatibility as future implementation work rather than completed evidence.

## Unresolved Questions

- Which Clerk environment and configuration route will own the session-token claim mapping?
- Which deployment S3 provider and recoverable object-preservation capability will be selected before release acceptance?

Status: DONE_WITH_CONCERNS

Summary: The accepted scope is coherent, but four prerequisites or failure rules must be assigned before implementation can safely satisfy its own success criteria.

Concerns/Blockers: None blocks plan revision; Clerk claim configuration and provider-specific backup capability are external prerequisites that must be resolved before their respective acceptance tests.

## Follow-up Verification

Recheck date: 2026-10-29. Scope was limited to the four findings above after the plan and contracts were revised. External Clerk/provider setup is accepted as an implementation acceptance prerequisite; no selection interview or runtime testing was performed.

1. **Clerk claim configuration — Resolved at plan level.** Phase 2 now owns configuring and documenting the environment-specific session-token mapping, explicitly states that metadata publication alone is insufficient, and requires refresh to include the field (`plans/261029-1220-openlet-backend-mvp/phase-02-identity-workspaces.md:43`). Architecture assigns the same ownership to phase 2 (`docs/architecture.md:45`). The credential-dependent smoke verifies actual backend metadata and refreshed JWT (`docs/testing.md:37`), while the end-to-end onboarding path and gateway checks cover use of that refreshed claim. Exact Clerk setup remains correctly deferred until implementation.

2. **Finite recursive-copy enumeration and budgets — Resolved.** Each directory records a maximum observed child ID before bounded keyset enumeration (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:46`; `docs/data-model.md:86`). Overall node, byte, and runtime ceilings prevent continually nested additions from extending a copy forever (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:71`; `docs/data-model.md:90`). The phase and shared testing contract require continuous-add termination/resource-cap coverage (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:82`; `docs/testing.md:27`). This preserves the accepted dynamic, non-snapshot semantics.

3. **Closed-before-admission Temporal policy — Resolved.** The API contract now defines running-run attachment, durable DB recheck after closure, allow-duplicate-after-close replacement, input mismatch rejection, late-attempt deduplication, and explicit Go/Rust SDK option pinning/testing (`docs/api-contracts.md:17`). Phase 2 explicitly tests the onboarding/workspace path (`plans/261029-1220-openlet-backend-mvp/phase-02-identity-workspaces.md:78`), phase 4 explicitly tests `CopyNode` (`plans/261029-1220-openlet-backend-mvp/phase-04-storage-and-copy.md:83`), and the shared status test requirement applies the same contract to durable starts (`docs/testing.md:31`). No runtime behavior is claimed before the SDK/server options are pinned and exercised.

4. **Provider-specific backup capability and full write freeze — Resolved.** Phase 6 makes selection of the deployment provider's exact preservation/restore method a prerequisite and rejects a generic unverified S3 promise (`plans/261029-1220-openlet-backend-mvp/phase-06-integration-operations.md:64`). It explicitly blocks all mutating public/internal HTTP, pauses schedules, drains database/activity/S3 work, and stops service workers plus Temporal Server writers before capture (`plans/261029-1220-openlet-backend-mvp/phase-06-integration-operations.md:51`). Architecture and release testing repeat the same recovery-point and selected-provider requirements (`docs/architecture.md:103`; `docs/testing.md:55`). Exact commands and guarantees remain correctly contingent on the selected provider and isolated restore drill.

Status: DONE

Summary: All four prior findings are resolved in the current plan and supporting contracts, with external configuration and runtime compatibility retained as explicit implementation acceptance prerequisites.

Concerns/Blockers: None within the requested plan-only scope.
