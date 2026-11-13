# Observability toàn Openlet: thiết kế đã chốt

Đang implementation cùng Leta. Collector/Cloud config, native SDK instrumentation, RAG/ingest observations và managed prompts đã có code; evaluation hoãn. Xem [execution record](../261111-2010-leta-rewrite/execution.md) cho checks và acceptance còn lại; chưa deploy Cloud.

Người dùng chốt toàn bộ thiết kế observability 2026-11-13, gồm RAG và file processing: **Langfuse Cloud Hobby/Free**, demo và 1–10 Openlet testers, tích hợp theo docs chuẩn; evaluation là chủ đề thiết kế tiếp theo, chưa triển khai. Agent tồn tại lâu nhưng graph invocation thường hoàn thành rồi dừng/chờ công việc mới. Không dùng skill/subagent hoặc thay domain/Temporal/schema đã chốt. Người dùng đã chốt Grafana Cloud Free: local chỉ Alloy, Cloud Mimir/Tempo/Loki/Grafana thay toàn bộ monitoring backends self-host.

## Kết quả cần đạt

Platform, LetFS, ingest, Leta/Leti dùng OTel → Alloy → Grafana Cloud Mimir/Tempo/Loki; Cloud Langfuse cho AI tracing/prompt management. Mỗi graph invocation có trace với model/tool observations tự động. Giữ inbox/checkpoint/streaming và native Temporal instrumentation.

Scope: topology, native instrumentation/correlation, metrics/dashboard, prompt/version/cache và Free usage. Không telemetry service, custom exporter/queue, trace registry, immortal-agent telemetry architecture, capture sampling framework hoặc prompt release snapshot pipeline. Future system message giải quyết inbox còn lại không thuộc scope.

## Tài liệu và trạng thái

| Phần                  | Trạng thái                                                                              | Chi tiết                                                                                                                     |
| --------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Native core telemetry | Baseline có local proof                                                                 | [Core](../261111-1727-platform-letfs-rewrite/telemetry.md), [evidence](../reports/implementation-261112-native-telemetry.md) |
| Hosting/tier          | Người dùng chọn Grafana Cloud Free + Langfuse Hobby                                     | Local chỉ Alloy, native container logs lên Cloud Loki; không backend self-host                                               |
| Monitoring            | Đã có config/dashboard assets; local Alloy validate/routing proof pass, Cloud chưa kiểm | [System design](system.md)                                                                                                   |
| Tracing/prompts       | Integration có native runtime export proof; prompt content vẫn draft/chưa publish       | [Langfuse design](langfuse.md)                                                                                               |
| LiteLLM/inference     | Chốt 2026-11-14, chưa migrate implementation                                            | [Shared groups, Prompt Config và per-deployment cost](../261111-2010-leta-rewrite/inference.md)                              |
| RAG/file processing   | Đã có implementation và local export/routing proof                                      | [Retrieval và ingestion](langfuse.md#rag-online)                                                                             |
| Feature research      | 27+15 pages đã nghiên cứu                                                               | [Audit](feature-audit.md), cập nhật scope mới                                                                                |
| Evaluation            | Hoãn theo quyết định người dùng                                                         | Không thuộc scope implementation hai plan hiện tại                                                                           |
| Runtime/deploy        | Shared API E2E 5/5 pass; Cloud/deploy acceptance còn lại                                | [Execution](../261111-2010-leta-rewrite/execution.md)                                                                        |

## Thiết kế đã chốt

1. Giữ core provider/exporter và native Temporal tracing. Chạy Alloy, backend dùng Grafana Cloud Mimir/Tempo/Loki/Grafana; demo dùng existing sample ratio 1.0, không sampler redesign.
2. Python LF SDK dùng chung provider/default exporter trực tiếp Cloud; existing OTLP đi Alloy/Tempo. Giữ default AI filter, thêm đúng gRPC client SemanticSearch để nối cây RAG. Go SemanticSearch/embedding/rerank dùng official OTLP qua Alloy, không forward Python LF spans lần nữa hoặc export toàn bộ infrastructure vào LF.
3. Leta/Leti dùng CallbackHandler mỗi invocation; native trace_context tách Temporal parent, model/tools cùng trace. Bật native run_inline để context truyền xuống RPC trong async tools; không subclass callback. Session existing agent ID, không per-call standalone traces hoặc UTC-day grouping.
4. Capture/usage bình thường cho demo, native batch/export, không per-token observations. Tempo bỏ AI content. Theo dõi Usage dashboard thay vì quota/capture controller.
5. Platform prompts và task model/parameters ở LF Prompt Config; agent instructions SQL, tools/output contracts code. LiteLLM sở hữu model groups/deployments/capabilities/prices/retry theo [inference đã chốt](../261111-2010-leta-rewrite/inference.md); không catalog/pricing copy trong Openlet/LF. Role prompt/config resolve một lần/invocation, native cache 60s/labels/version/link; rollback label. Chưa cold fallback machinery.
6. Dùng native traces/Agent Graphs/sessions/search/token-cost/prompt metrics/Playground. Evaluation chưa có thiết kế/implementation, không thuộc scope observability.
7. RAG giữ search hiện tại; tận dụng SemanticSearch server span làm retriever, embedding có observation riêng, rerank là span với model/counts/indices/scores, chưa token/cost khi provider response chưa được đọc usage. Không observation từng hit hoặc LangChain retriever wrapper quanh RPC.
8. Grafana theo dõi toàn bộ file processing; LF quan sát enrichment/batch embedding. Đối chiếu bằng file_id/source_version và TraceID khi cùng trace; LetFS processing state vẫn là nguồn trạng thái sản phẩm.

## Thứ tự triển khai

| Bước                 | Phạm vi                                                                 | Acceptance                                                                                                                   |
| -------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| 1. Monitoring        | Alloy, Cloud destinations/log pipeline, native dependency scrapes       | Config validation/core journey có metrics/traces/logs; telemetry outage không fail business effects                          |
| 2. LF + Leta         | Shared provider/default exporter/callback/sessions                      | Model/tool tree trong invocation; lần sau trace mới/cùng session; không duplicate                                            |
| 3. AI calls khác/RAG | Ingest wrapper, Go retrieval/embedding/rerank OTLP, compaction callback | RAG tree nối qua SemanticSearch RPC, usage không duplicate; processing stages ở Grafana, AI detail ở LF; Tempo không content |
| 4. Prompts/demo      | Approved prompts/cache/labels/link/rollback/Usage                       | Exact versions, không per-token upload, đo demo units                                                                        |

Dependencies: [Leta](../261111-2010-leta-rewrite/plan.md), [core](../261111-1727-platform-letfs-rewrite/plan.md). Không thêm domain tables/queues/activities. [Prompt content](../261111-2010-leta-rewrite/prompting.md) vẫn draft cần review.

## Bằng chứng và giới hạn

Research đọc official docs, 27 observability/15 prompt-management features, current source qua CodeGraph, public SDKs LF 5.2.0/LangChain 1.5.0/Temporal Python 1.35.0. Hiệu chỉnh kiểm lại native callback/shared OTel/prompt propagation/cache/Free pricing; thay proposal per-call traces/capture sampling/snapshot/evaluation trước đó.

Offline proof cũ chỉ xác nhận vài primitives, không là proof integration mới. Graph/provider streaming và native Langfuse export đã có local runtime proof; chưa Cloud ingestion/auth, backend deploy, overhead hoặc quota thực đo. Thiết kế đã duyệt và đã có implementation; Cloud acceptance vẫn cần deployment thật.

Free có 50k units/tháng, 30 ngày access, 2 dashboard seats; Openlet testers là khái niệm khác. Cold process/cache rỗng khi prompt API down chưa chạy được model call; chấp nhận cho demo, chưa fallback release system.

Chốt deployment: [pipeline SDK/processor/exporter](system.md#3-shared-provider-native-exporters) giữ nguyên; [Grafana Cloud Free + Alloy](system.md#11-quyết-định-triển-khai-cloud-đã-chốt) thay baseline self-host. Cloud metrics/traces/logs retention 14 ngày; không local Prometheus/Tempo/Grafana/Loki hoặc S3 observability.

Không còn quyết định kiến trúc observability cần chốt trước khi bàn evaluation. Endpoints/credentials/region, alert contact points/default thresholds và số đo Cloud usage là công việc deployment/tuning. RAG propagation, stream usage, duplicate/content filtering và prompt-cache behavior cần focused integration proof khi triển khai; không phải một vòng brainstorm mới. Nội dung system prompts vẫn draft độc lập với việc đã duyệt integration.
