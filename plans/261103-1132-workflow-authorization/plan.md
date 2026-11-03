---
title: Simplify durable workflows and incremental authorization
status: completed
branch: dev
---

# Outcome

Implement the accepted onboarding tree (Account owns identity/Clerk; Workspace owns admission and references; letfs owns storage). Temporal must accept commands before business SQL changes. Replace revisioned membership snapshots and periodic graph scans with stable role groups and targeted, atomic relationship updates. Serialize authorization mutations per workspace using native Temporal primitives. Keep current action policy, user authorization, lifecycle, natural idempotency and existing receipt tables. Add no application tables or columns.

# Execution

- [x] Replace snapshot projection with stable groups; implement targeted membership/storage/lifecycle writers and offline rebuild.
- [x] Move Account/Workspace admission into workflows, group provisioning activities, remove whole-graph reconciliation and retain receipt expiry cleanup.
- [x] Route membership/ownership/invitation acceptance/deletion through durable serialized workspace work; retain API errors, retry safety and terminal failure visibility.
- [x] Remove no-op copy activities and duplicate deletion admission checks; make maintenance phases independent. Preserve processing stages and necessary pending-dispatch/object cleanup.
- [x] Update tests, contracts, recovery scripts and owning documentation; run focused, workflow, integration and API checks and review the complete diff.
- [x] Run a real Temporal regular/local-activity latency lab entirely outside the repository; report distributions and limitations without changing production activity placement.

# Validation and constraints

Read source and test inventory from the preceding workflow review; verify installed SDK APIs before use. Source backup: `/tmp/openlet-workflow-authz-source-261103-1132.tar.gz`. No existing containers were running. Database tests use disposable state; back up before modifying any persistent database. No real paid LLM calls. Do not commit or push without a new request. Lab source, data and logs must remain outside the repository. Update this file with actual check results and outstanding work.

# Execution evidence

Stable role groups replace revision/status snapshots. Membership writes touch only affected users; owner transfer writes both in one SpiceDB request. PostgreSQL schema is unchanged. Existing receipts cover SQL acknowledgement loss and stay pinned until graph publication; creation completion expires only its own receipt.

Onboarding now has one Workspace child and no separate Workspace admission Activity. Creation is PrepareWorkspace -> remote CreateStorage -> CompleteWorkspace. Membership, transfer, invitation acceptance and deletion admission use serialized Temporal Updates. No Account/Workspace whole-graph or pending-admission schedules remain; offline owner rebuild and Workspace receipt expiry remain. Existing letfs processing/copy/purge recovery is preserved.

Verified so far: root check, build and unit suites; all three Go workflow suites; Account/Workspace PostgreSQL/SpiceDB integration; grouped letfs provisioning/deletion against real Temporal; the complete 34-test API suite including coordinated backup/restore. Final-source API rerun: 33/33 passed. Fresh native histories replayed successfully for Account, Workspace and letfs. Final root check and workflow suites passed; affected mutation/rebuild/receipt integration passed. Relative documentation links and git diff whitespace checks passed. Review covered acceptance, connected callers, permission boundaries, acknowledgement-loss recovery and creation/deletion races. The external lab completed separately; its source, measurements and conclusions were kept outside this repository. No commit, push or production Activity-placement change was made.

# Approved hybrid follow-up

The user subsequently approved local PrepareMutation with regular ApplyMutation and requested commit/push to dev. Scope is the Activity placement, its recovery verification and the owning workflow documentation. The original latency lab remains outside the repository.

- [x] Apply a five-second local preparation timeout and verify local dispatch/serialization tests.
- [x] Kill a real worker after the ownership SQL commit and verify restart preserves the prepared owner, completes graph publication and replays fresh history.
- [x] Run affected checks and review the accepted workflow/authz implementation for commit/push to dev.

Hybrid verification: the real worker was killed with SIGKILL after SQL commit and before graph publication/Activity acknowledgement. Its replacement recovered the saved preparation, kept the SQL revision unchanged, completed the existing receipt and corrected graph permissions. Native replay of the resulting history passed. Final root check, all three workflow suites and the Workspace SQL/SpiceDB mutation integration passed. The final-source API suite passed 33/33 tests; fresh Account, Workspace and letfs histories replayed successfully. Final diff review and whitespace/credential checks passed. The recovery harness and history remain outside the repository with the original lab; its test processes and the API containers were cleaned up. Commit/push to dev is authorized and follows this verification; Git history records delivery.
