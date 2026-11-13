# Telemetry native

Cập nhật 2026-11-12. Instrumentation Platform/LetFS/ingest và Envoy đã triển khai; chưa chọn hoặc dựng monitoring backend. [Plan](plan.md), [configuration](configuration.md) và [HTTP contract](http-json.md) là các owning surfaces liên quan.

Cập nhật research 2026-11-13: stack OTel/Alloy + Grafana Cloud Free Mimir/Tempo/Loki/Grafana và Langfuse Cloud Free/demo 1–10 testers; local chỉ Alloy. [Thiết kế đã chốt](../261113-1335-system-observability/plan.md) giữ native core/provider/exporter; LF default exporter trực tiếp Cloud, graph callback chuẩn, native prompts. Evaluation hoãn; chưa sửa baseline source/config hoặc deploy backend. Nội dung bên dưới vẫn là implementation baseline.

## 1. Kết quả và giới hạn

Instrumentation dùng OpenTelemetry API/SDK và integration native, xuất được dữ liệu sang monitoring backend sau này mà không sửa business handlers. Không tạo telemetry service, event bus, exporter/retry framework hoặc database telemetry của Openlet. Chưa triển khai Grafana/Prometheus/Tempo/Loki, dashboard, alert rules hoặc vendor SDK.

Ba signals có một đường đi rõ ràng:

```text
Application traces/metrics -- OTLP/gRPC --> Collector --> backend được chọn sau
Application/Envoy logs ---- JSON stdout --> runtime log collection --> Collector/backend
Infrastructure metrics --- native private endpoints --> scraper/Collector --> backend
```

Collector là optional infrastructure, không nằm trong business request path. Khi chưa cấu hình endpoint, ứng dụng vẫn có JSON logs và chạy không cần Collector. OTLP endpoint dùng mạng private; nếu sau này đi ngoài trust boundary thì dùng TLS/auth native của exporter/Collector.

Leta là optional integration: trace context đi qua các business RPC khi integration được bật. Core startup/readiness và permission hot path không chờ Leta, không probe queue/worker nội bộ của nó hoặc gộp readiness Leta vào health core. Async owning cleanup được phép theo architecture hiện tại; concrete API/transport Leta tiếp tục hoãn. Danh sách service.name dưới đây không là danh sách runtime dependencies.

## 2. Identity và propagation

Resource attributes dùng semantic conventions: service.name, service.version, service.instance.id và deployment.environment.name. Go lấy version từ module/VCS metadata khi có, fallback `dev`; Python dùng installed SDK package version. Go/Python sinh UUID cho process instance. Standard `OTEL_RESOURCE_ATTRIBUTES` có thể cung cấp version từ release metadata, được renderer truyền vào container; Python và Go dùng cùng các resource values trong logs. Envoy có service.name/environment và native telemetry.sdk.version; environment resource detector nhận các resource attributes bổ sung khi deploy. Không tạo database identity hoặc thêm field vào business schema.

| Process | service.name |
|---|---|
| Platform API/worker | openlet-platform |
| LetFS API/worker | openlet-letfs |
| Ingest CPU | openlet-ingest-cpu |
| Ingest IO | openlet-ingest-io |
| Leta API | openlet-leta-api |
| Leta worker | openlet-leta-worker |
| Envoy | openlet-gateway |

Nếu process có nhiều vai trò, thêm bounded worker.role thay vì tạo nhiều telemetry providers trong cùng process. Environment lấy runtime.environment trong YAML.

HTTP/gRPC dùng W3C traceparent/tracestate qua native propagator. Temporal dùng SDK tracing integration truyền context trong native workflow/activity headers; Go/Python dùng cùng TraceContext propagator. Không tự tạo trace headers, lưu trace IDs trong SQL hoặc đưa actor/credentials vào baggage. Trace context không phải authentication.

Workflow replay không được phát sinh duplicate business spans/logs/metrics. Dùng SDK workflow integration và replay-safe workflow logger; không gọi exporter hoặc ordinary wall-clock instrumentation trong workflow code. Manual spans chỉ ở activity/handler hoặc qua API workflow-safe của SDK nếu thực sự cần.

## 3. Traces và instrumentation

| Boundary | Cách thực hiện |
|---|---|
| Go gRPC server/client | otelgrpc native stats handlers, một lần tại channel/server construction |
| Python gRPC | OpenTelemetry gRPC instrumentation, không wrapper mỗi generated RPC |
| PostgreSQL | pgx tracer integration; statement name/type/duration, không parameter values hoặc raw content |
| Provider HTTP/S3/Qdrant | Clerk/OpenAI qua otelhttp; S3 dùng smithyoteltracing/smithyotelmetrics native adapters; Qdrant qua otelgrpc. Không dùng deprecated otelaws hoặc instrument HTTP lần hai bên dưới S3 |
| Temporal Go | contrib/opentelemetry tracing interceptor + native metrics handler |
| Temporal Python | contrib.opentelemetry tracing; SDK/Core metrics qua native OpenTelemetryConfig |
| Ingest CPU/IO | Vài stage spans cho parse/export/enrich/embed/index, không span mỗi chunk/artifact |
| Leta | Giữ domain/runtime; chỉ thay telemetry initialization/context boundary theo YAML |
| Envoy | Native OpenTelemetry tracer; access logs dùng native JSON formatter |

Không bật đồng thời hai instrumentors cho cùng một transport. SDK chưa hỗ trợ instrumentation phù hợp thì giữ network span sẵn có; không dựng wrapper framework để phủ đủ mọi provider. Query count/performance probes dùng native pgx hooks/OTel và công cụ PostgreSQL, không port SQL rewriting/probe engine cũ.

Trace spans có thể chứa resource ID phục vụ điều tra khi cần; span names dùng RPC/stage cố định. Không ghi full request/response, file text, prompts/completions, signed URL query, authorization headers hoặc SQL bind values. Provider instrumentation phải được cấu hình không capture payload/query secrets tại boundary.

## 4. Metrics ít nhưng có ý nghĩa

Giữ native instrument names/units của versions đã pin, không viết metric mirror chỉ để đổi tên. Custom metrics chỉ bổ sung phần native instrumentation chưa biết.

| Nguồn | Signals cần |
|---|---|
| gRPC | Request duration, calls/errors theo method/status; active calls nếu native hỗ trợ |
| pgx pool/query | Connections/acquire wait, query duration; query count theo operation trong verification |
| SpiceDB/S3/model/Qdrant calls | Latency/status từ native client spans/metrics |
| Temporal SDK | Task queue schedule-to-start, activity execution/retry/failure, worker slots |
| Processing | Stage duration và outcome theo parse/enrich/index, không một series mỗi file |
| Domain errors | Quota rejection, version conflict, idempotency replay/conflict khi cần phân biệt từ RPC status |
| Process/runtime | Native Go/Python CPU/memory/runtime instrumentation phù hợp |

Metric labels chỉ dùng tập bounded: service, worker role, RPC method, status, stage, reason; model ID chỉ lấy catalog cấu hình hữu hạn. Không user/workspace/file/upload/workflow/trace ID, path, raw error string hoặc SQL text trong labels. IDs cần điều tra nằm trong log/span, không trong metric series.

Không chạy background SUM toàn workspace hoặc count mọi workspace để xuất quota gauges. Product API đã có used_bytes/quota_bytes; operational aggregation chỉ thêm khi có dashboard/query thật sự cần.

## 5. Logs

Go dùng slog JSONHandler và handler nhỏ thêm current trace/span ID; Python dùng logging với JSONFormatter chung đã có. Temporal Python Core logs được native LogForwardingConfig chuyển về cùng JSON handler. OTel Go exporter errors cũng đi qua slog. Không thêm logging framework hoặc OTLP logs exporter.

Operation log có timestamp, severity, message, service identity; thêm trace_id/span_id từ current span khi có. Processing logs thêm file_id/version/stage; Temporal logs dùng native workflow/run/activity context. Không tạo request-ID registry. Request không sampled vẫn có thể có trace ID để correlation nhưng backend không nhất thiết có trace tương ứng.

Envoy ghi access log một lần với route template, HTTP/gRPC status, duration, upstream và trace correlation. App ghi meaningful domain events/final failure; không log success từng SQL/chunk hoặc cùng exception ở handler, store, client và SDK. Expected user errors không mặc định là internal-error stack trace.

Logs chỉ đi stdout một lần. Khi chọn log backend, dùng runtime/Collector collection; không vừa tail stdout vừa bật app OTLP logs và nhân đôi ingestion. Log scrubbing nằm ở boundary tạo dữ liệu, không regex-scan mọi payload sau khi đã ghi.

## 6. Config và lifecycle

Chỉ cần phần này trong YAML chung:

```yaml
telemetry:
  otlp_endpoint: null
  trace_sample_ratio: 0.1
  metrics_export_interval_seconds: 60
```

Khi bật, endpoint ví dụ http://otel-collector:4317; protocol duy nhất hiện tại là OTLP/gRPC. Không giữ matrix OTLP HTTP/gRPC, per-signal env override và sampler selection framework. Runtime log level nằm ở runtime.log_level hiện có; resource environment lấy runtime.environment.

Root traces dùng ratio sampling, child spans theo parent bằng native ParentBased sampler. Metrics không bị trace sampling. Envoy root sampling render từ cùng setting; không giả định sampling 10% giữ mọi failed trace. Warning/error logs vẫn ghi theo log level. Tail sampling chỉ xét khi có nhu cầu vận hành thực, không thêm ở MVP.

Process entrypoint sở hữu một TracerProvider và MeterProvider. SDK batch processor/periodic reader dùng bounded memory/native retry/timeouts. Endpoint HTTP(S), sample ratio hữu hạn trong [0,1] và interval dương được kiểm khi bật export; config sai báo startup error; Collector unavailable không làm RPC fail/readiness fail. Queue đầy có thể drop telemetry; không có durable spool, custom retry hoặc business transaction chờ exporter.

Shutdown: drain requests/activities trước rồi flush/shutdown providers. Go dùng context deadline; trace/metric exporters có native timeout 3 giây. Python trace exporter timeout 3 giây, metric exporter/shutdown timeout 3 giây; không block business requests để chờ collector. Không gọi flush trên từng request. Null endpoint không tạo outbound exporters hoặc yêu cầu Collector trong unit tests.

## 7. Collector và monitoring sau này

Khi cần backend, thêm một Collector deployment với OTLP receiver, memory_limiter, batch và exporters native. Backend giữ retention/auth/dashboard/alerts; application code giữ nguyên. Traces có thể tới Tempo/Jaeger/SaaS, metrics tới backend hỗ trợ OTLP hoặc Prometheus qua Collector, logs tới log backend được chọn. Target đã chốt là Alloy + Grafana Cloud Free/Langfuse Cloud Free theo owning observability plan; baseline này chưa deploy.

Envoy/Temporal/SpiceDB/Qdrant dùng metrics endpoints native trong mạng private; Collector có thể scrape bằng Prometheus receiver. Envoy admin /stats/prometheus không public. PostgreSQL dùng native operational views hoặc exporter khi bổ sung monitoring; không mở app HTTP listener chỉ để xuất metrics.

Native Collector config nếu cần được render bằng bootstrap từ YAML/deployment settings đã chọn, giống Envoy/Temporal. Backend Cloud đã chọn; implementation điền endpoints/secret refs thực vào owning YAML route, không thêm hand-maintained config thứ hai.

## 8. Ownership và verification

packages/sdk-go/telemetry.go và sdk-python/openlet_sdk/telemetry.py chỉ init native providers/resource/propagation và shutdown. Owning apps gắn instrumentation và business spans/metrics. Không event registry hoặc decorators mirror mọi method.

Focused Go test dùng OTLP receiver nội bộ để kiểm gRPC parent-child context, export và log correlation; kiểm null endpoint và bounded shutdown khi collector unavailable. Python tests kiểm native HTTPX signed-URL redaction, JSON correlation/exception cause và stage duration/outcome labels. Compose smoke dùng receiver tạm ngoài source để kiểm Envoy → Go → Temporal → Python → LetFS; không thêm full monitoring stack vào CI hoặc test lại từng native metric.

Envoy 1.40.2 đã validate cấu hình native; versions nằm trong Go modules/uv.lock/Compose. Gateway dùng native ParentBased + ratio sampler từ cùng YAML, max_path_tag_length=0 tránh ghi query/path; access log chỉ ghi route name, method, status, duration, upstream và trace ID. Chưa đo overhead dưới production load; không hứa giữ mọi error trace hay không bao giờ mất telemetry.

## Nguồn chính thức

- [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/).
- [Context propagation](https://opentelemetry.io/docs/concepts/context-propagation/).
- [Resource semantic conventions](https://opentelemetry.io/docs/specs/semconv/resource/).
- [Temporal Go OpenTelemetry integration](https://pkg.go.dev/go.temporal.io/sdk/contrib/opentelemetry).
- [Temporal Python telemetry config](https://python.temporal.io/temporalio.runtime.TelemetryConfig.html).
- [Envoy administration/stats](https://www.envoyproxy.io/docs/envoy/latest/operations/admin).
