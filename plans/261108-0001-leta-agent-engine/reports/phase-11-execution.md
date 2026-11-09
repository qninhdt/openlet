# Phase 11 execution checkpoint

Status: complete within phase ownership. Typed history and durable compaction passed focused acceptance and whole-service regression. No user approval is pending. Creator HTTP authorization and Redis/AG-UI publication remain with phases15/16; no live UI or provider acceptance is claimed.

## Implemented

- `leta/history.py` owns the discriminated public transcript contract: inbox input (digest/full), assistant, tool call/result, final note and compaction. Public projection excludes internal replay messages and provider-private blocks. Fixtures cover every kind and duplicate-event/reload identities.
- `runtime/history.py` journals checkpointed input, summary and assistant output using stable IDs. The existing tool wrapper records actual execution and saved results. `search_history` and line-paged `read_history` select only the current agent's transcript; SQL checks the root/agent namespace. Search omits internal saved replay bodies and image bytes.
- `OpenletSummary` uses the supported upstream `SummarizationMiddleware` async entry point and public summarizer callable. The complete selected older prefix reaches the summary model without default 4,000-token trimming. Public text and tool groups are projected before inference; private reasoning never reaches the summary prompt. The exact saved summary becomes a public compaction card after the saver barrier.
- Ordinary compaction starts at 80% of the input budget with approximately 20% recent retention, after system/tool/output overhead and safety margin. A pending batch that would overflow context forces earlier old-context compaction. That whole batch is pinned as pending_input in the summary checkpoint, then CollectInbox appends it with its cursor atomically. Later arrivals wait for the next boundary. A batch too large on its own fails without cursor advancement.
- Recovery includes public snapshot tasks as well as next/interrupts, covering a failed checkpoint whose completed node writes are recoverable. Summary/input publishers resume saved state rather than generating a new summary merely to rebuild UI history.
- New assistant IDs are assigned before persistence, so provider IDs reused after compaction cannot reuse an unrelated saved tool result. Tool-call IDs remain intact. Image read paths resolve before awaiting filesystem access, preventing concurrent cwd changes from altering the public file reference.

## Verification

- `PATH=/usr/local/go/bin:$PATH uv run --locked --package leta pytest apps/leta/tests/test_history.py apps/leta/tests/test_compaction_integration.py apps/leta/tests/test_runtime.py apps/leta/tests/test_runtime_graph.py -q --tb=short`: **25 passed** using owned PostgreSQL containers.
- The changed-cwd image regression first failed on the old code and passed after resolving the absolute path before the read: **1 passed**. It also verifies saved image-result reuse, no duplicate read and a public path without bytes/private provider fields.
- `pnpm --filter @openlet/leta check`: passed, 50 Python files formatted.
- Whole-service regression before the phase12 messaging increment: `PATH=/usr/local/go/bin:$PATH uv run --locked --package leta pytest apps/leta/tests -q --tb=short`: **144 passed, 3 skipped**. The later phase12 run also passes all history/compaction regressions. The three skips require the cross-language Mirage/LetFS fixtures supplied by their owning Go integration; this plain pytest invocation does not configure them.
- Existing independent runtime review confirmed the pinned graph's cached task-output recovery and identified the fixed path race. No full new independent audit was claimed.
- Initial integration setup could not find Go in the shell PATH. Re-running with the installed `/usr/local/go/bin` resolved the fixture setup; no application workaround or skipped integration check was introduced.

## Next work and remaining gates

1. Phase11 implementation and its owned verification are complete.
2. Continue phase12 messaging and resource/box lifecycle with the existing Temporal AgentWorkflow and canonical SQL gates.
3. Phase15 implements creator/membership-gated history APIs. An addressed resource approver receives no transcript access.
4. Phase16 binds the committed DTOs to Redis/AG-UI, including post-checkpoint result publication and reconnect behavior. Redis publication failure is not a reason to rerun model/tools. This checkpoint does not mark that integration done.

No commit, push, deployment, production migration or paid inference was performed.
