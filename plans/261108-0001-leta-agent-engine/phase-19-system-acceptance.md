---
title: "Phase 19: System acceptance and final conflict review"
status: in-progress
priority: P1
dependencies: [18]
---

# Phase 19: System acceptance and final conflict review

## Overview

Prove the complete product journey through real service boundaries, exercise the accepted crash/retry cases, and deliver a coherent backend ready for frontend implementation. This phase is acceptance of earlier phase behavior, not permission to add new engine abstractions.

## Files and prerequisites

- Extend existing Playwright API suites under `e2e/tests/` using the actual current directory layout; add focused Leta journey and authorization tests rather than a second E2E framework.
- Use `apps/leta/tests/integration/` and app-owned workflow/replay tests for precise failure barriers; UI rendering assertions are typed contract assertions until frontend exists.
- Extend `e2e/setup/` owned Compose/recovery fixtures and log/history collection; Phase 18 owns their infrastructure changes.
- Record results in `reports/acceptance.md` inside this plan, with exact commands, source revision, outcomes and material not-run checks. Do not mark unchecked work complete because a plan or historical test passed.

## Standard end-to-end journey

1. Human active member creates Leta with selected model_id/reasoning_effort. Verify one independent root resource, one ordinary home scope, home/shared editor grants and one root runtime despite lost response/retry. No human user/bot membership is created.
2. Owner sends work using a stable message ID. Before the worker can process it, inspect pending/unknown acknowledgment semantics; after commit, UI DTO confirms inbox persisted.
3. Leta receives grouped digest, reads the detail, creates a two-Leti box with representative and one undirected edge, then sends work through the common send_message. Graph creation itself does not send work.
4. Representative/peer exchange messages only over their edge. A Leti issues ask_user with single-choice, multiple-choice and text questions in one form, then returns a short note while the request remains pending.
5. A separate schedule delivers a reminder to Leta. Leta sends a real owner-facing message while the Leti question is pending. Verify no agent-wide waiting-for-human state or blocking graph interrupt.
6. Owner submits the whole form with empty choice selection and a note where allowed. Input is delivered to the requesting Leti, not root and not a direct owner chat route. Work resumes on the same Leti thread.
7. Leti requests viewer access to another human's personal scope. Verify the card appears for RESOURCE OWNER, not Leta owner; the latter cannot approve it. Accept grants to the root Leta resource; Leti receives actual grant outcome and refreshes mounts.
8. Read/search through Mirage under `/users/<human-id>/`, including text artifacts and image preview. Resource owner revokes. A previously cached read/search now fails current authorization; history already read remains visible to Leta owner as disclosed.
9. Leti sends result to representative, representative sends under box identity to Leta, Leta sends to owner. Final text remains a note. No hidden chain-of-thought is requested/stored.
10. Trigger compaction with a controlled small context fixture, inspect the exact summary card, restart worker and resume from that summary/recent checkpoint without losing cursor or tool protocol. Full public transcript remains pageable.
11. Delete box while it has pending input/schedule/HITL. Confirm input is retained as history, future sources cancelled, runners stopped before home trash, no late resurrection and Leta's existing received grants unaffected by box deletion.
12. In a separate fixture, verify creator membership departure removes creator API/home access through normal policy, without an invented departure workflow or foreign-scope inheritance. Keep the original journey creator active to archive Leta, settle accepted grants before received-scope cleanup, preserve file/history visibility under ordinary active owner membership, remove received runtime scope grants and prove rebuild does not recreate discretionary revoked grants. Delete the workspace with initializing, active and archived roots and a queued accepted grant: all resources stop and received grants/resource tuples are removed before storage teardown, without reentering the locked WorkspaceChanges queue. Restore the coordinated backup in an owned isolated project and repeat core read/resume checks.

Use controlled model responses in deterministic acceptance tests so the scenario verifies engine behavior rather than model obedience. These doubles replace only the remote provider; use real PG/checkpointer, Temporal, Redis, SpiceDB, human identity, Workspace and LetFS boundaries. A separately configured real-model smoke is optional and explicitly reported, never silently loaded from development secrets.

## Failure and lifecycle matrix

| Boundary | Required outcome |
| --- | --- |
| Inbox commit before Update completion | Retry same ID returns one row; latest_seq wakes agent. |
| New input while model/tool executes | Collected at next safe boundary without tool-protocol corruption. |
| Bootstrap races receive | Latest sequence is merged rather than overwritten by old snapshot. |
| Assistant/tool IDs checkpointed, tool result not checkpointed | Stable effect identity; no duplicate message/request/box/schedule. |
| Shell/Monty result absent after crash | Command may replay; the agent can inspect/correct duplicate effects. No special unknown-outcome machinery. |
| Graph ended, run-result save failed | Finalize saved graph output rather than call model again. |
| Summary checkpointed, journal write failed | Resume publisher using saved summary, one compaction entry. |
| Journal committed, Redis publication failed | PG history correct; stream resync without repeating effect. |
| Response at HITL deadline / cancel race | One PG-validated terminal result, correct current status shown. |
| Approval accepted, grant dependency unavailable | Decision retained; actual grant pending/error/success shown accurately; requester receives settled outcome. |
| Already accepted request during archive | Settle grant before cleanup; no later access resurrection. |
| Schedule SQL committed, native apply failed | Same Workflow converges with stable canonical time/ID. |
| Worker stopped across scheduled time | Native delivery resumes with nominal scheduled_at; no duplicate occurrence. |
| Worker running long/idle/paused across history threshold | Cooperative checkpoint/yield and Continue-As-New retain state without a model-call budget. |
| Two Leti edit shared box file / stale worker cache | Backend preconditions reject lost updates; new reads see current fingerprint/permission. |
| Valid Redis cursor across disconnect/attempt change | Same root stream suffix, existing text prefix preserved, no PG polling. |
| Root stream interleaves Leta/Leti/new runs | One SSE demultiplexes AG-UI by agent/run, compatible deltas only coalesce after Redis. |
| Redis cursor trimmed/expired/evicted | Explicit resync from PG; no incomplete protocol suffix asserted complete. |

## Verification order

1. Run the owning phase's smallest useful tests after each fix. Do not rerun expensive unchanged suites without a new concern.
2. At final integrated revision, run `pnpm contracts:check`, `pnpm check`, `pnpm build`, `pnpm test`, then `make test-workflow` and `make test-integration` sequentially as existing resource conventions require.
3. Export fresh histories from actual integration scenarios for all six Leta Workflow types plus affected human-onboarding/Workspace/LetFS flows. Run `pnpm --filter @openlet/leta test:replay` and existing native replay commands. Missing required history is a failure, not skip.
4. Run `pnpm check:e2e`, list Playwright API tests to verify new discovery, then `pnpm --dir e2e exec playwright test --project=api`. Include existing file/quota/processing/copy/trash/authz/recovery regressions affected by LetFS/API changes.
5. Run bootstrap/recovery tests and the owned restore journey. The user waived a backup prerequisite for this fresh development implementation; recovery tests use owned isolated snapshots. Never reset user or production volumes to make tests green.
6. Run the focused text-search benchmark with the actual new SQL/query parameters and default planner. Record result correctness, plan/buffers, relation/index bytes and insert/update cost. Short/common substring scans are acceptable when measured; the selective corpus case must show an effective candidate path or explain a source-backed query fix before release. Do not set enable_seqscan off globally.
7. Run targeted longevity experiments, not a months-long soak: current Temporal history near rotation threshold, cold worker replay, a checkpoint table with many old entries but compact current state, and an active run exceeding Redis cap. Report recovery latency versus actual event/state/stream bytes, not calendar age. Keep limits configurable; do not promise constant database costs as storage grows.
8. Review source/docs/config/contract diff against [scope lock](design-contract.md). Check no old tool approval, send_box, task/job engine, outbox/poller, separate Leti service, hardcoded daily/weekly scheduler or raw blob access reappeared.
9. Inspect owned processes/containers/ports and stop test resources. Preserve user changes; no commit, push or deployment unless separately requested.

## Requirements

- [x] Full owner→Leta→box→Leti HITL→independent reminder→resume→owner result journey passes.
- [x] Resource-owner access approval, inheritance, revoke and archive cleanup pass real authorization checks.
- [x] Additional combined Leta journeys cover warm-cache revocation during a model call, replacement forms/duplicate answers, worker outage, mixed-input steering, graph route denial and expiration during pause. Coordinated restore includes accepted-but-unsettled approval.
- [x] Crash/retry, compaction, schedules, cache and replay evidence covers the actual final revision.
- [x] Contracts/docs/test commands agree and no accepted feature was silently cut or unrequested subsystem added.

## Completion evidence and rollback

Final integrated evidence is recorded in the [acceptance record](reports/acceptance.md). The [execution checkpoint](reports/phase-19-execution.md) preserves incremental failures, repairs and earlier open gates.

Acceptance report separates PASS, FAIL and NOT RUN with reasons, including real model/provider checks. Local controlled-provider success is not a live-model capability claim. Backend DTO tests prove custom components can be rendered, not that a frontend has been implemented.

Reconcile every phase checklist with actual evidence before changing overall status. Keep explicit remaining work if a required gate fails. On a release blocker, stop new Leta admission and retain data for diagnosis; use the coordinated rollback/restore procedure from Phase 18 rather than deleting durable records or weakening tests.
