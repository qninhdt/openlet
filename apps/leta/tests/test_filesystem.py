import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import grpc
import pytest
from langfuse import propagate_attributes
from leta.auth import Actor
from leta.config import LetFSServiceAsyncStub, Services
from leta.filesystem.letfs import LetFS
from leta.filesystem.workspace import Filesystem
from mirage import FileType, Mount, MountMode, PathSpec, Session, Workspace
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_api.letfs.v1.letfs_pb2_grpc import (
    LetFSServiceServicer,
    LetFSServiceStub,
    add_LetFSServiceServicer_to_server,
)
from openlet_sdk.config import Config, LetFSSettings

LETFS_SETTINGS = cast(
    LetFSSettings,
    {
        "max_text_bytes": 1048576,
        "max_blob_bytes": 104857600,
        "multipart_threshold_bytes": 16777216,
    },
)


@pytest.fixture
async def driver() -> AsyncIterator[LetFS]:
    root, folder, file = str(uuid4()), str(uuid4()), str(uuid4())
    nodes = {
        root: fs.Node(id=root, name="", kind=fs.NODE_KIND_DIRECTORY),
        folder: fs.Node(
            id=folder, parent_id=root, name="reports", kind=fs.NODE_KIND_DIRECTORY
        ),
        file: fs.Node(
            id=file, parent_id=folder, name="report.txt", kind=fs.NODE_KIND_FILE
        ),
    }
    blob = fs.Node(
        id=str(uuid4()),
        parent_id=root,
        name="quotes.xlsx",
        kind=fs.NODE_KIND_FILE,
        file=fs.FileHeader(
            type=fs.FILE_TYPE_BLOB,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    )
    artifact = fs.Node(
        id=str(uuid4()),
        parent_id=blob.id,
        name="table.csv",
        kind=fs.NODE_KIND_FILE,
        file=fs.FileHeader(
            type=fs.FILE_TYPE_TEXT, media_type="text/csv", size_bytes=12
        ),
        readonly=True,
    )
    image = fs.Node(
        id=str(uuid4()),
        parent_id=root,
        name="reference.png",
        kind=fs.NODE_KIND_FILE,
        file=fs.FileHeader(type=fs.FILE_TYPE_BLOB, media_type="image/png"),
    )

    class Files(LetFSServiceServicer):
        async def ReadTree(
            self,
            request: fs.ReadTreeRequest,
            context: grpc.aio.ServicerContext[fs.ReadTreeRequest, fs.ReadTreeResponse],
        ) -> fs.ReadTreeResponse:
            if request.root.path == "reference.png":
                return fs.ReadTreeResponse(entries=[fs.TreeEntry(path="", node=image)])
            if request.root.path == "quotes.xlsx":
                return fs.ReadTreeResponse(
                    entries=[fs.TreeEntry(path="table.csv", node=artifact)]
                )
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

        async def ListNodes(
            self,
            request: fs.ListNodesRequest,
            context: grpc.aio.ServicerContext[
                fs.ListNodesRequest, fs.ListNodesResponse
            ],
        ) -> fs.ListNodesResponse:
            if request.parent.path == ".":
                return fs.ListNodesResponse(nodes=[blob, image])
            assert request.parent.path == "quotes.xlsx"
            return fs.ListNodesResponse(nodes=[artifact])

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
            if request.target.WhichOneof("locator") == "path":
                if request.target.path == "quotes.xlsx/table.csv":
                    return artifact
                return blob if request.target.path == "quotes.xlsx" else nodes[root]
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
                LETFS_SETTINGS,
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
    hit = cast(list[dict[str, object]], result["hits"])[0]
    assert UUID(str(hit["node_id"]))
    assert result == {
        "path": "/home/reports",
        "hits": [
            {
                "path": "/home/reports/report.txt",
                "text": "hello",
                "storage_id": str(driver.storage),
                "node_id": hit["node_id"],
            }
        ],
    }
    assert (
        await driver.files_containing(path, "hello", whole_word=True, ignore_case=False)
        is None
    )
    listing = cast(dict[str, object], await driver.list_page(path, depth=2))
    assert listing["items"] == [
        {
            "path": "/home/reports/report.txt",
            "kind": "file",
            "storage_id": str(driver.storage),
            "node_id": hit["node_id"],
            "artifacts": False,
            "media_type": "",
            "size_bytes": None,
        }
    ]


async def test_original_document_is_file_and_artifacts_keep_preview(
    driver: LetFS,
) -> None:
    path = PathSpec(
        virtual="/data/quotes.xlsx", directory="/data", vfs_path="quotes.xlsx"
    )
    assert (await driver.stat(path)).type == FileType.FILE
    workspace = Workspace(
        {"/data": Mount(vfs=driver, mode=MountMode.READ)}, network=False
    )
    try:
        session = await workspace.session("tools")
        assert (await session.vfs.stat("/data/quotes.xlsx")).type == FileType.FILE
        listing, _ = await session.vfs.dispatch("list_page", path)
        assert "table.csv" in str(listing)
        preview, _ = await session.vfs.dispatch("preview", path, image=False)
        assert "table.csv" in str(preview)
    finally:
        await workspace.close()


async def test_listings_distinguish_images_from_document_artifacts(
    driver: LetFS,
) -> None:
    from leta.runtime.tools import directory_text

    root = PathSpec(virtual="/data", directory="/data", vfs_path="")
    listing = await driver.list_page(root)
    text = directory_text("/data", listing)
    assert "quotes.xlsx/ [document artifacts]" in text
    assert "reference.png [image; read with file_read]" in text
    assert "reference.png/" not in text
    image = PathSpec(
        virtual="/data/reference.png", directory="/data", vfs_path="reference.png"
    )
    listing = await driver.list_page(image, depth=3)
    assert directory_text("/data/reference.png", listing) == (
        "Image: /data/reference.png [read with file_read]"
    )


async def test_parallel_file_tools_share_session_and_only_apply_mount_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from leta.filesystem import workspace as module
    from leta.filesystem.workspace import StorageMount

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
        mount = cast(dict[str, Mount], args[0])["/home"]
        assert mount.mode == MountMode.EXEC
        assert cast(LetFS, mount.vfs).root == root
        assert kwargs["network"] is True
        return cast(Workspace, NativeWorkspace())

    storage, root = uuid4(), uuid4()
    writable = False

    async def discover(self: Filesystem) -> None:
        await asyncio.sleep(0)
        self.bindings = {"/shared": StorageMount(root, writable, storage)}

    monkeypatch.setattr(module, "Workspace", workspace)

    def redis_url(_: Config) -> str:
        return "redis://unused"

    monkeypatch.setattr(module, "redis_url", redis_url)
    monkeypatch.setattr(Filesystem, "discover", discover)

    class Files:
        async def GetStorage(self, *args: object, **kwargs: object) -> fs.Storage:
            return fs.Storage(root_node_id=str(root))

    services = cast(
        Services,
        SimpleNamespace(
            files=Files(),
            config=cast(
                Config,
                {
                    "dependencies": {"redis": {"address": "redis:6379"}},
                    "services": {"letfs": LETFS_SETTINGS},
                },
            ),
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
    assert changes == [("/shared", MountMode.READ)]
    writable = True
    await filesystem.open()
    await filesystem.open()
    assert changes == [
        ("/shared", MountMode.READ),
        ("/shared", MountMode.EXEC),
    ]


@pytest.mark.parametrize("command", ["curl -fsS -o", "wget -q -O"])
async def test_shell_downloads_http_to_workspace(command: str) -> None:
    from mirage.vfs.ram import RAMVFS

    async def respond(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\nConnection: close\r\n\r\ndownload"
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(respond, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    ws = Workspace(
        {"/data": Mount(vfs=RAMVFS(), mode=MountMode.EXEC)},
        network=True,
    )
    try:
        session = await ws.session("tools")
        result = await session.shell(
            f"{command} /data/download.txt http://127.0.0.1:{port}/"
        )
        assert result.exit_code == 0, result.stderr
        downloaded = await session.shell("cat /data/download.txt")
        assert await downloaded.materialize_stdout() == b"download"
    finally:
        await ws.close()
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize("command", ["cp", "mv"])
@pytest.mark.parametrize(
    "cross_storage,refuse", [(False, False), (True, False), (True, True)]
)
async def test_shell_transfers_original_blob_and_keeps_source_on_failure(
    command: str, cross_storage: bool, refuse: bool
) -> None:
    media = "application/pdf"
    source_storage, other_storage, source_root, other_root = (uuid4() for _ in range(4))
    destination_storage = other_storage if cross_storage else source_storage
    original = fs.Node(
        id=str(uuid4()),
        storage_id=str(source_storage),
        parent_id=str(source_root),
        name="original.bin",
        kind=fs.NODE_KIND_FILE,
        file=fs.FileHeader(
            type=fs.FILE_TYPE_BLOB, media_type=media, size_bytes=12, version=1
        ),
    )
    nodes = {
        (str(source_storage), "."): fs.Node(
            id=str(source_root), kind=fs.NODE_KIND_DIRECTORY
        ),
        (str(other_storage), "."): fs.Node(
            id=str(other_root), kind=fs.NODE_KIND_DIRECTORY
        ),
        (str(source_storage), original.name): original,
    }
    payload = b"\x00\xffraw bytes\x00"
    contents = {original.id: payload}
    calls: list[str] = []

    class Files:
        async def Stat(self, request: fs.NodeRequest, **kwargs: object) -> fs.Node:
            try:
                return nodes[(request.storage_id, request.target.path)]
            except KeyError:
                raise FileNotFoundError(request.target.path) from None

        async def CopyNode(
            self, request: fs.TransferNodeRequest, **kwargs: object
        ) -> fs.Node:
            calls.append("copy")
            if refuse:
                raise PermissionError("destination refused")
            source = nodes[(request.storage_id, request.source.path)]
            assert source.kind == fs.NODE_KIND_FILE and source.HasField("file")
            result = fs.Node()
            result.CopyFrom(source)
            result.id = str(uuid4())
            result.storage_id = request.destination_storage_id
            result.name = request.name
            nodes[(result.storage_id, result.name)] = result
            contents[result.id] = contents[source.id]
            return result

        async def MoveNode(
            self, request: fs.TransferNodeRequest, **kwargs: object
        ) -> fs.Node:
            calls.append("move")
            source = nodes.pop((request.storage_id, request.source.path))
            source.name = request.name
            source.storage_id = request.destination_storage_id
            nodes[(source.storage_id, source.name)] = source
            return source

        async def TrashNode(
            self, request: fs.TrashNodeRequest, **kwargs: object
        ) -> None:
            calls.append("trash")
            del nodes[(request.storage_id, request.target.path)]

    stub = cast(LetFSServiceAsyncStub, Files())
    actor, workspace = Actor("agent", uuid4()), uuid4()
    driver = LetFS(stub, actor, workspace, source_storage, source_root, LETFS_SETTINGS)
    destination = LetFS(
        stub, actor, workspace, other_storage, other_root, LETFS_SETTINGS
    )
    ws = Workspace(
        {
            "/source": Mount(vfs=driver, mode=MountMode.WRITE),
            "/destination": Mount(vfs=destination, mode=MountMode.WRITE),
        },
        network=False,
    )
    try:
        session = await ws.session("tools")
        target = "/destination" if cross_storage else "/source"
        result = await session.shell(
            f"{command} /source/original.bin {target}/result.bin"
        )
        source_key = (str(source_storage), "original.bin")
        destination_key = (str(destination_storage), "result.bin")
        if refuse:
            assert result.exit_code != 0
            assert source_key in nodes and destination_key not in nodes
            assert calls == ["copy"]
        else:
            assert result.exit_code == 0, result.stderr
            transferred = nodes[destination_key]
            assert transferred.kind == fs.NODE_KIND_FILE
            assert transferred.file.media_type == media
            assert contents[transferred.id] == payload
            assert (source_key in nodes) == (command == "cp")
            assert calls == (
                ["copy"]
                if command == "cp"
                else ["copy", "trash"]
                if cross_storage
                else ["move"]
            )
    finally:
        await ws.close()
