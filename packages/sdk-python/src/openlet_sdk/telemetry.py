import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.grpc import GrpcAioInstrumentorClient
from opentelemetry.instrumentation.httpx import (
    HTTPX2ClientInstrumentor,
    HTTPXClientInstrumentor,
)
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


class JSONFormatter(logging.Formatter):
    def format(self, record):
        fields = {
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            fields["exception"] = self.formatException(record.exc_info)
        span = trace.get_current_span().get_span_context()
        if span.is_valid:
            fields.update(trace_id=f"{span.trace_id:032x}", span_id=f"{span.span_id:016x}")
        return json.dumps(fields, ensure_ascii=False)


def redact_request(span, request):
    if span.is_recording():
        url = urlsplit(str(request.url))
        safe = urlunsplit((url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", ""))
        for attribute in ("http.url", "url.full"):
            if attribute in span.attributes:
                span.set_attribute(attribute, safe)


async def redact_async_request(span, request):
    redact_request(span, request)


def initialize(name, runtime, settings):
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=runtime["log_level"].upper(), handlers=[handler], force=True)
    # Provider transport logs may include signed URLs or model request content.
    for logger in ("httpx", "httpx2", "httpcore", "httpcore2", "openai"):
        logging.getLogger(logger).setLevel(logging.WARNING)
    set_global_textmap(TraceContextTextMapPropagator())
    endpoint = settings["otlp_endpoint"]
    if not endpoint:
        return lambda: None
    resource = Resource.create({
        "service.name": name,
        "deployment.environment.name": runtime["environment"],
    })
    tracing = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(settings["trace_sample_ratio"])),
    )
    tracing.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    metering = MeterProvider(resource=resource, metric_readers=[PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint),
        export_interval_millis=settings["metrics_export_interval_seconds"] * 1000,
    )])
    trace.set_tracer_provider(tracing)
    metrics.set_meter_provider(metering)
    GrpcAioInstrumentorClient().instrument()
    HTTPXClientInstrumentor().instrument(request_hook=redact_request, async_request_hook=redact_async_request)
    HTTPX2ClientInstrumentor().instrument(request_hook=redact_request, async_request_hook=redact_async_request)

    def shutdown():
        tracing.shutdown()
        metering.shutdown()

    return shutdown
