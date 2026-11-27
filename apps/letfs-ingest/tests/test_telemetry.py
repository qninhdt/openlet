from __future__ import annotations

import json
import logging
import sys
from typing import TYPE_CHECKING

import httpx
import pytest
from letfs_ingest import telemetry
from openlet_sdk.telemetry import JSONFormatter, redact_async_request, redact_request
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor, RequestInfo
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

if TYPE_CHECKING:
    from typing import NoReturn

    from letfs_ingest.telemetry import ProcessingIdentity


async def test_signed_queries_stay_out_of_exported_spans() -> None:
    signed = "https://s3.example/bucket/file?X-Amz-Credential=private-key&X-Amz-Signature=private-signature"
    request = httpx.Request("GET", signed)
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        info = RequestInfo(
            b"GET", request.url, request.headers, request.stream, request.extensions
        )
        with provider.get_tracer(__name__).start_as_current_span(
            "transfer", attributes={"http.url": signed, "url.full": signed}
        ) as span:
            redact_request(span, info)
            await redact_async_request(span, info)
        assert exporter.get_finished_spans()[0].attributes == {
            "http.url": "https://s3.example/bucket/file",
            "url.full": "https://s3.example/bucket/file",
        }
    finally:
        provider.shutdown()


def _raise_dimension_mismatch() -> NoReturn:
    raise ValueError("embedding dimensions mismatch")


def test_json_logs_preserve_activity_exception_cause() -> None:
    try:
        _raise_dimension_mismatch()
    except ValueError:
        record = logging.LogRecord(
            "worker", logging.ERROR, __file__, 1, "Activity failed", (), sys.exc_info()
        )
    output = json.loads(JSONFormatter().format(record))
    assert output["message"] == "Activity failed"
    assert "ValueError: embedding dimensions mismatch" in output["exception"]


async def test_native_http_instrumentation_redacts_signed_url() -> None:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    url = "https://s3.example/file?X-Amz-Signature=do-not-export"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ) as client:
        HTTPXClientInstrumentor.instrument_client(
            client, tracer_provider=provider, request_hook=redact_async_request
        )
        assert (await client.get(url)).status_code == 200
        HTTPXClientInstrumentor.uninstrument_client(client)
    try:
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert "do-not-export" not in str(spans[0].attributes)
    finally:
        provider.shutdown()


def test_processing_stage_records_bounded_metrics_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    metering = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(telemetry, "tracer", provider.get_tracer("test"))
    monkeypatch.setattr(
        telemetry,
        "duration",
        metering.get_meter("test").create_histogram("stage.duration", unit="s"),
    )
    identity: ProcessingIdentity = {"blob_id": "blob-123"}
    try:
        with telemetry.stage("parse", identity):
            record = logging.LogRecord(
                "worker", logging.INFO, __file__, 1, "stage", (), None
            )
            log = json.loads(JSONFormatter({"service.name": "cpu"}).format(record))
        with (
            pytest.raises(ValueError, match="private provider payload"),
            telemetry.stage("index", identity),
        ):
            raise ValueError("private provider payload")
        spans = exporter.get_finished_spans()
        assert spans[0].context is not None
        assert log["trace_id"] == f"{spans[0].context.trace_id:032x}"
        assert log["service.name"] == "cpu"
        assert spans[1].status.status_code.name == "ERROR"
        assert spans[1].attributes is not None
        assert spans[1].attributes["error.type"] == "ValueError"
        assert spans[1].attributes["blob.id"] == "blob-123"
        assert not spans[1].events
        data = reader.get_metrics_data()
        assert data is not None
        points_data = (
            data.resource_metrics[0].scope_metrics[0].metrics[0].data.data_points
        )
        attributes = [point.attributes for point in points_data]
        assert {"outcome": "success", "stage": "parse"} in attributes
        assert {"outcome": "error", "stage": "index"} in attributes
    finally:
        provider.shutdown()
        metering.shutdown()
