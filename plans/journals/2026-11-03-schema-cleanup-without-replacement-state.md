---
title: Schema cleanup without replacement state
date: 2026-11-03
summary: "Removed 30 columns and merged index status, retaining all eight metadata timestamps; 14 tables and 119 columns remain."
---

# Schema cleanup without replacement state

## What happened

Implemented the accepted schema review across Workspace, Account onboarding, letfs, Python ingest, protobuf bindings, public API schemas, recovery fixtures and DBML. Workspace admission commits once and provisioning resumes by existing workspace ID. Processing uses source generation, upload identity and one pipeline status; Temporal owns retries. Removed permanent creation fingerprints/service ownership, custom attempt protocol, manifest hashes, duplicate timestamps/generations, copied upload fields and per-row embedding configuration. No replacement persistent state was added.

Initial boundary tests exposed assertions for intentionally removed contracts and stale fixtures. Updated those expectations while keeping real authorization, atomic quota/publication, generation checks, S3 transfer validation and cleanup behavior. Final reference scanning also found stale public OpenAPI fields and one standalone recovery fixture; both now match the schema.

## Verification

Schema inventory and DBML agree: 14 tables, 150 to 119 columns, all eight retained metadata timestamps present. pnpm check, unit/script tests, workflow suites, Workspace integration and full race-enabled letfs integration passed. API/recovery E2E passed 34/34. All three Go owners replayed fresh Temporal recordings successfully after the E2E history set was complete.

## Limits

Only baseline migration sources changed; no existing persistent database was reset or migrated. Test databases were disposable and owned processes/containers finished cleanup. Existing dev installations need the previously authorized reset to apply this baseline. No commit or push was requested. AgentWiki publish skipped.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
