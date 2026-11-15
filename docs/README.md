# Openlet documentation

Executable contracts and migrations own the wire format and database schema. The [active rewrite plan](../plans/261111-1727-platform-letfs-rewrite/plan.md) records acceptance and outstanding verification.

- [Architecture](architecture.md): service ownership, authorization and boundaries.
- [Setup](setup.md): configuration, generation and local commands.
- [API contracts](api-contracts.md): gRPC, HTTP/ProtoJSON, identity and errors.
- [Data model](data-model.md): domain data, quota, versions and idempotency.
- [Workflows](workflows.md): Temporal ownership and processing.
- [Testing](testing.md): focused checks and API E2E.
- [Operations](operations.md): deployment, backup and empty-target restore.

Leta has a [separate design](../plans/261111-2010-leta-rewrite/plan.md), with its implementation deferred. Older plans and reports describe historical systems; their commands and schema are not current product contracts.
