# Openlet

Workspace agents, file storage and durable document processing.

Platform owns users, workspaces and invitations. LetFS owns workspace storages, files, quota and artifacts. Leta owns autonomous root agents and Leti teams, using native LangGraph agents and Temporal orchestration. Two Python ingest workers parse blobs and enrich/index their output through Temporal. PostgreSQL holds domain data; SpiceDB holds membership and grants. Envoy exposes core APIs as HTTP/ProtoJSON and routes Leta HTTP/SSE directly.

- [Architecture](docs/architecture.md)
- [Setup and commands](docs/setup.md)
- [API contracts](docs/api-contracts.md)
- [Testing](docs/testing.md)
- [Operations and recovery](docs/operations.md)
- [Cloud observability and managed prompts](docs/observability.md)
- [Rewrite progress and acceptance](plans/261111-1727-platform-letfs-rewrite/plan.md)

Go services use Go 1.27.4, Python uses 3.14, and API E2E uses TypeScript/Playwright. Local and CI infrastructure use Docker Compose. The rewritten Leta runs in the optional `leta` Compose profile; core also runs independently. Computer is design-only. See the [Leta execution record](plans/261111-2010-leta-rewrite/execution.md) for implementation checks and remaining deployment checks.
