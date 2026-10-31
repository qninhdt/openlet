import json
import logging
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import httpx2
import pytest
from opentelemetry import propagate
from opentelemetry.instrumentation.httpx import (
    HTTPX2ClientInstrumentor,
    HTTPXClientInstrumentor,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from openlet_processor.telemetry import JsonFormatter, sanitize_async_request


@pytest.mark.parametrize("endpoint", ["", "http://127.0.0.1:1"])
def test_optional_exporter_does_not_block_worker_or_shutdown(endpoint):
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("OTEL_")
    }
    environment.update(
        OTEL_EXPORTER_OTLP_ENDPOINT=endpoint,
        OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf",
        OTEL_METRICS_EXPORTER="none",
        OTEL_TRACES_SAMPLER="always_on",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import asyncio, logging
from opentelemetry import trace
from openlet_processor.telemetry import configure
async def main():
    async with configure('processing'):
        with trace.get_tracer('test').start_as_current_span('business operation'):
            logging.info('business completed')
asyncio.run(main())
""",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=8,
        check=True,
    )
    records = [json.loads(line) for line in result.stdout.splitlines()]
    completed = next(
        record for record in records if record["message"] == "business completed"
    )
    assert len(completed["trace_id"]) == 32
    assert len(completed["span_id"]) == 16
    assert "127.0.0.1" not in result.stdout + result.stderr
    if not endpoint:
        assert len(records) == 1


@pytest.mark.parametrize(
    ("http", "instrumentor"),
    [(httpx, HTTPXClientInstrumentor), (httpx2, HTTPX2ClientInstrumentor)],
)
async def test_real_http_context_and_logs_exclude_signed_queries(http, instrumentor):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(dict(self.headers))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    previous = propagate.get_global_textmap()
    propagator = TraceContextTextMapPropagator()
    propagate.set_global_textmap(propagator)
    trace_id = "1234567890abcdef1234567890abcdef"
    try:
        parent = propagator.extract(
            {
                "traceparent": f"00-{trace_id}-1234567890abcdef-01",
                "baggage": "private=must-not-export",
            }
        )
        async with http.AsyncClient() as client:
            instrumentor.instrument_client(
                client,
                tracer_provider=provider,
                request_hook=sanitize_async_request,
            )
            with provider.get_tracer("test").start_as_current_span(
                "parse", context=parent
            ) as activity:
                response = await client.get(
                    f"http://127.0.0.1:{server.server_port}/object"
                    "?X-Amz-Signature=must-not-export"
                )
                assert response.status_code == 204
                record = logging.makeLogRecord(
                    {"msg": "parse completed", "name": "openlet_processor"}
                )
                log = json.loads(JsonFormatter().format(record))
                assert log["trace_id"] == trace_id
                assert log["span_id"] == format(
                    activity.get_span_context().span_id, "016x"
                )
        assert len(received) == 1
        headers = {key.lower(): value for key, value in received[0].items()}
        assert trace_id in headers["traceparent"]
        assert "baggage" not in headers
        spans = exporter.get_finished_spans()
        assert len(spans) == 2
        outbound = next(span for span in spans if span.name == "GET")
        assert outbound.parent.span_id == activity.get_span_context().span_id
        assert all(format(span.context.trace_id, "032x") == trace_id for span in spans)
        assert "must-not-export" not in str([dict(span.attributes) for span in spans])
        diagnostic = logging.makeLogRecord(
            {
                "msg": "export failed at private-endpoint",
                "name": "opentelemetry.exporter",
            }
        )
        assert "private-endpoint" not in JsonFormatter().format(diagnostic)
    finally:
        propagate.set_global_textmap(previous)
        provider.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()
