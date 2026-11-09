from types import SimpleNamespace

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool
from openlet.errors import AppError
from test_human_requests_integration import ask
from test_messaging import context
from test_store_integration import active_box, active_root

from leta.runtime.human import get_hitl, list_hitl
from leta.runtime.tools import build_tools

pytestmark = pytest.mark.integration


async def test_request_tools_limit_children_to_self_and_root_can_select_a_box(store):
    root = await active_root(store)
    box = await active_box(store, root)
    parent = await context(store, root, root.id, None)
    child = await context(store, root, box.letis[0].id, None)
    for agent_id in (root.id, box.letis[0].id, box.letis[1].id):
        await store.create_request(
            ask(root).model_copy(update={"requester_agent_id": agent_id})
        )
    page = await list_hitl(parent)
    assert len(page["items"]) == 1
    assert page["items"][0]["requester_agent_id"] == str(root.id)
    page = await list_hitl(parent, box=box.name, limit=1, status="pending")
    next_page = await list_hitl(
        parent, box=str(box.id), limit=1, cursor=page["next_cursor"]
    )
    assert len(next_page["items"]) == 1 and next_page["next_cursor"] is None
    assert page["items"][0]["id"] != next_page["items"][0]["id"]
    assert len((await list_hitl(child))["items"]) == 1
    with pytest.raises(AppError, match="only its requests"):
        await list_hitl(child, box=box.name)
    sibling_request = next(
        row
        for row in next_page["items"] + page["items"]
        if row["requester_agent_id"] != str(child.request.agent_id)
    )
    with pytest.raises(AppError, match="only its requests"):
        await get_hitl(child, sibling_request["id"])
    assert (await get_hitl(parent, sibling_request["id"]))["leta_id"] == root.id


async def test_actual_openai_schema_keeps_human_actor_and_grantee_out_of_model_input(
    store,
):
    root = await active_root(store)
    parent = await context(store, root, root.id, None)
    parent.workspace = SimpleNamespace(session=None)
    tools = {
        item.name: convert_to_openai_tool(item)["function"]["parameters"]
        for item in build_tools(parent)
    }
    ask_schema = tools["ask_user"]
    assert set(ask_schema["properties"]) == {"title", "questions", "timeout_seconds"}
    question = ask_schema["properties"]["questions"]["items"]
    assert {
        variant["properties"]["type"]["const"] for variant in question["oneOf"]
    } == {"single_choice", "multiple_choice", "text"}
    access = tools["request_access"]["properties"]
    assert set(access) == {"resource", "role", "reason", "timeout_seconds"}
    assert set(access["resource"]["properties"]) == {"type", "user_id"}
    assert access["role"]["enum"] == ["viewer", "editor"]
    assert "answer_user" not in tools and "approve" not in tools
