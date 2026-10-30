# Openlet

Backend for a cloud file application.

Implemented backend: Clerk onboarding, workspaces, ID/path file operations, editable inline text, direct S3 transfers, quota, trash/restore, Docling artifacts and temporary ZIP exports. Temporal handles durable copy/deletion, processing, exports and maintenance. The plan records verification and remaining recovery/release gates; Clerk development and Cloudflare R2 are configured locally.

- [Backend documentation](docs/README.md)
- [Setup and verification](docs/setup.md)
- [Active implementation plan](plans/261029-1624-artifact-file-processing/plan.md)

The MVP uses Go/Chi for User and Workspace, Rust/Axum for letfs, Envoy, Clerk, PostgreSQL, Temporal and configurable S3-compatible storage. Frontend, billing and AI execution are outside this round.
