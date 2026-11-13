# LiteLLM và cấu hình inference — đã chốt

Người dùng chốt 2026-11-14. Đây là target design cho Leta/Leti, ingest và
LetFS, **chưa phải implementation hoàn tất**. Thay các proposal catalog riêng,
model reference có effort suffix và sao chép price definitions sang Langfuse.
Không dùng skills/subagents; evaluation tiếp tục hoãn.

[Plan triển khai hợp nhất](../261114-0035-inference-prompts-compaction/plan.md)
ghi retrospective, thiết kế chi tiết, file map/commit sequence và các gate còn
chưa chốt. Prompt-management release thử qua Openlet; Playground hoãn, không
cần public gateway hoặc Langfuse LLM connection ở lượt này.

## 1. Ownership

| Nội dung                                                                                                | Nguồn duy nhất                                                        |
| ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| Prompt và task default model, reasoning effort, temperature, top_p/top_k, output budget khi cần         | Langfuse Prompt Config, version cùng prompt                           |
| Model groups/deployments, Leta-supported subset, upstream URL/credentials, capabilities/limits, pricing | LiteLLM                                                               |
| Transport retry/backoff và routing giữa deployments                                                     | Native LiteLLM Proxy                                                  |
| Explicit agent selection và Root/Leti inheritance                                                       | Existing Openlet product state; model là opaque group name            |
| Tools, typed output contracts, permissions và hard execution/context budgets                            | Owning application code/config                                        |
| Embedding model/dimensions gắn với index                                                                | Gateway selection phối hợp index configuration; đổi model cần reindex |

Ví dụ Langfuse Prompt Config:

```json
{
  "model": "openai/gpt-6.1-sol",
  "reasoning_effort": "low"
}
```

Chỉ khai báo parameters thực sự cần và model hỗ trợ; không thêm null fields.
App đọc config rồi truyền vào client bình thường; Langfuse không tự thực thi
config. Không cấu hình lại cùng task defaults trong LiteLLM/Openlet YAML.
Compaction dùng model đang chạy, không có model/default catalog riêng.
Config LF phẳng, không `default` wrapper. Root dùng các giá trị này khi chưa có
explicit DB selection; giữ hai fields `model_id` và `reasoning_effort`, DB pair
ưu tiên và Leti tiếp tục root inheritance. Không parse effort suffix.

## 2. Một model group, nhiều provider

Langfuse và Leta chọn **loại model**, không chọn nhà cung cấp request đó.
`openai/gpt-6.1-sol` là public group name: phần `openai` biểu thị hãng tạo model,
không buộc request đi OpenAI chính hãng. Không backend parser cho provider hoặc
`:reasoning-effort`; effort là native inference parameter.

Ba deployments khai báo cùng `model_name`:

```yaml
credential_list:
  - credential_name: vilao
    credential_values:
      api_base: os.environ/OPENAI_BASE_URL
      api_key: os.environ/OPENAI_API_KEY
    credential_info:
      custom_llm_provider: openai

model_list:
  - model_name: openai/gpt-6.1-sol
    litellm_params:
      model: openai/gpt-6.1-sol
      litellm_credential_name: vilao
    model_info:
      access_groups: [leta]
      supports_response_schema: false
      supports_function_calling: true

  - model_name: openai/gpt-6.1-sol
    litellm_params:
      model: openai/gpt-6.1-sol
      api_key: os.environ/OPENAI_OFFICIAL_API_KEY
    model_info:
      access_groups: [leta]

  - model_name: openai/gpt-6.1-sol
    litellm_params:
      model: openrouter/openai/gpt-6.1-sol
      api_key: os.environ/OPENROUTER_API_KEY
    model_info:
      access_groups: [leta]
```

Đây là native model group, không phải ba lựa chọn public riêng. Thêm một group
khác bằng LiteLLM config; model-list API Leta chiếu metadata thành một item mỗi
group thuộc access group `leta`. Không list cứng trong backend/config ứng dụng.

`litellm_params.model` mới là native adapter/upstream ID. Vilao dùng OpenAI-compatible
adapter và named credential có sẵn, không custom provider class hoặc SDK fork.
Tên upstream Vilao tạm không có slash theo khả năng endpoint hiện tại.

Native gateway routing quyết định deployment; không tự chốt ưu tiên Vilao,
chia đều traffic hoặc chuyển sang loại model khác từ ví dụ này. Mỗi deployment
có giá/capabilities thực riêng. Không suy group hỗ trợ schema/effort từ một
deployment tốt nhất rồi gửi request đó sang deployment không hỗ trợ.

## 3. Deploy và đọc metadata

- Một standard stable LiteLLM Proxy trong Compose, một worker; chưa dùng Rust RC.
- Cấu hình tại `infra/config/litellm.yaml`, mount read-only; credentials trong
  root `.env`. App chỉ giữ gateway URL/key và product/runtime settings.
- Ban đầu không DB/Redis riêng cho LiteLLM. Native UI-managed models/credentials,
  virtual keys hoặc durable spend/budgets cần DB; khi cần dùng DB/user riêng trên
  PostgreSQL hiện có, không tự thêm ở lượt này.
- `/model/info` là nguồn metadata deployments/capabilities; snapshot trong process,
  TTL 60 giây, refresh theo nhu cầu. Không Redis, background polling hoặc gọi mỗi
  model token/tool. Không cần gọi thêm `/v1/models` để lấy cùng catalog.
- Không dùng local capability helpers cho arbitrary proxy aliases: live probe
  đã thấy missing/false facts. Proxy metadata/overrides mới là nguồn đúng.

Langfuse giữ native prompt/config cache 60 giây. Đổi provider trong cùng group
không cần sửa prompt. Đổi task model/parameters bằng prompt version + label,
không cần sửa Openlet YAML. App không thêm `default_for`, gateway task aliases
hoặc một cơ chế default thứ hai cạnh Langfuse.

## 4. Clients, retries và structured output

| Caller                  | Client                                      |
| ----------------------- | ------------------------------------------- |
| Leta/LangGraph          | `langchain_litellm.ChatLiteLLM`             |
| Ingest structured calls | `instructor.from_litellm`, async completion |
| Ingest embedding        | `litellm.aembedding`                        |
| Go LetFS embedding      | Existing official OpenAI Go SDK qua Proxy   |
| Go rerank khi bật       | HTTP tới native Proxy rerank endpoint       |

Không app `Router`/`ChatLiteLLMRouter` cạnh Proxy. App SDK transport retries = 0;
Proxy sở hữu bounded retry/backoff/fallback. Temporal durable recovery giữ riêng.
Instructor sở hữu bounded validation feedback; không output validator/JSON repair
hoặc correction loop thứ hai trong Openlet.

YAML `models.enrichment.output_mode: tools | json_schema | text` chọn một mode,
tương ứng Instructor `TOOLS | JSON_SCHEMA | MD_JSON`. Vilao dùng `tools`.
Backend không biết deployment được group chọn trước request; không autodetect,
mode downgrade chain hoặc capability intersection/filter. Instructor trả object
đã validate hoặc báo lỗi sau bounded correction; không validation thứ hai.
Giữ `drop_params: false`, không silently drop schema/parameters được yêu cầu.
Routing/fallback phải tương thích tools/schema/context của request. Embedding
không fallback sang model khác trên index hiện có. Reranker optional; tắt thì
giữ dense + BM25/RRF retrieval đang có.

## 5. Cost và observability

LiteLLM tính cost; Langfuse nhận explicit actual request cost và aggregate.
Mỗi deployment có thể override giá bằng native `model_info`, kể cả cùng
`model_name`: `input_cost_per_token`, `output_cost_per_token`,
`cache_read_input_token_cost` khi applicable. Đơn vị USD/token; không nhét chữ
USD vào field tự chế, không lấy giá OpenAI chính hãng áp cho Vilao.
Giá Vilao thật chưa được xác minh; ví dụ research không phải supplier rates.

Không backend price calculator/fetch OpenRouter prices hoặc sync price definitions
sang Langfuse. Tách price theo deployment làm cost vẫn đúng khi gateway đổi provider.

Streaming bật `include_cost_in_streaming_usage: true`, request
`stream_options.include_usage: true`: final usage chunk có `usage.cost`;
ChatLiteLLM giữ `response_metadata.response_cost`. Nonstreaming/embedding đọc
`x-litellm-response-cost`. Interrupted stream thiếu final cost là unknown, không zero.

Leta dùng native Langfuse LangChain callback; small inline cost callback chạy
trước nó để đặt explicit total cost qua public API. Ingest ghi từng completion
usage/cost trước khi trả response cho Instructor, gồm các correction attempts;
embedding giữ đúng observation type. Không cộng response usage đã bị Instructor
aggregate lần nữa. Không bật gateway export AI observations sang Langfuse lần hai;
gateway operational telemetry đi Alloy/Grafana.
Cost coverage gồm mọi LLM, embedding và reranker calls: enrichment/batch embedding
của file processing, query embedding/optional rerank của semantic search, agent
và compaction. Reranker giữ native billed units/pricing; missing usage/cost là
unknown, không zero. Chi tiết attribution/Cloud proof ở plan hợp nhất.

## 6. Phạm vi implementation và kiểm chứng

Xóa catalog/providers/price arithmetic/effort parser/transport retry cũ sau khi
migrate callers. Nối metadata listing/selection, Prompt Config, typed SDK paths,
cost propagation và gateway Compose/Alloy/env/docs. Không compatibility/deadcode,
không tự thêm field API/SQL theo naming proposal đã bỏ. Pyright strict cho
Leta, ingest và SDK; tests chỉ essential behavior và shared integration.

Cache-friendly compaction giữ accepted stable system prefix, native messages/tools,
summary + bounded tail/checkpoint; không model riêng hoặc flatten XML. Xem
[prompt composition](prompting.md#3-cấu-trúc-model-request-đề-xuất) và
[runtime acceptance](execution.md#acceptance-còn-lại): design đã chốt nhưng code
compaction hiện tại vẫn cần sửa/kiểm actual wire prefix/cache usage.

Research đã có real Vilao chat/tool/stream/embedding, native metadata/shared
credentials/aliases và per-request cost proof. Chưa có authenticated calls cả
OpenAI/OpenRouter trong cùng group, full LangGraph/Go/Cloud migration hoặc
heterogeneous group capability/routing proof. Không suy test aliases là test
cả ba upstreams. Gateway outage vẫn ảnh hưởng inference toàn hệ thống.

Nguồn/bằng chứng: [gateway research](../reports/research-261113-2251-litellm-gateway.md),
[SDK/cost probes](../reports/research-261113-2324-litellm-sdk-capabilities.md),
[configuration/cache/stream probes](../reports/research-261113-2345-inference-configuration-ownership.md),
[native model groups](https://docs.litellm.ai/docs/proxy/load_balancing),
[custom pricing](https://docs.litellm.ai/docs/proxy/custom_pricing),
[Langfuse config](https://langfuse.com/docs/prompt-management/features/config).
