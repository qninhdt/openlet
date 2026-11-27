from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from leta.channels.base import (
    CallerContext,
    ChannelMessage,
    ChannelSummary,
    OutboundMessage,
    OutboundReceipt,
    PlainTargetMatch,
)
from leta.channels.router import ChannelRouter, outbound_idempotency_key, parse_address
from leta.config import LetaRuntimeConfig
from leta.hitl.service import Question, build_ask_form, validate_ask_response
from leta.observability import build_rag_baggage, mask_trace_data
from leta.runtime.prompts import prompt_version_hash
from leta.schedules.service import Timing, build_temporal_schedule, normalize_timing
from leta.subagents.service import random_appearance, root_handle_base, slugify_handle
from openlet_sdk.config import load_path
from openlet_sdk.types import is_object_list, is_str_mapping


class _DummyAdapter:
    def __init__(self, scheme: str) -> None:
        self.scheme = scheme
        self.sent: list[tuple[str, str, str]] = []

    async def resolve_uuid_target(
        self, caller: CallerContext, raw_id: str
    ) -> str | None:
        _ = caller
        return raw_id

    async def resolve_plain_targets(
        self, caller: CallerContext, query: str
    ) -> list[PlainTargetMatch]:
        _ = caller, query
        return []

    async def send(
        self,
        caller: CallerContext,
        target: str,
        msg: OutboundMessage,
        idempotency_key: UUID,
    ) -> OutboundReceipt:
        self.sent.append((target, msg.content, str(idempotency_key)))
        return OutboundReceipt(
            channel=self.scheme, target=target, message_id=str(idempotency_key)
        )

    async def react(
        self, caller: CallerContext, target: str, message_id: str, emoji: str
    ) -> None:
        return None

    async def read_history(
        self,
        caller: CallerContext,
        target: str,
        *,
        before_seq: int | None = None,
        limit: int = 20,
        query: str = "",
    ) -> list[ChannelMessage]:
        return []

    async def list_channels(
        self, caller: CallerContext, *, query: str = "", limit: int = 20
    ) -> list[ChannelSummary]:
        return []

    async def set_typing(
        self, caller: CallerContext, target: str, active: bool
    ) -> None:
        return None

    async def mark_read(self, caller: CallerContext, target: str, seq: int) -> None:
        return None


async def test_channel_router_enforces_root_vs_subagent_and_idempotency() -> None:
    chat = _DummyAdapter("chat")
    agent = _DummyAdapter("agent")
    router = ChannelRouter([chat, agent])
    ws, lid, sid = uuid4(), uuid4(), uuid4()
    root = CallerContext(ws, lid, lid, "nora-the-analyst", "Nora", is_root=True)
    sub = CallerContext(ws, lid, sid, "researcher", "Researcher", is_root=False)

    assert parse_address("chat:123") == ("chat", "123")
    with pytest.raises(PermissionError):
        await router.send(
            sub, "chat:conv-1", OutboundMessage("hi"), tool_call_id="call-1"
        )

    r1 = await router.send(
        root, "chat:conv-1", OutboundMessage("hello"), tool_call_id="call-1"
    )
    r2 = await router.send(
        root, "chat:conv-1", OutboundMessage("hello"), tool_call_id="call-1"
    )
    assert (
        r1.message_id == r2.message_id == str(outbound_idempotency_key(lid, "call-1"))
    )

    sub_r = await router.send(
        sub, "agent:nora-the-analyst", OutboundMessage("done"), tool_call_id="call-2"
    )
    assert sub_r.channel == "agent"
    assert sub_r.target == "nora-the-analyst"


def test_hitl_question_types_and_validation() -> None:
    form = build_ask_form(
        [
            Question(text="Which region?"),
            Question(text="Pick one", options=["US", "EU"]),
            Question(text="Pick many", options=["A", "B", "C"], multiple=True),
        ]
    )
    valid = validate_ask_response(
        form,
        {
            "answers": {"q1": "North America", "q2": "o1", "q3": ["o1", "o3"]},
            "note": "Use Q4 data",
        },
    )
    assert valid.note == "Use Q4 data"
    assert valid.answers["q3"] == ["o1", "o3"]

    with pytest.raises(ValueError, match="requires one valid option id"):
        validate_ask_response(
            form, {"answers": {"q1": "ok", "q2": "bad_opt", "q3": ["o1"]}}
        )
    with pytest.raises(ValueError, match="non-empty list of unique valid option ids"):
        validate_ask_response(
            form, {"answers": {"q1": "ok", "q2": "o1", "q3": ["o1", "o1"]}}
        )


def test_schedule_timing_normalization_and_temporal_spec() -> None:
    now = datetime(2026, 11, 26, 10, 0, 0, tzinfo=UTC)
    normalized = normalize_timing(Timing(after_seconds=60), now)
    assert normalized is not None
    kind, spec = normalized
    assert kind == "at"
    assert spec["at"] == (now + timedelta(seconds=60)).isoformat()
    sched = build_temporal_schedule(
        schedule_id=uuid4(),
        sched_type=kind,
        spec=spec,
        paused=False,
        orchestration_queue="openlet-leta-orchestration",
    )
    assert sched.state.limited_actions is True
    assert sched.state.remaining_actions == 1

    normalized_cal = normalize_timing(
        Timing(calendar={"hour": [9], "minute": [30], "day_of_week": [1, 3, 5]}), now
    )
    assert normalized_cal is not None
    ck, cspec = normalized_cal
    assert ck == "calendar"
    csched = build_temporal_schedule(
        schedule_id=uuid4(),
        sched_type=ck,
        spec=cspec,
        paused=True,
        orchestration_queue="openlet-leta-orchestration",
    )
    assert csched.state.paused is True


def test_handles_appearance_and_yaml_config_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        root_handle_base("Nora Vance", "Lead Analyst!") == "nora-vance-the-lead-analyst"
    )
    assert slugify_handle("   ") == "agent"
    app = random_appearance()
    assert "shape" in app
    assert "color" in app

    raw = load_path(Path("infra/config/openlet.example.yaml"))
    cfg = LetaRuntimeConfig.from_openlet_config(raw)
    assert cfg.model.max_steps_per_run is None
    assert cfg.messaging.notification_preview_chars == 120
    assert cfg.bash.python_max_memory == "256MB"
    assert cfg.bash.network == "public_only"
    assert cfg.queues.orchestration == "openlet-leta-orchestration"
    assert cfg.queues.runtime == "openlet-leta-runtime"
    _ = monkeypatch


def test_observability_masking_baggage_and_prompt_hash() -> None:
    payload = {
        "text": "hello",
        "nested": [
            {"url": "data:image/png;base64," + "A" * 500},
            {"url": "https://example.com/a.png"},
        ],
    }
    masked = mask_trace_data(data=payload)
    assert is_str_mapping(masked)
    nested = masked["nested"]
    assert is_object_list(nested)
    assert is_str_mapping(nested[0])
    assert is_str_mapping(nested[1])
    assert masked["text"] == "hello"
    assert "[omitted" in str(nested[0]["url"])
    assert "AAAA" not in str(nested[0]["url"])
    assert nested[1]["url"] == "https://example.com/a.png"

    bag = build_rag_baggage(session_id="s1", agent_id="a1", workspace_id="w1")
    assert "langfuse_session_id=s1" in bag
    assert "langfuse_metadata_agent_id=%22a1%22" in bag
    assert "langfuse_metadata_workspace_id=%22w1%22" in bag

    h_root = prompt_version_hash(True)
    h_sub = prompt_version_hash(False)
    assert len(h_root) == 12
    assert len(h_sub) == 12
    assert h_root != h_sub
