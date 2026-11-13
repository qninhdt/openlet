# Vilao OpenAI-compatible provider: live compatibility research

## Scope and status

The user requested live provider verification and a proposal before application
changes. Requests used synthetic prompts, arithmetic tools and generated solid
color images. No workspace files or customer content were sent. No application
code, lockfile, prompt publication, database or deployment was changed.

The supplied Grafana and model-provider credentials were saved privately to the
root credential file, mode `0600`; no credential values appear in this report.
The inference endpoint is `https://api.vilao.ai/v1`, with `OPENAI_API_KEY` and
`OPENAI_BASE_URL`. A concurrent change to the tracked credential example was
observed and left outside this research commit.

## Existing integration

- Leta constructs native `ChatOpenAI` with configurable base URL/key, tool
  calling, streaming usage and `reasoning_effort`. Compaction uses text output.
  It does not require a structured response schema for agent answers.
- Ingest uses the Langfuse OpenAI wrapper and
  `chat.completions.parse(response_format=Metadata)` for enrichment. Metadata
  has title, description, semantic type and context, with Pydantic validation.
  Its reasoning parameter currently uses `extra_body.reasoning.effort`, unlike
  Leta's OpenAI-style `reasoning_effort`.
- Embedding and Go query embedding/reranking currently share the same provider
  configuration. Reranking uses `/rerank`, which is not an OpenAI standard
  endpoint. Repointing this shared provider affects indexing and search.
- The committed example names OpenRouter and its key; the actual clients already
  accept configurable endpoints. There is no implemented OpenRouter price-fetch
  mechanism in the inspected integration. Langfuse currently relies on native
  usage and model definitions for inferred pricing.

## Live evidence

Project versions: OpenAI SDK 3.49.0, langchain-openai 1.7.4, Langfuse 5.2.0,
Pydantic 2.14.3. Project requests used installed SDKs without modifying them.

| Check | Result |
|---|---|
| `GET /models` | Three IDs: `deepseek-v4.1-flash`, `gpt-6.1-sol`, `deepseek-v4.1-flash-1017` |
| Text completion, all three IDs | Passed; the dated DeepSeek ID responded with the undated model ID |
| DeepSeek SSE, `include_usage=true` | Passed; content, finish reason and one final usage object observed |
| GPT SSE through native ChatOpenAI | Passed; input/output usage present, cache/reasoning details can be absent |
| DeepSeek native streamed tool roundtrip | Passed: tool arguments, tool-call ID, tool result and final answer |
| GPT native streamed tool roundtrip | Passed with the same standard interfaces |
| Native `create_agent` graph | Passed: two tool calls in one model turn, two results, then correct final answer |
| Structured JSON schema | Request accepted, schema ignored: requested `{total: integer}`, received text `5`; SDK parse raised ValidationError |
| `json_object` | One valid JSON response observed; this does not establish enforced JSON mode |
| Repeated-prefix caching | Same 2,920-token prompt: first reported zero cached tokens, repeat reported 2,688 |
| Cache usage through ChatOpenAI streaming | Native `input_token_details.cache_read=2688`, reasoning detail also preserved numerically |
| DeepSeek reasoning low/high | Both accepted; counts present. This does not prove the effort setting is honored |
| DeepSeek reasoning none | Arithmetic answer returned without reasoning text, with reasoning tokens zero |
| Invalid reasoning effort | HTTP-success completion containing an error sentence, rather than an API error |
| Raw DeepSeek reasoning text | Returned as nonstandard `reasoning_content`; native ChatOpenAI does not retain this field |
| OpenRouter-style model ID | `deepseek/deepseek-v4.1-flash` returned HTTP 403; current bare ID works |
| Embeddings with configured embedding model | HTTP 403: model not subscribed under this API key; endpoint existence is not sufficient |
| `/rerank` | HTTP 404 |
| Simple image input | GPT identified red/blue correctly. DeepSeek identified blue but called red white in an earlier probe; vision is not established as reliable |

Examples of usage reporting:

- DeepSeek minimal text: 35 input, 11 output, including 9 reasoning tokens.
- Repeated prefix: 2,920 input, 2,688 cached; cached tokens are a subset of input.
- GPT minimal text: 1,508 input, 5 output, with 1,280 cached in one response.
  These are provider-reported counts, including possible hidden overhead; the
  test cannot independently verify billing or actual model identity.
- Missing cache/reasoning details occurred in valid GPT responses. Unknown
  details must remain unknown; do not synthesize zero or add subset tokens again.

Short successful probes typically took approximately 1–6 seconds. These are
compatibility checks, not a production latency or reliability benchmark.

## Instructor verification

Official documentation describes `TOOLS`, `JSON_SCHEMA`, `JSON` and `MD_JSON`.
`MD_JSON` requests JSON as ordinary model text; the observed request had neither
`response_format` nor tools. Both native modes below worked against Vilao:

- `TOOLS`: four-field file metadata validated on the first request.
- `MD_JSON`: the same metadata shape validated on the first request.
- Validation feedback: a title missing a validator-required prefix failed;
  Instructor sent the error back and produced a valid title on the second
  request. `max_retries=1` meant one additional extraction attempt in this
  tested version. Each SDK client's transport retries were disabled for probes.

Dependency constraint is material: Instructor 1.17.0 requires `jiter<0.15`,
whereas the project's OpenAI 3.49.0 requires `jiter>=0.16`. The resolver rejected
that combination. An isolated environment with Instructor 1.17.0 and
langchain-openai 1.7.4 selected OpenAI 3.3.0/jiter 0.14.0; live extraction probes
passed there. No project downgrade, dependency override or SDK patch was made.
Initial source-inspection imports targeted obsolete Instructor module locations
and failed; public APIs and wire-request hooks were then used successfully.

## Proposal, not an approved implementation change

1. Keep native OpenAI/ChatOpenAI clients and Chat Completions. Use `OPENAI_*`
   credentials/settings; remove the OpenRouter-specific key convention when
   implementing. Preserve YAML as the shared settings authority and explicitly
   resolve environment references for a configured base URL; current loading
   does not interpolate arbitrary YAML strings automatically.
2. Keep Leta's native tools and text compaction. No response JSON schema or
   SDK subclass is needed. Missing reasoning text does not block the tested
   tool loop. Do not promise raw reasoning display through native ChatOpenAI.
3. Use Instructor for ingest validation feedback instead of handwritten JSON
   repair, regex mutation or a custom retry protocol. Propose one setting:
   `models.enrichment.output_mode: tools | json_schema | text`, mapped to
   Instructor `TOOLS | JSON_SCHEMA | MD_JSON`. Select `tools` for this provider;
   `text` remains an explicit supported choice. Do not autodetect/fallback across
   modes or send `strict: true` to ordinary tool mode.
4. Keep Pydantic Metadata as the single validation schema. At most one
   validation correction request is a reasonable initial bound. Transport
   retries use the native SDK/Temporal mechanisms, with the actual total request
   bound reviewed when implementing; no new retry service or JSON fixer.
   Record every model request, including failed validation attempts, in
   Langfuse rather than recording only the eventual successful extraction.
5. Resolve the dependency conflict deliberately before adding Instructor. A
   compatible official release is preferred. Using the isolated compatible SDK
   versions requires a reviewed dependency change and the project's integration
   checks; forcing incompatible requirements or forking the SDK is not proposed.
6. Keep embedding and reranking on working independently configured endpoints
   until Vilao subscriptions/endpoints are available. Do not remove search,
   fabricate vectors or silently skip reranking to accommodate the chat provider.
7. Maintain exact model IDs advertised by the inference endpoint. When Vilao
   adds canonical OpenRouter-style IDs, use those directly. Until then, a small
   explicit canonical pricing-model mapping is safer than stripping/prepending
   prefixes or conflating distinct dated model variants.
8. Prices come only from the public OpenRouter model catalog. Fetch outside
   individual model calls and populate native Langfuse model definitions using
   supported APIs. Treat these as OpenRouter reference estimates, not Vilao
   invoices. Do not fetch Vilao price data or implement a custom cost exporter.
   This research verified matching OpenRouter IDs, without fetching/reporting
   numeric prices for a pricing decision or creating Langfuse definitions.

## Grafana credential check

Empty requests were sent to all three ingestion endpoints using the discovered
instance IDs. Metrics, logs and traces each returned HTTP 401. The logs response
specifically said `authentication error: invalid scope requested`. The supplied
token is stored but is not proven usable; its stack realm and write scopes need
correction or replacement. No telemetry content was uploaded in these probes.

## Sources

- [Instructor modes](https://python.useinstructor.com/modes-comparison/)
- [Instructor retry behavior](https://python.useinstructor.com/concepts/retrying/)
- [Instructor release metadata](https://pypi.org/pypi/instructor/1.17.0/json)
- [OpenRouter public model catalog](https://openrouter.ai/api/v1/models)
- [Langfuse usage and native model pricing](https://langfuse.com/docs/observability/features/token-and-cost-tracking)

## Decisions still needed

- Which authorized endpoints/keys will serve embedding and reranking?
- Whether an approved compatible dependency change is acceptable if Instructor
  still conflicts with the project's current SDK when implementation begins.
- Vilao canonical model aliases need provider-side availability before callers
  switch to OpenRouter-style request IDs.

No full Openlet/Langfuse Cloud integration, outage/retry fault injection,
large-context stress, reliable vision evaluation or price synchronization ran.
