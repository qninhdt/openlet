from uuid import UUID, uuid7

import pytest
from pydantic import ValidationError

from leta.domain import (
    AgentConfiguration,
    LetiSpec,
    NewBox,
    NewHumanRequest,
    NewLeta,
    NewMessage,
    NewSchedule,
    Source,
    box_slug,
)


def root_input(**changes):
    return NewLeta.model_validate(
        {
            "id": uuid7(),
            "workspace_id": uuid7(),
            "created_by_user_id": uuid7(),
            "home_scope_id": uuid7(),
            "name": "Leta",
            "system_prompt": "Assist owner",
            "model": {"model_id": "provider/model", "reasoning_effort": None},
            **changes,
        }
    )


def box_input(leta_id, **changes):
    return NewBox.model_validate(
        {
            "id": uuid7(),
            "leta_id": leta_id,
            "home_node_id": uuid7(),
            "name": "Research team",
            "letis": [
                LetiSpec(id=uuid7(), name="Researcher", system_prompt="Research"),
                LetiSpec(id=uuid7(), name="Writer", system_prompt="Write"),
            ],
            "edges": [("Researcher", "Writer")],
            "representative": "Researcher",
            **changes,
        }
    )


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Research team", "research-team"),
        ("Báo cáo", "báo-cáo"),
        ("Ｒｅｐｏｒｔ", "report"),
        ("v1.2 / report", "v1-2-report"),
    ],
)
def test_slug_has_no_separate_identity(name, slug):
    assert box_slug(name) == slug


@pytest.mark.parametrize("name", ["", " ", "..", "///", "---", "___"])
def test_empty_slug_is_rejected(name):
    with pytest.raises(ValueError):
        box_slug(name)


@pytest.mark.parametrize(
    "changes",
    [
        {"id": UUID(int=0)},
        {"name": "  "},
        {"name": " leading"},
        {"name": "line\nbreak"},
        {"owner_account_id": str(uuid7())},
    ],
)
def test_root_identity_and_name_validation(changes):
    with pytest.raises(ValidationError):
        root_input(**changes)


def test_box_graph_accepts_disconnected_agents_and_rejects_invalid_edges():
    root = uuid7()
    box = box_input(root)
    assert box_input(root, edges=[]).edges == []
    for changes in (
        {"representative": "Unknown"},
        {"edges": [("Researcher", "Unknown")]},
        {"edges": [("Writer", "Writer")]},
        {"edges": [("Researcher", "Writer"), ("Writer", "Researcher")]},
        {"letis": [box.letis[0], box.letis[0]]},
        {"letis": [box.letis[0].model_copy(update={"id": root})]},
    ):
        with pytest.raises(ValidationError):
            box_input(root, **changes)


@pytest.mark.parametrize(
    "patch",
    [
        {"name": None},
        {"description": None},
        {"system_prompt": None},
        {"name": " leading"},
        {"name": "line\nbreak"},
    ],
)
def test_configuration_preserves_profile_validation(patch):
    with pytest.raises(ValidationError):
        AgentConfiguration(**patch)


def test_generic_inbox_source_and_exactly_one_recipient():
    data = {
        "id": uuid7(),
        "leta_id": uuid7(),
        "content": "An integration input",
        "source": Source(type="future.integration", id="event-1", label="External"),
    }
    assert (
        NewMessage(**data, recipient_agent_id=uuid7()).source.type
        == "future.integration"
    )
    for recipients in (
        {},
        {"recipient_agent_id": uuid7(), "recipient_user_id": uuid7()},
    ):
        with pytest.raises(ValidationError):
            NewMessage(**data, **recipients)


@pytest.mark.parametrize("content", ["invalid\0text", "invalid\ud800text"])
def test_text_rejects_unstorable_utf8_before_sql(content):
    with pytest.raises(ValidationError):
        root_input(system_prompt=content)


def test_structured_payloads_must_be_json():
    with pytest.raises(ValidationError):
        NewMessage(
            id=uuid7(),
            leta_id=uuid7(),
            recipient_agent_id=uuid7(),
            source=Source(type="event", id="1", label="A source"),
            content="Hello",
            data={"invalid": object()},
        )


def test_request_shape_does_not_confuse_ask_with_resource_access():
    root = uuid7()
    base = dict(
        id=uuid7(),
        leta_id=root,
        requester_agent_id=uuid7(),
        title="Access?",
        payload={},
        approver_user_id=uuid7(),
        outcome_message_id=uuid7(),
    )
    assert NewHumanRequest(**base, kind="ask").grantee_leta_id is None
    grant = dict(
        grantee_leta_id=root,
        resource={"type": "personal_scope"},
        requested_role="viewer",
        grant_key=uuid7(),
    )
    assert (
        NewHumanRequest(**base, kind="approval", **grant).approver_user_id
        == base["approver_user_id"]
    )
    for kind, fields in (
        ("approval", {}),
        ("ask", grant),
        ("approval", grant | {"grantee_leta_id": uuid7()}),
    ):
        with pytest.raises(ValidationError):
            NewHumanRequest(**base, kind=kind, **fields)


def test_schedule_storage_requires_known_spec_and_aware_time():
    base = dict(
        id=uuid7(),
        leta_id=uuid7(),
        creator_agent_id=uuid7(),
        target_agent_id=uuid7(),
        title="Reminder",
        content="Check report",
    )
    assert (
        NewSchedule(**base, spec={"type": "interval", "every_seconds": 3600}).end_at
        is None
    )
    with pytest.raises(ValidationError):
        NewSchedule(**base, spec={"type": "daily"})
    with pytest.raises(ValidationError):
        NewSchedule(**base, spec={"type": "at"}, end_at="2026-11-09T00:00:00Z")


def test_configuration_json_roundtrip_preserves_patch_fields():
    patch = AgentConfiguration(name="Renamed", model_id=None)
    restored = AgentConfiguration.model_validate_json(patch.model_dump_json())
    assert restored.model_fields_set == {"name", "model_id"}
    assert restored.model_dump(exclude_unset=True) == {
        "name": "Renamed",
        "model_id": None,
    }
