import posixpath
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.messages.tool import ToolCall
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]  # Upstream has annotations but no py.typed marker.
from langgraph.prebuilt import ToolNode
from leta.config import Services
from leta.db import Pool, Row
from leta.filesystem.workspace import Filesystem, StorageMount
from leta.runtime.agent import ToolEffects
from leta.runtime.inbox import State
from leta.runtime.tools import Context, tools
from mirage import MountMode, Session, Workspace
from mirage.runtime.python.monty import MontyRuntime  # pyright: ignore[reportMissingTypeStubs]  # Upstream package does not publish type stubs.
from openlet_sdk.config import JSON
from pydantic import BaseModel


def test_native_tools_expose_only_agent_arguments() -> None:
    root = {tool.name: tool for tool in tools(root=True)}
    leti = {tool.name: tool for tool in tools(root=False)}
    assert set(root) - set(leti) == {
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
    assert "target_box" in fields["schedule_create"]
    assert fields["hitl_request"] == {"user_id", "role", "reason"}
    assert fields["inbox_react"] == {"message", "emoji", "action"}
    assert not any("emote" in name for name in root)
    schedule = leti["schedule_create"].tool_call_schema
    assert isinstance(schedule, type) and issubclass(schedule, BaseModel)
    assert "target_box" not in schedule.model_fields


async def test_native_toolnode_injects_runtime_and_validates_arguments() -> None:
    builder = StateGraph(State, context_schema=Context)
    builder.add_node(  # pyright: ignore[reportUnknownMemberType]  # Native overload leaves cache-policy generics unspecified.
        "tools",
        ToolNode(tools(root=True), awrap_tool_call=ToolEffects().awrap_tool_call),
    )
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()  # pyright: ignore[reportUnknownMemberType]  # Native overload leaves checkpoint generics unspecified.
    workspace = Workspace(
        {},
        mode=MountMode.EXEC,
        network=False,
        runtimes=[MontyRuntime()],
    )
    try:

        class Files:
            bindings = {
                "read-only": StorageMount(uuid4(), False, "Sources"),
                "editable": StorageMount(uuid4(), True, "Working"),
            }

            async def open(self) -> Session:
                return await workspace.session("tools")

        identity = uuid4()

        class Connection:
            async def execute(self, query: str, parameters: object) -> "Connection":
                return self

            async def fetchone(self) -> Row | None:
                return None

        class Database:
            @asynccontextmanager
            async def connection(self) -> AsyncGenerator[Connection]:
                yield Connection()

        context = Context(
            services=cast(Services, SimpleNamespace(db=cast(Pool, Database()))),
            agent={"id": identity, "leta_id": identity},
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
                                "name": "execute",
                                "args": {"command": "printf native"},
                            },
                            {
                                "id": "python",
                                "name": "execute",
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
                                "name": "execute",
                                "args": {"command": "false"},
                            },
                            {
                                "id": "failed-python",
                                "name": "execute",
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
                            {
                                "id": "duplicate-edge",
                                "name": "box_create",
                                "args": {
                                    "name": "review-team",
                                    "letis": [
                                        {"name": "A", "system_prompt": "Analyze."},
                                        {"name": "B", "system_prompt": "Review."},
                                    ],
                                    "edges": [["A", "B"], ["B", "A"]],
                                    "representative": "A",
                                },
                            },
                            {
                                "id": "wrong-recipient",
                                "name": "inbox_send",
                                "args": {
                                    "to": "reviewer",
                                    "content": "Review the quote.",
                                },
                            },
                            {
                                "id": "unsupported-command",
                                "name": "execute",
                                "args": {"command": "openlet-unknown-command"},
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
        assert "Sources — read-only" in replies["mounts"].text
        assert "Working — read/write" in replies["mounts"].text
        assert replies["invalid-calendar"].status == "error"
        assert "day_of_week" in replies["invalid-calendar"].text
        assert replies["duplicate-edge"].status == "error"
        assert "bidirectional" in replies["duplicate-edge"].text
        assert "without also declaring B-A" in replies["duplicate-edge"].text
        assert replies["wrong-recipient"].status == "error"
        assert "recipient not found" in replies["wrong-recipient"].text
        assert replies["unsupported-command"].status == "error"
        assert "command not found" in replies["unsupported-command"].text
        context.agent = {
            "id": uuid4(),
            "leta_id": identity,
            "box_id": uuid4(),
            "representative_agent_id": uuid4(),
        }
        forbidden = await graph.ainvoke(  # pyright: ignore[reportUnknownMemberType]  # Native invocation overload.
            {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "root-contact",
                                "name": "inbox_send",
                                "args": {"to": "root", "content": "Unrouted report"},
                            }
                        ],
                    )
                ]
            },
            context=context,
        )
        blocked = forbidden["messages"][-1]
        assert isinstance(blocked, ToolMessage) and blocked.status == "error"
        assert "Only the representative" in blocked.text
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
    from leta.runtime.tools import execute

    async def timed_out(request: ToolCallRequest) -> ToolMessage | Command[object]:
        raise TimeoutError

    call: ToolCall = {
        "name": "execute",
        "args": {"command": "work"},
        "id": "timeout",
    }
    request = ToolCallRequest(
        tool_call=call,
        tool=execute,
        state={"messages": [AIMessage(content="", tool_calls=[call])]},
        runtime=cast(ToolRuntime[None, dict[str, object]], None),
    )
    result = await ToolEffects().awrap_tool_call(request, timed_out)
    assert isinstance(result, ToolMessage)
    assert (result.name, result.status) == ("execute", "error")
    assert "time limit" in result.text and "inspect" in result.text


def test_box_names_are_path_components_and_root_is_reserved() -> None:
    import pytest
    from leta.boxes import CreateBox
    from pydantic import ValidationError

    fields = {
        "letis": [{"name": "analyst", "system_prompt": "Analyze sources."}],
        "edges": [],
        "representative": "analyst",
    }
    assert (
        CreateBox.model_validate({"name": "quote-review", **fields}).name
        == "quote-review"
    )
    for name in ("Quote Review", "../escape", "review/a", "root", "x" * 65):
        with pytest.raises(ValidationError):
            CreateBox.model_validate({"name": name, **fields})
    with pytest.raises(ValidationError, match="reserved"):
        CreateBox.model_validate(
            {
                "name": "quote-review",
                "letis": [{"name": "root", "system_prompt": "Analyze."}],
                "edges": [],
                "representative": "root",
            }
        )


async def test_search_keeps_ranked_paths_and_caps_multibyte_excerpts() -> None:
    from leta.filesystem.workspace import path as file_path
    from leta.runtime.tools import file_semantic_search
    from mirage import PathSpec

    class VFS:
        async def dispatch(
            self, name: str, scope: PathSpec, **kwargs: object
        ) -> tuple[JSON, None]:
            return {
                "path": scope.virtual,
                "hits": [
                    {
                        "path": scope.virtual + f"/document-{i}.md",
                        "text": "Thông tin báo giá. " * 300,
                    }
                    for i in range(10)
                ],
            }, None

    class Files:
        async def open(self) -> Session:
            return cast(Session, SimpleNamespace(vfs=VFS()))

    identity = uuid4()
    context = Context(
        services=cast(Services, None),
        agent={
            "id": identity,
            "leta_id": identity,
            "workspace_id": uuid4(),
            "box_id": None,
        },
        run_id=uuid4(),
        filesystem=cast(Filesystem, Files()),
    )
    builder = StateGraph(State, context_schema=Context)
    builder.add_node("tools", ToolNode([file_semantic_search]))  # pyright: ignore[reportUnknownMemberType]  # Native overload leaves cache generics unspecified.
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()  # pyright: ignore[reportUnknownMemberType]  # Native overload leaves checkpoint generics unspecified.
    paths = ["~/north", "~/south", "~/shared"]
    result = await graph.ainvoke(  # pyright: ignore[reportUnknownMemberType]  # Native invocation overload.
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "search",
                            "name": "file_semantic_search",
                            "args": {"query": "supplier pricing", "paths": paths},
                        }
                    ],
                )
            ]
        },
        context=context,
    )
    reply = result["messages"][-1]
    assert isinstance(reply, ToolMessage)
    assert len(reply.text.encode()) <= 16384
    assert (
        "[excerpt truncated]" in reply.text
        and "[excerpt omitted; read source]" in reply.text
    )
    excerpt = "Thông tin báo giá. " * 300
    assert excerpt[:1024] + " [excerpt truncated]" in reply.text
    assert excerpt[:1025] not in reply.text
    for path in paths:
        group = reply.text.split(f"Search scope: {file_path(path)}\n\n", 1)[1].split(
            "Search scope:", 1
        )[0]
        positions = [group.index(f"document-{i}.md") for i in range(10)]
        assert positions == sorted(positions)


@pytest.mark.parametrize("image", [False, True])
async def test_file_tool_snapshots_reuse_metadata_without_extra_reads(
    image: bool,
) -> None:
    from leta.runtime.tools import file_edit, file_read, file_write
    from mirage import ContentType, FileStat, FileType

    storage, node = str(uuid4()), str(uuid4())
    metadata = FileStat(
        name="report.txt",
        type=FileType.FILE,
        content=ContentType.IMAGE_PNG if image else ContentType.TEXT,
        extra={
            "storage_id": storage,
            "node_id": node,
            "media_type": "image/png" if image else "text/plain",
        },
    )
    calls: list[str] = []

    class VFS:
        async def stat(self, path: str) -> FileStat:
            calls.append("stat")
            return metadata

        async def read(self, path: str) -> bytes:
            calls.append("read")
            return b"report"

        async def dispatch(
            self, name: str, *args: object, **kwargs: object
        ) -> tuple[object, None]:
            calls.append(name)
            if name == "preview":
                return [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AA=="},
                    }
                ], None
            return metadata, None

    class Files:
        async def open(self) -> Session:
            return cast(Session, SimpleNamespace(vfs=VFS()))

    identity = uuid4()
    context = Context(
        services=cast(Services, None),
        agent={"id": identity, "leta_id": identity},
        run_id=uuid4(),
        filesystem=cast(Filesystem, Files()),
    )
    graph = StateGraph(State, context_schema=Context)
    graph.add_node("tools", ToolNode([file_read, file_write, file_edit]))  # pyright: ignore[reportUnknownMemberType]
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    result = await graph.compile().ainvoke(  # pyright: ignore[reportUnknownMemberType]
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "read",
                            "name": "file_read",
                            "args": {"path": "~/report.txt"},
                        },
                        {
                            "id": "write",
                            "name": "file_write",
                            "args": {"path": "~/report.txt", "content": "report"},
                        },
                        {
                            "id": "edit",
                            "name": "file_edit",
                            "args": {
                                "path": "~/report.txt",
                                "old_text": "report",
                                "new_text": "updated",
                            },
                        },
                    ],
                )
            ]
        },
        context=context,
    )
    replies = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(replies) == 3
    for reply in replies:
        assert reply.status == "success"
        assert reply.artifact["ui"]["data"]["storage_id"] == storage
        assert reply.artifact["ui"]["data"]["node_id"] == node
    assert sorted(calls) == [
        "edit_text",
        "preview" if image else "read",
        "stat",
        "write_text",
    ]
    if image:
        assert replies[0].content == [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}
        ]


@pytest.mark.parametrize(
    ("case", "expected_files"),
    [
        ("mention", 0),
        ("files-only", 2),
        ("mixed", 2),
        ("teammate", 2),
        ("missing", None),
        ("directory", None),
        ("empty", None),
        ("too-many", None),
    ],
)
async def test_inbox_send_paths_and_explicit_attachments(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_files: int | None,
) -> None:
    from unittest.mock import AsyncMock

    from leta import events, messages, worker
    from leta.runtime.tools import inbox_send
    from mirage import FileStat, FileType
    from openlet_api.letfs.v1 import letfs_pb2 as fs

    root, user, storage, one, two, teammate = (uuid4() for _ in range(6))
    nodes = {
        "one.txt": fs.Node(
            id=str(one),
            storage_id=str(storage),
            name="one.txt",
            kind=fs.NODE_KIND_FILE,
            file=fs.FileHeader(media_type="text/plain", size_bytes=3, version=1),
        ),
        "two.png": fs.Node(
            id=str(two),
            storage_id=str(storage),
            name="two.png",
            kind=fs.NODE_KIND_FILE,
            file=fs.FileHeader(media_type="image/png", size_bytes=10, version=1),
        ),
    }

    async def stat(path: str) -> FileStat:
        assert path.startswith("/home/")
        if path.endswith("missing"):
            raise FileNotFoundError("file not found")
        if path.endswith("directory"):
            return FileStat(name="directory", type=FileType.DIRECTORY)
        node = nodes[posixpath.basename(path)]
        return FileStat(
            name=node.name,
            type=FileType.FILE,
            extra={"storage_id": str(storage), "node_id": node.id},
        )

    class Connection:
        async def execute(self, query: str, parameters: object) -> "Connection":
            return self

        async def fetchone(self) -> Row | None:
            return {"id": teammate, "box_id": None} if case == "teammate" else None

    class Database:
        @asynccontextmanager
        async def connection(self) -> AsyncGenerator[Connection]:
            yield Connection()

    async def metadata(request: fs.NodeRequest, **kwargs: object) -> fs.Node:
        return next(
            node for node in nodes.values() if node.id == request.target.node_id
        )

    services = cast(
        Services,
        SimpleNamespace(
            db=Database(),
            redis=None,
            auth=SimpleNamespace(
                require=AsyncMock(), allowed=AsyncMock(return_value=True)
            ),
            files=SimpleNamespace(Stat=AsyncMock(side_effect=metadata)),
        ),
    )
    context = Context(
        services=services,
        agent={"id": root, "leta_id": root, "workspace_id": uuid4(), "box_id": None},
        run_id=uuid4(),
        filesystem=cast(
            Filesystem,
            SimpleNamespace(
                open=AsyncMock(
                    return_value=SimpleNamespace(vfs=SimpleNamespace(stat=stat))
                )
            ),
        ),
    )
    delivered, handoff = AsyncMock(), AsyncMock()
    monkeypatch.setattr(messages, "deliver_user", delivered)
    monkeypatch.setattr(worker, "deliver", handoff)
    monkeypatch.setattr(events, "changed", AsyncMock())
    builder = StateGraph(State, context_schema=Context)
    builder.add_node(  # pyright: ignore[reportUnknownMemberType]  # Native overload leaves cache generics unspecified.
        "tools", ToolNode([inbox_send], awrap_tool_call=ToolEffects().awrap_tool_call)
    )
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()  # pyright: ignore[reportUnknownMemberType]  # Native overload leaves checkpoint generics unspecified.
    arguments: dict[str, object] = {"to": str(user)}
    if case in ("mention", "mixed"):
        arguments["content"] = "Xem :file[Bản mới]{path=~/one.txt}"
    if case in ("files-only", "mixed", "teammate"):
        arguments["attachments"] = ["~/one.txt", "two.png", "/home/one.txt"]
    if case in ("missing", "directory"):
        arguments["attachments"] = ["~/one.txt", "~/" + case]
    if case == "too-many":
        arguments["attachments"] = ["~/one.txt"] * 21
    result = await graph.ainvoke(  # pyright: ignore[reportUnknownMemberType]  # Native invocation overload.
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "send-files",
                            "name": "inbox_send",
                            "args": arguments,
                        }
                    ],
                )
            ]
        },
        context=context,
    )
    reply = result["messages"][-1]
    assert isinstance(reply, ToolMessage)
    if expected_files is None:
        assert reply.status == "error"
        delivered.assert_not_awaited()
        handoff.assert_not_awaited()
        return
    assert reply.status == "success", reply.text
    assert reply.text == '{"sent": true}'
    snapshot = cast(dict[str, dict[str, dict[str, JSON]]], reply.artifact)["ui"]["data"]
    assert isinstance(snapshot["file_refs"], list)
    assert isinstance(snapshot["content"], str)
    assert len(snapshot["file_refs"]) == expected_files
    assert "{path=" not in snapshot["content"]
    if case == "mention":
        assert f"{{name={storage}/{one}}}" in snapshot["content"]
    if case == "teammate":
        assert handoff.await_args is not None
        message = cast(messages.Message, handoff.await_args.args[1])
        assert message.content == "" and len(message.file_refs) == 2
        delivered.assert_not_awaited()
    else:
        assert delivered.await_args is not None
        assert delivered.await_args.args[3] == snapshot["content"]
        assert delivered.await_args.args[-1] == snapshot["file_refs"]
