# Assumption and scope audit

Scope: plan documents only for `plans/261102-1059-go-grpc-filesystem-authorization/`. No application builds or tests were run.

## Findings

### Critical — letfs-owned authorization projection has no implementation phase

- **Plan location:** `architecture-contract.md:43-45,104-118`; `phase-03-workspace-authorization-and-durable-projection.md:73`; `phase-04-go-filesystem-core-and-storage.md:42-71,73-86`; `phase-05-go-workflows-ingest-and-search.md:44-87,88-104`; `phase-06-direct-filesystem-api-and-proxy-removal.md:20-23,46-56`.
- **Flaw:** The architecture makes letfs the canonical owner of filesystem-to-resource binding and requires every canonical owner to persist projection intents/acks and run ordered CAS/epoch-fenced projection. Phase 3 explicitly postpones whole-letfs rebuild, but Phases 4-5 only assign binding storage, ordinary filesystem workflows, and admission checks. Neither phase assigns letfs projection tables/intents, a projection workflow/activity/reconciler, relationship-head ownership, acknowledgment semantics, replay, or rebuild snapshot access. Phase 7 mentions replay/recovery of “projection” after Phase 6 has already enabled direct routes.
- **Failure:** Phase 6 can reach direct filesystem authorization with no durable writer for the binding tuples on which inherited checks depend. A fresh filesystem either remains absent from SpiceDB and is denied, or requires an unplanned/manual write that violates the canonical-owner and recovery contracts. Binding deletion/reassignment also has no stale-write fence before public cutover.
- **Evidence:** Today the cross-owner association is only Workspace's stored `filesystem_id`/`root_id` (`apps/workspace/migrations/0001_initial.sql:47-51`), while letfs provisions a filesystem using a workspace-derived `provision_key` and returns it without any graph write (`apps/letfs/src/fs/provisioning.rs:109-118`). There is no current projection mechanism to inherit.
- **Fix within accepted scope:** Assign letfs binding aggregate revision/intent/ack and tuple ownership to Phase 4's schema/domain work; assign its Temporal projector, reconciler, CAS/epoch tests, rebuild snapshot, replay, and failure semantics to Phase 5. Make those gates prerequisites for Phase 6 and include them in the verification matrix.

### High — the ingest rename makes the pre-cutover stack unrunnable

- **Plan location:** `phase-02-shared-go-contracts-and-infrastructure.md:43,55`; `phase-05-go-workflows-ingest-and-search.md:14,55-57,76-86,99-104,169-170`; `phase-06-direct-filesystem-api-and-proxy-removal.md:51`.
- **Flaw:** Phase 2 creates generated files inside the future `apps/letfs-ingest` destination while the real app still lives at `apps/letfs-processing`. Phase 5 then says to move the old directory atomically to that already-created destination, yet explicitly preserves both Compose files and defers their path/service switch to Phase 6.
- **Failure:** The move has a destination collision, and after it the checked-in dev/E2E Compose definitions still build `apps/letfs-processing/Dockerfile`. Therefore the claimed Phase-5 state cannot both have a complete rename and retain a runnable pre-cutover Rust/Python stack. Clean E2E startup, rollback, and the Phase-6 entry gate become dependent on unstated manual filesystem/config surgery.
- **Evidence:** The only current uv workspace member is `apps/letfs-processing` (`pyproject.toml:1-2`); the final directory does not exist. Dev and E2E Compose hard-code the old Dockerfile path (`infra/compose/dev.yaml:222-228`, `infra/compose/e2e.yaml:231-233`), and E2E startup names the old services (`e2e/setup/environment.ts:180`).
- **Fix within accepted scope:** Choose one coherent stage. The smallest is to generate/package `openlet_api` under the current app through Phase 4, then in Phase 5 move the directory and update build-path-only consumers needed to keep the pre-cutover Rust stack runnable; Phase 6 can still switch service/env/queue names and gRPC runtime together. Do not pre-create the move destination.

### High — Phase 1's Python/codegen proof is scheduled before its owning artifacts and packaging changes

- **Plan location:** `architecture-contract.md:58-61`; `phase-01-contracts-and-proof-gates.md:34-41,48,52-55,59-66,77-82`; `phase-02-shared-go-contracts-and-infrastructure.md:38-46,55-64`; `phase-05-go-workflows-ingest-and-search.md:78-83,99-101`.
- **Flaw:** Phase 1 must generate Go/Python stubs, prove installed-wheel imports and a real RPC round trip, and finalize Buf/OpenAPI generation. Its file inventory does not own Buf config, generated output trees, or Python wheel configuration/dependencies; those are first assigned to Phases 2 and 5. The phase cannot satisfy its own blocking proof using durable final artifacts without silently pulling later-phase scope forward.
- **Failure:** The foundational proof gate is either non-executable, implemented with disposable/ad-hoc generation contrary to the plan, or marked complete before the actual wheel/import contract exists. Downstream proto namespace and OpenAPI decisions can then change after consumers start implementation.
- **Evidence:** The current wheel includes only `src/openlet_processor` (`apps/letfs-processing/pyproject.toml:46-47`) and its direct dependency list has no declared generated gRPC runtime contract (`apps/letfs-processing/pyproject.toml:5-17`). Current workspace/package discovery also knows only the old app (`pyproject.toml:1-2`, `pnpm-workspace.yaml:1-3`).
- **Fix within accepted scope:** Move the minimal Buf configs, generated Go/Python outputs, and staged wheel packaging/direct runtime dependencies into Phase 1 ownership (using the current Python app path until the atomic rename), then let Phase 2 extend/integrate them. Keep Phase 5 responsible for the name move, not first proof of package inclusion.

### Medium — the final old-name cleanup gate cannot detect several required rename surfaces

- **Plan location:** `plan.md:47-48`; `phase-07-rust-removal-recovery-and-acceptance.md:38-40,53-58,81-87`.
- **Flaw:** Phase 7 requires complete service/config/secret/queue cleanup, but its only scoped search checks `openlet_processor|openlet-processor|letfs-processing|cargo |rust-toolchain`. It omits the active service names, environment/secret names, and image names that the plan also requires to change; it also omits `Makefile` from the searched targets despite assigning Rust cleanup there.
- **Failure:** Final acceptance can report “no obsolete active references” while `processor-cpu`, `processor-io`, `PROCESSOR_*`, `processor_service_token`, or Rust commands in `Makefile` remain. Those leftovers can break restart/recovery controls or leave the rename incomplete even though the completion criteria pass.
- **Evidence:** These unsearched names are active in `infra/compose/dev.yaml:222-253`, `infra/compose/e2e.yaml:231-254`, `e2e/setup/environment.ts:180`, `e2e/fixtures/restart-service.ts:9-21`, and `scripts/operations/recovery.py:19-27`.
- **Fix within accepted scope:** Expand the final inventory/gate to the exact accepted old-name families and all assigned active files, including service names, env/secret identifiers, image/package/module names, queue names, recovery/E2E controls, CI, and `Makefile`. Treat each intentional retained occurrence explicitly rather than relying on the current narrow regex.

## Unresolved questions

None. The findings are phase-ownership and staging defects inside the already accepted scope; they do not require a product decision.

Status: DONE
Summary: Four load-bearing plan defects found: missing letfs graph projection ownership, an unrunnable ingest rename stage, a proof-gate/codegen ordering gap, and an incomplete final rename cleanup gate.
Concerns/Blockers: No application tests/builds were run as requested; findings are source- and plan-grounded.
