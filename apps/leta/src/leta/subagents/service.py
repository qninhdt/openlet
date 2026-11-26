from __future__ import annotations

import asyncio
import re
import secrets
from typing import Literal
from uuid import UUID, uuid4

from openlet_sdk.config import JSON, ReasoningEffort
from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field
from temporalio.client import Client as TemporalClient
from temporalio.service import RPCError, RPCStatusCode

from ..activity import ActivityEmitter
from ..db import Pool, json_row
from ..inbox import InboxGateway, InboxItem, InboxSender

AVATAR_SHAPES: tuple[str, ...] = (
    "cercle",
    "galet",
    "squircle",
    "capsule",
    "triangle",
    "hexagone",
    "nuage",
    "goutte",
)
AVATAR_COLORS: tuple[str, ...] = (
    "rouge",
    "orange",
    "ambre",
    "vert",
    "turquoise",
    "bleu",
    "violet",
    "rose",
    "encre",
    "creme",
    "brun",
    "gris",
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class Appearance(BaseModel):
    shape: Literal[
        "cercle",
        "galet",
        "squircle",
        "capsule",
        "triangle",
        "hexagone",
        "nuage",
        "goutte",
    ]
    color: Literal[
        "rouge",
        "orange",
        "ambre",
        "vert",
        "turquoise",
        "bleu",
        "violet",
        "rose",
        "encre",
        "creme",
        "brun",
        "gris",
    ]


def random_appearance() -> dict[str, str]:
    return {
        "shape": secrets.choice(AVATAR_SHAPES),
        "color": secrets.choice(AVATAR_COLORS),
    }


def slugify_handle(text: str, *, fallback: str = "agent") -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    if len(slug) > 64:
        slug = slug[:64].rstrip("-")
    return slug or fallback


def root_handle_base(name: str, title: str) -> str:
    n = slugify_handle(name, fallback="leta")
    t = slugify_handle(title, fallback="")
    return f"{n}-the-{t}" if t else n


async def allocate_unique_root_handle(
    conn: AsyncConnection[DictRow], workspace_id: UUID, name: str, title: str
) -> str:
    base = root_handle_base(name, title)
    rows = await (
        await conn.execute(
            """
            SELECT a.handle
            FROM agents a
            JOIN letas l ON l.id = a.leta_id
            WHERE l.workspace_id = %s
              AND l.state IN ('provisioning', 'active')
              AND a.parent_agent_id IS NULL
              AND (a.handle = %s OR a.handle LIKE %s)
            """,
            (workspace_id, base, f"{base}-%"),
        )
    ).fetchall()
    taken = {str(r["handle"]) for r in rows}
    if base not in taken:
        return base
    for n in range(2, 1000):
        candidate = f"{base}-{n}"
        if candidate not in taken:
            return candidate
    return f"{base}-{uuid4().hex[:6]}"


async def allocate_unique_subagent_handle(
    conn: AsyncConnection[DictRow], leta_id: UUID, name: str, title: str = ""
) -> str:
    base = slugify_handle(name if not title else f"{name}-{title}", fallback="subagent")
    rows = await (
        await conn.execute(
            """
            SELECT handle
            FROM agents
            WHERE leta_id = %s AND state = 'active'
              AND (handle = %s OR handle LIKE %s)
            """,
            (leta_id, base, f"{base}-%"),
        )
    ).fetchall()
    taken = {str(r["handle"]) for r in rows}
    if base not in taken:
        return base
    for n in range(2, 1000):
        candidate = f"{base}-{n}"
        if candidate not in taken:
            return candidate
    return f"{base}-{uuid4().hex[:6]}"


class AgentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    appearance: Appearance | None = None
    custom_instructions: str | None = Field(default=None, max_length=32000)
    model_id: str | None = None
    reasoning_effort: ReasoningEffort = None


async def get_agent_row(db: Pool, agent_id: UUID) -> dict[str, object]:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                """
                SELECT a.*, l.workspace_id, l.storage_id, l.state AS leta_state, l.paused
                FROM agents a
                JOIN letas l ON l.id = a.leta_id
                WHERE a.id = %s
                """,
                (agent_id,),
            )
        ).fetchone()
    if row is None:
        raise LookupError("agent not found")
    return dict(row)


async def list_leta_agents(db: Pool, leta_id: UUID) -> list[dict[str, JSON]]:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT a.id, a.leta_id, a.parent_agent_id, a.depth, a.name, a.title,
                       a.description, a.appearance, a.handle, a.custom_instructions,
                       a.model_id, a.reasoning_effort, a.state, a.created_at,
                       EXISTS(
                           SELECT 1 FROM runs r
                           WHERE r.agent_id = a.id AND r.status = 'running'
                       ) AS running
                FROM agents a
                WHERE a.leta_id = %s
                ORDER BY a.depth ASC, a.created_at ASC
                """,
                (leta_id,),
            )
        ).fetchall()
    return [json_row(r) for r in rows]


async def update_agent(
    db: Pool,
    leta_id: UUID,
    agent_id: UUID,
    patch: AgentPatch,
) -> dict[str, JSON]:
    supplied = patch.model_fields_set
    async with db.connection() as conn, conn.transaction():
        current = await (
            await conn.execute(
                "SELECT * FROM agents WHERE id = %s AND leta_id = %s FOR UPDATE",
                (agent_id, leta_id),
            )
        ).fetchone()
        if current is None:
            raise LookupError("agent not found")
        if "custom_instructions" in supplied and current["parent_agent_id"] is not None:
            raise ValueError("custom_instructions can only be edited on the Root Leta")

        name = patch.name.strip() if patch.name is not None else current["name"]
        title = patch.title.strip() if patch.title is not None else current["title"]
        description = (
            patch.description
            if "description" in supplied and patch.description is not None
            else current["description"]
        )
        appearance = (
            patch.appearance.model_dump()
            if "appearance" in supplied and patch.appearance is not None
            else current["appearance"]
        )
        custom_instructions = (
            patch.custom_instructions
            if "custom_instructions" in supplied
            and patch.custom_instructions is not None
            else current["custom_instructions"]
        )
        model_id = patch.model_id if "model_id" in supplied else current["model_id"]
        reasoning_effort = (
            patch.reasoning_effort
            if "reasoning_effort" in supplied
            else current["reasoning_effort"]
        )

        # Immutable handle is intentionally preserved across edits.
        row = await (
            await conn.execute(
                """
                UPDATE agents
                SET name = %s,
                    title = %s,
                    description = %s,
                    appearance = %s,
                    custom_instructions = %s,
                    model_id = %s,
                    reasoning_effort = %s
                WHERE id = %s AND leta_id = %s
                RETURNING *
                """,
                (
                    name,
                    title,
                    description,
                    Jsonb(appearance),
                    custom_instructions,
                    model_id,
                    reasoning_effort,
                    agent_id,
                    leta_id,
                ),
            )
        ).fetchone()
    assert row is not None
    return json_row(row)


async def spawn_subagent(
    *,
    db: Pool,
    inbox: InboxGateway,
    activity: ActivityEmitter | None,
    parent_agent_id: UUID,
    name: str,
    title: str = "",
    description: str = "",
    task: str,
    model_id: str | None = None,
    reasoning_effort: ReasoningEffort = None,
    max_depth: int = 3,
    max_active_per_leta: int = 16,
    idempotency_key: str | None = None,
) -> dict[str, JSON]:
    async with db.connection() as conn, conn.transaction():
        parent = await (
            await conn.execute(
                """
                SELECT a.id, a.leta_id, a.depth, a.handle, a.name, a.model_id, a.reasoning_effort,
                       a.state, l.state AS leta_state
                FROM agents a
                JOIN letas l ON l.id = a.leta_id
                WHERE a.id = %s
                FOR UPDATE OF a
                """,
                (parent_agent_id,),
            )
        ).fetchone()
        if (
            parent is None
            or parent["state"] != "active"
            or parent["leta_state"] != "active"
        ):
            raise LookupError("parent agent is not active")

        new_depth = int(parent["depth"]) + 1
        if new_depth > max_depth:
            raise ValueError(f"maximum subagent depth ({max_depth}) reached")

        leta_id = UUID(str(parent["leta_id"]))
        count_row = await (
            await conn.execute(
                """
                SELECT count(*) AS cnt
                FROM agents
                WHERE leta_id = %s AND parent_agent_id IS NOT NULL AND state = 'active'
                """,
                (leta_id,),
            )
        ).fetchone()
        if count_row is not None and int(count_row["cnt"]) >= max_active_per_leta:
            raise ValueError(
                f"maximum active subagents per Leta ({max_active_per_leta}) reached"
            )

        handle = await allocate_unique_subagent_handle(conn, leta_id, name, title)
        sub_id = uuid4()
        appearance = random_appearance()
        eff_model = model_id if model_id is not None else parent["model_id"]
        eff_effort = (
            reasoning_effort
            if reasoning_effort is not None
            else parent["reasoning_effort"]
        )
        row = await (
            await conn.execute(
                """
                INSERT INTO agents(
                    id, leta_id, parent_agent_id, depth, name, title, description,
                    appearance, handle, custom_instructions, model_id, reasoning_effort, state
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '', %s, %s, 'active')
                RETURNING *
                """,
                (
                    sub_id,
                    leta_id,
                    parent_agent_id,
                    new_depth,
                    name.strip(),
                    title.strip(),
                    description.strip(),
                    Jsonb(appearance),
                    handle,
                    eff_model,
                    eff_effort,
                ),
            )
        ).fetchone()
    assert row is not None

    if activity is not None:
        await activity.emit(
            leta_id=leta_id,
            agent_id=parent_agent_id,
            event_type="subagent.spawned",
            data={
                "subagent_id": str(sub_id),
                "parent_agent_id": str(parent_agent_id),
                "handle": handle,
                "name": name.strip(),
                "title": title.strip(),
                "depth": new_depth,
                "appearance": {k: v for k, v in appearance.items()},
            },
        )

    await inbox.deliver(
        InboxItem(
            agent_id=sub_id,
            idempotency_key=idempotency_key or f"spawn:{sub_id}",
            kind="agent",
            channel="agent",
            reply_address=f"agent:{parent['handle']}",
            sender=InboxSender(
                type="agent",
                id=str(parent_agent_id),
                name=str(parent["name"]),
                handle=str(parent["handle"]),
            ),
            content=task,
            metadata={"spawned_by": str(parent["handle"])},
        )
    )
    return json_row(row)


async def stop_agent_tree(
    *,
    db: Pool,
    temporal: TemporalClient | None,
    activity: ActivityEmitter | None,
    agent_id: UUID,
    include_self: bool = True,
) -> list[UUID]:
    async with db.connection() as conn, conn.transaction():
        rows = await (
            await conn.execute(
                """
                WITH RECURSIVE subtree AS (
                    SELECT id, leta_id, parent_agent_id, handle
                    FROM agents WHERE id = %s
                    UNION ALL
                    SELECT c.id, c.leta_id, c.parent_agent_id, c.handle
                    FROM subtree s
                    JOIN agents c ON c.parent_agent_id = s.id
                )
                SELECT id, leta_id, parent_agent_id, handle
                FROM subtree
                WHERE (%s OR id <> %s)
                """,
                (agent_id, include_self, agent_id),
            )
        ).fetchall()
        stopped_ids = [UUID(str(r["id"])) for r in rows]
        if stopped_ids:
            await conn.execute(
                "UPDATE agents SET state = 'stopped' WHERE id = ANY(%s) AND state = 'active'",
                (stopped_ids,),
            )

    async def _stop_one(r: dict[str, object]) -> None:
        aid = UUID(str(r["id"]))
        leta_id = UUID(str(r["leta_id"]))
        if temporal is not None:
            try:
                handle = temporal.get_workflow_handle(f"agent/{aid}")
                await handle.signal("stop")
            except RPCError as exc:
                if exc.status != RPCStatusCode.NOT_FOUND:
                    raise
        if activity is not None:
            await activity.emit(
                leta_id=leta_id,
                agent_id=aid,
                event_type="subagent.stopped",
                data={"agent_id": str(aid), "handle": str(r["handle"])},
            )

    if rows:
        await asyncio.gather(*(_stop_one(r) for r in rows))
    return stopped_ids


async def notify_parent_failure(
    *, db: Pool, inbox: InboxGateway, agent_id: UUID, error_message: str
) -> None:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                """
                SELECT id, leta_id, parent_agent_id, name, handle
                FROM agents
                WHERE id = %s
                """,
                (agent_id,),
            )
        ).fetchone()
    if row is None or row["parent_agent_id"] is None:
        return
    parent_id = UUID(str(row["parent_agent_id"]))
    await inbox.deliver(
        InboxItem(
            agent_id=parent_id,
            idempotency_key=f"subagent-failed:{agent_id}:{uuid4().hex[:8]}",
            kind="notification",
            channel="agent",
            reply_address=f"agent:{row['handle']}",
            sender=InboxSender(
                type="system",
                id=str(agent_id),
                name=str(row["name"]),
                handle=str(row["handle"]),
            ),
            content="",
            metadata={
                "subagent_id": str(agent_id),
                "subagent_handle": str(row["handle"]),
                "subagent_name": str(row["name"]),
                "error": error_message or "unknown error",
                "event": "subagent_failed",
            },
        )
    )


async def list_workspace_root_agents(
    db: Pool, workspace_id: UUID, *, limit: int | None = None
) -> list[dict[str, JSON]]:
    async with db.connection() as conn:
        if limit is not None:
            rows = await (
                await conn.execute(
                    """
                    SELECT a.id, a.name, a.title, a.handle, a.description
                    FROM agents a JOIN letas l ON l.id = a.leta_id
                    WHERE l.workspace_id = %s AND l.state = 'active' AND a.parent_agent_id IS NULL
                    ORDER BY a.created_at ASC LIMIT %s
                    """,
                    (workspace_id, limit),
                )
            ).fetchall()
        else:
            rows = await (
                await conn.execute(
                    """
                    SELECT a.id, a.name, a.title, a.handle, a.description
                    FROM agents a JOIN letas l ON l.id = a.leta_id
                    WHERE l.workspace_id = %s AND l.state = 'active' AND a.parent_agent_id IS NULL
                    ORDER BY a.created_at ASC
                    """,
                    (workspace_id,),
                )
            ).fetchall()
    return [json_row(r) for r in rows]


async def resolve_leta_agent(
    db: Pool,
    leta_id: UUID,
    raw_ref: str,
    *,
    active_only: bool = True,
) -> dict[str, object] | None:
    cleaned = raw_ref.strip().removeprefix("agent:").lstrip("@").strip()
    if not cleaned:
        return None
    uid: UUID | None = None
    try:
        uid = UUID(cleaned)
    except ValueError:
        uid = None
    low = cleaned.lower()
    state_clause = "AND a.state = 'active'" if active_only else ""
    async with db.connection() as conn:
        if uid is not None:
            row = await (
                await conn.execute(
                    f"""
                    SELECT a.id, a.parent_agent_id, a.name, a.title, a.handle, a.state,
                           EXISTS(SELECT 1 FROM runs r WHERE r.agent_id = a.id AND r.status = 'running') AS running
                    FROM agents a
                    WHERE a.leta_id = %s AND a.id = %s {state_clause}
                    ORDER BY a.created_at DESC LIMIT 1
                    """,
                    (leta_id, uid),
                )
            ).fetchone()
        else:
            row = await (
                await conn.execute(
                    f"""
                    SELECT a.id, a.parent_agent_id, a.name, a.title, a.handle, a.state,
                           EXISTS(SELECT 1 FROM runs r WHERE r.agent_id = a.id AND r.status = 'running') AS running
                    FROM agents a
                    WHERE a.leta_id = %s AND lower(a.handle) = %s {state_clause}
                    ORDER BY a.created_at DESC LIMIT 1
                    """,
                    (leta_id, low),
                )
            ).fetchone()
    return dict(row) if row is not None else None


async def list_active_subagents_status(
    db: Pool, leta_id: UUID
) -> list[dict[str, object]]:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT a.handle, a.name, a.title, a.state,
                       EXISTS(SELECT 1 FROM runs r WHERE r.agent_id = a.id AND r.status = 'running') AS running
                FROM agents a
                WHERE a.leta_id = %s AND a.parent_agent_id IS NOT NULL AND a.state = 'active'
                ORDER BY running DESC, a.created_at DESC
                """,
                (leta_id,),
            )
        ).fetchall()
    return [dict(r) for r in rows]
