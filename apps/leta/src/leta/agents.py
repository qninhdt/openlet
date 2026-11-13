from datetime import datetime
from typing import Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from openlet_sdk.config import JSON, ReasoningEffort
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from .db import Connection, Pool, Row, receipt, save_receipt


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateLeta(Input):
    request_id: UUID
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    system_prompt: str = Field(default="", max_length=32000)
    model_id: str | None = None
    reasoning_effort: ReasoningEffort = None


class ConfigureAgent(Input):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    system_prompt: str | None = Field(default=None, max_length=32000)
    model_id: str | None = None
    reasoning_effort: ReasoningEffort = None


class RootCreation(Input):
    workspace_id: UUID
    owner_id: UUID
    leta_id: UUID
    storage_id: UUID
    root_node_id: UUID
    request: CreateLeta


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


async def prepare(db: Pool, creation: RootCreation) -> dict[str, JSON]:
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
            creation.request,
        )
        if saved is not None:
            return cast(dict[str, JSON], saved)
        await conn.execute(
            "INSERT INTO letas(id,workspace_id,storage_id,state) VALUES(%s,%s,%s,'provisioning')",
            (creation.leta_id, creation.workspace_id, creation.storage_id),
        )
        request = creation.request
        await conn.execute(
            """INSERT INTO agents(id,leta_id,name,description,system_prompt,model_id,reasoning_effort)
            VALUES(%s,%s,%s,%s,%s,%s,%s)""",
            (
                creation.leta_id,
                creation.leta_id,
                request.name,
                request.description,
                request.system_prompt,
                request.model_id,
                request.reasoning_effort,
            ),
        )
        result: dict[str, JSON] = {"id": str(creation.leta_id), "state": "provisioning"}
        await save_receipt(
            conn,
            f"user:{creation.owner_id}",
            "leta.create",
            request.request_id,
            request,
            result,
        )
        return result


async def finish_run(
    db: Pool,
    run_id: UUID,
    status: Literal["completed", "paused", "failed", "cancelled"],
    error: str | None = None,
) -> None:
    async with db.connection() as conn:
        await conn.execute(
            """UPDATE runs SET status=%s, finished_at=CASE WHEN %s='paused' THEN NULL ELSE now() END,
            error_code=%s WHERE id=%s AND status IN ('running','paused')""",
            (status, status, error, run_id),
        )


async def record(
    db: Pool, agent_id: UUID, run_id: UUID, identity: str, kind: str, payload: JSON
) -> UUID:
    id = uuid5(NAMESPACE_URL, f"{agent_id}/{identity}")
    async with db.connection() as conn, conn.transaction():
        await conn.execute("SELECT id FROM agents WHERE id=%s FOR UPDATE", (agent_id,))
        found = await (
            await conn.execute("SELECT id FROM history WHERE id=%s", (id,))
        ).fetchone()
        if found is None:
            seq = await (
                await conn.execute(
                    "UPDATE agents SET history_seq=history_seq+1 WHERE id=%s RETURNING history_seq",
                    (agent_id,),
                )
            ).fetchone()
            assert seq is not None
            await conn.execute(
                "INSERT INTO history(id,agent_id,run_id,seq,kind,payload) VALUES(%s,%s,%s,%s,%s,%s)",
                (id, agent_id, run_id, seq["history_seq"], kind, Jsonb(payload)),
            )
    return id


def json_row(row: Row) -> dict[str, JSON]:
    return {
        key: str(value)
        if isinstance(value, UUID)
        else value.isoformat()
        if isinstance(value, datetime)
        else cast(JSON, value)
        for key, value in row.items()
    }
