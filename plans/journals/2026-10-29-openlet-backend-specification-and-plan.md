---
title: Openlet backend specification and plan
date: 2026-10-29
summary: "Recorded accepted scope, existing Envoy gateway, no application lease subsystem, and six implementation phases."
---

# Openlet backend specification and plan

## Work

Created current architecture, data, API and workflow specifications plus a six-phase implementation plan. Researched Temporal Rust GA support and kept real Go/Rust integration as the first executable gate. Four design-review lenses exposed scope, ownership, retry and cleanup gaps; the controller reconciled the specifications.

## Correction

The user rejected an unrequested custom Go gateway and questioned leases. Replaced gateway application work with existing Envoy configuration. Removed upload takeover, copy expiry leases and per-download leases: use one-shot upload state transitions, durable copy state/checkpoints and bounded stream duration with delayed object GC. No gateway/application code had been written.

## Evidence and next step

Plan format and 15-file documentation consistency checks passed. No application tests, processes, migrations or deployments ran. Implement the foundation/compatibility gate first; no implementation phase is complete. No external publication was requested or performed.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
