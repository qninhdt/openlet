# Openlet backend MVP: planning validation

Date: 2026-10-29, Asia/Ho_Chi_Minh. Result: ready for implementation at the document-contract level. All six implementation phases remain pending. This report validates a plan, not a running system.

## Authority and scope

The user accepted the researched short-mutation retry recommendation and explicitly instructed continuation: “ok toi chon cai nay tiep tuc workflow cua akplan di”. No new product questions were needed. This authorizes completing the plan and affected documents; it does not start implementation.

Current authority is the [plan](../261029-1220-openlet-backend-mvp/plan.md) and [backend docs](../../docs/README.md). Evidence: [production patterns](research-261029-1220-production-patterns.md) and [retry research](research-261029-1344-file-operation-retries.md). Earlier discarded-plan reports are historical only.

## Independent review and adjudication

Sources: [Security](review-261029-1220-security.md), [Failure](review-261029-1220-failure.md), [Scope](review-261029-1220-scope.md), [Assumptions](review-261029-1220-assumptions.md). Their original findings and subsequent verification are retained; the final verification sections supersede earlier open-status summaries.

The 17 initial findings (13 High, 4 Medium) overlap on direct replay, closed-before-admission retry and backup write safety. Grouped below: 14 issues, 11 accepted and 3 accepted with modified remedies. No evidence-backed concern is silently discarded; rejection of a proposed mechanism is distinct from rejection of the underlying failure case.

| Issue / source | Disposition | Final contract and owner |
|---|---|---|
| Direct retry ambiguity; Failure 1, Scope 1 | Accept modified | User-selected original identity/revision plus state reconciliation for trash/restore/file purge; no receipt rows. Phase 3 owns base operations migration for inline-copy deduplication, phase 4 extends it, phase 5 direct purge debits atomically. |
| Purge debit ambiguity; Failure 2 | Accept | Each charged node debits in the batch transaction removing it; retry cannot debit twice. Phase 5. |
| Closed run before admission; Failure 3, Assumptions 3 | Accept | Attach running execution; after closure recheck DB, return existing outcome or explicitly allow same-ID replacement if absent, fenced by first-activity uniqueness. Owning phases 2/4/5 pin SDK options and test it. |
| Full backup gate and recoverable provider objects; Failure 4, Assumptions 4 | Accept | Block all direct/durable mutating HTTP, pause schedules, drain storage/DB/activity work and stop service/Temporal writers; preserve matching objects using the selected provider's tested method. Phase 6. |
| Copy into self/descendant; Scope 2 | Accept | Reject during prepare and recheck at publication under the filesystem lock. Phase 4. |
| Invitation role; Scope 3 | Accept | Editor/Viewer only, with Owner-invite rejection. Phase 2. |
| Unnecessary Workspace Temporal edits; Scope 4 | Accept | Phase 4 touches Workspace HTTP/letfs adapters only; letfs owns CopyNode. |
| Unowned local rate limit; Scope 5 | Accept modified | Keep accepted native Envoy local token-bucket config, per-instance semantics and deterministic rejection test in phase 1. Removing it would undo accepted scope. No distributed limiter or Redis. |
| Uncharged upload/copy resource growth; Security 1 | Accept modified | Existing rows bound outstanding jobs/cleanup backlog, with finite per-file/copy byte/node/runtime ceilings; stop new admission when cleanup stalls. Phase 4. No exact physical-byte ledger or logical reservation. |
| External storage confidentiality; Security 2 | Accept | Verified TLS, private objects and least-privilege object credentials; real-provider release smoke. Phases 4/6. |
| Empty-node exhaustion; Security 3 | Accept | Transactional node-count cap includes empty/trash/staging nodes; boundary and reconciliation tests. Phase 3. |
| Member enrichment privacy; Security 4 | Accept | Allowlist `{id,display_name,avatar_url}`, distinct verified-email lookup and private-field exclusion tests. Phase 2. |
| Clerk claim publication versus session mapping; Assumptions 1 | Accept | Phase 2 owns external environment claim mapping and publication → token refresh → Envoy forwarded-ID smoke. |
| Infinite dynamic copy enumeration; Assumptions 2 | Accept | Per-directory child-ID upper bound plus overall job node/byte/runtime ceiling, preserving non-snapshot semantics. Phase 4. |

Final narrow follow-ups report no remaining blocker for these issues. Security verified its four fixes; Failure and Scope rechecked the user-selected retry contract and migration handoff; Assumptions verified its four assigned prerequisites/rules. These reviews do not claim runtime correctness.

## Validation decisions and propagation

- Short mutations may return 404/409/412 after an ambiguous response. Clients reconcile authorized state; an error does not prove who changed it. Never interpret every 404 as success or refresh a revision to repeat old destructive intent.
- A path can resolve to a replacement with the same revision. Existing-node path mutations require expected node identity; path-selected destination parents require expected parent identity, checked under lock. Re-trash creates a fresh trash entry; node revision remains monotonic.
- Inline copy retains request identity/result IDs to prevent duplicate creation. Upload finalize retains upload state/result. Multi-step operations retain scoped admission, checkpoints and outcome; Temporal deterministic replay and retry-safe activity effects remain necessary.
- Propagated through API, data model, workflows, tests and phases 3–6. Phase 3 creates inline-copy code/operations schema; phase 4 extends them rather than claiming a second creation owner.
- Preserve the three services, native owning workers, generic quota/filesystem boundaries, hard commit-time quota, same-filesystem operations, independent data copies, inline text and non-snapshot recursive copy. Redis and rejected speculative mechanisms remain excluded.

## Verification scope

Full document tier: read the plan index, every phase and the owning docs. Verify current facts against repository state and future work as explicitly planned deliverables. Application paths, commands, SDK configuration and migrations do not yet exist; absent planned files are not treated as completed implementation or false current-source claims. There are no application callers or runtime flows to trace yet.

Mechanical validation covers plan/frontmatter format, parsing of six pending phases, sequential dependencies, unchecked tasks, relative links, Markdown fences, planned Make target consistency and focused contract-presence/stale-text checks. Exact command results are recorded below after the final sweep. No service, compilation, integration, workflow or E2E test is claimed as run.

## Remaining acceptance prerequisites

These are implementation work assigned in phases, not unresolved product questions or plan blockers:

- Phase 1 pins supported versions and proves real configuration/provisioning; exact native SDK option names are verified in their owning durable-start phases.
- Phase 2 needs a development Clerk environment/credentials and explicit backend-controlled session claim mapping for the live smoke.
- Phases 4/6 select the deployment S3 provider, confirm TLS/private/version/delete behavior and test its exact object-preservation procedure.
- Phase 6 executes coordinated metadata/object restore in isolation. Recovery point and maintenance downtime remain operational trade-offs.
- Filesystem write serialization limits hot-filesystem throughput; recursive path work grows with depth; copy provides per-file coherence rather than a source-tree snapshot; transfer can precede quota rejection. These accepted limits must be described honestly.

No task-owned background process remains. No app implementation, publish, commit or external messaging was performed.

## Final mechanical results

- `ak plan validate plans/261029-1220-openlet-backend-mvp --json`: valid, no errors.
- `ak plan parse plans/261029-1220-openlet-backend-mvp --json`: six phases, 96 phase checklist tasks, zero completed, zero percent implementation progress.
- Standard-library document checks: 25 Markdown files, 43 relative links, zero missing targets, balanced fenced blocks. Thirty-six assertions passed for dependency order, pending status, planned ownership, execution sections, command uniqueness, retry contracts, seven workflow types and repository-state claims; zero failed.
- Planned Make target references are consistent. Duplicate command lines were removed; no planned target was executed as if an application already existed.
- Whole-plan sweep reconciled API/data/workflow/testing and phases 3–6 for the new retry decision, expected path identities and phase-3/4 schema ownership. No unresolved document contradiction remains.

These checks establish internal document consistency. Clerk, S3, native worker compatibility, SQL concurrency and recovery remain unverified runtime behavior until implementation delivers the assigned acceptance evidence.

## Local workflow completion

`ak plan reindex --apply --json` recognized the current six-phase plan as `openlet/261029-1220`; `ak plan use` set the worktree-private active-plan pointer. No external task-management tool was available, so the phase checklists remain the execution task authority. Local journal creation and `ak journal validate` succeeded; AgentWiki publishing was skipped. After journal creation the final link/fence sweep covered 26 Markdown files and 45 relative links with zero missing targets. No application process was started.
