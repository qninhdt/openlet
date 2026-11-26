"""Live Leta trial execution, output capture, and deliverable rendering."""

from __future__ import annotations

import asyncio
import re
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import httpx
import jinja2
from openlet_env import Environment
from openlet_env.dataset import read_seed_specs
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .suite import AgentEvalConfig, AgentTask

DEFAULT_PROMPT_TEMPLATE = """{{ task }}

---
Instructions:
- Ground all company, transaction, and document facts in `/shared`; do not invent unsupported facts or figures, and explicitly flag any missing or conflicting information.
- Complete the task autonomously without asking clarifying questions.
- Save your final deliverable(s) as file(s) in your conversation storage (`/chat/<handle>`), choosing whatever structure and formats best fit the work.
- Send only ONE message via `send_message` when the work is completely finished (do not send interim progress updates).
- In that final message, put ONLY the final deliverable/result file(s) in `attachments` (not inline mentions in text, and do not attach scratch files, scripts, intermediate drafts, or `/shared` source files).
- Keep the final message text to a brief summary of what was completed; do not put the detailed analysis or findings in the message text."""

_JINJA = jinja2.Environment(trim_blocks=True, lstrip_blocks=True, autoescape=False)
_LETFS_LINK_RE = re.compile(
    r"(?<!!)\[((?:\\.|[^\]\\\n]){1,1024})\]\(/letfs/([\w-]+)/([\w-]+)(?:/[^)\s]*)?\)"
)
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "paused"})


class RunUsage(BaseModel):
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0


class ToolCallRecord(BaseModel):
    name: str
    input_parameters: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None
    status: str = "unknown"


class ToolStats(BaseModel):
    total: int = 0
    errors: int = 0
    compactions: int = 0
    by_tool: dict[str, int] = Field(default_factory=dict)


class AssistantMessage(BaseModel):
    id: str = ""
    content: str = ""
    sources: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    attachments: list[str] = Field(default_factory=list[str])


class Attachment(BaseModel):
    path: str
    mime: str | None = None
    size: int | None = None
    text: str | None = None


class TrialArtifact(BaseModel):
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


def _json_obj(resp: httpx.Response) -> dict[str, Any]:
    raw: Any = resp.json()
    return cast(dict[str, Any], raw) if isinstance(raw, dict) else {}


def _sub_obj(obj: Mapping[str, Any], key: str) -> dict[str, Any]:
    raw = obj.get(key)
    return cast(dict[str, Any], raw) if isinstance(raw, dict) else {}


def _json_list(obj: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    raw = obj.get(key)
    return cast(list[dict[str, Any]], raw) if isinstance(raw, list) else []


def resolve_inline_mentions(
    content: str, path_map: Mapping[tuple[str, str], str]
) -> str:
    def _sub_letfs(m: re.Match[str]) -> str:
        label = re.sub(r"\\(.)", r"\1", m.group(1))
        path = path_map.get((m.group(2), m.group(3)))
        if not path:
            return label
        target = f"<{path}>" if any(c.isspace() or c in "()" for c in path) else path
        return f"[{label}]({target})"

    return _LETFS_LINK_RE.sub(_sub_letfs, content)


def parse_history(
    entries: Sequence[Mapping[str, Any]],
) -> tuple[list[ToolCallRecord], ToolStats]:
    """Pair tool_call and tool_result activity rows (v2 and legacy v1 schemas) + count compactions."""
    by_id: dict[str, ToolCallRecord] = {}
    calls: list[ToolCallRecord] = []
    counts: Counter[str] = Counter()
    errors = 0
    compactions = 0

    for entry in sorted(entries, key=lambda e: int(e.get("seq", 0))):
        ev_type = str(entry.get("type") or entry.get("kind") or "")
        raw_payload = entry.get("data") if "data" in entry else entry.get("payload")
        if not isinstance(raw_payload, Mapping):
            continue
        p = cast(Mapping[str, Any], raw_payload)
        cid = str(p.get("tool_call_id") or "")
        if ev_type in ("activity.tool_call", "tool_call"):
            name = str(p.get("name") or "unknown")
            counts[name] += 1
            raw_args = p.get("args")
            rec = ToolCallRecord(
                name=name,
                input_parameters=dict(cast(Mapping[str, Any], raw_args))
                if isinstance(raw_args, Mapping)
                else {},
            )
            if cid:
                by_id[cid] = rec
            calls.append(rec)
        elif ev_type in ("activity.tool_result", "tool_result"):
            status = str(p.get("status") or "success")
            errors += int(status == "error")
            if cid in by_id:
                out_val = (
                    p.get("content")
                    if "content" in p
                    else (p.get("preview") if "preview" in p else p.get("text"))
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
    node = _json_obj(r)
    parent_id = node.get("parentId")
    if not isinstance(parent_id, str) or not parent_id:
        path = prefix
    else:
        parent_path = await _resolve_path(client, wid, prefixes, cache, sid, parent_id)
        path = f"{(parent_path or prefix).rstrip('/')}/{node.get('name') or nid}"
    cache[(sid, nid)] = path
    return path


async def _wait_for_run(
    client: httpx.AsyncClient, root_path: str, agent_id: str, timeout_s: float
) -> tuple[dict[str, Any], bool]:
    deadline = time.monotonic() + timeout_s
    run_id: str | None = None
    run_row: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if run_id is None:
            runs_resp = await client.get(
                f"{root_path}/agents/{agent_id}/runs", params={"limit": 5}
            )
            if runs_resp.is_success:
                items = _json_list(_json_obj(runs_resp), "items")
                if items:
                    latest = items[0]
                    rid = latest.get("id")
                    if isinstance(rid, str):
                        run_id = rid
                        run_row = latest
                        if run_row.get("status") in _TERMINAL_STATES:
                            return run_row, False
        if run_id:
            resp = await client.get(f"{root_path}/agents/{agent_id}/runs/{run_id}")
            if resp.is_success:
                run_row = _json_obj(resp)
                if run_row.get("status") in _TERMINAL_STATES:
                    return run_row, False
        await asyncio.sleep(1.0)

    if run_id:
        try:
            await client.post(
                f"{root_path}/agents/{agent_id}/cancel",
                json={"run_id": run_id},
                timeout=15.0,
            )
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1.0)
        try:
            resp = await client.get(
                f"{root_path}/agents/{agent_id}/runs/{run_id}", timeout=15.0
            )
            if resp.is_success:
                run_row = _json_obj(resp)
        except httpx.HTTPError:
            pass
    return run_row, True


async def _collect_outputs(
    client: httpx.AsyncClient,
    wid: str,
    root_path: str,
    leta_id: str,
    conv_id: str,
    storage_prefixes: Mapping[str, str],
    path_cache: dict[tuple[str, str], str],
) -> tuple[list[AssistantMessage], list[Attachment], list[ToolCallRecord], ToolStats]:
    prefixes = dict(storage_prefixes)
    conv_sid: str | None = None
    conv = await client.post(
        f"/v1/workspaces/{wid}/conversations/{conv_id}:ensureStorage", json={}
    )
    if conv.is_success:
        cd = _json_obj(conv)
        conv_sid = str(cd.get("storageId") or "")
        conv_root = str(cd.get("rootNodeId") or "")
        if conv_sid and conv_root:
            prefixes[conv_sid] = "/chat"
            path_cache[(conv_sid, conv_root)] = "/chat"

    raw_msgs: list[dict[str, Any]] = []
    before_seq: int | None = None
    while True:
        params: dict[str, str] = {"limit": "100"}
        if before_seq is not None:
            params["beforeSeq"] = str(before_seq)
        r = await client.get(
            f"/v1/workspaces/{wid}/conversations/{conv_id}/messages", params=params
        )
        r.raise_for_status()
        data = _json_obj(r)
        items = _json_list(data, "messages")
        if not items:
            break
        raw_msgs.extend(m for m in items if m.get("senderType") == "agent")
        if not data.get("hasBefore"):
            break
        seqs = [int(m.get("seq", 0)) for m in items if int(m.get("seq", 0)) > 0]
        if not seqs or min(seqs) <= 1:
            break
        before_seq = min(seqs)

    raw_msgs.sort(key=lambda m: (int(m.get("seq", 0)), str(m.get("id") or "")))

    activity: list[dict[str, Any]] = []
    after = 0
    while True:
        r = await client.get(
            f"{root_path}/agents/{leta_id}/activity",
            params={"after": after, "limit": 100},
        )
        r.raise_for_status()
        data = _json_obj(r)
        items = _json_list(data, "items")
        if not items:
            break
        activity.extend(items)
        max_seq = max(int(it.get("seq", 0)) for it in items)
        if len(items) < 100 or max_seq <= after:
            break
        after = max_seq

    tool_calls, tool_stats = parse_history(activity)
    messages: list[AssistantMessage] = []
    attachments: list[Attachment] = []
    seen_att: set[tuple[str, str]] = set()

    last_idx = len(raw_msgs) - 1
    for idx, m in enumerate(raw_msgs):
        is_final = idx == last_idx
        raw_content = str(m.get("content") or "")
        for match in _LETFS_LINK_RE.finditer(raw_content):
            await _resolve_path(
                client, wid, prefixes, path_cache, match.group(2), match.group(3)
            )

        meta = _sub_obj(m, "metadata")
        sources: list[dict[str, Any]] = []
        for s in _json_list(meta, "sources"):
            if s.get("kind") == "web":
                sources.append(s)
                continue
            sid = str(s.get("storage_id") or "")
            nid = str(s.get("node_id") or "")
            resolved = await _resolve_path(client, wid, prefixes, path_cache, sid, nid)
            sources.append(
                {**s, "path": resolved or str(s.get("path") or s.get("label") or "")}
            )

        att_paths: list[str] = []
        for ref in _json_list(m, "attachments"):
            sid = str(ref.get("storageId") or "")
            nid = str(ref.get("nodeId") or "")
            name = str(ref.get("name") or nid)
            path = (
                await _resolve_path(client, wid, prefixes, path_cache, sid, nid)
                or f"/chat/{name}"
            )
            att_paths.append(path)
            if is_final and conv_sid and sid == conv_sid and (sid, nid) not in seen_att:
                seen_att.add((sid, nid))
                text: str | None = None
                if ref.get("kind") != "folder":
                    tr = await client.get(
                        f"/v1/workspaces/{wid}/storages/{sid}/nodes/{nid}:download"
                    )
                    if tr.is_success:
                        dl = _json_obj(tr)
                        txt_obj = _sub_obj(dl, "text")
                        if "content" in txt_obj:
                            text = str(txt_obj.get("content") or "")
                raw_sz = ref.get("sizeBytes") or ref.get("size")
                attachments.append(
                    Attachment(
                        path=path,
                        mime=str(ref.get("mediaType") or ref.get("mime") or "") or None,
                        size=int(raw_sz) if raw_sz is not None else None,
                        text=text,
                    )
                )
        messages.append(
            AssistantMessage(
                id=str(m.get("id") or ""),
                content=resolve_inline_mentions(raw_content, path_cache),
                sources=sources,
                attachments=att_paths,
            )
        )
    return messages, attachments, tool_calls, tool_stats


async def _execute_trial(
    cfg: AgentEvalConfig,
    api_url: str,
    ws_ctx: tuple[str, dict[str, str], Mapping[str, str], dict[tuple[str, str], str]],
    task: AgentTask,
    trial: int,
    idx: int,
) -> TrialArtifact:
    wid, headers, storage_prefixes, path_cache = ws_ctx
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
            leta_id = str(_json_obj(res)["id"])
            root = f"/v1/workspaces/{wid}/letas/{leta_id}"

            deadline = time.monotonic() + 60.0
            while time.monotonic() < deadline:
                st = await client.get(root)
                if st.is_success and _json_obj(st).get("state") == "active":
                    break
                await asyncio.sleep(0.5)
            else:
                raise TimeoutError(f"Leta {leta_id} did not become active within 60s")

            dm_resp = await client.post(
                f"/v1/workspaces/{wid}/conversations:dm",
                json={"target": {"type": "agent", "id": leta_id}},
            )
            dm_resp.raise_for_status()
            conv_id = str(_json_obj(dm_resp)["id"])

            prompt = (
                _JINJA.from_string(cfg.prompt_template).render(task=task.task).strip()
            )
            sent = await client.post(
                f"/v1/workspaces/{wid}/conversations/{conv_id}/messages",
                json={"idempotencyKey": str(uuid4()), "content": prompt},
            )
            sent.raise_for_status()

            run_row, timed_out = await _wait_for_run(
                client, root, leta_id, cfg.sample_timeout_seconds
            )
            latency_s = round(time.perf_counter() - t0, 3)
            messages, attachments, tool_calls, tool_stats = await _collect_outputs(
                client, wid, root, leta_id, conv_id, storage_prefixes, path_cache
            )
            return TrialArtifact(
                task_id=task.id,
                workspace=task.workspace,
                trial=trial,
                task=task.task,
                must=task.must,
                must_not=task.must_not,
                run_id=str(run_row.get("id") or ""),
                status="timeout"
                if timed_out
                else str(run_row.get("status") or "unknown"),
                error_code=run_row.get("error_code"),
                latency_s=latency_s,
                usage=RunUsage.model_validate(
                    {k: v for k, v in run_row.items() if v is not None}
                ),
                tool_stats=tool_stats,
                tools_called=tool_calls,
                messages=messages,
                attachments=attachments,
                deliverable=render_deliverable(attachments),
            )
        except Exception as exc:
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
                try:
                    await client.request(
                        "DELETE",
                        f"/v1/workspaces/{wid}/letas/{leta_id}",
                        json={"request_id": str(uuid4())},
                        timeout=15.0,
                    )
                except httpx.HTTPError:
                    pass


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
        owners = {s.handle: str(s.manifest["owner"]) for s in specs}

        async def _run_all() -> list[TrialArtifact]:
            ws_ctx: dict[
                str,
                tuple[str, dict[str, str], dict[str, str], dict[tuple[str, str], str]],
            ] = {}
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
                    for st in _json_list(_json_obj(r), "storages"):
                        if st.get("visibility") == "STORAGE_VISIBILITY_PUBLIC":
                            sid = str(st["id"])
                            prefixes[sid] = "/shared"
                            cache[(sid, str(st["rootNodeId"]))] = "/shared"
                ws_ctx[slug] = (wid, headers, prefixes, cache)

            sem = asyncio.Semaphore(cfg.concurrency)
            jobs = [
                (t, tr, i)
                for i, (t, tr) in enumerate(
                    (t, tr) for t in tasks for tr in range(1, cfg.trials + 1)
                )
            ]

            async def _bounded(t: AgentTask, tr: int, i: int) -> TrialArtifact:
                async with sem:
                    return await _execute_trial(
                        cfg, api_url, ws_ctx[t.workspace], t, tr, i
                    )

            return list(
                await asyncio.gather(*(_bounded(t, tr, i) for t, tr, i in jobs))
            )

        return asyncio.run(_run_all())
