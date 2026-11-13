from typing import cast
from uuid import uuid4

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from leta.config import Services
from leta.filesystem.workspace import Filesystem
from leta.runtime.inbox import State
from leta.runtime.tools import Context, tools
from mirage import Workspace


def test_native_tools_expose_only_agent_arguments() -> None:
    root = {tool.name: tool for tool in tools(root=True)}
    leti = {tool.name: tool for tool in tools(root=False)}
    assert len(root) == 28
    assert len(leti) == 22
    assert set(root) - set(leti) == {
        "inbox_list",
        "inbox_read",
        "box_create",
        "box_get",
        "box_list",
        "box_delete",
    }
    for tool in root.values():
        fields = tool.tool_call_schema.model_json_schema()["properties"]
        assert (
            not {
                "runtime",
                "expected_version",
                "timeout_seconds",
                "actor",
                "workspace_id",
            }
            & fields.keys()
        )
    assert (
        "target_box_id"
        in root["schedule_create"].tool_call_schema.model_json_schema()["properties"]
    )
    assert (
        "target_box_id"
        not in leti["schedule_create"].tool_call_schema.model_json_schema()[
            "properties"
        ]
    )


async def test_native_toolnode_injects_runtime_and_validates_arguments() -> None:
    builder = StateGraph(State, context_schema=Context)
    builder.add_node("tools", ToolNode(tools(root=False)))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()
    workspace = Workspace({}, network=False)
    try:
        context = Context(
            services=cast(Services, None),
            agent={},
            run_id=uuid4(),
            filesystem=cast(Filesystem, None),
            session=await workspace.session("tools"),
        )
        result = await graph.ainvoke(
            {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "shell",
                                "name": "exec_shell",
                                "args": {"command": "printf native"},
                            },
                            {
                                "id": "invalid",
                                "name": "file_read",
                                "args": {"path": "~", "start_line": 0},
                            },
                        ],
                    )
                ]
            },
            context=context,
        )
        replies = {
            message.tool_call_id: message
            for message in result["messages"]
            if isinstance(message, ToolMessage)
        }
        assert replies["shell"].status == "success"
        assert "native" in replies["shell"].content
        assert replies["invalid"].status == "error"
        assert "start_line" in replies["invalid"].content
    finally:
        await workspace.close()
