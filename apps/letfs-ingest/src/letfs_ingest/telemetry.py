import asyncio
import json
import logging
import os
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from opentelemetry import metrics, propagate, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter as GrpcMetricExporter,
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter as GrpcSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter as HttpMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as HttpSpanExporter,
)
from opentelemetry.instrumentation.httpx import (
    HTTPX2ClientInstrumentor,
    HTTPXClientInstrumentor,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from temporalio.contrib.opentelemetry import MetricsExporter, TracingInterceptor
from temporalio.runtime import MetricBuffer, Runtime, TelemetryConfig


class JsonFormatter(logging.Formatter):
    def format(self, record):
        value = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.name.startswith("opentelemetry"):
            value["message"] = "telemetry export failed"
        if record.exc_info:
            value["exception_type"] = record.exc_info[0].__name__
        identity = trace.get_current_span().get_span_context()
        if identity.is_valid:
            value["trace_id"] = format(identity.trace_id, "032x")
            value["span_id"] = format(identity.span_id, "016x")
        return json.dumps(value, ensure_ascii=False)


def sanitize_request(span, request):
    if span.is_recording():
        url = urlsplit(str(request.url))
        safe_url = urlunsplit(
            (url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", "")
        )
        span.set_attribute("http.url", safe_url)
        span.set_attribute("url.full", safe_url)


async def sanitize_async_request(span, request):
    sanitize_request(span, request)


def enabled(signal):
    return (
        os.getenv("OTEL_SDK_DISABLED") != "true"
        and os.getenv(f"OTEL_{signal}_EXPORTER") != "none"
        and bool(
            os.getenv(f"OTEL_EXPORTER_OTLP_{signal}_ENDPOINT")
            or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        )
    )


def exporter(signal):
    protocol = (
        os.getenv(f"OTEL_EXPORTER_OTLP_{signal}_PROTOCOL")
        or os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL")
        or "grpc"
    )
    exporters = {
        ("TRACES", "grpc"): GrpcSpanExporter,
        ("TRACES", "http/protobuf"): HttpSpanExporter,
        ("METRICS", "grpc"): GrpcMetricExporter,
        ("METRICS", "http/protobuf"): HttpMetricExporter,
    }
    try:
        return exporters[signal, protocol](timeout=3)
    except Exception:
        raise ValueError("telemetry exporter configuration rejected") from None


@asynccontextmanager
async def configure(role):
    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "openlet-letfs-ingest"),
            "service.version": "0.1.0",
            "openlet.worker.role": role,
        }
    )
    async with AsyncExitStack() as cleanup:
        traces = TracerProvider(
            resource=resource,
            shutdown_on_exit=False,
            **(
                {"sampler": ALWAYS_OFF}
                if os.getenv("OTEL_SDK_DISABLED") == "true"
                else {}
            ),
        )
        cleanup.push_async_callback(asyncio.to_thread, traces.shutdown)
        if enabled("TRACES"):
            traces.add_span_processor(
                BatchSpanProcessor(
                    exporter("TRACES"),
                    max_queue_size=1024,
                    max_export_batch_size=256,
                    export_timeout_millis=3000,
                )
            )
        readers = []
        if enabled("METRICS"):
            readers.append(
                PeriodicExportingMetricReader(
                    exporter("METRICS"),
                    export_interval_millis=30000,
                    export_timeout_millis=3000,
                )
            )
        meters = MeterProvider(
            resource=resource, metric_readers=readers, shutdown_on_exit=False
        )
        cleanup.push_async_callback(
            asyncio.to_thread, meters.shutdown, timeout_millis=3000
        )
        trace.set_tracer_provider(traces)
        metrics.set_meter_provider(meters)
        propagator = TraceContextTextMapPropagator()
        propagate.set_global_textmap(propagator)
        for instrumentor in (HTTPXClientInstrumentor(), HTTPX2ClientInstrumentor()):
            instrumentor.instrument(
                tracer_provider=traces,
                meter_provider=meters,
                request_hook=sanitize_request,
                async_request_hook=sanitize_async_request,
            )
            cleanup.callback(instrumentor.uninstrument)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpx2").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)
        logging.getLogger("instructor").setLevel(logging.CRITICAL)
        interceptor = TracingInterceptor(traces.get_tracer("temporalio"))
        # This app executes Activities only; no Python Workflow interceptor is used.
        interceptor.text_map_propagator = propagator
        runtime = None
        if readers:
            buffer = MetricBuffer(10000)
            runtime = Runtime(telemetry=TelemetryConfig(metrics=buffer))
            await cleanup.enter_async_context(MetricsExporter(buffer, meters))
        yield interceptor, runtime
