"""Public transcript contract shared by persistence, owner APIs and AG-UI."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, TypeAdapter

from leta.domain import ID, Input, ReplyTo, Source


class TextBlock(Input):
    type: Literal["text"] = "text"
    text: str


class FileBlock(Input):
    type: Literal["file"] = "file"
    path: str
    media_type: str | None = None


PublicBlock = Annotated[TextBlock | FileBlock, Field(discriminator="type")]


class InboxItem(Input):
    message_id: ID
    seq: int = Field(gt=0)
    source: Source
    conversation_id: str | None
    reply_to: ReplyTo | None
    content: str
    data: dict[str, JsonValue]
    created_at: AwareDatetime

    @classmethod
    def from_row(cls, row):
        return cls(
            message_id=row["id"],
            seq=row["seq"],
            source={
                "type": row["source_type"],
                "id": row["source_id"],
                "label": row["source_label"],
            },
            conversation_id=row["conversation_key"],
            reply_to=row["reply_to"],
            content=row["content"],
            data=row["data"],
            created_at=row["created_at"],
        )


class InboxGroup(Input):
    source: Source
    conversation_id: str | None
    reply_to: ReplyTo | None
    new_count: int = Field(gt=0)
    message_ids: list[ID]
    preview: str


class DigestInput(Input):
    mode: Literal["digest"] = "digest"
    runtime_message_id: str
    cursor_from: int = Field(ge=0)
    cursor_to: int = Field(gt=0)
    groups: list[InboxGroup]


class FullInput(Input):
    mode: Literal["full"] = "full"
    runtime_message_id: str
    cursor_from: int = Field(ge=0)
    cursor_to: int = Field(gt=0)
    items: list[InboxItem]


InboxInput = Annotated[DigestInput | FullInput, Field(discriminator="mode")]
INBOX_INPUT = TypeAdapter(InboxInput)


class ToolCallData(Input):
    id: str
    name: str
    args: dict[str, JsonValue]


class AssistantData(Input):
    llm_message_id: str
    content: list[PublicBlock]
    tool_calls: list[ToolCallData]


class FinalNoteData(Input):
    llm_message_id: str
    content: list[PublicBlock]


class ToolStartedData(Input):
    llm_message_id: str
    tool_call_id: str
    name: str
    args: dict[str, JsonValue]
    started_at: AwareDatetime


class ToolResultData(Input):
    tool_call_id: str
    name: str
    result: list[PublicBlock]
    outcome: Literal["success", "error"]


class CompactionData(Input):
    summary_message_id: str
    summary: str
    replaces_through_message_id: str | None
    retained_message_ids: list[str]


class ActivityBase(Input):
    id: ID
    agent_id: ID
    run_id: ID | None
    seq: int = Field(gt=0)
    created_at: AwareDatetime
    message_id: ID | None = None
    tool_call_id: str | None = None


class InboxEntry(ActivityBase):
    kind: Literal["inbox_input"]
    data: InboxInput


class AssistantEntry(ActivityBase):
    kind: Literal["assistant"]
    data: AssistantData


class FinalNoteEntry(ActivityBase):
    kind: Literal["final_note"]
    data: FinalNoteData


class ToolCallEntry(ActivityBase):
    kind: Literal["tool_call"]
    data: ToolStartedData


class ToolResultEntry(ActivityBase):
    kind: Literal["tool_result"]
    data: ToolResultData


class CompactionEntry(ActivityBase):
    kind: Literal["compaction"]
    data: CompactionData


ActivityEntry = Annotated[
    InboxEntry
    | AssistantEntry
    | FinalNoteEntry
    | ToolCallEntry
    | ToolResultEntry
    | CompactionEntry,
    Field(discriminator="kind"),
]
ACTIVITY_ENTRY = TypeAdapter(ActivityEntry)


def activity_entry(row: dict) -> ActivityEntry:
    value = {key: row[key] for key in ActivityBase.model_fields}
    data = dict(row["data"])
    if row["kind"] == "tool_call":
        data.update(
            llm_message_id=row["llm_message_id"],
            tool_call_id=row["tool_call_id"],
            started_at=row["created_at"],
        )
    elif row["kind"] == "tool_result":
        # Replay keeps the tool message; clients receive its public projection.
        data.pop("message", None)
    return ACTIVITY_ENTRY.validate_python(value | {"kind": row["kind"], "data": data})


def public_content(content: str | list, *, file_path: str | None = None) -> list[dict]:
    """Allowlist public text and authorized file refs; omit reasoning."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    result = []
    for block in content:
        if isinstance(block, str):
            result.append({"type": "text", "text": block})
        elif isinstance(block, dict):
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                result.append({"type": "text", "text": block["text"]})
            elif block.get("type") in {"image", "image_url"} and file_path:
                result.append(
                    {
                        "type": "file",
                        "path": file_path,
                        "media_type": block.get("mime_type"),
                    }
                )
    return result
