---
title: Simplify workflow admission and incremental authorization
date: 2026-11-03
summary: Move durable Account/Workspace mutations into Temporal and replace graph snapshots with targeted relationship writes.
---

# Simplify workflow admission and incremental authorization

## What happened

Account and Workspace now submit durable work before business SQL mutations. Onboarding uses one Workspace child; storage creation is one grouped letfs Activity. Workspace authorization changes run as serialized Temporal Updates with the existing SQL receipt table protecting acknowledgement-loss retries.

Stable role groups and affected-member writes replace revision/status snapshots and periodic graph scans. Owner transfer publishes both members atomically. Offline rebuild and receipt expiry remain. letfs skips no-op copy completion and duplicate deletion admission work, and maintenance attempts every phase before returning combined errors.

## Verification

Root check, unit and build suites passed. All three Go workflow suites passed. Account/Workspace PostgreSQL/SpiceDB integration and grouped letfs provisioning/deletion against real Temporal passed. The complete API suite passed 34 tests, followed by a final-source API rerun with 33 tests. Fresh Account, Workspace and letfs histories replayed successfully. Documentation links and diff whitespace checks passed.

Review found and fixed Update-handler ActivityOptions inheritance, concurrent create-payload validation, duplicate deletion starts, activation/deletion ordering, receipt expiry scope and missing-resource error classification. Review was performed inline with the connected callers and tests.

## State

The initial implementation completed without an application schema or role-policy change. The user subsequently approved hybrid Activity placement and requested commit/push to dev.

## Hybrid follow-up

`PrepareMutation` now runs as a Local Activity with a five-second attempt timeout. `ApplyMutation` remains a regular Activity so scheduling it persists the original preparation before SQL mutation. The SDK test verifies local dispatch while retaining serialized retry behavior.

A real worker was killed with SIGKILL after the ownership SQL commit and before graph publication/Activity acknowledgement. Its replacement recovered the same preparation, preserved the SQL revision, completed the existing receipt and corrected graph permissions. Native replay passed. The recovery harness and history remain outside the repository.

Final root check, all workflow suites and the Workspace SQL/SpiceDB mutation integration passed. The final-source API suite passed 33/33 tests, and fresh Account, Workspace and letfs histories replayed successfully. Diff review and whitespace/credential checks passed. Test processes and containers were cleaned up. The verified implementation is ready for the authorized commit/push to dev; Git history records delivery.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
