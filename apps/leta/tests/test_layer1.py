from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from leta.channels.base import CallerContext, OutboundMessage, OutboundReceipt
from leta.channels.router import ChannelRouter, outbound_idempotency_key, parse_address
from leta.config import LetaRuntimeConfig
from leta.hitl.service import Question, build_ask_form, validate_ask_response
from leta.schedules.service import Timing, build_temporal_schedule, normalize_timing
from leta.subagents.service import random_appearance, root_handle_base, slugify_handle
from openlet_sdk.config import JSON, Config


class _DummyAdapter:
    def __init__(self, scheme: str) -> None:
        self.scheme = scheme
        self.sent: list[tuple[str, str, str]] = []

    async def send(
        self,
        caller: CallerContext,
        target: str,
        msg: OutboundMessage,
        idempotency_key: object,
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
    ) -> list[object]:
        return []

    async def list_channels(
        self, caller: CallerContext, *, query: str = "", limit: int = 20
    ) -> list[object]:
        return []

    async def set_typing(
        self, caller: CallerContext, target: str, active: bool
    ) -> None:
        return None


async def test_channel_router_enforces_root_vs_subagent_and_idempotency() -> None:
    chat = _DummyAdapter("chat")
    agent = _DummyAdapter("agent")
    router = ChannelRouter([chat, agent])  # type: ignore[list-item]
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
    assert sub_r.channel == "agent" and sub_r.target == "nora-the-analyst"


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
    assert valid["note"] == "Use Q4 data"
    assert cast(dict[str, JSON], valid["answers"])["q3"] == ["o1", "o3"]

    with pytest.raises(ValueError):
        validate_ask_response(
            form, {"answers": {"q1": "ok", "q2": "bad_opt", "q3": ["o1"]}}
        )
    with pytest.raises(ValueError):
        validate_ask_response(
            form, {"answers": {"q1": "ok", "q2": "o1", "q3": ["o1", "o1"]}}
        )


def test_schedule_timing_normalization_and_temporal_spec() -> None:
    now = datetime(2026, 11, 26, 10, 0, 0, tzinfo=UTC)
    kind, spec = normalize_timing(Timing(after_seconds=60), now) or ("", {})
    assert kind == "at"
    assert spec["at"] == (now + timedelta(seconds=60)).isoformat()
    sched = build_temporal_schedule(
        schedule_id=uuid4(),
        sched_type=kind,
        spec=spec,
        paused=False,
        orchestration_queue="openlet-leta-orchestration",
    )
    assert sched.state.limited_actions is True and sched.state.remaining_actions == 1

    ck, cspec = normalize_timing(
        Timing(calendar={"hour": [9], "minute": [30], "day_of_week": [1, 3, 5]}), now
    ) or ("", {})
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
    from pathlib import Path

    import yaml

    assert (
        root_handle_base("Nora Vance", "Lead Analyst!") == "nora-vance-the-lead-analyst"
    )
    assert slugify_handle("   ") == "agent"
    app = random_appearance()
    assert "shape" in app and "color" in app

    raw = yaml.safe_load(
        Path("infra/config/openlet.example.yaml").read_text(encoding="utf-8")
    )
    cfg = LetaRuntimeConfig.from_openlet_config(cast(Config, raw))
    assert cfg.model.max_steps_per_run is None
    assert cfg.messaging.notification_preview_chars == 120
    assert cfg.bash.python_max_memory == "256MB"
    assert cfg.bash.network == "public_only"
    assert cfg.queues.orchestration == "openlet-leta-orchestration"
    assert cfg.queues.runtime == "openlet-leta-runtime"
    _ = monkeypatch
