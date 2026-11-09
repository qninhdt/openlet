"""Offline recovery preserves canonical grants and uses owner lifecycle data."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from authzed.api.v1 import RelationshipUpdate
from test_domain import root_input
from test_store_integration import active_box, active_root

from leta.rebuild import rebuild

pytestmark = pytest.mark.integration


async def test_rebuild_retains_archived_home_but_never_restores_editor_grants(store):
    workspaces = sorted(uuid7() for _ in range(3))
    roots = []
    for workspace in workspaces:
        root = root_input(workspace_id=workspace)
        await store.create_leta(root)
        await store.activate_leta(root.id)
        await store.begin_delete(root.id)
        await store.archive(root.id)
        roots.append(root)
    graph = SimpleNamespace(WriteRelationships=AsyncMock(), _openlet_metadata=())
    inventory = [
        json.dumps({"workspace_id": str(id), "status": status})
        for id, status in zip(
            workspaces, ["active", "deleting", "deleted"], strict=True
        )
    ]
    await rebuild(store, graph, inventory)
    updates = [
        item
        for call in graph.WriteRelationships.call_args_list
        for item in call.args[0].updates
    ]
    touched = {
        (
            item.relationship.resource.object_type,
            item.relationship.resource.object_id,
            item.relationship.relation,
        )
        for item in updates
        if item.operation == RelationshipUpdate.OPERATION_TOUCH
    }
    assert touched == {
        ("leta", str(roots[0].id), "workspace"),
        ("leta", str(roots[0].id), "creator"),
        ("scope", str(roots[0].home_scope_id), "home_of"),
    }
    assert (
        len(
            [
                item
                for item in updates
                if item.operation == RelationshipUpdate.OPERATION_DELETE
            ]
        )
        == 4
    )
    assert all(
        item.relationship.relation not in {"viewer", "editor"} for item in updates
    )
    # Omitted interior workspaces cannot silently pass recovery validation.
    with pytest.raises(ValueError, match="incomplete"):
        await rebuild(store, graph, [inventory[0], inventory[2]])


async def test_startup_rejects_saved_model_and_inherited_reasoning_conflict(store):
    root = await active_root(store)
    box = await active_box(store, root)
    await store.verify_models()
    async with store.transaction() as cursor:
        await cursor.execute(
            "UPDATE agents SET model_id='removed/model' WHERE id=%s", (box.letis[0].id,)
        )
    with pytest.raises(ValueError, match="unsupported"):
        await store.verify_models()
