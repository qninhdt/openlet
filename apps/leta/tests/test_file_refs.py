from types import SimpleNamespace
from typing import cast
from collections.abc import Awaitable
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
