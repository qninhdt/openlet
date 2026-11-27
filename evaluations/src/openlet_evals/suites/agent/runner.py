"""Live Leta trial execution, output capture, and deliverable rendering."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
import jinja2
from openlet_env import Environment
from openlet_env.dataset import read_seed_specs
from openlet_sdk.types import JSON, MutableJsonObject
from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from openlet_evals.suites.agent.suite import AgentEvalConfig, AgentTask

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_TEMPLATE = """{{ task }}

---
Instructions:
- Ground all company, transaction, and document facts in `/shared`; do not invent unsupported facts or figures, and explicitly flag any missing or conflicting information.
- Complete the task autonomously without asking clarifying questions.
- Save your final deliverable(s) as file(s) in your conversation storage (`/chat/<handle>`), choosing whatever structure and formats best fit the work.
- Send only ONE message via `send_message` when the work is completely finished (do not send interim progress updates).
- In that final message, put ONLY the final deliverable/result file(s) in `attachments` (not inline mentions in text, and do not attach scratch files, scripts, intermediate drafts, or `/shared` source files).
- Keep the final message text to a brief summary of what was completed; do not put the detailed analysis or findings in the message text."""

_JINJA = jinja2.Environment(trim_blocks=True, lstrip_blocks=True, autoescape=False)  # noqa: S701  # LLM prompt template, not HTML.
_LETFS_LINK_RE = re.compile(
    r"(?<!!)\[((?:\\.|[^\]\\\n]){1,1024})\]\(/letfs/([\w-]+)/([\w-]+)(?:/[^)\s]*)?\)"
)
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "paused"})


class RunUsage(BaseModel):
    """Token, LLM call, and USD cost totals for one agent run."""

    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0


class ToolCallRecord(BaseModel):
    """Single paired tool call and result extracted from activity history."""

    name: str
    input_parameters: MutableJsonObject = Field(default_factory=dict)
    output: str | None = None
    status: str = "unknown"


@dataclass(slots=True)
class WorkspaceContext:
    """Per-workspace auth headers and storage-node path resolution cache."""

    workspace_id: str
    headers: dict[str, str]
    storage_prefixes: Mapping[str, str]
    path_cache: dict[tuple[str, str], str]


class ToolStats(BaseModel):
    """Aggregated tool call counts, errors, and compactions for one trial."""

    total: int = 0
    errors: int = 0
    compactions: int = 0
    by_tool: dict[str, int] = Field(default_factory=dict)


class MessageSource(BaseModel):
    """Citation source attached to an assistant message."""

    model_config = ConfigDict(extra="allow")

    kind: str = ""
    storage_id: str = ""
    node_id: str = ""
    path: str = ""
    label: str = ""


class AssistantMessage(BaseModel):
    """Normalized assistant message captured from a conversation."""

    id: str = ""
    content: str = ""
    sources: list[MessageSource] = Field(default_factory=list[MessageSource])
    attachments: list[str] = Field(default_factory=list[str])


class Attachment(BaseModel):
    """Deliverable file attached to the agent's final message."""

    path: str
    mime: str | None = None
    size: int | None = None
    text: str | None = None


class TrialArtifact(BaseModel):
    """Full captured transcript, telemetry, and deliverables for one trial."""

    task_id: str
    workspace: str
    trial: int
    task: str
    must: list[str]
    must_not: list[str] = Field(default_factory=list[str])
    run_id: str = ""
    status: str = "unknown"
    error_code: str | None = None
    latency_s: float = 0.0
    usage: RunUsage = Field(default_factory=RunUsage)
    tool_stats: ToolStats = Field(default_factory=ToolStats)
    tools_called: list[ToolCallRecord] = Field(default_factory=list[ToolCallRecord])
    messages: list[AssistantMessage] = Field(default_factory=list[AssistantMessage])
    attachments: list[Attachment] = Field(default_factory=list[Attachment])
    deliverable: str = ""


class _NodeResp(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    parent_id: str | None = Field(default=None, alias="parentId")
    name: str = ""


class RunStatusResp(BaseModel):
    """Run status and usage payload returned by the Leta runs API."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    status: str = "unknown"
    error_code: str | None = None
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0


class _RunsListResp(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[RunStatusResp] = Field(default_factory=list[RunStatusResp])


class _EnsureStorageResp(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    storage_id: str = Field(default="", alias="storageId")
    root_node_id: str = Field(default="", alias="rootNodeId")


class _ChatAttachmentRef(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    storage_id: str = Field(default="", alias="storageId")
    node_id: str = Field(default="", alias="nodeId")
    name: str = ""
    kind: str = ""
    media_type: str = Field(default="", alias="mediaType")
    mime: str = ""
    size_bytes: int | str | None = Field(default=None, alias="sizeBytes")
    size: int | str | None = None


class _ChatMessageMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sources: list[MessageSource] = Field(default_factory=list[MessageSource])


class _ChatMessageItem(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = ""
    seq: int = 0
    sender_type: str = Field(default="", alias="senderType")
    content: str = ""
    metadata: _ChatMessageMetadata = Field(default_factory=_ChatMessageMetadata)
    attachments: list[_ChatAttachmentRef] = Field(
        default_factory=list[_ChatAttachmentRef]
    )


class _MessagesPageResp(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    messages: list[_ChatMessageItem] = Field(default_factory=list[_ChatMessageItem])
    has_before: bool = Field(default=False, alias="hasBefore")


class _ActivityToolPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool_call_id: str = ""
    name: str = "unknown"
    args: MutableJsonObject = Field(default_factory=dict)
    status: str = "success"
    content: JSON = None
    preview: JSON = None
    text: JSON = None


class ActivityEventItem(BaseModel):
    """Single agent activity stream item."""

    model_config = ConfigDict(extra="ignore")

    seq: int = 0
    type: str = ""
    kind: str = ""
    data: _ActivityToolPayload | None = None
    payload: _ActivityToolPayload | None = None


class _ActivityPageResp(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[ActivityEventItem] = Field(default_factory=list[ActivityEventItem])


class _DownloadTextResp(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str | None = None


class _DownloadResp(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: _DownloadTextResp | None = None


class _IdResp(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str


class _LetaStateResp(BaseModel):
    model_config = ConfigDict(extra="ignore")

    state: str = ""


class _StorageSummary(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    root_node_id: str = Field(default="", alias="rootNodeId")
    visibility: str = ""


class _StoragesListResp(BaseModel):
    model_config = ConfigDict(extra="ignore")

    storages: list[_StorageSummary] = Field(default_factory=list[_StorageSummary])


def resolve_inline_mentions(
    content: str, path_map: Mapping[tuple[str, str], str]
) -> str:
    """Replace ``/letfs/<storage>/<node>`` links in Markdown with resolved paths."""

    def _sub_letfs(m: re.Match[str]) -> str:
        label = re.sub(r"\\(.)", r"\1", m.group(1))
        path = path_map.get((m.group(2), m.group(3)))
        if not path:
            return label
        target = f"<{path}>" if any(c.isspace() or c in "()" for c in path) else path
        return f"[{label}]({target})"

    return _LETFS_LINK_RE.sub(_sub_letfs, content)


def parse_history(
    entries: Sequence[ActivityEventItem],
) -> tuple[list[ToolCallRecord], ToolStats]:
    """Pair tool_call and tool_result activity rows + count compactions."""
    by_id: dict[str, ToolCallRecord] = {}
    calls: list[ToolCallRecord] = []
    counts: Counter[str] = Counter()
    errors = 0
    compactions = 0

    for entry in sorted(entries, key=lambda e: e.seq):
        ev_type = entry.type or entry.kind
        p = entry.data if entry.data is not None else entry.payload
        if p is None:
            continue
        cid = p.tool_call_id
        if ev_type in ("activity.tool_call", "tool_call"):
            name = p.name or "unknown"
            counts[name] += 1
            rec = ToolCallRecord(name=name, input_parameters=dict(p.args))
            if cid:
                by_id[cid] = rec
            calls.append(rec)
        elif ev_type in ("activity.tool_result", "tool_result"):
            status = p.status or "success"
            errors += int(status == "error")
            if cid in by_id:
                out_val = (
                    p.content
                    if p.content is not None
                    else (p.preview if p.preview is not None else p.text)
                )
                by_id[cid].output = None if out_val is None else str(out_val)
                by_id[cid].status = status
        elif ev_type in ("activity.compacted", "compaction"):
            compactions += 1

    return calls, ToolStats(
        total=len(calls),
        errors=errors,
        compactions=compactions,
        by_tool=dict(sorted(counts.items())),
    )


def render_deliverable(attachments: Sequence[Attachment]) -> str:
    """Render attached `/chat` deliverable files from the final message for grading."""
    if not attachments:
        return "(No deliverable files were attached to the final message.)"
    lines = ["# Deliverable Files"]
    for item in attachments:
        lines.extend(["", f"## `{item.path}`"])
        if item.text is not None:
            lines.append(item.text)
        else:
            sz = f", {item.size} bytes" if item.size is not None else ""
            lines.append(f"[binary file ({item.mime or 'binary'}): {item.path}{sz}]")
    return "\n".join(lines).strip()


def _agent_name(idx: int) -> str:
    chars: list[str] = []
    n = idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        chars.append(chr(ord("a") + rem))
    return "Eval" + "".join(reversed(chars))


async def _resolve_path(
    client: httpx.AsyncClient,
    wid: str,
    prefixes: Mapping[str, str],
    cache: dict[tuple[str, str], str],
    *,
    sid: str,
    nid: str,
) -> str | None:
    if (sid, nid) in cache:
        return cache[(sid, nid)]
    prefix = prefixes.get(sid)
    if not prefix:
        return None
    r = await client.get(f"/v1/workspaces/{wid}/storages/{sid}/nodes/{nid}")
    if not r.is_success:
        return None
    node = _NodeResp.model_validate(r.json())
    if not node.parent_id:
        path = prefix
    else:
        parent_path = await _resolve_path(
            client, wid, prefixes, cache, sid=sid, nid=node.parent_id
        )
        path = f"{(parent_path or prefix).rstrip('/')}/{node.name or nid}"
    cache[(sid, nid)] = path
    return path


async def wait_for_run(
    client: httpx.AsyncClient, root_path: str, agent_id: str, timeout_s: float
) -> tuple[RunStatusResp, bool]:
    """Poll the agent's latest run until terminal status or timeout cancellation."""
    deadline = time.monotonic() + timeout_s
    run_id: str | None = None
    run_row = RunStatusResp()
    while time.monotonic() < deadline:
        if run_id is None:
            runs_resp = await client.get(
                f"{root_path}/agents/{agent_id}/runs", params={"limit": 5}
            )
            if runs_resp.is_success:
                items = _RunsListResp.model_validate(runs_resp.json()).items
                if items and items[0].id:
                    run_id = items[0].id
                    run_row = items[0]
                    if run_row.status in _TERMINAL_STATES:
                        return run_row, False
        if run_id:
            resp = await client.get(f"{root_path}/agents/{agent_id}/runs/{run_id}")
            if resp.is_success:
                run_row = RunStatusResp.model_validate(resp.json())
                if run_row.status in _TERMINAL_STATES:
                    return run_row, False
        await asyncio.sleep(1.0)

    if run_id:
        with contextlib.suppress(httpx.HTTPError):
            await client.post(
                f"{root_path}/agents/{agent_id}/cancel",
                json={"run_id": run_id},
                timeout=15.0,
            )
        await asyncio.sleep(1.0)
        try:
            resp = await client.get(
                f"{root_path}/agents/{agent_id}/runs/{run_id}", timeout=15.0
            )
            if resp.is_success:
                run_row = RunStatusResp.model_validate(resp.json())
        except httpx.HTTPError:
            pass
    return run_row, True


async def _fetch_agent_messages(
    client: httpx.AsyncClient, wid: str, conv_id: str
) -> list[_ChatMessageItem]:
    raw_msgs: list[_ChatMessageItem] = []
    before_seq: int | None = None
    while True:
        params: dict[str, str] = {"limit": "100"}
        if before_seq is not None:
            params["beforeSeq"] = str(before_seq)
        r = await client.get(
            f"/v1/workspaces/{wid}/conversations/{conv_id}/messages", params=params
        )
        r.raise_for_status()
        page = _MessagesPageResp.model_validate(r.json())
        if not page.messages:
            break
        raw_msgs.extend(m for m in page.messages if m.sender_type == "agent")
        if not page.has_before:
            break
        seqs = [m.seq for m in page.messages if m.seq > 0]
        if not seqs or min(seqs) <= 1:
            break
        before_seq = min(seqs)
    raw_msgs.sort(key=lambda m: (m.seq, m.id))
    return raw_msgs


async def _fetch_activity_events(
    client: httpx.AsyncClient, root_path: str, leta_id: str
) -> list[ActivityEventItem]:
    activity: list[ActivityEventItem] = []
    after = 0
    while True:
        r = await client.get(
            f"{root_path}/agents/{leta_id}/activity",
            params={"after": after, "limit": 100},
        )
        r.raise_for_status()
        items = _ActivityPageResp.model_validate(r.json()).items
        if not items:
            break
        activity.extend(items)
        max_seq = max(it.seq for it in items)
        if len(items) < 100 or max_seq <= after:
            break
        after = max_seq
    return activity


async def _download_attachment(
    client: httpx.AsyncClient,
    wid: str,
    ref: _ChatAttachmentRef,
    path: str,
) -> Attachment:
    text: str | None = None
    if ref.kind != "folder":
        tr = await client.get(
            f"/v1/workspaces/{wid}/storages/{ref.storage_id}/nodes/{ref.node_id}:download"
        )
        if tr.is_success:
            dl = _DownloadResp.model_validate(tr.json())
            if dl.text is not None and dl.text.content is not None:
                text = dl.text.content
    raw_sz = ref.size_bytes if ref.size_bytes is not None else ref.size
    return Attachment(
        path=path,
        mime=(ref.media_type or ref.mime) or None,
        size=int(raw_sz) if raw_sz is not None else None,
        text=text,
    )


async def collect_outputs(
    client: httpx.AsyncClient,
    wid: str,
    root_path: str,
    leta_id: str,
    conv_id: str,
    *,
    storage_prefixes: Mapping[str, str],
    path_cache: dict[tuple[str, str], str],
) -> tuple[list[AssistantMessage], list[Attachment], list[ToolCallRecord], ToolStats]:
    """Collect agent messages, final attachments, and tool history for a finished run."""
    prefixes = dict(storage_prefixes)
    conv_sid: str | None = None
    conv = await client.post(
        f"/v1/workspaces/{wid}/conversations/{conv_id}:ensureStorage", json={}
    )
    if conv.is_success:
        cd = _EnsureStorageResp.model_validate(conv.json())
        conv_sid = cd.storage_id
        if conv_sid and cd.root_node_id:
            prefixes[conv_sid] = "/chat"
            path_cache[(conv_sid, cd.root_node_id)] = "/chat"

    raw_msgs = await _fetch_agent_messages(client, wid, conv_id)
    activity = await _fetch_activity_events(client, root_path, leta_id)
    tool_calls, tool_stats = parse_history(activity)
    messages: list[AssistantMessage] = []
    attachments: list[Attachment] = []
    seen_att: set[tuple[str, str]] = set()

    last_idx = len(raw_msgs) - 1
    for idx, m in enumerate(raw_msgs):
        is_final = idx == last_idx
        for match in _LETFS_LINK_RE.finditer(m.content):
            await _resolve_path(
                client,
                wid,
                prefixes,
                path_cache,
                sid=match.group(2),
                nid=match.group(3),
            )

        sources: list[MessageSource] = []
        for s in m.metadata.sources:
            if s.kind == "web":
                sources.append(s)
                continue
            resolved = await _resolve_path(
                client, wid, prefixes, path_cache, sid=s.storage_id, nid=s.node_id
            )
            sources.append(s.model_copy(update={"path": resolved or s.path or s.label}))

        att_paths: list[str] = []
        for ref in m.attachments:
            sid = ref.storage_id
            nid = ref.node_id
            name = ref.name or nid
            path = (
                await _resolve_path(client, wid, prefixes, path_cache, sid=sid, nid=nid)
                or f"/chat/{name}"
            )
            att_paths.append(path)
            if is_final and conv_sid and sid == conv_sid and (sid, nid) not in seen_att:
                seen_att.add((sid, nid))
                attachments.append(await _download_attachment(client, wid, ref, path))
        messages.append(
            AssistantMessage(
                id=m.id,
                content=resolve_inline_mentions(m.content, path_cache),
                sources=sources,
                attachments=att_paths,
            )
        )
    return messages, attachments, tool_calls, tool_stats


async def _wait_for_active_leta(
    client: httpx.AsyncClient, root: str, leta_id: str, timeout_s: float = 60.0
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        st = await client.get(root)
        if st.is_success and _LetaStateResp.model_validate(st.json()).state == "active":
            return
        await asyncio.sleep(0.5)
    raise TimeoutError(f"Leta {leta_id} did not become active within {timeout_s:g}s")


async def execute_trial(
    cfg: AgentEvalConfig,
    api_url: str,
    ws_ctx: WorkspaceContext,
    task: AgentTask,
    *,
    trial: int,
    idx: int,
) -> TrialArtifact:
    """Provision an ephemeral Leta agent, run one task trial, and capture outputs."""
    wid = ws_ctx.workspace_id
    headers = ws_ctx.headers
    storage_prefixes = ws_ctx.storage_prefixes
    path_cache = ws_ctx.path_cache
    t0 = time.perf_counter()
    leta_id: str | None = None
    async with httpx.AsyncClient(
        base_url=api_url, headers=headers, timeout=60.0
    ) as client:
        try:
            res = await client.post(
                f"/v1/workspaces/{wid}/letas",
                json={
                    "request_id": str(uuid4()),
                    "name": _agent_name(idx),
                    "title": "Evaluation Agent",
                    "custom_instructions": "",
                    "model_id": cfg.model,
                    "reasoning_effort": cfg.reasoning_effort,
                },
            )
            res.raise_for_status()
            leta_id = _IdResp.model_validate(res.json()).id
            root = f"/v1/workspaces/{wid}/letas/{leta_id}"
            await _wait_for_active_leta(client, root, leta_id)

            dm_resp = await client.post(
                f"/v1/workspaces/{wid}/conversations:dm",
                json={"target": {"type": "agent", "id": leta_id}},
            )
            dm_resp.raise_for_status()
            conv_id = _IdResp.model_validate(dm_resp.json()).id

            prompt = (
                _JINJA.from_string(cfg.prompt_template).render(task=task.task).strip()
            )
            sent = await client.post(
                f"/v1/workspaces/{wid}/conversations/{conv_id}/messages",
                json={"idempotencyKey": str(uuid4()), "content": prompt},
            )
            sent.raise_for_status()

            run_row, timed_out = await wait_for_run(
                client, root, leta_id, cfg.sample_timeout_seconds
            )
            latency_s = round(time.perf_counter() - t0, 3)
            messages, attachments, tool_calls, tool_stats = await collect_outputs(
                client,
                wid,
                root,
                leta_id,
                conv_id,
                storage_prefixes=storage_prefixes,
                path_cache=path_cache,
            )
            return TrialArtifact(
                task_id=task.id,
                workspace=task.workspace,
                trial=trial,
                task=task.task,
                must=task.must,
                must_not=task.must_not,
                run_id=run_row.id,
                status="timeout" if timed_out else run_row.status,
                error_code=run_row.error_code,
                latency_s=latency_s,
                usage=RunUsage(
                    input_tokens=run_row.input_tokens,
                    cached_input_tokens=run_row.cached_input_tokens,
                    output_tokens=run_row.output_tokens,
                    reasoning_tokens=run_row.reasoning_tokens,
                    cost_usd=run_row.cost_usd,
                    llm_calls=run_row.llm_calls,
                ),
                tool_stats=tool_stats,
                tools_called=tool_calls,
                messages=messages,
                attachments=attachments,
                deliverable=render_deliverable(attachments),
            )
        except (
            httpx.HTTPError,
            ValidationError,
            TimeoutError,
            ValueError,
            RuntimeError,
        ) as exc:
            logger.warning("Trial %s#%s failed", task.id, trial, exc_info=True)
            return TrialArtifact(
                task_id=task.id,
                workspace=task.workspace,
                trial=trial,
                task=task.task,
                must=task.must,
                must_not=task.must_not,
                status="error",
                error_code=f"{type(exc).__name__}: {exc}",
                latency_s=round(time.perf_counter() - t0, 3),
                deliverable=render_deliverable([]),
            )
        finally:
            if leta_id:
                with contextlib.suppress(httpx.HTTPError):
                    await client.request(
                        "DELETE",
                        f"/v1/workspaces/{wid}/letas/{leta_id}",
                        json={"request_id": str(uuid4())},
                        timeout=15.0,
                    )


def run_trials(
    repo_root: Path,
    cfg: AgentEvalConfig,
    tasks: Sequence[AgentTask],
    *,
    keep_stack: bool = False,
) -> list[TrialArtifact]:
    """Boot one openlet-env stack, seed required workspaces once, and run all (task x trial)."""
    workspaces = sorted({t.workspace for t in tasks})
    datasets_dir = repo_root / cfg.datasets_dir
    env = Environment(
        project=cfg.env_project,
        mode="live",
        profiles=("leta",),
        config_overrides={
            "models": {"gateway": {"timeout_seconds": cfg.gateway_timeout_seconds}},
            "services": {"leta": {"tools": dict(cfg.tools)}},
        },
        repo_root=repo_root,
        teardown_on_exit=not keep_stack,
        teardown_volumes=not keep_stack,
    )
    with env:
        seeded = env.seed(
            dataset_dir=datasets_dir, workspaces=workspaces, idempotent=True
        )
        api_url = env.endpoints.api_url
        _, specs = read_seed_specs(datasets_dir, workspaces)
        owners = {s.handle: s.manifest.owner for s in specs}

        async def _run_all() -> list[TrialArtifact]:
            ws_ctx: dict[str, WorkspaceContext] = {}
            for slug in workspaces:
                wid = env.state.seeded_workspaces[slug]
                token = env.token(owners[slug], ttl_seconds=12 * 3600)
                headers = {"Authorization": f"Bearer {token}"}
                if seeded.zed_token:
                    headers["x-openlet-zed-token"] = seeded.zed_token
                prefixes: dict[str, str] = {}
                cache: dict[tuple[str, str], str] = {}
                async with httpx.AsyncClient(
                    base_url=api_url,
                    headers=headers,
                    timeout=30.0,
                ) as c:
                    r = await c.get(f"/v1/workspaces/{wid}/storages")
                    r.raise_for_status()
                    for st in _StoragesListResp.model_validate(r.json()).storages:
                        if st.visibility == "STORAGE_VISIBILITY_PUBLIC":
                            prefixes[st.id] = "/shared"
                            cache[(st.id, st.root_node_id)] = "/shared"
                ws_ctx[slug] = WorkspaceContext(
                    workspace_id=wid,
                    headers=headers,
                    storage_prefixes=prefixes,
                    path_cache=cache,
                )

            sem = asyncio.Semaphore(cfg.concurrency)
            jobs = [
                (t, tr, i)
                for i, (t, tr) in enumerate(
                    (t, tr) for t in tasks for tr in range(1, cfg.trials + 1)
                )
            ]

            async def _bounded(t: AgentTask, tr: int, i: int) -> TrialArtifact:
                async with sem:
                    return await execute_trial(
                        cfg, api_url, ws_ctx[t.workspace], t, trial=tr, idx=i
                    )

            return list(
                await asyncio.gather(*(_bounded(t, tr, i) for t, tr, i in jobs))
            )

        return asyncio.run(_run_all())
