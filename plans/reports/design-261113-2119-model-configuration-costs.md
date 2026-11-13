# Model configuration, structured output and API costs

## Status and scope

Proposal for review, following the user's approval of OpenAI-compatible clients,
`OPENAI_*` environment names, bare Vilao model names, and Instructor-based
structured extraction. No application code, dependencies, database, deployment
or Langfuse model definitions were changed. The uncommitted credential-example
edit was preserved. Previous [live provider research](research-261113-2054-vilao-provider.md)
remains evidence, with the embedding restriction superseded below.

## Verified follow-up

### Grafana

The user's screenshot shows `logs:read`, `metrics:read`, `traces:read` on the
policy. Alloy requires `logs:write`, `metrics:write`, `traces:write`. This explains
the observed ingestion error `invalid scope requested`. Editing the existing
policy changes its tokens' permissions; replacement credentials are not needed
solely to change scopes. Save the policy and repeat ingestion checks afterward.
No policy change or new Grafana verification ran in this proposal.

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

### Dependency conflict

An isolated official dependency set resolved and passed live calls:

| Dependency | Version |
|---|---|
| Instructor | 1.17.0 |
| OpenAI | 3.3.0 |
| jiter | 0.14.0 |
| LangChain | 1.5.0 |
| langchain-openai | 1.7.4 |
| Langfuse | 5.2.0 |

Instructor with the official Langfuse OpenAI wrapper extracted a validated
integer. Native ChatOpenAI streaming retained usage. Langfuse Cloud export was
disabled because its project keys are still unavailable, so wrapper compatibility
is proven, not full Cloud ingestion. Instructor's incompatible bound is on jiter;
do not force OpenAI 3.49.0 into that set or patch its SDK.

Recommendation: pin this compatible official set, keep the current LangChain and
Langfuse versions, and run the affected graph/tool/stream/enrichment/embedding,
type and telemetry checks before merging. No project downgrade has occurred.

## Configuration proposal

Keep one shared YAML with three actual boundaries: providers, catalog and task
assignments. Provider credentials/URLs can reference `OPENAI_*`; the existing
loader must explicitly resolve allowed references rather than pass literal
`${...}` strings to clients. Resolve configured fields, not arbitrary YAML text.

```yaml
models:
  providers:
    main:
      base_url: ${OPENAI_BASE_URL}
      api_key: ${OPENAI_API_KEY}
      timeout_seconds: 90
      max_retries: 1

  catalog:
    fast:
      provider: main
      model: deepseek-v4.1-flash
      pricing_model: deepseek/deepseek-v4.1-flash
      context_window_tokens: 65536
      structured_output: tools
      reasoning_efforts: [null, none, low, high]

    reasoning:
      provider: main
      model: gpt-6.1-sol
      pricing_model: openai/gpt-6.1-sol
      context_window_tokens: 65536
      structured_output: tools
      reasoning_efforts: [null, low]

    documents:
      provider: main
      model: text-embedding-3-large
      pricing_model: openai/text-embedding-3-large
      dimensions: 1536

  tasks:
    agent:
      model: fast
      allowed_models: [fast, reasoning]
      max_output_tokens: 8192
      reasoning_effort: null

    compaction:
      model: fast
      max_output_tokens: 4096
      reasoning_effort: none

    enrichment:
      model: fast
      max_output_tokens: 8192
      reasoning_effort: none
      validation_retries: 1

    embedding:
      model: documents

    rerank: null
```

The 65,536-token context settings above are conservative configured working
budgets for illustration, not verified Vilao capacity. Existing input/image
limits remain with enrichment; parsing/chunking/concurrency remain with ingest.
Do not infer Vilao's true capacity from OpenRouter metadata.

Field responsibilities:

- Provider: connection details and native transport retry policy, shared by the
  selected entries. A second provider entry is needed only when actually used.
- Catalog key: stable application model selection ID. `model` is exactly the
  provider request string. SQL/API agent `model_id` would select the catalog key;
  this is an intentional contract change that must include callers/tests and
  an explicit data transition if existing rows are retained. No fallback alias.
- `pricing_model`: exact OpenRouter catalog ID, independent of request names.
  Do not prepend a guessed vendor or infer identity from an alias.
- `structured_output`: strategy only for calls that supply a response schema.
  It does not impose structured answers on agent tool loops or compaction.
- Context/reasoning settings: existing budget/admission responsibility, not a
  provider capability registry. List only values intentionally offered by UI/API.
- Task: model selection and generation budget for a real call site. Agent
  selection does not silently change compaction or enrichment.

Per-task `structured_output` can override the catalog default when actually
needed; omit it otherwise. A new structured task supplies its Pydantic response
model in code and selects a catalog model in config. Do not place schemas,
prompts, tool definitions or arbitrary adapter classes into YAML.

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
the ingest OpenRouter-specific `extra_body.reasoning` shape.

Native transport `max_retries=1` allows one additional HTTP attempt for supported
transient errors. Instructor `validation_retries=1` allows one correction model
call. This yields at most four HTTP attempts for an extraction attempt under
those native retry rules; existing Temporal activity retries remain outside
that bound. Authentication/configuration errors do not become JSON correction
attempts. No new Temporal workflow or retry controller is proposed.

## Optional reranking

`tasks.rerank: null` disables reranking. Enabling it selects a configured entry,
for example `rerank: {model: relevance}`; the referenced model supplies its own
provider/model. Do not add both `enabled` and a nullable model field.

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
- Changing each task's model affects only that task; per-agent selection remains
  admitted against its catalog. Remove old OpenRouter-specific config names
  and update owners/callers/docs; no compatibility branch.
- Validated output modes work through native libraries; validation correction
  appears as two generations with both usage records, not just the final call.
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

- [OpenAI embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create)
- [OpenRouter embedding request](https://openrouter.ai/docs/api/api-reference/embeddings/create-embeddings)
- [OpenRouter embedding models](https://openrouter.ai/api/v1/embeddings/models)
- [Langfuse cost/model definitions](https://langfuse.com/docs/observability/features/token-and-cost-tracking)
- [Langfuse Metrics API](https://langfuse.com/docs/metrics/features/metrics-api)
- [Instructor retry behavior](https://python.useinstructor.com/concepts/retrying/)

No OpenAI/OpenRouter authenticated live calls, full workspace dependency change,
Cloud price synchronization, RPC cost-attribution test, database/index migration
or production reliability benchmark was performed. All background probe processes
started for this research completed; temporary Go code remained outside the repo.
