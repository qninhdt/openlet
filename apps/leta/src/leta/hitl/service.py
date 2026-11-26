from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

import grpc
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_sdk.config import JSON
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..activity import ActivityEmitter, leta_user_channel
from ..auth import Actor, Authorization
from ..db import Pool, json_row
from ..inbox import InboxGateway, InboxItem, InboxSender

if TYPE_CHECKING:
    from openlet_api.letfs.v1.letfs_pb2_grpc import LetFSServiceAsyncStub


class HitlInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


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
        if isinstance(data, dict):
            d = dict(cast(dict[str, object], data))
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
    type: Literal["ask", "approval"]
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


def build_ask_form(questions: list[Question]) -> dict[str, JSON]:
    items: list[JSON] = []
    for idx, q in enumerate(questions):
        item: dict[str, JSON] = {
            "id": f"q{idx + 1}",
            "text": q.text,
            "type": (
                "multiple_choice"
                if q.multiple
                else "single_choice"
                if q.options
                else "text"
            ),
        }
        if q.options:
            item["options"] = [
                {"id": f"o{i + 1}", "label": label} for i, label in enumerate(q.options)
            ]
        items.append(item)
    return {"questions": items}


def validate_ask_response(
    payload: dict[str, JSON], response: dict[str, JSON] | None
) -> dict[str, JSON]:
    if not isinstance(response, dict):
        raise ValueError("response is required for ask requests")
    raw_answers = response.get("answers")
    if not isinstance(raw_answers, dict):
        raise ValueError("response.answers object is required")
    questions = cast(list[dict[str, JSON]], payload.get("questions", []))
    expected_ids = {str(q["id"]) for q in questions}
    unknown = set(raw_answers) - expected_ids
    if unknown:
        raise ValueError(f"unknown question ids: {', '.join(sorted(unknown))}")

    cleaned: dict[str, JSON] = {}
    for q in questions:
        qid = str(q["id"])
        qtype = str(q["type"])
        if qid not in raw_answers:
            raise ValueError(f"missing answer for question {qid}")
        ans = raw_answers[qid]
        if qtype == "text":
            if not isinstance(ans, str) or not ans.strip():
                raise ValueError(f"question {qid} requires a non-empty text answer")
            cleaned[qid] = ans.strip()
        elif qtype == "single_choice":
            valid_opts = {
                str(cast(dict[str, JSON], o)["id"])
                for o in cast(list[JSON], q.get("options", []))
            }
            if not isinstance(ans, str) or ans not in valid_opts:
                raise ValueError(f"question {qid} requires one valid option id")
            cleaned[qid] = ans
        elif qtype == "multiple_choice":
            valid_opts = {
                str(cast(dict[str, JSON], o)["id"])
                for o in cast(list[JSON], q.get("options", []))
            }
            if (
                not isinstance(ans, list)
                or not ans
                or any(not isinstance(v, str) or v not in valid_opts for v in ans)
                or len(set(cast(list[str], ans))) != len(ans)
            ):
                raise ValueError(
                    f"question {qid} requires a non-empty list of unique valid option ids"
                )
            cleaned[qid] = list(ans)
    out: dict[str, JSON] = {"answers": cleaned}
    if "note" in response and response["note"] is not None:
        if not isinstance(response["note"], str):
            raise ValueError("note must be a string")
        note = response["note"].strip()
        if note:
            out["note"] = note[:4000]
    return out


async def open_hitl(
    *,
    db: Pool,
    auth: Authorization,
    letfs: LetFSServiceAsyncStub,
    activity: ActivityEmitter | None,
    request: OpenHitlInput,
) -> dict[str, JSON]:
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
            for st in page.storages:
                access = await letfs.ListStorageAccess(
                    fs.StorageRequest(workspace_id=str(workspace_id), storage_id=st.id),
                    metadata=recipient_meta,
                    timeout=15,
                )
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
        return {
            "id": str(request.id),
            "leta_id": str(leta_id),
            "status": "already_granted",
            "payload": payload,
        }

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
    serialized = json_row(row)
    if activity is not None:
        await activity.emit(
            leta_id=leta_id,
            agent_id=request.requester_agent_id,
            event_type="hitl.updated",
            data={"hitl": serialized},
            extra_channels=[leta_user_channel(request.recipient_user_id)],
        )
    return serialized


async def resolve_hitl(
    *,
    db: Pool,
    activity: ActivityEmitter | None,
    decision: HitlDecisionInput,
) -> dict[str, JSON]:
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
        if row["status"] != "pending":
            raise ValueError(f"hitl request already {row['status']}")

        req_type = str(row["type"])
        clean_response: dict[str, JSON] | None = decision.response
        if decision.status == "answered":
            if req_type != "ask":
                raise ValueError("answered status is only valid for ask requests")
            clean_response = validate_ask_response(
                cast(dict[str, JSON], row["payload"]), decision.response
            )
        elif decision.status in ("accepted", "denied"):
            if req_type != "approval":
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
    serialized = json_row(updated)
    if activity is not None:
        await activity.emit(
            leta_id=UUID(str(updated["leta_id"])),
            agent_id=UUID(str(updated["requester_agent_id"])),
            event_type="hitl.updated",
            data={"hitl": serialized},
            extra_channels=[leta_user_channel(str(updated["recipient_user_id"]))],
        )
    return serialized


async def apply_hitl_effect(
    *,
    db: Pool,
    auth: Authorization,
    letfs: LetFSServiceAsyncStub,
    activity: ActivityEmitter | None,
    request_id: UUID,
) -> dict[str, JSON]:
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
    if row["type"] != "approval" or row["status"] != "accepted":
        return json_row(row)
    if row["outcome"] is not None:
        return json_row(row)

    payload = cast(dict[str, JSON], row["payload"])
    storage_id = str(payload["storage_id"])
    role_str = str(payload.get("role", "viewer"))
    role_enum = (
        fs.STORAGE_ROLE_EDITOR if role_str == "editor" else fs.STORAGE_ROLE_VIEWER
    )
    workspace_id = str(row["workspace_id"])
    recipient_id = UUID(str(row["recipient_user_id"]))
    leta_id = UUID(str(row["leta_id"]))

    outcome: dict[str, JSON]
    if row["leta_state"] != "active":
        outcome = {"applied": False, "reason": "leta_inactive"}
    elif not await auth.allowed(
        Actor("user", recipient_id), "workspace", workspace_id, "participate"
    ):
        outcome = {"applied": False, "reason": "recipient_no_longer_in_workspace"}
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
            outcome = {
                "applied": True,
                "storage_id": storage_id,
                "role": role_str,
            }
        except grpc.aio.AioRpcError as exc:
            outcome = {"applied": False, "reason": exc.details() or str(exc.code())}

    async with db.connection() as conn:
        updated = await (
            await conn.execute(
                "UPDATE hitl_requests SET outcome = %s WHERE id = %s RETURNING *",
                (Jsonb(outcome), request_id),
            )
        ).fetchone()
    assert updated is not None
    serialized = json_row(updated)
    if activity is not None:
        await activity.emit(
            leta_id=leta_id,
            agent_id=UUID(str(updated["requester_agent_id"])),
            event_type="hitl.updated",
            data={"hitl": serialized},
            extra_channels=[leta_user_channel(recipient_id)],
        )
    return serialized


def format_hitl_response(payload: object, response: object) -> str:
    """Render a HITL response as clean human-readable UTF-8 text (no Python dict repr)."""
    if response is None:
        return ""
    if not isinstance(response, Mapping):
        return str(response)
    resp = cast(Mapping[str, object], response)
    lines: list[str] = []

    raw_answers = resp.get("answers")
    if isinstance(raw_answers, Mapping):
        answers = cast(Mapping[str, object], raw_answers)
        q_meta: dict[str, tuple[str, dict[str, str]]] = {}
        if isinstance(payload, Mapping):
            raw_qs = cast(Mapping[str, object], payload).get("questions")
            if isinstance(raw_qs, list):
                for q in cast(list[object], raw_qs):
                    if not isinstance(q, Mapping):
                        continue
                    qd = cast(Mapping[str, object], q)
                    qid = str(qd.get("id") or "")
                    qtext = str(qd.get("text") or "")
                    opts: dict[str, str] = {}
                    raw_opts = qd.get("options")
                    if isinstance(raw_opts, list):
                        for o in cast(list[object], raw_opts):
                            if isinstance(o, Mapping):
                                od = cast(Mapping[str, object], o)
                                oid = str(od.get("id") or "")
                                lbl = str(od.get("label") or "")
                                if oid and lbl:
                                    opts[oid] = lbl
                    if qid:
                        q_meta[qid] = (qtext, opts)

        if answers:
            lines.append("Answers:")
            for qid, raw_val in answers.items():
                q_key = str(qid)
                qtext, opt_labels = q_meta.get(q_key, ("", {}))
                label = f"{q_key} ({qtext})" if qtext else q_key
                if isinstance(raw_val, list):
                    val_text = ", ".join(
                        opt_labels.get(str(v), str(v))
                        for v in cast(list[object], raw_val)
                    )
                else:
                    s_val = str(raw_val)
                    val_text = opt_labels.get(s_val, s_val)
                if "\n" in val_text:
                    indented = "\n".join(f"  {ln}" for ln in val_text.splitlines())
                    lines.append(f"- {label}:\n{indented}")
                else:
                    lines.append(f"- {label}: {val_text}")

    raw_note = resp.get("note")
    if isinstance(raw_note, str) and raw_note.strip():
        note = raw_note.strip()
        if "\n" in note:
            lines.append(f"Note:\n{note}")
        else:
            lines.append(f"Note: {note}")

    if not lines:
        return json.dumps(dict(resp), ensure_ascii=False, default=str)
    return "\n".join(lines)


def format_hitl_outcome_attr(outcome: object) -> str:
    """Short single-line outcome status suitable for XML attributes and UI summaries."""
    if outcome is None:
        return ""
    if isinstance(outcome, str):
        return outcome
    if isinstance(outcome, Mapping):
        om = cast(Mapping[str, object], outcome)
        applied = om.get("applied")
        if applied is True:
            role = str(om.get("role") or "").strip()
            return f"applied ({role})" if role else "applied"
        if applied is False:
            reason = str(om.get("reason") or "failed").strip()
            return f"not_applied: {reason}"
        return json.dumps(dict(om), ensure_ascii=False, default=str)
    return str(outcome)


def format_hitl_outcome(outcome: object) -> str:
    """Human-readable outcome summary for agent text outputs."""
    if outcome is None:
        return ""
    if isinstance(outcome, str):
        return outcome
    if isinstance(outcome, Mapping):
        om = cast(Mapping[str, object], outcome)
        applied = om.get("applied")
        if applied is True:
            details: list[str] = []
            if om.get("role"):
                details.append(f"role={om['role']}")
            if om.get("storage_id"):
                details.append(f"storage_id={om['storage_id']}")
            suffix = f" ({', '.join(details)})" if details else ""
            return f"Access granted{suffix}."
        if applied is False:
            reason = str(om.get("reason") or "unknown reason")
            return f"Not applied: {reason}."
        return json.dumps(dict(om), ensure_ascii=False, default=str)
    return str(outcome)


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
    requester_id = UUID(str(row["requester_agent_id"]))
    status = str(row["status"])
    title = str(row["title"])
    parts = [f"HITL request '{title}' ({request_id}) resolved with status: {status}."]
    resp_text = format_hitl_response(row["payload"], row["response"])
    if resp_text:
        parts.append(resp_text)
    outcome_text = format_hitl_outcome(row["outcome"])
    if outcome_text:
        parts.append(f"Outcome: {outcome_text}")
    outcome_attr = format_hitl_outcome_attr(row["outcome"])
    await inbox.deliver(
        InboxItem(
            agent_id=requester_id,
            idempotency_key=f"hitl:{request_id}:result",
            kind="hitl",
            channel="hitl",
            reply_address=None,
            sender=InboxSender(
                type="user",
                id=str(row["recipient_user_id"]),
            ),
            content="\n".join(parts),
            metadata={
                "request_id": str(request_id),
                "title": title,
                "type": str(row["type"]),
                "status": status,
                "outcome": outcome_attr,
                "outcome_detail": cast(JSON, row["outcome"]),
                "response": cast(JSON, row["response"]),
            },
        )
    )


async def get_hitl(db: Pool, request_id: UUID) -> dict[str, JSON]:
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
    return json_row(row)


async def list_recipient_hitl(
    db: Pool,
    recipient_user_id: UUID,
    *,
    workspace_id: UUID | None = None,
    leta_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, JSON]:
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
    return {
        "items": [json_row(r) for r in rows],
        "pending_count": int(cnt_row["cnt"]) if cnt_row is not None else 0,
    }


async def list_leta_hitl(
    db: Pool,
    leta_id: UUID,
    *,
    requester_agent_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, JSON]]:
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
    return [json_row(r) for r in rows]
