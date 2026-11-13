# Langfuse feature audit và nguồn research

Khảo sát 2026-11-13 cho [thiết kế đã chốt](plan.md), không phải báo cáo đã bật features. Người dùng chọn Langfuse Cloud Free/Hobby và Grafana Cloud Free cho demo 1–10 Openlet testers; local chỉ Alloy, centralized logs qua Cloud Loki. Observability gồm RAG/file processing đã chốt; evaluation là chủ đề thiết kế tiếp theo, chưa triển khai. Đối chiếu **toàn bộ 27 pages dưới Observability/Features và 15 pages dưới Prompt Management/Features** từ official [docs index](https://langfuse.com/llms-docs.txt), cùng SDK/integration/evaluation/administration/metrics/infra docs liên quan.

User URL là nhóm Prompt Management; phần Observability là nhóm riêng. Thiết kế hiệu chỉnh dùng native LangGraph cookbook từng lượt graph; agent tồn tại lâu không đồng nghĩa invocation chạy mãi. Một số docs còn nhắc v4 preview trong khi compatibility page đã ghi v4/current SDKs; API contract/versioning lấy từ current compatibility, native API reference và source thay vì ghép ví dụ cũ/mới.

## 1. Observability: 27/27 feature pages

“Dùng” là thuộc thiết kế đã chốt; “có điều kiện/hoãn” là đã đánh giá, không quên hoặc cần tự xây một cơ chế thay thế.

| Feature/source | Mức dùng | Áp dụng cụ thể và giới hạn |
|---|---|---|
| [Agent Graphs](https://langfuse.com/docs/observability/features/agent-graphs) | Dùng native | Execution tree mỗi graph invocation, không Box topology/full async DAG |
| [Agentic Access](https://langfuse.com/docs/observability/features/agentic-access) | Hoãn runtime agents | Operator có thể dùng native API/CLI sau này; không cấp platform-wide telemetry/admin tools cho mọi Leta/Leti |
| [Alerts](https://langfuse.com/docs/observability/features/alerts) | Có điều kiện, native | Hobby tối đa 2 alerts tại ngày research; cost/error/latency nếu cần, evaluation hoãn |
| [Comments](https://langfuse.com/docs/observability/features/comments) | Dùng native UI | Ghi nhận incident/review context trên observation/prompt; không build annotation app |
| [Corrections](https://langfuse.com/docs/observability/features/corrections) | Deferred | Cùng toàn bộ evaluation; chưa corrections/dataset workflow |
| [Environments](https://langfuse.com/docs/observability/features/environments) | Dùng | Environments deployments thực có; không evaluation environment bắt buộc hoặc access isolation |
| [Chart any table](https://langfuse.com/docs/observability/features/events-table-charts) | Dùng | Lưu filtered observation charts thành native dashboards; lưu ý aggregate chart không áp được mọi metadata/content/score filter như table |
| [Filter Search Bar](https://langfuse.com/docs/observability/features/filter-search-bar) | Dùng | Query theo prompt/model/level/agent/run metadata + time range; share exact filtered URL |
| [Full-Text Search](https://langfuse.com/docs/observability/features/full-text-search) | Dùng native capture | Tìm input/output thực đã capture, không thay LetFS search |
| [Log Levels](https://langfuse.com/docs/observability/features/log-levels) | Dùng | Unexpected error/provider failure khác conflict/denied/cancel; không biến mọi tool domain result thành ERROR |
| [Masking](https://langfuse.com/docs/observability/features/masking) | Chưa custom hook | Native capture cho demo; không credentials trong context; Tempo bỏ AI content |
| [MCP Tracing](https://langfuse.com/docs/observability/features/mcp-tracing) | Có điều kiện | Nếu có actual MCP clients/servers mới propagate native `_meta`; không dựng MCP để instrument native Openlet tools |
| [Metadata](https://langfuse.com/docs/observability/features/metadata) | Dùng tối thiểu | Existing workspace/agent/run/root/box IDs theo context, không transcript/checkpoint blob |
| [Multi-Modality](https://langfuse.com/docs/observability/features/multi-modality) | Native khi có | Không uploader toàn storage/custom media pipeline |
| [Observation Types](https://langfuse.com/docs/observability/features/observation-types) | Dùng native | Callback ghi graph/agent/chain/generation/tool/native retriever; Go SemanticSearch server span annotate retriever, query embedding theo provider call; rerank là span, không invented type hoặc eval score |
| [Pulse](https://langfuse.com/docs/observability/features/pulse) | Dùng | Outlier count/cost/p95 → narrow time range; native drill-down, không thêm Openlet charts |
| [Event Queuing/Batching](https://langfuse.com/docs/observability/features/queuing-batching) | Dùng | Native SDK batch, Python trực tiếp Cloud; shutdown flush, không mỗi token/call |
| [Releases & Versioning](https://langfuse.com/docs/observability/features/releases-and-versioning) | Dùng | Release=application commit; prompt link=numeric prompt version; không dùng SDK package version thay application release |
| [Sampling](https://langfuse.com/docs/observability/features/sampling) | Native defaults cho demo | Existing Openlet ratio 1.0, LF default 1.0, không content sampling/sampler redesign |
| [Sessions](https://langfuse.com/docs/observability/features/sessions) | Dùng | Existing agent/thread ID gom invocations; root/Leti riêng, không root/day |
| [Tags](https://langfuse.com/docs/observability/features/tags) | Dùng ít | Stable role/use-case tags, không IDs. Immutable tags không là trạng thái/outcome có thể sửa sau |
| [Token & Cost Tracking](https://langfuse.com/docs/observability/features/token-and-cost-tracking) | Dùng đầy đủ | Provider usage/cache/reasoning normalization/custom model prices; missing usage unknown, không estimate bằng text; không billing ledger |
| [Trace IDs & Distributed Tracing](https://langfuse.com/docs/observability/features/trace-ids-and-distributed-tracing) | Dùng | Native callback trace_context tạo TraceID mới/invocation; Tempo/LF cùng graph IDs, metadata nối Temporal |
| [Trace URLs](https://langfuse.com/docs/observability/features/url) | Dùng operators | Native trace URL với correct region/project, không public share mặc định hoặc trace token thay authorization |
| [User Feedback](https://langfuse.com/docs/observability/features/user-feedback) | Deferred | Cùng evaluation: chưa scores/annotation/corrections hoặc product feedback endpoints |
| [User Tracking](https://langfuse.com/docs/observability/features/users) | Có điều kiện | Chỉ exact human interaction; autonomous/mixed source không gán creator/owner làm user_id |
| [Web Callouts](https://langfuse.com/docs/observability/features/web-callouts) | Hoãn | Chưa có support/incident backend cần action; không dựng webhook để bật đủ feature. Read-only share/filter links đủ bắt đầu |

## 2. Prompt Management: 15/15 feature pages

| Feature/source | Mức dùng | Áp dụng cụ thể và giới hạn |
|---|---|---|
| [A/B Testing](https://langfuse.com/docs/prompt-management/features/a-b-testing) | Deferred | Chưa experiment assignment/traffic splitting |
| [Agentic Access](https://langfuse.com/docs/prompt-management/features/agentic-access) | Operator optional | Native prompt API/CLI để maintain; runtime Leta không tự edit/promote platform system prompts |
| [Caching](https://langfuse.com/docs/prompt-management/features/caching) | Dùng | Native RAM cache 60s, stale-while-revalidate; không Redis cache/invalidation bus |
| [Composability](https://langfuse.com/docs/prompt-management/features/composability) | Dùng | Root/Leti reference common **numeric version**; không dynamic label bên trong released outer prompt |
| [Config](https://langfuse.com/docs/prompt-management/features/config) | Không runtime authority mới | Arbitrary JSON không tự chạy. Giữ model catalog/tool schemas/response schema/timeouts ở owning code/config |
| [Folders](https://langfuse.com/docs/prompt-management/features/folders) | Dùng | `leta/*`, `letfs/*` native names, không custom namespace registry |
| [GitHub Integration](https://langfuse.com/docs/prompt-management/features/github-integration) | Deferred | LF edit/version/label đủ demo, không sync hoặc release snapshot |
| [Guaranteed Availability](https://langfuse.com/docs/prompt-management/features/guaranteed-availability) | Native cache, chưa fallback | Warm stale cache; cold miss/API down có thể fail invocation; không generated snapshot |
| [Link to Traces](https://langfuse.com/docs/prompt-management/features/link-to-traces) | Dùng | Exact PromptClient qua native propagation; compaction override scope, không graph metadata sai chỗ |
| [Message Placeholders](https://langfuse.com/docs/prompt-management/features/message-placeholders) | Khi full chat template cần | Native list-of-messages, không stringify role/tool call IDs; current system text blocks chưa cần chuyển graph state vào LF template |
| [n8n Node](https://langfuse.com/docs/prompt-management/features/n8n-node) | Không áp dụng | Openlet không chạy n8n; không thêm automation platform chỉ để fetch prompt |
| [Playground](https://langfuse.com/docs/prompt-management/features/playground) | Dùng | Thử prompt/model/schema/representative messages; không giả lập real Temporal/Mirage/Box side effects |
| [Prompt Version Control](https://langfuse.com/docs/prompt-management/features/prompt-version-control) | Dùng | Immutable versions, staging/production labels, rollback; protected labels phụ thuộc Cloud tier/add-on |
| [Variables](https://langfuse.com/docs/prompt-management/features/variables) | Dùng khi cần | Chỉ placeholders current renderer thật sự dùng; không nhét trace/framework/infra metadata vào model input |
| [Webhooks & Slack](https://langfuse.com/docs/prompt-management/features/webhooks-slack-integrations) | Optional thông báo | Có thể báo promotion nếu team cần; không webhook receiver/cache invalidation service mặc định |

## 3. Metrics, evaluation và administration liên quan

| Nhóm nguồn | Kết luận ảnh hưởng design |
|---|---|
| [Custom dashboards](https://langfuse.com/docs/metrics/features/custom-dashboards), [Metrics API](https://langfuse.com/docs/metrics/features/metrics-api) | Dùng native dashboards/export JSON; v2 metrics views observations/scores, không legacy traces view. Top-N/time bounds cho high-cardinality dimensions; không rebuild LF dashboard API wrapper |
| [Online eval](https://langfuse.com/docs/evaluation/get-started/online), [LLM judge](https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge) | Deferred, chưa online rules/LLM judge |
| [Code evaluators](https://langfuse.com/docs/evaluation/evaluation-methods/code-evaluators), [decision models](https://langfuse.com/docs/evaluation/evaluation-methods/decision-models) | Deferred, không hosted checks/evaluator service |
| [Annotation queues](https://langfuse.com/docs/evaluation/evaluation-methods/annotation-queues), [scores UI](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-ui), [scores SDK](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk) | Deferred, chưa scores/annotation/corrections |
| [Datasets](https://langfuse.com/docs/evaluation/experiments/datasets), [SDK experiments](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk), [comparison](https://langfuse.com/docs/evaluation/experiments/compare-experiments), [CI/CD](https://langfuse.com/docs/evaluation/experiments/experiments-ci-cd) | Deferred, chưa datasets/experiments/paid CI gates |
| [Compatibility](https://langfuse.com/docs/compatibility), [native OTLP](https://langfuse.com/integrations/native/opentelemetry), [existing OTel](https://langfuse.com/faq/all/existing-otel-setup) | Shared provider, native LF exporter trực tiếp Cloud; existing OTLP Alloy. Go dùng Cloud OTLP; demo ratio 1.0 |
| [Retention](https://langfuse.com/docs/administration/data-retention), [deletion](https://langfuse.com/docs/administration/data-deletion) | Cloud access window không là automatic deletion. Core/Hobby không native retention; Pro/Enterprise có. Datasets/linked observations có vòng đời khác nhau |
| [Billable units](https://langfuse.com/docs/administration/billable-units), [pricing](https://langfuse.com/pricing) | Hobby Free: 50k units/tháng, 30 ngày access, 2 dashboard seats; Openlet testers độc lập. Units = traces + observations + scores, đo Usage dashboard |
| [RBAC](https://langfuse.com/docs/administration/rbac), [LLM connections](https://langfuse.com/docs/administration/llm-connection) | Cloud project dành operators; environments không tenant isolation. Judge/Playground connections không thay provider secrets/model selection của Openlet |
| [Self-host Compose](https://langfuse.com/self-hosting/deployment/docker-compose), [Redis](https://langfuse.com/self-hosting/deployment/infrastructure/cache), [self-observability](https://langfuse.com/self-hosting/configuration/observability) | Đã so sánh trước lựa chọn Cloud: web/worker/PG/ClickHouse/Redis/S3, queue noeviction, official small deployment recommendation4CPU/16GiB; không thuộc target Cloud topology |

## 4. Nguồn hạ tầng

- [Alloy OTel pipeline](https://grafana.com/docs/alloy/latest/collect/opentelemetry-to-lgtm-stack/), [memory limiter](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.memory_limiter/), [filter](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.filter/), [transform](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.transform/).
- [Alloy OTLP HTTP exporter](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.exporter.otlphttp/): native queue/backoff và byte-sized batching; không custom payload batching.
- [Alloy probabilistic sampler](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.probabilistic_sampler/): TraceID decision, cùng seed cho cùng sampling tier; không buffer tới lúc whole workflow kết thúc.
- [Alloy Prometheus exporter](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.exporter.prometheus/), [remote write](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.remote_write/), [scrape](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.scrape/).
- Native [Postgres](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.postgres/), [Redis](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.redis/), [Unix](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.unix/), [cAdvisor](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.cadvisor/) components; không viết exporter service.
- [Prometheus storage](https://prometheus.io/docs/prometheus/latest/storage/): native time/size retention, WAL/head/compaction overhead, receiver flag `/api/v1/write`; sample byte estimate không là whole disk estimate.
- [Tempo deployment modes](https://grafana.com/docs/tempo/latest/reference-tempo-architecture/deployment-modes/), [configuration](https://grafana.com/docs/tempo/latest/configuration/), [long-running traces](https://grafana.com/docs/tempo/latest/troubleshooting/querying/long-running-traces/): v3 monolithic không Kafka, object storage recommended, native retention; long trace fragmentation/memory là vấn đề thật.
- [Temporal self-host monitoring](https://docs.temporal.io/self-hosted-guide/monitoring), [OTel span links](https://opentelemetry.io/docs/concepts/signals/traces/#span-links): native SDK/server metrics và bounded causal traces.

## 5. Source verification và phạm vi bằng chứng

Current Openlet source được khảo sát qua CodeGraph: Go/Python telemetry initialization/log formatting, ingest worker native Temporal metrics/interceptor và model describe/embed calls, LetFS semantic-search boundary. Đã đọc active Compose/Temporal template, architecture/operations docs, core native telemetry implementation report và cả core/Leta accepted plans. Không coi archived runtime là implementation target.

Downloaded public sources: [Langfuse Python 5.2.0](https://pypi.org/project/langfuse/5.2.0/), [LangChain 1.5.0](https://pypi.org/project/langchain/1.5.0/), [Temporal Python 1.35.0](https://pypi.org/project/temporalio/1.35.0/). Xem Langfuse client/resource manager/span processor/exporter/callback handler; native LangChain middleware/factory; Temporal OTel interceptor. Không install dependency vào repo hoặc đụng ignored project environment.

Các chi tiết đã kiểm bằng source:

- Existing provider được dùng chung; Langfuse processor có public exporter override/filter, không tự mirror vào exporter khác.
- Default filter giữ LF/gen_ai/known LLM scopes cho native Cloud exporter; existing ordinary OTLP processor riêng tới Alloy.
- Masking chạy export stage sau media; per-exporter mask không bảo vệ branch khác.
- Callback run maps có root-lifetime cleanup; `on_llm_new_token` chỉ set first completion timestamp, không observation mỗi token.
- Native CallbackHandler có public trace_context gán TraceID graph root; proposal mới không dùng model/tool tracing middleware.
- Callback attach observation vào OTel context; dùng native BaseCallbackHandler.run_inline để async tool/RPC kế thừa context, không subclass. Default LF filter thêm đúng SemanticSearch client; Go server span annotate retriever và embedding/rerank route qua Alloy. Parent filtering caveat đã đối chiếu official existing-OTel docs; đây là thiết kế chưa runtime proof.
- Current SemanticSearch đã có dense + BM25/RRF, SQL validity filter rồi rerank. Query embedding response có usage; rerank response struct chỉ đọc indices/scores, chưa claim rerank token/cost. LF chỉ capture final authorized retrieval hits; ingestion parse/upsert thuộc Grafana, enrichment/batch embeddings thuộc cả hai branches.
- Temporal native Continue-As-New tiếp tục truyền context; không giả CAN tự reset trace tree.
- Prompt cache stale-while-revalidate có native refresh dedup; cold fallback không được cache như fetched prompt.

Proof thuộc proposal cũ, không verification callback wiring mới. Offline Python3.14 + Langfuse5.2.0/in-memory exporter pass: shared provider/export processor; ordinary/AI spans xuất một lần; ba roots khác TraceID với links; session/usage propagation; standalone generation root thêm link bằng public API. Không server/provider/network ingestion proof.

Không đọc credentials, tạo Cloud resources, gửi feedback/webhooks/messages, publish prompt hoặc thực hiện deployment. Cần thực thi checks trong [system design](system.md#10-phạm-vi-files-và-verification-khi-implementation) trước tuyên bố production-ready.
