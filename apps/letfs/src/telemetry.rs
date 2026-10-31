use opentelemetry::{
    KeyValue, global,
    trace::{TraceContextExt, TracerProvider},
};
use opentelemetry_otlp::{Protocol, WithExportConfig};
use opentelemetry_sdk::{
    Resource,
    metrics::{PeriodicReader, SdkMeterProvider},
    propagation::TraceContextPropagator,
    trace::{BatchConfigBuilder, BatchSpanProcessor, Sampler, SdkTracerProvider},
};
use std::{fmt, time::Duration};
use temporalio_sdk::opentelemetry::{WorkflowIdGenerator, WorkflowSpanProcessor};
use tracing::{Event, Subscriber};
use tracing_opentelemetry::OpenTelemetrySpanExt;
use tracing_serde::AsSerde;
use tracing_subscriber::{
    EnvFilter,
    fmt::{FmtContext, FormatEvent, FormatFields, format::Writer},
    layer::SubscriberExt,
    registry::LookupSpan,
    util::SubscriberInitExt,
};

pub struct Telemetry {
    traces: SdkTracerProvider,
    metrics: SdkMeterProvider,
}

impl Telemetry {
    pub fn init() -> Result<Self, String> {
        let resource = Resource::builder()
            .with_service_name(
                std::env::var("OTEL_SERVICE_NAME").unwrap_or_else(|_| "openlet-letfs".into()),
            )
            .with_attribute(KeyValue::new("service.version", env!("CARGO_PKG_VERSION")))
            .build();
        let mut traces = SdkTracerProvider::builder()
            .with_resource(resource.clone())
            .with_id_generator(WorkflowIdGenerator::default());
        let mut metrics = SdkMeterProvider::builder().with_resource(resource);
        if std::env::var("OTEL_SDK_DISABLED").as_deref() == Ok("true") {
            traces = traces.with_sampler(Sampler::AlwaysOff);
        } else {
            if enabled("TRACES") {
                let exporter = match protocol("TRACES").as_str() {
                    "grpc" => opentelemetry_otlp::SpanExporter::builder()
                        .with_tonic()
                        .with_timeout(Duration::from_secs(3))
                        .build(),
                    "http/protobuf" => opentelemetry_otlp::SpanExporter::builder()
                        .with_http()
                        .with_protocol(Protocol::HttpBinary)
                        .with_timeout(Duration::from_secs(3))
                        .build(),
                    _ => return Err("unsupported OTLP traces protocol".into()),
                }
                .map_err(|_| "telemetry traces configuration rejected")?;
                let processor = BatchSpanProcessor::builder(exporter)
                    .with_batch_config(
                        BatchConfigBuilder::default()
                            .with_max_queue_size(1024)
                            .with_max_export_batch_size(256)
                            .build(),
                    )
                    .build();
                traces = traces.with_span_processor(WorkflowSpanProcessor::new(processor));
            }
            if enabled("METRICS") {
                let exporter = match protocol("METRICS").as_str() {
                    "grpc" => opentelemetry_otlp::MetricExporter::builder()
                        .with_tonic()
                        .with_timeout(Duration::from_secs(3))
                        .build(),
                    "http/protobuf" => opentelemetry_otlp::MetricExporter::builder()
                        .with_http()
                        .with_protocol(Protocol::HttpBinary)
                        .with_timeout(Duration::from_secs(3))
                        .build(),
                    _ => return Err("unsupported OTLP metrics protocol".into()),
                }
                .map_err(|_| "telemetry metrics configuration rejected")?;
                metrics = metrics.with_reader(
                    PeriodicReader::builder(exporter)
                        .with_interval(Duration::from_secs(30))
                        .build(),
                );
            }
        }
        let traces = traces.build();
        let metrics = metrics.build();
        tracing_subscriber::registry()
            .with(
                EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("letfs=info")),
            )
            .with(tracing_opentelemetry::layer().with_tracer(traces.tracer("letfs")))
            .with(tracing_subscriber::fmt::layer().event_format(CorrelatedJson))
            .try_init()
            .map_err(|_| "telemetry subscriber initialization failed")?;
        global::set_text_map_propagator(TraceContextPropagator::new());
        global::set_tracer_provider(traces.clone());
        global::set_meter_provider(metrics.clone());
        Ok(Self { traces, metrics })
    }

    pub fn shutdown(self) {
        // The pinned metric reader has its own five-second shutdown bound.
        if self.metrics.shutdown().is_err() {
            tracing::warn!("telemetry metrics shutdown incomplete");
        }
        if self
            .traces
            .shutdown_with_timeout(Duration::from_secs(3))
            .is_err()
        {
            tracing::warn!("telemetry traces shutdown incomplete");
        }
    }
}

fn enabled(signal: &str) -> bool {
    std::env::var(format!("OTEL_{signal}_EXPORTER")).as_deref() != Ok("none")
        && [
            format!("OTEL_EXPORTER_OTLP_{signal}_ENDPOINT"),
            "OTEL_EXPORTER_OTLP_ENDPOINT".into(),
        ]
        .iter()
        .any(|name| std::env::var(name).is_ok_and(|value| !value.is_empty()))
}

fn protocol(signal: &str) -> String {
    std::env::var(format!("OTEL_EXPORTER_OTLP_{signal}_PROTOCOL"))
        .or_else(|_| std::env::var("OTEL_EXPORTER_OTLP_PROTOCOL"))
        .unwrap_or_else(|_| "grpc".into())
}

pub(crate) struct HttpSpan;

impl reqwest_tracing::ReqwestOtelSpanBackend for HttpSpan {
    fn on_request_start(
        request: &reqwest::Request,
        extensions: &mut axum::http::Extensions,
    ) -> tracing::Span {
        reqwest_tracing::DefaultSpanBackend::on_request_start(request, extensions)
    }

    fn on_request_end(
        span: &tracing::Span,
        outcome: &reqwest_middleware::Result<reqwest::Response>,
        _: &mut axum::http::Extensions,
    ) {
        if let Ok(response) = outcome {
            reqwest_tracing::default_on_request_success(span, response);
        } else {
            // Reqwest's error/debug strings can contain credentials and signed URLs.
            span.record("otel.status_code", "ERROR");
            span.record("error.message", "HTTP transport failed");
        }
    }
}

pub(crate) struct CorrelatedJson;

impl<S, N> FormatEvent<S, N> for CorrelatedJson
where
    S: Subscriber + for<'a> LookupSpan<'a>,
    N: for<'a> FormatFields<'a> + 'static,
{
    fn format_event(
        &self,
        _: &FmtContext<'_, S, N>,
        mut writer: Writer<'_>,
        event: &Event<'_>,
    ) -> fmt::Result {
        let mut value = serde_json::to_value(event.as_serde()).map_err(|_| fmt::Error)?;
        value["timestamp"] = serde_json::json!(chrono::Utc::now().to_rfc3339());
        let active = tracing::Span::current().context();
        let context = if active.span().span_context().is_valid() {
            active
        } else {
            opentelemetry::Context::current()
        };
        let span = context.span();
        let identity = span.span_context();
        if identity.is_valid() {
            value["trace_id"] = serde_json::json!(identity.trace_id().to_string());
            value["span_id"] = serde_json::json!(identity.span_id().to_string());
        }
        writeln!(writer, "{value}")
    }
}
