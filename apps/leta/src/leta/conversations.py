"""Private conversation storage, provisioned only when files are first needed."""

from typing import cast
from uuid import UUID

from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as fs

from .agents import get_agent, json_row, stable
from .auth import Actor, relationship
from .config import Services
from .db import Row
from .messages import conversation


async def storage(s: Services, root: UUID, user: UUID) -> Row:
    await s.auth.require(Actor("user", user), "agent", root, "use")
    agent = await get_agent(s.db, root)
    id = conversation(root, "user", user)
    storage_id = stable(id, "storage")
    async with s.db.connection() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO conversations(id,leta_id,user_id,storage_id) VALUES(%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
            (id, root, user, storage_id),
        )
        row = await (
            await conn.execute(
                "SELECT * FROM conversations WHERE id=%s FOR UPDATE", (id,)
            )
        ).fetchone()
        assert row is not None
        if not row["ready"]:
            # Serialize retries for this conversation; remote writes are idempotent.
            await s.auth.write(
                [
                    relationship("conversation", id, "agent", "agent", root),
                    relationship("conversation", id, "member", "user", user),
                    relationship("conversation", id, "member", "agent", root),
                ]
            )
            await s.storage.CreateStorage(
                internal.CreateStorageRequest(
                    workspace_id=str(agent["workspace_id"]),
                    storage_id=str(storage_id),
                    root_node_id=str(stable(id, "root")),
                    owner=fs.StorageOwnership(conversation_id=str(id)),
                    name=f"Conversation · {agent['name']} · user {user} · {id}",
                    visibility=fs.STORAGE_VISIBILITY_PRIVATE,
                    allow_blob_files=True,
                    allow_indexing=True,
                ),
                timeout=15,
            )
            await conn.execute("UPDATE conversations SET ready=true WHERE id=%s", (id,))
        return {
            **json_row(row),
            "ready": True,
            "root_node_id": str(stable(id, "root")),
            "workspace_id": str(cast(UUID, agent["workspace_id"])),
        }
