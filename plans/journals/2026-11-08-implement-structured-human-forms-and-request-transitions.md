---
title: Implement structured human forms and request transitions
date: 2026-11-08
summary: Add mixed-question forms and SQL decisions with exact approvers and lock-time deadlines.
---

# Implement structured human forms and request transitions

## What changed

Started phase13 after phase12's full 172-pass regression. Added typed single/multiple/text forms, exact question and option validation, blank choices with notes, and text-only answers. Added request resolution inputs and SQL open/lookup/decision/outcome methods. Optional timeout is normalized once; row-locked decisions use clock_timestamp after acquiring the lock. Accepted resource approval records the decision while leaving actual grant outcome pending. No fifth status, new table or fake grant exists.

## Evidence and review

Initial form tests passed 21 cases. The first form/request/store suite passed 45 tests; a stronger actual blocked-transaction deadline case brought it to 46. Scoped review found malformed ask payloads could be stored and then never answered. Admission now validates AskForm; old generic fixtures use a valid text question. Post-review focused regression passed 47 tests in 72.04s. Lint/format passed for 61 files. The deadline test was also rerun after splitting overlong SQL literals.

## Next steps

Authoritative continuation: plans/261108-0001-leta-agent-engine/reports/phase-13-execution.md. Implement the finite HumanRequestWorkflow and actual Local/regular Activities, canonical resource-owner resolution, grant/outcome delivery, agent tools and lifecycle settlement. The current SQL tests grant no real permissions. Phase12 native lifecycle gates remain open; phase15 APIs and phase16 publication remain later work. Goal stays active with no approval pending. No commit, push, deployment or paid inference occurred.

AgentWiki publish skipped.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
