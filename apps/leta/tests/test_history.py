import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import ValidationError
from test_runtime import RecordingModel

from leta.config import ModelCatalog
from leta.history import ACTIVITY_ENTRY, INBOX_INPUT, activity_entry, public_content
from leta.runtime import middleware as middleware_module
from leta.runtime.middleware import OpenletSummary


def test_public_blocks_strip_provider_private_fields_and_image_bytes():
    marker = "PRIVATE_REASONING_SENTINEL"
    content = [
        {"type": "reasoning", "text": marker},
        {"type": "thinking", "thinking": marker},
        {"type": "text", "text": "Public answer", "provider_secret": marker},
        {"type": "image", "mime_type": "image/png", "base64": "private-bytes"},
        {"type": "unknown", "text": marker},
    ]
    assert public_content(content) == [{"type": "text", "text": "Public answer"}]
    projected = public_content(content, file_path="/shared/report.pdf/chart.png")
    assert projected[-1] == {
        "type": "file",
        "path": "/shared/report.pdf/chart.png",
        "media_type": "image/png",
    }
    assert marker not in json.dumps(projected) and "private-bytes" not in json.dumps(
        projected
    )
    # Public data can mention reasoning without being a provider-private block.
    assert public_content("Explain reasoning") == [
        {"type": "text", "text": "Explain reasoning"}
    ]


def test_inbox_contract_uses_metadata_and_discriminated_variants():
    source = {"type": "some.future.source", "id": "source-1", "label": "Future"}
    digest = {
        "mode": "digest",
        "runtime_message_id": "input-1",
        "cursor_from": 0,
        "cursor_to": 1,
        "groups": [
            {
                "source": source,
                "conversation_id": None,
                "reply_to": None,
                "new_count": 1,
                "message_ids": [str(uuid7())],
                "preview": "Preview",
            }
        ],
    }
    assert INBOX_INPUT.validate_python(digest).model_dump(mode="json") == digest
    with pytest.raises(ValidationError):
        INBOX_INPUT.validate_python(digest | {"items": []})


def test_activity_projection_excludes_internal_replay_and_natural_key():
    row = {
        "id": uuid7(),
        "agent_id": uuid7(),
        "run_id": uuid7(),
        "seq": 5,
        "created_at": datetime.now(UTC),
        "message_id": None,
        "tool_call_id": "call-1",
        "llm_message_id": "assistant-1",
        "dedup_key": "internal",
        "kind": "tool_result",
        "data": {
            "tool_call_id": "call-1",
            "name": "read_file",
            "outcome": "success",
            "result": [
                {"type": "file", "path": "/shared/chart.png", "media_type": "image/png"}
            ],
            "message": {"type": "tool", "data": {"content": "image replay body"}},
        },
    }
    entry = activity_entry(row)
    data = entry.model_dump(mode="json")
    assert "message" not in data["data"] and "dedup_key" not in data
    assert "image replay body" not in entry.model_dump_json()
    assert ACTIVITY_ENTRY.validate_json(entry.model_dump_json()) == entry


async def test_summary_sanitizes_prior_messages_before_inference(
    catalog_data, monkeypatch
):
    marker = "UNIQUE_PRIOR_PROVIDER_REASONING"
    model = RecordingModel(responses=[AIMessage(content="Not a normal model call")])
    catalog_data["models"][0]["context_window_tokens"] = 10000
    catalog = ModelCatalog.model_validate(catalog_data)
    context = SimpleNamespace(
        models=catalog,
        selection=catalog.default,
        tools=[],
        system_prompt=lambda: "Agent instructions",
        model_factory=lambda selection: model,
    )
    messages = [
        HumanMessage(id="old-input", content="A" * 3400),
        AIMessage(
            id="old-assistant",
            content=[
                {"type": "reasoning", "text": marker},
                {"type": "text", "text": "B" * 3400},
            ],
            additional_kwargs={"reasoning_content": marker},
            tool_calls=[
                {
                    "id": "old-call",
                    "name": "read_file",
                    "args": {"path": "/shared/result.txt"},
                }
            ],
        ),
        ToolMessage(
            id="old-tool",
            tool_call_id="old-call",
            name="read_file",
            content="C" * 3400,
            additional_kwargs={"provider_private": marker},
        ),
        HumanMessage(id="recent-input", content="D" * 3400),
    ]
    assert marker in str(messages)

    async def no_input(state, context):
        return None

    monkeypatch.setattr(middleware_module, "prepare_input", no_input)
    update = await OpenletSummary().abefore_model(
        {"messages": messages}, SimpleNamespace(context=context)
    )
    assert update and len(model.summary_calls) == 1
    prompt = "\n".join(message.content for message in model.summary_calls[0][1:])
    assert marker not in prompt
    assert "old-call" in str(model.summary_calls) and "/shared/result.txt" in str(
        model.summary_calls
    )
    for text in ("A" * 3400, "B" * 3400, "C" * 3400):
        assert text in prompt
    assert marker not in str(update)


def test_typed_activity_fixtures_cover_reload_and_duplicate_events():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/activity-entries.json").read_text()
    )
    entries = [ACTIVITY_ENTRY.validate_python(item) for item in fixture["entries"]]
    assert {entry.kind for entry in entries} == {
        "inbox_input",
        "assistant",
        "tool_call",
        "tool_result",
        "final_note",
        "compaction",
    }
    assert {entry.data.mode for entry in entries if entry.kind == "inbox_input"} == {
        "digest",
        "full",
    }
    saved = {str(entry.id): entry for entry in entries}
    rendered = {identity: saved[identity] for identity in fixture["replayed_entry_ids"]}
    assert list(rendered) == fixture["reload_entry_ids"]


async def test_quote_heavy_prefix_is_not_double_encoded(catalog_data, monkeypatch):
    model = RecordingModel(responses=[AIMessage(content="Not called normally")])
    catalog_data["models"][0]["context_window_tokens"] = 10000
    catalog = ModelCatalog.model_validate(catalog_data)
    context = SimpleNamespace(
        models=catalog,
        selection=catalog.default,
        tools=[],
        system_prompt=lambda: "Agent instructions",
        model_factory=lambda selection: model,
    )

    async def no_input(state, context):
        return None

    monkeypatch.setattr(middleware_module, "prepare_input", no_input)
    messages = [
        HumanMessage(id="old", content='"' * 13000),
        HumanMessage(id="recent", content="r" * 1000),
    ]
    update = await OpenletSummary().abefore_model(
        {"messages": messages}, SimpleNamespace(context=context)
    )
    assert update and len(model.summary_calls) == 1
    assert model.summary_calls[0][1].content == '"' * 13000
