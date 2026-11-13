from datetime import datetime
from typing import Literal, cast
from uuid import UUID

import grpc
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_api.letfs.v1.letfs_pb2_grpc import LetFSServiceStub
from openlet_sdk.config import JSON
from psycopg.types.json import Jsonb
from pydantic import Field, model_validator

from .agents import Input, gate, get_agent, json_row
from .auth import Actor, Authorization
from .db import Pool, effect


class Question(Input):
    text: str = Field(min_length=1, max_length=4000)
    options: list[str] | None = Field(default=None, min_length=2, max_length=20)
    multiple: bool = False

    @model_validator(mode="after")
    def choices(self) -> "Question":
        if self.multiple and self.options is None:
            raise ValueError("multiple selection requires options")
        if self.options and (
            len(set(self.options)) != len(self.options)
            or any(not text for text in self.options)
        ):
            raise ValueError("options must be unique nonempty labels")
        return self


class OpenRequest(Input):
    id: UUID
    requester_agent_id: UUID
    recipient_user_id: UUID
    type: Literal["ask", "approval"]
    title: str = Field(min_length=1, max_length=255)
    payload: dict[str, JSON]
    expires_at: datetime | None = None


class Decision(Input):
    request_id: UUID
    actor: Actor
    status: Literal["answered", "accepted", "denied", "cancelled", "expired"]
    response: dict[str, JSON] | None = None
    resolved_at: datetime


def form(questions: list[Question]) -> dict[str, JSON]:
    items: list[JSON] = []
    for index, question in enumerate(questions):
        item: dict[str, JSON] = {
            "id": f"q{index + 1}",
            "text": question.text,
            "type": "multiple_choice"
            if question.multiple
            else "single_choice"
            if question.options
            else "text",
        }
        if question.options:
            item["options"] = [
                {"id": f"o{i + 1}", "label": text}
                for i, text in enumerate(question.options)
            ]
        items.append(item)
    return {"questions": items}


async def get(db: Pool, id: UUID) -> dict[str, JSON]:
    async with db.connection() as conn:
        row = await (
            await conn.execute("SELECT * FROM hitl_requests WHERE id=%s", (id,))
        ).fetchone()
    if row is None:
        raise LookupError("request not found")
    return json_row(row)


async def open_request(
    db: Pool, auth: Authorization, files: LetFSServiceStub, request: OpenRequest
) -> dict[str, JSON]:
    agent = await get_agent(db, request.requester_agent_id)
    await auth.require(
        Actor("user", request.recipient_user_id),
        "workspace",
        cast(UUID, agent["workspace_id"]),
        "participate",
    )
    if request.type == "approval":
        await files.GetStorage(
            fs.StorageRequest(
                workspace_id=str(agent["workspace_id"]),
                storage_id=str(request.payload["storage_id"]),
            ),
            metadata=Actor("user", request.recipient_user_id).metadata,
            timeout=15,
        )
        permission = "write" if request.payload["role"] == "editor" else "read"
        if await auth.allowed(
            Actor("agent", cast(UUID, agent["leta_id"])),
            "storage",
            UUID(str(request.payload["storage_id"])),
            permission,
        ):
            return {"id": str(request.id), "status": "already_granted"}
    if request.type == "approval":
        await auth.require(
            Actor("user", request.recipient_user_id),
            "storage",
            UUID(str(request.payload["storage_id"])),
            "manage_access",
        )
    async with db.connection() as conn, conn.transaction():
        await gate(
            conn, cast(UUID, agent["leta_id"]), cast(UUID | None, agent["box_id"])
        )
        old = await (
            await conn.execute("SELECT * FROM hitl_requests WHERE id=%s", (request.id,))
        ).fetchone()
        if old is not None:
            for key, value in request.model_dump().items():
                if old[key] != value:
                    raise ValueError("request ID was already used with different input")
            return json_row(old)
        row = await (
            await conn.execute(
                """INSERT INTO hitl_requests(id,requester_agent_id,recipient_user_id,type,title,payload,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (
                    request.id,
                    request.requester_agent_id,
                    request.recipient_user_id,
                    request.type,
                    request.title,
                    Jsonb(request.payload),
                    request.expires_at,
                ),
            )
        ).fetchone()
    assert row is not None
    return json_row(row)


def validate_answers(payload: dict[str, JSON], response: dict[str, JSON]) -> None:
    questions = cast(list[dict[str, JSON]], payload["questions"])
    answers = cast(dict[str, dict[str, JSON]], response.get("answers", {}))
    if set(answers) != {str(question["id"]) for question in questions}:
        raise ValueError(
            "answer every question using its ID; empty answers are allowed"
        )
    for question in questions:
        answer = answers[str(question["id"])]
        kind = question["type"]
        if kind == "text":
            if set(answer) != {"text"} or not isinstance(answer["text"], str):
                raise ValueError("text answer required")
        else:
            options = {
                str(option["id"])
                for option in cast(list[dict[str, JSON]], question["options"])
            }
            if kind == "single_choice":
                value = answer.get("option_id")
                if value is not None and value not in options:
                    raise ValueError("unknown option")
                if not set(answer) <= {"option_id", "note"}:
                    raise ValueError("invalid choice answer")
            else:
                values = answer.get("option_ids")
                if (
                    not isinstance(values, list)
                    or any(value not in options for value in values)
                    or len(set(cast(list[str], values))) != len(values)
                ):
                    raise ValueError("invalid multiple choice answer")
                if not set(answer) <= {"option_ids", "note"}:
                    raise ValueError("invalid choice answer")
            if "note" in answer and not isinstance(answer["note"], str):
                raise ValueError("note must be text")


async def resolve(db: Pool, auth: Authorization, decision: Decision) -> dict[str, JSON]:
    saved = await get(db, decision.request_id)
    agent = await get_agent(db, UUID(str(saved["requester_agent_id"])))
    if decision.status in ("answered", "accepted", "denied"):
        if (
            decision.actor.kind != "user"
            or str(decision.actor.id) != saved["recipient_user_id"]
        ):
            raise PermissionError("only the addressed person may answer")
        await auth.require(
            decision.actor,
            "workspace",
            cast(UUID, agent["workspace_id"]),
            "participate",
        )
        if saved["type"] == "approval":
            if decision.status == "answered":
                raise ValueError("approval requires accept or deny")
            payload = cast(dict[str, JSON], saved["payload"])
            await auth.require(
                decision.actor,
                "storage",
                UUID(str(payload["storage_id"])),
                "manage_access",
            )
        else:
            if decision.status != "answered":
                raise ValueError("ask requires answers")
            validate_answers(
                cast(dict[str, JSON], saved["payload"]), decision.response or {}
            )
    elif decision.status == "cancelled":
        if decision.actor.kind == "user":
            await auth.require(
                decision.actor, "agent", cast(UUID, agent["leta_id"]), "manage"
            )
        elif decision.actor.id not in (agent["id"], agent["leta_id"]):
            raise PermissionError("request belongs to a different agent")
    response = (
        {**(decision.response or {}), "actor": str(decision.actor)}
        if decision.status != "expired"
        else None
    )
    async with db.connection() as conn, conn.transaction():
        old = await (
            await conn.execute(
                "SELECT * FROM hitl_requests WHERE id=%s FOR UPDATE",
                (decision.request_id,),
            )
        ).fetchone()
        assert old is not None
        if old["status"] != "pending":
            if old["status"] != decision.status or old["response"] != response:
                raise ValueError("request already resolved")
            return json_row(old)
        row = await (
            await conn.execute(
                """UPDATE hitl_requests SET status=%s,response=%s,resolved_at=%s
            WHERE id=%s RETURNING *""",
                (
                    decision.status,
                    Jsonb(response),
                    decision.resolved_at,
                    decision.request_id,
                ),
            )
        ).fetchone()
    assert row is not None
    return json_row(row)


async def apply(
    db: Pool, auth: Authorization, stub: LetFSServiceStub, id: UUID
) -> dict[str, JSON]:
    request = await get(db, id)
    agent = await get_agent(db, UUID(str(request["requester_agent_id"])))
    root = cast(UUID, agent["leta_id"])
    async with effect(db, root):
        request = await get(db, id)
        if request["outcome"] is not None:
            return cast(dict[str, JSON], request["outcome"])
        if request["type"] != "approval" or request["status"] != "accepted":
            raise ValueError("approval has not been accepted")
        payload = cast(dict[str, JSON], request["payload"])
        storage = UUID(str(payload["storage_id"]))
        user = Actor("user", UUID(str(request["recipient_user_id"])))
        agent = await get_agent(db, UUID(str(request["requester_agent_id"])))
        reason = None
        if agent["state"] != "active" or (
            agent["box_id"] and agent["box_state"] != "active"
        ):
            reason = "requester_inactive"
        elif not await auth.allowed(user, "storage", storage, "manage_access"):
            reason = "permission_revoked"
        if reason:
            outcome: dict[str, JSON] = {"status": "skipped", "reason": reason}
        else:
            permission = "write" if payload["role"] == "editor" else "read"
            if not await auth.allowed(
                Actor("agent", root), "storage", storage, permission
            ):
                try:
                    await stub.SetStorageAccess(
                        fs.SetStorageAccessRequest(
                            workspace_id=str(agent["workspace_id"]),
                            storage_id=str(storage),
                            actor=fs.ActorRef(agent_id=str(root)),
                            role=fs.STORAGE_ROLE_EDITOR
                            if permission == "write"
                            else fs.STORAGE_ROLE_VIEWER,
                        ),
                        metadata=user.metadata,
                        timeout=30,
                    )
                except grpc.aio.AioRpcError as error:
                    if error.code() not in (
                        grpc.StatusCode.NOT_FOUND,
                        grpc.StatusCode.PERMISSION_DENIED,
                    ):
                        raise
                    reason = "storage_unavailable"
            outcome = (
                {"status": "skipped", "reason": reason}
                if reason
                else {"status": "granted"}
            )
        async with db.connection() as conn:
            await conn.execute(
                "UPDATE hitl_requests SET outcome=%s WHERE id=%s", (Jsonb(outcome), id)
            )
        return outcome
