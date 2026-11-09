# Phase 17 execution checkpoint: stop before workspace storage deletion

Historical increment: the open gates below were subsequently exercised. See [final integrated acceptance](acceptance.md) for current phase reconciliation and fixture boundaries.

## Implemented

- Workspace-only native ListWorkspaceLeta enumerates canonical roots in every
  lifecycle state, with exact workspace/keyset/limit checks and no delegated actor.
- StopLetaForWorkspaceDeletion verifies binding and direct deleting Workspace
  status, invokes the existing lifecycle and acknowledges actual completion.
  Ordinary archived roots reenter cleanup for workspace teardown.
- Existing Go DeleteWorkspace marks deleting, pages roots, stops in windows of8,
  then invokes its existing LetFS child and removes Workspace.
- Workspace teardown removes root resource relationships after exact received-grant
  cleanup. Ordinary archive retains resource/home read relationships. No new
  Workflow, receipt, lock or outbox was introduced.

## Verification

- Ordering regression failed against the old deletion sequence. Updated Workflow
  suite passes, including130 roots across100+30 pages and failed-stop storage guard.
- Go native clients, Workspace checks and generated contracts pass.
- Python native inventory/admission/persistent-Temporal cleanup: **3 passed in14.62s**.
  Includes archived roots, held cleanup, actual root/Leti COMPLETED before native
  acknowledgement, and safe retries.
- Go TestIntegrationWorkspaceDeletionWaitsForNativeLetaCleanup with
  OPENLET_LETA_HITL_INTEGRATION=1: **passes in15.60s**. Actual Go Workspace/Python
  Leta authenticated callbacks, both PostgreSQL owners, SpiceDB and shared persistent
  Temporal. WorkspaceChanges holds its deletion mutex while direct cleanup finishes.
  A pending child ask is cancelled; an accepted/unapplied grant settles; a real
  recurring Schedule is removed; busy root/child Activities finish cleanup. Storage
  stays untouched during held settlement and runs once afterwards. Busy runner and
  storage child are explicit external-boundary fixtures, so real model/Mirage
  close-before-storage remains a system gate.
- Full Leta run:280 passed,4 startup-fixture failures,5 native-fixture skips. The
  four failures share a missing gRPC method on the fake channel; all7 owning tests
  pass after that test-only repair. The new native journey is additional evidence.

## Remaining gates

- Authorization recovery must respect root/home and Workspace lifecycle tombstones;
  never recreate direct grants from HITL history. Phase18 owns operational wiring.
- Fresh changed Go deletion/Python teardown history replay.
- Full model/Mirage shutdown, initializing-create race, interrupted native cleanup,
  and queued/lost-ack grant cases using existing phase04/12/13 evidence and final fixture.
- Production worker, exact credentials, migrations, Redis and deployment wiring.

Fixture-owned processes and containers exited after tests.
