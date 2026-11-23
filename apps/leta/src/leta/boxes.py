from typing import cast
from uuid import UUID

from openlet_sdk.config import JSON
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import Field, model_validator

from .agents import (
    AgentName,
    AgentTitle,
    Input,
    agent_handle,
    appearance,
    gate,
    json_row,
    slug,
    stable,
)
from .db import Pool, Row, receipt, save_receipt


class LetiDefinition(Input):
    name: AgentName
    title: AgentTitle
    description: str = Field(default="", max_length=4000)
    system_prompt: str = Field(min_length=1, max_length=32000)


class CreateBox(Input):
    name: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9 -]*$"
    )
    description: str = Field(default="", max_length=4000)
    letis: list[LetiDefinition] = Field(min_length=1, max_length=20)
    workflow: str = Field(default="", max_length=4000)
    additional_links: list[tuple[str, str]] = Field(
        default_factory=list[tuple[str, str]], max_length=171
    )
    leader: str

    @model_validator(mode="after")
    def graph(self) -> "CreateBox":
        names = {item.name for item in self.letis}
        if (
            len({name.lower() for name in names}) != len(self.letis)
            or self.leader not in names
        ):
            raise ValueError("Leti names must be unique and include the Leader")
        links: set[tuple[str, str]] = set()
        for a, b in self.additional_links:
            link = (min(a, b), max(a, b))
            if (
                a not in names
                or b not in names
                or a == b
                or self.leader in link
                or link in links
            ):
                raise ValueError(
                    "Declare each additional link once between two distinct non-Leader members."
                )
            links.add(link)
        return self


class BoxCreation(Input):
    leta_id: UUID
    box_id: UUID
    request_id: UUID
    request: CreateBox


async def prepare(
    db: Pool, creation: BoxCreation, home: UUID, handle: str
) -> dict[str, JSON]:
    async with db.connection() as conn, conn.transaction():
        await gate(conn, creation.leta_id)
        saved = await receipt(
            conn,
            f"agent:{creation.leta_id}",
            "box.create",
            creation.request_id,
            creation.request,
        )
        if saved is not None:
            return cast(dict[str, JSON], saved)
        ids = {
            item.name: stable(creation.box_id, item.name)
            for item in creation.request.letis
        }
        roster: list[dict[str, JSON]] = [
            {
                "name": item.name,
                "title": item.title,
                "handle": agent_handle(item.name, item.title),
            }
            for item in creation.request.letis
        ]
        await conn.execute(
            """INSERT INTO boxes(id,leta_id,name,description,leader_agent_id,home_node_id,handle,workflow,state)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'active')""",
            (
                creation.box_id,
                creation.leta_id,
                creation.request.name,
                creation.request.description,
                ids[creation.request.leader],
                home,
                handle,
                creation.request.workflow,
            ),
        )
        members = [
            (
                ids[item.name],
                creation.leta_id,
                creation.box_id,
                item.name,
                item.description,
                item.system_prompt,
                item.title,
                Jsonb(appearance(ids[item.name])),
                definition["handle"],
            )
            for item, definition in zip(creation.request.letis, roster, strict=True)
        ]
        await conn.execute(
            sql.SQL(
                "INSERT INTO agents(id,leta_id,box_id,name,description,system_prompt,title,appearance,handle) VALUES {}"
            ).format(
                sql.SQL(",").join(
                    sql.SQL("(%s,%s,%s,%s,%s,%s,%s,%s,%s)") for _ in members
                )
            ),
            tuple(value for member in members for value in member),
        )
        links = [
            (creation.box_id, *sorted((ids[a], ids[b])))
            for a, b in creation.request.additional_links
        ]
        if links:
            await conn.execute(
                sql.SQL(
                    "INSERT INTO box_links(box_id,agent_low_id,agent_high_id) VALUES {}"
                ).format(sql.SQL(",").join(sql.SQL("(%s,%s,%s)") for _ in links)),
                tuple(value for link in links for value in link),
            )
        leader = next(
            item for item in roster if item["name"] == creation.request.leader
        )
        result: dict[str, JSON] = {
            "id": str(creation.box_id),
            "state": "active",
            "home": f"~/.boxes/{handle}/",
            "handle": handle,
            "name": creation.request.name,
            "description": creation.request.description,
            "workflow": creation.request.workflow,
            "leader": {"name": leader["name"], "handle": leader["handle"]},
            "letis": list(roster),
        }
        await save_receipt(
            conn,
            f"agent:{creation.leta_id}",
            "box.create",
            creation.request_id,
            creation.request,
            result,
        )
        return result


async def identity(db: Pool, root: UUID, id: UUID) -> Row:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT id,leader_agent_id FROM boxes WHERE id=%s AND leta_id=%s",
                (id, root),
            )
        ).fetchone()
    if row is None:
        raise LookupError("box not found")
    return row


async def get(db: Pool, root: UUID, id: UUID, prompts: bool = False) -> dict[str, JSON]:
    async with db.connection() as conn:
        box = await (
            await conn.execute(
                "SELECT * FROM boxes WHERE leta_id=%s AND id=%s",
                (root, id),
            )
        ).fetchone()
        if box is None:
            raise LookupError("box not found")
        members = await (
            await conn.execute(
                "SELECT id,name,title,handle,appearance,description,model_id,reasoning_effort"
                + (",system_prompt" if prompts else "")
                + " FROM agents WHERE box_id=%s ORDER BY id",
                (box["id"],),
            )
        ).fetchall()
        links = await (
            await conn.execute(
                "SELECT agent_low_id,agent_high_id FROM box_links WHERE box_id=%s",
                (box["id"],),
            )
        ).fetchall()
    return {
        **json_row(box),
        "letis": [json_row(row) for row in members],
        "additional_links": [json_row(row) for row in links],
    }


async def list_boxes(
    db: Pool, root: UUID, after: UUID | None = None
) -> dict[str, JSON]:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT b.*,count(a.id) AS agent_count FROM boxes b LEFT JOIN agents a ON a.box_id=b.id
            WHERE b.leta_id=%s AND (%s::uuid IS NULL OR b.id>%s) GROUP BY b.id ORDER BY b.id LIMIT 20""",
                (root, after, after),
            )
        ).fetchall()
    return {
        "boxes": [json_row(row) for row in rows],
        "next_cursor": str(rows[-1]["id"]) if len(rows) == 20 else None,
    }


async def by_handle(db: Pool, root: UUID, handle: str) -> Row:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT id,name,handle,leader_agent_id FROM boxes WHERE leta_id=%s AND handle=%s AND state<>'archived'",
                (root, handle),
            )
        ).fetchone()
    if row is None:
        raise LookupError("box not found; use its handle from box_list")
    return row


async def next_handle(db: Pool, creation: BoxCreation) -> str:
    base = slug(creation.request.name)
    async with db.connection() as conn:
        taken = await (
            await conn.execute(
                "SELECT handle FROM agents WHERE leta_id=%s AND box_id IS DISTINCT FROM %s AND handle=ANY(%s) LIMIT 1",
                (
                    creation.leta_id,
                    creation.box_id,
                    [
                        agent_handle(item.name, item.title)
                        for item in creation.request.letis
                    ],
                ),
            )
        ).fetchone()
        if taken:
            raise ValueError(
                f"Agent handle {taken['handle']} is already in use. Choose another name."
            )
        rows = await (
            await conn.execute(
                "SELECT handle FROM boxes WHERE leta_id=%s AND id<>%s AND (handle=%s OR handle LIKE %s)",
                (creation.leta_id, creation.box_id, base, f"{base}-%"),
            )
        ).fetchall()
    used = {row["handle"] for row in rows}
    handle, suffix = base, 2
    while handle in used:
        handle = f"{base}-{suffix}"
        suffix += 1
    return handle
