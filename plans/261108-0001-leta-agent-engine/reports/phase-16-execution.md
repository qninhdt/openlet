# Phase 16 execution: Redis replay and AG-UI streaming

## Runtime and SSE integration checkpoint (2026-11-09)

Phase16 is complete within its ownership. The root
SSE route is active and the manual public API now contains 24 Leta paths. A
process-level publisher injection point is available on AgentRunner and
agent_workers; final production process construction remains phase18.

- Authenticated SSE uses real root authorization, bounded PG snapshots, retained
  Redis replay, valid-cursor suffix resume, explicit resync/orphan limitations,
  25ms/16KiB post-Redis merging, periodic current-access checks, archive closure
  and explicit nested async-generator/XREAD cleanup. No SQL discovery polling.
- DynamicModel allocates its public message UUID before model callbacks. The same
  UUID is saved to the synchronous-durability LangGraph checkpoint and typed
  public history. Actual installed ChatOpenRouter `_agenerate/_astream` source
  confirms AsyncCallbackManager token callbacks carry ChatGenerationChunk.
  Only public chunk content is projected; summary calls and reasoning are absent.
- Typed inbox, assistant/note, tool start/result and compaction entries publish
  after their SQL save. Only send_message creates the owner chat item. Paused/
  yielded runs emit status rather than a false RUN_FINISHED; final completion and
  permanent runtime failure publish the appropriate terminal event.
- Existing six Workflows call one regular publish_resource_event Activity with
  `(leta_id, kind, resource_id)`. Canonical PG data establishes the actual agent
  identity. Local SQL Activities never write Redis. Publication has one bounded
  attempt and never owns/retries the business mutation. Root, box, request,
  schedule and inbox changes share the same root stream.
- New Workflow commands require fresh development fixtures. Agent/HITL histories
  were recaptured; schedule fixtures were recaptured by their native gates.
  No legacy version branches or old-data conversion were added.

Focused evidence so far:

- SSE bootstrap/reconnect/auth and reader cleanup: 3 passed; subsequently the
  native idle-root integration also passed with real Redis, PG and persistent
  Temporal. That journey receives a newly created box, child HITL expiry/input,
  root reminder, schedule changes and final root archive on one SSE connection.
  External Workspace/LetFS/graph boundaries use the existing explicit fakes.
- Existing runtime plus HTTP contract and SSE subset: **14 passed in33.95s**.
- Native runner/callback/history failure subset: **3 passed in8.17s**. Actual Redis
  failure does not prevent saver completion or repeat a completed tool/run.
- Agent/HITL Workflow gates: **14 passed in49.40s** after moving sparse HITL
  notification outside the SQL-transition lock and waiting for unfinished receive
  handlers before surfacing a terminal runner failure.
- Fresh Workflow histories plus public contract: **13 passed in2.08s**.
- Package lint/format passed97 files; generated contracts passed with the supported
  Go executable on PATH.

A schedule regression initially timed out intermittently. A deterministic new test
then delayed the real native creation across a one-shot's due time and reproduced
lost delivery (**failed before repair**). apply_temporal_schedule now rechecks the
due time while updating native state and after the update, consumes the one-shot
and attaches the existing stable occurrence Workflow. The regression plus
pause/delete source gate and streaming unit cases pass **11 tests in10.83s**.
No new scheduler, repair loop or delivery record was added.

Merge measurement for 100 compatible UTF-8 text deltas: **100 Redis events remain
100 writes; 100 SSE frames become1, framing bytes25,490→1,245**, public content
1,000 bytes unchanged, final cursor `1-99`. This is an available-batch measurement,
not a claimed production reduction for all arrival patterns; the live timer test
separately verifies flushing without a subsequent event.

One slow-send unit test initially expected TimeoutError; installed Starlette
converts the OSError subclass to ClientDisconnect under ASGI2.4. Its assertion
now checks that actual contract and verifies body cleanup. No product check was
weakened. Independent review found one additional issue: current authorization must also be
checked during long retained replay and slow output, not only the live-read loop.
Every yielded frame now passes the same rate-limited current-access check. The
focused regression passes; the reviewer reported no remaining confirmed findings.

Final regression: **280 passed, 4 failed, 5 skipped in439.37s**. All four failures
were the same startup test fixture lacking `channel.unary_unary` after the new
WorkspaceClient construction. The fixture now supplies that actual gRPC channel
method; all **7 lifespan tests pass**. No production fallback was added. The prior
messaging fixture failure was also repaired with explicit `events=None`; native
cleanup/messaging/SSE regression passes15 cases. Latest owner-send streaming
subset passes3 cases, including real committed send_message and exact tool-args
bytes. The full suite was not repeated after these test-only repairs.

The 5 skips require explicitly launched native Go fixtures. Phase17's new native
cleanup journey and phase18 production wiring are separate acceptance gates.
