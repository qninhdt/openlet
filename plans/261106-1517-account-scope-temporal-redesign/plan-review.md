# Plan review and validation

## User-reviewed scope

The conversation approved one accounts table with independent user/agent identities, fixed roles/actions, one filesystem per workspace, shared/per-member scopes, inactive membership/rejoin, no mounting/quota bucket/workspace-count limit, and cleanup of newly created storage on permanent refusal.

The earlier draft also introduced details that had not been explicitly reviewed. Treating all of them as approved internal clarifications was inaccurate. The user reviewed those additions and authorized the following update:

| Decision | Current plan |
|---|---|
| Duplicate deletion | Allow overlapping execution; existing SQL/idempotent effects suffice. No singleton/join coordinator. |
| Copy | One workflow → one activity, direct bounded copy. Remove checkpoint/resume/progress machinery and all corresponding surfaces/tests. |
| Partial copy failure | Return error and retain copied files; no automatic whole-copy retry. |
| Ownership transfer | Remove from both Account and Workspace, including actions, API/workflow branches, owner-CAS commands/tests. |
| Account disable | Remove feature, account status field, active userset and gating. Membership active/inactive remains. |
| Defaults and identity details | Retain reviewed shared/personal role defaults, managed-create owner/type constraints and exact wire rename. |
| Cleanup and onboarding | Preserve real cleanup evidence; tombstone only while required. Use existing published account identity for completed onboarding, without another marker/mapping. |

## Prior source review

Earlier read-only reviewers checked security/facts, failures/flow and scope/contracts. Useful retained corrections include the operation/action matrix, forced managed-create type/owner, trusted onboarding child admission, complete LetFS transport inventory, cross-runtime wire consumers and direct-grant-preserving recovery.

The previously proposed disabled-account summary behavior, expected/prior-owner compare-and-set protocol, acknowledged copy checkpoints and heartbeat/history progress retrieval are superseded. They are not implementation requirements. The earlier reviews and SDK feasibility findings do not establish runtime correctness or user approval of those rejected mechanisms.

The existing SQL→graph publication model remains: required publication must be acknowledged before success. No new graph-first coordinator or SQL grant mirror. Source inventory is in [Source evidence](source-evidence.md).

## Verification for this update

This update is documentation only. Completed checks after propagating the user's decisions:

- [x] CLI validates/parses the existing plan with five pending phases.
- [x] Relative links and code fences are valid; twelve workflow roots remain distinct.
- [x] All plan files agree on removal of disable/transfer/checkpoint/progress, including tests and cleanup steps.
- [x] Account has no status field; membership status and resource lifecycle remain.
- [x] Copy has no automatic retry/resume guarantee; dispatch recovery cannot restart a partially failed copy.
- [x] Only existing plan/journal documents changed; source and inline_text_only work preserved.

Implementation, integration/fault-injection/API tests have not run for this update. They remain execution gates. No implementation authorization is inferred from plan approval.

## Whole-plan consistency sweep

Updated all five phases, design contract, index, evidence and this review together. CLI validation passed; parsing found five pending phases and zero completed implementation tasks. Markdown checks passed for all ten edited documents, including the existing journal. Implementation checkboxes remain pending. Do not reintroduce removed behavior through generic controllers, tests, SDK helpers or maintenance. Further changes to approved schema, ownership, public behavior or workflow trees require review of the concrete issue.
