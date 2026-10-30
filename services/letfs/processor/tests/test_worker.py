import sys
from unittest.mock import AsyncMock

import pytest

from openlet_processor import worker


async def test_missing_ocr_runtime_fails_before_connecting(tmp_path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("a" * 32)
    for name, value in {
        "TEMPORAL_ADDRESS": "temporal:7233",
        "TEMPORAL_NAMESPACE": "default",
        "LETFS_URL": "http://letfs:8080",
        "PROCESSOR_SERVICE_TOKEN_FILE": str(token),
        "DOCLING_MODELS_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    connect = AsyncMock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(worker.Client, "connect", connect)
    with pytest.raises(RuntimeError, match="OCR runtime unavailable") as error:
        await worker.main()
    assert isinstance(error.value.__cause__, ImportError)
    connect.assert_not_called()
