import asyncio
import hashlib
import json
import os
from uuid import UUID

import pytest
from mirage import Workspace
from mirage.cache.types import ABSENT_WRITE, MatchWrite, ReplaceRequest
from mirage.types import FileType, MountMode, PathSpec
from openlet.clients.letfs import FilesystemClient
from openlet.errors import AppError
from openlet.rpc import Actor, RpcClient

from leta.filesystem.letfs_vfs import LetFSVFS, Mount


@pytest.mark.integration
async def test_native_mirage_artifacts_and_commands():
    raw = os.getenv("OPENLET_TEST_LETFS_FIXTURE")
    if not raw:
        pytest.skip("run TestIntegrationMirageLetFS with OPENLET_MIRAGE_INTEGRATION=1")
    fixture = json.loads(raw)
    actor = Actor("leta", UUID(fixture["leta_id"]))
    async with RpcClient(
        fixture["address"], fixture["token"], allow_plaintext=True
    ) as rpc:
        backend = LetFSVFS(
            FilesystemClient(rpc),
            actor,
            Mount(
                fixture["filesystem_id"],
                fixture["scope_id"],
                fixture["root_id"],
                "/home",
                True,
            ),
        )
        workspace = Workspace({"/home": (backend, MountMode.WRITE)}, network=False)
        try:
            with pytest.raises(AppError) as raw_blob:
                await backend.client.get_download(
                    fixture["filesystem_id"],
                    fixture["scope_id"],
                    fixture["source_id"],
                    actor=actor,
                )
            assert raw_blob.value.kind == "forbidden"
            workspace.create_session("native-mirage")
            assert (await workspace.stat("/home/report.pdf")).type == FileType.FILE
            metadata = await workspace.tools.read("/home/report.pdf")
            assert not metadata.is_error, metadata.text
            assert "private original blob" not in metadata.text
            assert "report.md" in metadata.text
            for source in ("report.pdf", "@" + fixture["source_id"]):
                path = "/home/" + source + "/report.md"
                read = await workspace.tools.read(path)
                assert not read.is_error, read.text
                assert "artifact needle" in read.text
                for command in ("cat", "head -n 1", "tail -n 1"):
                    read = await workspace.tools.shell(command + " " + path)
                    assert not read.is_error, read.text
                write = await workspace.tools.write(path, "forbidden")
                assert write.is_error, "generated artifact must remain readonly"
            result = await workspace.tools.write("/home/notes.txt", "alpha\nneedle\r\n")
            assert not result.is_error, result.text
            for command in (
                "cat /home/notes.txt",
                "head -n 1 /home/notes.txt",
                "tail -n 1 /home/notes.txt",
                "wc -l /home/notes.txt",
                "sha256sum /home/notes.txt",
                "rg needle /home",
                "grep -r -n needle /home",
                "ls /home/report.pdf",
            ):
                result = await workspace.tools.shell(command)
                assert not result.is_error, (command, result.text)
            for command in (
                "printf 'more\\n' >> /home/notes.txt",
                "mkdir -p /home/a/b",
                "cp /home/notes.txt /home/a/copied.txt",
                "mv /home/a/copied.txt /home/a/renamed.txt",
                "rm /home/a/renamed.txt",
                "rmdir /home/a/b",
            ):
                result = await workspace.tools.shell(command)
                assert not result.is_error, (command, result.text)
            result = await workspace.tools.shell("cat /home/notes.txt")
            assert "more" in result.text
            escaped = await workspace.tools.read(
                "/home/@" + fixture["scope_root_id"] + "/box/notes.txt"
            )
            assert escaped.is_error, "ID alias cannot escape and reenter a box root"
            session = await workspace.session("native-hooks")
            vfs = session.vfs
            observations = workspace.vfs.records
            path = PathSpec.from_str_path("/home/notes.txt")
            for hook, kwargs in (
                ("line_count", {}),
                ("checksum", {"algorithm": "sha256"}),
                ("lines_containing", {"text": "needle", "ignore_case": False}),
            ):
                await workspace.cache.remove(path.virtual)
                before = len(observations)
                await vfs.dispatch(hook, path, **kwargs)
                assert any(
                    record.op == "read" and record.fingerprint and record.revision
                    for record in observations[before:]
                ), hook
            before = len(observations)
            await vfs.dispatch(
                "read_image", PathSpec.from_str_path("/home/picture.png")
            )
            assert any(
                record.op == "read" and record.fingerprint and record.revision
                for record in observations[before:]
            )
            await vfs.dispatch("pwrite", path, data=b"A", offset=0)
            await vfs.dispatch("truncate", path, length=5)
            await vfs.dispatch("edit_text", path, old_text="Alpha", new_text="omega")
            assert await vfs.read(path) == b"omega"

            # Hooks operate on real native bytes, including guards and offsets.
            hook_path = PathSpec.from_str_path("/home/hooks.txt")
            await vfs.dispatch("create", hook_path)
            await vfs.dispatch("append", hook_path, data=b"first\nlast\n")
            await vfs.dispatch("create", hook_path)
            assert await vfs.read(hook_path) == b"first\nlast\n"
            assert await backend.read(hook_path, offset=6, size=4) == b"last"
            assert await backend.first_lines(hook_path, 1) == b"first\n"
            assert await backend.last_lines(hook_path, 1) == b"last\n"
            assert await backend.line_count(hook_path) == 2
            assert (
                await backend.checksum(hook_path, "sha256")
                == hashlib.sha256(b"first\nlast\n").hexdigest()
            )
            assert await backend.checksum(hook_path, "unknown") is None
            read_ahead = await backend.read_many([hook_path, path], 6)
            assert read_ahead == {path.virtual: b"omega"}
            tree = await backend.read_tree(PathSpec.from_str_path("/home"))
            assert tree["hooks.txt"].size == 11
            original = await backend.stat(hook_path)
            with pytest.raises(FileExistsError):
                await backend._replace(ReplaceRequest(hook_path, b"bad", ABSENT_WRITE))
            await backend._replace(
                ReplaceRequest(hook_path, b"replaced\n", MatchWrite(original.revision))
            )
            with pytest.raises(OSError):
                await backend._replace(
                    ReplaceRequest(hook_path, b"stale", MatchWrite(original.revision))
                )
            assert await backend.read(hook_path) == b"replaced\n"
            follow = await backend.follow(hook_path, 0, 0.001)
            try:
                pending = asyncio.create_task(anext(follow))
                await vfs.dispatch("append", hook_path, data=b"new line\n")
                async with asyncio.timeout(5):
                    assert await pending == b"new line\n"
            finally:
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                await follow.aclose()

            # Cross-mount copy must preserve the blob, never copy metadata as text.
            result = await workspace.tools.shell("mkdir /home/destination")
            assert not result.is_error, result.text
            destination = await backend.native_stat(
                PathSpec.from_str_path("/home/destination")
            )
            target = LetFSVFS(
                backend.client,
                actor,
                Mount(
                    fixture["filesystem_id"],
                    fixture["scope_id"],
                    destination.node.id,
                    "/destination",
                    True,
                ),
            )
            workspace.add_mount("/destination", target, MountMode.WRITE)
            result = await session.tools.shell(
                "cp /home/report.pdf /destination/copied.pdf"
            )
            assert not result.is_error, result.text
            copied = await target.native_stat(
                PathSpec.from_str_path("/destination/copied.pdf")
            )
            assert copied.storage_kind == "inline"
            assert copied.node.media_type == "application/pdf"
            assert copied.node.size_bytes == len(b"private original blob")
        finally:
            await workspace.close()
