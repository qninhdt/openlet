# Harness optimization — implementation

## Scope completed

- Native `create_agent`, ToolNode validation, SummarizationMiddleware and PostgreSQL checkpoint/history ordering remain in place. No new agent loop, retry engine, recovery engine, locks or review service.
- Truncated model responses cannot dispatch tool calls. Tool errors retain name/status and actionable timeout feedback. Public image results retain a file reference without base64.
- `ChatModel` only corrects Unicode tool-argument serialization and provides context counting from the SDK message representation. Context uses the existing `LiteLLM.token_counter`, including replayed reasoning and tool schemas. No fabricated reasoning messages or new direct tokenizer dependency.
- Text reads use line offset/limit (default200, maximum2000). Complete lines fit a shared16KiB preview, estimated as4 UTF-8 bytes/token. Continuations point to the first unread line. Oversized lines are reported explicitly. History text uses actual lines rather than an escaped JSON text string.
- Shell uses the same total preview budget for stdout/stderr, preserves head/tail and exit code, and drains the command to completion. Overflow makes one VFS capture write, capped at1MiB with an explicit incomplete flag. Capture failure does not turn a completed command into a command failure. Removed `exec_python`; Python remains available through shell/Monty.
- `keep_tokens:8192` replaces `keep_fraction` everywhere in active runtime/example/test/local settings. No compatibility alias or zero-tail mutation of native middleware internals. Trigger remains0.8 and summary output budget remains2048. Native compaction preserves tool pairs and recent messages. The current model/effort/system/tools and original conversation prefix are used for the summary request; its instruction is appended.
- Prompt source lives in [apps/leta/prompts](../../apps/leta/prompts/README.md). Paragraphs are not hard-wrapped. Common covers efficient reads/scripts, supported shell/Python capabilities, messaging/waiting, access and concise reporting. Role prompts cover box delegation and handoff. The summary prompt uses goal/current state/pending/next steps headings and removes obsolete detail. No runtime prompt fallback or publisher service.
- Preserved the TODO for upstream issue33504; no speculative invalid-call workaround.

## Langfuse publication

Published and fetched back from Cloud with label `production`: common4, root4, Leti4, compaction3. Root/Leti pin common version4 using native composition. Compiled text matches Markdown sources. Existing model, reasoning effort and other prompt config values were preserved. WireMock fixtures contain the corresponding compiled text.

## Verification

- 26 Leta + Python SDK tests passed. Coverage includes real local HTTP capture for streaming/non-streaming, Unicode arguments, SDK-payload token counting, native tool validation, truncated mutation rejection, projection metadata, complete-line pagination, head/tail capture,1MiB ceiling, native summary prefix/tool pairs/tail and client reuse.
- Strict Pyright: zero errors/warnings for Leta source/tests and shared Python SDK source/tests. Ruff lint/format and targeted Prettier checks pass.
- No provider inference calls, journey resumes, database migrations, checkpoint rewrites or history deletion. Langfuse prompt publication is the external change in this phase. Worker images were not rebuilt/restarted and full Compose API E2E was not rerun.

## Offline benchmark

Temporary scripts and raw results: `/tmp/openlet-harness-research/implemented-benchmark.json`; no benchmark script added to source. Same LiteLLM estimator for old/new prompt text; assignment, box context and tool schemas are excluded from this text comparison.

| Prompt | Before estimate | After estimate | Reduction |
| --- | ---: | ---: | ---: |
| Root |3307|1861|43.7%|
| Leti |3122|1717|45.0%|
| Compaction |485|346|28.7%|

Local Mirage/RAMVFS, `seq 1 10000` with a redirected full file: median4.526ms before versus5.022ms after (six measured samples after warmup). Old preview lost the final line; new preview includes it and the capture equals the complete redirected file. Capture writes per overflowing command:0 before,1 after. This measures local correctness and overhead, not production RPC latency, model speed, billed savings or task quality.

## Remaining validation

Rebuild/restart the Leta services before testing the new runtime against updated local configuration. Run the approved small root–Leti task only when model execution is authorized; compare completion correctness, rereads, errors, compactions, token/cache usage and cost. No new claim that the five journeys now pass. Model behavior and provider compliance with requested output budgets still require a real run.

Follow-up: model names now remain unchanged throughout Leta, enrichment and embedding. Gateway routing is configured once in the Leta client and ingest connection parameters. Removed prefix concatenation/stripping and the redundant LangChain model metadata override. Local streaming/non-streaming HTTP and callback tests verify the canonical model name used by Langfuse; existing Cloud records are not rewritten.
