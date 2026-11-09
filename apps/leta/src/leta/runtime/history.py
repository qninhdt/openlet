"""Journal committed graph output; owner authorization stays at the API boundary."""

import json
from uuid import UUID

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage

from leta.domain import ActivityKind, NewActivity
from leta.history import INBOX_INPUT, activity_entry, public_content
from leta.runtime.state import LetaAgentState, RuntimeContext, effect_id


async def record(context, kind, message_id, data, tool_call_id=""):
    identity = effect_id(context.request.agent_id, message_id, tool_call_id, kind)
    saved = await context.store.append_activity(
        NewActivity(
            id=identity,
            agent_id=context.request.agent_id,
            run_id=context.request.run_id,
            kind=kind,
            llm_message_id=message_id,
            tool_call_id=tool_call_id or None,
            dedup_key=str(identity),
            data=data,
        )
    )
    await context.publish_entry(saved)
    return activity_entry(saved)


class PublishContext(AgentMiddleware[LetaAgentState, RuntimeContext]):
    async def abefore_model(self, state, runtime):
        context, changes = runtime.context, {}
        messages = state["messages"]
        if messages:
            first = messages[0]
            metadata = first.additional_kwargs.get("openlet", {})
            if metadata.get("kind") == "compaction" and first.id != state.get(
                "published_summary_id"
            ):
                await record(
                    context, ActivityKind.COMPACTION, first.id, metadata["payload"]
                )
                changes["published_summary_id"] = first.id
            last = messages[-1]
            metadata = last.additional_kwargs.get("openlet", {})
            if (
                isinstance(last, HumanMessage)
                and metadata.get("kind") == "inbox_input"
                and last.id != state.get("published_input_id")
            ):
                payload = INBOX_INPUT.validate_python(metadata["payload"])
                await record(
                    context,
                    ActivityKind.INBOX_INPUT,
                    last.id,
                    payload.model_dump(mode="json"),
                )
                changes["published_input_id"] = last.id
        return changes or None


class PublishAssistant(AgentMiddleware[LetaAgentState, RuntimeContext]):
    async def aafter_model(self, state, runtime):
        message = state["messages"][-1]
        if not isinstance(message, AIMessage) or not message.id:
            raise ValueError("committed assistant message required")
        data = {
            "llm_message_id": message.id,
            "content": public_content(message.content),
        }
        kind = ActivityKind.FINAL_NOTE
        if message.tool_calls:
            kind = ActivityKind.ASSISTANT
            data["tool_calls"] = [
                {key: call[key] for key in ("id", "name", "args")}
                for call in message.tool_calls
            ]
        await record(runtime.context, kind, message.id, data)
        return None


async def search_history(context, query=None, limit=20, cursor=None):
    if cursor is not None and (not cursor.isascii() or not cursor.isdecimal()):
        raise ValueError("invalid history cursor")
    found = await context.store.search_activity(
        context.request.leta_id,
        context.request.agent_id,
        query=query,
        before=int(cursor) if cursor else None,
        limit=limit,
    )
    page = found[:limit]
    return {
        "items": [
            {**row, "id": str(row["id"]), "created_at": row["created_at"].isoformat()}
            for row in page
        ],
        "next_cursor": str(page[-1]["seq"]) if len(found) > limit else None,
    }


async def read_history(context, entry_id, start_line=1, max_lines=200):
    if start_line < 1 or not 1 <= max_lines <= 10000:
        raise ValueError("invalid history line range")
    row = await context.store.get_activity(
        context.request.leta_id, context.request.agent_id, UUID(entry_id)
    )
    entry = activity_entry(row).model_dump(mode="json")
    lines = json.dumps(entry.pop("data"), ensure_ascii=False, indent=2).splitlines()
    selected = lines[start_line - 1 : start_line - 1 + max_lines]
    return {
        "entry": entry,
        "content": "\n".join(selected),
        "start_line": start_line,
        "total_lines": len(lines),
        "complete": start_line - 1 + len(selected) >= len(lines),
    }
