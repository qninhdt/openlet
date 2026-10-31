---
phase: 3
title: "Complete Gin migration and OpenTelemetry"
status: completed
priority: P1
effort: "3–4 days"
dependencies: [2]
---

# Phase 3: Complete Gin migration and OpenTelemetry

## Goal and source evidence

Replace Chi completely in Account/Workspace and prepare every Go/Rust/Python app for OpenTelemetry, following the approved design. Do not deploy Collector, Grafana, or Prometheus.

Before implementation, inspect routers/handlers/middleware, HTTP server lifecycle, outbound clients, database pools, Temporal clients/workers, logging/configuration/shutdown, and lockfiles. Pre-move Go server.go files use Chi and custom access logging. Letfs already uses tracing. Temporal Rust 1.1.0 exposes opentelemetry/otel features; a feature name alone does not prove distributed tracing support.

## Minimal design

| Boundary | Target |
|----------|--------|
| Go HTTP | gin.New(), explicit middleware and native Gin handlers; otelgin inbound, otelhttp outbound |
| Rust HTTP | Keep Axum/Tower and tracing; connect tracing-opentelemetry and version-compatible HTTP instrumentation |
| Python | OTel Python, httpx instrumentation, supported Temporal contrib integration |
| Temporal | SDK-supported client/worker tracing integrations; prove actual Go↔Rust↔Python propagation |
| Database/storage/model | Instrument real driver/client boundaries where supported; manual spans only for useful uncovered operations |
| Logs/metrics | JSON stdout with trace_id/span_id; bounded HTTP duration/count/error and existing SDK metrics |

Each app owns a small native bootstrap at startup/shutdown. No telemetry service, cross-language framework, custom transport, per-function wrapper, or mandatory OTel log exporter. Domain code receives native context, never *gin.Context.

## File inventory

| Action | Target files or group | Size | Test impact |
|--------|-----------------------|------|-------------|
| Rewrite/delete | apps/account and apps/workspace internal/http, cmd, Go dependencies | Medium | Auth, route/body/error/stream contract, no Chi |
| Modify | All four apps' startup/config/logging/HTTP/Temporal clients and manifests | Medium | Context and optional exporter behavior |
| Create if needed | Small app-local telemetry bootstrap | Small/app | Resource attributes, provider lifecycle |
| Modify | Compose configuration, setup/architecture/testing docs | Small | Standard optional exporter settings |
| Add/update | Native integration and one system correlation journey | Small | Assert actual spans/context rather than HTTP success alone |

## Steps and execution checklist

- [x] Check official docs and installed types for the pinned Gin/OTel/contrib, Temporal Go/Rust/Python, and HTTP integrations. Pin compatible dependencies without unrelated upgrades. Distinguish SDK metrics from tracing support.
- [x] Rewrite Go handlers/middleware directly in Gin. Remove Chi imports/dependencies and obsolete wrappers; no gin.WrapH compatibility path. Keep server-owned http.Server timeout/graceful-shutdown management; avoid duplicate Gin/custom access logs.
- [x] Preserve duplicate trusted-header rejection, constant-time gateway authentication, internal authorization, request IDs, body limits, cancellation, and streaming flush. Explicitly trust only Envoy proxies. Check Gin redirect/path normalization, binding auto-writes, and panic recovery against the intended contract.
- [x] Instrument inbound/outbound HTTP and Temporal clients/workers in every app. Use W3C traceparent/tracestate. Do not forward arbitrary baggage across trust boundaries; add an allowlist only for a demonstrated need. No trace IDs in business payloads.
- [x] Use the installed Temporal Rust 1.1.0 native OpenTelemetryPlugin with its required experimental + opentelemetry features, pinned to the tested SDK version. Its distributed tracing API is explicitly experimental; enabling it is a scoped implementation choice for this nonproduction refactor, not permission for unrelated upgrades. The separate otel feature enables Core telemetry/metrics and does not substitute for this plugin. Configure trace-context-only propagation because the plugin otherwise propagates W3C Baggage by default. Use its documented replay-safe ID generator/processors where required. Prove cross-SDK _tracer-data propagation and Continue-As-New behavior with real integration; do not write a custom interceptor framework. If pinned integration fails, record the concrete incompatibility and revisit that dependency choice before claiming this gate passes.
- [x] Set stable service.name, service.version, deployment environment, and semantic-convention attributes. Both Python processes share the app service name with a worker-role attribute after phase 6. Use route templates, not raw resource paths/UUIDs as metric labels.
- [x] Support standard OTLP endpoint/protocol/sampling settings. No endpoint means no exporter/network retries to localhost; stdout logs still work. Configured exporters use bounded queues/batches/timeouts, and exporter failure never fails business requests.
- [x] Flush/shut down with a deadline, including partial startup. Exclude tokens, signed URL queries, file contents, SQL parameters, and model prompts from telemetry.
- [x] Use native test exporters or a test-only OTLP receiver to prove HTTP and Temporal context propagation, resource attributes, and log correlation. Respect native SDK replay/long-running trace/link semantics; do not add manual workflow spans that duplicate on replay.
- [x] Check absent/unreachable exporters, cancellation, and bounded shutdown. Update docs/dependencies and run focused Gin boundary tests plus the passing API baseline. Complete target RFC9457 business contracts in phases 4–5 without retaining two response formats.

## Concrete propagation and failure checks

| Risk | Test boundary and expected result |
|------|-----------------------------------|
| Gin migration changes trust checks | Real handler/gateway tests reject spoofed and duplicate trusted headers and unauthorized internal requests |
| Framework writes an unintended response | Invalid binding, unknown route, redirect-sensitive path and panic cases preserve the documented response semantics |
| Lost cancellation/stream support | Disconnect propagates through request context and downstream body reads; flush remains available |
| HTTP context stops at a service | Native exporter/receiver observes the related inbound/outbound spans with W3C context |
| Temporal integration only exports metrics | A real cross-language workflow/Activity produces tracing evidence at the worker boundary |
| Replay duplicates telemetry | SDK-supported replay behavior does not produce a new business effect or manually duplicated workflow instrumentation |
| Exporter is absent/unavailable | Normal app/worker requests succeed; no implicit localhost retry or unbounded memory growth |
| Shutdown happens during startup/export | Owned providers and connections close within a defined deadline, including partial initialization |
| Log/metric cardinality or sensitive content | Route-template labels remain bounded; active-span logs correlate without exporting payload/auth data |

Use the least expensive reliable layer for each check. Add one actual propagation scenario across languages, not an E2E permutation for every endpoint. A test-only exporter/receiver is not new production observability infrastructure.

## Configuration and handoff to later phases

Document the standard OTLP endpoint/protocol and sampler settings actually supported by each installed SDK. Keep provider configuration app-local and direct; no configuration framework or parallel custom environment vocabulary. Structured stdout logs remain useful without an exporter.

Phase 4 adds child workflows/remote Activities using this same integration; phase 6 starts both Python worker roles with it. Those phases must preserve context rather than adding a second telemetry initialization path. New public routes also need stable route-template spans and bounded attributes.

## Acceptance and risks

- [x] No Chi dependency/import/route/middleware or legacy handler adapter remains.
- [x] Real HTTP→outbound/Temporal Activity propagation and correlated active-span logs are proven for Go/Rust/Python.
- [x] Apps work with no exporter and with an unavailable endpoint; no unbounded buffer, hanging shutdown, or duplicate access logs.
- [x] Auth/body/error/stream tests and the phase-1 API baseline pass.

Version compatibility and the Rust SDK's experimental tracing API are the main risks. Its current source explicitly provides distributed tracing and replay handling, so use that implementation and test it instead of treating tracing support as unknown or inventing another one. Resolve incompatibilities during preflight/integration; never silently drop tracing. Revert phase changes if needed, keeping one framework in the final codebase. Continue to [phase 4](./phase-04-account-workspace-temporal.md).

References: [OTel Go](https://opentelemetry.io/docs/languages/go/), [OTel Python](https://opentelemetry.io/docs/languages/python/), [OTel Rust](https://opentelemetry.io/docs/languages/rust/), [otelgin](https://pkg.go.dev/go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin), [Temporal observability](https://docs.temporal.io/develop/go/observability).

## Execution evidence

- Native Gin boundary tests cover trusted-header duplication, internal authorization, JSON/body limits, redirect-sensitive routes, panic recovery and HTTP parentage. No Chi/WrapH remains.
- Native Go, Rust and Python exporters/log tests verify context, resource attributes, route templates and sensitive-query exclusion. Python instruments HTTPX and HTTPX2, which OpenAI 3 actually uses.
- A real gateway → Workspace Go → Letfs Rust → Temporal → Python enrichment/indexing journey completed with trace `511ec448fe64c13e7bd84e4c6f192e16`. Generation and embedding boundary requests retained that trace and contained no baggage. This probe used current business routes; the permanent target-route journey remains in the API suite for phase 4/5.
- Real Rust Temporal integration runs two Continue-As-New executions and Activities under one trace, fetches both histories and replays them through the native plugin without exporting additional spans. It is included in the native integration command.
- Four gateway baseline cases passed with no endpoint and again with an unreachable HTTP/protobuf endpoint; app/worker startup and owned-stack shutdown completed. Go/Python also exercise absent/unavailable exporters and bounded shutdown directly.
- Go unit/workflow/vet and PostgreSQL integration checks pass; Rust 14 lib tests, real continuation/replay integration and all-target Clippy pass; Python 69 nonparser tests and focused telemetry tests pass; TypeScript, Compose validation and whitespace checks pass. Existing parser/storage verification is recorded separately in validation.md.
- Target business API cases intentionally remain red until phases 4–6. Live external providers and remote CI are not claimed as verified. Both Python worker roles are completed in phase 6 using the same bootstrap.
