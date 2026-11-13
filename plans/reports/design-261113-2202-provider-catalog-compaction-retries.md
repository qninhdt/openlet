# Provider catalogs, model references, cache-friendly compaction and retries

## Status

This follows the user's revised model configuration requirements. It supersedes
the catalog, model-selection, automatic OpenRouter price sourcing and retry
recommendations in the [previous proposal](design-261113-2119-model-configuration-costs.md).
Its earlier SDK/provider probes remain evidence.

Accepted directions: upstream Instructor from GitHub, provider-owned model
catalogs, multiple providers, one model reference including optional reasoning
effort, manually entered prices in dollars, and the three structured-output
modes. Cache-friendly compaction was already accepted in the Leta plan; the
current implementation does not satisfy it. The retry recommendation below is
for review. No application, dependency, schema, data or deployed configuration
was changed in this research.

## 1. Instructor

Keep OpenAI SDK 3.49.0 and use official Instructor source at an exact commit:

```text
instructor @ git+https://github.com/567-labs/instructor.git@aeb7e2558166caeec497e541bcfc6b4eaa2cf53b
```

The upstream pyproject identifies this source as 1.18.0 and permits jiter 0.18;
the published stable 1.17.0 still conflicts with the SDK's jiter floor. Isolated
resolution and live Vilao tools/text extraction, including validation feedback
through the Langfuse wrapper, passed with this commit. Pin the full commit in
project dependencies/lock, not a moving branch. No fork, constraint override or
OpenAI downgrade is needed. Full application/type/export checks still belong
to implementation; the commit is not a published stable release.

## 2. Catalog inside each provider

Keep the shared config's existing owning `models` section. Each provider owns
`models.llm`, `models.embedding` and `models.reranker`. The provider key supplies
the connection identity; the collection key supplies the model kind. Remove
entry fields `type`, `provider`, `pricing_model`, and the separate root catalog.

This is an illustrative fragment, not active runtime configuration. Context
figures are configured working budgets, not verified provider limits. Null price
values mean rates have not been supplied, not that inference is free. Prices
for LLM/embedding usage are dollars per million tokens; do not repeat currency
or the unit in every field name.

```yaml
models:
  providers:
    vilao:
      base_url: ${OPENAI_BASE_URL}
      api_key: ${OPENAI_API_KEY}
      timeout_seconds: 90
      models:
        llm:
          deepseek-v4.1-flash:
            context_window_tokens: 65536
            max_output_tokens: 8192
            reasoning_efforts: [none, low, high]
            structured_output: tools
            prices:
              input: null
              output: null
              cache_read: null
          gpt-6.1-sol:
            context_window_tokens: 65536
            max_output_tokens: 8192
            reasoning_efforts: [low]
            structured_output: tools
            prices:
              input: null
              output: null
              cache_read: null
        embedding:
          text-embedding-3-large:
            dimensions: 1536
            prices:
              input: null
        reranker: {}

    openrouter:
      base_url: https://openrouter.ai/api/v1
      api_key: ${OPENAI_OPENROUTER_API_KEY}
      timeout_seconds: 90
      models:
        llm:
          openai/gpt-6.1-sol:
            context_window_tokens: 65536
            max_output_tokens: 8192
            reasoning_efforts: [low]
            structured_output: json_schema
            prices:
              input: null
              output: null
              cache_read: null
        embedding: {}
        reranker: {}

  leta:
    default_model: vilao/deepseek-v4.1-flash:none
  enrichment:
    model: vilao/deepseek-v4.1-flash:none
    # Existing input/image limits stay here.
  embedding: vilao/text-embedding-3-large
  reranker: null
```

The second provider demonstrates simultaneous configuration, not authenticated
OpenRouter verification. Do not activate it without its key and compatible
models. Empty kind collections can be omitted. Do not add an unavailable Vilao
reranker merely to populate the config. A real reranker goes in its provider's
`models.reranker`, with its actual billing unit established when enabled.

Keep model-specific effort sets and context/output limits: they are consumed by
validation and budgeting. `reasoning_efforts` lists allowed suffixes, not a
second selection field. A non-reasoning model can omit that list. Cache-write
pricing is optional when an actual endpoint reports/bills it. Embedding has no
effort or output-mode fields. No per-role model aliases or duplicate model IDs.

The caller resolves only the required model kind. Indexing and query embedding
use the same shared embedding selection. Clients are reused per process and
selected provider. Resolve the known base-URL/key environment references before
constructing clients; do not interpolate arbitrary YAML. Do not add automatic
fallback or provider plugins.

## 3. One reference selects model and effort

```text
vilao/gpt-6.1-sol
vilao/gpt-6.1-sol:low
vilao/deepseek-v4.1-flash:none
openrouter/openai/gpt-6.1-sol:low
vilao/text-embedding-3-large
```

Split at the first slash for the application provider. The remaining model ID
can contain slashes. An optional terminal effort suffix must belong to the
selected LLM's effort list. First try an exact catalog model-key match, so real
provider names such as OpenRouter's `:free` variants are not mistaken for effort
settings. No need for an escaping format or parser framework.

An absent suffix means do not send `reasoning_effort`; the provider uses its
default. That is what the previous `reasoning_effort: null` meant. It did not
mean zero reasoning. `:none` explicitly sends `reasoning_effort="none"`, and is
valid only when offered for that model. Prefer an explicit suffix for configured
reasoning-model defaults when a particular effort is intended.

Store and accept one `model_id` string on agents, including provider and optional
suffix. Remove the standalone reasoning-effort API/SQL field when implementing
this intentional contract change. A missing/null agent model still means inherit
Leti → root → configured Leta default; it is not a reasoning-effort setting.
Resolve and validate the reference before calling the SDK, then send only the
provider's actual model name and optional effort to that endpoint. No alias
compatibility layer or data migration was executed.

## 4. Current API and target

Current source has:

- `POST /v1/workspaces/{workspace_id}/letas`: CreateLeta accepts optional
  `model_id` and a separate `reasoning_effort`.
- `PATCH /v1/workspaces/{workspace_id}/letas/{leta_id}/agents/{agent_id}`:
  changes model/effort for the root or a Leti. Runtime resolves updates at safe
  boundaries; it does not interrupt an in-flight tool/model call to switch.
- No model-listing route in the Leta API. Per-agent selection exists; listing
  for a selector is missing. No frontend selector was verified.

Propose an authenticated `GET /v1/models` returning the configured LLM selection
IDs, including supported effort variants. It reads the local shared catalog,
not provider `/models`, and never exposes credentials. A minimal response is:

```json
{
  "default_model": "vilao/deepseek-v4.1-flash:none",
  "data": [
    {"id": "vilao/gpt-6.1-sol"},
    {"id": "vilao/gpt-6.1-sol:low"},
    {"id": "openrouter/openai/gpt-6.1-sol:low"}
  ]
}
```

Creation/configuration then takes only `model_id`, for example
`{"model_id":"vilao/gpt-6.1-sol:low"}`. Leta configuration needs one
`default_model`, not its own catalog or compaction model. Embedding/reranker
entries are not offered as agent choices. The generated Envoy route currently
matches Leta workspace paths and HITL requests only; include the new model-list
path in `scripts/configure.py` when implementing the endpoint.

## 5. Cache-friendly compaction

The [owning design](../261111-2010-leta-rewrite/design.md#6-inbox-và-agent-execution)
already requires summary + bounded tail and prompt-cache reuse. Source review
found three implementation mismatches:

1. `runtime/agent.py:441` replaces the normal system prompt with the compaction
   instruction and flattens messages into one XML string. It also omits the
   normal tool definitions. This is not a cache-preserving request.
2. `Current time` is rebuilt into the system prompt inside the boundary loop at
   line 412. Its changing value prevents reuse of the full conversation prefix.
3. Native middleware is configured to trim summarization input. Trimming the
   earlier part of a prefix prevents reuse of that part of the parent's cache.

Claude Code's documented cache-safe fork retains model, system/context, tools
and history, appending the summarization instruction as a final user message.
It reserves context room for this instruction and the summary response. OpenAI
also documents exact-prefix matching and cache changes caused by replacing
context. A native middleware's default summarization request does not by itself
implement that layout.

Target integration:

1. Keep native SummarizationMiddleware trigger, cutoff, tool-pair-safe tail,
   rolling-summary replacement and native checkpoint persistence.
2. Its public custom `summarizer` callback receives the older message prefix.
   Set `trim_tokens_to_summarize=None` so it remains an original prefix. Build
   a request from the same system message, original message objects and identical
   ordered tool definitions, followed by the compaction instruction as a user
   message. A matching older prefix can reuse the parent's cache even though
   the retained recent tail is not part of the summarization input.
3. Use the executing agent's same model and reasoning effort. Keep cache-affecting
   settings identical. Do not change tool choice just to suppress tools without
   verifying that it preserves cache. The summary callback consumes text and
   does not dispatch model-proposed tools through the agent loop.
4. Keep dynamic time in input/context messages rather than rewriting the static
   system prefix on every boundary. Actual assignment/prompt/model changes may
   deliberately change the prefix; do not freeze configuration forever.
5. Budget the complete summary request: system, tools, source prefix, appended
   instruction and output reserve. Use existing bounded-input validation, not
   another summary/re-summary or protocol-repair loop.
6. Return the summary string to native middleware. It keeps summary + bounded
   tail and native saver state as already accepted. No second agent, workflow,
   model selection, summary store or custom checkpoint implementation.

The model still makes an inference request to produce the summary. Cache reuse
reduces its input work; it does not make summarization request-free. The first
normal request after replacing history cannot reuse the old replaced messages;
the stable system/tools prefix remains reusable and the new summary prefix can
be cached for later turns.

Required proof: compare actual main/summary wire prefixes, including tools and
parameters; test trigger/summary/tail/tool pairing/restart; then inspect real
provider cached-token usage. Earlier standalone cache probes do not prove the
current runtime meets this requirement. Current code is unchanged here.

## 6. Retry recommendation

Current Python LLM/enrichment/embedding clients explicitly set SDK retries to
zero; Go search retains the native two retries. Agent activity retries are
unlimited by count under its existing policy; EnrichAndIndex has at most three
activity attempts. There is no configured LangGraph model/node retry policy.
The custom summarizer bypasses middleware's internal summary-model retry.

Two scopes matter:

| Scope | Failure it addresses | Cost of retry |
|---|---|---|
| Native provider SDK | A short transient failure of one HTTP request | That request is tried again; completed sibling work stays in RAM |
| Temporal activity | Process loss, heartbeat timeout, or failures that escape local handling | Activity restarts; native agent checkpoint or ingest committed stage controls recovery |

Recommendation for review: enable the native SDK default of two retries for
Python LLM/embedding and retain it for Go embedding/rerank. Keep existing
Temporal activity recovery. Add no LangChain retry middleware, tool/RPC retry
loop, per-model retry settings, durable per-inference journal or fallback engine.
This changes the previous recommendation to keep all Python SDK retries at zero.
The reason is concrete: enrichment holds successful artifact metadata in RAM
until its stage commit, so immediately escalating one temporary model failure to
Temporal can repeat successful paid work across artifacts. The query API also
serves direct callers with no Temporal wrapper.

Removing SDK retries is functionally possible. An agent model failure would
reach its activity and resume through Temporal/native checkpoints; ingest would
retry from its committed processing stage; a direct search would return the
transient upstream failure to the caller. Removing Temporal recovery instead
would remove process-crash/heartbeat recovery and is not proposed.

Do not hide the multiplication: two SDK retries mean at most three HTTP attempts
per call. Ingest's three activity attempts can mean up to nine attempts of one
revisited request; an activity can contain many requests. Agent activity retries
have no fixed count cap. Failed requests with no returned usage can have unknown
charges. SDK retries do not automatically resume a stream after output has been
received; such failure can still reach activity recovery. Existing timeouts and
cancellation remain in force.

Keep Instructor's one validation correction separately: it changes an invalid
answer using feedback. It is not another transport retry loop. The tested
upstream version retries parsing/validation errors only; its wrapper still needs
cause-aware permanent/transient classification, including ingest ExceptionGroup.
Authentication, invalid model/effort/schema configuration and exhausted schema
correction must not trigger repeated whole-stage inference. Do not classify all
provider failures as permanent merely to remove activity retries.

Additional offline HTTP fault injection against official OpenAI 3.49.0 observed:

| Check | HTTP attempts / outcome |
|---|---|
| LLM, retries 0, one initial HTTP 500 | 1 / failure |
| LLM, retries 2, one initial HTTP 500 | 2 / success |
| Embedding, retries 2, one initial HTTP 500 | 2 / success |
| Persistent HTTP 500, retries 2 | 3 / failure |
| HTTP 401, retries 2 | 1 / failure |

This proves SDK behavior, not an application outage/load test. Small bounded
local retries plus durable recovery are useful here; arbitrarily stacking retry
layers is not. Avoid adding configuration knobs solely to expose SDK defaults.

## 7. Structured output and manual prices

The accepted three modes stay on each provider's LLM entry:

- `tools`: Instructor TOOLS, ordinary function arguments validated by Pydantic.
- `json_schema`: native response format, only for a compatible endpoint/model.
- `text`: Instructor MD_JSON, schema instructions in text plus validation.

The mode applies only when code supplies a response type. Ordinary agent text
and compaction do not become structured output. Keep Metadata and future response
types in code; do not duplicate them in YAML or infer mode by failed requests.

Prices are entered on each provider model. Remove OpenRouter price-ID mapping
and automatic price-fetch work from the previous proposal. Config is the source
for inferred rates; publish them to native Langfuse model definitions outside
inference. Convert million-token prices to per-token units for that API. Preserve
known provider-reported monetary cost precedence; missing usage/rates stay
unknown, not zero. Cache/reasoning subsets are not charged again on top of totals.

Multiple providers may return the same raw model name with different rates.
Record the selected provider/model reference in native observation metadata.
Langfuse supports native pricing-tier conditions on top-level metadata, so rates
can be selected by this identity rather than mispricing every identical raw name
at one provider's rate. This requires an export/pricing proof when implementing;
do not solve it by forking a callback or modifying the inference model name.
No billing ledger, custom cost service or per-token database writes.

## Sources and outstanding checks

- [Claude Code: prompt caching and cache-safe compaction](https://claude.dev/blog/lessons-from-building-claude-code-prompt-caching-is-everything/)
- [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- [LangChain built-in middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)
- [Instructor exact upstream source](https://github.com/567-labs/instructor/tree/aeb7e2558166caeec497e541bcfc6b4eaa2cf53b)
- [OpenAI SDK retry behavior](https://github.com/openai/openai-python/blob/v3.49.0/README.md#retries)
- [Temporal retry policies](https://docs.temporal.io/encyclopedia/retry-policies)
- [AWS: bounded retries and retry multiplication](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)
- [Langfuse costs, model definitions and metadata pricing tiers](https://langfuse.com/docs/observability/features/token-and-cost-tracking)

Reviewed current model clients, config, agent API/DTOs, native middleware and
Langfuse source. Remaining: actual prices/context limits, user acceptance of the
retry recommendation, implementation of the listing/reference contract and
cache-preserving compaction, full integration/type checks, and native Langfuse
Cloud pricing/export proof. No database/index/prompt/deployment changes ran.
