# Model configuration, structured output and API costs

## Status and scope

Revised proposal for review after the user rejected model aliases and a separate
compaction model. One catalog contains real provider model IDs for LLMs,
embeddings and rerankers. Every LLM selection includes its reasoning effort.
OpenAI-compatible clients, `OPENAI_*` names, bare Vilao request names and
Instructor-based extraction remain the accepted direction. The dependency
choice below remains open; do not treat an upstream development commit as an
approved production dependency.

No application code, dependencies, database, deployment or Langfuse model
definitions were changed. The uncommitted credential-example edit was preserved.
Previous [live provider research](research-261113-2054-vilao-provider.md) remains
evidence, with its embedding restriction superseded below. This revision
supersedes the earlier `fast`/`reasoning` aliases, independent compaction choice,
provider-wide retry knob and recommendation to downgrade to OpenAI 3.3.0.

## Verified follow-up

### Grafana

After the user corrected the policy, empty ingestion requests succeeded:
Prometheus remote write returned HTTP 200, Loki push HTTP 204, and OTLP traces
HTTP 200. Traces use the regional OTLP gateway, not the previously tested direct
Tempo HTTP paths. The correct base endpoint is
`https://otlp-gateway-prod-ap-southeast-1.grafana.net/otlp`, with stack ID
`1867013` as the Basic username. The collector appends `/v1/traces`.

These checks establish authentication and routing, not export of actual
application spans, dashboard rendering or alert delivery. No policy was edited
by this research. See the [readiness record](infra-261113-2008-cloud-cli-readiness.md).

### Embedding compatibility

Vilao now lists `text-embedding-3-large`. Live requests used synthetic strings:

| Client/check | Result |
|---|---|
| Python OpenAI 3.49.0, single string | HTTP 200, one 1,536-dimensional float vector |
| Python, two-string batch | HTTP 200, two vectors, indices 0/1 |
| Explicit `dimensions=256` | HTTP 200, exactly 256 dimensions |
| Python SDK defaults | Wire base64, SDK decoded to 3,072 float dimensions |
| Explicit base64/1,536 dimensions | Base64 preserved as requested; decoded length agrees |
| Go openai-go/v3 3.98.0, existing LetFS query shape | Passed, one 1,536-dimensional finite vector and usage |
| Same input, batch versus single | Cosine similarity 1.0 within Vilao |
| Response envelope | `object`, `data`, `model`, `usage` |
| Embedding item | `object`, `embedding`, `index` |
| Usage | `prompt_tokens`, `total_tokens` |

Both official OpenAI and OpenRouter embedding documentation support the same
text-only subset. Keep explicit `encoding_format="float"` and dimensions in
both clients to avoid depending on different SDK defaults. The Go query client
currently works without an explicit encoding field, but making it explicit is
the consistent contract. Do not add a Vilao adapter or base64 decoder.

Provider/model substitutions:

| Provider | Base URL | Request model |
|---|---|---|
| Vilao | `https://api.vilao.ai/v1` | `text-embedding-3-large` |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/text-embedding-3-large` |
| OpenAI | `https://api.openai.com/v1` | `text-embedding-3-large` |

The OpenRouter embedding catalog is a separate public endpoint:
`GET /api/v1/embeddings/models`. The configured embedding model was found there;
it is absent from the chat-model catalog. OpenAI/OpenRouter authenticated live
requests were not run because corresponding credentials are not available.
API compatibility does not prove cross-provider vector identity. Switching an
embedding model/dimensions requires reindexing; moving providers for the same
declared model/dimensions requires a representative vector/retrieval comparison
before retaining an existing index. Query and document embeddings must always
resolve the same catalog entry.

### OpenAI 3.3.0 versus 3.49.0

OpenAI 3.3.0 passed isolated text/tool/stream/embedding checks with Instructor
1.17.0, LangChain 1.5.0, langchain-openai 1.7.4 and Langfuse 5.2.0. It retains the
basic APIs used by Openlet. This does not make the downgrade equivalent:

| Later version | Change relevant to assessing a downgrade |
|---|---|
| 3.3.1 | Dependency updates carrying published security fixes, including jiter/PyO3 |
| 3.4.0 | Incremental SSE decoding without an event-size limit; shared embedding decoding |
| 3.12.0 | Standard `AsyncStream.aclose()` cleanup |
| 3.14.0 | Normalized errors while reading streams |
| 3.19.0 / 3.20.0 | Request-replay eligibility and TLS transport retry fixes |
| 3.30.0 | Restored async HTTP/1.1 connection reuse |
| 3.9.0 / 3.36.0 / 3.40.0 / 3.45.0 | Additional cache diagnostics, usage fields and cache controls |

Some later additions concern Responses, Realtime or other APIs Openlet does not
currently use. Do not claim those are required. Streaming, connections and
dependency fixes are sufficient reason to withdraw the earlier assertion that
3.3.0 is a downgrade without relevant losses. Existing cached/reasoning usage
is not entirely absent from 3.3.0; distinguish newer fields from those already
present and tested.

### Instructor dependency choice remains open

The published Instructor 1.17.0 requires `jiter>=0.6.1,<0.15`; OpenAI 3.49.0
requires `jiter>=0.16,<1`. OpenAI 3.3.1 already requires the newer floor, so using
3.3.1 instead of 3.3.0 does not resolve that conflict. Downgrading Instructor
among the inspected older releases does not resolve it either.

Official Instructor main has widened the bound to `jiter<0.19`. An isolated
environment pinned to commit
`aeb7e2558166caeec497e541bcfc6b4eaa2cf53b` resolved:

| Dependency | Version |
|---|---|
| Instructor | 1.18.0 in upstream source; not a published stable release |
| OpenAI | 3.49.0 |
| jiter | 0.18.0 |
| LangChain / langchain-openai / Langfuse | 1.5.0 / 1.7.4 / 5.2.0 |

Live Vilao calls through Instructor plus the official Langfuse OpenAI wrapper
passed both ordinary tool-based extraction and text JSON with a deliberate
validation failure followed by correction. Cloud tracing was disabled because
Langfuse project keys are unavailable; this proves wrapper compatibility, not
Cloud ingestion or all application integration paths.

Recommendation: retain OpenAI 3.49.0. If implementation must proceed before a
compatible Instructor release, propose pinning that exact official commit,
subject to the user's acceptance of an unreleased dependency. Otherwise retain
the SDK and wait for a compatible stable Instructor release. Do not silently
downgrade, pin moving `main`, override incompatible constraints or fork the SDK.

## Configuration proposal

Keep the existing shared YAML. Move model definitions out of Leta's private
catalog into one `models.catalog`; other sections select entries rather than
redefine them. Provider credentials/URLs can reference `OPENAI_*`; explicitly
resolve the configured fields rather than pass literal `${...}` strings to
clients or interpolate arbitrary YAML text.

```yaml
models:
  providers:
    vilao:
      base_url: ${OPENAI_BASE_URL}
      api_key: ${OPENAI_API_KEY}
      timeout_seconds: 90

  catalog:
    deepseek-v4.1-flash:
      type: llm
      provider: vilao
      pricing_model: deepseek/deepseek-v4.1-flash
      context_window_tokens: 65536
      max_output_tokens: 8192
      structured_output: tools
      reasoning_efforts: [null, none, low, high]

    gpt-6.1-sol:
      type: llm
      provider: vilao
      pricing_model: openai/gpt-6.1-sol
      context_window_tokens: 65536
      max_output_tokens: 8192
      structured_output: tools
      reasoning_efforts: [null, low]

    text-embedding-3-large:
      type: embedding
      provider: vilao
      pricing_model: openai/text-embedding-3-large
      dimensions: 1536

  leta:
    default:
      model_id: deepseek-v4.1-flash
      reasoning_effort: none

  enrichment:
    model_id: deepseek-v4.1-flash
    reasoning_effort: none
    max_input_characters: 24000
    max_image_pixels: 25000000
    image_max_side: 1600
    image_jpeg_quality: 85

  embedding:
    model_id: text-embedding-3-large

  reranking: null
```

The context settings are illustrative conservative working budgets, not verified
Vilao capacity. Parsing/chunking/concurrency remain with ingest. Reasoning sets
contain the exercised choices and the explicit provider-default choice; HTTP
acceptance alone does not establish the provider honors each effort precisely.
Do not infer actual Vilao context capacity from OpenRouter metadata.

Field responsibilities:

- Provider: connection details. Keep the current provider name `vilao`; a second
  entry is needed only for an endpoint actually used. Retry ownership follows
  execution context, not one provider-wide setting.
- Catalog key: actual provider request model ID, also used by SQL/API `model_id`.
  No `fast`/`reasoning` role aliases or duplicate request-name field. Adding a
  model adds one entry; it does not add a new config section, class or agent
  column. Changing to OpenRouter can change its key to the canonical ID.
- `type`: `llm`, `embedding` or `reranker`, so a choice can reject the wrong kind.
  Each kind has only its relevant fields; embedding does not carry reasoning or
  structured-output settings. A configured reranker belongs in the same catalog.
- `pricing_model`: exact OpenRouter catalog ID, independent of request names.
  Do not prepend a guessed vendor or infer identity from an alias.
- `structured_output`: strategy only for calls that supply a response schema.
  It does not impose structured answers on agent tool loops or compaction.
- Context/output settings: retain the budget information consumed by admission
  and summarization. The output cap is defined once per LLM entry rather than
  repeated with the same value at every selection.
- `reasoning_efforts`: choices permitted for this particular entry, checked on
  model selection. A non-reasoning model can allow only `[null]`. `null` omits
  the parameter; `none` explicitly requests no reasoning. They are not synonyms.
- `dimensions`: used by both document and query embedding and checked against
  the index.
- Leta default/enrichment: each selects the pair `model_id` and
  `reasoning_effort`. Existing enrichment input/image limits stay with their
  owning operation; they are not model capabilities.

Per-agent creation/configuration must also carry the model/effort pair when
setting either field. A PATCH that changes `model_id` must explicitly supply
`reasoning_effort`; an effort change sends the same model ID with the new effort.
Do not carry the previous model's effort onto a new model. Both fields can be
omitted for an unrelated PATCH. Explicitly clearing the pair preserves existing
Leti → root → default inheritance, as one pair. No new SQL model-alias column or
migration to role aliases is proposed.

Current compaction is an extra inference request: `summarize()` calls
`chat.ainvoke()` in `apps/leta/src/leta/runtime/agent.py:441`. It uses the same
already constructed chat model and reasoning effort as the agent. Preserve that
behavior. There is no independent compaction model choice, provider client or
task assignment in config. A `compaction` observation label still distinguishes
its actual cost from the agent's ordinary calls.

A new structured operation supplies its Pydantic response type in code and
selects a catalog LLM plus effort. It reuses that entry's `structured_output`.
Do not add per-task mode overrides, schema files, prompts, tool definitions or
arbitrary adapter classes to YAML.

Mode mapping:

| Config value | Native implementation | Request |
|---|---|---|
| `tools` | Instructor TOOLS | Ordinary function/tool calling, no strict response schema |
| `json_schema` | Instructor JSON_SCHEMA | Native `response_format=json_schema` |
| `text` | Instructor MD_JSON | JSON requested as ordinary text, local Pydantic validation |

Keep clients reusable per process/provider. A small model/task lookup and a
typed structured-call function are enough; no provider plugin framework, custom
OpenAI client subclass, automatic fallback, JSON repair or per-model classes.
Use OpenAI-style `reasoning_effort` consistently in both call sites, rather than
the ingest OpenRouter-specific `extra_body.reasoning` shape. OpenRouter documents
`reasoning_effort` as shorthand for `reasoning.effort`; authenticated OpenRouter
verification is still outstanding.

Concrete enrichment example: select `deepseek-v4.1-flash` with effort `none`,
pass existing Pydantic `Metadata`, and resolve its `structured_output: tools`.
Instructor sends an ordinary tool definition whose arguments match Metadata,
then parses and validates the returned arguments. It does not depend on Vilao
honoring `response_format`. `text` instead puts schema instructions into the
messages and parses the returned text. `json_schema` asks the endpoint to enforce
the response format and is unsuitable for the currently tested Vilao endpoint.
None of these settings changes ordinary agent replies or text compaction into
structured output when the caller has not requested a response type.

## Retry audit and proposal

| Current path | In-process retries | Outer recovery |
|---|---|---|
| Leta/Leti model | `ChatOpenAI(max_retries=0)` | Agent Temporal activity policy |
| Custom compaction callback | Same client; callback called once | Same activity policy |
| Ingest description/embedding | `AsyncOpenAI(max_retries=0)` | EnrichAndIndex, maximum 3 activity attempts |
| Go query embedding/rerank | Native Go SDK default: 2 retries, up to 3 HTTP attempts | A failed search can propagate to an agent activity; direct API callers have no Temporal wrapper |
| Instructor | Not integrated in application yet | Would add validation correction, not a second transport retry policy |

The agent retry policy does not set `maximum_attempts`; it retains Temporal's
default unlimited attempts, subject to activity timeouts and its nonretryable
error types. Do not describe the complete agent request count as bounded by
three. There is no configured graph `with_retry` or per-node retry policy.

Installed SummarizationMiddleware creates an internal model retry runnable by
default, but the application's custom `summarizer=summarize` path bypasses it.
An offline failing-callback probe observed exactly one invocation. Do not report
three internal compaction attempts for the current code.

Recommendations:

1. Keep Python model SDK retries at zero and keep existing Temporal recovery.
   Withdraw the earlier new provider-wide `max_retries: 1` setting.
2. Keep Go's native two transport retries for synchronous query embedding and
   optional reranking. They retry a short request locally, including for human
   search callers. Explicitly acknowledge that when called by an agent this can
   coexist with later activity recovery; it is not a claim of zero nested retry.
   Add no Go retry loop or RPC retry configuration. Setting Go to zero would
   remove that overlap but make direct searches return transient errors without
   local retry; it is not automatically a better policy.
3. Use native Instructor `max_retries=1`: at most one correction after parsing
   or validation failure. The inspected upstream version already filters these
   errors; no new Tenacity controller is needed.
4. Classify failures at the existing activity boundary. Exhausted schema
   correction and permanent auth/request/config failures must be nonretryable;
   transient transport/rate-limit/provider failures remain retryable. Instructor
   wraps both categories in `InstructorRetryException`, and ingest TaskGroup
   can wrap them in an ExceptionGroup. Examine the native causes/leaf exceptions
   rather than mark every wrapper retryable or nonretryable. Cancellation stays
   cancellation. Do not broaden this into a generic exception framework.

An isolated HTTP fault-injection check against the pinned upstream Instructor
with OpenAI 3.49.0 and SDK retries disabled observed:

| Response sequence | HTTP attempts |
|---|---|
| Invalid arguments, then valid arguments | 2; validated result returned |
| Invalid arguments twice | 2; wrapper cause is ValidationError |
| HTTP 500 | 1; wrapper cause is InternalServerError |
| HTTP 401 | 1; wrapper cause is AuthenticationError |

This verifies native correction behavior and error wrapping, not Temporal
classification already implemented. Activity recovery can repeat paid inference:
enrichment holds per-artifact metadata in RAM until CommitEnrichment, and a
retry before that commit can repeat successful sibling calls. Indexing can also
repeat successful embedding batches. Existing stage/checkpoint boundaries avoid
some work, but do not provide exactly-once provider billing. Do not add a
per-request persistence mechanism in this configuration change.

## Optional reranking

`models.reranking: null` disables reranking. Enabling it selects a real catalog
entry with `type: reranker`, using `reranking: {model_id: <actual-model-id>}`.
That entry selects an actually working rerank provider endpoint; Vilao currently
has none, so do not populate a fake active entry. Do not add both `enabled` and
a nullable model field. Reranking does not have a reasoning effort.

Off:

1. Embed the query with the same embedding entry used at indexing time.
2. Retrieve dense and BM25 candidates, combine with existing Qdrant RRF.
3. Keep existing SQL authorization/source-version/live-ancestry filtering.
4. Preserve fused ordering and return the first `top_k` eligible hits.

On: insert the existing rerank step after SQL filtering and before final top-k.
Candidate overfetch is still useful when off because filtering can remove hits.
Expose `rerank_enabled` in retrieval observation metadata. Scores in the disabled
path remain RRF scores; do not pretend they are reranker relevance scores.

RAG works without reranking. Optional reranking changes ranking quality, latency
and API cost, not whether retrieval exists. Keep failures visible when reranking
is explicitly enabled; do not add an unrelated automatic degradation policy.

## Cost ownership and measurement

Use native Langfuse observations and model definitions as the cost analytics
store. Do not add cost tables, per-token SQL writes, a billing ledger or a
separate cost microservice. Grafana owns operational latency/availability and
CPU/RAM/disk, not a parallel inference-price calculator.

| Call site | Observation and attribution |
|---|---|
| Leta/Leti model calls | Native callback generations; agent session/workspace/root/run |
| Compaction | Generation, task `compaction`, same executing agent |
| Ingest enrichment and validation correction | Official OpenAI wrapper, one generation for each model response; workspace/file/source version/task |
| Ingest embedding batch | One native embedding observation per batch; same file/version attribution |
| Go search query embedding | Existing OTel embedding span; workspace and invoking agent when present |
| Optional rerank | Existing rerank span with calls/latency/status; no invented token usage or cost |
| Parse/transfer/Qdrant/database | Grafana operational telemetry; no fabricated dollar cost |

Every model observation carries resolved task/model/provider identity through
existing metadata. Agent calls keep `session_id=agent_id`; ingestion uses file
and source version instead of pretending it is a conversation. Do not charge an
autonomous agent's owner as the user or assign all workspace ingestion to the
last agent that touched a file.

Reports should show total observed inference cost, split by task/model/provider,
agent session, workspace and file/source version. Include requests/errors,
input/output/cache/reasoning usage and missing-usage coverage. Native Langfuse
UI, session views and Metrics API v2 cover these queries; Hobby supports the
Metrics API. Use bounded queries/filtering and top-N for high-cardinality agent
IDs, not millions of new metric labels or one dashboard per agent.

Sum leaf generation/embedding observations once. A trace/session cost is an
aggregate; do not add it again to its children's costs. Reusing checkpointed
messages incurs no new inference charge. New successful responses on Instructor
or Temporal retries are real additional calls and stay in totals. Transport
failures without returned usage can have unknown charges; SDK-internal HTTP
retries do not each produce a separate Langfuse generation. Observability totals
therefore are not an invoice reconciliation system.

### Cross-service agent attribution

Current traceparent propagation connects the Python tool and Go retrieval tree,
but does not propagate Langfuse session/metadata. SDK `propagate_attributes`
defaults `as_baggage=False`; the shared propagator currently carries TraceContext
only. A connected trace alone is not proof that per-session cost aggregation
includes every Go embedding observation.

To include query-embedding cost in exact agent/workspace breakdowns, propose
standard OTel baggage for only the internal SemanticSearch RPC, carrying the
existing workspace/agent/root/run identifiers. Extract those selected values in
Go and set the native Langfuse session/metadata attributes on its observations.
Do not propagate prompts, keys, tool content or authorization through baggage.
Keep provider HTTP propagation TraceContext-only so this internal context is not
forwarded to external model endpoints. Do not enable global Langfuse baggage or
change Temporal's baggage policy. This is a narrow addition to the earlier
no-baggage baseline, justified by the new attribution requirement.

Ingest already receives workspace/storage identity in GetProcessingInput;
apply it before enrichment/embedding observations. No extra lookup RPC or cost
context database is needed.

### OpenRouter prices, native Langfuse calculations

One operator command during deployment or an explicit refresh should:

1. Read only configured `pricing_model` IDs.
2. Fetch OpenRouter chat and embedding model catalogs, not Vilao pricing.
3. Validate requested models/rates and retain explicit missing-price results.
4. Create/update project-owned native Langfuse model definitions through the
   Models API, matching exact provider model names. Use native pricing tiers and
   effective dates; don't reprice historical observations or add a price-history
   database. Model definitions already stored in Langfuse survive application
   restarts, and inference never waits on a price fetch.

Langfuse's public model API supports create/list/get/delete and the installed
CLI also exposes upsert. Use the current native API rather than old deprecated
`inputPrice`/`outputPrice` fields; `pricingTiers` handles usage subtypes.

Native ChatOpenAI/Langfuse conversion was checked with a synthetic usage object:
1,000 input (800 cached), 100 output (40 reasoning) becomes 200 `input`, 800
`input_cache_read`, 60 `output`, 40 `output_reasoning`. OpenAI wrapper/server
normalization can use equivalent keys such as `input_cached_tokens` and
`output_reasoning_tokens`; map their prices in the native definition too.
Price input/cache/output subtypes without charging overlapping totals twice.
Reasoning uses the completion rate when the source price has no distinct
reasoning rate; `total` is not an extra billable token class.

For Vilao, inferred costs are OpenRouter reference estimates, not its cheaper
actual bill. Preserve that distinction in reporting. Native OpenRouter costs,
when returned by OpenRouter itself, have priority in Langfuse; they remain
OpenRouter-sourced. Vilao probes returned usage but no cost; no Vilao price
endpoint is needed. If a different gateway later supplies conflicting cost
values, choose a deliberate source policy before changing capture.

Missing cache breakdown makes cache-discounted reference cost approximate;
missing usage makes cost unknown. Missing rate types or complex source price
overrides must be reported instead of silently flattened to a wrong zero/flat
price. The inspected OpenRouter GPT entry has a `min_prompt_tokens=272000`
override with input/output/cache read/write rates. Map it to a native Langfuse
usage-threshold tier using the sum of input usage subtypes, including cached
input. Preserve base rates below the threshold. This threshold is above the
illustrative working budget but still matters if that budget is raised later.
If future conditions cannot be represented, mark that reference price unsupported.

Pricing-model identity is independent of response aliases: one dated DeepSeek
request previously returned an undated response model. Do not assign two
different tariffs to an indistinguishable response name. The proposed initial
catalog uses the verified undated model; request/response names remain available
for diagnosing later aliases.

Reranking is off and makes no paid rerank calls. If enabled later, its provider's
usage/rate unit must be established before promising dollar totals; retain a
span rather than mislabel rerank as an LLM generation solely to get a cost field.

## Acceptance when implementation is authorized

- Resolve the official dependency set and pass strict Pyright plus affected
  native graph/tool/stream/structured-output/embedding/telemetry checks.
- Defaults, enrichment, agent creation/configuration and Box/Leti selections
  resolve the same central catalog with model-specific effort validation. Agent
  compaction uses the executing agent's same model/effort. Remove old
  OpenRouter-specific config names and update owners/callers/docs; no
  compatibility branch.
- Validated output modes work through native libraries; validation correction
  appears as two generations with both usage records, not just the final call.
- Permanent failures stay nonretryable through Instructor/TaskGroup wrappers;
  transient failures retain activity recovery. Verify actual HTTP/correction and
  Temporal attempt counts rather than infer them from option names.
- Query/document embeddings share model and dimensions; no implicit collection
  migration or index reuse across different embedding spaces.
- Rerank off makes zero rerank requests and returns authorized live fused hits
  bounded by top_k; on preserves the explicit error behavior.
- Cloud price fixtures verify cache/reasoning costs, effective dates, missing
  rates and sums without aggregate/child duplication. Real Cloud proof requires
  Langfuse keys and approved project access.
- Agent → SemanticSearch → embedding attribution is verified through the real
  RPC/export path, with no internal baggage at external provider HTTP endpoints.

## Sources and limits

- [OpenAI 3.49.0 changelog](https://github.com/openai/openai-python/blob/v3.49.0/CHANGELOG.md)
- [OpenAI dependency update](https://github.com/openai/openai-python/pull/3680)
- [Published Instructor 1.17.0 metadata](https://pypi.org/pypi/instructor/1.17.0/json)
- [Official Instructor commit tested with OpenAI 3.49.0](https://github.com/567-labs/instructor/tree/aeb7e2558166caeec497e541bcfc6b4eaa2cf53b)
- [OpenAI embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create)
- [OpenRouter embedding request](https://openrouter.ai/docs/api/api-reference/embeddings/create-embeddings)
- [OpenRouter embedding models](https://openrouter.ai/api/v1/embeddings/models)
- [OpenRouter reasoning-effort shorthand](https://openrouter.ai/docs/client-sdks/python/api-reference/chat)
- [Langfuse cost/model definitions](https://langfuse.com/docs/observability/features/token-and-cost-tracking)
- [Langfuse Metrics API](https://langfuse.com/docs/metrics/features/metrics-api)
- [Instructor retry behavior](https://python.useinstructor.com/concepts/retrying/)

No OpenAI/OpenRouter authenticated live calls, full workspace dependency change,
Cloud price synchronization, RPC cost-attribution test, database/index migration
or production reliability benchmark was performed. All background probe processes
started for this research completed; temporary Go code remained outside the repo.
