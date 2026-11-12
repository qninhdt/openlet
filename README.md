# Openlet

Workspace resources with native gRPC APIs, file storage and durable document processing.

Platform owns users, workspaces and invitations. LetFS owns workspace storages, files, quota and artifacts. Two Python ingest workers parse blobs and enrich/index their output through Temporal. PostgreSQL holds domain data; SpiceDB holds membership and grants. Envoy exposes the public APIs as HTTP/ProtoJSON.

- [Architecture](docs/architecture.md)
- [Setup and commands](docs/setup.md)
- [API contracts](docs/api-contracts.md)
- [Testing](docs/testing.md)
- [Operations and recovery](docs/operations.md)
- [Rewrite progress and acceptance](plans/261111-1727-platform-letfs-rewrite/plan.md)

Go services use Go 1.27.4, Python uses 3.14, and API E2E uses TypeScript/Playwright. Local and CI infrastructure use Docker Compose. Leta is archived for a separate rewrite; Computer is design-only. Core startup and tests work without either service.
