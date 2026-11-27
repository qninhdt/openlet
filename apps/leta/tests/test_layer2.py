from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import TYPE_CHECKING, Self, cast
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph import (  # pyright: ignore[reportMissingTypeStubs]
    END,
    START,
    StateGraph,
)
from langgraph.prebuilt import ToolRuntime
from leta.channels.router import ChannelRouter
from leta.config import (
    CompactionConfig,
    LetaRuntimeConfig,
    MediaConfig,
    ModelConfig,
    ModelRetryConfig,
    ModelSpec,
    Services,
    ToolFlags,
    ToolOutputConfig,
    WebConfig,
)
from leta.filesystem.letfs import parse_letfs_by_id_path
from leta.hitl.models import AskPayload, AskResponse, HitlOutcome
from leta.hitl.service import Question
from leta.inbox import InboxRecord
from leta.runtime.compaction import (
    assemble_checkpoint_xml,
    compaction_ceiling,
    estimate_prompt_tokens,
    flatten_and_drop_oldest,
    is_checkpoint_message,
    serialize_recent_context,
)
from leta.runtime.formatting import (
    format_hitl_outcome,
    format_hitl_outcome_attr,
    format_hitl_response,
)
from leta.runtime.media import (
    PreparedImage,
    bound_history_images,
    detect_media_type,
    optimize_image_bytes,
)
from leta.runtime.nodes.inbox import (
    format_inbox_item_full,
    format_inbox_notification_preview,
)
from leta.runtime.nodes.tools import after_tools_router, build_tools_node
from leta.runtime.prompts import render_system_prompt
from leta.runtime.retry import (
    ContextOverflowError,
    compute_output_limit,
    invoke_with_retry,
    retry_one_shot,
)
from leta.runtime.runner import find_orphaned_tool_calls
from leta.runtime.state import AgentState, RuntimeContext, reasoning_kwargs_for_model
from leta.runtime.tool_repair import (
    format_input_issues,
    format_tool_error,
    repair_tool_args,
    repair_tool_args_with_notes,
    resolve_tool_alias,
)
from leta.runtime.tools import web as web_tools
from leta.runtime.tools.base import ToolArgs, ToolResult, make_tool
from leta.runtime.tools.files import (
    FileEditArgs,
    apply_file_edit,
    apply_file_edit_detailed,
    build_file_tools,
    normalize_workspace_path,
)
from leta.runtime.tools.messaging import (
    RootSendMessageArgs,
    build_messaging_tools,
    validate_citations,
)
from leta.runtime.tools.web import build_web_tools, normalize_public_url
from leta.runtime.tools.workspace_tools import (
    HitlAskArgs,
    ScheduleCreateArgs,
    build_domain_tools,
    format_activity_event_summary,
    parse_schedule_timing,
)
from leta.truncation import truncate_head, truncate_tail
from openlet_sdk.types import is_str_mapping
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tinyfish import FetchResponse, SDKError, SearchQueryResponse

if TYPE_CHECKING:
    from leta.activity import ActivityEmitter
    from leta.filesystem.workspace import Filesystem

# --- 1. ToolInputRepair ---


class _SampleToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int
    ratio: float
    enabled: bool
    tags: list[str]
    optional_note: str | None = None
    limit: int = Field(default=10, ge=1)


def test_tool_alias_and_recursive_coercion() -> None:
    target, note = resolve_tool_alias(
        "execute", {"bash": object(), "file_read": object()}
    )
    assert target == "bash"
    assert note is not None
    assert "<tool-repair>" in note

    target2, note2 = resolve_tool_alias("bash", {"bash": object()})
    assert target2 == "bash"
    assert note2 is None

    repaired = repair_tool_args(
        {
            "count": "42",
            "ratio": "3.14",
            "enabled": "true",
            "tags": '["alpha", "beta"]',
            "optional_note": {},  # stripped optional empty object
        },
        _SampleToolArgs.model_json_schema(),
    )
    parsed = _SampleToolArgs.model_validate(repaired)
    assert parsed.count == 42
    assert parsed.ratio == pytest.approx(3.14)
    assert parsed.enabled is True
    assert parsed.tags == ["alpha", "beta"]
    assert parsed.optional_note is None

    # Unknown parameters must NOT be silently dropped; validation surfaces them with valid params.
    with_unknown = repair_tool_args(
        {
            "count": 1,
            "ratio": 1.0,
            "enabled": True,
            "tags": ["a"],
            "bogus_param": 123,
        },
        _SampleToolArgs.model_json_schema(),
    )
    with pytest.raises(ValidationError) as extra_exc:
        _SampleToolArgs.model_validate(with_unknown)
    extra_msg = format_input_issues(
        extra_exc.value,
        with_unknown,
        valid_params=list(_SampleToolArgs.model_fields.keys()),
    )
    assert "bogus_param: unknown parameter" in extra_msg
    assert "Valid parameters:" in extra_msg

    with pytest.raises(ValidationError) as exc_info:
        _SampleToolArgs.model_validate({"count": "not-an-int"})
    msg = format_input_issues(
        exc_info.value, {"count": "not-an-int"}, excerpt_limit=100
    )
    assert "Invalid tool arguments:" in msg
    assert "count" in msg


# --- 2. Dual HEAD / TAIL Truncation ---


def test_head_and_tail_truncation() -> None:
    lines = [f"line-{i}" for i in range(1, 51)]
    text = "\n".join(lines)

    head = truncate_head(text, max_lines=10, max_bytes=10000, max_line_length=200)
    assert head.truncated is True
    assert head.start_line == 1
    assert head.end_line == 10
    assert head.total_lines == 50
    assert head.text.startswith("line-1\n")
    assert head.text.endswith("line-10")

    tail = truncate_tail(text, max_lines=10, max_bytes=10000)
    assert tail.truncated is True
    assert tail.start_line == 41
    assert tail.end_line == 50
    assert tail.total_lines == 50
    assert tail.text.startswith("line-41\n")
    assert tail.text.endswith("line-50")

    # Line clipping
    long_line = "x" * 3000
    clipped = truncate_head(
        long_line, max_lines=10, max_bytes=10000, max_line_length=100
    )
    assert "line truncated to 100 chars" in clipped.text


# --- 3. Pillow Image Optimization & History Hysteresis ---


def _make_png(w: int, h: int, *, alpha: int = 255) -> bytes:
    buf = BytesIO()
    img = Image.new("RGBA", (w, h), (120, 80, 200, alpha))
    # Add some pixel variance so PNG is larger than JPEG
    px = img.load()
    assert px is not None
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            px[x, y] = ((x * 7) % 255, (y * 11) % 255, ((x + y) * 3) % 255, alpha)
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_image_optimization_and_hysteresis() -> None:
    cfg = MediaConfig()
    small_png = _make_png(64, 64, alpha=255)
    assert detect_media_type(small_png) == "image/png"
    res = optimize_image_bytes(small_png, cfg)
    assert isinstance(res, PreparedImage)
    assert res.media_type == "image/png"
    assert res.width == 64
    assert res.height == 64

    oversized_opaque = _make_png(2400, 1200, alpha=255)
    res2 = optimize_image_bytes(oversized_opaque, cfg)
    assert isinstance(res2, PreparedImage)
    assert res2.width <= 2000
    assert res2.height <= 2000
    assert res2.base64_bytes <= cfg.image_max_base64_bytes

    transparent_large = _make_png(2400, 1200, alpha=100)
    res3 = optimize_image_bytes(transparent_large, cfg)
    assert isinstance(res3, PreparedImage)
    assert res3.media_type == "image/png"
    assert res3.width <= 2000

    # History hysteresis: trigger 1000 -> target 500
    tight_cfg = MediaConfig(
        history_image_bytes_trigger=1000, history_image_bytes_target=500
    )
    msgs: list[BaseMessage] = [
        ToolMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64," + "A" * 400},
                }
            ],
            tool_call_id="c1",
            artifact={"path": "/shared/img1.png"},
        ),
        ToolMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64," + "B" * 400},
                }
            ],
            tool_call_id="c2",
            artifact={"path": "/shared/img2.png"},
        ),
        ToolMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64," + "C" * 400},
                }
            ],
            tool_call_id="c3",
            artifact={"path": "/shared/img3.png"},
        ),
    ]
    bounded = bound_history_images(msgs, tight_cfg)
    assert "[Image omitted to save context; re-read /shared/img1.png if needed]" in str(
        bounded[0].content
    )
    assert "[Image omitted to save context; re-read /shared/img2.png if needed]" in str(
        bounded[1].content
    )
    assert "image_url" in str(bounded[2].content)


# --- 4. file_edit 3-Tier Match, CRLF/BOM, missHint ---


def test_file_edit_3_tier_crlf_bom_and_miss_hint() -> None:
    # Tier 1 exact + BOM + CRLF preservation
    src = "\ufeffline1\r\nhello world\r\nline3\r\n"
    updated, count, diff = apply_file_edit(src, "hello world", "hello\nopenlet")
    assert count == 1
    assert updated.startswith("\ufeff")
    assert "hello\r\nopenlet\r\n" in updated
    assert "-hello world" in diff

    # Tier 2 unicode curly quote normalization
    curly = "He said \u201chello\u201d to Bob."
    u2, c2, _ = apply_file_edit(curly, 'He said "hello"', 'He said "hi"')
    assert c2 == 1
    assert u2 == 'He said "hi" to Bob.'

    # Tier 3 trailing whitespace line match
    ws_src = "alpha   \nbeta  \ngamma\n"
    u3, c3, _ = apply_file_edit(ws_src, "alpha\nbeta", "ALPHA\nBETA")
    assert c3 == 1
    assert u3.startswith("ALPHA\nBETA\ngamma")

    # missHint when newString already applied
    with pytest.raises(ValueError, match="already present"):
        apply_file_edit("already done", "not here", "already done")

    # missHint shows closest lines
    with pytest.raises(ValueError, match="Closest matching lines:"):
        apply_file_edit("a\nb\nrevenue_total = 100\nd\n", "revenue_total = 999", "x")


# --- 5. model-retry.ts & dynamic outputLimit ---


class _FakeHTTPError(RuntimeError):
    def __init__(
        self, msg: str, status_code: int, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(msg)
        self.status_code = status_code
        self.headers = headers or {}


@pytest.mark.asyncio
async def test_model_retry_and_output_limit() -> None:
    spec = ModelSpec(
        model_id="gpt-6-luna",
        reasoning_efforts=[None, "high"],
        context_window_tokens=272000,
        max_output_tokens=128000,
    )
    mcfg = ModelConfig()
    out_lim = compute_output_limit(
        spec, measured_tokens=200000, estimated_tokens=10000, cfg=mcfg
    )
    assert 1024 <= out_lim <= 128000
    assert out_lim == 269280 - 200000 - 11500

    # Retry-After honored & x-should-retry: false aborts immediately
    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)

    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _FakeHTTPError("rate limited", 429, {"Retry-After": "12"})
        return "ok"

    res = await invoke_with_retry(flaky, cfg=ModelRetryConfig(), sleep=fake_sleep)
    assert res == "ok"
    assert attempts == 2
    assert sleeps[0] >= 12.0

    # x-should-retry: false stops immediately
    async def no_retry() -> str:
        raise _FakeHTTPError("stop", 503, {"x-should-retry": "false"})

    with pytest.raises(_FakeHTTPError):
        await invoke_with_retry(no_retry, cfg=ModelRetryConfig(), sleep=fake_sleep)

    # Context overflow raises ContextOverflowError immediately
    async def overflow() -> str:
        raise _FakeHTTPError("maximum context length exceeded", 400)

    with pytest.raises(ContextOverflowError):
        await invoke_with_retry(overflow, cfg=ModelRetryConfig(), sleep=fake_sleep)

    # Timeout retries capped at timeout_max_retries
    t_calls = 0

    async def always_timeout() -> str:
        nonlocal t_calls
        t_calls += 1
        raise TimeoutError("timed out")

    with pytest.raises(TimeoutError):
        await invoke_with_retry(
            always_timeout,
            cfg=ModelRetryConfig(timeout_max_retries=2),
            sleep=fake_sleep,
        )
    assert t_calls == 3

    # One-shot retries only not-sent errors
    o_calls = 0

    async def oneshot_429() -> str:
        nonlocal o_calls
        o_calls += 1
        if o_calls < 2:
            raise _FakeHTTPError("429", 429)
        return "done"

    assert (
        await retry_one_shot(oneshot_429, cfg=ModelRetryConfig(), sleep=fake_sleep)
        == "done"
    )


# --- 6. Compaction Helpers ---


def test_compaction_estimators_recent_text_and_5_level_flatten() -> None:
    spec = ModelSpec(
        model_id="gpt-6-luna",
        reasoning_efforts=[None],
        context_window_tokens=200000,
        max_output_tokens=64000,
    )
    ccfg = CompactionConfig()
    assert compaction_ceiling(spec, ccfg) == 170000.0  # 85%

    mcfg = ModelConfig()
    msgs: list[BaseMessage] = [
        HumanMessage(content="hello"),
        AIMessage(
            content="checking",
            usage_metadata={
                "input_tokens": 50000,
                "output_tokens": 500,
                "total_tokens": 50500,
            },
            additional_kwargs={"openlet_model_id": "gpt-6-luna"},
        ),
        ToolMessage(content="a" * 4000, tool_call_id="tc1"),
    ]
    est = estimate_prompt_tokens(msgs, mcfg, model_id="gpt-6-luna")
    assert est.measured == 50500
    assert est.estimated == 1000
    assert est.anchor_index == 1

    recent, _, _ = serialize_recent_context(
        msgs,
        keep_recent_tokens=15000,
        recent_tool_output_max_chars=1250,
    )
    assert "[Tool result]:" in recent
    assert "[truncated]" in recent

    # 5-level flatten drops oldest while preserving newest exchange
    big_msgs: list[BaseMessage] = [
        HumanMessage(content="old request 1 " * 10),
        AIMessage(
            content="ok",
            tool_calls=[{"id": "1", "name": "file_read", "args": {"path": "/a"}}],
        ),
        ToolMessage(content="X" * 10000, tool_call_id="1"),
        HumanMessage(content="newest critical request"),
        AIMessage(content="working on newest"),
    ]
    flattened_clipped = flatten_and_drop_oldest(
        big_msgs, room_tokens=200, clip_chars=200
    )
    assert flattened_clipped is not None
    assert "characters omitted" in flattened_clipped
    assert "newest critical request" in flattened_clipped

    flattened = flatten_and_drop_oldest(big_msgs, room_tokens=20, clip_chars=200)
    assert flattened is not None
    assert "newest critical request" in flattened
    assert "older exchange(s) omitted" in flattened

    chk = assemble_checkpoint_xml(
        summary="## Objective\nTest",
        recent_text="[User]: hi",
        subagents_text="- vega | running",
        hitl_text="",
        schedules_text="",
    )
    assert is_checkpoint_message(chk)
    assert "<subagents>" in str(chk.content)
    assert "<pending-hitl>" not in str(chk.content)


# --- 7. LetFSByID, Citations, Inbox XML, Orphaned Tool Calls, Fast Exit ---


def test_letfs_by_id_parsing_and_root_blocking() -> None:
    sid = str(uuid4())
    nid = str(uuid4())
    parsed = parse_letfs_by_id_path(f"/{sid}/{nid}/sheet/summary.md")
    assert parsed == (sid, nid, "sheet/summary.md")
    with pytest.raises(PermissionError):
        parse_letfs_by_id_path("/")
    with pytest.raises(ValueError, match="badly formed hexadecimal UUID string"):
        parse_letfs_by_id_path("/not-a-uuid/123")


def test_citations_inbox_xml_orphans_and_end_turn_router() -> None:
    validate_citations(
        "Revenue grew 12% [1] per filing [2].", ["/shared/a.pdf", "https://example.com"]
    )
    with pytest.raises(ValueError, match="out of range"):
        validate_citations("See [3].", ["/shared/a.pdf"])
    with pytest.raises(ValueError, match="not cited"):
        validate_citations("See [1].", ["/shared/a.pdf", "/shared/b.pdf"])

    full_xml = format_inbox_item_full(
        InboxRecord.model_validate(
            {
                "seq": 7,
                "kind": "channel",
                "channel": "chat",
                "reply_address": "chat:11111111-1111-1111-1111-111111111111",
                "sender": {
                    "type": "user",
                    "id": "u1",
                    "name": "Alice",
                    "handle": "alice",
                },
                "content": "Check <Q3> & totals",
                "attachments": [
                    {
                        "storage_id": "s1",
                        "node_id": "n1",
                        "name": "q3.xlsx",
                        "media_type": "application/vnd.ms-excel",
                    }
                ],
                "metadata": {"message_id": "m1", "reply_to_message_id": "m0"},
                "created_at": "2026-11-26T10:00:00Z",
            }
        )
    )
    assert "&lt;Q3&gt; &amp; totals" in full_xml
    assert "/letfs/s1/n1" in full_xml
    assert '<reply-to id="m0" />' in full_xml

    react_xml = format_inbox_item_full(
        InboxRecord.model_validate(
            {
                "seq": 9,
                "kind": "reaction",
                "channel": "chat",
                "reply_address": "chat:11111111-1111-1111-1111-111111111111",
                "sender": {
                    "type": "user",
                    "id": "u1",
                    "name": "Alice",
                    "handle": "alice",
                },
                "content": "",
                "metadata": {
                    "target_message_id": "m1",
                    "emoji": "👍",
                    "action": "added",
                },
                "created_at": "2026-11-26T10:02:00Z",
            }
        )
    )
    assert '<reaction seq="9"' in react_xml
    assert 'target_message_id="m1"' in react_xml
    assert 'emoji="👍"' in react_xml
    assert 'action="added"' in react_xml

    preview_xml = format_inbox_notification_preview(
        InboxRecord.model_validate(
            {
                "seq": 8,
                "kind": "channel",
                "channel": "chat",
                "reply_address": "chat:22222222-2222-2222-2222-222222222222",
                "sender": {"type": "user", "id": "u2", "name": "Bob", "handle": "bob"},
                "content": "Hey, quick question about Q4",
                "metadata": {"message_id": "m2"},
                "created_at": "2026-11-26T10:01:00Z",
            }
        ),
        unread_in_channel=2,
    )
    assert "<notification " in preview_xml
    assert "read_messages" in preview_xml

    # Orphaned tool calls detection
    orphans = find_orphaned_tool_calls(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "c1", "name": "file_read", "args": {}},
                    {"id": "c2", "name": "grep", "args": {}},
                ],
            ),
            ToolMessage(content="ok", tool_call_id="c1"),
        ]
    )
    assert orphans == [("c2", "grep")]

    # after_tools_router fast exit vs error loop
    ok_state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"id": "c1", "name": "send_message", "args": {}}],
            ),
            ToolMessage(
                content="sent",
                tool_call_id="c1",
                status="success",
                artifact={"end_turn": True},
            ),
        ],
        "inbox_cursor": 1,
    }
    assert after_tools_router(ok_state) == "end_turn"

    err_state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"id": "c1", "name": "send_message", "args": {}}],
            ),
            ToolMessage(
                content="err",
                tool_call_id="c1",
                status="error",
                artifact={"end_turn": True},
            ),
        ],
        "inbox_cursor": 1,
    }
    assert after_tools_router(err_state) == "inbox"


@dataclass(slots=True)
class _FakePromptSettings:
    tools: ToolFlags = field(default_factory=ToolFlags)


@dataclass(slots=True)
class _FakePromptServices:
    settings: _FakePromptSettings = field(default_factory=_FakePromptSettings)


@dataclass(slots=True)
class _FakePromptContext:
    is_root: bool = True
    agent_name: str = "Luna"
    agent_title: str = "Analyst"
    handle: str = "luna"
    agent_description: str = "Financial analyst"
    custom_instructions: str = "Always double check math."
    parent_handle: str = ""
    services: _FakePromptServices = field(default_factory=_FakePromptServices)


def test_prompt_rendering_and_reasoning_mapping() -> None:
    fake_rt = _FakePromptContext(
        services=_FakePromptServices(
            settings=_FakePromptSettings(
                tools=ToolFlags(
                    hitl=True,
                    subagents=True,
                    schedule=True,
                    web=True,
                    bash=True,
                    semantic_search=True,
                    todo=False,
                    react=True,
                )
            )
        )
    )
    rendered = render_system_prompt(fake_rt)
    assert "Luna" in rendered
    assert "Always double check math." in rendered
    assert "send_message" in rendered

    assert reasoning_kwargs_for_model("claude-opus-4", "high") == {
        "thinking": {"type": "enabled", "budget_tokens": 24576}
    }
    assert reasoning_kwargs_for_model("gpt-6-luna", "medium") == {
        "reasoning_effort": "medium"
    }


def test_schedule_timing_parser_and_simplified_tool_schemas() -> None:
    # 1. One-shot relative & ISO
    t_rel = parse_schedule_timing(run_at="+30m", repeat=None)
    assert t_rel.after_seconds == 1800

    t_in = parse_schedule_timing(run_at="in 1h30m", repeat=None)
    assert t_in.after_seconds == 5400

    t_iso = parse_schedule_timing(
        run_at="2026-12-01T09:00:00", repeat=None, timezone="Asia/Ho_Chi_Minh"
    )
    assert t_iso.at is not None
    assert t_iso.at.tzinfo is not None

    # 2. Recurring interval & 5-field cron
    t_every = parse_schedule_timing(run_at=None, repeat="every 15m")
    assert t_every.every_seconds == 900

    t_cron = parse_schedule_timing(
        run_at=None,
        repeat="0 9 * * 1-5",
        timezone="Asia/Ho_Chi_Minh",
        ends_at="2026-12-31T23:59:00+07:00",
    )
    assert t_cron.cron == "0 9 * * 1-5"
    assert t_cron.ends_at is not None

    t_step = parse_schedule_timing(run_at=None, repeat="*/15 * * * mon,sun")
    assert t_step.cron == "*/15 * * * mon,sun"

    with pytest.raises(ValueError, match="not both"):
        parse_schedule_timing(run_at="+5m", repeat="every 5m")

    # 3. Verify simplified schemas
    assert set(ScheduleCreateArgs.model_json_schema()["properties"].keys()) == {
        "title",
        "content",
        "run_at",
        "repeat",
        "timezone",
        "ends_at",
        "target_agent",
        "runtime",
    }
    assert "recipient" in HitlAskArgs.model_json_schema()["required"]
    assert set(FileEditArgs.model_json_schema()["properties"].keys()) == {
        "path",
        "old_string",
        "new_string",
        "replace_all",
        "runtime",
    }
    assert (
        "reply_to_message_id" in RootSendMessageArgs.model_json_schema()["properties"]
    )


def test_native_structured_tools_and_ergonomics() -> None:
    # 1. Native LangChain OpenAI schema projection: no $defs, no $ref, no title, no runtime
    all_tools = [
        *build_file_tools(),
        *build_web_tools(),
        *build_domain_tools(is_root=True, enable_todo=True),
    ]
    by_name = {t.name: t for t in all_tools}
    hitl_openai = convert_to_openai_tool(by_name["hitl_ask"])
    params = hitl_openai["function"]["parameters"]
    assert "$defs" not in params
    assert "runtime" not in params["properties"]
    assert "title" not in params
    assert "after_seconds" not in by_name["schedule_create"].description
    assert "run_at" in by_name["schedule_create"].description

    # 2. No '@' prefix in inbox XML
    xml_out = format_inbox_item_full(
        InboxRecord.model_validate(
            {
                "seq": 1,
                "kind": "channel",
                "channel": "chat",
                "reply_address": "chat:11111111-1111-1111-1111-111111111111",
                "sender": {
                    "type": "user",
                    "id": "u1",
                    "name": "Ethan Brooks",
                    "handle": "ethan",
                },
                "content": "hi",
                "attachments": [],
                "metadata": {"message_id": "m1"},
                "created_at": "2026-11-27T00:00:00Z",
            }
        )
    )
    assert 'from="Ethan Brooks (ethan)"' in xml_out
    assert "@ethan" not in xml_out

    # 3. Domain auto-heals: bash ms->s timeout, param aliases, hitl options=[]
    bash_schema = convert_to_openai_tool(by_name["bash"])["function"]["parameters"]
    assert is_str_mapping(bash_schema)
    healed_bash, notes = repair_tool_args_with_notes(
        {"command": "echo hi", "cwd": "/shared", "timeout": 120000},
        dict(bash_schema),
        tool_name="bash",
    )
    assert healed_bash == {"command": "echo hi", "workdir": "/shared", "timeout": 120}
    assert any("120s" in n for n in notes)

    edit_schema = convert_to_openai_tool(by_name["file_edit"])["function"]["parameters"]
    assert is_str_mapping(edit_schema)
    healed_edit, _ = repair_tool_args_with_notes(
        {
            "filePath": "/home/a.txt",
            "oldString": "a",
            "newString": "b",
            "replaceAll": "true",
        },
        dict(edit_schema),
        tool_name="file_edit",
    )
    assert healed_edit == {
        "path": "/home/a.txt",
        "old_string": "a",
        "new_string": "b",
        "replace_all": True,
    }

    q = Question.model_validate({"text": "Any notes?", "options": []})
    assert q.options is None

    # 4. Path & URL normalization
    assert normalize_workspace_path("shared/q3.csv") == "/shared/q3.csv"
    assert normalize_workspace_path("chat/ethan/out.md") == "/chat/ethan/out.md"
    assert normalize_public_url("example.com/docs") == "https://example.com/docs"

    # 5. file_edit: CRLF LF-view, sequential line-prefix strip, multi-match line numbers
    crlf_doc = "alpha\r\nbeta\r\ngamma\r\n"
    updated, count, _, lines, note = apply_file_edit_detailed(
        crlf_doc, "1: alpha\n2: beta", "ALPHA\nBETA"
    )
    assert count == 1
    assert lines == [1]
    assert note is not None
    assert updated == "ALPHA\r\nBETA\r\ngamma\r\n"

    with pytest.raises(ValueError, match=r"lines 1, 3"):
        apply_file_edit_detailed("dup\nmid\ndup\n", "dup", "new")

    # 6. Citations allow [1] when sources=[] and ignore code blocks
    validate_citations("Use items[1] in code and [2] in text.", [])
    validate_citations(
        "Revenue grew [1]. See `arr[99]` and ```\nx[42]\n```.", ["/shared/a.pdf"]
    )

    # 7. Schedule shorthands & timezone aliases
    assert parse_schedule_timing(run_at="30m", repeat=None).after_seconds == 1800
    assert parse_schedule_timing(run_at=None, repeat="15m").every_seconds == 900
    daily = parse_schedule_timing(run_at=None, repeat="daily", timezone="UTC+7")
    assert daily.timezone == "Asia/Ho_Chi_Minh"
    assert daily.cron == "0 9 * * *"
    weekdays = parse_schedule_timing(run_at=None, repeat="weekdays", timezone="EST")
    assert weekdays.timezone == "America/New_York"
    assert weekdays.cron == "0 9 * * 1-5"

    # 8. Tail truncation per-line clipping & clean error formatting
    tail_clipped = truncate_tail(
        "a\n" + "z" * 500, max_lines=5, max_bytes=10000, max_line_length=50
    )
    assert tail_clipped.truncated is True
    assert "line truncated to 50 chars" in tail_clipped.text
    assert "Invalid timezone" in format_tool_error(
        ValueError("Invalid timezone 'Mars'")
    )


@dataclass(slots=True)
class _FakeEmitter:
    emitted: list[dict[str, object]]

    async def emit(self, **kwargs: object) -> None:
        self.emitted.append(kwargs)


@dataclass(slots=True)
class _FakeFS:
    async def write_spill(self, prefix: str, full_text: str) -> str:
        _ = full_text
        return f"/home/.tool-output/{prefix}-test.txt"


@dataclass(slots=True)
class _FakeServices:
    settings: LetaRuntimeConfig


def _make_test_runtime_context(
    *,
    settings: LetaRuntimeConfig | None = None,
    emitter: _FakeEmitter | None = None,
    fs: _FakeFS | None = None,
) -> RuntimeContext:
    return RuntimeContext(
        agent_id=uuid4(),
        leta_id=uuid4(),
        workspace_id=uuid4(),
        storage_id=uuid4(),
        is_root=True,
        handle="nora",
        agent_name="Nora",
        agent_title="Analyst",
        agent_description="",
        custom_instructions="",
        parent_handle="",
        model_spec=ModelSpec(
            model_id="gpt-6-luna",
            reasoning_efforts=[None],
            context_window_tokens=128000,
            max_output_tokens=16000,
        ),
        reasoning_effort=None,
        run_id=uuid4(),
        services=cast(
            "Services", _FakeServices(settings=settings or LetaRuntimeConfig())
        ),
        emitter=cast("ActivityEmitter", emitter or _FakeEmitter(emitted=[])),
        fs=cast("Filesystem", fs or _FakeFS()),
        router=ChannelRouter([]),
        tools={},
    )


@pytest.mark.asyncio
async def test_native_langgraph_tool_node_pipeline() -> None:
    # Smoke-check ToolNode initialization across every production tool (verifies get_type_hints & ToolRuntime)
    all_prod_tools = [
        *build_file_tools(),
        *build_web_tools(),
        *build_messaging_tools(is_root=True, enable_react=True),
        *build_domain_tools(is_root=True, enable_todo=True),
    ]
    assert len(all_prod_tools) == 28
    build_tools_node(all_prod_tools)

    emitted: list[dict[str, object]] = []

    class _EchoArgs(ToolArgs):
        path: str = Field(min_length=1)
        limit: int = 10

    async def _echo(
        path: str, limit: int = 10, *, runtime: ToolRuntime[RuntimeContext, AgentState]
    ) -> ToolResult:
        return f"ok:{runtime.context.handle}:{path}:{limit}", {"end_turn": True}

    echo_tool = make_tool(
        name="file_read",
        description="Read test",
        args_schema=_EchoArgs,
        coroutine=_echo,
    )

    rt = _make_test_runtime_context(
        settings=LetaRuntimeConfig(tool_output=ToolOutputConfig()),
        emitter=_FakeEmitter(emitted=emitted),
        fs=_FakeFS(),
    )

    g: StateGraph[AgentState, RuntimeContext, AgentState, AgentState] = StateGraph(
        AgentState, context_schema=RuntimeContext
    )
    g.add_node("tools", build_tools_node([echo_tool]))  # pyright: ignore[reportUnknownMemberType]
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    app = g.compile()  # pyright: ignore[reportUnknownMemberType]

    # 1. Alias tool ('read' -> 'file_read') + param alias ('filePath' -> 'path') + type coercion
    out = await app.ainvoke(  # pyright: ignore[reportUnknownMemberType]
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "read",
                            "args": {"filePath": "/shared/a.md", "limit": "5"},
                        }
                    ],
                )
            ],
            "inbox_cursor": 0,
        },
        context=rt,
    )
    tm = out["messages"][-1]
    assert isinstance(tm, ToolMessage)
    assert tm.status == "success"
    assert tm.name == "read"
    assert "<tool-repair>" in tm.text
    assert "ok:nora:/shared/a.md:5" in tm.text
    assert tm.artifact == {"end_turn": True}
    assert (
        after_tools_router(
            {
                "messages": list(out["messages"]),
                "inbox_cursor": int(out["inbox_cursor"]),
            }
        )
        == "end_turn"
    )

    # 2. Unknown parameter rejected with Valid parameters hint + invalid_tool_calls handled cleanly
    out2 = await app.ainvoke(  # pyright: ignore[reportUnknownMemberType]
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call-2",
                            "name": "file_read",
                            "args": {"path": "/shared/a.md", "mystery": 1},
                        }
                    ],
                    invalid_tool_calls=[
                        {
                            "id": "call-3",
                            "name": "file_read",
                            "args": "{bad json",
                            "error": "JSON decode error",
                        }
                    ],
                )
            ],
            "inbox_cursor": 0,
        },
        context=rt,
    )
    t_msgs = [m for m in out2["messages"] if isinstance(m, ToolMessage)]
    by_id = {m.tool_call_id: m for m in t_msgs}
    assert by_id["call-2"].status == "error"
    assert "mystery: unknown parameter" in by_id["call-2"].text
    assert "Valid parameters:" in by_id["call-2"].text
    assert by_id["call-3"].status == "error"
    assert "JSON decode error" in by_id["call-3"].text
    assert len(emitted) >= 3


def test_clean_utf8_formatting_for_hitl_schedule_and_agent_status() -> None:
    payload = AskPayload.model_validate(
        {
            "questions": [
                {
                    "id": "q1",
                    "text": "Chọn phương án?",
                    "type": "single_choice",
                    "options": [
                        {"id": "o1", "label": "Phương án A ✅"},
                        {"id": "o2", "label": "Phương án B"},
                    ],
                },
                {"id": "q2", "text": "Ghi chú thêm?", "type": "text"},
            ]
        }
    )
    response = AskResponse.model_validate(
        {
            "answers": {
                "q1": "o1",
                "q2": "Dòng 1 tiếng Việt 🇻🇳\nDòng 2 xuống dòng thật",
            },
            "note": "Cảm ơn bạn!\nTiếp tục nhé 🚀",
        }
    )
    rendered = format_hitl_response(payload, response)
    assert "Phương án A ✅" in rendered
    assert "Dòng 1 tiếng Việt 🇻🇳\n  Dòng 2 xuống dòng thật" in rendered
    assert "Note:\nCảm ơn bạn!\nTiếp tục nhé 🚀" in rendered
    assert "\\n" not in rendered
    assert "{'answers'" not in rendered

    outcome = HitlOutcome(applied=True, role="viewer", storage_id="s-123")
    assert format_hitl_outcome_attr(outcome) == "applied (viewer)"
    assert (
        format_hitl_outcome(outcome)
        == "Access granted (role=viewer, storage_id=s-123)."
    )

    hitl_xml = format_inbox_item_full(
        InboxRecord.model_validate(
            {
                "seq": 10,
                "kind": "hitl",
                "channel": "hitl",
                "reply_address": None,
                "sender": {
                    "type": "user",
                    "id": "u1",
                    "name": "Minh",
                    "handle": "minh",
                },
                "content": f"HITL resolved.\n{rendered}",
                "metadata": {
                    "request_id": "req-1",
                    "type": "ask",
                    "status": "answered",
                    "outcome": "applied (viewer)",
                },
                "created_at": "2026-11-27T03:00:00Z",
            }
        )
    )
    assert 'request_id="req-1"' in hitl_xml
    assert 'type="ask"' in hitl_xml
    assert 'status="answered"' in hitl_xml
    assert 'outcome="applied (viewer)"' in hitl_xml
    assert "Dòng 1 tiếng Việt 🇻🇳" in hitl_xml
    assert "\\n" not in hitl_xml

    sched_xml = format_inbox_item_full(
        InboxRecord.model_validate(
            {
                "seq": 11,
                "kind": "schedule",
                "channel": "schedule",
                "reply_address": None,
                "sender": {"type": "system", "id": "s1", "name": "schedule"},
                "content": "Báo cáo sáng ☀️\nGửi cho ethan",
                "metadata": {
                    "schedule_id": "sc-1",
                    "title": "Báo cáo sáng",
                    "scheduled_for": "2026-11-27T09:00:00+07:00",
                },
                "created_at": "2026-11-27T09:00:01+07:00",
            }
        )
    )
    assert 'scheduled_for="2026-11-27T09:00:00+07:00"' in sched_xml
    assert "Báo cáo sáng ☀️\nGửi cho ethan" in sched_xml

    ev_msg = format_activity_event_summary(
        "activity.message", {"text": "Đang phân tích báo cáo 📊\nBước 2 xong"}
    )
    assert ev_msg == "Đang phân tích báo cáo 📊 Bước 2 xong"
    assert "{'text'" not in ev_msg

    ev_tool = format_activity_event_summary(
        "activity.tool_call",
        {"name": "send_message", "args": {"to": "ethan", "content": "Xin chào 👋"}},
    )
    assert ev_tool == 'send_message({"to": "ethan", "content": "Xin chào 👋"})'
    assert "\\u" not in ev_tool


@pytest.mark.asyncio
async def test_tinyfish_fetch_and_search_use_fetch_and_search_apis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    next_fetch: list[FetchResponse | Exception] = []
    next_search: list[SearchQueryResponse | Exception] = []

    class _FakeFetch:
        async def get_contents(
            self,
            urls: list[str],
            *,
            format: str | None = None,  # noqa: A002  # Matches tinyfish SDK get_contents kwarg
            per_url_timeout_ms: int | None = None,
        ) -> FetchResponse:
            calls.append(
                (
                    "fetch",
                    {
                        "urls": urls,
                        "format": format,
                        "per_url_timeout_ms": per_url_timeout_ms,
                    },
                )
            )
            outcome = next_fetch.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class _FakeSearch:
        async def query(self, query: str) -> SearchQueryResponse:
            calls.append(("search", {"query": query}))
            outcome = next_search.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class _FakeTinyFish:
        def __init__(self, *, api_key: str, timeout: float = 30.0) -> None:
            self.api_key = api_key
            self.timeout = timeout
            self.fetch = _FakeFetch()
            self.search = _FakeSearch()

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    async def _allow_public(_url: str) -> None:
        return None

    monkeypatch.setattr(web_tools, "AsyncTinyFish", _FakeTinyFish)
    monkeypatch.setattr(web_tools, "assert_public_url", _allow_public)

    state: AgentState = {"messages": [], "inbox_cursor": 0}
    rt = ToolRuntime(
        state=state,
        context=_make_test_runtime_context(
            settings=LetaRuntimeConfig(
                web=WebConfig(fetch_mode="tinyfish", search_max_results=2),
                web_search_api_key="tf-test-key",
            )
        ),
        config={},
        stream_writer=lambda _chunk: None,
        tool_call_id="tc-web",
        store=None,
    )

    next_fetch.append(
        FetchResponse.model_validate(
            {
                "results": [
                    {
                        "url": "https://example.com/a",
                        "final_url": "https://example.com/final",
                        "title": "Example",
                        "published_date": "2026-11-01",
                        "text": "# Hello\nWorld",
                        "format": "markdown",
                    }
                ],
                "errors": [],
            }
        )
    )
    body, artifact = await web_tools.handle_webfetch(
        "https://example.com/a", format="markdown", timeout=15, runtime=rt
    )
    assert body == "# Hello\nWorld"
    assert artifact["final_url"] == "https://example.com/final"
    assert artifact["source"] == "tinyfish"
    assert calls[-1] == (
        "fetch",
        {
            "urls": ["https://example.com/a"],
            "format": "markdown",
            "per_url_timeout_ms": 15_000,
        },
    )

    next_fetch.append(
        FetchResponse.model_validate(
            {
                "results": [
                    {
                        "url": "https://example.com/b",
                        "text": "<h1>Heading</h1><p>Plain body</p>",
                        "format": "html",
                    }
                ],
                "errors": [],
            }
        )
    )
    plain, plain_meta = await web_tools.handle_webfetch(
        "https://example.com/b", format="text", runtime=rt
    )
    assert "Heading" in plain
    assert "Plain body" in plain
    assert "<h1>" not in plain
    assert plain_meta["content_type"] == "text/plain"

    next_fetch.append(
        FetchResponse.model_validate(
            {
                "results": [],
                "errors": [{"url": "https://example.com/err", "error": "blocked"}],
            }
        )
    )
    with pytest.raises(ToolException, match="blocked"):
        await web_tools.handle_webfetch("https://example.com/err", runtime=rt)

    next_fetch.append(SDKError("rate limited"))
    with pytest.raises(ToolException, match="rate limited"):
        await web_tools.handle_webfetch("https://example.com/err2", runtime=rt)

    next_search.append(
        SearchQueryResponse.model_validate(
            {
                "query": "openlet",
                "total_results": 3,
                "results": [
                    {
                        "position": 1,
                        "site_name": "example.com",
                        "title": "Doc 1",
                        "url": "https://example.com/1",
                        "snippet": "Snippet 1",
                        "date": "2026-10-01",
                    },
                    {
                        "position": 2,
                        "site_name": "example.com",
                        "title": "Doc 2",
                        "url": "https://example.com/2",
                        "snippet": "Snippet 2",
                    },
                    {
                        "position": 3,
                        "site_name": "example.com",
                        "title": "Doc 3",
                        "url": "https://example.com/3",
                        "snippet": "Snippet 3",
                    },
                ],
            }
        )
    )
    md, search_meta = await web_tools.handle_websearch("openlet", runtime=rt)
    assert "Doc 1" in md
    assert "2026-10-01" in md
    assert "Doc 3" not in md
    assert search_meta["provider"] == "tinyfish"
    assert isinstance(search_meta["results"], list)
    assert len(search_meta["results"]) == 2
    assert search_meta["results"][0] == {
        "title": "Doc 1",
        "url": "https://example.com/1",
        "published_at": "2026-10-01",
        "snippet": "Snippet 1",
    }
