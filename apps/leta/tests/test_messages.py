import json
from datetime import datetime, timezone
from uuid import uuid4

from leta.db import Row
from leta.messages import input_batch
from openlet_sdk.config import JSON


def test_mixed_input_groups_only_notifications_and_preserves_decisions() -> None:
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
    root = input_batch(rows, root=True)
    assert "message=1" not in root and "message=2" in root
    preview = root.split("message=2\nPreview: ", 1)[1].split("\n", 1)[0]
    assert len(preview) == 120 and preview.endswith("…")
    assert "Answer: GreenCarton\nNote: Approved within budget" in root
    assert root.count("Original occurrence instruction") == 1
    assert (
        root.index("New inbox message from User")
        < root.index("Decision:")
        < root.index("Scheduled task:")
    )
    leti = input_batch(rows, root=False)
    assert leti.index("Older instruction") < leti.index("New  instruction\n")
    assert "x" * 200 in leti
    assert "Preview:" not in leti and "New inbox message" not in leti
    assert "Read full:" not in root


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
