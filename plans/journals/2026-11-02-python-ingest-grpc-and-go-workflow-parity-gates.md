---
title: Python ingest gRPC and Go workflow parity gates
date: 2026-11-02
summary: "Completed isolated Go/Python ingest, actual Temporal retries and replay, with the Rust runtime held for coordinated cutover."
---

# Python ingest gRPC and Go workflow parity gates

## What happened

Phase 5 now has actual Python activities calling generated Go ingest gRPC, using the real Docling Word/image parser, signed MinIO transfers and Qdrant. Completion responses are deliberately lost through all RPC retries; Temporal retries the activities, which prepare and reuse their committed results. Index-only execution and public semantic search pass. Native cancellation reaches the Go server context.

The reference API test exposed protobuf JSON serialization omitting the root's required empty path. A focused regression proved the omission before correction; the rebuilt Rust/HTTP processing journeys then passed. Review also corrected retry classification: internal failures retry, request/resource limits stop immediately. The new native gRPC regression tests failed before correction and pass afterward.

## Evidence

The complete race-enabled Go integration and unit/workflow suites, separate exported-history replay, tagged vet, native build, 97 Python tests, reproducible contracts and independent wheel checks passed. Two rebuilt reference API processing journeys passed. Evidence is in the active plan's phase-05 progress report. The simplification pass removed one redundant manifest list.

## Next

The deployed runtime remains Rust. Phase 6 switches the existing Python worker from LegacyProcessor to Processor, deletes the temporary HTTP binding, renames the app/module/package, activates Go/direct filesystem routes and removes the Workspace proxy with all bootstrap/CI/recovery consumers. Phase 7 owns final Rust removal and whole-system recovery. No real paid model evaluation was run.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
