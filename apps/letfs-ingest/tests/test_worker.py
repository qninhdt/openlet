import sys
from unittest.mock import AsyncMock

import pytest

from letfs_ingest import worker


async def test_missing_ocr_runtime_fails_before_connecting(tmp_path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("a" * 32)
    for name, value in {
        "TEMPORAL_ADDRESS": "temporal:7233",
        "TEMPORAL_NAMESPACE": "default",
        "LETFS_RPC_ADDRESS": "letfs:9090",
        "INGEST_SERVICE_TOKEN_FILE": str(token),
        "DOCLING_MODELS_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    connect = AsyncMock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(worker, "connect", connect)
    with pytest.raises(RuntimeError, match="OCR runtime unavailable") as error:
        await worker.main("cpu")
    assert isinstance(error.value.__cause__, ImportError)
    connect.assert_not_called()


async def test_io_worker_polls_without_parser_models_or_ocr(tmp_path, monkeypatch):
    import signal
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    token = tmp_path / "token"
    token.write_text("a" * 32)
    for name, value in {
        "TEMPORAL_ADDRESS": "temporal:7233",
        "TEMPORAL_NAMESPACE": "default",
        "LETFS_RPC_ADDRESS": "letfs:9090",
        "INGEST_SERVICE_TOKEN_FILE": str(token),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("DOCLING_MODELS_PATH", raising=False)
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    handlers = {}
    loop = worker.asyncio.get_running_loop()
    monkeypatch.setattr(
        loop,
        "add_signal_handler",
        lambda sig, handler: handlers.__setitem__(sig, handler),
    )
    monkeypatch.setattr(loop, "remove_signal_handler", lambda sig: handlers.pop(sig))

    @asynccontextmanager
    async def telemetry(service, role):
        assert service == "openlet-letfs-ingest"
        assert role == "io"
        yield "tracing", None

    class Poller:
        def __init__(self, client, **options):
            assert options["task_queue"] == "openlet-letfs-io"
            assert [activity.__name__ for activity in options["activities"]] == [
                "enrich_file",
                "index_file",
            ]
            assert options["max_concurrent_activities"] == 4

        async def __aenter__(self):
            handlers[signal.SIGTERM]()

        async def __aexit__(self, *args):
            pass

    ai = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(worker, "configure", telemetry)
    monkeypatch.setattr(worker.AISettings, "from_env", lambda: None)
    monkeypatch.setattr(worker.IndexSettings, "from_env", lambda: None)
    monkeypatch.setattr(worker, "OpenRouter", lambda settings: ai)
    monkeypatch.setattr(worker, "connect", AsyncMock())
    monkeypatch.setattr(worker, "Worker", Poller)
    await worker.main("io")
    ai.close.assert_awaited_once()
    assert not handlers
