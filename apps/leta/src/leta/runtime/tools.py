"""Only implemented capabilities are exposed to the model."""

from datetime import datetime
from typing import Literal

from google.protobuf.json_format import MessageToDict
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from leta.domain import SchedulePatch
from leta.filesystem.tools import FilesystemTools
from leta.human import Question
from leta.runtime import boxes, history, human, messaging, schedules
from leta.runtime.state import LetaAgentState, RuntimeContext, effect_id
from leta.schedules import ScheduleInputSpec


def build_tools(context: RuntimeContext):
    filesystem = FilesystemTools(context.workspace)

    def identity(runtime, kind):
        assistant = next(
            item
            for item in reversed(runtime.state["messages"])
            if isinstance(item, AIMessage)
            and any(call["id"] == runtime.tool_call_id for call in item.tool_calls)
        )
        return effect_id(
            context.request.agent_id, assistant.id, runtime.tool_call_id, kind
        )

    @tool
    async def send_message(
        to: str,
        content: str,
        runtime: ToolRuntime[RuntimeContext, LetaAgentState],
        in_reply_to: str | None = None,
    ) -> dict:
        """Send to an allowed recipient ID or exact name; final notes do not send."""
        return await messaging.send_message(
            context, identity(runtime, "message"), to, content, in_reply_to
        )

    @tool
    async def create_box(
        name: str,
        description: str,
        letis: list[boxes.LetiDefinition],
        edges: list[tuple[str, str]],
        representative: str,
        runtime: ToolRuntime[RuntimeContext, LetaAgentState],
    ) -> dict:
        """Create an immutable communication box; send its work separately."""
        return await boxes.create_box(
            context,
            identity(runtime, "box"),
            name,
            description,
            letis,
            edges,
            representative,
        )

    @tool
    async def ask_user(
        title: str,
        questions: list[Question],
        runtime: ToolRuntime[RuntimeContext, LetaAgentState],
        timeout_seconds: int | None = None,
    ) -> dict:
        """Ask the Leta creator a form; return pending and continue other work."""
        return await human.ask_user(
            context, identity(runtime, "hitl"), title, questions, timeout_seconds
        )

    @tool
    async def request_access(
        resource: human.PersonalResource,
        runtime: ToolRuntime[RuntimeContext, LetaAgentState],
        role: Literal["viewer", "editor"] = "viewer",
        reason: str = "",
        timeout_seconds: int | None = None,
    ) -> dict:
        """Ask a human resource owner to grant root Leta personal-scope access."""
        return await human.request_access(
            context, identity(runtime, "hitl"), resource, role, reason, timeout_seconds
        )

    @tool
    async def list_hitl(
        status: Literal["pending", "resolved", "cancelled", "expired"] | None = None,
        box: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict:
        """List own human requests; root Leta may select one of its boxes."""
        return await human.list_hitl(context, status, box, limit, cursor)

    @tool
    async def get_hitl(request_id: str) -> dict:
        """Inspect a human request, its decision and actual resource outcome."""
        return human.projection(await human.get_hitl(context, request_id))

    @tool
    async def cancel_hitl(request_id: str, reason: str = "") -> dict:
        """Cancel a pending request; accepted access cannot be cancelled."""
        return await human.cancel_hitl(context, request_id, reason)

    @tool
    async def create_schedule(
        title: str,
        content: str,
        spec: ScheduleInputSpec,
        runtime: ToolRuntime[RuntimeContext, LetaAgentState],
        target: str = "self",
        end_at: datetime | None = None,
    ) -> dict:
        """Schedule inbox input once, at an interval or by calendar fields."""
        return await schedules.create_schedule(
            context,
            identity(runtime, "schedule"),
            title,
            content,
            spec.model_dump(mode="json"),
            target,
            end_at,
        )

    @tool
    async def list_schedules(
        box: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict:
        """List own schedules; root Leta may select one of its boxes."""
        return await schedules.list_schedules(context, box, limit, cursor)

    @tool
    async def get_schedule(schedule_id: str) -> dict:
        """Read a schedule and its bounded upcoming forecast when available."""
        return await schedules.get_schedule(context, schedule_id)

    @tool
    async def update_schedule(
        schedule_id: str,
        runtime: ToolRuntime[RuntimeContext, LetaAgentState],
        title: str | None = None,
        content: str | None = None,
        spec: ScheduleInputSpec | None = None,
        end_at: datetime | None = None,
        paused: bool | None = None,
    ) -> dict:
        """Edit supplied fields; null end_at clears cutoff; paused pauses/resumes."""
        supplied = next(
            call["args"]
            for message in reversed(runtime.state["messages"])
            if isinstance(message, AIMessage)
            for call in message.tool_calls
            if call["id"] == runtime.tool_call_id
        )
        values = {
            "title": title,
            "content": content,
            "spec": spec.model_dump(mode="json") if spec is not None else None,
            "end_at": end_at,
            "paused": paused,
        }
        patch = SchedulePatch.model_validate(
            {k: v for k, v in values.items() if k in supplied}
        )
        return await schedules.update_schedule(
            context, identity(runtime, "schedule-change"), schedule_id, patch
        )

    @tool
    async def delete_schedule(
        schedule_id: str,
        runtime: ToolRuntime[RuntimeContext, LetaAgentState],
    ) -> dict:
        """Delete a schedule without retracting committed inbox messages."""
        return await schedules.delete_schedule(
            context, identity(runtime, "schedule-change"), schedule_id
        )

    @tool
    async def list_boxes(limit: int = 20, cursor: str | None = None) -> dict:
        """List owned boxes and counts without opening their agents' transcripts."""
        return await boxes.list_boxes(context, limit, cursor)

    @tool
    async def get_box(box: str) -> dict:
        """Inspect a box by ID or live name, including its graph and pending work."""
        return await boxes.get_box(context, box)

    @tool
    async def delete_box(box: str) -> dict:
        """Stop and archive the whole box, trashing its home after runners stop."""
        return await boxes.delete_box(context, box)

    @tool
    async def search_history(
        query: str | None = None, limit: int = 20, cursor: str | None = None
    ) -> dict:
        """Search this agent's public transcript, or list recent entries."""
        return await history.search_history(context, query, limit, cursor)

    @tool
    async def read_history(
        entry_id: str, start_line: int = 1, max_lines: int = 200
    ) -> dict:
        """Read one public transcript entry of this agent, with line paging."""
        return await history.read_history(context, entry_id, start_line, max_lines)

    @tool
    async def get_workspace() -> dict:
        """Inspect identity, mounts, model and allowed message recipients."""
        workspace = await context.scopes.get_workspace(
            str(context.root["workspace_id"]), actor=context.workspace.actor
        )
        return {
            "workspace": MessageToDict(workspace, preserving_proto_field_name=True),
            "leta_id": str(context.request.leta_id),
            "agent_id": str(context.request.agent_id),
            **context.selection.model_dump(),
            "mounts": [
                {"path": prefix, "read": True, "write": backend.mount.writable}
                for prefix, backend in sorted(context.workspace.policy.backends.items())
            ],
            "messaging_roster": await messaging.messaging_roster(context),
        }

    @tool
    async def list_workspace_members(
        limit: int = 20, cursor: str | None = None
    ) -> dict:
        """List active humans for scope requests; does not open a chat route."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        result = await context.scopes.list_members(
            str(context.root["workspace_id"]),
            actor=context.workspace.actor,
            limit=limit,
            cursor=cursor,
        )
        return MessageToDict(result, preserving_proto_field_name=True)

    @tool
    async def list_files(
        path: str = "~", depth: int = 1, limit: int = 100, cursor: str | None = None
    ) -> dict:
        """List file metadata under a permitted virtual path."""
        return await filesystem.list_files(path, depth, limit, cursor)

    @tool(response_format="content_and_artifact")
    async def read_file(
        path: str, start_line: int = 1, max_lines: int = 200
    ) -> tuple[dict | list, dict]:
        """Read text, blob metadata/artifact tree, or an authorized image."""
        resolved = filesystem.path(path).virtual
        return await filesystem.read_file(resolved, start_line, max_lines), {
            "file_path": resolved,
        }

    @tool
    async def write_file(path: str, content: str, overwrite: bool = False) -> dict:
        """Create or replace small inline UTF-8 text through the mounted filesystem."""
        return await filesystem.write_file(path, content, overwrite)

    @tool
    async def edit_file(
        path: str, old_text: str, new_text: str, replace_all: bool = False
    ) -> dict:
        """Replace exact text; the default requires exactly one occurrence."""
        return await filesystem.edit_file(path, old_text, new_text, replace_all)

    @tool
    async def run_shell(
        command: str, cwd: str = "~", timeout_seconds: int = 30
    ) -> dict:
        """Run Mirage virtual shell commands in permitted mounts, never host Bash."""
        return await filesystem.run_shell(command, cwd, timeout_seconds)

    @tool
    async def run_python(code: str, timeout_seconds: int = 30) -> dict:
        """Run Python in Monty with the same mounts and no host access."""
        return await filesystem.run_python(code, timeout_seconds)

    @tool
    async def semantic_search(
        query: str, paths: list[str] | None = None, limit: int = 10
    ) -> list[dict]:
        """Search permitted files semantically; paths narrow readable mounts."""
        return await filesystem.semantic_search(query, paths, limit)

    @tool(args_schema=messaging.InboxQuery.model_json_schema())
    async def list_inbox(**arguments) -> dict:
        """List inbox conversations with source, counts and short previews."""
        query = messaging.InboxQuery.model_validate(arguments)
        return await messaging.list_inbox(context, **query.model_dump())

    @tool(response_format="content_and_artifact")
    async def read_inbox(
        conversation_id: str,
        unread_only: bool = True,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[dict, dict]:
        """Read one inbox conversation and mark only the returned items read."""
        result = await messaging.read_inbox(
            context, conversation_id, unread_only, limit, cursor, mark_read=False
        )
        return result, {
            "read_message_ids": [item["message_id"] for item in result["items"]]
        }

    tools = [
        send_message,
        ask_user,
        request_access,
        list_hitl,
        get_hitl,
        cancel_hitl,
        create_schedule,
        list_schedules,
        get_schedule,
        update_schedule,
        delete_schedule,
        get_workspace,
        list_workspace_members,
        search_history,
        read_history,
        list_files,
        read_file,
        write_file,
        edit_file,
        run_shell,
        run_python,
        semantic_search,
    ]
    if context.agent["kind"] == "leta":
        tools.extend(
            [list_inbox, read_inbox, create_box, list_boxes, get_box, delete_box]
        )
    return tools
