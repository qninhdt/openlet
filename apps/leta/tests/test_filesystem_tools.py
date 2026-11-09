import base64
import json
import os
from uuid import UUID, uuid7

import pytest
from openlet.clients.letfs import FilesystemClient
from openlet.rpc import Actor, RpcClient
from openlet_api.workspace.v1 import workspace_pb2 as pb
from redis.asyncio import Redis
from test_domain import box_input, root_input
from test_filesystem_workspace import ScopePages

from leta.filesystem.tools import FilesystemTools
from leta.filesystem.workspace import WorkspaceFactory


@pytest.mark.integration
async def test_factory_mount_isolation_tools_and_monty(
    store, redis_url, tmp_path, monkeypatch
):
    raw = os.getenv("OPENLET_TEST_LETFS_FIXTURE")
    if not raw:
        pytest.skip("run TestIntegrationMirageLetFS with OPENLET_MIRAGE_INTEGRATION=1")
    fixture = json.loads(raw)
    root = root_input(
        id=UUID(fixture["leta_id"]), home_scope_id=UUID(fixture["scope_id"])
    )
    await store.create_leta(root)
    await store.activate_leta(root.id)
    box = box_input(root.id, home_node_id=UUID(fixture["root_id"]))
    await store.create_box(box)
    await store.activate_box(root.id, box.id)
    page = pb.ListAccessibleScopesResponse(
        filesystem_id=fixture["filesystem_id"],
        items=[
            pb.AccessibleScope(
                id=fixture["scope_id"],
                root_id=fixture["scope_root_id"],
                kind="home",
                rights=pb.ScopeRights(
                    read_metadata=True, read_content=True, write=True
                ),
            )
        ],
    )
    host_file = tmp_path / "host-secret.txt"
    host_file.write_text("host-only data")
    async with (
        RpcClient(fixture["address"], fixture["token"], allow_plaintext=True) as rpc,
        Redis.from_url(redis_url) as redis,
    ):
        # Discovery's RPC contract is tested in Workspace; keep the real engine
        # Store, native LetFS, authorization, Mirage/Monty and Redis in this test.
        scopes = ScopePages(Actor("leta", root.id), [page] * 10)
        factory = WorkspaceFactory(
            store, scopes, FilesystemClient(rpc), redis, redis_url, "owned-fixture"
        )
        async with factory.open(root.id, root.id, str(uuid7())) as parent:
            tools = FilesystemTools(parent)
            await tools.write_file("~/private.txt", "parent-private\n")
            assert (await tools.read_file("~/private.txt"))[
                "text"
            ] == "parent-private\n"
            with pytest.raises(FileExistsError):
                await tools.write_file("~/private.txt", "must not overwrite")
            assert (await tools.read_file("~/private.txt"))[
                "text"
            ] == "parent-private\n"
            await tools.edit_file("~/private.txt", "parent-private", "edited")
            assert (await tools.read_file("~/private.txt"))["text"] == "edited\n"
            result = await tools.run_python("print(open('/home/private.txt').read())")
            assert result["exit_code"] == 0 and "edited" in result["stdout"], result
            denied = await tools.run_python(f"print(open({str(host_file)!r}).read())")
            assert denied["exit_code"] != 0 and "host-only data" not in denied["stdout"]
            denied = await tools.run_python("import socket")
            assert denied["exit_code"] != 0
            exhausted = await tools.run_python("payload = 'x' * (32 * 1024 * 1024)")
            assert exhausted["exit_code"] != 0
            assert "memory" in exhausted["stderr"].lower(), exhausted
            with monkeypatch.context() as patch:
                patch.setattr("leta.filesystem.tools.MAX_READ_BYTES", 64)
                with pytest.raises(OSError, match="output limit"):
                    await tools.run_shell("printf " + "x" * 65)
            with pytest.raises(TimeoutError):
                await tools.run_shell("sleep 10", timeout_seconds=0.01)
            assert not parent.workspace.processes.live()
            assert "VFS.md" in parent.guidance()
            for command in ("curl http://localhost", "git fetch origin"):
                denied = await tools.run_shell(command)
                assert denied["exit_code"] == 126
            local_git = await tools.run_shell("git status")
            assert local_git["exit_code"] != 126
            assert await tools.semantic_search("not indexed") == []
            async with factory.open(root.id, box.letis[0].id, str(uuid7())) as child:
                child_tools = FilesystemTools(child)
                with pytest.raises(FileNotFoundError):
                    await child_tools.read_file("~/private.txt")
                for path in (
                    "~/report.pdf/report.md",
                    "~/@" + fixture["source_id"] + "/report.md",
                ):
                    assert (
                        "artifact needle" in (await child_tools.read_file(path))["text"]
                    )
                blob = await child_tools.read_file("~/report.pdf")
                assert isinstance(
                    blob, dict
                ) and "private original blob" not in json.dumps(blob)
                image = await child_tools.read_file("~/picture.png")
                assert base64.b64decode(image[1]["base64"]).startswith(b"\x89PNG")
                assert json.loads(image[0]["text"])["width"] == 2
                with pytest.raises(ValueError, match="line selection"):
                    await child_tools.read_file("~/picture.png", start_line=2)
                listing = await child_tools.list_files("~", limit=1)
                assert not listing["complete"] and listing["next_cursor"]
                next_page = await child_tools.list_files(
                    "~", limit=1, cursor=listing["next_cursor"]
                )
                assert next_page["items"][0]["path"] != listing["items"][0]["path"]
                denied = await child_tools.run_shell("cat /home/../private.txt")
                assert denied["exit_code"] != 0
                # Native channels are borrowed: closing a child cannot close them.
            assert (await tools.read_file("~/private.txt"))["text"] == "edited\n"
            page.items[0].rights.write = False
            await parent.refresh()
            with pytest.raises(PermissionError):
                await tools.write_file(
                    "~/private.txt", "cannot overwrite", overwrite=True
                )
            assert (await tools.read_file("~/private.txt"))["text"] == "edited\n"
            page.items[0].rights.write = True
            await parent.refresh()
            await tools.write_file("~/private.txt", "refreshed\n", overwrite=True)
