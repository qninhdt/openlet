---
title: "Simplify six reviewed backend and verification paths"
status: completed
branch: dev
---

# Outcome

Implement the six accepted review recommendations: skip authorization synchronization for name-only Workspace updates; batch Account relationship reconciliation; stream HTTP ZIP directly from its reader; replace search JSON roundtrips with typed HTTP DTOs; avoid recreating matching Qdrant indexes per document; eliminate repeated CI gates. Preserve public response shapes, authorization, projection recovery, atomic Workspace grants, streaming cancellation/failure behavior and existing unrelated work.

No database/schema changes, new dependencies, caches, product features, commit or deployment.

## Tasks and acceptance

- [x] Workspace: name-only update succeeds without Temporal; ownership transfer still synchronizes grants.
- [x] Account: canonical pages publish through bounded native batch writes; retries, multi-page rebuild and workflow continuation/failure remain tested. No per-account Activity in full reconciliation.
- [x] HTTP ZIP: reader streams directly, bounded reusable buffer, headers/deadline/flush/abort and cancellation preserved; no synthetic gRPC frames.
- [x] Search: typed flat DTO preserves omission/presence, decimal counters, timestamps, matching evidence and empty pages; no marshal/unmarshal roundtrip.
- [x] Qdrant: existing correct indexes cause no PUT; missing indexes are created and mismatched definitions corrected; real integration validates response shape.
- [x] CI: run contracts/build/check/unit/workflow/integration graph once per task; script tests once; preserve all checks and sequential integration resource bound.
- [x] Focused tests, full affected integration/API tests, fresh workflow replay, simplify/review, docs and journal.

## Validation and rollback

Use existing Go/Python tests and Playwright API/recovery stack. First add discriminating regressions at each changed boundary, then run native formatting/vet/Ruff, build/unit/workflow and affected real integration. Generate fresh histories because Account reconciliation changes activity history; dev has no production compatibility requirement. Restore only this task's scoped edits if needed; preserve the large existing uncommitted migration.

Execution evidence: `.local/simplify-*`. Final results are recorded here.

Focused checks passed: Go HTTP tests, Account workflow decisions, real Account
100+3 page writes/retries and Workspace HTTP name updates with no Temporal client;
16 Python indexing tests. A disposable pinned Qdrant verified initial creation,
GET-only repeated ensure, wrong-index repair and GET-only retry. CI dry-run has
28 unique runnable tasks, one contracts check and no contracts build alias.
Simplifier compared only this task's baseline and changed one stale documentation
sentence; no further code changes. Inline review traced changed callers, public
JSON, grant publication, streaming cleanup and CI task ownership; no unresolved
finding in this scope.

Final verification passed:

- Native CI-equivalent graph: all 28 build/check/unit/workflow/integration tasks
  in 3m31s. Actual logs confirm one contract check and one execution of each
  shared build. Native integration includes the race-enabled letfs suite.
- Script Ruff/format checks and all 21 script tests; all 3 real setup/recovery tests.
- All 34 API/recovery journeys in 5.9m, including ZIP disconnect cancellation,
  late S3-read abort, ownership transfer, membership revocation, worker restart,
  response-loss retries, parsing/search and coordinated restore.
- Native letfs integration-history replay and fresh API-history replay for all
  three Go workflow owners (3/3 tasks).
- `git diff --check`; all owned test containers/processes cleaned up.

No remote GitHub CI, live Clerk, paid model or external S3 provider was exercised.
No commit/push/deploy. Session history: [journal](../journals/2026-11-03-simplify-six-backend-paths.md).
