---
title: Implement Leta and box lifecycle coordinators
date: 2026-11-08
summary: Wire durable lifecycle Activities and canvas tools; fix recovery across mutable names and native cleanup identity.
---

# Implement Leta and box lifecycle coordinators

## What changed

Continued the accepted Leta plan at phase12. Added the two planned lifecycle coordinators, short SQL Local Activities and regular native provisioning/access/start/control/trash Activities. Creation saves the immutable graph before home/start effects; agents remain idle until an explicit message. Root configuration/pause/resume preserve working context. Ordinary archive retains home/history and resource tuples.

Added root-only create/list/get/delete box tools, with stable IDs from persisted tool calls and derived home slugs. The actual LangGraph saver/tool pipeline now exercises creation, inspection and deletion.

## Defects found

Real Temporal JSON round trips exposed omitted configuration patch fields becoming explicit nulls. The supported Pydantic serializer now retains only explicitly supplied fields.

Scoped review found committed message replay could fail after a root rename or box archive. Replay now validates and reuses the committed message before reconstructing mutable admission metadata.

Review also found ordinary Workspace cleanup lacked its delegated creator Actor, and delete-by-name recovery could target a replacement box after name reuse. The latter regression failed by actually archiving the replacement before the fix. Resolved targets now stay in the existing public tool-call row; no new ledger, receipt, lease, outbox or command stage was introduced. Ordinary archive now supplies its recorded creator identity.

## Verification and limits

The lifecycle suite passes 10 tests using real owned PostgreSQL/Temporal and the async saver, with explicit external Workspace/LetFS/SpiceDB fakes. It covers identity checks, stop-before-trash, paused children, late activation rejection, coordinator rotation/replay, initialization rejection and checkpointed tools including the reproduced deletion recovery defect.

A full suite before the final review fixes passed 171 tests, with three native Mirage fixture skips. The full post-fix regression passed 172 tests with the same three fixture-dependent skips in 272.10 seconds; exact evidence is in the phase12 execution checkpoint. Lint/format, whitespace and plan/link validation passed.

## Continue here

Read plans/261108-0001-leta-agent-engine/reports/phase-12-execution.md. Native lifecycle execution is still required; the explicit external fakes do not establish cross-service compatibility. HITL/scheduler settlement, sparse publication, trusted workspace teardown and production wiring remain their owning later phases. The overall goal stays active, with no approval pending. No commit, push, deployment or paid inference occurred.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.

AgentWiki publish skipped.
