# Openlet

Backend for a cloud file application.

Backend: Clerk onboarding, workspaces, ID/path file operations, exact inline bytes, direct S3 transfers, quota, trash/restore, Docling artifacts, semantic search and streamed ZIP downloads. Temporal handles durable partial copy/deletion, processing and maintenance. The plan records verification and external-provider limits.

- [Backend documentation](docs/README.md)
- [Setup and verification](docs/setup.md)
- [Completed implementation plan and validation](plans/261031-1758-simplify-backend-refactor/plan.md)

The backend uses Go/Gin for Account and Workspace, Rust/Axum for letfs, separate Python CPU/I/O workers, Envoy, Clerk, PostgreSQL, Temporal and configurable S3-compatible storage. All applications support OpenTelemetry. Frontend, billing and agent execution are outside this round.

Native apps live under `apps/`; pnpm/Turbo coordinates Go, Cargo and uv. Development wiring is `infra/compose/dev.yaml`; the fresh API E2E environment is `infra/compose/e2e.yaml`. The completed refactor replaces public APIs/schema directly; external-provider and remote CI verification limits are recorded in the plan's validation evidence.
