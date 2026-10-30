---
phase: 1
title: "Foundation and Real Provisioning"
status: pending
priority: P1
effort: "4d"
dependencies: []
---

# Phase 1: Foundation and Real Provisioning

## Goal

Establish the three-service repository, private infrastructure, authenticated routing, and real letfs bucket/filesystem/root provisioning required by later phases.

## Scope

- User and Workspace are independent Go/Chi services; letfs is Rust/Axum.
- One PostgreSQL instance hosts separate service databases/credentials and separate Temporal persistence/visibility databases.
- Each workflow will run on the official Go or Rust SDK worker in its owning service when its phase introduces real workflow code.
- Redis, a custom gateway application, SDK sidecars, and placeholder storage stubs are out of scope.

## Files to Create / Modify

Paths below are relative to `/home/qninh/projects/openlet`; all are planned creations or extensions from prior phases.

- Create: `go.work`, `Makefile`, `.env.example`
- Create: `services/user/{go.mod,cmd/server/,internal/config/,internal/http/,internal/temporal/}`
- Create: `services/workspace/{go.mod,cmd/server/,internal/config/,internal/http/,internal/letfs/,internal/temporal/}`
- Create: `services/letfs/{Cargo.toml,src/config/,src/http/,src/fs/,src/temporal/,migrations/}`
- Create: `contracts/internal/openapi.yaml`
- Create: `deploy/{compose.yaml,envoy/,postgres/,temporal/}`
- Create: `scripts/verify-foundation.sh`, `scripts/test-integration.sh`

## Data Flow

1. A client reaches only Envoy; service ports remain private to Compose.
2. Envoy verifies a test JWT issuer/JWKS, removes client-supplied trusted headers, and forwards verified claims.
3. Workspace calls letfs over authenticated HTTP with a stable provision key, bucket/filesystem IDs, limit, and root name.
4. letfs commits the bucket, filesystem, and root node and returns the existing result on an identical retry.
5. Services start real HTTP endpoints with graceful shutdown. Owner-local worker registration arrives with real domain workflows; cross-domain work uses internal HTTP, not Go-to-Rust Temporal calls.

## Requirements

- [x] Pin Go, Rust, PostgreSQL, Envoy, Temporal Server, and SDK versions in reproducible files.
- [x] Validate URLs, credentials, issuer/audience, limits, and service tokens at startup without logging secrets.
- [x] Give User, Workspace, letfs, Temporal persistence, and Temporal visibility separate databases and credentials.
- [x] Configure Envoy native JWT verification, bootstrap restriction, trusted-header stripping, request IDs, configurable local token-bucket rate/burst limits, and routing. Document per-instance semantics and reject excess bursts in the Envoy integration test; no distributed rate-limit service.
- [x] Use a local test issuer/JWKS to prove Envoy behavior without claiming Clerk integration.
- [x] Implement liveness/readiness endpoints that distinguish process, database, and Temporal health.
- [x] Implement authenticated letfs `EnsureQuotaBucket` and `EnsureFilesystem`; creation includes exactly one root.
- [x] Make provisioning idempotent by stable key and reject immutable-scope mismatch as conflict.
- [x] Pin SDK dependencies but introduce worker registrations only with real owning workflows in phases 2/4; no throwaway SDK probes.
- [x] Keep network I/O outside database transactions and row locks.

## Implementation Steps

1. Create the service modules and workspace commands without a shared business-model package.
2. Add Compose networks, health checks, schema initialization, migrations, and named volumes without embedded credentials.
3. Add service-specific configuration, structured logs, request IDs, and graceful HTTP/worker shutdown.
4. Configure Envoy's JWT filter and internal header policy, exposing only the gateway port.
5. Define initial internal OpenAPI envelopes, service authentication, errors, and provisioning DTO fixtures.
6. Add letfs migrations for `quota_buckets`, `filesystems`, `nodes`, and provisioning uniqueness.
7. Implement letfs application functions and private routes for bucket/filesystem ensure and get.
8. Configure the persistent Temporal server, private namespace and SDK connection settings; integrate native workers with real workflows in phases 2/4.
9. Add Workspace's minimal adapter so phase 2 uses real letfs behavior rather than a fake.
10. Add deterministic scripts for migrations, routing, restart, and provisioning retry.

## Test Matrix

| Layer | Evidence |
|---|---|
| Unit | Config rejection and provisioning-input validation; Envoy header rules are tested against Envoy rather than custom filtering code |
| Integration | Real PostgreSQL migrations, retry/conflict uniqueness, service-token rejection |
| Workflow infrastructure | Persistent Temporal namespace/readiness after restart; real workflow retry tests begin with onboarding in phase 2 |
| System | Compose health, gateway-only exposure, JWT allow/deny, bucket/filesystem/root creation, configured local-rate-limit rejection |

## Planned Verification Commands

These targets are phase deliverables and do not exist before implementation.

```bash
make fmt-check
make test-unit
make test-integration TEST=foundation
make test-e2e TEST=compose-smoke
```

## Failure Modes and Mitigations

| Failure | Risk | Mitigation |
|---|---|---|
| Schema is not ready at startup | High | One-shot initialization, readiness gates, bounded retry |
| Client spoofs identity headers | High | Strip before JWT processing and assert downstream values |
| Lost response duplicates storage | High | Unique provision key and return committed resource on retry |
| Version mismatch appears later | High | Pin versions, restart real infrastructure now, and test real workflow recovery in owning phases |
| Secrets leak | High | Placeholder env, mounted secrets, log-redaction assertions |

## Rollback

- Stop the new stack and workers cleanly.
- Roll back phase-1 schemas only while no later phase data exists; preserve volumes until dumps are verified.
- Revert image/SDK pins together with configuration and fixtures.
- Never use `docker compose down -v` as routine rollback.

## Success Criteria

- [x] A clean checkout builds and starts all services, Envoy, PostgreSQL, and Temporal with one documented command.
- [x] Only Envoy is host-accessible; forged headers and invalid JWTs fail closed.
- [x] Separate credentials cannot read another service or Temporal database.
- [x] Identical provisioning retry returns one bucket, filesystem, and root; changed immutable input conflicts.
- [x] PostgreSQL/Temporal/service restarts preserve committed storage and Temporal namespace; workflow recovery is verified in phase 2.

