# Openlet backend documentation

Status: Go filesystem, direct gRPC/HTTP APIs, shared Go/Python contracts and SpiceDB authorization are implemented. All required local gates passed in the completed migration plan; historical provider checks do not establish acceptance of this source.

- [Architecture and scope](architecture.md): stack, ownership, identity, repository layout and operation.
- [Setup and verification](setup.md): foundation configuration, local commands and test isolation.
- [Operation and recovery](operations.md): limits, cleanup, coordinated backup, isolated restore and external release checks.
- [Data model and consistency](data-model.md): tree, quota, storage publication and lifecycle invariants.
- [Monolith database diagram](openlet-monolith.dbml): English DBML covering current application tables, constraints and physical/logical relationships.
- [API contracts](api-contracts.md): public/internal responsibilities and authorization.
- [Workflows](workflows.md): service-owned Temporal workflows, activities and recovery.
- [Testing](testing.md): native unit/integration and Playwright API E2E, with concrete correctness gates.
- [Production-pattern research](../plans/reports/research-261029-1220-production-patterns.md): upstream evidence versus Openlet adaptations.
- [File-operation retry research](../plans/reports/research-261029-1344-file-operation-retries.md): conditional/state recovery versus stored response replay.
- [Completed foundation migration](../plans/261102-1059-go-grpc-filesystem-authorization/plan.md): Go letfs, shared contracts, SpiceDB, direct filesystem access and recovery acceptance.
- [Previous implementation plan](../plans/261031-1758-simplify-backend-refactor/plan.md): API E2E rewrite, schema and lifecycle simplification, Gin/OpenTelemetry, processing and final acceptance evidence.

These documents supersede the discarded plan's specifications. Historical research/journals retain context, not current architecture authority. Redis, shared content/refcounts, source snapshots/epochs, custom gateway/leases and SDK experiments are not MVP requirements.
