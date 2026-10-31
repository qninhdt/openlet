---
title: Complete Gin tracing and replace Account onboarding orchestration
date: 2026-10-31
summary: Verified cross-language tracing and native continuation/replay; replaced Account operation state with lifecycle and a Workspace child.
---

# Complete Gin tracing and replace Account onboarding orchestration

## What changed

Phase 3 now has real Go→Rust→Temporal→Python generation/indexing correlation, native Rust Continue-As-New/replay evidence and an unavailable-exporter gateway baseline. The model fixture needed actual Instructor text-part arrays; JSON-stringifying messages or assuming strings caused 400s.

Account no longer has operations or workflow-internal Workspace HTTP polling. Clerk identity durably admits a user; the Workspace child returns its owned ID before Clerk publication. A native five-minute schedule reconciles pending lifecycles. The initial provisioning response permits a null Workspace ID; E2E now checks it at readiness.

Workspace resource reads/status and storage-table merge are in progress. Workspace receipts, direct Letfs Activities/deletion children and final recovery acceptance remain open; phase 4 is not complete. No external provider or remote CI claim is made.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
