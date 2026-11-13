import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import grpc
import pytest
from langfuse import propagate_attributes
from leta.auth import Actor
from leta.config import Services
from leta.filesystem.letfs import LetFS
from leta.filesystem.workspace import Filesystem
from mirage import MountMode, PathSpec, Session, Workspace
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_api.letfs.v1.letfs_pb2_grpc import (
    LetFSServiceServicer,
    LetFSServiceStub,
    add_LetFSServiceServicer_to_server,
)
from openlet_sdk.config import Config


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
            self,
            request: fs.ReadTreeRequest,
            context: grpc.aio.ServicerContext[fs.ReadTreeRequest, fs.ReadTreeResponse],
        ) -> fs.ReadTreeResponse:
            assert request.root.path == "reports"
            return fs.ReadTreeResponse(
                entries=[fs.TreeEntry(path="report.txt", node=nodes[file])]
            )

        async def TextSearch(
            self,
            request: fs.TextSearchRequest,
            context: grpc.aio.ServicerContext[
                fs.TextSearchRequest, fs.TextSearchResponse
            ],
        ) -> fs.TextSearchResponse:
            assert request.root.path == "reports"
            return fs.TextSearchResponse(
                hits=[fs.TextHit(node=nodes[file], snippet="hello", path="report.txt")]
            )

        async def SemanticSearch(
            self,
            request: fs.SemanticSearchRequest,
            context: grpc.aio.ServicerContext[
                fs.SemanticSearchRequest, fs.SemanticSearchResponse
            ],
        ) -> fs.SemanticSearchResponse:
            assert request.root.root_node_id == root
            assert any(
                key == "baggage"
                and isinstance(value, str)
                and "langfuse_session_id=" in value
                for key, value in context.invocation_metadata() or ()
            )
            return fs.SemanticSearchResponse(
                hits=[
                    fs.SemanticHit(node=nodes[file], snippet="hello", path="report.txt")
                ]
            )

        async def Stat(
            self,
            request: fs.NodeRequest,
            context: grpc.aio.ServicerContext[fs.NodeRequest, fs.Node],
        ) -> fs.Node:
            assert request.target.root_node_id == root
            return nodes[request.target.node_id]

    server = grpc.aio.server()
    add_LetFSServiceServicer_to_server(Files(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
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
    with propagate_attributes(session_id=str(uuid4()), as_baggage=True):
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


async def test_parallel_file_tools_share_session_and_only_apply_mount_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from leta.filesystem import workspace as module

    created = 0
    opened = 0
    changes: list[tuple[str, MountMode]] = []
    shared = cast(Session, object())

    class NativeWorkspace:
        async def session(self, name: str) -> Session:
            nonlocal opened
            opened += 1
            await asyncio.sleep(0)
            return shared

        def add_mount(
            self, path: str, *args: object, mode: MountMode, **kwargs: object
        ) -> None:
            changes.append((path, mode))

        def set_mount_mode(self, path: str, mode: MountMode) -> None:
            changes.append((path, mode))

    def workspace(*args: object, **kwargs: object) -> Workspace:
        nonlocal created
        created += 1
        return cast(Workspace, NativeWorkspace())

    storage, root = uuid4(), uuid4()
    writable = False

    async def discover(self: Filesystem) -> None:
        await asyncio.sleep(0)
        self.bindings = {str(storage): (root, writable)}

    monkeypatch.setattr(module, "Workspace", workspace)

    def redis_url(_: Config) -> str:
        return "redis://unused"

    monkeypatch.setattr(module, "redis_url", redis_url)
    monkeypatch.setattr(Filesystem, "discover", discover)
    services = cast(
        Services,
        SimpleNamespace(
            files=None,
            config=cast(Config, {"dependencies": {"redis": {"address": "redis:6379"}}}),
        ),
    )
    filesystem = Filesystem(
        services,
        {
            "leta_id": uuid4(),
            "workspace_id": uuid4(),
            "storage_id": uuid4(),
            "home_node_id": uuid4(),
        },
    )
    sessions = await asyncio.gather(*(filesystem.open() for _ in range(5)))
    assert all(session is shared for session in sessions)
    assert (created, opened) == (1, 1)
    assert changes == [(f"/mnt/{storage}", MountMode.READ)]
    writable = True
    await filesystem.open()
    await filesystem.open()
    assert changes == [
        (f"/mnt/{storage}", MountMode.READ),
        (f"/mnt/{storage}", MountMode.WRITE),
    ]
