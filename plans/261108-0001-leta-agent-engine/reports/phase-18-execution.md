# Phase 18 execution checkpoint

Historical increment: the open gates below were subsequently exercised. See [final integrated acceptance](acceptance.md) for current phase reconciliation and fixture boundaries.

## Implemented

- One locked nonroot Leta wheel image supplies API, worker, migration, health and offline authorization rebuild entrypoints. Production worker supplies all six Workflow types and the real AgentRunner/Mirage/native/Redis integrations.
- Bootstrap preserves Leta DB/Redis credentials and the configurable model catalog. Dev/E2E Compose run explicit domain/saver migrations, required private authenticated Redis (256 MiB, allkeys-lru, no persistence), Leta API/worker and Workspace RPC. Envoy routes normal product APIs and one root/child SSE connection separately.
- Graceful worker shutdown yields at a checkpoint boundary and releases run resources. API/worker startup verifies migrations and every persisted effective model selection.
- Recovery captures seven databases including Leta product/checkpoints, the model catalog and existing blob/index sources. Restore is isolated; resume rebuilds derived Workspace and Leta resource/home bindings from owning lifecycle facts before reopening writers. Direct viewer/editor grants are never replayed from HITL history.
- Workspace exports sorted JSON-lines inventory without starting listeners/workers. Build is separate from export/import: Compose build progress on stdout previously corrupted the JSON pipe; the actual restore test reproduced this and now passes.
- Added offline replay fixtures for LetaLifecycleWorkflow and BoxLifecycleWorkflow; all six Leta Workflow types now have replay coverage. CI includes Leta replay.

## Verified

- Existing bootstrap/recovery subset: 20 passed before current recovery repair; recovery script regression now 14 passed.
- Leta image build, CLI smoke and dev/E2E Compose config pass.
- Real Compose onboarding smoke: 2 passed.
- Real isolated backup/restore/resume: 1 passed in 114.67 seconds, after repairing the build-log/JSON boundary. Fixture containers/volumes were cleaned.
- Real Go Workspace/Python Leta/SpiceDB resource-request integration with the added post-revoke rebuild check: passes in 19.28 seconds. Rebuild restores creator resource visibility without restoring revoked personal access.
- Lifecycle rotation/capture test: 1 passed in 5.09 seconds; standalone six-type replay suite: 13 passed.
- Monorepo contracts and check pass with the supported Go binary on PATH. E2E typecheck passes.
- Previous worker-shutdown subset: 2 passed in 9 seconds.

## Active work and remaining acceptance

Phase 19's deterministic remote-model journey passes through the real Compose runtime in 9.5 seconds. It covers owner input, immutable two-Leti box, child ask with all question types/empty choices/notes, an independent reminder, resource-owner approval, inherited Mirage access, explicit box/result messaging, archive and workspace cleanup. Acceptance repaired the public typed scope-access adapter, UUIDv7 home provisioning and the provider fixture's required SSE metadata. See the [system acceptance checkpoint](phase-19-execution.md) for current regression evidence and remaining gates.

Full integrated regression, expanded product-state restore and final replay/acceptance matrix remain open. Do not infer these from the basic restore or narrow native tests. Saver tables use their existing upstream-managed names in the dedicated Leta database alongside domain tables; no additional schema/search_path adapter is needed or implemented.
