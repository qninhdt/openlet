---
title: Complete durable compaction and wire agent messaging
date: 2026-11-08
summary: Finish typed history/compaction and implement box-aware messaging with transactional inbox reads.
---

# Complete durable compaction and wire agent messaging

## What changed

Completed Leta phase11's public transcript and durable compaction: typed digest/full inputs, exact persisted summary cards, public-only summarizer input, pinned inbox batches and recovery across saver/publication failures. A relative image path is resolved before awaiting reads, so concurrent shell cwd changes cannot alter the artifact reference.

Started phase12 messaging with the existing Temporal receive path. One send_message tool resolves allowed IDs/names, routes Leta to creator/box, permits edge-connected peers and returns representative results under the box identity while retaining the actual sender. Leti cannot message humans directly. Final model text remains a journal note.

Added Leta-only grouped list/read inbox tools. Source types remain generic; missing conversation keys derive from the source pair. The pinned LangChain subset schema drops Pydantic aliases, so list_inbox uses its supported JSON schema plus explicit Pydantic validation to preserve the public `from` argument.

## Failure found and fixed

A read_inbox crash test proved that marking a message read before saving its tool result could hide that input on retry. The runtime now commits the selected read markers with the existing saved tool-result row in one transaction. A failure before commit leaves the input unread; a failure after commit reuses the exact saved result. No receipt table, outbox, lease or new operation registry was introduced.

## Verification

Full Leta pytest suite: 152 passed, 3 skipped. The skips require cross-language Mirage/LetFS fixtures supplied by the owning Go integration, which this plain pytest invocation does not configure. The owning native integration passed in phase08 and was not rerun for this messaging change. Ruff lint/format, git diff whitespace checks and plan validation passed. A scoped independent messaging review is pending.

## Continue here

The authoritative checkpoint is plans/261108-0001-leta-agent-engine/reports/phase-12-execution.md. Phase11 is complete within its ownership. Phase12 still needs concrete LetaLifecycleWorkflow/BoxLifecycleWorkflow, home/resource provisioning, create/delete tools and cross-service lifecycle tests. HITL/schedule cleanup and Redis/AG-UI publication remain with their owning later phases and are required before release. Overall goal remains active; no approval is pending. No commit, deployment, production migration, backup or paid inference was performed.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
