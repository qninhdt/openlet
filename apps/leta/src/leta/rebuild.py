"""Offline derived relationships; direct grants remain canonical in SpiceDB."""

import argparse
import asyncio
import json
import sys
from uuid import UUID

from authzed.api.v1 import (
    ObjectReference,
    Relationship,
    RelationshipUpdate,
    SubjectReference,
    WriteRelationshipsRequest,
)
from openlet.authz import AuthorizationClient
from psycopg_pool import AsyncConnectionPool

from leta.config import Settings
from leta.domain import Lifecycle
from leta.store import Store
from leta.temporal.lifecycle_activities import leta_resource_updates


async def rebuild(store, graph, workspaces):
    after = UUID(int=0)
    processed = 0
    for line in workspaces:
        value = json.loads(line)
        workspace_id = UUID(value["workspace_id"])
        status = value["status"]
        if (
            set(value) != {"workspace_id", "status"}
            or workspace_id <= after
            or status not in {"active", "deleting", "deleted"}
        ):
            raise ValueError("invalid owner workspace inventory")
        after, cursor = workspace_id, None
        while True:
            async with store.transaction() as query:
                await query.execute(
                    "SELECT * FROM agents WHERE kind='leta' AND workspace_id=%s "
                    "AND (%s::uuid IS NULL OR id>%s) ORDER BY id LIMIT 100",
                    (workspace_id, cursor, cursor),
                )
                roots = await query.fetchall()
            processed += len(roots)
            for root in roots:
                updates = leta_resource_updates(root, remove=status != "active")
                if status == "active" and root["status"] != Lifecycle.INITIALIZING:
                    updates.append(
                        RelationshipUpdate(
                            operation=RelationshipUpdate.OPERATION_TOUCH,
                            relationship=Relationship(
                                resource=ObjectReference(
                                    object_type="scope",
                                    object_id=str(root["home_scope_id"]),
                                ),
                                relation="home_of",
                                subject=SubjectReference(
                                    object=ObjectReference(
                                        object_type="leta", object_id=str(root["id"])
                                    )
                                ),
                            ),
                        )
                    )
                await graph.WriteRelationships(
                    WriteRelationshipsRequest(updates=updates),
                    metadata=graph._openlet_metadata,
                    timeout=5,
                )
            if len(roots) < 100:
                break
            cursor = roots[-1]["id"]
    # Missing owner records cannot be treated as permission to recreate a resource.
    async with store.database.connection() as connection:
        row = await (
            await connection.execute("SELECT count(*) FROM agents WHERE kind='leta'")
        ).fetchone()
    if row[0] != processed:
        raise ValueError("workspace inventory is incomplete")


async def main():
    settings = Settings.from_env()
    graph = AuthorizationClient(
        settings.spicedb_address,
        settings.spicedb_key,
        allow_plaintext=settings.allow_plaintext,
    )
    try:
        async with AsyncConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=2,
            open=False,
            kwargs={"autocommit": True},
        ) as database:
            await database.wait(timeout=5)
            store = Store(database, settings.models)
            await store.verify_models()
            await rebuild(store, graph, sys.stdin)
    finally:
        await graph.close()


if __name__ == "__main__":
    argparse.ArgumentParser(
        description="Rebuild Leta relationships from Workspace JSON lines on stdin"
    ).parse_args()
    asyncio.run(main())
