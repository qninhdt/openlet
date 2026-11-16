from typing import cast
from uuid import UUID

from openlet_sdk.config import JSON
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import Field, model_validator

from .agents import Input, appearance, gate, json_row, stable
from .db import Pool, Row, receipt, save_receipt


class LetiDefinition(Input):
    name: str = Field(min_length=1, max_length=255)
    title: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=4000)
    system_prompt: str = Field(min_length=1, max_length=32000)


class CreateBox(Input):
    name: str = Field(
        min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    description: str = Field(default="", max_length=4000)
    letis: list[LetiDefinition] = Field(min_length=1, max_length=20)
    edges: list[tuple[str, str]] = Field(max_length=190)
    representative: str

    @model_validator(mode="after")
    def graph(self) -> "CreateBox":
        names = {item.name for item in self.letis}
        if self.name == "root" or "root" in names:
            raise ValueError("root is reserved for the parent agent")
        if len(names) != len(self.letis) or self.representative not in names:
            raise ValueError("Leti names must be unique and include the representative")
        edges: set[tuple[str, str]] = set()
        for a, b in self.edges:
            edge = (min(a, b), max(a, b))
            if a not in names or b not in names or a == b or edge in edges:
                raise ValueError(
                    "Each edge must connect two distinct Leti names. Edges are bidirectional: "
                    "declare A-B once, without also declaring B-A."
                )
            edges.add(edge)
        return self


class BoxCreation(Input):
    leta_id: UUID
    box_id: UUID
    request_id: UUID
    request: CreateBox


async def prepare(db: Pool, creation: BoxCreation, home: UUID) -> dict[str, JSON]:
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
        await conn.execute(
            """INSERT INTO boxes(id,leta_id,name,description,representative_agent_id,home_node_id,state)
            VALUES(%s,%s,%s,%s,%s,%s,'active')""",
            (
                creation.box_id,
                creation.leta_id,
                creation.request.name,
                creation.request.description,
                ids[creation.request.representative],
                home,
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
            )
            for item in creation.request.letis
        ]
        await conn.execute(
            sql.SQL(
                "INSERT INTO agents(id,leta_id,box_id,name,description,system_prompt,title,appearance) VALUES {}"
            ).format(
                sql.SQL(",").join(sql.SQL("(%s,%s,%s,%s,%s,%s,%s,%s)") for _ in members)
            ),
            tuple(value for member in members for value in member),
        )
        edges = [
            (creation.box_id, *sorted((ids[a], ids[b])))
            for a, b in creation.request.edges
        ]
        if edges:
            await conn.execute(
                sql.SQL(
                    "INSERT INTO box_edges(box_id,agent_low_id,agent_high_id) VALUES {}"
                ).format(sql.SQL(",").join(sql.SQL("(%s,%s,%s)") for _ in edges)),
                tuple(value for edge in edges for value in edge),
            )
        result: dict[str, JSON] = {
            "id": str(creation.box_id),
            "state": "active",
            "home": f"~/.boxes/{creation.request.name}/",
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
                "SELECT id,representative_agent_id FROM boxes WHERE id=%s AND leta_id=%s",
                (id, root),
            )
        ).fetchone()
    if row is None:
        raise LookupError("box not found")
    return row


async def get(
    db: Pool, root: UUID, id_or_name: str, prompts: bool = False
) -> dict[str, JSON]:
    async with db.connection() as conn:
        box = await (
            await conn.execute(
                "SELECT * FROM boxes WHERE leta_id=%s AND (id::text=%s OR (name=%s AND state<>'archived'))",
                (root, id_or_name, id_or_name),
            )
        ).fetchone()
        if box is None:
            raise LookupError("box not found")
        members = await (
            await conn.execute(
                "SELECT id,name,title,appearance,description,model_id,reasoning_effort"
                + (",system_prompt" if prompts else "")
                + " FROM agents WHERE box_id=%s ORDER BY id",
                (box["id"],),
            )
        ).fetchall()
        edges = await (
            await conn.execute(
                "SELECT agent_low_id,agent_high_id FROM box_edges WHERE box_id=%s",
                (box["id"],),
            )
        ).fetchall()
    return {
        **json_row(box),
        "letis": [json_row(row) for row in members],
        "edges": [json_row(row) for row in edges],
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


async def named(db: Pool, root: UUID, name: str) -> Row:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT id,name,representative_agent_id FROM boxes WHERE leta_id=%s AND name=%s AND state<>'archived'",
                (root, name),
            )
        ).fetchone()
    if row is None:
        raise LookupError("box not found; use its exact name from box_list")
    return row


async def available(db: Pool, creation: BoxCreation) -> None:
    async with db.connection() as conn:
        existing = await (
            await conn.execute(
                "SELECT id FROM boxes WHERE leta_id=%s AND name=%s AND state<>'archived' AND id<>%s",
                (creation.leta_id, creation.request.name, creation.box_id),
            )
        ).fetchone()
    if existing:
        raise ValueError("box name is already in use; reuse it or choose another name")
