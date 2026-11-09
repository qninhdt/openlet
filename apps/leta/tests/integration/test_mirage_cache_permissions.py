import asyncio
import json
import os
from uuid import UUID

import pytest
from authzed.api.v1 import (
    ObjectReference,
    Relationship,
    RelationshipUpdate,
    SubjectReference,
    WriteRelationshipsRequest,
)
from mirage import Workspace
from mirage.cache.file.config import RedisCacheConfig
from mirage.policy import Policy
from mirage.types import MountMode, ReadPolicy, ReadSpec
from openlet.authz import AuthorizationClient
from openlet.clients.letfs import FilesystemClient
from openlet.rpc import Actor, RpcClient
from psycopg import AsyncConnection
from redis.asyncio import Redis

from leta.filesystem.access_policy import AccessPolicy, cache_network
from leta.filesystem.letfs_vfs import LetFSVFS, Mount
from leta.filesystem.workspace import AGENT_PROFILE


class BetweenReads(Policy):
    def __init__(self):
        self.enabled = False
        self.first_read, self.updated = asyncio.Event(), asyncio.Event()

    async def post_vfs(self, ctx):
        if (
            self.enabled
            and ctx.call.name == "read"
            and ctx.path.virtual.endswith("cache.txt")
        ):
            self.enabled = False
            self.first_read.set()
            await self.updated.wait()


@pytest.mark.integration
async def test_real_redis_fresh_external_write_and_revocation(redis_url):
    raw = os.getenv("OPENLET_TEST_LETFS_FIXTURE")
    if not raw:
        pytest.skip("run TestIntegrationMirageLetFS with OPENLET_MIRAGE_INTEGRATION=1")
    fixture = json.loads(raw)
    actor = Actor("leta", UUID(fixture["leta_id"]))
    async with RpcClient(
        fixture["address"], fixture["token"], allow_plaintext=True
    ) as rpc:
        native = FilesystemClient(rpc)
        mount = Mount(
            fixture["filesystem_id"],
            fixture["scope_id"],
            fixture["root_id"],
            "/home",
            True,
        )
        policy = AccessPolicy({"/home": LetFSVFS(native, actor, mount)})
        between = BetweenReads()
        workspace = Workspace(
            {"/home": (policy.backends["/home"], MountMode.WRITE)},
            cache=RedisCacheConfig(url=redis_url, key_prefix="leta:real-cache:"),
            read=ReadSpec(policy=ReadPolicy.FRESH),
            policies=[policy, between],
            profiles={"agent": AGENT_PROFILE},
            profile="agent",
            network=cache_network(redis_url),
        )
        policy.cache = workspace.cache
        other = Workspace(
            {"/home": (LetFSVFS(native, actor, mount), MountMode.WRITE)}, network=False
        )
        graph = AuthorizationClient(
            fixture["graph_address"], fixture["graph_key"], allow_plaintext=True
        )
        relation = Relationship(
            resource=ObjectReference(object_type="scope", object_id=mount.scope_id),
            relation="editor",
            subject=SubjectReference(
                object=ObjectReference(object_type="leta", object_id=fixture["leta_id"])
            ),
        )
        try:
            session = await workspace.session("cache-permissions")
            write = await other.tools.write("/home/cache.txt", "before\n")
            assert not write.is_error, write.text
            assert await session.vfs.read("/home/cache.txt") == b"before\n"
            assert await workspace.cache.get_versioned("/home/cache.txt") is not None
            write = await other.tools.write("/home/cache.txt", "after\n")
            assert not write.is_error, write.text
            assert await session.vfs.read("/home/cache.txt") == b"after\n"

            async def external_write():
                await between.first_read.wait()
                try:
                    write = await other.tools.write("/home/cache.txt", "during\n")
                    assert not write.is_error, write.text
                finally:
                    between.updated.set()

            between.enabled = True
            async with asyncio.timeout(5), asyncio.TaskGroup() as group:
                group.create_task(external_write())
                result = await session.tools.shell(
                    "cat /home/cache.txt; cat /home/cache.txt"
                )
            assert not result.is_error and result.text == "after\nduring\n", result.text

            metadata = await session.vfs.read("/home/report.pdf")
            old_token = (await workspace.cache.get_versioned("/home/report.pdf"))[1]
            async with await AsyncConnection.connect(
                fixture["database_url"], autocommit=True
            ) as connection:
                await connection.execute(
                    "UPDATE nodes SET revision=revision+1 WHERE parent_id=%s",
                    (UUID(fixture["source_id"]),),
                )
            changed = await session.vfs.read("/home/report.pdf")
            assert changed != metadata
            assert json.loads(changed)["revision"] == json.loads(metadata)["revision"]
            assert (await workspace.cache.get_versioned("/home/report.pdf"))[
                1
            ] != old_token
            blocked = await session.tools.shell("curl http://127.0.0.1:6379")
            assert blocked.is_error, blocked.text
            async with Redis.from_url(redis_url) as redis:
                keys = [key async for key in redis.scan_iter(match="leta:real-cache:*")]
                assert keys
            # Interrupt the real cache without replacing its implementation.
            async with Redis.from_url(redis_url) as redis:
                await redis.config_set("requirepass", "owned-cache-fixture-password")
                await redis.execute_command(
                    "CLIENT", "KILL", "TYPE", "normal", "SKIPME", "yes"
                )
            try:
                with pytest.raises(OSError, match="Redis cache unavailable"):
                    await session.vfs.read("/home/cache.txt")
            finally:
                async with Redis.from_url(
                    redis_url, password="owned-cache-fixture-password"
                ) as admin:
                    await admin.config_set("requirepass", "")
            await graph.WriteRelationships(
                WriteRelationshipsRequest(
                    updates=[
                        RelationshipUpdate(
                            operation=RelationshipUpdate.OPERATION_DELETE,
                            relationship=relation,
                        )
                    ]
                ),
                metadata=graph._openlet_metadata,
            )
            with pytest.raises(PermissionError):
                await session.vfs.read("/home/cache.txt")
            result = await session.tools.shell("cat /home/cache.txt")
            assert result.is_error and "after" not in result.text
        finally:
            await graph.WriteRelationships(
                WriteRelationshipsRequest(
                    updates=[
                        RelationshipUpdate(
                            operation=RelationshipUpdate.OPERATION_TOUCH,
                            relationship=relation,
                        )
                    ]
                ),
                metadata=graph._openlet_metadata,
            )
            await graph.close()
            await workspace.close()
            await other.close()
