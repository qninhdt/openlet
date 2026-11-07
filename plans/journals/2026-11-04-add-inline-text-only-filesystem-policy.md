---
title: Add inline text only filesystem policy
date: 2026-11-04
summary: "Immutable filesystem creation policy enforced across inline writes, uploads and processing, with Go/Python contracts and integration coverage."
---

# Add inline text only filesystem policy

Implemented `inline_text_only`, default false, on LetFS filesystem creation and reads. Added an additive migration; existing data stays unrestricted. Creation fingerprints omit false to retain existing idempotency receipts. Policy changes through identity reuse are rejected.

Restricted writes accept UTF-8 text without control characters except tab/CR/LF. Public and processing object admission are disabled. Restricted sources use text processing regardless of filename; same-filesystem copy retains validated payloads. Go/Python clients and generated contracts carry the flag; existing Go call syntax defaults to false.

Validated focused real PostgreSQL/SpiceDB/MinIO and authenticated HTTP/gRPC/Temporal integration, all affected Go unit tests, 22 Python unit tests, contract generation drift, lint/vet/build and workflow checks. Scoped simplifier review found no changes needed. No live database or deployment was changed; full Compose E2E and external-provider checks were outside this run. Apply migration 0002 after backup and before starting the updated binary. See plans/261104-1532-inline-text-only/plan.md for validation details.

AgentWiki publish skipped; this entry is local only.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
