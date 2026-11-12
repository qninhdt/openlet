import json
import logging
import math
from datetime import datetime, timezone
from importlib.metadata import version
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.grpc import GrpcAioInstrumentorClient
from opentelemetry.instrumentation.httpx import (
    HTTPX2ClientInstrumentor,
    HTTPXClientInstrumentor,
)
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import OTELResourceDetector, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


class JSONFormatter(logging.Formatter):
    def __init__(self, identity=None):
        super().__init__()
        self.identity = identity or {}

    def format(self, record):
        fields = {
            **self.identity,
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("file_id", "version", "stage", "outcome", "temporal_activity", "temporal_workflow"):
            if hasattr(record, key):
                fields[key] = getattr(record, key)
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
    resource = Resource.create({
        "service.name": name,
        "service.version": version("openlet-sdk"),
        "service.instance.id": str(uuid4()),
        "deployment.environment.name": runtime["environment"],
    }).merge(OTELResourceDetector().detect())
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter({key: value for key, value in resource.attributes.items() if key.startswith("service.") or key == "deployment.environment.name"}))
    logging.basicConfig(level=runtime["log_level"].upper(), handlers=[handler], force=True)
    # Provider transport logs may include signed URLs or model request content.
    for logger in ("httpx", "httpx2", "httpcore", "httpcore2", "openai"):
        logging.getLogger(logger).setLevel(logging.WARNING)
    set_global_textmap(TraceContextTextMapPropagator())
    endpoint = settings["otlp_endpoint"]
    if not endpoint:
        return lambda: None
    url = urlsplit(endpoint)
    ratio = settings["trace_sample_ratio"]
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.query or url.fragment or not math.isfinite(ratio) or not 0 <= ratio <= 1 or settings["metrics_export_interval_seconds"] < 1:
        raise ValueError("invalid telemetry endpoint, sample ratio or metrics interval")
    tracing = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(ratio)),
    )
    tracing.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=3)))
    metering = MeterProvider(resource=resource, metric_readers=[PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, timeout=3),
        export_interval_millis=settings["metrics_export_interval_seconds"] * 1000,
        export_timeout_millis=3000,
    )])
    trace.set_tracer_provider(tracing)
    metrics.set_meter_provider(metering)
    SystemMetricsInstrumentor(config={
        "process.cpu.time": ["user", "system"],
        "process.memory.usage": None,
        "process.thread.count": None,
        "cpython.gc.collections": None,
    }).instrument()
    GrpcAioInstrumentorClient().instrument()
    HTTPXClientInstrumentor().instrument(request_hook=redact_request, async_request_hook=redact_async_request)
    HTTPX2ClientInstrumentor().instrument(request_hook=redact_request, async_request_hook=redact_async_request)

    def shutdown():
        try:
            tracing.shutdown()
        finally:
            metering.shutdown(timeout_millis=3000)

    return shutdown
