# LiteLLM metadata, SDKs and cost integration

Follow-up: [production configuration ownership](research-261113-2345-inference-configuration-ownership.md)
records the user's withdrawal of the suffix-format constraint, verifies native
gateway aliases/shared Vilao credentials/streaming cost, and proposes Langfuse
Prompt Config for task tuning. It supersedes the suffix/default_for proposals
below; the SDK and per-call cost evidence remains applicable.

## Status

Research/proposal only. No application, dependencies, accepted implementation
plans, schema, deployed configuration or Cloud resources changed. The unrelated
`.env.example` edit remains untouched. Evaluation remains deferred.

This refines the [first gateway assessment](research-261113-2251-litellm-gateway.md):
prefer `ChatLiteLLM` for Leta and LiteLLM async calls with Instructor for ingest.
The verified cost path below removes the earlier proposed setup-time price copy
to Langfuse. Do not implement that price synchronization.

## Recommended boundary

Use one config-file LiteLLM Proxy, initially one worker without DB or Redis.
Keep concrete model deployments, upstream credentials, capabilities, prices,
Leta availability and configured defaults there. Openlet consumes metadata and
keeps product model selection, context budgets, RAG/index semantics and traces.

```text
Leta: ChatLiteLLM + Langfuse LangChain callback ─┐
Ingest: Instructor + LiteLLM async SDK ─────────┼─ Proxy ─ providers
LetFS: OpenAI Go SDK + standard rerank HTTP ────┘

App-owned observations + gateway-calculated cost ─ Langfuse Cloud
Services and gateway operational telemetry ─ Alloy ─ Grafana Cloud
```

Only the Proxy owns short transport retries/failover. Set application SDK and
ChatLiteLLM retries to zero. Instructor validation feedback and Temporal durable
activity recovery retain their separate responsibilities. No local Router,
second provider catalog, price calculator or transport retry middleware.

## Registry and deployed capabilities

The user-supplied maintained model registry contains model kinds, endpoints,
modalities, input/output limits, tool/schema support, reasoning/effort flags,
cache capabilities and prices. Use LiteLLM's maintained data rather than copying
this file into Openlet or implementing a registry refresh job.

Distinguish native model capabilities from a reseller deployment. Vilao's
OpenAI-compatible endpoint can expose fewer features than native OpenAI. Set
those differences once in Proxy `model_info`; do not maintain another output
mode or capability table in application configuration. Unknown metadata is not
evidence of support.

Verified with LiteLLM 1.109.1:

- `GET /model/info` returns deployment capability overrides and custom metadata.
- `litellm.proxy.client.Client(...).models.info()` returns that metadata;
  `.models.list()` returns deployed aliases. Both returned three configured
  models in the live probe. This management client is synchronous and broadly
  typed; the existing async HTTP client plus a small validated response boundary
  is also sufficient for application startup/listing.
- `get_model_info()` and capability helpers work for known native registry IDs.
  For a `litellm_proxy/vilao/...` alias they returned missing/false capabilities,
  despite the Proxy exposing the correct overrides. Do not use these local
  helpers as a replacement for fetching deployed metadata.
- `model_group/info` is useful but its typed projection does not include every
  deployment capability. Prefer `/model/info` for this consumer.

Read metadata during startup and reuse it for runtime/listing validation.
Config-file changes use the deployment restart workflow; no catalog polling or
per-LLM-call metadata request. Return only public selection information to the
browser, never the full admin response with deployment/credential settings.

## Leta-supported subset and defaults

Native `model_info.access_groups: [leta]` marks models offered to Leta. Other
chat, embedding, rerank or decision deployments can coexist in the same Proxy.
The product listing/selection boundary filters this group and checks the
capabilities actually required by the agent. An embedding model is never an
agent choice merely because it is deployed.

For config-only defaults without concrete names in backend configuration,
propose `model_info.default_for: [leta]`. This is an explicitly **custom metadata
convention**, not an automatic LiteLLM default-selection feature. The native
model-info schema permits extra metadata; the live Proxy returned this marker.
Require one default for each consumer that needs one. Enrichment can use the
same convention; select the shared embedding deployment consistently in both
indexing and query code. A configured optional reranker can remain absent.

Illustrative deployment fragment, not active configuration or a price claim:

```yaml
model_list:
  - model_name: vilao/gpt-6.1-sol
    litellm_params:
      model: openai/gpt-6.1-sol
      api_base: os.environ/OPENAI_BASE_URL
      api_key: os.environ/OPENAI_API_KEY
      reasoning_effort: low
    model_info:
      access_groups: [leta]
      default_for: [leta]
      supports_response_schema: false
      supports_function_calling: true
      supported_reasoning_efforts: [low]
```

Only override limits/modalities/prices where the actual deployment differs or
is unknown; do not repeat every native registry field. `default_for` and the
explicit effort-list override are application-consumed metadata. Proxy
membership/default metadata does not enforce service authorization when callers
share its internal master key. Native virtual keys with group restrictions
provide that enforcement if needed, but require a LiteLLM DB.

Keep the accepted selection `<public-alias>[:effort]`, for example
`vilao/gpt-6.1-sol:low`. Exact alias matching precedes suffix parsing. Send the
alias and native `reasoning_effort` separately on the inference request. No
separate effort field in product API/SQL. Absence omits the request parameter
and uses the deployment/provider default; `none` explicitly disables reasoning
only when supported. The client-only `litellm_proxy/` prefix never enters the
stored product model reference.

## SDK convenience and recommendation

| Consumer                | Recommended client                                                     | Evidence and limit                                                                                        |
| ----------------------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Leta/LangGraph          | `langchain_litellm.ChatLiteLLM` from `langchain-litellm`               | Native tools, async and streaming; tested tool-call continuation and cost metadata through the Proxy      |
| Ingest structured calls | `instructor.from_litellm` around the async completion call             | Real TOOLS extraction and validation correction through the Proxy passed; keep native Pydantic validation |
| Ingest embeddings       | `litellm.aembedding`                                                   | Real batch/dimensions/float response and gateway cost passed                                              |
| LetFS Go                | Existing official OpenAI Go SDK; generic HTTP for Cohere-shaped rerank | A Python SDK is unnecessary in Go; read gateway cost from response headers                                |
| Deployment metadata     | Native management client or existing HTTP client                       | Native management SDK worked; no new catalog framework is needed                                          |

Do not use `ChatLiteLLMRouter` or an application `litellm.Router` alongside the
Proxy. Set `ChatLiteLLM.max_retries=0` and underlying SDK `num_retries=0`; its
inspected default max retries is one. Reuse clients per process. Python SDKs
add dependencies to workers; no worker memory benchmark was performed.

`ChatLiteLLM.with_structured_output()` supports `json_schema`,
`function_calling` and `json_mode`; it does not itself implement a general
capability-driven fallback policy for arbitrary Proxy aliases.

## Structured output without a manual mode field

Native Structured Outputs commonly means schema enforcement through JSON
Schema; they are not two successive generic mechanisms. Select the existing
Instructor modes from the actual deployment metadata:

```text
supports_response_schema = true → JSON_SCHEMA
otherwise supports_function_calling = true → TOOLS
otherwise → MD_JSON/text + Pydantic validation
```

No `structured_output` setting is needed per model. No mode selection belongs
on ordinary agent tool calls. A schema-demanding caller chooses once from
metadata. If a deployment explicitly rejects that format/parameter, a bounded
lower-mode attempt is reasonable; do not downgrade for authentication, 429,
5xx or an arbitrary 400. Correct stale metadata after verification. Instructor
owns bounded validation feedback; the gateway owns transport recovery. Never
enable parameter dropping that silently discards required schema enforcement.

Configured fallback deployments must satisfy the exposed model group's
capability contract. Do not promise that native gateway fallback dynamically
rebuilds an Instructor request for a backup with a different output mechanism.
Changing an embedding model requires index coordination/reindexing, not a
transparent cross-model fallback.

## Cost ownership and Langfuse

LiteLLM calculates costs from reported usage and its registry/overrides.
Langfuse displays and aggregates the explicitly supplied per-call cost with
agent/session/workspace/file observations. Neither the SDK nor a gateway can
infer Vilao's real selling price from a native OpenAI name. Configure custom
supplier prices in LiteLLM once when rates differ. Unknown price is not zero.
Use native per-token units and cache-rate fields; no Openlet arithmetic or
manual Langfuse price map.

### Leta

`ChatLiteLLM` 0.11.2 preserves gateway-specific `response_cost` in message
response metadata, including streaming. A small inline LangChain cost callback
before the native inline Langfuse callback reads this total and calls public
`update_current_generation(cost_details={"total": ...})` while that generation
is current. No Langfuse callback subclass or second generation.

Real async invoke and async stream each emitted exactly one Langfuse generation
with the expected cost into an in-memory OTel exporter. This refines the earlier
ChatOpenAI test, which discarded the streamed extra cost field.

### Ingest and Instructor correction attempts

Record the individual inference completion before returning it to Instructor.
Use public native Langfuse generation/embedding observations around the typed
async SDK calls and set usage/cost from each raw response. This replaces the
existing instrumented OpenAI client for these calls; do not enable an additional
LiteLLM Langfuse callback on top.

A live forced-validation probe made two successful provider requests, then one
embedding request. The public-API integration emitted two generations and one
embedding, with the same parent and each call's gateway cost. Input counts
were copied before Instructor combined usage, and remained per request.

Why this explicit integration is justified:

- Reading only `create_with_completion()`'s final response cost misses paid
  correction attempts.
- The tested native LiteLLM OTel v2 callback ran after Instructor mutated its
  response usage: the second generation reported the accumulated first-plus-
  second token counts. Its total costs were still per request. Native embedding
  mapping also labeled the embedding as `generation` in this version.
- The older callback's defaults updated the existing parent instead of creating
  a separate primary observation for each call. Enabling it without inspecting
  those defaults would not prove correct per-attempt observability.

The minimal public-API integration avoids those observed problems. It does not
implement another exporter, cost calculator or retry layer. Implementation must
preserve cache/reasoning usage details as well as totals, link managed prompts,
and verify error/cancellation behavior. The research probe primarily verified
per-attempt input/output counts, costs, types and parentage.

### Go and gateway

Go keeps its existing app-owned retrieval/embedding/rerank observations. Read
nonstreaming `x-litellm-response-cost` into their cost attributes. The previous
real embedding probe confirmed this header; full Go export remains to verify.

Do not enable gateway-to-Langfuse export for these same calls. Operational
Proxy metrics/spans go to Alloy/Grafana; avoid re-exporting them into Langfuse.
This keeps one counted paid-call observation and avoids duplicated Cloud units.
No-DB operation calculates per-response cost; it does not provide a durable
LiteLLM spend ledger or budget enforcement. Costs are operational estimates,
not a replacement for the supplier invoice, including unreported partial work.

## Rust status and deployment

As inspected on 2026-11-13, the official migration tracker reports 39% of major
APIs. The 1.110 RC release moves the Router core to Rust and introduces a
standalone gateway binary with Python forwarding. That is not full Proxy
feature parity or an end-to-end Rust implementation of Openlet's workload.
The blog's December target concerns selected `/v1/messages` traffic, not all
chat/embedding/rerank/telemetry paths today. Tested 1.109.1 source still selects
the Python router core; do not apply 1.110 RC claims to that version.

Recommend the standard stable Proxy image, pinned after compatibility checks.
Do not choose an RC Rust-only deployment for this MVP. The published ~21.8 MB
Rust versus ~329.5 MB Python example measures a forwarding-only beta without
logging/spend/persistence; it does not size our complete setup. No Rust runtime
or comparable load benchmark was run.

Proposed, not created:

- `infra/config/litellm.yaml`: deployments, capabilities/prices, groups/default
  markers and router retry settings; no plaintext secrets.
- `infra/compose.yaml`: internal Proxy service and read-only config mount.
- Root `.env`: upstream credentials and internal gateway key, referenced using
  native `os.environ/...` entries. Application config contains gateway
  connectivity and product/runtime budgets, not a second concrete model list.
- Add a separate DB/user on existing PostgreSQL only if native UI-managed model
  editing, virtual keys, durable spend or budgets become requirements. No
  database is required for the demonstrated config-only path.

## Exact code impact

| Existing owner                                                  | Change if approved                                                                                                                        |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `packages/sdk-python/src/openlet_sdk/config.py` and shared YAML | Remove local catalog/model-specific settings moved to the Proxy; retain connection and product execution limits                           |
| `apps/leta/src/leta/config.py`                                  | Replace local-catalog/effort validation with a small deployed-metadata boundary                                                           |
| `apps/leta/src/leta/runtime/agent.py`                           | ChatLiteLLM construction and inline cost integration; same graph/tools/checkpoints                                                        |
| `apps/leta/src/leta/agents.py`, `api.py`, SQL                   | Complete accepted single-selection contract and model-list endpoint; no standalone effort field                                           |
| `apps/letfs-ingest/src/letfs_ingest/providers.py`               | Instructor schema calls, LiteLLM async embedding, per-attempt native Langfuse observations; remove provider-specific reasoning formatting |
| `apps/letfs/internal/storage/search.go`                         | Gateway URL/model discovery/default selection, response cost, optional reranker; retain native Go SDK                                     |
| `scripts/configure.py`, Compose, Alloy/config examples          | Internal gateway wiring, new product model-list route and operational telemetry                                                           |

Do not create a price-fetcher/synchronizer, model registry service, custom
provider interface, SDK fork, separate compaction model or response-cache
system. Cache-friendly compaction still needs its already recorded request
fixes; adopting LiteLLM does not make the current compaction implementation
correct automatically.

## Verification and remaining limits

Tested in `/tmp/openlet-litellm-research-261113/` with LiteLLM 1.109.1,
langchain-litellm 0.11.2, Langfuse 5.2.0 and pinned upstream Instructor 1.18.0.
The isolated environment resolved OpenAI 3.50.0; application lock is 3.49.0.
Real requests used synthetic inputs and the existing authorized Vilao key
without printing it. Configured costs were illustrative test rates.

No full LangGraph/concurrent-tools/compaction test with the new wrapper, Go
cost-export test, real second-provider failover, paid reranker/decision call,
Cloud ingestion or Rust benchmark. The public-API cost probe checks local OTel
output, not Cloud aggregation. All temporary research servers were stopped.

## Sources

- [Maintained model registry supplied by the user](https://raw.githubusercontent.com/BerriAI/litellm/refs/heads/main/model_prices_and_context_window.json)
- [LangChain LiteLLM integration](https://docs.langchain.com/oss/python/integrations/chat/litellm)
- [Instructor LiteLLM integration](https://python.useinstructor.com/integrations/litellm/)
- [Model access groups](https://docs.litellm.ai/docs/proxy/model_access_groups)
- [Structured-output capabilities](https://docs.litellm.ai/docs/completion/json_mode)
- [Custom model pricing](https://docs.litellm.ai/docs/proxy/custom_pricing)
- [OpenTelemetry v2](https://docs.litellm.ai/docs/observability/opentelemetry_v2)
- [Rust migration tracker](https://docs.litellm.ai/rust-migration)
- [Router migration announcement](https://docs.litellm.ai/blog/router-rust)
- [1.110 RC release](https://docs.litellm.ai/release_notes/v1.110.0rc1/v1-110-0-rc-1)
