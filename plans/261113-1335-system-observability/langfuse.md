# Langfuse Cloud: tracing và prompt management

Integration được người dùng chốt toàn bộ 2026-11-13, gồm RAG/file processing: **Langfuse Cloud Hobby/Free + Grafana Cloud Free**, demo và 1–10 Openlet testers. Evaluation là chủ đề thiết kế tiếp theo, chưa triển khai. [Plan](plan.md), [system pipeline](system.md), [feature/source audit](feature-audit.md). Prompt content vẫn draft; chưa tạo Cloud project/key, publish prompt hoặc sửa runtime.

## 1. Phạm vi và cách hiểu run

Agent tồn tại lâu, mỗi lượt làm việc thường kết thúc khi graph hoàn thành rồi chờ lần đánh thức tiếp theo. Theo [LangGraph cookbook](https://langfuse.com/integrations/frameworks/langgraph): **một graph invocation = một trace**, model/tool calls là observations bên trong. Agent lifetime, SQL run, Temporal Workflow và graph invocation không phải cùng một thứ.

Không đổi inbox, checkpoint, heartbeat, Continue-As-New hoặc thêm soft slice vì telemetry. Future system message giải quyết inbox còn lại không thuộc scope. Langfuse không thay public history/AG-UI replay, permissions hoặc billing ledger.

## 2. Tích hợp Leta và Leti

1. Trước mỗi invocation, lấy role prompt và tạo native `langfuse.langchain.CallbackHandler`; đặt `handler.run_inline = True` để OTel context của callbacks truyền xuống async tool/RPC trong cùng execution context.
2. Gắn qua `config["callbacks"]` khi `graph.astream`/`ainvoke`; giữ checkpoint `configurable.thread_id` và runtime config.
3. Callback tự ghi graph/node/chain, generations, tools/retrievers thực thi qua LangChain. Custom graph nodes truyền native RunnableConfig xuống model/tool.
4. Graph return/error/cancel thì trace invocation kết thúc. Lượt sau trace mới/cùng session; crash có thể thiếu final observations.

Không viết model/tool tracing middleware, subclass callback, reset internal maps hoặc instrument provider lần nữa dưới LangChain callback. [Official integration](https://langfuse.com/integrations/frameworks/langchain).

### Temporal activity

Graph chạy trong activity đã có OTel context. Tạo callback với `trace_context={"trace_id": langfuse.create_trace_id()}` để invocation có trace riêng. Đây là public constructor option trong SDK Python 5.2.0 đã kiểm source. New random ID mỗi invocation/attempt; không deterministic TraceID theo agent/logical run.

Giữ native Temporal tracing/metrics/history. Existing workflow/run/attempt IDs giúp đối chiếu với graph trace; không hứa parent tree liền mạch suốt Temporal lifetime hoặc thêm SQL trace registry. [Trace IDs](https://langfuse.com/docs/observability/features/trace-ids-and-distributed-tracing).

### Session và metadata

| Field                                | Mapping                                           | Dùng để                                        |
| ------------------------------------ | ------------------------------------------------- | ---------------------------------------------- |
| `session_id`                         | Existing agent ID, cùng identity với graph thread | Gom các lượt làm việc/resume                   |
| Name                                 | `leta.agent` hoặc `leti.agent`                    | Phân biệt vai trò                              |
| `workspace_id`, `agent_id`, `run_id` | Existing domain IDs                               | Tìm đúng resource/lượt làm việc                |
| `root_id`, `box_id`                  | Khi có context đó                                 | Liên hệ root, Leti và Box                      |
| Temporal workflow/run/attempt        | Existing activity context                         | Đối chiếu execution/retry, không SQL field mới |
| `environment`, `release`             | Deployment environment/application commit         | Phân biệt deployments                          |
| `user_id`                            | Chỉ khi xác định đúng một human actor             | Không tự gán owner cho autonomous/mixed inbox  |

Root/Leti có traces/sessions riêng, lọc root/box metadata để xem liên quan. Không session theo ngày hoặc async multi-agent DAG. Message/tool-call IDs đã ở payload; không copy mọi ID vào mọi span.

```text
Session: agent R
  Trace A: leta.agent
    model → inbox_read → model → file_read → model → inbox_send → end
  Trace B: leta.agent                 (lần đánh thức sau)
    model → file_edit → model → inbox_send → end

Session: Leti L
  Trace C: leti.agent                 (làm việc độc lập trong Box)
    model → file_read → model → inbox_send → end
```

Đây là simplified view; native callback có thêm graph/node/chain observations. Agent Graphs thể hiện execution trong trace; Box membership vẫn từ domain API. `inbox_send` success nghĩa là admission thành công, không chứng minh recipient đã hoàn thành việc.

### Python minh họa

Chưa runtime implementation. `graph_input` đã được dựng bằng `prompt.compile()` cùng existing instructions/context; `existing_config` giữ checkpoint và runtime settings.

```python
from langfuse import get_client, propagate_attributes
from langfuse.langchain import CallbackHandler

langfuse = get_client()
prompt = langfuse.get_prompt("leta/root", label="production")
handler = CallbackHandler(
    trace_context={"trace_id": langfuse.create_trace_id()},
)
handler.run_inline = True
config = {
    **existing_config,
    "callbacks": [*existing_config.get("callbacks", []), handler],
    "run_name": "leta.agent",
}

with propagate_attributes(
    session_id=str(agent_id),
    metadata={"workspace_id": str(workspace_id), "agent_id": str(agent_id)},
    prompt=prompt,
):
    async for event in graph.astream(graph_input, config=config):
        ...  # Existing product stream processing.
```

Native exporter batch background; flush theo shutdown lifecycle, không mỗi token/model/tool.

## 3. Theo docs và phần riêng Openlet

| Phần                     | Chuẩn theo docs                                                   | Mapping/điều chỉnh Openlet                                                                   |
| ------------------------ | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Graph/model/tool tracing | CallbackHandler + RunnableConfig                                  | Callback mới mỗi invocation, native trace_context tách Temporal parent                       |
| Sessions/metadata        | `propagate_attributes`                                            | Agent ID làm session, existing workspace/root/box/run IDs                                    |
| Stream/usage/errors      | Native LangChain integration                                      | Bật provider stream usage khi cần; giữ tool outcome semantics                                |
| OTel coexistence         | Shared provider/native processors/exporters                       | Existing OTLP đi Alloy/Grafana Cloud Tempo, LF SDK trực tiếp Langfuse Cloud                  |
| Prompts                  | Fetch/compile/labels/version/cache/link                           | Business instructions và danh mục Openlet                                                    |
| Ingest Python            | Public native Langfuse observations trên Instructor/LiteLLM calls | Từng paid attempt có prompt/file/version/stage/cost, không duplicate                         |
| LetFS Go RAG             | Official OTel/OTLP ingestion và observation types                 | SemanticSearch server span làm retriever; embedding/rerank boundaries; chọn đúng RPC nối cây |

Không tracing framework, prompt registry/cache service, telemetry SQL/outbox hoặc evaluation hooks.

## 4. OTel, Alloy, Tempo và Prometheus

Giữ global TracerProvider và existing OTLP BatchSpanProcessor. Khởi tạo Langfuse sau core telemetry, dùng chung provider; SDK thêm processor/exporter mặc định **trực tiếp Cloud**. Hai nhánh có processor và exporter riêng; chỉ dùng chung provider/context/trace identity. Hai processors gửi hai backends là [cách docs hướng dẫn](https://langfuse.com/faq/all/existing-otel-setup).

Không override LF exporter hoặc thay exporter core. Default LF filter giữ LF/GenAI/known LLM scopes; dùng native `should_export_span` kết hợp `is_default_export_span` để thêm đúng gRPC client SemanticSearch nối cây RAG. Không export-all infrastructure spans. Existing OTLP chứa AI spans thì Alloy bỏ content trước Tempo. LF-only mask không bảo vệ exporter khác.

Demo dùng existing `trace_sample_ratio: 1.0` nhất quán trong Openlet SDK/Envoy; giữ ParentBased sampler/config, LF sample rate default 1.0. Không sampler redesign, content sampling 10% hoặc capture framework. Upstream đã drop span thì LF không khôi phục được; không cam kết không mất telemetry. Metrics không sampling.

Hai settings không là independent backend samplers: Python SDK 5.2.0 reuse existing provider/sampler, `sample_rate` chỉ cấu hình ratio sampler khi LF tự tạo provider. Chưa giảm sampling cho vài users/workspaces/agents. Nếu chỉ Tempo lớn thì sample riêng Alloy → Tempo, giữ common provider 1.0; LF quota xử lý khi có actual usage, không mặc định thêm filter/sampler framework. Core BatchSpanProcessor giữ AI timing spans, Alloy bỏ content; native LF processor giữ default AI filter và ngoại lệ SemanticSearch client nêu trên. Chi tiết trong [system sampling](system.md#4-sampling-batching-và-outage).

Native batch/timeout/retry; upload telemetry lỗi không rollback business effects. Queue hữu hạn có thể mất traces khi outage/crash; prompt API dependency trình bày tại mục 7.

## 5. Streaming và capture

Capture bình thường model messages/output, tool arguments/results, errors, usage và timings để debug đúng context. **Không observation/HTTP request LF mỗi token**: callback nhận chunks để theo dõi timing, generation hoàn tất có final output/usage và export theo native batch. Không Postgres writes từ tracing; browser vẫn SSE/Redis/history đã chốt.

Usage lấy native provider/LangChain metadata; bật stream usage theo adapter. Không estimate bằng tokenizer, cộng cached/reasoning tokens hai lần hoặc gọi missing usage là zero. [Token/cost](https://langfuse.com/docs/observability/features/token-and-cost-tracking).

Theo [LiteLLM/inference đã chốt 2026-11-14](../261111-2010-leta-rewrite/inference.md), LiteLLM tính giá mỗi deployment bằng native pricing/overrides, đơn vị USD/token; Langfuse nhận explicit request cost rồi aggregate. Một public model group có thể route qua Vilao/OpenAI/OpenRouter với giá khác nhau. Không price calculator/catalog trong backend hoặc sao chép price definitions sang LF. Streaming lấy final usage cost; nonstreaming/embedding lấy response-cost header. Ghi từng paid Instructor attempt trước khi response usage bị aggregate; không bật gateway→LF AI export lần hai. Reranker optional, không suy token/cost khi response không có dữ liệu. Migration này chưa implementation.

Không credentials/auth headers/checkpoint trong metadata. Model/file/tool content xuất hiện trong Cloud theo native capture, kể cả media integration hỗ trợ; demo dùng dữ liệu thử phù hợp. Keys server-side, dashboard operators; không tự uploader toàn storage. Tempo bỏ AI content.

Expected conflict/denied/not_found giữ domain results; không tạo exceptions chỉ để dashboard đỏ. Unexpected exceptions/provider failures là execution errors.

## 6. AI calls ngoài agent graph

| Owner                     | Tích hợp                                                                                 | Giữ đúng                                                                                      |
| ------------------------- | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Ingest enrichment         | `instructor.from_litellm` + public native LF generation APIs                             | Instructor validate/correction; từng paid attempt có usage/cost và đúng prompt version        |
| Ingest embeddings         | `litellm.aembedding` + public native LF embedding observation                            | Một observation/provider batch; explicit gateway cost, output count/dimensions, không vectors |
| LetFS Go query embedding  | Native OTel embedding span → Alloy filter riêng → official Cloud OTLP                    | Model/actual usage/batch size, không vectors hoặc Go wrapper tự chế                           |
| LetFS Go retrieval/rerank | Existing SemanticSearch server span + provider rerank span → Alloy → official Cloud OTLP | Retriever output chỉ gồm final authorized hits; rerank không giả generation hoặc usage        |
| Leta compaction           | Existing LangChain callback + scoped `propagate_attributes(prompt=compaction_prompt)`    | Link compaction prompt, không kế thừa nhầm role prompt                                        |

Python upload trực tiếp Cloud. Go dùng [official OTLP route](https://langfuse.com/integrations/native/opentelemetry), chọn đúng service và SemanticSearch retriever/query embedding/rerank spans; rerank dùng type span nên không lọc bằng embedding/generation type đơn thuần. Không forward Python LF spans lần nữa. Public SDK 5.2.0 embedding observation và per-attempt cost đã có [focused proof](../reports/research-261113-2324-litellm-sdk-capabilities.md); full migration chưa implementation.

Enrichment có AI trace riêng tại describe call khi cần tách Temporal parent bằng native trace_context; embeddings theo provider request. Không trace kéo dài suốt ingest nhiều file hoặc observation mỗi chunk.

### RAG online

Giữ [SemanticSearch hiện tại](../../apps/letfs/internal/storage/search.go): query embedding → Qdrant dense + BM25/RRF → SQL kiểm tra source/version/storage/live ancestry → rerank. Tool `file_semantic_search` đã được callback ghi tự động; không thêm LangChain retriever wrapper quanh Go RPC hoặc đổi tool schema.

```text
Agent invocation
├─ Model                                  generation
├─ file_semantic_search                   tool, native callback
│  └─ gRPC client SemanticSearch          span, native OTel
│     └─ SemanticSearch                   retriever, existing server span
│        ├─ query_embedding               embedding
│        └─ rerank                        span
└─ Model                                  generation, actual tool context
```

Sơ đồ bỏ các graph/node/chain observations trung gian. Tận dụng server span bằng `langfuse.observation.type="retriever"`; thêm provider spans ngay tại query embedding/rerank calls, dùng context trả về để native downstream HTTP spans vẫn nối đúng ở Tempo. Không instrument provider hai lần.

| Observation              | Input/output và metadata cần                                                                                                                                           |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Native tool              | Query/paths và output đúng như agent nhận                                                                                                                              |
| SemanticSearch retriever | Query, storage/root, top_k; output là final hits thực trả gồm file ID/snippet/score theo thứ tự; metadata đếm Qdrant candidates, SQL-valid candidates và returned hits |
| Query embedding          | Model/query/actual provider usage/dimensions, không vectors                                                                                                            |
| Rerank                   | Query, model trong metadata, candidate count; output selected indices/scores, native latency/status/error; không lặp toàn bộ candidate text                            |
| Model sau search         | Messages thực gửi provider, output/usage; không dựng thêm bản sao RAG answer riêng                                                                                     |

Không capture nội dung Qdrant candidates bị SQL loại, không observation từng hit/chunk. Mỗi RPC tìm trong một scope có retrieval observation tương ứng; tool nhiều paths giữ thứ tự/ranking từng scope đã chốt, không cross-mount fusion mới. Kết quả rỗng hợp lệ không là exception. Rerank relevance score là output xếp hạng, không phải Langfuse evaluation score. Current response struct chưa đọc rerank usage, nên chưa ghi token/cost hoặc suy từ document count.

W3C context đi qua native gRPC instrumentation. Callback dùng thuộc tính native [run_inline](https://reference.langchain.com/python/langchain-core/callbacks/base/BaseCallbackHandler/run_inline); SDK callback attach context đã kiểm source. Python LF processor giữ default filter cộng đúng client SemanticSearch; Go Alloy branch giữ existing server span đã annotate và embedding/rerank. Giữ RPC client parent để cây LF không bị đứt khi lọc infrastructure; không custom header, baggage/trace registry, parent rewriting hoặc callback subclass. [Official filtering caveat](https://langfuse.com/faq/all/existing-otel-setup).

### File processing

Grafana theo dõi toàn bộ pipeline; Langfuse đi sâu vào AI calls. Cùng một model call được instrument một lần rồi export hai nhánh theo owning integration, không gọi provider hai lần.

| Processing step                                  | Grafana/Tempo/Mimir/Loki                                                   | Langfuse                                                                    |
| ------------------------------------------------ | -------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| Chờ worker, Temporal activities/retries/failures | Native queue/execution metrics, spans/logs; chi tiết history ở Temporal UI | Không mirror orchestration                                                  |
| Parse/export text/artifacts                      | Stage duration/errors, CPU/RAM, subprocess failure                         | Không                                                                       |
| Enrichment                                       | Duration/status/errors, không AI content                                   | Prompt/version/input/output/model/actual usage/cost                         |
| Batch embedding                                  | Duration/status/errors, không AI content                                   | Input batch/model/actual usage/cost, output count/dimensions; không vectors |
| Qdrant upsert, commit processing status          | Stage duration/errors, dependency spans/logs                               | Không                                                                       |

Đối chiếu bằng existing file_id/source_version trong selected spans/logs/LF metadata và TraceID khi cùng trace; không thêm IDs vào metric/Loki labels hoặc ép các Temporal activities thành một immortal trace. LetFS processing state vẫn là nguồn trạng thái file trong product API/UI. Parse/upsert không thành LF observations chỉ để thấy toàn pipeline ở cả hai backends.

## 7. Prompt management

| Nội dung                                                  | Authority                                                                  |
| --------------------------------------------------------- | -------------------------------------------------------------------------- |
| Common concepts/business rules                            | LF text prompt `leta/common`                                               |
| Root/Leti instructions                                    | `leta/root`, `leta/leti`                                                   |
| Compaction/enrichment                                     | `leta/compaction`, `letfs/enrichment`                                      |
| Agent mission/user instructions                           | Existing SQL/profile                                                       |
| Tool names/descriptions/schemas, response schemas         | Owning code                                                                |
| Task model/effort/temperature/top_p/top_k/output defaults | LF Prompt Config, version cùng prompt; chỉ fields cần dùng                 |
| Model groups/deployments/capabilities/prices/retry        | LiteLLM theo [inference đã chốt](../261111-2010-leta-rewrite/inference.md) |
| Explicit agent selection/inheritance và hard limits       | Existing product state/application budgets                                 |
| Summary/tail/inbox                                        | Existing checkpoint/domain runtime                                         |

[System drafts](../261111-2010-leta-rewrite/prompting.md) vẫn cần review, chưa publish production. Không prompt mỗi user/agent.

**Runtime:** trước mỗi graph invocation, `get_prompt(name, label="production")` → `compile()` → SystemMessage theo accepted composition. Giữ PromptClient suốt invocation, không fetch mỗi LLM/tool. `propagate_attributes(prompt=prompt)` link generations đúng version; compaction override scope riêng. Không gắn `langfuse_prompt` bừa lên graph/model metadata; PromptTemplate metadata là phương pháp khác, chưa cần thêm PromptTemplate chỉ để link. [Linking](https://langfuse.com/docs/prompt-management/features/link-to-traces).

**Cache:** native RAM default **60s**; fresh hit không network, stale hit trả cũ + background refresh, cold miss fetch API. Invocation giữ version đã lấy, lượt sau nhận version mới khi cache refresh. Compaction/enrichment fetch tại owning invocation. Không Redis prompt cache/invalidation bus hoặc release snapshot pipeline. [Caching](https://langfuse.com/docs/prompt-management/features/caching).

**Availability:** demo chưa thêm cold-start fallback. Process mới/cache rỗng + API down thì model invocation báo lỗi theo existing handling/retry; không prompt rỗng hoặc silently latest. Warm cache giúp khi API chập chờn. Native `fallback=` có sẵn nếu sau này cần; chưa thêm prompt copy hoặc artifact generation. Đây là giới hạn demo.

**Version/rollback:** edit tạo immutable version cùng config → thử thực tế qua Openlet → chuyển production label → runtime nhận qua cache. `latest` chỉ cho development; staging khi có deployment tương ứng. Root/Leti native composition pin common numeric version, ví dụ `@@@langfusePrompt:name=leta/common|version=7@@@`; common đổi thì outer role version mới. Không fetch/nối common lần nữa hoặc tự inherit config của common. Rollback chuyển label về version trước, không reset checkpoint/Temporal.

Folders/labels/composition/cache/link/config đều native. **Playground hoãn theo chốt cuối**; không cần public local LiteLLM endpoint hoặc Langfuse LLM connection để managed prompts hoạt động. Task model/parameter config đã chốt; không đưa tool/output contracts vào LF. Hoãn A/B assignment, GitHub sync, protected-label workflow, webhooks/Slack và evaluation. Agentic CLI/API chỉ cho authorized operator, runtime agent không sửa/promote platform prompts. [Plan triển khai hợp nhất](../261114-0035-inference-prompts-compaction/plan.md) ghi chi tiết và acceptance; prompt wording vẫn draft.

## 8. Free và features dùng ngay

[Hobby pricing tại ngày research](https://langfuse.com/pricing): **50,000 units/tháng, 30 ngày data access, 2 dashboard users**. Dashboard seats không giới hạn Openlet users; 1–10 testers không cần mỗi người một LF account. Một project, environments theo deployments thực có; không project/workspace provisioning. Grafana Cloud Free đã chọn cho hệ thống; local chỉ Alloy, logs lên Cloud Loki, không local monitoring backends. Prompt fetching unlimited theo pricing; model inference vẫn dùng provider riêng.

Units = traces + observations + scores. Callback có graph/node/chain observations ngoài model/tools; không suy quota chỉ từ LLM calls. Dùng native Usage dashboard đo demo rồi quyết định nếu gần quota, chưa quota controller/purge daemon/nâng tier. [Units](https://langfuse.com/docs/administration/billable-units).

Dùng trace tree/Agent Graphs, sessions, input/output/tools/errors/latency, token/cache/cost, search/filter, prompt metrics/version links và Usage. Playground hoãn. Tags vài role/use-case, comments khi debug. Không dựng lại UI hoặc poll Metrics API vào Prometheus. Hobby có feature limits.

30 ngày access không là cam kết tự xóa đúng ngày 30. Không Cloud cleanup trong workspace deletion; history/inbox có lifecycle riêng. [Retention](https://langfuse.com/docs/administration/data-retention).

## 9. Evaluation và verification

**Observability đã chốt, không còn decision blocker trước evaluation.** Evaluation là chủ đề thiết kế tiếp theo; chưa datasets/experiments, annotation queues/scores, LLM judge, feedback endpoints hoặc paid CI checks. Audit giữ research tham khảo; prompt cases không biến thành suite mới.

Implementation kiểm focused integration: graph hai models/một tool trong một trace; lần sau trace mới/cùng session; Leti độc lập; stream usage/no token observations; prompt/compaction đúng version; rollback/cache; provider không duplicate; Tempo không content. Thêm SemanticSearch journey xác nhận async callback → RPC client → Go retriever → embedding/rerank nối đúng, chỉ final authorized hits được capture và không duplicate usage. Direct ingest/Go calls kiểm theo actual pinned provider/version. Không test từng LF feature.

Lượt hiệu chỉnh chỉ sửa docs/proposal, đã đối chiếu official docs/public SDK source. Chưa graph/provider/Cloud ingestion, credentials/quota hoặc deployment stack. Offline proof cũ không là verification callback wiring mới.
