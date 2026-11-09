from uuid import uuid4

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from test_engine_compatibility import ScriptedModel

from leta.runtime.state import effect_id


def test_effect_identity_uses_unambiguous_provider_ids():
    agent_id = uuid4()
    assert effect_id(agent_id, "a:b", "c", "tool_result") != effect_id(
        agent_id, "a", "b:c", "tool_result"
    )
    assert effect_id(agent_id, "a:b", "c", "tool_result") == effect_id(
        agent_id, "a:b", "c", "tool_result"
    )


class BarrierState(AgentState):
    marker: str


@pytest.mark.integration
async def test_pinned_middleware_order_and_sync_checkpoint_barriers(postgres_dsn):
    config = {"configurable": {"thread_id": str(uuid4())}}
    order = []

    async with AsyncPostgresSaver.from_conn_string(postgres_dsn) as saver:
        await saver.setup()

        async def barrier(expected, marker):
            saved = await saver.aget(config)
            assert saved["channel_values"].get("marker") == expected
            order.append(marker)
            return {"marker": marker}

        class OpenletBoundary(AgentMiddleware):
            async def abefore_model(self, state, runtime):
                return await barrier(state.get("marker"), "boundary")

        class OpenletSummary(AgentMiddleware):
            async def abefore_model(self, state, runtime):
                return await barrier("boundary", "summary")

        class CollectInbox(AgentMiddleware):
            async def abefore_model(self, state, runtime):
                return await barrier("summary", "inbox")

        class PublishContext(AgentMiddleware):
            async def abefore_model(self, state, runtime):
                return await barrier("inbox", "context")

        class PublishAssistant(AgentMiddleware):
            async def aafter_model(self, state, runtime):
                saved = await saver.aget(config)
                assert saved["channel_values"]["messages"][-1] == state["messages"][-1]
                return await barrier("context", "assistant")

        @tool
        async def effect() -> str:
            """Assert the assistant call has already been committed."""
            saved = await saver.aget(config)
            assert (
                saved["channel_values"]["messages"][-1].tool_calls[0]["id"] == "call-1"
            )
            assert saved["channel_values"]["marker"] == "assistant"
            order.append("tool")
            return "done"

        graph = create_agent(
            ScriptedModel(
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[{"id": "call-1", "name": "effect", "args": {}}],
                    ),
                    AIMessage(content="Saved note"),
                ]
            ),
            tools=[effect],
            middleware=[
                OpenletBoundary(),
                OpenletSummary(),
                CollectInbox(),
                PublishContext(),
                PublishAssistant(),
            ],
            state_schema=BarrierState,
            checkpointer=saver,
        )
        edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
        for edge in [
            ("OpenletBoundary.before_model", "OpenletSummary.before_model"),
            ("OpenletSummary.before_model", "CollectInbox.before_model"),
            ("CollectInbox.before_model", "PublishContext.before_model"),
            ("PublishContext.before_model", "model"),
            ("model", "PublishAssistant.after_model"),
        ]:
            assert edge in edges
        await graph.ainvoke({"messages": []}, config, durability="sync")
        assert order == [
            "boundary",
            "summary",
            "inbox",
            "context",
            "assistant",
            "tool",
            "boundary",
            "summary",
            "inbox",
            "context",
            "assistant",
        ]
