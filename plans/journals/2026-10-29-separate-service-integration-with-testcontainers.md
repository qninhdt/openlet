---
title: Separate service integration with Testcontainers
date: 2026-10-29
summary: Replace Compose service integration entry point with native Testcontainers suites while preserving system E2E and recovery.
---

# Separate service integration with Testcontainers

## Change

User requested Testcontainers after inspection showed the integration target delegated to the complete Compose stack. Added native Go and Rust fixtures with fresh PostgreSQL, real backup/migrations, dynamic ports and cleanup. User tests cover concurrent identity admission/profile persistence. Workspace tests cover provisioning replay, verified invitations, ownership and concurrent workspace limits. letfs covers paths, revisions, hard shared quota, inline bytes and real S3 upload/finalize.

## Boundaries

Compose retains complete gateway/cross-service/restart/backup journeys. Replay histories now point to the E2E command. Test fixtures never read development Clerk/R2 credentials. The Rust fixture needs a Temporal dev server for the concrete App client; it does not claim durable workflow recovery coverage.

## Verification and corrections

Focused suites passed individually; verify and Compose foundation passed. The final repeated letfs run exposed the host disk falling below SeaweedFS's one-percent safety threshold after image builds. A bounded 256 MiB tmpfs isolates the disposable S3 fixture; no provider safety threshold or production configuration was weakened. Final acceptance evidence is in the Testcontainers implementation report.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
