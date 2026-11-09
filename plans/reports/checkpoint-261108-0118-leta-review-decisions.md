# Leta design review checkpoint: items 1–18

Latest accepted direction: [workspace-owned Leta and current review decisions](design-261108-0148-leta-workspace-resource.md). Items 1–34 are settled with recorded corrections. Artifacts remain ordinary child files accessed by source absolute path or /@<original-file-id>/relative-artifact; no separate artifact ID concept/namespace. LetFS provides data APIs and the adapter implements Mirage hooks only. Items 35–42 are the final pending group; no implementation has started. Older statuses below are historical.

Status: items 1–18 settled by subsequent user confirmation. Review continues with 19–26; 27–42 remain parked. No implementation has started or been authorized.

This checkpoint records the user's response to the [42-item design-addition inventory](../261108-0001-leta-agent-engine/reports/design-additions-review.md). The user has reviewed **only items 1–18**. Within that range, unmentioned items are accepted. Items 19–42 remain parked and unreviewed; silence does not accept them. The trailing repeated “16.” is not an additional decision.

This newer user feedback overrides conflicting older plan/checkpoint statements. The affected owning phase files have now been reconciled with the settled items 1–18. The plan still awaits review of items 19–42 before implementation. Do not create a new architecture or expand the explanation into another distributed-systems design.

## Decisions recorded

| Inventory item | Current disposition |
| --- | --- |
| 1 — Initial provider | Accepted: OpenRouter integration as the initial provider adapter. |
| 2 — Leti model override in create_box | Accepted correction: remove model/reasoning from the agent tool's LetiSpec. Owner configuration APIs retain overrides; default inheritance remains. |
| 3 — Workspace binding | Corrected: Leta cannot independently leave or move workspace. It is a resource of its workspace. Deletion is the product operation; membership removal is internal deletion cleanup, not a separate Leta leave feature. |
| 4 — Role policy scope | Accepted recommendation: member-only Leta creation; do not silently impose new blanket role/workspace restrictions on unrelated managed accounts. |
| 5 — Post-owner-leave visibility | Special retained access/discovery machinery rejected as unnecessary complexity. Follow ordinary workspace membership/access semantics; do not preserve a special permanent owner-access bypass after owner workspace departure. |
| 6 — Name reuse | Accepted: live uniqueness; reuse after completed deletion/archive/trash with new IDs; no resurrection. |
| 7 — Disconnected graph | Accepted: allowed communication graph need not be connected. |
| 8 — Oversized input | Accepted: explicit error without silently dropping/splitting the captured full Leti batch or advancing its cursor. |
| 9 — Permanent failure wake bookkeeping | Rejected: remove the proposed failure_wake_seq field and associated custom wake policy. Use ordinary run error/retry behavior; do not replace it with another subsystem. |
| 10 — Interrupted shell/Monty | Accepted replay risk: an unfinished command may execute again after crash. The agent checks/corrects effects. Remove start-marker replay suppression, synthetic outcome_unknown and extra execution bookkeeping. |
| 11 — Calendar wildcard | Accepted correction by omission within the reviewed range: preserve explicit "*" input. |
| 12 — Domain identities/schema | Accepted by omission, subject to the newer deletion-only lifecycle and rejected field/mechanisms above. A cleanup key is internal to deletion, not a user leave capability. |
| 13 — Commit-ordered cursors | Accepted by omission. |
| 14 — Command journal admission/completion | Remove the proposed permanent two-stage journal and extra completion saves. Temporal owns ordinary retry; no arbitrary historical-command replay guarantee after rotation/intervening commands. |
| 15 — Permanent Workspace receipts | Reuse existing idempotency_keys and retention. MutationReceipt is a Go helper over that table, not a separate receipt table. No indefinite-retention extension. |
| 16 — Runner recovery/one writer | Temporal serializes run_agent invocations; the previously brainstormed advisory lock/checkpoint remains a small implementation guard for overlapping retry attempts. No leasing/fencing subsystem or exactly-once claim. |
| 17 — Invocation segmentation | Yield at a safe checkpoint when Temporal history needs Continue-As-New; resume the same agent/business run/context. Remove forced two-minute/128-boundary segmentation. Actual upstream safeguard handling is not a product work budget. |
| 18 — Middleware/checkpoint/public summary | Accepted. Public tool history does not impose the rejected command replay-suppression policy. |

## Verified answer: human personal scope after workspace leave

- `apps/workspace/internal/workspace/membership.go::ApplyMembership` invokes WriteMemberRelationships with defaults enabled on removal.
- `apps/workspace/internal/workspace/relations.go::WriteMemberRelationships` deletes workspace role tuples and the member's default personal-scope manager relationship when membership is inactive (lines 43–55 in the reviewed source).
- `packages/contracts/authz/schema.zed` derives scope read permissions from viewer/editor/manager, not permanent human ownership.
- Therefore default personal access is revoked on leave; existing independent direct grants, if any, are a separate current-code fact. This review does not redesign human leave or add a new cleanup framework.
- The user rejected a special Leta visibility exception after owner departure. Do not retain the previous plan's active-membership bypass, permanent post-leave viewer promise or dedicated archived-owner discovery path.
- No automatic deletion, ownership transfer or new owner-departure Workflow is inferred from this feedback. Any required alignment with existing membership authorization must stay explicit and minimal.

## Subsequent confirmation and reconciliation

The user explicitly accepted the simplified answers for items 10 and 14–17 and requested the files be fully updated before continuing. The earlier permanent-command journal, infinite Workspace receipt retention, shell replay suppression and fixed invocation segmentation are no longer plan requirements.

Reconciled owning files cover Workspace access/idempotency, schema, Temporal/runtime, history, filesystem replay contracts, lifecycle, HITL, scheduler changes, owner API and system acceptance. Existing source-backed review reports remain historical; they cannot override the later accepted trade-offs. Filesystem/RPC proposals under 19–26 are presented next, without assuming acceptance. No implementation or runtime checks occurred.

## Parked review items 19–42

Full payload, rationale and trade-offs remain in the [original inventory](../261108-0001-leta-agent-engine/reports/design-additions-review.md). Keep its numbering stable. The following items have not yet been reviewed by the user:

| Item | Topic |
| --- | --- |
| 19 | Account/Workspace RPC surfaces |
| 20 | Managed-owner mapping and aggregate filesystem view |
| 21 | Canonical TEXT migration and binary compatibility |
| 22 | Large-text streaming and old consumers |
| 23 | Backend Locator root restriction |
| 24 | Native read/tree/search wire semantics |
| 25 | Text mutation semantics and guards |
| 26 | Shell trash/copy behavior |
| 27 | Artifact namespace and HOME |
| 28 | Original-image preview policy |
| 29 | Redis cache authorization/capabilities |
| 30 | Complete literal search and Mirage fallback |
| 31 | Default-planner GIN performance gate |
| 32 | HITL edge behavior |
| 33 | Native schedule compilation/precision |
| 34 | Editing fired one-shot schedules |
| 35 | Schedule pause/delete admission boundary |
| 36 | Calendar preview pagination/ordering |
| 37 | Public API/UI projections |
| 38 | Provisional token loss during reconnect |
| 39 | Per-connection PG refresh |
| 40 | Redis outage behavior |
| 41 | Proposed operational defaults |
| 42 | Packaging/readiness/recovery |

## Next continuation

Review is complete through item42. The later workspace-resource redesign and final streaming decisions supersede this historical inventory. Continue from [the current 19-phase English plan](../261108-0001-leta-agent-engine/plan.md) and [current design checkpoint](design-261108-0148-leta-workspace-resource.md). All accepted corrections are incorporated, including explicit phase02 user/agent migration. Implementation has not started; do not reopen already accepted review groups or execute obsolete account/large-text/per-run-stream designs.
