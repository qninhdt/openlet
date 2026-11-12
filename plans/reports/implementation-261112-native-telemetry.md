# Native OpenTelemetry implementation

2026-11-12. Scope: Platform, LetFS, ingest CPU/IO, shared SDKs and Envoy. Owning design: [telemetry](../261111-1727-platform-letfs-rewrite/telemetry.md).

## Delivered

- Go SDK initializes resource identity, ParentBased sampling, W3C propagation, OTLP/gRPC trace/metric exporters and native runtime metrics. slog adds current trace/span IDs and resource identity; exporter errors use the same JSON logger. pgx pool metrics join the existing SQL tracer, with raw SQL disabled.
- Platform Clerk and LetFS model HTTP clients use otelhttp. S3 uses current Smithy tracing/metrics adapters; Qdrant uses otelgrpc. No deprecated otelaws dependency remains.
- Python adds native process CPU/memory/thread/GC metrics and service identity. Temporal Core logs forward through the existing JSON logger; activity context is retained as structured data.
- Ingest records parse, export/publication, enrich, embed-batch and index spans, plus a duration histogram with stage/outcome labels. File IDs/version are span/log fields, never metric labels. Parser subprocess conversion is covered by its parent parse stage; no per-artifact instrumentation.
- Envoy emits JSON access logs with bounded route names and trace correlation. Conditional native OTLP tracing uses the shared endpoint/sample ratio, ParentBased sampling and zero path-tag length. Query strings and authorization headers are absent from access logs. HTTPS collector URLs use native TLS verification.
- Common YAML remains unchanged. `otlp_endpoint: null` disables export; optional standard `OTEL_RESOURCE_ATTRIBUTES` supplies deployment version metadata. No application HTTP metrics server or monitoring backend was added.

Go uses module/VCS version when present, otherwise `dev`; Python reports installed SDK version. Go/Python generate process instance UUIDs. Envoy supplies its native SDK version and accepts standard resource attributes through its environment detector. Release metadata/instance attributes for the gateway can be supplied at deployment.

## Verification

- `make check test`: Go formatting/vet/tests, Ruff, Buf, TypeScript and shell syntax passed; **17 Python tests passed**. Existing third-party LangSmith asyncio deprecation warnings remain.
- Focused Go telemetry tests export real OTLP to an in-process receiver, verify a root → gRPC client → server chain and JSON correlation, and exercise null endpoint/unavailable collector with bounded shutdown. The final focused tests also passed the race detector.
- Python tests exercise native HTTPX redaction with signed URLs, log correlation/exception causes and bounded stage metric labels. A separate fresh-process check confirmed null-endpoint initialization is no-op and shuts down immediately. Native Temporal Runtime initialization with log forwarding was also checked directly.
- Envoy **1.40.2** accepted the native tracing/access-log configuration; final Compose startup also exercised the environment resource detector.
- Fresh isolated Compose stack, random test credentials, fresh databases and pre-migration backup: **4/4 existing API journeys passed, 41.9 seconds** for Playwright. Export validation found **1,260 spans** across Platform (367), LetFS (738), gateway (135), ingest IO (14), ingest CPU (6).
- Exported parent chains verified both Onboard → ProvisionWorkspace and gateway → CompleteUpload → StartWorkflow/RunWorkflow ProcessBlob → StartActivity/RunActivity → CPU/IO stage → LetFS RPC. Each processing stage kept the gateway trace ID and linked to its actual parent span. Native S3/Qdrant/HTTP spans and Go/pgx/Python/Temporal/stage metrics were received.
- Explicit sampled incoming W3C context was retained; unsampled context produced no exported span even with root sampling set to 100%. Exported telemetry contained no signed S3 query fields or the injected private-query marker. Ten stage logs carried trace/span IDs and structured Temporal activity context; gateway access logs also carried trace IDs.
- After stopping the collector and restarting Envoy, **2/2 gateway/onboarding and XLSX CPU+IO processing journeys passed, 22.5 seconds**. Collector unavailability generated telemetry errors while business requests and processing continued.
- Containers, network and volumes removed; cleanup exit **0**. No actual dotenv or old database was read or changed.

Ignored local evidence: `.local/otel-smoke/{run.log,checks-final.log,summary.json,compose.log,cleanup.log,output/otlp.jsonl}`. Receiver and orchestration live only in that ignored directory; CI gains only focused tests, without a monitoring stack.

## Issues found and resolved during verification

The first unavailable-collector rerun rotated its JWT signing key while Envoy cached the prior JWKS. The smoke sequence now restarts Envoy before a second Playwright invocation. A subsequent run caught missing required arguments in the new Temporal Python logging filter; explicit native WARN/ERROR levels fixed worker startup. Final fresh-image runs passed all journeys above.

## Limits

No production-load overhead/retention test, collector/backend deployment, dashboard or remote CI run. Leta runtime remains outside this change. Export uses native bounded queues/retries; collector outages can lose telemetry. TLS collector configuration was rendered and reviewed, while the live smoke used private-network plaintext OTLP/gRPC.
