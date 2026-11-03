---
title: Refactor Go and Python service boundaries
date: 2026-11-03
summary: Completed four services with native shared clients and verified workflows.
---

# Refactor Go and Python service boundaries

## Outcome

Implemented the accepted feature, transport and Temporal boundaries for Account, Workspace, letfs and letfs-ingest. Both languages have shared destination clients and common identity, authorization, transport, error, configuration, telemetry and Temporal capabilities. Generated contracts remain independent of handwritten runtime code.

## Corrections found through real execution

Initial-workspace receipts needed durable lifetime beyond ordinary creation receipts. Polling workflows needed bounded histories. Archive adapters needed to preserve native failure codes and cancel Python streams deterministically. Python indexing had a duplicate VectorSpace type; one shared validated type repaired the real processing pipeline.

Old system fixtures expected public gRPC and cross-service child workflows. Updated assertions verify internal service and actor authentication, HTTP-only ingress and independent owner recovery. Host disk pressure caused MinIO writes to return 507; generated Go compilation cache was cleared. A cold-image recovery run exceeded its subprocess time budget; the later independent rerun passed without weakening checks.

## Verification

Native builds, static checks, unit tests, workflow tests, integration and all 11 offline parser/OCR cases passed. The final clean API run passed 33 tests; a separate clean backup and restore run passed its recovery journey. Fresh history replay passed for all three Go owners. Evidence and limitations are recorded in plans/261103-1348-service-refactor/verification.md.

## Delivery boundary

No commit, deployment or schema/data change to an existing environment. Live external-provider acceptance was not run. Fresh histories validate the new workflow definitions; pre-refactor history compatibility was outside the accepted greenfield scope. AgentWiki publish skipped.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
