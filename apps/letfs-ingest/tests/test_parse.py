from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from letfs_ingest import parse
from openlet_api.letfs.v1 import internal_pb2 as pb
from openlet_sdk.config import Config


async def test_parser_passes_original_name_without_using_it_as_a_local_path(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    name = "--Sales [draft] 2026.xlsx"
    stub = AsyncMock()
    stub.GetProcessingInput.return_value = pb.ProcessingInput(
        outcome=pb.ProcessingOutcome(stage="pending"),
        source_name=name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        download_url="https://example.invalid/input",
    )

    @asynccontextmanager
    async def heartbeats() -> AsyncGenerator[None]:
        yield

    child, download, publish = AsyncMock(return_value=0), AsyncMock(), AsyncMock()
    monkeypatch.setattr(parse, "heartbeats", heartbeats)
    monkeypatch.setattr(parse, "run_child", child)
    monkeypatch.setattr(parse, "download", download)
    monkeypatch.setattr(parse, "publish", publish)
    async with httpx.AsyncClient() as http:
        await parse.Parser(stub, http, config["services"]["letfs"]).run(
            {"file_id": "file-123", "version": 1}
        )
    arguments = child.call_args.args[0]
    assert arguments[-1] == f"--source-name={name}"
    assert download.call_args.args[2].name == "input.xlsx"
    publish.assert_awaited_once()
