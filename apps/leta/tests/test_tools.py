from typing import cast
from uuid import uuid4

from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.messages.tool import ToolCall
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]  # Upstream has annotations but no py.typed marker.
from langgraph.prebuilt import ToolNode
from leta.config import Services
from leta.filesystem.workspace import Filesystem
from leta.runtime.agent import ToolEffects
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
    assert fields["hitl_request"] == {"user_id", "role", "reason"}
    schedule = leti["schedule_create"].tool_call_schema
    assert isinstance(schedule, type) and issubclass(schedule, BaseModel)
    assert "target_box_id" not in schedule.model_fields


async def test_native_toolnode_injects_runtime_and_validates_arguments() -> None:
    builder = StateGraph(State, context_schema=Context)
    builder.add_node(  # pyright: ignore[reportUnknownMemberType]  # Native overload leaves cache-policy generics unspecified.
        "tools",
        ToolNode(tools(root=False), awrap_tool_call=ToolEffects().awrap_tool_call),
    )
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()  # pyright: ignore[reportUnknownMemberType]  # Native overload leaves checkpoint generics unspecified.
    workspace = Workspace(
        {}, mode=MountMode.EXEC, network=False, runtimes=[MontyRuntime()]
    )
    try:

        class Files:
            bindings = {"read-only": (uuid4(), False), "editable": (uuid4(), True)}

            async def open(self) -> Session:
                return await workspace.session("tools")

        context = Context(
            services=cast(Services, None),
            agent={"id": uuid4()},
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
                                "name": "exec_shell",
                                "args": {
                                    "command": 'python <<\'PY\'\nprint({"label": "customer\'s total", "minutes": 42 / (6 * 6) * 60})\nPY'
                                },
                            },
                            {
                                "id": "invalid",
                                "name": "file_read",
                                "args": {"path": "~", "start_line": 0},
                            },
                            {
                                "id": "failed-shell",
                                "name": "exec_shell",
                                "args": {"command": "false"},
                            },
                            {
                                "id": "failed-python",
                                "name": "exec_shell",
                                "args": {"command": "python -c 'print(1 / 0)'"},
                            },
                            {
                                "id": "mounts",
                                "name": "file_list",
                                "args": {"path": "/mnt"},
                            },
                            {
                                "id": "invalid-calendar",
                                "name": "schedule_create",
                                "args": {
                                    "content": "Review stock",
                                    "calendar": {"weekday": [1]},
                                },
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
        assert replies["failed-shell"].status == "error"
        assert replies["failed-python"].status == "error"
        assert "ZeroDivisionError" in replies["failed-python"].text
        assert '"writable": false' in replies["mounts"].text
        assert '"writable": true' in replies["mounts"].text
        assert replies["invalid-calendar"].status == "error"
        assert "day_of_week" in replies["invalid-calendar"].text
    finally:
        await workspace.close()


async def test_truncated_arguments_cannot_overwrite_an_existing_file() -> None:
    from mirage import Mount
    from mirage.vfs.ram import RAMVFS

    builder = StateGraph(State, context_schema=Context)
    builder.add_node(  # pyright: ignore[reportUnknownMemberType]  # Native overload has unspecified cache generics.
        "tools",
        ToolNode(tools(root=False), awrap_tool_call=ToolEffects().awrap_tool_call),
    )
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()  # pyright: ignore[reportUnknownMemberType]  # Native overload has unspecified checkpoint generics.
    workspace = Workspace(
        {"/home": Mount(vfs=RAMVFS(), mode=MountMode.WRITE)}, network=False
    )
    try:
        session = await workspace.session("tools")
        await session.vfs.write("/home/report.md", b"Complete original report")

        class Files:
            async def open(self) -> Session:
                return session

        identity = uuid4()
        context = Context(
            services=cast(Services, None),
            agent={"id": identity, "leta_id": identity},
            run_id=uuid4(),
            filesystem=cast(Filesystem, Files()),
        )
        message = AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "name": "file_write",
                    "id": "truncated",
                    "index": 0,
                    "args": '{"path":"~/report.md","overwrite":true,"content":"unfinished',
                }
            ],
            response_metadata={"finish_reason": "length"},
        )
        assert message.tool_calls[0]["args"]["content"] == "unfinished"
        result = await graph.ainvoke(  # pyright: ignore[reportUnknownMemberType]  # Native invocation overload.
            {"messages": [message]}, context=context
        )
        error = result["messages"][-1]
        assert isinstance(error, ToolMessage)
        assert (error.name, error.status, error.tool_call_id) == (
            "file_write",
            "error",
            "truncated",
        )
        assert "not executed" in error.text
        assert await session.vfs.read("/home/report.md") == b"Complete original report"
    finally:
        await workspace.close()


async def test_tool_timeout_returns_named_actionable_error() -> None:
    from langgraph.prebuilt.tool_node import ToolCallRequest
    from langgraph.types import Command
    from leta.runtime.tools import exec_shell

    async def timed_out(request: ToolCallRequest) -> ToolMessage | Command[object]:
        raise TimeoutError

    call: ToolCall = {
        "name": "exec_shell",
        "args": {"command": "work"},
        "id": "timeout",
    }
    request = ToolCallRequest(
        tool_call=call,
        tool=exec_shell,
        state={"messages": [AIMessage(content="", tool_calls=[call])]},
        runtime=cast(ToolRuntime[None, dict[str, object]], None),
    )
    result = await ToolEffects().awrap_tool_call(request, timed_out)
    assert isinstance(result, ToolMessage)
    assert (result.name, result.status) == ("exec_shell", "error")
    assert "time limit" in result.text and "inspect" in result.text
