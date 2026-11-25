from collections.abc import Awaitable
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from leta import file_refs
from leta.auth import Actor
from leta.config import Services
from openlet_api.letfs.v1 import letfs_pb2 as fs


def test_file_tokens_preserve_custom_labels_and_deduplicate_ids() -> None:
    storage, node = uuid4(), uuid4()
    token = f":file[Budget \\] final]{{name={storage}/{node}}}"
    assert file_refs.references(
        f"Check {token}, again :file[Renamed]{{name={storage}/{node}}}"
    ) == [("Budget ] final", storage, node)]
    assert file_refs.references("Budget.csv /mnt/some/path.txt") == []
    with pytest.raises(ValueError):
        file_refs.references(":file[Bad]{name=not-a-uuid/node}")
    with pytest.raises(ValueError, match="20 files"):
        file_refs.references(
            " ".join(f":file[F]{{name={uuid4()}/{uuid4()}}}" for _ in range(21))
        )


def test_plaintext_replaces_file_tokens_before_preview_truncation() -> None:
    target = f"{uuid4()}/{uuid4()}"
    token = f":file[Budget \\] final]{{name={target}}}"
    content = f"Check {token} and :file[Notes.md]{{name={target}}} " + "tail " * 60
    plain = file_refs.plaintext(content)
    assert plain.startswith("Check Budget ] final and Notes.md tail ")
    assert len(plain[:240]) == 240
    assert ":file[" not in plain[:240] and "{name=" not in plain[:240]
    assert file_refs.plaintext("/mnt/files/report.txt") == "/mnt/files/report.txt"


async def test_reference_checks_both_actors_before_reading_metadata() -> None:
    sender, recipient = Actor("user", uuid4()), Actor("agent", uuid4())
    storage, node, workspace = uuid4(), uuid4(), uuid4()
    auth = SimpleNamespace(
        require=AsyncMock(side_effect=[None, PermissionError("private")])
    )
    files = SimpleNamespace(Stat=AsyncMock())
    s = cast(Services, SimpleNamespace(auth=auth, files=files))
    with pytest.raises(PermissionError):
        await file_refs.validate(
            s, workspace, sender, recipient, f":file[budget]{{name={storage}/{node}}}"
        )
    assert auth.require.await_count == 2
    files.Stat.assert_not_awaited()
    auth.require.side_effect = None
    files.Stat.return_value = fs.Node(
        id=str(node),
        storage_id=str(storage),
        name="Budget.csv",
        kind=fs.NODE_KIND_FILE,
        file=fs.FileHeader(media_type="text/csv", size_bytes=32, version=3),
    )
    assert await file_refs.validate(
        s, workspace, sender, recipient, f":file[estimate]{{name={storage}/{node}}}"
    ) == [
        {
            "storage_id": str(storage),
            "node_id": str(node),
            "label": "estimate",
            "name": "Budget.csv",
            "mime": "text/csv",
            "size": 32,
            "version": 3,
        }
    ]


async def test_conversation_membership_drives_storage_permissions() -> None:
    import os
    from pathlib import Path

    import grpc
    from authzed.api.v1 import WriteSchemaRequest, WriteSchemaResponse
    from authzed.api.v1.schema_service_pb2_grpc import SchemaServiceStub
    from leta.auth import Authorization, relationship

    target = os.environ.get("OPENLET_FILE_TEST_AUTHZ")
    if not target:
        pytest.skip("Set OPENLET_FILE_TEST_AUTHZ to disposable SpiceDB")
    channel = grpc.aio.insecure_channel(target)
    auth = Authorization.__new__(Authorization)
    auth.channel = channel
    from authzed.api.v1.permission_service_pb2_grpc import PermissionsServiceStub

    auth.stub = PermissionsServiceStub(channel)
    auth.metadata = (("authorization", "Bearer files"),)
    try:
        await cast(
            Awaitable[WriteSchemaResponse],
            SchemaServiceStub(channel).WriteSchema(
                WriteSchemaRequest(
                    schema=(
                        Path(__file__).parents[3]
                        / "packages/contracts/authz/schema.zed"
                    ).read_text()
                ),
                metadata=auth.metadata,
            ),
        )
        workspace, root, owner, user, other, conversation, storage = (
            uuid4() for _ in range(7)
        )
        relationships = [
            relationship("workspace", workspace, "owner", "user", owner),
            relationship("workspace", workspace, "member", "user", user),
            relationship("workspace", workspace, "member", "user", other),
            relationship("workspace", workspace, "agent", "agent", root),
            relationship("agent", root, "workspace", "workspace", workspace),
            relationship("agent", root, "owner", "user", owner),
            relationship("agent", root, "operator", "user", user),
            relationship("agent", root, "operator", "user", other),
            relationship("conversation", conversation, "agent", "agent", root),
            relationship("conversation", conversation, "member", "user", user),
            relationship("conversation", conversation, "member", "agent", root),
            relationship("storage", storage, "workspace", "workspace", workspace),
            relationship(
                "storage", storage, "conversation", "conversation", conversation
            ),
        ]
        await auth.write(relationships)
        for actor in [Actor("user", user), Actor("agent", root)]:
            assert await auth.allowed(actor, "storage", storage, "read")
            assert await auth.allowed(actor, "storage", storage, "write")
            assert not await auth.allowed(actor, "storage", storage, "manage_access")
        for id in [owner, other]:
            assert not await auth.allowed(Actor("user", id), "storage", storage, "read")
            assert not await auth.allowed(
                Actor("user", id), "storage", storage, "write"
            )
        await auth.write(
            [relationship("agent", root, "operator", "user", user)], delete=True
        )
        assert not await auth.allowed(Actor("user", user), "storage", storage, "read")
        assert not await auth.allowed(Actor("user", user), "storage", storage, "write")
        assert await auth.allowed(Actor("agent", root), "storage", storage, "read")
    finally:
        await channel.close()


async def test_paths_resolve_without_turning_mentions_into_attachments() -> None:
    from mirage import FileStat, FileType

    storage, node = uuid4(), uuid4()
    stat = AsyncMock(
        return_value=FileStat(
            name="Bản [cuối].txt",
            type=FileType.FILE,
            extra={"storage_id": str(storage), "node_id": str(node)},
        )
    )
    content, attached = await file_refs.resolve(
        r"Xem [Bản \[cuối\]](<~/thư mục/file (1).txt>) và [web](https://example.com) và ![img](/shared/pic.png)",
        [],
        stat,
    )
    assert file_refs.references(content) == [("Bản [cuối]", storage, node)]
    assert "[web](https://example.com)" in content
    assert "![img](/shared/pic.png)" in content
    assert attached == ""
    stat.assert_awaited_once_with("~/thư mục/file (1).txt")
    stat.reset_mock()
    content, attached = await file_refs.resolve(
        "Xem [Doc](/shared/q3/report.pdf)", [], stat
    )
    assert file_refs.references(content) == [("Doc", storage, node)]
    stat.assert_awaited_once_with("/shared/q3/report.pdf")
    content, attached = await file_refs.resolve("", ["~/one.txt", "~/two.txt"], stat)
    assert content == ""
    assert file_refs.references(attached) == [("Bản [cuối].txt", storage, node)]


@pytest.mark.parametrize(
    "kind,extra",
    [
        ("directory", {}),
        ("file", {}),
    ],
)
async def test_path_attachments_reject_nonstored_nodes(
    kind: str, extra: dict[str, str]
) -> None:
    from mirage import FileStat, FileType

    stat = AsyncMock(
        return_value=FileStat(name="invalid", type=FileType(kind), extra=extra)
    )
    with pytest.raises(ValueError, match="stored file"):
        await file_refs.resolve("", ["~/invalid"], stat)


async def test_private_files_copy_to_conversation_without_granting_source_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from leta import conversations

    sender, recipient = Actor("agent", uuid4()), Actor("user", uuid4())
    storage, node, destination, copied, parent, workspace, request = (
        uuid4() for _ in range(7)
    )
    source = fs.Node(
        id=str(node),
        storage_id=str(storage),
        name="report.txt",
        kind=fs.NODE_KIND_FILE,
        file=fs.FileHeader(media_type="text/plain", size_bytes=4, version=7),
    )
    result = fs.Node(
        id=str(copied),
        storage_id=str(destination),
        name="report.txt",
        kind=fs.NODE_KIND_FILE,
        file=fs.FileHeader(media_type="text/plain", size_bytes=4, version=1),
    )
    files = SimpleNamespace(
        Stat=AsyncMock(return_value=source),
        CopyNode=AsyncMock(return_value=result),
        CreateDirectories=AsyncMock(return_value=fs.Node(id=str(parent))),
    )
    auth = SimpleNamespace(
        require=AsyncMock(), allowed=AsyncMock(return_value=False), write=AsyncMock()
    )
    services = cast(Services, SimpleNamespace(auth=auth, files=files))
    provision = AsyncMock(
        return_value={
            "storage_id": str(destination),
            "root_node_id": str(uuid4()),
            "zed_token": "causal-token",
        }
    )
    monkeypatch.setattr(conversations, "storage", provision)
    for _ in range(2):
        refs = await file_refs.validate(
            services,
            workspace,
            sender,
            recipient,
            file_refs.token("Report", str(storage), str(node)),
            copy_request=request,
        )
        assert refs == [
            {
                "storage_id": str(destination),
                "node_id": str(copied),
                "label": "Report",
                "name": "report.txt",
                "mime": "text/plain",
                "size": 4,
                "version": 1,
            }
        ]
    calls = files.CopyNode.await_args_list
    assert calls[0].args[0].request_id == calls[1].args[0].request_id
    assert calls[0].args[0].parent.node_id == str(parent)
    assert ("x-openlet-zed-token", "causal-token") in calls[0].kwargs["metadata"]
    assert files.CreateDirectories.await_args.args[0].path == "attachments"
    provision.assert_awaited_with(services, sender.id, recipient.id)
    auth.write.assert_not_called()
    auth.require.reset_mock(side_effect=True)
    auth.require.side_effect = PermissionError("source denied")
    files.CopyNode.reset_mock()
    with pytest.raises(PermissionError, match="source denied"):
        await file_refs.validate(
            services,
            workspace,
            sender,
            recipient,
            file_refs.token("Report", str(storage), str(node)),
            copy_request=request,
        )
    files.CopyNode.assert_not_awaited()


async def test_invalid_batch_is_rejected_before_copying_any_file() -> None:
    sender, recipient = Actor("agent", uuid4()), Actor("user", uuid4())
    storage, node, directory = uuid4(), uuid4(), uuid4()
    files = SimpleNamespace(
        Stat=AsyncMock(
            side_effect=[
                fs.Node(id=str(node), kind=fs.NODE_KIND_FILE),
                fs.Node(id=str(directory), kind=fs.NODE_KIND_DIRECTORY),
            ]
        ),
        CopyNode=AsyncMock(),
    )
    services = cast(
        Services,
        SimpleNamespace(
            files=files,
            auth=SimpleNamespace(
                require=AsyncMock(), allowed=AsyncMock(return_value=False)
            ),
        ),
    )
    with pytest.raises(ValueError, match="Copy the folder only if authorized"):
        await file_refs.validate(
            services,
            uuid4(),
            sender,
            recipient,
            file_refs.token("File", str(storage), str(node))
            + file_refs.token("Directory", str(storage), str(directory)),
            copy_request=uuid4(),
        )
    files.CopyNode.assert_not_awaited()


async def test_flat_attachments_suffix_on_collision_preserves_idempotency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import grpc
    from leta import conversations
    from leta.agents import stable

    class FakeAlreadyExists(grpc.aio.AioRpcError):
        def __init__(self) -> None:
            pass

        def code(self) -> grpc.StatusCode:
            return grpc.StatusCode.ALREADY_EXISTS

    sender, recipient = Actor("agent", uuid4()), Actor("user", uuid4())
    storage, node, destination, copied, parent, workspace, request = (
        uuid4() for _ in range(7)
    )
    expected_tag = stable(request, f"attachment/{storage}/{node}/dedup").hex[:8]
    expected_name = f"report ({expected_tag}).txt"
    source = fs.Node(
        id=str(node),
        storage_id=str(storage),
        name="report.txt",
        kind=fs.NODE_KIND_FILE,
        file=fs.FileHeader(media_type="text/plain", size_bytes=4, version=2),
    )
    dedup_result = fs.Node(
        id=str(copied),
        storage_id=str(destination),
        name=expected_name,
        kind=fs.NODE_KIND_FILE,
        file=fs.FileHeader(media_type="text/plain", size_bytes=4, version=1),
    )
    files = SimpleNamespace(
        Stat=AsyncMock(return_value=source),
        CopyNode=AsyncMock(
            side_effect=[
                FakeAlreadyExists(),
                dedup_result,
                FakeAlreadyExists(),
                dedup_result,
            ]
        ),
        CreateDirectories=AsyncMock(return_value=fs.Node(id=str(parent))),
    )
    auth = SimpleNamespace(
        require=AsyncMock(), allowed=AsyncMock(return_value=False), write=AsyncMock()
    )
    services = cast(Services, SimpleNamespace(auth=auth, files=files))
    monkeypatch.setattr(
        conversations,
        "storage",
        AsyncMock(
            return_value={
                "storage_id": str(destination),
                "root_node_id": str(uuid4()),
                "zed_token": "causal-token",
            }
        ),
    )

    for _ in range(2):
        refs = await file_refs.validate(
            services,
            workspace,
            sender,
            recipient,
            file_refs.token("Report", str(storage), str(node)),
            copy_request=request,
        )
        assert isinstance(refs[0], dict)
        assert refs[0]["name"] == expected_name

    calls = files.CopyNode.await_args_list
    assert calls[0].args[0].name == "report.txt"
    assert calls[1].args[0].name == expected_name
    assert calls[1].args[0].request_id == calls[3].args[0].request_id
    assert calls[0].args[0].request_id != calls[1].args[0].request_id
