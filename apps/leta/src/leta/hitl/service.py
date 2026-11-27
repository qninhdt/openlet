from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import grpc
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_sdk.config import JSON
from openlet_sdk.types import is_str_mapping
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator
from temporalio.client import Client as TemporalClient
from temporalio.service import RPCError, RPCStatusCode

from ..activity import ActivityEmitter, leta_user_channel
from ..auth import Actor, Authorization
from ..db import Pool, hydrate
from ..inbox import InboxGateway, InboxItem, InboxSender
from .models import (
    ApprovalPayload as ApprovalPayload,
)
from .models import (
    ApprovalResponse as ApprovalResponse,
)
from .models import (
    AskOption as AskOption,
)
from .models import (
    AskPayload as AskPayload,
)
from .models import (
    AskQuestionForm as AskQuestionForm,
)
from .models import (
    AskResponse as AskResponse,
)
from .models import (
    HitlOutcome as HitlOutcome,
)

if TYPE_CHECKING:
    from openlet_api.letfs.v1.letfs_pb2_grpc import LetFSServiceAsyncStub

type HitlType = Literal["ask", "approval"]
type HitlStatus = Literal[
    "pending", "answered", "accepted", "denied", "cancelled", "expired"
]
type HitlOpenStatus = Literal[
    "pending",
    "answered",
    "accepted",
    "denied",
    "cancelled",
    "expired",
    "already_granted",
]


class HitlInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HitlRecord(BaseModel):
    id: UUID
    leta_id: UUID
    workspace_id: UUID | None = None
    requester_agent_id: UUID | None = None
    recipient_user_id: UUID | None = None
    type: HitlType | None = None
    title: str = ""
    payload: AskPayload | ApprovalPayload | dict[str, JSON] = Field(
        default_factory=dict[str, JSON]
    )
    status: HitlOpenStatus = "pending"
    response: AskResponse | ApprovalResponse | dict[str, JSON] | None = None
    outcome: HitlOutcome | None = None
    expires_at: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime | None = None


class RecipientHitlList(BaseModel):
    items: list[HitlRecord]
    pending_count: int


class Question(HitlInput):
    text: str = Field(min_length=1, max_length=4000)
    options: list[str] | None = Field(
        default=None,
        min_length=2,
        max_length=20,
        description="Distinct choice labels (omit for free-text; put recommended first with '(Recommended)').",
    )
    multiple: bool = Field(
        default=False,
        description="Allow multiple selections (requires options).",
    )

    @model_validator(mode="before")
    @classmethod
    def coerce_empty_options(cls, data: object) -> object:
        if is_str_mapping(data):
            d = dict(data)
            if d.get("options") == []:
                d["options"] = None
            return d
        return data

    @model_validator(mode="after")
    def validate_choices(self) -> Question:
        if self.multiple and self.options is None:
            raise ValueError("multiple selection requires options")
        if self.options is not None and (
            len(set(self.options)) != len(self.options)
            or any(not label for label in self.options)
        ):
            raise ValueError("options must be unique non-empty labels")
        return self


class OpenHitlInput(HitlInput):
    id: UUID
    requester_agent_id: UUID
    recipient_user_id: UUID
    type: HitlType
    title: str = Field(min_length=1, max_length=255)
    payload: dict[str, JSON]
    expires_at: datetime | None = None


class HitlDecisionInput(HitlInput):
    request_id: UUID
    actor_type: Literal["user", "agent"] = "user"
    actor_id: UUID
    status: Literal["answered", "accepted", "denied", "cancelled", "expired"]
    response: dict[str, JSON] | None = None
    resolved_at: datetime | None = None


def build_ask_form(questions: list[Question]) -> AskPayload:
    items: list[AskQuestionForm] = []
    for idx, q in enumerate(questions):
        qtype: Literal["text", "single_choice", "multiple_choice"] = (
            "multiple_choice"
            if q.multiple
            else "single_choice"
            if q.options
            else "text"
        )
        opts = (
            [
                AskOption(id=f"o{i + 1}", label=label)
                for i, label in enumerate(q.options)
            ]
            if q.options
            else []
        )
        items.append(
            AskQuestionForm(id=f"q{idx + 1}", text=q.text, type=qtype, options=opts)
        )
    return AskPayload(questions=items)


def validate_ask_response(
    payload: AskPayload | dict[str, JSON], response: dict[str, JSON] | None
) -> AskResponse:
    if not isinstance(response, dict):
        raise ValueError("response is required for ask requests")
    raw_answers = response.get("answers")
    if not isinstance(raw_answers, dict):
        raise ValueError("response.answers object is required")
    form = (
        payload
        if isinstance(payload, AskPayload)
        else AskPayload.model_validate(payload)
    )
    expected_ids = {q.id for q in form.questions}
    unknown = set(raw_answers) - expected_ids
    if unknown:
        raise ValueError(f"unknown question ids: {', '.join(sorted(unknown))}")

    cleaned: dict[str, str | list[str]] = {}
    for q in form.questions:
        if q.id not in raw_answers:
            raise ValueError(f"missing answer for question {q.id}")
        ans = raw_answers[q.id]
        if q.type == "text":
            if not isinstance(ans, str) or not ans.strip():
                raise ValueError(f"question {q.id} requires a non-empty text answer")
            cleaned[q.id] = ans.strip()
        elif q.type == "single_choice":
            valid_opts = {o.id for o in q.options}
            if not isinstance(ans, str) or ans not in valid_opts:
                raise ValueError(f"question {q.id} requires one valid option id")
            cleaned[q.id] = ans
        else:
            valid_opts = {o.id for o in q.options}
            if not isinstance(ans, list) or not ans:
                raise ValueError(
                    f"question {q.id} requires a non-empty list of unique valid option ids"
                )
            chosen: list[str] = []
            for v in ans:
                if not isinstance(v, str) or v not in valid_opts:
                    raise ValueError(
                        f"question {q.id} requires a non-empty list of unique valid option ids"
                    )
                chosen.append(v)
            if len(set(chosen)) != len(chosen):
                raise ValueError(
                    f"question {q.id} requires a non-empty list of unique valid option ids"
                )
            cleaned[q.id] = chosen

    clean_note: str | None = None
    if "note" in response and response["note"] is not None:
        if not isinstance(response["note"], str):
            raise ValueError("note must be a string")
        note = response["note"].strip()
        if note:
            clean_note = note[:4000]
    return AskResponse(answers=cleaned, note=clean_note)


async def open_hitl(
    *,
    db: Pool,
    auth: Authorization,
    letfs: LetFSServiceAsyncStub,
    activity: ActivityEmitter | None,
    request: OpenHitlInput,
) -> HitlRecord:
    async with db.connection() as conn:
        agent = await (
            await conn.execute(
                """
                SELECT a.id, a.leta_id, a.state, l.workspace_id, l.state AS leta_state
                FROM agents a JOIN letas l ON l.id = a.leta_id
                WHERE a.id = %s
                """,
                (request.requester_agent_id,),
            )
        ).fetchone()
    if agent is None or agent["state"] != "active" or agent["leta_state"] != "active":
        raise LookupError("requester agent is not active")
    workspace_id = UUID(str(agent["workspace_id"]))
    leta_id = UUID(str(agent["leta_id"]))

    await auth.require(
        Actor("user", request.recipient_user_id),
        "workspace",
        workspace_id,
        "participate",
    )

    payload = dict(request.payload)
    already_granted = False
    if request.type == "approval":
        role = str(payload.get("role", "viewer"))
        if role not in ("viewer", "editor"):
            raise ValueError("approval role must be 'viewer' or 'editor'")
        query = fs.ListStoragesRequest(
            workspace_id=str(workspace_id),
            visibility=fs.STORAGE_VISIBILITY_PRIVATE,
            owned_only=True,
            page_size=100,
        )
        personal_storages: list[fs.Storage] = []
        recipient_meta = Actor("user", request.recipient_user_id).metadata
        while True:
            page = await letfs.ListStorages(query, metadata=recipient_meta, timeout=15)
            accesses = await asyncio.gather(
                *(
                    letfs.ListStorageAccess(
                        fs.StorageRequest(
                            workspace_id=str(workspace_id), storage_id=st.id
                        ),
                        metadata=recipient_meta,
                        timeout=15,
                    )
                    for st in page.storages
                )
            )
            for st, access in zip(page.storages, accesses, strict=True):
                if access.ownership.user_id == str(request.recipient_user_id):
                    personal_storages.append(st)
            if not page.next_page_token:
                break
            query.page_token = page.next_page_token
        if len(personal_storages) != 1:
            raise ValueError(
                "recipient must have exactly one Personal storage in this workspace"
            )
        storage_id = personal_storages[0].id
        payload["storage_id"] = storage_id
        perm = "write" if role == "editor" else "read"
        if await auth.allowed(Actor("agent", leta_id), "storage", storage_id, perm):
            already_granted = True

    if already_granted:
        return HitlRecord(
            id=request.id,
            leta_id=leta_id,
            status="already_granted",
            payload=payload,
        )

    async with db.connection() as conn, conn.transaction():
        row = await (
            await conn.execute(
                """
                INSERT INTO hitl_requests(
                    id, leta_id, requester_agent_id, recipient_user_id,
                    type, title, payload, status, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s)
                ON CONFLICT (id) DO UPDATE SET id = hitl_requests.id
                RETURNING *
                """,
                (
                    request.id,
                    leta_id,
                    request.requester_agent_id,
                    request.recipient_user_id,
                    request.type,
                    request.title,
                    Jsonb(payload),
                    request.expires_at,
                ),
            )
        ).fetchone()
    assert row is not None
    record = hydrate(row, HitlRecord)
    if activity is not None:
        await activity.emit(
            leta_id=leta_id,
            agent_id=request.requester_agent_id,
            event_type="hitl.updated",
            data={"hitl": record.model_dump(mode="json")},
            extra_channels=[leta_user_channel(request.recipient_user_id)],
        )
    return record


async def resolve_hitl(
    *,
    db: Pool,
    activity: ActivityEmitter | None,
    decision: HitlDecisionInput,
) -> HitlRecord:
    now = decision.resolved_at or datetime.now(UTC)
    async with db.connection() as conn, conn.transaction():
        row = await (
            await conn.execute(
                "SELECT * FROM hitl_requests WHERE id = %s FOR UPDATE",
                (decision.request_id,),
            )
        ).fetchone()
        if row is None:
            raise LookupError("hitl request not found")
        existing = hydrate(row, HitlRecord)
        if existing.status != "pending":
            raise ValueError(f"hitl request already {existing.status}")

        clean_response: dict[str, JSON] | None = decision.response
        if decision.status == "answered":
            if existing.type != "ask":
                raise ValueError("answered status is only valid for ask requests")
            if isinstance(existing.payload, ApprovalPayload):
                raise ValueError("ask request payload must contain questions")
            validated = validate_ask_response(existing.payload, decision.response)
            clean_response = validated.model_dump(exclude_none=True)
        elif decision.status in ("accepted", "denied"):
            if existing.type != "approval":
                raise ValueError(
                    "accepted/denied status is only valid for approval requests"
                )
            if decision.response and "note" in decision.response:
                note = str(decision.response["note"]).strip()
                clean_response = {"note": note[:4000]} if note else None
            else:
                clean_response = None

        updated = await (
            await conn.execute(
                """
                UPDATE hitl_requests
                SET status = %s, response = %s, resolved_at = %s
                WHERE id = %s
                RETURNING *
                """,
                (
                    decision.status,
                    Jsonb(clean_response) if clean_response is not None else None,
                    now,
                    decision.request_id,
                ),
            )
        ).fetchone()
    assert updated is not None
    record = hydrate(updated, HitlRecord)
    if activity is not None and record.requester_agent_id is not None:
        extra = (
            [leta_user_channel(record.recipient_user_id)]
            if record.recipient_user_id is not None
            else None
        )
        await activity.emit(
            leta_id=record.leta_id,
            agent_id=record.requester_agent_id,
            event_type="hitl.updated",
            data={"hitl": record.model_dump(mode="json")},
            extra_channels=extra,
        )
    return record


async def apply_hitl_effect(
    *,
    db: Pool,
    auth: Authorization,
    letfs: LetFSServiceAsyncStub,
    activity: ActivityEmitter | None,
    request_id: UUID,
) -> HitlRecord:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                """
                SELECT h.*, l.workspace_id, l.state AS leta_state
                FROM hitl_requests h
                JOIN letas l ON l.id = h.leta_id
                WHERE h.id = %s
                """,
                (request_id,),
            )
        ).fetchone()
    if row is None:
        raise LookupError("hitl request not found")
    record = hydrate(row, HitlRecord)
    if record.type != "approval" or record.status != "accepted":
        return record
    if record.outcome is not None:
        return record

    approval = ApprovalPayload.model_validate(record.payload)
    storage_id = approval.storage_id or ""
    role_enum = (
        fs.STORAGE_ROLE_EDITOR if approval.role == "editor" else fs.STORAGE_ROLE_VIEWER
    )
    workspace_id = str(record.workspace_id or "")
    recipient_id = record.recipient_user_id
    assert recipient_id is not None
    leta_id = record.leta_id

    outcome: HitlOutcome
    if row["leta_state"] != "active":
        outcome = HitlOutcome(applied=False, reason="leta_inactive")
    elif not await auth.allowed(
        Actor("user", recipient_id), "workspace", workspace_id, "participate"
    ):
        outcome = HitlOutcome(applied=False, reason="recipient_no_longer_in_workspace")
    else:
        try:
            await letfs.SetStorageAccess(
                fs.SetStorageAccessRequest(
                    workspace_id=workspace_id,
                    storage_id=storage_id,
                    actor=fs.ActorRef(agent_id=str(leta_id)),
                    role=role_enum,
                ),
                metadata=Actor("user", recipient_id).metadata,
                timeout=15,
            )
            outcome = HitlOutcome(
                applied=True,
                storage_id=storage_id,
                role=approval.role,
            )
        except grpc.aio.AioRpcError as exc:
            outcome = HitlOutcome(
                applied=False, reason=exc.details() or str(exc.code())
            )

    async with db.connection() as conn:
        updated = await (
            await conn.execute(
                "UPDATE hitl_requests SET outcome = %s WHERE id = %s RETURNING *",
                (Jsonb(outcome.model_dump(exclude_none=True)), request_id),
            )
        ).fetchone()
    assert updated is not None
    updated_record = hydrate(updated, HitlRecord)
    if activity is not None and updated_record.requester_agent_id is not None:
        await activity.emit(
            leta_id=leta_id,
            agent_id=updated_record.requester_agent_id,
            event_type="hitl.updated",
            data={"hitl": updated_record.model_dump(mode="json")},
            extra_channels=[leta_user_channel(recipient_id)],
        )
    return updated_record


async def start_hitl_workflow(
    *,
    temporal: TemporalClient,
    orchestration_queue: str,
    request: OpenHitlInput,
) -> None:
    from .workflow import HitlWorkflow

    await temporal.start_workflow(
        HitlWorkflow.run,
        request,
        id=f"hitl/{request.id}",
        task_queue=orchestration_queue,
    )


async def cancel_hitl_workflow(
    *,
    temporal: TemporalClient,
    request_id: UUID,
    actor_id: UUID,
) -> bool:
    try:
        await temporal.get_workflow_handle(f"hitl/{request_id}").signal(
            "cancel", actor_id
        )
        return True
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            return False
        raise


def _to_json_dict(
    value: BaseModel | dict[str, JSON] | None,
) -> dict[str, JSON] | None:
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    return value


async def deliver_hitl_result(
    *, db: Pool, inbox: InboxGateway, request_id: UUID
) -> None:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT * FROM hitl_requests WHERE id = %s", (request_id,)
            )
        ).fetchone()
    if row is None:
        return
    record = hydrate(row, HitlRecord)
    if record.requester_agent_id is None:
        return
    await inbox.deliver(
        InboxItem(
            agent_id=record.requester_agent_id,
            idempotency_key=f"hitl:{request_id}:result",
            kind="hitl",
            channel="hitl",
            reply_address=None,
            sender=InboxSender(
                type="user",
                id=str(record.recipient_user_id or ""),
            ),
            content="",
            metadata={
                "request_id": str(request_id),
                "title": record.title,
                "type": record.type or "",
                "status": record.status,
                "payload": _to_json_dict(record.payload),
                "outcome": _to_json_dict(record.outcome),
                "response": _to_json_dict(record.response),
            },
        )
    )


async def get_hitl(db: Pool, request_id: UUID) -> HitlRecord:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                """
                SELECT h.*, l.workspace_id
                FROM hitl_requests h
                JOIN letas l ON l.id = h.leta_id
                WHERE h.id = %s
                """,
                (request_id,),
            )
        ).fetchone()
    if row is None:
        raise LookupError("hitl request not found")
    return hydrate(row, HitlRecord)


async def list_recipient_hitl(
    db: Pool,
    recipient_user_id: UUID,
    *,
    workspace_id: UUID | None = None,
    leta_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
) -> RecipientHitlList:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT h.*, l.workspace_id
                FROM hitl_requests h
                JOIN letas l ON l.id = h.leta_id
                WHERE h.recipient_user_id = %s
                  AND (%s::uuid IS NULL OR l.workspace_id = %s)
                  AND (%s::uuid IS NULL OR h.leta_id = %s)
                  AND (%s::text IS NULL OR h.status = %s)
                ORDER BY h.created_at DESC
                LIMIT %s
                """,
                (
                    recipient_user_id,
                    workspace_id,
                    workspace_id,
                    leta_id,
                    leta_id,
                    status,
                    status,
                    max(1, min(limit, 100)),
                ),
            )
        ).fetchall()
        cnt_row = await (
            await conn.execute(
                """
                SELECT count(*) AS cnt
                FROM hitl_requests h
                JOIN letas l ON l.id = h.leta_id
                WHERE h.recipient_user_id = %s
                  AND h.status = 'pending'
                  AND (%s::uuid IS NULL OR l.workspace_id = %s)
                """,
                (recipient_user_id, workspace_id, workspace_id),
            )
        ).fetchone()
    return RecipientHitlList(
        items=[hydrate(r, HitlRecord) for r in rows],
        pending_count=int(cnt_row["cnt"]) if cnt_row is not None else 0,
    )


async def list_leta_hitl(
    db: Pool,
    leta_id: UUID,
    *,
    requester_agent_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[HitlRecord]:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT h.*, l.workspace_id
                FROM hitl_requests h
                JOIN letas l ON l.id = h.leta_id
                WHERE h.leta_id = %s
                  AND (%s::uuid IS NULL OR h.requester_agent_id = %s)
                  AND (%s::text IS NULL OR h.status = %s)
                ORDER BY h.created_at DESC
                LIMIT %s
                """,
                (
                    leta_id,
                    requester_agent_id,
                    requester_agent_id,
                    status,
                    status,
                    max(1, min(limit, 100)),
                ),
            )
        ).fetchall()
    return [hydrate(r, HitlRecord) for r in rows]
