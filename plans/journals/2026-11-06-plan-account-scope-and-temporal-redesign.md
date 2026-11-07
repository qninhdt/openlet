---
title: Plan account scope and Temporal redesign
date: 2026-11-06
summary: Updated the five-phase plan with user-reviewed scope cuts; implementation remains pending.
---

# Plan account scope and Temporal redesign

## Result

Created and then updated [the implementation plan](../261106-1517-account-scope-temporal-redesign/plan.md), covering account/scope schema, action matrix, twelve workflow trees and connected cleanup. No implementation source changed.

## Superseded proposals

The initial draft introduced account disable, ownership-transfer reconciliation and a copy checkpoint/progress protocol. Its claim that every detail was already reviewed was inaccurate. After explicit review, the user removed disable/status/active gating, ownership transfer and all copy checkpoint/resume/progress machinery. Copy is one ordinary activity; partial failure keeps copied files and returns error without automatic whole-copy retry. Concurrent duplicate deletion relies on natural idempotency.

Earlier SDK API research and reviews remain historical evidence, not requirements to implement those rejected protocols. Preserve the reviewed membership status, roles, cleanup evidence and existing recovery tooling. No new journal, code, persistent database operation or change to user inline_text_only work is part of this update.

## Next

Implement only after a separate instruction. The updated plan owns execution; this journal records history.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
