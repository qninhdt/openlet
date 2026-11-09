# Openlet

Backend for a cloud file application with durable AI agents.

Backend: Clerk onboarding, workspaces, ID/path file operations, exact inline bytes, direct S3 transfers, quota, trash/restore, Docling artifacts, semantic search and streamed ZIP downloads. File copy/purge run in requests; Temporal handles filesystem/scope deletion, processing, maintenance and independent Leta/Leti execution. The plan records verification and external-provider limits.

- [Backend documentation](docs/README.md)
- [Setup and verification](docs/setup.md)
- [Leta agent engine implementation](plans/261108-0001-leta-agent-engine/plan.md)
- [Direct cross-scope file operations](plans/261107-1114-direct-cross-scope-file-operations/plan.md)
- [Account/scope implementation plan](plans/261106-1517-account-scope-temporal-redesign/plan.md)
- [Foundation validation history](plans/261102-1059-go-grpc-filesystem-authorization/plan.md)

The backend uses Go/Gin for Account and Workspace, Go HTTP/gRPC for letfs, Python Leta API/agent and CPU/I/O ingest workers, Redis, Envoy, Clerk, PostgreSQL, SpiceDB, Temporal and configurable S3-compatible storage. All applications support OpenTelemetry. Frontend and billing are outside this round.

Native apps live under `apps/`; pnpm/Turbo coordinates Go and uv. Development wiring is `infra/compose/dev.yaml`; the fresh API E2E environment is `infra/compose/e2e.yaml`. The completed refactor replaces public APIs/schema directly; external-provider and remote CI verification limits are recorded in the plan's validation evidence.
