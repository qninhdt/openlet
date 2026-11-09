import asyncio
import json
import posixpath
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from ag_ui.core import TextMessageContentEvent
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    SummarizationMiddleware,
)
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from mirage import Workspace
from mirage.cache.file.config import RedisCacheConfig
from mirage.cache.index.config import RedisIndexConfig
from mirage.runtime.python import MontyRuntime
from mirage.types import FileStat, FileType, MountMode
from mirage.vfs import RAMVFS, BaseVFS
from psycopg import AsyncConnection
from redis.asyncio import Redis
from temporal_fixtures import MessagePassingFixture
from temporalio.client import WithStartWorkflowOperation
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.worker import Worker


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class CursorState(AgentState):
    inbox_cursor: int


class InboxFixture(AgentMiddleware):
    state_schema = CursorState

    async def abefore_model(self, state, runtime):
        if state.get("inbox_cursor", 0) < 7:
            return {
                "inbox_cursor": 7,
                "messages": [
                    HumanMessage(
                        content="New inbox input",
                        additional_kwargs={"inbox_input": {"message_ids": ["fixture"]}},
                    )
                ],
            }
        return None


@pytest.mark.integration
async def test_sync_saver_before_effect_and_resume(postgres_dsn):
    config = {"configurable": {"thread_id": str(uuid4())}}
    async with await AsyncConnection.connect(
        postgres_dsn, autocommit=True
    ) as connection:
        await connection.execute("CREATE TABLE effects (value text NOT NULL)")

    @tool
    async def perform_effect() -> str:
        """Perform a real test effect after the tool call is durable."""
        async with AsyncPostgresSaver.from_conn_string(postgres_dsn) as reader:
            saved = await reader.aget(config)
            assert saved["channel_values"]["messages"][-1].tool_calls[0]["name"] == (
                "perform_effect"
            )
        async with await AsyncConnection.connect(postgres_dsn, autocommit=True) as conn:
            await conn.execute("INSERT INTO effects VALUES ('done')")
        return "effect complete"

    call = AIMessage(
        content="",
        tool_calls=[{"name": "perform_effect", "args": {}, "id": "call-fixture"}],
    )
    async with AsyncPostgresSaver.from_conn_string(postgres_dsn) as saver:
        await saver.setup()
        agent = create_agent(
            ScriptedModel(responses=[call]),
            tools=[perform_effect],
            middleware=[InboxFixture()],
            checkpointer=saver,
            interrupt_after=["tools"],
        )
        await agent.ainvoke(
            {"messages": [HumanMessage(content="Start")]}, config, durability="sync"
        )

    async with AsyncPostgresSaver.from_conn_string(postgres_dsn) as saver:
        agent = create_agent(
            ScriptedModel(responses=[AIMessage(content="Short continuation note")]),
            tools=[perform_effect],
            middleware=[InboxFixture()],
            checkpointer=saver,
        )
        result = await agent.ainvoke(None, config, durability="sync")
        assert result["inbox_cursor"] == 7
        assert all(isinstance(message, BaseMessage) for message in result["messages"])
        assert len([m for m in result["messages"] if isinstance(m, ToolMessage)]) == 1
        typed_input = next(
            m for m in result["messages"] if m.additional_kwargs.get("inbox_input")
        )
        assert typed_input.additional_kwargs["inbox_input"]["message_ids"] == [
            "fixture"
        ]
    async with await AsyncConnection.connect(postgres_dsn) as connection:
        cursor = await connection.execute("SELECT count(*) FROM effects")
        assert await cursor.fetchone() == (1,)


@pytest.mark.integration
async def test_public_compaction_and_cursor_reload(postgres_dsn):
    config = {"configurable": {"thread_id": str(uuid4())}}
    summary = SummarizationMiddleware(
        ScriptedModel(
            responses=[AIMessage(content="Fixture summary: preserve the task")]
        ),
        trigger=("messages", 4),
        keep=("messages", 2),
    )
    async with AsyncPostgresSaver.from_conn_string(postgres_dsn) as saver:
        await saver.setup()
        agent = create_agent(
            ScriptedModel(responses=[AIMessage(content="Short note")]),
            middleware=[InboxFixture(), summary],
            checkpointer=saver,
        )
        messages = [
            cls(content=f"Previous exchange {i}")
            for i in range(5)
            for cls in (HumanMessage, AIMessage)
        ]
        await agent.ainvoke({"messages": messages}, config, durability="sync")
    async with AsyncPostgresSaver.from_conn_string(postgres_dsn) as saver:
        checkpoint = await saver.aget(config)
        state = checkpoint["channel_values"]
        assert state["inbox_cursor"] == 7
        assert len(state["messages"]) < len(messages)
        assert any("Fixture summary" in m.content for m in state["messages"])
        assert all(isinstance(m, BaseMessage) for m in state["messages"])


class ArtifactFixture(BaseVFS):
    """The backend resolves an original file ID just as LetFS will."""

    name = "leta-artifact-fixture"
    caches_reads = True
    files = {
        "docs/report.pdf": b"blob metadata only",
        "docs/report.pdf/report.md": b"report content\n",
        "docs/report.pdf/images/chart.txt": b"nested artifact\n",
    }
    directories = {"", "docs", "docs/report.pdf/images"}

    @staticmethod
    def canonical(path):
        return path.vfs_path.strip("/").replace(
            "@original-file-id", "docs/report.pdf", 1
        )

    async def stat(self, path):
        key = self.canonical(path)
        if key in self.files:
            return FileStat(
                name=posixpath.basename(key),
                type=FileType.FILE,
                size=len(self.files[key]),
                fingerprint="fixture-v1",
            )
        if key in self.directories:
            return FileStat(name=posixpath.basename(key), type=FileType.DIRECTORY)
        raise FileNotFoundError(key)

    async def readdir(self, path):
        key = self.canonical(path)
        entries = []
        for child in sorted(set(self.files) | self.directories):
            if child and posixpath.dirname(child) == key:
                entries.append(
                    FileStat(
                        name=posixpath.basename(child),
                        type=FileType.FILE
                        if child in self.files
                        else FileType.DIRECTORY,
                        size=len(self.files[child]) if child in self.files else None,
                        fingerprint="fixture-v1",
                    )
                )
        return entries

    async def read(self, path):
        return self.files[self.canonical(path)]


async def test_mirage_file_parent_artifact_paths():
    workspace = Workspace({"/home": ArtifactFixture()}, network=False)
    try:
        workspace.create_session("compatibility")
        assert (await workspace.stat("/home/docs/report.pdf")).type == FileType.FILE
        for source in ("/home/docs/report.pdf", "/home/@original-file-id"):
            result = await workspace.tools.read(source + "/report.md")
            assert not result.is_error, result.text
            assert "report content" in result.text
            result = await workspace.tools.read(source + "/images/chart.txt")
            assert not result.is_error, result.text
            assert "nested artifact" in result.text
            result = await workspace.tools.shell("cat " + source + "/report.md")
            assert not result.is_error, result.text
            assert "report content" in result.text
            result = await workspace.tools.ls(source + "/images")
            assert not result.is_error, result.text
            assert "chart.txt" in result.text
    finally:
        await workspace.close()


@pytest.mark.integration
async def test_monty_isolation_redis_cache_and_agui(redis_url, monkeypatch, tmp_path):
    monkeypatch.setenv("LETA_HOST_SECRET", "host-only")
    host_file = tmp_path / "host-only.txt"
    host_file.write_text("host-only data")
    workspace = Workspace(
        {
            "/": (RAMVFS(), MountMode.EXEC),
            "/home": (RAMVFS(), MountMode.WRITE),
            "/artifacts": ArtifactFixture(),
        },
        network={"allowed_domains": [urlsplit(redis_url).netloc]},
        runtimes=[MontyRuntime(config={"max_memory": "16MB"})],
        env={"HOME": "/home"},
        cache=RedisCacheConfig(url=redis_url, key_prefix="leta:compat:cache"),
        index=RedisIndexConfig(url=redis_url, key_prefix="leta:compat:index"),
    )
    try:
        result = await workspace.tools.write("/home/input.txt", "mounted content")
        assert not result.is_error, result.text
        result = await workspace.tools.shell(
            "python -c 'print(open(\"/home/input.txt\").read())'"
        )
        assert not result.is_error, result.text
        assert "mounted content" in result.text
        result = await workspace.tools.shell(
            f"python -c 'print(open(\"{host_file}\").read())'"
        )
        assert result.is_error and "host-only data" not in result.text
        result = await workspace.tools.shell(
            "python -c 'import os; "
            'print(os.environ.get("LETA_HOST_SECRET", "absent"))\''
        )
        assert not result.is_error and "absent" in result.text, result.text
        result = await workspace.tools.shell("python -c 'import socket'")
        assert result.is_error, result.text
        for _ in range(2):
            result = await workspace.tools.read("/artifacts/docs/report.pdf/report.md")
            assert not result.is_error and "report content" in result.text, result.text
        async with Redis.from_url(redis_url) as redis:
            keys = [key async for key in redis.scan_iter(match="*leta:compat:*")]
            assert any(b"cache" in key for key in keys)
            assert any(b"index" in key for key in keys)
            root, child, run = (str(uuid4()) for _ in range(3))
            event = TextMessageContentEvent(message_id="message-1", delta="hello")
            envelope = {
                "leta_id": root,
                "agent_id": child,
                "run_id": run,
                "event": event.model_dump(mode="json", by_alias=True),
            }
            stream = f"leta:{root}:events"
            cursor = await redis.xadd(stream, {"data": json.dumps(envelope)})
            records = await redis.xrange(stream, min=cursor, max=cursor)
            restored = json.loads(records[0][1][b"data"])
            assert restored == envelope
            assert (
                TextMessageContentEvent.model_validate(restored["event"]).delta
                == "hello"
            )
    finally:
        await workspace.close()


async def test_temporal_update_with_start(temporal_environment):
    client = temporal_environment.client
    queue = "leta-compat-" + uuid4().hex
    operation = WithStartWorkflowOperation(
        MessagePassingFixture.run,
        id=queue,
        task_queue=queue,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    async with Worker(client, task_queue=queue, workflows=[MessagePassingFixture]):
        async with asyncio.timeout(20):
            result = await client.execute_update_with_start_workflow(
                MessagePassingFixture.receive,
                "fixture input",
                start_workflow_operation=operation,
            )
            assert result == "fixture input"
            handle = await operation.workflow_handle()
            assert await handle.result() == "fixture input"
