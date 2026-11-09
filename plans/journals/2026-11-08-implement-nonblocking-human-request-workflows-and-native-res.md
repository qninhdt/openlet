---
title: Implement nonblocking human request workflows and native resource grants
date: 2026-11-08
summary: "Added finite HITL orchestration, agent tools, native Workspace grants and recovery checks; began pure schedule definitions."
---

# Implement nonblocking human request workflows and native resource grants

## What happened

Implemented phase13's finite HumanRequestWorkflow, Local SQL transitions and regular Workspace/inbox/settlement effects. Tools open structured requests and finish immediately; resource owners approve access to root Leta, including when a Leti asks. Request creation persists one UUIDv7 grant key in the existing row.

Actual Python→Go Workspace gRPC→PostgreSQL/SpiceDB tests verified ownership, current access, revoke and recovery after the real grant acknowledgement was lost during deletion. The first race-enabled run found a mutable binding fixture race; an RWMutex fixed the actual race and the native gate passed with -race.

Actual worker SIGKILL after decision commit recovered through Temporal without a Local marker. Separate completion-loss tests cover decision, outcome and inbox boundaries. Saved ask tool results survive graph recovery and unrelated work proceeds while the human is pending. Eight real-history replay fixtures/tests pass.

The first full service run was 234 passed, one failed, five native-fixture skips. New tool schemas raised the conservative schema estimate from 3623 to 5799 tokens; the image-recovery test's 10k model plus 4096-token image allowance correctly exceeded its budget. That test now uses the actual read_file tool only, keeping its image/path/checkpoint contract and the production context guard unchanged. Its focused rerun passed. The final full run is in progress; consult the execution report for its result.

## Review and next steps

Independent review found and fixed a completed-settlement namespace check; the final bounded rereview found no further concrete defect in grant recovery/admission. Simplification shared the existing Update-error traversal without changing contracts.

Phase13 still needs sparse publication and real WorkspaceChanges locked-queue teardown integration at their owning phases. Phase14 pure at/relative/anchored interval/calendar validation and native type translation has 28 passing tests; native schedules/forecasts/tools remain next. No commit, deployment, production migration or paid inference occurred.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.

## Final verification

The final full Leta regression passed **240 tests**, with five native-fixture skips, in 333.29s. Both native HITL cases passed separately inside the Go `-race` gate; the three Mirage fixture cases were not rerun for this change. Ruff lint/format passed for 71 files; plan format/local links and whitespace passed. No owned background process remains, and no publication/commit was performed.
