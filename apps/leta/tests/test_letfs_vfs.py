import asyncio
import errno
from dataclasses import replace
from uuid import uuid7

import pytest
from mirage.types import PathSpec, SearchQuery
from openlet.clients.letfs import (
    Breadcrumb,
    FileStat,
    Node,
    SearchMatch,
    SearchResult,
    SemanticSearchResults,
    TextRead,
)
from openlet.rpc import Actor

from leta.filesystem.letfs_vfs import LetFSVFS, Mount, collect_body


def test_locator_is_mount_relative_at_policy_and_backend_boundaries():
    mount = Mount(*(str(uuid7()) for _ in range(3)), "/users/person", True)
    backend = LetFSVFS(None, Actor("leta", uuid7()), mount)
    for path in [
        PathSpec.from_str_path("/users/person/@source/report.md"),
        PathSpec.from_str_path(
            "/users/person/@source/report.md", vfs_path="@source/report.md"
        ),
    ]:
        locator = backend.locator(path)
        assert locator.path == "/@source/report.md"
        assert locator.root_id == mount.root_id


async def test_collect_body_closes_once_on_success_limit_and_cancellation():
    closed = []

    async def body():
        try:
            yield b"abc"
            yield b"def"
        finally:
            closed.append(True)

    assert await collect_body(body(), 6) == b"abcdef"
    with pytest.raises(OSError) as error:
        await collect_body(body(), 5)
    assert error.value.errno == errno.EFBIG
    assert closed == [True, True]

    entered = asyncio.Event()

    async def waiting():
        try:
            yield b"a"
            entered.set()
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    task = asyncio.create_task(collect_body(waiting()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == [True, True, True]


class FollowClient:
    def __init__(self, mount):
        self.node = Node(
            str(uuid7()),
            mount.root_id,
            "notes.txt",
            "file",
            1,
            0,
            "text/plain",
            mount.scope_id,
        )
        self.body = b"before\npartial"
        self.reads = []

    async def stat(self, *args, **kwargs):
        return FileStat(
            self.node,
            "text",
            "text",
            len(self.body),
            str(self.node.revision),
            self.body.count(b"\n"),
            "digest",
        )

    async def read_text(self, fs, scope, locator, selection, **kwargs):
        self.reads.append(selection)
        stat = await self.stat()
        if selection.kind == "tail":
            content = self.body if selection.line_count else b""
        else:
            assert kwargs["expected_fingerprint"] == stat.fingerprint
            content = self.body[selection.offset :]
        return TextRead(stat, content, len(self.body) - len(content), len(content))


async def test_follow_joins_fragments_reads_only_new_bytes_and_closes():
    mount = Mount(*(str(uuid7()) for _ in range(3)), "/home", True)
    client = FollowClient(mount)
    backend = LetFSVFS(client, Actor("leta", uuid7()), mount)
    stream = await backend.follow(PathSpec.from_str_path("/home/notes.txt"), 2, 0.001)
    assert await anext(stream) == b"before\n"
    client.body += b" completed\n"
    client.node = replace(client.node, revision=2)
    async with asyncio.timeout(1):
        assert await anext(stream) == b"partial completed\n"
    assert client.reads[-1].offset == len(b"before\npartial")
    await stream.aclose()


async def test_follow_cancellation_stops_polling():
    mount = Mount(*(str(uuid7()) for _ in range(3)), "/home", True)
    client = FollowClient(mount)
    backend = LetFSVFS(client, Actor("leta", uuid7()), mount)
    stream = await backend.follow(PathSpec.from_str_path("/home/notes.txt"), 0, 10)
    task = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await stream.aclose()
    assert len(client.reads) == 1


async def test_semantic_mapping_preserves_root_and_source_artifact_alias():
    mount = Mount(*(str(uuid7()) for _ in range(3)), "/shared", True)

    class SemanticClient(FollowClient):
        async def semantic_search(self, fs, scope, query, *, filters, limit, actor):
            assert (fs, scope) == (mount.filesystem_id, mount.scope_id)
            assert query == "revenue" and limit == 10
            assert filters.parent.root_id == mount.root_id
            assert filters.parent.path == "/reports"
            return SemanticSearchResults(
                (
                    SearchResult(
                        self.node,
                        "/reports/report.pdf",
                        SearchMatch(
                            str(uuid7()),
                            (
                                Breadcrumb(self.node.id, "report.pdf"),
                                Breadcrumb(str(uuid7()), "nested"),
                                Breadcrumb(str(uuid7()), "report.md"),
                            ),
                            "Revenue grew",
                        ),
                    ),
                ),
                False,
                None,
            )

    client = SemanticClient(mount)
    backend = LetFSVFS(client, Actor("leta", uuid7()), mount)
    hits = await backend.search(
        PathSpec.from_str_path("/shared/reports", vfs_path="reports"),
        SearchQuery("revenue"),
    )
    assert hits == [
        (
            f"/shared/@{client.node.id}/nested/report.md",
            f"/shared/@{client.node.id}/nested/report.md\nRevenue grew",
        )
    ]
