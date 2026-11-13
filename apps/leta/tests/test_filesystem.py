from collections.abc import AsyncIterator
from typing import cast
from uuid import uuid4

import grpc
import pytest
from leta.auth import Actor
from leta.filesystem.letfs import LetFS
from mirage import PathSpec
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_api.letfs.v1.letfs_pb2_grpc import (
    LetFSServiceServicer,
    LetFSServiceStub,
    add_LetFSServiceServicer_to_server,
)


@pytest.fixture
async def driver() -> AsyncIterator[LetFS]:
    root, folder, file = str(uuid4()), str(uuid4()), str(uuid4())
    nodes = {
        folder: fs.Node(
            id=folder, parent_id=root, name="reports", kind=fs.NODE_KIND_DIRECTORY
        ),
        file: fs.Node(
            id=file, parent_id=folder, name="report.txt", kind=fs.NODE_KIND_FILE
        ),
    }

    class Files(LetFSServiceServicer):
        async def ReadTree(
            self, request: fs.ReadTreeRequest, context: grpc.aio.ServicerContext
        ) -> fs.ReadTreeResponse:
            assert request.root.path == "reports"
            return fs.ReadTreeResponse(
                entries=[fs.TreeEntry(path="report.txt", node=nodes[file])]
            )

        async def TextSearch(
            self, request: fs.TextSearchRequest, context: grpc.aio.ServicerContext
        ) -> fs.TextSearchResponse:
            assert request.root.path == "reports"
            return fs.TextSearchResponse(
                hits=[fs.TextHit(node=nodes[file], snippet="hello")]
            )

        async def SemanticSearch(
            self, request: fs.SemanticSearchRequest, context: grpc.aio.ServicerContext
        ) -> fs.SemanticSearchResponse:
            assert request.root.root_node_id == root
            return fs.SemanticSearchResponse(
                hits=[fs.SemanticHit(node=nodes[file], snippet="hello")]
            )

        async def Stat(
            self, request: fs.NodeRequest, context: grpc.aio.ServicerContext
        ) -> fs.Node:
            assert request.target.root_node_id == root
            return nodes[request.target.node_id]

    server = grpc.aio.server()
    add_LetFSServiceServicer_to_server(Files(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            from uuid import UUID

            yield LetFS(
                LetFSServiceStub(channel),
                Actor("agent", uuid4()),
                uuid4(),
                uuid4(),
                UUID(root),
            )
    finally:
        await server.stop(0)


async def test_search_returns_openable_paths_under_mount(driver: LetFS) -> None:
    path = PathSpec(virtual="/home/reports", directory="/home", vfs_path="reports")
    files = await driver.files_containing(
        path, "hello", whole_word=False, ignore_case=True
    )
    assert files is not None
    assert [item.virtual for item in files] == ["/home/reports/report.txt"]
    result = await driver.semantic_search(path, "hello")
    assert result == {
        "path": "/home/reports",
        "hits": [{"path": "/home/reports/report.txt", "text": "hello"}],
    }
    assert (
        await driver.files_containing(path, "hello", whole_word=True, ignore_case=False)
        is None
    )
    listing = cast(dict[str, object], await driver.list_page(path, depth=2))
    assert listing["items"] == [
        {"path": "/home/reports/report.txt", "kind": "file", "size_bytes": None}
    ]
