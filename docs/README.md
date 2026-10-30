# Openlet backend documentation

Status: backend implemented; local acceptance and real Clerk/R2 smoke checks passed. Provider-specific recovery acceptance remains open. The plan records evidence; the following documents describe the accepted delivery scope.

- [Architecture and scope](architecture.md): stack, ownership, identity, repository layout and operation.
- [Setup and verification](setup.md): foundation configuration, local commands and test isolation.
- [Operation and recovery](operations.md): limits, cleanup, coordinated backup, isolated restore and external release checks.
- [Data model and consistency](data-model.md): tree, quota, storage publication and lifecycle invariants.
- [API contracts](api-contracts.md): public/internal responsibilities and authorization.
- [Workflows](workflows.md): service-owned Temporal workflows, activities and recovery.
- [Testing](testing.md): four test groups and concrete correctness gates.
- [Production-pattern research](../plans/reports/research-261029-1220-production-patterns.md): upstream evidence versus Openlet adaptations.
- [File-operation retry research](../plans/reports/research-261029-1344-file-operation-retries.md): conditional/state recovery versus stored response replay.
- [Active implementation plan](../plans/261029-1624-artifact-file-processing/plan.md): direct storage, hybrid artifacts, processing, ZIP and recovery status.

These documents supersede the discarded plan's specifications. Historical research/journals retain context, not current architecture authority. Redis, shared content/refcounts, source snapshots/epochs, custom gateway/leases and SDK experiments are not MVP requirements.
