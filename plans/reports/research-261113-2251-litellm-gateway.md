# LiteLLM gateway for Openlet

## Status and scope

Research and proposal, not an accepted migration. No application, dependency,
database, index, deployed configuration or Langfuse Cloud resource was changed.
The existing uncommitted `.env.example` edit was preserved.

The user clarified that decision models mean models such as Jev; Openlet does
not currently use them. Their availability is being assessed, not added as a
new product feature. Evaluation remains deferred.

This assesses a replacement for the catalog/provider/retry/pricing parts of
the [preceding design](design-261113-2202-provider-catalog-compaction-retries.md).
The accepted single model reference, optional reranking, Instructor output
modes and cache-friendly compaction requirements still apply.

## Recommendation

Use one config-file LiteLLM Proxy shared by Leta, ingest and Go LetFS. Keep
their native OpenAI-compatible clients, native LangGraph integration and
Instructor. The application points at the gateway; the gateway owns upstream
credentials, deployments, normalization, short retries, configured failover and
price calculation.

Start with one worker and no LiteLLM database or Redis. Do not deploy its
full reference stack, virtual-key hierarchy, budget system or another
observability backend for this demo. Existing Openlet authorization still
protects product APIs. The gateway and its admin credential stay internal.

```text
Leta: ChatOpenAI ────────────┐
Ingest: OpenAI + Instructor ├── LiteLLM Proxy ── Vilao / OpenRouter / others
LetFS: OpenAI Go + rerank ──┘

Application AI observations ──────────────── Langfuse Cloud
Services + gateway telemetry ── Alloy ───── Grafana Cloud
```

The SDK alone is useful in a Python-only application. Here it would leave Go
needing a gateway or separate routing/pricing logic and add provider dependencies
to the workers. A standalone Proxy gives both languages the same route without
replacing their client libraries.

## Verified against a running Proxy

Downloaded the PyPI source and installed LiteLLM **1.109.1** in an isolated
temporary environment. Ran one Uvicorn worker on loopback port 4000 with YAML
deployments, an ephemeral master key, no database, no Redis and no logging
callback. Real upstream requests used the existing authorized Vilao credentials
privately. Tests used synthetic prompts, not user documents.

| Check | Result |
|---|---|
| `GET /v1/models` | Configured public aliases returned; included `mode` and available input/output limits |
| `GET /model/info` | Configured limits, custom prices, tool capability and arbitrary `structured_output` metadata returned |
| `GET /model_group/info` | Model kind, provider, limits, supported OpenAI parameters, tool support and reasoning-effort metadata returned |
| Chat through public Vilao aliases | Both `gpt-6.1-sol:low` and `deepseek-v4.1-flash:none` returned successfully |
| Streamed tool calling | Both models returned a complete `get_weather` call through OpenAI-compatible streaming |
| Native LangChain client | `ChatOpenAI` 1.7.4 assembled both tool calls and completed tool-result continuations |
| Embedding | Two inputs returned indices 0/1 and two 1,536-dimensional float vectors with usage |
| Instructor | Pinned upstream Instructor 1.18.0 produced validated data in TOOLS and MD_JSON modes through the Proxy |
| Transient failure | A controlled upstream returning 503 twice was called exactly three times before success |
| Invalid request | Controlled 400 upstream was called once; Proxy returned 400 |
| Fallback | Controlled primary received three calls, then configured backup received one and succeeded |
| Custom price | Ten input plus two output tokens at illustrative rates produced `0.000014` dollars |
| Endpoint registration | Running OpenAPI included chat, embeddings, both rerank aliases, decisions and systemone |

The fault-injection upstream was a separate local test server on port 4001;
it was not a real second provider. Two retries were separated by approximately
0.68/1.31 seconds in the transient-success check. This verifies bounded retry
and increasing waits in that check, not every provider-specific backoff policy.

Client test environment resolved OpenAI 3.50.0; the application lock currently
uses 3.49.0. No SDK source was patched. Isolated dependency resolution permitted
Langfuse 5.2.0 and the pinned Instructor source together. LiteLLM's optional
`proxy-runtime` extra has a different Langfuse constraint; it was not needed for
this config-only Proxy and need not enter application environments.

Temporary harness and detailed results were kept under
`/tmp/openlet-litellm-research-261113/`. Both research servers were terminated.
No load benchmark, actual second-provider failover, paid reranker, decision
inference or Langfuse Cloud export was performed.

## Catalog and agent selection

LiteLLM has two different catalogs in practical terms:

- Its bundled model registry describes models the library knows about. It does
  not establish that our provider sells them or that our key can call them.
- Proxy `model_list` describes deployments we actually configure and serve.
  `/v1/models` lists these public names, subject to gateway access controls.

Move the deployment/model catalog to native LiteLLM YAML. Do not keep a second
provider/model catalog in Openlet. The backend can fetch native metadata and
return a small authenticated product listing: chat models with tool support,
their supported effort choices and the Openlet default. Embedding, rerank and
decision models are not agent choices.

Openlet still needs a thin listing/validation boundary. The current Leta API
supports agent model selection but has no listing endpoint. The proposed
`GET /v1/models` remains useful; it projects gateway metadata rather than
maintaining model definitions. Its gateway/Envoy route must be wired. Do not
forward `/model/info` wholesale to browsers: deployment settings and masked
credential metadata do not belong in the product response.

For recognized models, limits and capabilities can come from LiteLLM's registry.
For Vilao/custom endpoints, override facts that differ from the native vendor:
context/output limits, supported efforts, tools and schema support. A familiar
upstream model name is not evidence that the reseller exposes every native API
feature. `/model_group/info` in the probe inherited broad native GPT capabilities
unless overridden. Metadata is descriptive, not a substitute for provider tests
or product authorization.

Keep working context budgets, selected defaults and embedding dimensions where
the application consumes them. Do not query the gateway before every model
call; fetch catalog metadata at startup and for the model listing, reusing it
within the process. Config-file model changes can use the existing restart
deployment workflow rather than a new live-update system.

## Names and reasoning effort

Native upstream routing names use the LiteLLM adapter prefix, for example:

```text
openai/gpt-6.1-sol
openrouter/openai/gpt-6.1-sol
anthropic/<model>
cohere/<reranker>
typesafe/jev-latest
```

`model_name` is a public alias we choose; it need not equal that routing name.
Vilao requires no custom SDK adapter when its endpoint is OpenAI-compatible:

```yaml
model_list:
  - model_name: vilao/gpt-6.1-sol
    litellm_params:
      model: openai/gpt-6.1-sol
      api_base: os.environ/OPENAI_BASE_URL
      api_key: os.environ/OPENAI_API_KEY
    model_info:
      mode: chat
      max_input_tokens: 65536
      max_output_tokens: 8192
      supports_function_calling: true
      supports_response_schema: false
      supported_reasoning_efforts: [low]
      structured_output: tools
```

This is illustrative, not active configuration. Limits are the previously
selected working limits, not a new claim about upstream maximums. Actual Vilao
prices must be added before cost acceptance. `structured_output` here is small
Openlet metadata carried by native `model_info`; LiteLLM does not interpret it
as an Instructor mode. The other shown capability fields are native metadata.

Keep the accepted Openlet selection string
`<public-alias>[:<reasoning-effort>]`. For example, an agent stores
`vilao/gpt-6.1-sol:low`; the caller sends gateway model
`vilao/gpt-6.1-sol` plus native `reasoning_effort="low"`. The application only
parses/validates the selected suffix against fetched metadata. Exact alias
matching comes first, to preserve real names with colon suffixes.

LiteLLM does not generally turn an arbitrary `:low` suffix into effort itself.
Native alternative: register each complete selection as a public alias whose
deployment supplies an effort default. That worked in the live probes, but
creates one configured deployment per effort variant. Prefer the small suffix
parser over multiplying dozens of model definitions. Deployment effort defaults
can also be overridden by request parameters; the alias is not an enforcement
boundary.

Agent/API/SQL selection stays one string, without a second effort field.
Unsuffixed selection omits effort; `:none` explicitly disables it only where
supported. Leti → root → configured default inheritance stays in Openlet.

## Embeddings, reranking and decision models

- Embeddings use the OpenAI-compatible `/v1/embeddings` route. The actual Vilao
  batch/dimensions/float request passed through the Proxy. Index and query must
  retain the same embedding model and dimensions; equal dimensions alone do
  not make two models interchangeable. Do not configure cross-model embedding
  failover against an existing index.
- Rerank uses `/rerank` or `/v1/rerank`, following Cohere's request/response shape.
  LiteLLM has adapters for Cohere, Voyage, Together, NVIDIA and others. Go's
  existing generic rerank POST fits that boundary; an OpenAI SDK does not need
  a dedicated rerank method. Vilao still does not gain reranking merely by
  adding a gateway. With reranker unset, retain hybrid retrieval/fusion and
  permission/live/version filtering, returning fused top results.
- Decision models such as Jev are supported through `/v1/decisions` and
  `/v1/systemone`. They return typed decisions/probabilities rather than chat
  text. Current source includes the TypeSafe adapter and the running Proxy
  registered both endpoints. No actual Jev request was made without its key.
  Their availability does not imply adding automatic decision routing now.

## Retry, fallback and structured output

If the gateway is selected, move short provider retries from application SDKs
to LiteLLM Router. Set application OpenAI/ChatOpenAI/Go retries to zero. In
inspected 1.109.1 source, Router itself defaults underlying SDK `max_retries`
to zero; the controlled HTTP checks confirmed three attempts for two configured
router retries, rather than multiplicative inner SDK retries.

Temporal retains durable activity recovery; it is not removed by the gateway.
Permanent invalid/auth/configuration errors must retain the existing
nonretryable classification. Instructor's bounded schema correction remains
separate from transport recovery. Do not add graph/tool/RPC retry middleware.

Configure only known compatible fallback targets. LLM targets need the required
tools, images, context capacity and structured mode. Fallback can change model
behavior, cost and prompt-cache reuse. A target's different structured-output
requirements are not automatically solved by an alias. Start with bounded
retries; enable specific failover only after both endpoints are tested. No
backup provider credentials were tested in this research.

Do not promise transparent repair after a stream has emitted content. Current
documentation describes pre-first-chunk failover; preserving already delivered
tool arguments/output is a client/application execution concern, not magic
provided by retry configuration.

Keep the approved three output modes when a caller requests a Pydantic schema:
Instructor TOOLS, native JSON schema, and Instructor MD_JSON/text. LiteLLM
normalizes transport; it does not make an upstream that only supports text and
tool calling enforce JSON schema. Keep Pydantic validation and one bounded
feedback correction. Never silently drop a required schema parameter.

Compaction uses the same executing model and tools with the accepted stable
prefix, summary and tail. It remains an application concern and still needs
the already recorded implementation fixes; no compaction model or gateway
compression feature is proposed.

## Cost and Langfuse

LiteLLM and Langfuse overlap in model-call usage/cost observability. Their main
roles can remain complementary: gateway routing/reliability and application
agent/tool/prompt/session observability. LiteLLM's native `langfuse_otel`
integration can export calls with usage and cost, including streaming. It does
not replace graph traces, managed prompts or the later evaluation work.

Known providers/models have a maintained price registry. That reduces manual
pricing work; it does not guarantee a reseller's prices match native OpenAI or
OpenRouter. Vilao prices must be configured explicitly in LiteLLM. Native keys
include `input_cost_per_token`, `output_cost_per_token`,
`cache_read_input_token_cost` and `cache_creation_input_token_cost`, with
additional billing units where providers require them. They are dollars per
token: a one-dollar-per-million price is `0.000001`. Use native units rather
than inventing another pricing/config translation layer.

Usage comes from responses; prices can be bundled or overridden. Unknown price
is not a free call. Configured calculations are estimates of API cost, not a
financial billing ledger or a guarantee that every provider failure reports
billable partial usage.

### Important integration finding

The real streamed OpenAI responses contained final `usage.cost`; their initial
HTTP response headers had no final cost. Nonstreaming calls returned
`x-litellm-response-cost`. The tested embedding usage carried tokens but no
embedded cost field, although its response header had the calculated cost.

Native `ChatOpenAI` streaming kept token/cache/reasoning usage but discarded the
extra cost field in the resulting message. Inspected Langfuse 5.2.0 LangChain
callback parses usage and updates its generation without reading a LiteLLM
response cost. The native Langfuse OpenAI wrapper does parse a float
`usage.cost` where present. Therefore a generic documentation statement that
Langfuse captures LiteLLM cost does not prove zero-config cost propagation
through Openlet's current LangChain callback.

### Recommended minimal integration

Keep the existing app-owned native LangChain callback, ingest OpenAI wrapper
and Go RAG observations. Do not also enable Proxy → Langfuse generation export.
Use LiteLLM for gateway metrics/costs in Grafana. Keep gateway OTel spans out
of the Alloy → Langfuse route; otherwise the same paid model call can get a
second observation and a second counted cost.

For Langfuse's application generations, derive the required custom model price
definitions from LiteLLM metadata during the existing setup/configure operation,
using Langfuse's public Models API. This is a small explicit customization:
one price source, with a derived copy for native Langfuse cost inference.
No runtime synchronization service, polling job or second manually authored
catalog. Match the public alias/accepted effort variants and the actual
input/output/cache usage buckets. Use the current Models API pricing tiers
even for a flat price, rather than its deprecated flat-price fields.

This proposal does **not** claim a universal converter for every provider's
complex pricing exists. Validate the configured models' actual billing units;
do not quietly approximate a newly enabled non-token/tiered model. Built-in
Langfuse prices can be used where its model matching and supplier rates already
agree. Direct wrapper/header cost ingestion can override inference where the
existing call boundary exposes it without another model observation.

Alternative: make the gateway the sole owner of paid inference observations
through native `langfuse_otel`, and stop application instrumentation of those
same model calls. That removes the price-definition copy, but requires changing
the existing LangChain generation tracing and verifying parentage, session,
prompt-version links and Go/ingest behavior. It is not a one-line callback
addition and is not the recommended MVP change.

If that alternative is chosen later, native OTel v2 uses
`LITELLM_OTEL_LANGFUSE_SPAN_SCOPE=llm_only` to avoid exporting auth, DB, Redis,
health and admin traffic to Langfuse. This setting alone does not deduplicate
application and gateway generations.

## Deployment and footprint

Docker Compose can run the official Proxy image with the tested version/digest,
a read-only YAML file, upstream environment credentials and an internal master
key. Applications use `http://litellm:4000/v1`. Existing `OPENAI_*` upstream
variables can remain inputs to the Proxy; do not accidentally make the Proxy's
upstream URL point back at itself when configuring application clients.

The no-DB mode really served model listing, chat, streaming, embedding, retry,
fallback and custom cost calculations in this research. DB-backed virtual
keys, durable spend history, budgets and UI-managed model editing are separate
features that require a database. No-DB price calculation is not budget
enforcement. A shared Redis is unnecessary for one worker with local routing
state and response caching disabled.

Observed process-tree RSS, no child process:

- Approximately 406 MiB after startup.
- Approximately 471 MiB after the first chat/embedding/fault probes.
- Approximately 573 MiB after additional tools/Instructor calls and generating
  the full OpenAPI schema.

These are spot RSS readings from a Python process, not Docker cgroup totals,
peak measurements, a concurrency benchmark or evidence for a hard memory cap.
Allow roughly 1 GiB initially for this small no-DB demo and measure normal
documents/concurrency before imposing a limit. Official production guidance
states 1 vCPU/4 GiB per worker and specifically discusses the Prisma engine and
large database spend writes. Do not claim the measured no-DB footprint disproves
that guidance, or that the heavier production stack is required for this demo.

Send gateway logs/metrics and optional native OTel to existing Alloy/Grafana
Cloud. Do not add local Grafana, Prometheus, a new collector or LiteLLM Lens.
Keep content capture/filtering consistent with the accepted observability
design. The new gateway is an inference dependency: its outage affects all
three clients even when providers are healthy. Compose restart and health
checking are sufficient initially; no HA design is proposed.

## Code/config impact

| Remove or avoid | Keep in Openlet |
|---|---|
| Leta-only static model catalog and duplicate provider-owned catalog proposal | Thin authenticated model-list projection and selection validation |
| Application provider factories/routing adapters | Native Python/Go clients pointing at the gateway |
| Application transport retry/backoff/fallback code | Temporal recovery and error classification |
| Custom model price map, price fetching and token-cost arithmetic | Optional setup-time derived Langfuse price definitions |
| Per-provider reasoning request formatting | One reference parser and native outbound effort parameter |
| Vendor-specific rerank transport | RAG retrieval, filtering, optional-rerank choice and one standardized HTTP call |
| Repeated upstream credentials in each service | Internal gateway URL/key and application model defaults |
| Separate compaction model proposal | Correct cache-friendly native compaction, budgets and checkpoint behavior |

Do not describe all of these as deleting existing implementation: several are
parts of the preceding unimplemented proposal. Current code still needs the
accepted API/SQL effort-field change, optional reranking and compaction fixes.
LiteLLM does not complete those tasks by itself.

## Sources

- [Model management and deployment metadata](https://docs.litellm.ai/docs/proxy/model_management)
- [Model groups and deployments](https://docs.litellm.ai/docs/router/learn/deployments_and_model_groups)
- [OpenAI-compatible custom endpoints](https://docs.litellm.ai/docs/providers/openai_compatible)
- [Retries and fallback](https://docs.litellm.ai/docs/proxy/reliability)
- [Embedding](https://docs.litellm.ai/docs/embedding/supported_embedding)
- [Rerank](https://docs.litellm.ai/docs/rerank)
- [Decision models](https://docs.litellm.ai/docs/decisions)
- [Custom pricing](https://docs.litellm.ai/docs/proxy/custom_pricing)
- [No-database deployment](https://docs.litellm.ai/docs/proxy/docker_quick_start#running-without-a-database)
- [Production sizing](https://docs.litellm.ai/docs/proxy/prod#sizing-and-workers)
- [Langfuse Proxy integration](https://langfuse.com/integrations/gateways/litellm)
- [Langfuse usage and cost](https://langfuse.com/docs/observability/features/token-and-cost-tracking)
- [LiteLLM OTel v2 and Langfuse scopes](https://docs.litellm.ai/docs/observability/opentelemetry_v2)

Inspected PyPI 1.109.1 source: `router_python_core.py`,
`proxy/common_request_processing.py`, `llms/typesafe/decisions/transformation.py`,
`integrations/otel/mappers/langfuse.py`, `types/router.py`; Langfuse 5.2.0 source:
`langchain/CallbackHandler.py`, `openai.py` and the public Models API types.
