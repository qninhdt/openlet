import json
import logging
import math
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from langfuse import Langfuse
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.grpc import GrpcAioInstrumentorClient  # pyright: ignore[reportMissingTypeStubs]  # Upstream package does not publish type stubs.
from opentelemetry.instrumentation.httpx import (
    HTTPX2ClientInstrumentor,
    HTTPXClientInstrumentor,
    RequestInfo,
)
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import OTELResourceDetector, Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.util.types import AttributeValue

from .config import LangfuseSettings, RuntimeSettings, TelemetrySettings, secret


class JSONFormatter(logging.Formatter):
    def __init__(self, identity: Mapping[str, AttributeValue] | None = None) -> None:
        super().__init__()
        self.identity = identity or {}

    def format(self, record: logging.LogRecord) -> str:
        fields: dict[str, object] = {
            **self.identity,
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in (
            "file_id",
            "version",
            "stage",
            "outcome",
            "temporal_activity",
            "temporal_workflow",
        ):
            if hasattr(record, key):
                fields[key] = getattr(record, key)
        if record.exc_info:
            fields["exception"] = self.formatException(record.exc_info)
        span = trace.get_current_span().get_span_context()
        if span.is_valid:
            fields.update(
                trace_id=f"{span.trace_id:032x}", span_id=f"{span.span_id:016x}"
            )
        return json.dumps(fields, ensure_ascii=False)


def redact_request(span: Span, request: RequestInfo) -> None:
    if span.is_recording():
        url = urlsplit(str(request.url))
        safe = urlunsplit((url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", ""))
        for attribute in ("http.url", "url.full"):
            span.set_attribute(attribute, safe)


async def redact_async_request(span: Span, request: RequestInfo) -> None:
    redact_request(span, request)


def initialize(
    name: str, runtime: RuntimeSettings, settings: TelemetrySettings
) -> Callable[[], None]:
    resource = Resource.create(
        {
            "service.name": name,
            "service.instance.id": str(uuid4()),
            "deployment.environment.name": runtime["environment"],
        }
    ).merge(OTELResourceDetector().detect())
    handler = logging.StreamHandler()
    handler.setFormatter(
        JSONFormatter(
            {
                key: value
                for key, value in resource.attributes.items()
                if key.startswith("service.") or key == "deployment.environment.name"
            }
        )
    )
    logging.basicConfig(
        level=runtime["log_level"].upper(), handlers=[handler], force=True
    )
    # Provider transport logs may include signed URLs or model request content.
    for logger in ("httpx", "httpx2", "httpcore", "httpcore2", "openai"):
        logging.getLogger(logger).setLevel(logging.WARNING)
    set_global_textmap(TraceContextTextMapPropagator())
    endpoint = settings["otlp_endpoint"]
    url = urlsplit(endpoint or "")
    ratio = settings["trace_sample_ratio"]
    if (
        (
            endpoint
            and (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username
                or url.query
                or url.fragment
            )
        )
        or not math.isfinite(ratio)
        or not 0 <= ratio <= 1
        or settings["metrics_export_interval_seconds"] < 1
    ):
        raise ValueError("invalid telemetry endpoint, sample ratio or metrics interval")
    tracing = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(ratio)),
    )
    if endpoint:
        tracing.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=3))
        )
    metering = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoint, timeout=3),
                export_interval_millis=settings["metrics_export_interval_seconds"]
                * 1000,
                export_timeout_millis=3000,
            )
        ]
        if endpoint
        else [],
    )
    trace.set_tracer_provider(tracing)
    metrics.set_meter_provider(metering)
    SystemMetricsInstrumentor(
        config={
            "process.cpu.time": ["user", "system"],
            "process.memory.usage": None,
            "process.thread.count": None,
            "cpython.gc.collections": None,
        }
    ).instrument()
    GrpcAioInstrumentorClient().instrument()
    HTTPXClientInstrumentor().instrument(
        request_hook=redact_request, async_request_hook=redact_async_request
    )
    HTTPX2ClientInstrumentor().instrument(
        request_hook=redact_request, async_request_hook=redact_async_request
    )

    def shutdown() -> None:
        try:
            tracing.shutdown()
        finally:
            metering.shutdown(timeout_millis=3000)

    return shutdown


def langfuse_span(span: ReadableSpan) -> bool:
    from langfuse import is_default_export_span

    attributes = span.attributes or {}
    return is_default_export_span(span) or (
        span.kind == trace.SpanKind.CLIENT
        and attributes.get("rpc.service") == "openlet.letfs.v1.LetFSService"
        and attributes.get("rpc.method") == "SemanticSearch"
    )


def initialize_langfuse(
    settings: LangfuseSettings, runtime: RuntimeSettings
) -> Langfuse:
    return Langfuse(
        base_url=settings["base_url"],
        public_key=secret(settings["public_key"]),
        secret_key=secret(settings["secret_key"]),
        environment=runtime["environment"],
        should_export_span=langfuse_span,
    )
