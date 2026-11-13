from openlet_sdk.telemetry import langfuse_span
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.trace import SpanKind


def test_langfuse_filter_keeps_ai_and_only_search_client() -> None:
    provider = TracerProvider()
    tracer = provider.get_tracer('openlet.test')
    with tracer.start_as_current_span('query', attributes={'gen_ai.operation.name': 'embeddings'}) as ai:
        assert langfuse_span(ReadableSpan(name='query', attributes=ai.attributes))
    rpc = {'rpc.service': 'openlet.letfs.v1.LetFSService', 'rpc.method': 'SemanticSearch'}
    assert langfuse_span(ReadableSpan(name='search', kind=SpanKind.CLIENT, attributes=rpc))
    assert not langfuse_span(ReadableSpan(name='search', kind=SpanKind.SERVER, attributes=rpc))
    assert not langfuse_span(ReadableSpan(name='read', kind=SpanKind.CLIENT, attributes={**rpc, 'rpc.method': 'ReadText'}))
    assert not langfuse_span(ReadableSpan(name='sql', attributes={'db.system': 'postgresql'}))
    provider.shutdown()
