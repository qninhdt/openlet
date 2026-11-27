"""HITL request validation, persistence, workflow control, and side-effect application."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import grpc
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_sdk.config import JSON
from openlet_sdk.types import is_object_list, is_str_mapping
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator
from temporalio.service import RPCError, RPCStatusCode

from leta.activity import ActivityEmitter, leta_user_channel
from leta.auth import Actor, Authorization
from leta.db import Pool, hydrate
from leta.hitl.models import (
    ApprovalPayload,
    ApprovalResponse,
    AskOption,
    AskPayload,
    AskQuestionForm,
    AskResponse,
    HitlOutcome,
)
from leta.inbox import InboxGateway, InboxItem, InboxMetadata, InboxSender

if TYPE_CHECKING:
    from openlet_api.letfs.v1.letfs_pb2_grpc import LetFSServiceAsyncStub
    from temporalio.client import Client as TemporalClient

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
    """Base strict input model for HITL service operations."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HitlRecord(BaseModel):
    """Hydrated HITL request row persisted in PostgreSQL."""

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
    """Paginated HITL items and pending count for a recipient user."""

    items: list[HitlRecord]
    pending_count: int


class Question(HitlInput):
    """Authoring schema for a single question in an ask_user tool call."""

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
        """Normalize an empty options list to None so free-text questions validate cleanly."""
        if is_str_mapping(data):
            d = dict(data)
            if d.get("options") == []:
                d["options"] = None
            return d
        return data

    @model_validator(mode="after")
    def validate_choices(self) -> Question:
        """Ensure multiple selection has options and all option labels are unique and non-empty."""
        if self.multiple and self.options is None:
            raise ValueError("multiple selection requires options")
        if self.options is not None and (
            len(set(self.options)) != len(self.options)
            or any(not label for label in self.options)
        ):
            raise ValueError("options must be unique non-empty labels")
        return self


class OpenHitlInput(HitlInput):
    """Validated workflow input used to open an HITL request."""

    id: UUID
    requester_agent_id: UUID
    recipient_user_id: UUID
    type: HitlType
    title: str = Field(min_length=1, max_length=255)
    payload: AskPayload | ApprovalPayload
    expires_at: datetime | None = None


class HitlDecisionInput(HitlInput):
    """Validated decision payload submitted by a recipient or cancellation."""

    request_id: UUID
    actor_type: Literal["user", "agent"] = "user"
    actor_id: UUID
    status: Literal["answered", "accepted", "denied", "cancelled", "expired"]
    response: dict[str, JSON] | None = None
    resolved_at: datetime | None = None


def build_ask_form(questions: list[Question]) -> AskPayload:
    """Compile authored Question inputs into an AskPayload with stable IDs."""
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


def _validate_question_answer(q: AskQuestionForm, ans: object) -> str | list[str]:
    if q.type == "text":
        if not isinstance(ans, str) or not ans.strip():
            raise ValueError(f"question {q.id} requires a non-empty text answer")
        return ans.strip()
    valid_opts = {o.id for o in q.options}
    if q.type == "single_choice":
        if not isinstance(ans, str) or ans not in valid_opts:
            raise ValueError(f"question {q.id} requires one valid option id")
        return ans
    if not is_object_list(ans) or not ans:
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
    return chosen


def validate_ask_response(
    payload: AskPayload | dict[str, JSON], response: dict[str, JSON] | None
) -> AskResponse:
    """Validate an ask response payload against the expected form questions."""
    if not is_str_mapping(response):
        raise ValueError("response is required for ask requests")
    raw_answers = response.get("answers")
    if not is_str_mapping(raw_answers):
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
        cleaned[q.id] = _validate_question_answer(q, raw_answers[q.id])

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
    """Persist a new pending HITL request (or detect already-granted approval access)."""
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

    payload_model: AskPayload | ApprovalPayload = request.payload
    already_granted = False
    if request.type == "approval":
        if not isinstance(payload_model, ApprovalPayload):
            raise ValueError("approval request requires ApprovalPayload")
        role = payload_model.role
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
        payload_model = payload_model.model_copy(update={"storage_id": storage_id})
        perm = "write" if role == "editor" else "read"
        if await auth.allowed(Actor("agent", leta_id), "storage", storage_id, perm):
            already_granted = True
    elif not isinstance(payload_model, AskPayload):
        raise ValueError("ask request requires AskPayload")

    if already_granted:
        return HitlRecord(
            id=request.id,
            leta_id=leta_id,
            status="already_granted",
            payload=payload_model,
        )

    payload_json = payload_model.model_dump(mode="json")

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
                    Jsonb(payload_json),
                    request.expires_at,
                ),
            )
        ).fetchone()
    if row is None:
        raise RuntimeError(f"HITL insert returned no row for {request.id}")
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
    """Validate and record a decision on a pending HITL request."""
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
            if decision.response is not None:
                parsed_approval = ApprovalResponse.model_validate(decision.response)
                note = (parsed_approval.note or "").strip()
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
    if updated is None:
        raise RuntimeError(f"HITL update returned no row for {decision.request_id}")
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
    """Apply the storage access grant for an accepted approval HITL request."""
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
    if recipient_id is None:
        raise RuntimeError(f"HITL request {request_id} is missing recipient_user_id")
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
    if updated is None:
        raise RuntimeError(f"HITL outcome update returned no row for {request_id}")
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
    """Start the Temporal HitlWorkflow for a newly requested HITL interaction."""
    from leta.hitl.workflow import HitlWorkflow  # noqa: PLC0415  # Avoids circular import with hitl.workflow

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
    """Signal a running HitlWorkflow to cancel, returning False if already closed."""
    try:
        await temporal.get_workflow_handle(f"hitl/{request_id}").signal(
            "cancel", actor_id
        )
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            return False
        raise
    else:
        return True


async def deliver_hitl_result(
    *, db: Pool, inbox: InboxGateway, request_id: UUID
) -> None:
    """Deliver the resolved HITL request outcome to the requesting agent's inbox."""
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
            metadata=InboxMetadata(
                request_id=str(request_id),
                title=record.title,
                type=record.type or "",
                status=record.status,
                payload=record.payload,
                outcome=record.outcome,
                response=record.response,
            ),
        )
    )


async def get_hitl(db: Pool, request_id: UUID) -> HitlRecord:
    """Fetch a single HITL request record by ID."""
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
    """List HITL requests addressed to recipient_user_id along with pending count."""
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
    """List HITL requests belonging to a Leta instance."""
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
