from typing import cast
from uuid import uuid4

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]  # Upstream has annotations but no py.typed marker.
from langgraph.prebuilt import ToolNode
from leta.config import Services
from leta.filesystem.workspace import Filesystem
from leta.runtime.inbox import State
from leta.runtime.tools import Context, tools
from mirage import MountMode, Session, Workspace
from mirage.runtime.python.monty import MontyRuntime  # pyright: ignore[reportMissingTypeStubs]  # Upstream package does not publish type stubs.
from pydantic import BaseModel


def test_native_tools_expose_only_agent_arguments() -> None:
    root = {tool.name: tool for tool in tools(root=True)}
    leti = {tool.name: tool for tool in tools(root=False)}
    assert set(root) - set(leti) == {
        "inbox_list",
        "inbox_read",
        "box_create",
        "box_get",
        "box_list",
        "box_delete",
    }
    fields: dict[str, set[str]] = {}
    for tool in root.values():
        schema = tool.tool_call_schema
        assert isinstance(schema, type) and issubclass(schema, BaseModel)
        fields[tool.name] = set(schema.model_fields)
        assert (
            not {
                "runtime",
                "expected_version",
                "timeout_seconds",
                "actor",
                "workspace_id",
            }
            & fields[tool.name]
        )
    assert "target_box_id" in fields["schedule_create"]
    schedule = leti["schedule_create"].tool_call_schema
    assert isinstance(schedule, type) and issubclass(schedule, BaseModel)
    assert "target_box_id" not in schedule.model_fields


async def test_native_toolnode_injects_runtime_and_validates_arguments() -> None:
    builder = StateGraph(State, context_schema=Context)
    builder.add_node("tools", ToolNode(tools(root=False)))  # pyright: ignore[reportUnknownMemberType]  # Native overload leaves cache-policy generics unspecified.
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()  # pyright: ignore[reportUnknownMemberType]  # Native overload leaves checkpoint generics unspecified.
    workspace = Workspace(
        {}, mode=MountMode.EXEC, network=False, runtimes=[MontyRuntime()]
    )
    try:

        class Files:
            async def open(self) -> Session:
                return await workspace.session("tools")

        context = Context(
            services=cast(Services, None),
            agent={},
            run_id=uuid4(),
            filesystem=cast(Filesystem, Files()),
        )
        result = await graph.ainvoke(  # pyright: ignore[reportUnknownMemberType]  # Native overload leaves Command generics unspecified.
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
                                "id": "python",
                                "name": "exec_python",
                                "args": {
                                    "code": 'print({"label": "customer\'s total", "minutes": 42 / (6 * 6) * 60})'
                                },
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
        assert replies["python"].status == "success"
        assert "70.0" in replies["python"].text
        assert "customer's total" in replies["python"].text
        assert replies["invalid"].status == "error"
        assert "start_line" in replies["invalid"].content
    finally:
        await workspace.close()
