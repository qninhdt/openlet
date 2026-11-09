# Leta backend acceptance

Date: 2026-11-09. Source: `dev` at `63df7db` **plus the current tracked and untracked implementation**. HEAD alone does not contain this implementation. No commit, push, deployment or production migration was performed.

This record reconciles the accepted backend plan. The individual execution checkpoints retain earlier failures and partial results; their open-gate statements describe those earlier increments. Current verification is recorded below. Frontend and live-provider behavior are outside deterministic backend acceptance.

## Final verification

The final monorepo command completed successfully with the timed-HITL projection and box-coordinator archive fixes present:

```sh
export PATH=/usr/local/go/bin:$PATH
export OPENLET_MIRAGE_INTEGRATION=1
export OPENLET_LETA_HITL_INTEGRATION=1
export OPENLET_HISTORY_DIR=$PWD/.local/leta-final-verification/final-histories
pnpm contracts:check &&
pnpm check &&
pnpm build &&
pnpm test &&
make test-workflow &&
pnpm exec turbo run test:integration --concurrency=1 --env-mode=loose
```

| Gate | Result and evidence boundary |
| --- | --- |
| Generated contracts | PASS; current public/native schemas and generated callers agree. |
| Check/build | PASS; 11 check tasks and 7 build tasks, plus script lint/format. |
| Unit/script tests | PASS; 9 unit tasks, including 157 Leta, 50 shared-Python and 101 ingest cases; 33 script tests. |
| Go Workflow tests | PASS; 3 owning tasks. |
| Integration | PASS; 8 tasks in 9m18.073s. Leta: 124 passed, 6 skipped, 170 deselected in 439.27s. The six skips require fixtures launched by Go owners; they are not six waived product gates. Several Go package results used Go's cache. |
| Uncached cross-language fixture gates | PASS; `go -C apps/letfs test -race -tags integration ./internal/transport/grpc -run '^TestIntegrationMirageLetFS$' -count=1` (14.818s), then the Workspace native reads/grants and deletion callback gates with `-race -count=1` (32.777s). Both fixture environment flags above were enabled. These launch the six Python cases omitted from standalone Python integration. Log: `native-final.log`. |
| Home idempotency-key expiry regression | PASS; uncached real PostgreSQL/SpiceDB `TestIntegrationLetaHomePersonalGrantAndCleanup`, 6.179s. Retry retains the exact reserved home identity after key expiry. This test-only extension followed the broad command. |
| Lifecycle repair | PASS; 16 lifecycle/native-cleanup cases in 54.92s, including cancellation of box coordinators on root archive and retained files. |
| Timed-HITL repair | PASS; 13 HTTP/HITL cases in 71.10s, after reproducing the response-validation defect before repair. |
| Leta-specific Compose journeys | PASS; 9 cases in 2.2m after rebuilding repaired sources. |
| Full API/recovery | PASS; `pnpm --dir e2e exec playwright test --project=api`: 45 passed in 8.5m, including all nine Leta cases and accepted-but-unsettled approval restore. |
| Fresh all-owner replay | PASS; `OPENLET_HISTORY_DIR=$PWD/.local/api-e2e/histories make test-replay`: all 4 tasks, including 13 Leta cases, in 4.562s. Go histories come from the completed API run; Leta also replays its owning captured six-type fixtures. |
| Environment ownership/recovery guards | PASS; `node --test --test-concurrency=1 e2e/setup/environment.test.ts e2e/setup/recovery.test.ts`: 3 passed in 121.210s, covering occupied-port refusal, SIGTERM cleanup and real isolated restore. Source and restore Compose containers were removed by teardown. Log: `ownership-recovery-final.log`. |

Local logs are under `.local/leta-final-verification/`: `final-gates.log`, `home-expiry.log`, `lifecycle-final.log`, `timed-hitl-before.log`, `timed-hitl-after.log`, `complex-additions-final.log`, `api-final.log`, `replay-final.log` and `replay-api-final.log`. They are local diagnostic artifacts, not files required at runtime. The final Leta replay subset passed all 13 cases covering all six Workflow types; the LetFS replay subset passed against fresh integration histories.

## Product and failure coverage

The nine journeys in [leta.spec.ts](../../../e2e/tests/api/leta.spec.ts) exercise real Account, Workspace, LetFS, Leta API/worker, PostgreSQL/checkpointer, Temporal, Redis, SpiceDB and gateway boundaries. Only remote inference is scripted.

1. Owner → Leta → representative → connected Leti; mixed-question form; unrelated root reminder; answer to the exact child; another human's resource approval; inherited Mirage read; explicit result routing; revoke and archive.
2. Creator departure removes API/home visibility; trusted workspace deletion still cleans the resource.
3. Box deletion cancels pending questions and schedules, retains committed inbox history and trashes the home only after runtime stop.
4. Warm personal-scope cache is revoked during a held child model call; the next read fails, a write remains forbidden and direct child-to-owner messaging is denied.
5. Cancelled question is replaced while root handles other work; invalid answers preserve pending state, duplicate answers deliver once and changed terminal answers are rejected.
6. Worker outage spans an absolute reminder and pending owner admission; retry plus resume retains exact input and nominal scheduled time without duplicate result delivery.
7. Owner message, root reminder and box result arrive during a held model call; the next boundary injects each once in the same run, after the outstanding tool result. Child input carries full content.
8. Disconnected, cross-box and nonrepresentative-parent routes fail without waking recipients; connected ID/name routes and representative box-ID result delivery succeed.
9. Child question expiration and child reminder queue during root pause; late answer cannot replace expiration, resume collects both inputs and routes the result through the box.

[The coordinated restore journey](../../../e2e/tests/api/backup-recovery.spec.ts) additionally captures exact saver-table checksums, compaction text, retained box/home/files, queued paused input, pending question and future native schedule. Its new approval extension stops the actual Workspace dependency before acceptance: the decision is saved with no fabricated success outcome. The restored worker must complete the real viewer grant and deliver one outcome inbox item.

These additions exposed the timed-HITL HTTP 500: internal `timeout_seconds` retry metadata was leaking into a public payload whose schema rejects it. The shared [projection](../../../apps/leta/src/leta/runtime/human.py) now excludes that internal field and retains public `expires_at`. No new schema, Workflow, Activity or infrastructure was needed.

## Phase reconciliation

| Phase | Acceptance evidence |
| --- | --- |
| 01: foundation | Pinned factory/saver/Mirage compatibility experiments, current locked build and Compose images; [checkpoint](phase-01-execution.md). |
| 02: human identity | Humans-only SQL/claims/native actors and removed managed-account routes; onboarding/membership/public/native regressions; [checkpoint](phase-02-execution.md). |
| 03: schema | App migrations, graph/name constraints, stable IDs and product models; real SQL integration and restore; [checkpoint](phase-03-execution.md). |
| 04: resource permission | Typed user/Leta scope discovery, exact default grants, resource-owner delegation, revoke/cleanup and receipt-expiry retry; [checkpoint](phase-04-execution.md). |
| 05: inline text reads | Native path/ID/range reads, exact text representation, metadata-only blob access and ordinary artifacts; [checkpoint](phase-05-execution.md). |
| 06: mutations | Atomic preconditions, append/copy/trash/provenance and actual native callers; [checkpoint](phase-06-execution.md). |
| 07: text search | Correct production unary queries, lifecycle/current-permission tests and default-planner GIN experiment with retained raw plans; [checkpoint](phase-07-execution.md). |
| 08: Mirage | Complete applicable hooks, Monty, mounts, image/artifact reads and Redis multi-session authorization/fingerprint tests through Go-owned native fixture; [checkpoint](phase-08-execution.md). |
| 09: inbox/Temporal | Post-commit worker SIGKILL, duplicate admission, bootstrap wakeup, busy/paused delivery, stop and history rotation; [checkpoint](phase-09-execution.md). |
| 10: runtime | Real async saver, checkpointed tool protocol/effects, recovery and safe-boundary steering; [checkpoint](phase-10-execution.md). |
| 11: history/compaction | Typed public input and summary cards, public-only summarizer, successive compactions, replay and cold-saver experiment; [checkpoint](phase-11-execution.md). |
| 12: messaging/lifecycle | Nine Compose journeys, native exact-home retry, stop-before-trash, initialization gates, name reuse and coordinator archive repair; [checkpoint](phase-12-execution.md). |
| 13: HITL | All form types, empty choices/notes, resource-owner authorization, deadline arbitration, completion-loss/SIGKILL and real grant/cleanup callbacks; [checkpoint](phase-13-execution.md). |
| 14: schedules | Native at/relative/interval/calendar, DST/forecast, consumed/rearmed one-shot, outage, source deletion and BUFFER_ONE tests; [checkpoint](phase-14-execution.md). |
| 15: owner APIs | Creator/current-membership authorization, canvas/models/history/forms/calendar DTOs and generated public contract; [checkpoint](phase-15-execution.md). |
| 16: streaming | Real Redis/SSE root/child multiplexing, retained suffix, trimmed/evicted cursor resync, bounded log and publication failure tests; [checkpoint](phase-16-execution.md). |
| 17: workspace cleanup | Actual Go/Python authenticated mutex-held cleanup; queued grant rejection, direct status reads, canonical all-state inventory, create/delete races, rebuild and native replay; [checkpoint](phase-17-execution.md). |
| 18: deployment/recovery | Required private Redis, migration readiness, owned Compose startup, seven-database coordinated restore, model catalog and authorization rebuild; [checkpoint](phase-18-execution.md). |
| 19: system acceptance | Combined journeys and final commands above; detailed failures/repairs remain in the [system checkpoint](phase-19-execution.md). |

## Scope and measured limits

- Exactly six Leta Workflow types remain: agent, root lifecycle, box lifecycle, human request, schedule changes and schedule delivery. SQL-only Local Activities and regular remote-effect Activities retain the accepted boundaries. No account per Leta/Leti, seventh Workflow, task engine, outbox, lease/fence or additional scheduler service was introduced.
- The mutex-held workspace test uses actual Workspace/Python Leta/SpiceDB/Temporal; its busy runtime and storage child are explicit boundary fixtures. Compose separately exercises production runner/Mirage/storage. Neither test alone is claimed to prove both layers.
- Root archive requests box-coordinator cancellation after stopping agents; cancellation acknowledgement is not a universal claim that every in-flight Update handler has drained. Existing SQL gates and runner stop barrier protect retained storage.
- Selective document GIN queries improved in the default-planner benchmark; common/short and high-entropy log queries can legitimately scan. High-entropy index space reached 154% of logical text, and index updates cost more. See phase07's retained plans and corpus/write measurements.
- A cold saver retained exact compaction/current state with 10,029 checkpoint rows: single loads were 2.51ms before and 3.06ms after synthetic older-row growth. This is not a months-long soak or a constant-cost promise.
- The compatible-delta experiment retained 100 Redis writes and reduced 100 SSE frames to one, framing bytes 25,490 → 1,245. Coalescing is after Redis and cannot merge tool/message boundaries.
- NOT RUN: paid/live-provider inference, frontend rendering, production rollout and months-long load/soak. Deterministic inference validates engine behavior, not model obedience or provider quality. No unrelated user/lab environment was reset.

## Disposition

All required backend acceptance gates are satisfied. The remaining phase checklists are reconciled against this evidence; historical failures are retained in their execution records. Final source/test/contract review found no additional unresolved defect in this increment. The preceding scoped independent lifecycle review accepted the coordinator repair; no new independent review was claimed for these documentation-only final reconciliations.

No background test process or source/restore Compose container remains from the final commands. Working-tree implementation remains uncommitted for user review. Deferred product features remain exactly those in the design contract.
