# Production inference configuration: Langfuse and LiteLLM

## Status

Research and proposal, not application implementation or a newly accepted
architecture. The user explicitly withdrew the old model-reference naming
constraint. Do not preserve the `<provider>/<model>:effort` parser or the
previously proposed `default_for` metadata convention on that basis.

This refines the [SDK/capability assessment](research-261113-2324-litellm-sdk-capabilities.md).
The existing unrelated `.env.example` edit is preserved. No Cloud resource,
application, schema, dependency or live production setting was changed.

## Recommended ownership for production tuning

Both products can hold inference parameters. For Openlet's new requirement to
tune production behavior, recommend native Langfuse Prompt Config for each
task's default model selection and request parameters. Keep the deployed model
catalog and provider operations in LiteLLM.

| Setting                                                                   | Owner                                                                |
| ------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Prompt text and task default model alias                                  | Langfuse prompt version                                              |
| Task reasoning effort, temperature, top_p/top_k and desired output budget | Langfuse Prompt Config, only when needed and supported               |
| Deployed model aliases and Leta-supported subset                          | LiteLLM model_list and access_groups                                 |
| Upstream model ID, endpoint and credentials                               | LiteLLM deployment/credential configuration                          |
| Model capabilities, limits, prices and overrides                          | LiteLLM                                                              |
| Short transport retry/fallback                                            | LiteLLM                                                              |
| Explicit agent selection/inheritance                                      | Existing Openlet product state; selection is an opaque LiteLLM alias |
| Tools and output contract                                                 | Typed application code; Instructor validates model output            |
| Hard execution/context policy and embedding-index dimensions              | Application/index configuration                                      |

This keeps concrete system default model names and inference tuning out of
Openlet YAML. Langfuse's config is versioned with the prompt and fetched in the
same object. A model alias there must exist in LiteLLM; it is a reference to a
deployment, not another catalog. The SDK does not execute arbitrary prompt
config automatically: application integration must pass its supported fields
to the normal client call.

Do not configure the same task's temperature/effort/output defaults in both
Langfuse and LiteLLM. Do not silently omit an explicitly selected unsupported
parameter. LiteLLM's generic API compatibility does not mean every model
supports top_k, or that every reasoning model permits temperature tuning.
Missing optional parameters stay absent, not null-filled.

Illustrative Langfuse configs:

```json
{
  "model": "vilao/gpt-6.1-sol",
  "reasoning_effort": "low"
}
```

```json
{
  "model": "vilao/deepseek-v4.1-flash",
  "reasoning_effort": "none",
  "temperature": 0.2
}
```

These are proposed defaults for `leta/root` and `letfs/enrichment`, not values
published to Cloud. Leti/root selection inheritance remains application
behavior. Explicit agent model selection continues to override a system
default. The per-agent effort-selection API replacing the withdrawn suffix
format still needs to be agreed before that contract is implemented; this
research does not silently introduce another API/SQL field or remove effort
selection.

Compaction continues using the executing model; no model is added to the
compaction prompt config. Tools and the Pydantic output schema stay in code
because changing them changes application contracts.

## Production change workflow

1. Create a new prompt version with its changed config in Langfuse.
2. Verify that the chosen alias and parameters are supported by the actual
   LiteLLM deployment. A staging check need not become an evaluation system.
3. Move the `production` label to the new prompt version.
4. New invocations use the refreshed prompt/config; an invocation retains its
   resolved version. Roll back by moving the label to the previous version.

No application YAML change or service redeployment is required for this kind
of prompt/config release. Observations retain the actual model, parameters,
usage/cost and linked prompt version. A provider/deployment change remains a
separate LiteLLM operational change; it is not rolled back by a Langfuse label.

## Native gateway defaults are also possible

The live LiteLLM 1.109.1 probe verified native `router_settings.model_group_alias`:

```yaml
router_settings:
  model_group_alias:
    leta-default: vilao/gpt-6.1-sol-low
    enrichment: vilao/deepseek-v4.1-flash-none
    embedding: vilao/text-embedding-3-large
```

The target model_list entries supplied native `litellm_params.reasoning_effort`
values. Clients could use the aliases without parsing a suffix. `/model/info`
returned alias rows inheriting mode, capability overrides, groups and effort.
Streamed chat through `enrichment` and embedding through `embedding` succeeded.
This is an alternative ownership choice for chat/enrichment defaults, not a
second default mechanism to deploy alongside Langfuse Prompt Config.

If everything must instead be managed in the gateway, this native mechanism
works without `default_for`. For the production prompt/config versioning
requirement, prefer the Langfuse ownership above. Stable gateway embedding
selection remains appropriate because embedding has no prompt configuration;
changing its target model requires coordinated reindexing, not an ordinary
hot model switch.

## Proposed LiteLLM configuration

Config-only deployment, with no custom SDK/provider class:

```yaml
credential_list:
  - credential_name: vilao
    credential_values:
      api_base: os.environ/OPENAI_BASE_URL
      api_key: os.environ/OPENAI_API_KEY
    credential_info:
      custom_llm_provider: openai

model_list:
  - model_name: vilao/gpt-6.1-sol
    litellm_params:
      model: openai/gpt-6.1-sol
      litellm_credential_name: vilao
    model_info:
      access_groups: [leta]
      supports_response_schema: false
      supports_function_calling: true

  - model_name: vilao/deepseek-v4.1-flash
    litellm_params:
      model: openai/deepseek-v4.1-flash
      litellm_credential_name: vilao
    model_info:
      mode: chat
      access_groups: [leta]
      supports_response_schema: false
      supports_function_calling: true

  - model_name: embedding
    litellm_params:
      model: openai/text-embedding-3-large
      litellm_credential_name: vilao
    model_info:
      mode: embedding

router_settings:
  num_retries: 2

litellm_settings:
  drop_params: false
  include_cost_in_streaming_usage: true

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

Vilao is a custom OpenAI-compatible endpoint using the built-in OpenAI
transport, named `vilao` in the reusable credential store and public model
aliases. It is not claimed to be an upstream-registered `vilao/` adapter in
`litellm_params.model`. No editing LiteLLM's bundled providers.json, Python
provider plugin or SDK fork is necessary for the tested chat/embedding API.
The real shared-credential configuration was verified without repeating keys
or URLs per model.

The fragment illustrates ownership and routing. Deployment timeout/working
limits and verified custom prices still need the normal operational values.
Known model pricing can come from LiteLLM's registry; unrecognized/reseller
rates must be configured/mapped there rather than invented or treated as zero.
The native credential indirection probe used explicit illustrative rates, not
an assertion about Vilao's supplier invoice.

Openlet retains only gateway connectivity and product/runtime settings in its
YAML. `OPENAI_BASE_URL` points at Vilao on the Proxy, not back to the Proxy.
Backend clients point at the internal LiteLLM address and use its internal key.

If the user also wants to avoid editing the LiteLLM file, native Admin UI/API
model management needs a LiteLLM database. Use a separate DB/user on existing
PostgreSQL, not another PostgreSQL container. UI-owned keys cannot also be
owned by YAML. This is not required merely to tune Langfuse Prompt Config.

## Reads and caching

| Operation                               | When Openlet uses it                          | Cache/behavior                                                                                         |
| --------------------------------------- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Langfuse get_prompt                     | At an invocation/enrichment boundary          | Native SDK caches the complete prompt including config, default TTL 60 seconds; stale-while-revalidate |
| LiteLLM /model/info                     | Startup and on-demand catalog refresh/listing | Propose one in-process snapshot, TTL 60 seconds; no Redis or polling job                               |
| LiteLLM /v1/models                      | Not needed in addition to /model/info         | Existing product listing can project the cached info                                                   |
| LiteLLM chat/embedding/rerank endpoints | Actual inference requests                     | The request is the work; cost is returned with it, no second cost lookup                               |

LiteLLM loads its model registry/deployments into process memory. Config-only
/model/info enriches that registry data, rather than querying upstream /models
on every call. That is different from caching the HTTP response inside an
Openlet client. The tested management SDK performs a request on each info()
call; the live endpoint supplied neither Cache-Control nor ETag. Do not assume
transparent client caching. No per-token/per-tool metadata lookup is needed.

LiteLLM also offers optional LLM response caching. That is a separate feature
and does not cache Openlet's metadata reads. Do not enable it or add Redis for
this task. Provider prompt caching remains unrelated and available.

## Streaming cost: verified

Enable `litellm_settings.include_cost_in_streaming_usage: true` and request
`stream_options.include_usage: true`. With the tested OpenAI-compatible stream,
LiteLLM included numeric cost in the final usage chunk. There was no final
cost in the initial response header, since the answer had not completed yet.

Real request through the `enrichment` alias returned eight input tokens and
one output token. At the deliberately configured test rates, final usage.cost
was 0.000010, exactly matching the expected gateway calculation. ChatLiteLLM
streaming preserved the same 0.000010 in response_metadata.response_cost.
Embedding through the shared credential/alias returned one 1536-dimensional
vector and a nonstreaming x-litellm-response-cost header.

Cost is not an estimate attached to every token. In an interrupted stream,
final usage/cost may be missing; never silently present that as a free call.
The earlier app-owned Langfuse cost integration remains applicable.

## Instructor validation clarification

The Pydantic response model defines the output contract; Instructor performs
validation and bounded correction using it. Openlet does not reparse/revalidate
the successful result, add a JSON repair loop or independently retry it.
Boundary typing of a Langfuse config or gateway metadata is not another
validation pass over the LLM output.

## Sources and verification limits

- [Langfuse Prompt Config](https://langfuse.com/docs/prompt-management/features/config)
- [Langfuse versions and labels](https://langfuse.com/docs/prompt-management/features/prompt-version-control)
- [Native prompt cache](https://langfuse.com/docs/prompt-management/features/caching)
- [LiteLLM native alias resolution](https://docs.litellm.ai/docs/router/learn/names)
- [Reusable credentials and YAML/database ownership](https://docs.litellm.ai/docs/proxy/configs)
- [OpenAI-compatible endpoints](https://docs.litellm.ai/docs/providers/openai_compatible)
- [Streaming-cost configuration example](https://docs.litellm.ai/docs/self_hosted_coding_agents/moyai/setup)
- [LiteLLM response cache](https://docs.litellm.ai/docs/proxy/caching)

Probes used the isolated LiteLLM 1.109.1 environment and authorized synthetic
Vilao inputs. Langfuse Prompt Config/version/cache behavior was checked against
docs and installed SDK source, not published or exercised against Cloud. No
full application or parameter-matrix test, new DB, UI deployment or failover
provider was added. Temporary Proxy was stopped after the completed probes.

## Unresolved before implementation

The replacement per-agent effort selection contract needs agreement after the
old suffix format was withdrawn. The recommended task-config ownership is a
proposal for review, not permission to silently change existing product APIs.
