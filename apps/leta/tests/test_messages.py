import json
from datetime import datetime, timezone
from uuid import uuid4

from leta.db import Row
from leta.messages import input_batch, input_data
from openlet_sdk.config import JSON


def test_mixed_input_preserves_short_messages_previews_and_decisions() -> None:
    conversation = uuid4()
    rows: list[Row] = [
        {
            "seq": 1,
            "conversation_id": conversation,
            "source_kind": "user",
            "content": "Older instruction",
        },
        {
            "seq": 2,
            "conversation_id": conversation,
            "source_kind": "user",
            "content": "New  instruction\n" + "x" * 200,
        },
        {
            "seq": 3,
            "conversation_id": uuid4(),
            "source_kind": "hitl",
            "source_id": uuid4(),
            "request_title": "Supplier selection",
            "request_type": "ask",
            "request_payload": {
                "questions": [
                    {
                        "id": "q1",
                        "text": "Which supplier?",
                        "options": [{"id": "o1", "label": "GreenCarton"}],
                    }
                ]
            },
            "content": json.dumps(
                {
                    "status": "answered",
                    "response": {
                        "answers": {
                            "q1": {"option_id": "o1", "note": "Approved within budget"}
                        }
                    },
                }
            ),
        },
        {
            "seq": 4,
            "conversation_id": uuid4(),
            "source_kind": "schedule",
            "source_id": uuid4(),
            "schedule_title": "Purchasing",
            "scheduled_at": datetime(2026, 11, 15, tzinfo=timezone.utc),
            "content": "Original occurrence instruction",
        },
    ]
    for row in rows:
        row["source_name"], row["source_handle"] = "Emma", "emma"
    root = input_batch(rows, root=True)
    assert root.index("message=1") < root.index("message=2")
    assert "Full message:\nOlder instruction" in root
    preview = root.split("\nPreview: ", 1)[1].split("\n", 1)[0]
    assert len(preview) == 120 and preview.endswith("…")
    assert "Answer: GreenCarton\nNote: Approved within budget" in root
    assert root.count("Original occurrence instruction") == 1
    assert (
        root.index("From Emma#emma")
        < root.index("Decision:")
        < root.index("Scheduled task:")
    )
    leti = input_batch(rows, root=False)
    assert leti.index("Older instruction") < leti.index("New  instruction\n")
    assert "x" * 200 in leti
    assert "Preview:" not in leti and "New inbox message" not in leti
    assert "Read full:" not in root
    typed = input_data(rows, root=True)
    items = typed["items"]
    assert isinstance(items, list)
    assert isinstance(items[0], dict) and items[0]["presented"] is True
    assert items[0]["preview"] is False
    assert isinstance(items[1], dict) and items[1]["preview"] is True
    assert len(str(items[1]["content"])) == 120
    assert isinstance(items[2], dict)
    assert items[2]["decision"] == json.loads(str(rows[2]["content"]))
    assert items[2]["request_payload"] == rows[2]["request_payload"]
    assert isinstance(items[3], dict)
    assert items[3]["schedule_title"] == "Purchasing"
    assert items[3]["content"] == "Original occurrence instruction"
    assert items[3]["scheduled_at"] == "2026-11-15T00:00:00+00:00"


def test_short_message_boundary_preserves_original_whitespace_and_recipient() -> None:
    user = uuid4()
    rows: list[Row] = [
        {
            "seq": i,
            "conversation_id": user,
            "source_kind": "user",
            "source_id": user,
            "source_name": "Emma",
            "source_handle": "emma",
            "content": content,
        }
        for i, content in enumerate(("a" * 119, "\n\t" + " " * 118, "x" * 121), 1)
    ]
    body = input_batch(rows, root=True)
    assert "From Emma#emma" in body
    assert "Full message:\n" + str(rows[1]["content"]) in body
    assert body.count("Full message:") == 2
    assert body.count("[truncated; use inbox_read before acting]") == 1
    items = input_data(rows, root=True)["items"]
    assert isinstance(items, list)
    assert [i["preview"] for i in items if isinstance(i, dict)] == [False, False, True]
    assert isinstance(items[1], dict) and items[1]["content"] == rows[1]["content"]


def test_accepted_access_is_not_claimed_granted() -> None:
    from leta.hitl import render

    request: dict[str, JSON] = {
        "id": "request",
        "type": "approval",
        "title": "Personal documents",
        "status": "accepted",
        "payload": {"role": "viewer"},
    }
    assert "grant not confirmed" in render(request)
    request["outcome"] = {"status": "skipped", "reason": "permission_revoked"}
    assert "Access: skipped (permission_revoked)" in render(request)
    request["outcome"] = {"status": "granted"}
    assert "Access: granted" in render(request)


def test_reaction_input_keeps_latest_feedback_without_superseding_ordinary_message() -> (
    None
):
    user, target, conv = uuid4(), uuid4(), uuid4()
    rows: list[Row] = []
    for seq, emoji in enumerate(("👍", "🎉", None), 1):
        rows.append(
            {
                "seq": seq,
                "conversation_id": conv,
                "source_kind": "user",
                "source_id": user,
                "input_type": "reaction",
                "silent": True,
                "content": "Feedback",
                "input_payload": {
                    "target": {
                        "message_id": str(target),
                        "kind": "outgoing",
                        "content": "Quote",
                    },
                    "emoji": emoji,
                },
            }
        )
    rows.append(
        {
            "seq": 4,
            "conversation_id": conv,
            "source_kind": "user",
            "source_id": user,
            "content": "Continue working",
            "source_name": "Emma",
            "source_handle": "emma",
        }
    )
    body = input_batch(rows, root=True)
    assert "👍" not in body and "🎉" not in body
    assert "Emoji: removed" in body and "Continue working" in body
    items = input_data(rows, root=True)["items"]
    assert isinstance(items, list)
    assert [i["presented"] for i in items if isinstance(i, dict)] == [
        False,
        False,
        True,
        True,
    ]


def test_file_only_messages_remain_visible_to_the_receiving_agent() -> None:
    import pytest
    from leta.messages import Message
    from pydantic import ValidationError

    root, sender, storage, node = (uuid4() for _ in range(4))
    attachment: JSON = {
        "storage_id": str(storage),
        "node_id": str(node),
        "label": "report.txt",
    }
    fields = dict(
        id=uuid4(),
        recipient_agent_id=root,
        source_kind="agent",
        source_id=sender,
        conversation_id=uuid4(),
        content="",
    )
    message = Message.model_validate({**fields, "file_refs": [attachment]})
    assert message.content == ""
    with pytest.raises(ValidationError, match="content or attachments"):
        Message.model_validate(fields)
    body = input_batch(
        [
            {
                "seq": 1,
                "source_kind": "agent",
                "reply_to": "scout",
                "content": "",
                "file_refs": [attachment],
            }
        ],
        root=False,
    )
    assert f":file[report.txt]{{name={storage}/{node}}}" in body
