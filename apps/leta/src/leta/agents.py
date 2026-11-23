import re
from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from openlet_sdk.config import JSON, ReasoningEffort
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from .db import Connection, Pool, Row, receipt, save_receipt


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


AgentName = Annotated[str, Field(max_length=255, pattern=r"^[A-Za-z]+$")]


def bare_title(value: str) -> str:
    if value.partition(" ")[0] == "The":
        raise ValueError("Use a job title without the leading 'The'")
    return value


AgentTitle = Annotated[
    str,
    Field(max_length=255, pattern=r"^[A-Z][A-Za-z0-9-]*(?: [A-Z][A-Za-z0-9-]*)*$"),
    AfterValidator(bare_title),
]


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def agent_handle(name: str, title: str) -> str:
    return f"{slug(name)}-the-{slug(title)}"


class Appearance(Input):
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


def appearance(id: UUID) -> dict[str, str]:
    # UUID-based selection survives lifecycle retries and does not depend on the name.
    return {
        "shape": (
            "cercle",
            "galet",
            "squircle",
            "capsule",
            "triangle",
            "hexagone",
            "nuage",
            "goutte",
        )[id.bytes[0] % 8],
        "color": (
            "rouge",
            "orange",
            "ambre",
            "vert",
            "turquoise",
            "bleu",
            "violet",
            "rose",
        )[id.bytes[1] % 8],
    }


class CreateLeta(Input):
    request_id: UUID
    name: AgentName
    title: AgentTitle
    appearance: Appearance | None = None
    description: str = Field(default="", max_length=4000)
    system_prompt: str = Field(default="", max_length=32000)
    model_id: str | None = None
    reasoning_effort: ReasoningEffort = None


class ConfigureAgent(Input):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    appearance: Appearance | None = None
    description: str | None = Field(default=None, max_length=4000)
    system_prompt: str | None = Field(default=None, max_length=32000)
    model_id: str | None = None
    reasoning_effort: ReasoningEffort = None

    @model_validator(mode="after")
    def required_values(self) -> "ConfigureAgent":
        if any(
            getattr(self, name) is None
            for name in self.model_fields_set
            & {"name", "title", "appearance", "description", "system_prompt"}
        ):
            raise ValueError(
                "name, title, appearance, description and system_prompt cannot be null"
            )
        if (
            "model_id" in self.model_fields_set
            and self.model_id is None
            and self.reasoning_effort is not None
        ):
            raise ValueError("reasoning effort requires an explicit model")
        return self


class LetaRequest(Input):
    workspace_id: UUID
    owner_id: UUID
    request: CreateLeta


class LetaCreation(LetaRequest):
    leta_id: UUID
    storage_id: UUID
    root_node_id: UUID


def stable(scope: UUID, name: str) -> UUID:
    return uuid5(scope, name)


async def get_agent(db: Pool, id: UUID) -> Row:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                """SELECT a.*,l.workspace_id,l.storage_id,l.state,l.paused,
            b.home_node_id,b.state AS box_state FROM agents a JOIN letas l ON l.id=a.leta_id
            LEFT JOIN boxes b ON b.id=a.box_id WHERE a.id=%s""",
                (id,),
            )
        ).fetchone()
    if row is None:
        raise LookupError("agent not found")
    return row


async def gate(conn: Connection, leta: UUID, box: UUID | None = None) -> Row:
    root = await (
        await conn.execute("SELECT * FROM letas WHERE id=%s FOR UPDATE", (leta,))
    ).fetchone()
    if root is None or root["state"] != "active":
        raise ValueError("Leta is inactive")
    if box is not None:
        row = await (
            await conn.execute(
                "SELECT state FROM boxes WHERE id=%s AND leta_id=%s FOR UPDATE",
                (box, leta),
            )
        ).fetchone()
        if row is None or row["state"] != "active":
            raise ValueError("box is inactive")
    return root


async def prepare(db: Pool, creation: LetaCreation) -> dict[str, JSON]:
    original = LetaRequest(
        workspace_id=creation.workspace_id,
        owner_id=creation.owner_id,
        request=creation.request,
    )
    async with db.connection() as conn, conn.transaction():
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (str(creation.request.request_id),),
        )
        saved = await receipt(
            conn,
            f"user:{creation.owner_id}",
            "leta.create",
            creation.request.request_id,
            original,
        )
        if saved is not None:
            return cast(dict[str, JSON], saved)
        await conn.execute(
            "INSERT INTO letas(id,workspace_id,storage_id,state) VALUES(%s,%s,%s,'provisioning')",
            (creation.leta_id, creation.workspace_id, creation.storage_id),
        )
        request = creation.request
        await conn.execute(
            """INSERT INTO agents(id,leta_id,name,description,system_prompt,model_id,reasoning_effort,title,appearance,handle)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                creation.leta_id,
                creation.leta_id,
                request.name,
                request.description,
                request.system_prompt,
                request.model_id,
                request.reasoning_effort,
                request.title,
                Jsonb(
                    request.appearance.model_dump()
                    if request.appearance
                    else appearance(creation.leta_id)
                ),
                agent_handle(request.name, request.title),
            ),
        )
        result: dict[str, JSON] = {"id": str(creation.leta_id), "state": "provisioning"}
        await save_receipt(
            conn,
            f"user:{creation.owner_id}",
            "leta.create",
            request.request_id,
            original,
            result,
        )
        return result


async def finish_run(
    db: Pool,
    run_id: UUID,
    status: Literal["completed", "paused", "failed", "cancelled"],
    error: str | None = None,
) -> Row | None:
    async with db.connection() as conn:
        return await (
            await conn.execute(
                """UPDATE runs r SET status=%s,
                finished_at=CASE WHEN %s='paused' THEN NULL ELSE now() END,error_code=%s
                FROM agents a WHERE r.id=%s AND a.id=r.agent_id
                AND (r.status IN ('running','paused') OR r.status=%s) RETURNING r.agent_id,a.leta_id""",
                (status, status, error, run_id, status),
            )
        ).fetchone()


def history_id(agent: UUID, identity: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"{agent}/{identity}")


async def record_batch(
    db: Pool, agent_id: UUID, run_id: UUID, entries: list[tuple[str, str, JSON]]
) -> list[tuple[UUID, str, JSON]]:
    ordered = {
        history_id(agent_id, identity): (kind, body) for identity, kind, body in entries
    }
    if not ordered:
        return []
    async with db.connection() as conn, conn.transaction():
        await conn.execute("SELECT id FROM agents WHERE id=%s FOR UPDATE", (agent_id,))
        found = await (
            await conn.execute(
                "SELECT id FROM history WHERE id=ANY(%s)", (list(ordered),)
            )
        ).fetchall()
        existing = {row["id"] for row in found}
        new = [
            (id, kind, body)
            for id, (kind, body) in ordered.items()
            if id not in existing
        ]
        if new:
            counter = await (
                await conn.execute(
                    "UPDATE agents SET history_seq=history_seq+%s WHERE id=%s RETURNING history_seq",
                    (len(new), agent_id),
                )
            ).fetchone()
            assert counter is not None
            start = cast(int, counter["history_seq"]) - len(new)
            values = [
                (id, agent_id, run_id, start + index, kind, Jsonb(body))
                for index, (id, kind, body) in enumerate(new, 1)
            ]
            await conn.execute(
                sql.SQL(
                    "INSERT INTO history(id,agent_id,run_id,seq,kind,payload) VALUES {} "
                ).format(
                    sql.SQL(",").join(sql.SQL("(%s,%s,%s,%s,%s,%s)") for _ in values)
                ),
                tuple(value for row in values for value in row),
            )
    return [(id, kind, body) for id, (kind, body) in ordered.items()]


def json_row(row: Row) -> dict[str, JSON]:
    return {
        key: str(value)
        if isinstance(value, UUID)
        else value.isoformat()
        if isinstance(value, datetime)
        else cast(JSON, value)
        for key, value in row.items()
    }
