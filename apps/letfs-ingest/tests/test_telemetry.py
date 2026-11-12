import httpx
import pytest
from letfs_ingest.artifacts import check_transfer
from openlet_sdk.telemetry import redact_async_request, redact_request
from opentelemetry.instrumentation.httpx import RequestInfo
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from temporalio.exceptions import ApplicationError


async def test_signed_queries_stay_out_of_exported_spans_and_transfer_errors():
    signed = "https://s3.example/bucket/file?X-Amz-Credential=private-key&X-Amz-Signature=private-signature"
    request = httpx.Request("GET", signed)
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        info = RequestInfo(b"GET", request.url, request.headers, request.stream, request.extensions)
        with provider.get_tracer(__name__).start_as_current_span("transfer", attributes={"http.url": signed, "url.full": signed}) as span:
            redact_request(span, info)
            await redact_async_request(span, info)
        assert dict(exporter.get_finished_spans()[0].attributes) == {"http.url": "https://s3.example/bucket/file", "url.full": "https://s3.example/bucket/file"}
        with pytest.raises(ApplicationError) as caught:
            check_transfer(httpx.Response(403, request=request))
        assert "403" in str(caught.value)
        assert "private" not in str(caught.value) and "X-Amz" not in str(caught.value)
    finally:
        provider.shutdown()


def test_json_logs_preserve_activity_exception_cause():
    import json
    import logging
    import sys

    from openlet_sdk.telemetry import JSONFormatter

    try:
        raise ValueError('embedding dimensions mismatch')
    except ValueError:
        record = logging.LogRecord('worker', logging.ERROR, __file__, 1, 'Activity failed', (), sys.exc_info())
    output = json.loads(JSONFormatter().format(record))
    assert output['message'] == 'Activity failed'
    assert 'ValueError: embedding dimensions mismatch' in output['exception']
