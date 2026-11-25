import json
import logging

from openlet_sdk.telemetry import JSONFormatter, langfuse_span
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind


def test_langfuse_filter_keeps_ai_and_only_search_client() -> None:
    assert langfuse_span(
        ReadableSpan(name="query", attributes={"gen_ai.operation.name": "embeddings"})
    )
    rpc = {
        "rpc.service": "openlet.letfs.v1.LetFSService",
        "rpc.method": "SemanticSearch",
    }
    assert langfuse_span(
        ReadableSpan(name="search", kind=SpanKind.CLIENT, attributes=rpc)
    )
    assert not langfuse_span(
        ReadableSpan(name="search", kind=SpanKind.SERVER, attributes=rpc)
    )
    assert not langfuse_span(
        ReadableSpan(
            name="read",
            kind=SpanKind.CLIENT,
            attributes={**rpc, "rpc.method": "ReadText"},
        )
    )
    assert not langfuse_span(
        ReadableSpan(name="sql", attributes={"db.system": "postgresql"})
    )


def test_json_formatter_preserves_blob_id() -> None:
    record = logging.LogRecord(
        "worker", logging.INFO, __file__, 1, "stage done", (), None
    )
    record.blob_id = "blob-xyz"
    record.stage = "index"
    record.outcome = "success"
    parsed = json.loads(JSONFormatter().format(record))
    assert parsed["blob_id"] == "blob-xyz"
    assert parsed["stage"] == "index"
    assert parsed["outcome"] == "success"
