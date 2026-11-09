---
title: Validate Leta system journeys and repair runtime integration boundaries
date: 2026-11-09
summary: "Real multi-agent approval, SSE, recovery and lifecycle acceptance with focused regression repairs."
---

# Validate Leta system journeys and repair runtime integration boundaries

## What happened

Continued the accepted Leta implementation through deployment and system acceptance. The actual Compose journey now covers immutable boxes, all human-form types, an unrelated reminder during HITL, resource-owner approval, inherited Mirage file access, explicit result routing, revocation and archive/workspace cleanup. One root SSE carries child events and replays the retained suffix after reconnect. Creator departure removes resource/home visibility while trusted workspace cleanup remains functional.

Acceptance found concrete adapter/fixture issues: typed public scope grants were missing, LetFS home identities require UUIDv7, the controlled provider omitted required SSE created metadata, and the Envoy isolation fixture lacked the Leta cluster. A separate real Temporal/SQL regression reproduced a create_box retry before its home identity was saved; the existing box ID now also identifies the Temporal Update.

## Evidence

The broad integration rerun passes all eight tasks, including 120 Leta integration cases and LetFS race detection. Full API acceptance passed 38 tests before the latest extra restore/deletion assertions. All four replay tasks pass with fresh Go histories and six-type Leta fixtures. The eleven lifecycle tests pass after the retry repair. A cold saver returns the exact compacted state after 10,000 synthetic older rows; measured loads were 2.51 ms and 3.06 ms with 10,029 rows.

## Remaining work

The extended populated-state restore and pending-source box deletion gates pass. Three additional real-service journeys cover warm-cache scope revocation during a child model call, cancelled/replacement forms with concurrent duplicate answers, and a paused agent recovering overdue reminder plus pending owner input after worker outage. All six Leta-specific cases pass; the full API/recovery run passes 42 tests in 7.3 minutes, with E2E typecheck passing. These additions found no further production defect. Test teardown removed the owned Compose containers.

Reconcile remaining phase checklists against evidence and complete the final scoped review. The goal remains active. No live model credentials, deployment, commit or unrelated container cleanup were performed.

## Further combined journeys

Added three more Leta E2E cases: mixed owner/schedule/box input during a held model call, disconnected/cross-box/nonrepresentative routing denial with a successful allowed round trip, and child question expiration plus reminder delivery during root pause/resume. The first two passed immediately. The third exposed a real HTTP 500: timed HITL requests persist internal timeout retry metadata in payload, while the public form/access schema rejects that field. A focused HTTP regression reproduced the same defect for approval as well as ask.

The existing shared human-request projection now excludes internal timeout metadata and retains the public expires_at deadline. Storage/retry/timer behavior is unchanged. The 13-test HTTP/HITL group passes in 71.10 seconds; all nine Leta Compose journeys pass in 2.2 minutes after rebuilding current sources. Ruff, E2E typecheck and whitespace checks pass. Test discovery reports 45 API/recovery cases; the full 45-case suite was not rerun for this bounded repair. Only remote inference is scripted. Evidence and exact commands are in the phase19 execution checkpoint; no new Workflow, Activity, table, dependency or infrastructure was added.

The preceding final lifecycle review also repaired root archive leaving box coordinators running: existing box IDs now drive Temporal cancellation after the agent stop barrier, without trashing retained files. The 16-case lifecycle/native-cleanup slice and independent scoped review passed. Phase19 records the difference between cancellation acknowledgement and handler drainage, and the real-server fixture used for absent/closed coordinators.

## Final integrated acceptance

The full API/recovery run now passes 45 tests in 8.5 minutes, including all nine Leta journeys and the new accepted-but-unsettled resource approval restore. The approval decision is committed while the actual Workspace service is stopped; after coordinated restore the grant completes with viewer rights and exactly one requester inbox outcome. Exact checkpoint checksums, public compaction text, paused continuation, retained box/home and future schedule also survive.

Final contracts/check/build/unit/Workflow/integration commands pass. The integration run reports 124 Leta passes and six tests requiring Go-owned fixtures. Those six cases were then rerun through the uncached native Go owners with race detection: LetFS 14.818s and Workspace 32.777s. The home-key-expiry extension passes separately in 6.179s. Fresh API histories pass all four owning replay tasks, including the 13-case six-type Leta fixture suite. Environment ownership/recovery tests pass all three cases in 121.210s. Source/restore fixture containers and test processes are gone; user/lab resources remain untouched.

The final [acceptance record](../261108-0001-leta-agent-engine/reports/acceptance.md) maps all phases to evidence and states fixture limits. Phase checklists and the plan are reconciled to completed backend work. No paid-provider smoke, frontend rendering, production deployment or months-long soak was performed. No commit or push was made.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
