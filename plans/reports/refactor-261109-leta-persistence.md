# Leta persistence refactor and measurement

Status: complete for accepted phase-1 scope against baseline `043f4e5`. Commit and push requested after verification; no deployment. No API/schema/migration/dependency change.

## Changes

- Rejected schedule validation rolls back the reservation transaction. The validator receives the original request timestamp; completed receipts skip validation so later schedule edits do not break retries.
- `get_box` reads metadata; `get_box_graph` owns graph/details. All graph consumers migrated, and lifecycle activities reuse their graph read.
- Pause reads only active agent IDs; deletion/archive retain their full snapshots.
- Self-target schedule create/update performs admission once; distinct target and teardown guards remain.
- Removed `list_roots`, `list_conversation`, and write-on-read options. Tests now use active owner reads and atomic tool-result/read-marker publication.
- Merged transaction-local timeout setup and batched graph child/edge inserts without returning unused rows. Failed batch insertion is checked for complete rollback.
- Moved `fault` to domain with all consumers migrated; separated schedule validation from Temporal compilation. No mechanical Store extraction.

## Benchmark

Verdict: serial local Store operations and the measured ASGI request are faster in this run. This is not a production load or model-throughput claim.

Same process, owned PostgreSQL, migrations, pool (min 1/max 8, autocommit, prepare_threshold=0), installed dependencies and fixtures for both implementations. The baseline Store is the verbatim pre-edit copy from `043f4e5`; other imported modules are shared. Two warm-up rounds, then seven measured rounds, alternating A/B and B/A order. Each round uses 12 awaited operations per side (6 for graph creation); table reports median of round medians and their min–max range in milliseconds. Fixture creation and validation reads are outside the timed operation. No other audit test suite ran concurrently with the benchmark.

Graphs contain 2/16/64 agents with 32 KiB repetitive, compressible prompts and V−1 edges. Metadata scenarios share one root with those three graphs; pause visits that root plus 82 active children. Graph creation uses a fresh active root per sample. Schedule creation uses unique IDs and validates stored identity/spec. Every graph is read back to verify child identities, exact prompts and edge count; requests require HTTP 200 and exact empty-page output. All measured operations completed without errors.

| Operation | Before median [range] ms | After median [range] ms |
| --- | --- | --- |
| `get-agent-fixed-overhead` | 0.303 [0.290–0.319] | 0.254 [0.245–0.263] |
| `box-metadata-2` | 0.554 [0.498–0.560] | 0.252 [0.238–0.333] |
| `create-graph-2` | 2.555 [2.500–2.642] | 2.331 [2.280–2.450] |
| `box-metadata-16` | 0.928 [0.891–1.335] | 0.242 [0.234–0.343] |
| `create-graph-16` | 9.553 [9.275–9.874] | 6.035 [5.886–6.278] |
| `box-metadata-64` | 2.562 [2.448–3.303] | 0.245 [0.240–0.328] |
| `create-graph-64` | 33.462 [33.062–34.929] | 18.166 [17.843–18.415] |
| `pause-root-82-children` | 2.561 [2.534–2.644] | 1.713 [1.709–1.773] |
| `create-self-schedule` | 1.708 [1.665–2.029] | 1.519 [1.477–1.745] |
| `http-list-box-schedules-64` | 7.480 [6.676–7.643] | 2.085 [1.868–2.141] |

The HTTP scenario is the real FastAPI handler for listing schedules filtered by a 64-agent box, using real SQL and a fake external authorization boundary. It includes local ASGI/auth adapter/routing/serialization overhead; it excludes network/TLS, real SpiceDB RPC, Envoy, providers and production concurrency. It is a different scenario from direct graph creation, not a whole-system speedup attribution.

Query-count regressions independently protect metadata at 2 cursor executes (one timeout setup + one SELECT), pause at 4 (setup + root lock + update + active-agent SELECT), and one root admission gate for root/child self-target create and update. Baseline probes had 5 metadata executes, 9 pause executes and two self-target root gates. Cursor counts exclude BEGIN/COMMIT and protocol bookkeeping. Batching still writes every row; it is not O(1) database work.

Raw round medians and harness: ignored `.local/leta-persistence-refactor/benchmark.json`, `test-benchmark.py`, `store-before.py`, `benchmark.log`. Reproduce using the recorded baseline revision and the current Store with the existing owned SQL fixture:

```sh
PYTHONPATH=apps/leta/tests uv run --locked --package leta pytest -c apps/leta/pyproject.toml -p conftest .local/leta-persistence-refactor/test-benchmark.py -q -s
```

A separate instrumented metadata pass, excluded from benchmark timings, confirmed that graph SELECT/execute/fetchall stages consumed 93.6% of the baseline's recorded cursor-stage time. Fifty baseline calls fetched 100 MiB of prompt text; the metadata path fetched none after cleanup. This identifies graph retrieval/materialization as the removed cost in this fixture; cursor-stage shares exclude Python/transaction overhead and are not whole-request CPU shares. Profile artifacts are `profile.json` and `profile.log`; no load-generator throughput or production capacity claim is made.

## Verification

The initial regression failed on the original code with two retained reservations. A 69-test focused run passed before adding the final query-count/batch-rollback/completed-patch regressions. An intermediate batch-insert implementation assumed model override fields on LetiSpec; focused checks caught it and it was corrected before the accepted benchmark and wider gates. No assertion was weakened to hide that failure.

| Gate | Result |
| --- | --- |
| Leta Ruff lint/format | PASS |
| Leta unit | 157 passed |
| Leta integration | 132 passed, 6 intentional native-owner/opt-in fixture skips |
| Leta replay | 13 passed |
| Leta wheel/source build | PASS |
| API/coordinated recovery, current sources | 45/45 passed, 8.2 min; includes exact bytes, checkpoint/workflow recovery, pause/reminders, box deletion and warm-cache revocation |
| Fresh API histories replay | 4/4 tasks passed: Go Account/Workspace/LetFS consume fresh API histories; Leta reruns its 13 existing replay fixtures |
| Final focused pure-read regression after removing redundant marker setup | 1 passed |
| Separate metadata profile with exact work/byte assertions | 1 passed |
| Final diff/links/Python 3.14 syntax | PASS |

The final lifecycle adjustment preserves status from the mutation result and reuses the archived graph; it is included in the freshly built API/recovery run. Command logs and exit codes are retained in ignored `.local/leta-persistence-refactor/verification.json` and per-command logs. The baseline's full monorepo 32-task graph was not repeated for unchanged Go/ingest sources; the relevant Leta gates and complete cross-service API/recovery suite were rerun. SDK deprecation warnings remain non-failing.

Production Python: 162 added / 168 removed, net **−6** lines; Store itself is **−34**. Tests: 220 added / 22 removed, net **+198**. These are physical diff lines, not complexity scores. Test growth covers rejected-input retention, completed patch retry, active owner pagination, batch rollback and SQL-work bounds. The redundant marker setup was removed; the existing stronger atomic/recovery tests remain.

Review traced metadata versus graph consumers, reservation validation/rollback and retry, root-first schedule admission, graph transaction rollback, atomic tool-result/read-marker publication and lifecycle snapshot/replay. No unresolved review finding. Runner/Playwright processes exited and the owned API test stack was removed.

## Limits

Existing pending reservations are not bulk-deleted: unknown Temporal outcomes must retain their reconciliation identity. No production load/soak, live Clerk/storage-provider smoke, deployment or phases 2–7 audit. Compatibility normalization, patch serializers and recovery/replay coverage remain in place.
