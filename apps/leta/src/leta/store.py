"""Leta-owned SQL; remote authorization and effects stay outside transactions."""

import json
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid7

from openlet.errors import AppError
from psycopg import AsyncCursor, sql
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from leta.config import ModelCatalog, ModelSelection
from leta.domain import (
    AgentConfiguration,
    HumanStatus,
    Lifecycle,
    NewActivity,
    NewBox,
    NewHumanRequest,
    NewLeta,
    NewMessage,
    NewSchedule,
    RunStatus,
    SchedulePatch,
    TimeCursor,
    box_slug,
)
from leta.human import (
    AskForm,
    PersonalScopeResource,
    RequestResolution,
    normalize_answers,
)

Row = dict[str, Any]
Cursor = AsyncCursor[Row]


def fault(reason: str, detail: str, kind: str = "conflict") -> AppError:
    return AppError(detail, reason=reason, kind=kind, retryable=False)


async def one(cursor: Cursor, query, parameters=()) -> Row:
    row = await (await cursor.execute(query, parameters)).fetchone()
    if row is None:
        raise fault("NOT_FOUND", "resource not found", "missing")
    return row


async def rows(cursor: Cursor, query, parameters=()) -> list[Row]:
    return await (await cursor.execute(query, parameters)).fetchall()


def same(row: Row, expected: Row):
    if any(row[key] != value for key, value in expected.items()):
        raise fault("STATE_CONFLICT", "identity already exists with different content")


async def insert(cursor: Cursor, table: str, values: Row) -> Row:
    return await one(
        cursor,
        sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING *").format(
            sql.Identifier(table),
            sql.SQL(",").join(map(sql.Identifier, values)),
            sql.SQL(",").join(sql.Placeholder() for _ in values),
        ),
        tuple(Jsonb(v) if isinstance(v, (dict, list)) else v for v in values.values()),
    )


def page_limit(limit: int) -> int:
    if not 1 <= limit <= 200:
        raise fault("VALIDATION", "limit must be between 1 and 200", "invalid")
    return limit


def message_values(value: NewMessage):
    return value.model_dump(exclude={"source", "reply_to"}) | {
        "source_type": value.source.type,
        "source_id": value.source.id,
        "source_label": value.source.label,
        "reply_to": value.reply_to.model_dump(mode="json") if value.reply_to else None,
        "conversation_key": value.conversation_key
        if value.conversation_key is not None
        else json.dumps([value.source.type, value.source.id], ensure_ascii=False),
    }


class Store:
    def __init__(self, database: AsyncConnectionPool, models: ModelCatalog):
        self.database = database
        self.models = models

    async def verify_models(self):
        async with self.database.connection() as connection:
            async with (
                connection.transaction(),
                connection.cursor(name="model_choices") as cursor,
            ):
                await cursor.execute(
                    "SELECT a.kind,a.model_id,a.reasoning_effort,"
                    "r.model_id,r.reasoning_effort FROM agents a "
                    "JOIN agents r ON r.id=a.leta_id"
                )
                while choices := await cursor.fetchmany(100):
                    for kind, model_id, effort, root_model, root_effort in choices:
                        root = ModelSelection(
                            model_id=root_model, reasoning_effort=root_effort
                        )
                        if kind == "leta":
                            self.models.resolve(root)
                        else:
                            self.models.inherit(root, model_id, effort)

    @asynccontextmanager
    async def transaction(self):
        try:
            async with self.database.connection() as connection:
                async with connection.transaction():
                    async with connection.cursor(row_factory=dict_row) as cursor:
                        await cursor.execute("SET LOCAL statement_timeout = '2s'")
                        await cursor.execute("SET LOCAL lock_timeout = '2s'")
                        yield cursor
        except UniqueViolation as error:
            raise fault(
                "STATE_CONFLICT", "identity or live name already exists"
            ) from error

    async def _root(self, cursor: Cursor, leta_id: UUID, *, exclusive=False) -> Row:
        root = await one(
            cursor,
            sql.SQL("SELECT * FROM agents WHERE id=%s AND kind='leta' FOR {}").format(
                sql.SQL("UPDATE" if exclusive else "SHARE")
            ),
            (leta_id,),
        )
        return root

    @staticmethod
    def _active(row: Row):
        if row["status"] != Lifecycle.ACTIVE:
            raise fault("RESOURCE_INACTIVE", "resource is not active")

    async def _agent_gate(self, cursor: Cursor, leta_id: UUID, agent_id: UUID) -> Row:
        # Never upgrade a shared root lock when the recipient is the root itself.
        root = await self._root(cursor, leta_id, exclusive=agent_id == leta_id)
        self._active(root)
        if agent_id != leta_id:
            child = await one(
                cursor,
                "SELECT * FROM agents WHERE id=%s AND leta_id=%s",
                (agent_id, leta_id),
            )
            box = await one(
                cursor, "SELECT * FROM boxes WHERE id=%s FOR SHARE", (child["box_id"],)
            )
            self._active(box)
            child = await one(
                cursor, "SELECT * FROM agents WHERE id=%s FOR UPDATE", (agent_id,)
            )
            self._active(child)
        return root

    async def create_leta(self, value: NewLeta) -> Row:
        self.models.resolve(value.model)
        expected = value.model_dump(exclude={"model"}) | {
            "leta_id": value.id,
            "kind": "leta",
            **value.model.model_dump(),
        }
        async with self.transaction() as cursor:
            await cursor.execute(
                "INSERT INTO agents (id,leta_id,kind,workspace_id,created_by_user_id,"
                "home_scope_id,name,description,system_prompt,model_id,reasoning_effort)"
                " "
                "VALUES (%s,%s,'leta',%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (id) DO NOTHING",
                (
                    value.id,
                    value.id,
                    value.workspace_id,
                    value.created_by_user_id,
                    value.home_scope_id,
                    value.name,
                    value.description,
                    value.system_prompt,
                    value.model.model_id,
                    value.model.reasoning_effort,
                ),
            )
            root = await self._root(cursor, value.id, exclusive=True)
            same(root, expected)
            return root

    async def get_agent(self, leta_id: UUID, agent_id: UUID) -> Row:
        async with self.transaction() as cursor:
            return await one(
                cursor,
                "SELECT * FROM agents WHERE id=%s AND leta_id=%s",
                (agent_id, leta_id),
            )

    async def list_workspace_leta(self, workspace_id, *, after=None, limit=100):
        if not 1 <= limit <= 100:
            raise fault("VALIDATION", "limit must be between 1 and 100", "invalid")
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT id FROM agents WHERE kind='leta' AND workspace_id=%s "
                "AND (%s::uuid IS NULL OR id>%s) ORDER BY id LIMIT %s",
                (workspace_id, after, after, limit + 1),
            )

    async def get_binding(self, leta_id: UUID) -> Row:
        async with self.transaction() as cursor:
            return await one(
                cursor,
                "SELECT id AS leta_id,kind,workspace_id,created_by_user_id,"
                "home_scope_id,status FROM agents WHERE id=%s AND kind='leta'",
                (leta_id,),
            )

    async def _configuration(self, cursor, leta_id, agent_id, patch, *, lock=False):
        root = await self._root(cursor, leta_id, exclusive=lock)
        self._active(root)
        agent = (
            root
            if agent_id == leta_id
            else await one(
                cursor,
                "SELECT * FROM agents WHERE id=%s AND leta_id=%s"
                + (" FOR UPDATE" if lock else ""),
                (agent_id, leta_id),
            )
        )
        self._active(agent)
        changes = patch.model_dump(exclude_unset=True)
        if agent_id != leta_id and changes.keys() - {"model_id", "reasoning_effort"}:
            raise fault(
                "VALIDATION", "Leti profile and prompt are immutable", "invalid"
            )
        updated = agent | changes
        try:
            if agent_id == leta_id:
                selection = ModelSelection(
                    model_id=updated["model_id"],
                    reasoning_effort=updated["reasoning_effort"],
                )
                self.models.resolve(selection)
                incompatible = []
                for child in await rows(
                    cursor,
                    "SELECT id,name,model_id,reasoning_effort FROM agents "
                    "WHERE leta_id=%s AND kind='leti' AND status<>'archived'",
                    (leta_id,),
                ):
                    try:
                        self.models.inherit(
                            selection, child["model_id"], child["reasoning_effort"]
                        )
                    except ValueError:
                        incompatible.append(f"{child['name']} ({child['id']})")
                if incompatible:
                    raise fault(
                        "VALIDATION",
                        "incompatible Leti model settings: " + ", ".join(incompatible),
                        "invalid",
                    )
            else:
                self.models.inherit(
                    ModelSelection(
                        model_id=root["model_id"],
                        reasoning_effort=root["reasoning_effort"],
                    ),
                    updated["model_id"],
                    updated["reasoning_effort"],
                )
        except ValueError as error:
            raise fault(
                "VALIDATION", "invalid effective model configuration", "invalid"
            ) from error
        return agent, changes

    async def validate_configuration(self, leta_id, agent_id, patch):
        async with self.transaction() as cursor:
            await self._configuration(cursor, leta_id, agent_id, patch)

    async def configure_agent(
        self, leta_id: UUID, agent_id: UUID, patch: AgentConfiguration
    ) -> Row:
        async with self.transaction() as cursor:
            agent, changes = await self._configuration(
                cursor, leta_id, agent_id, patch, lock=True
            )
            if not changes:
                return agent
            return await one(
                cursor,
                sql.SQL(
                    "UPDATE agents SET {},updated_at=now() WHERE id=%s RETURNING *"
                ).format(
                    sql.SQL(",").join(
                        sql.SQL("{}=%s").format(sql.Identifier(key)) for key in changes
                    )
                ),
                (*changes.values(), agent_id),
            )

    async def get_run(self, leta_id: UUID, agent_id: UUID, run_id: UUID) -> Row:
        async with self.transaction() as cursor:
            return await one(
                cursor,
                "SELECT r.* FROM runs r JOIN agents a ON a.id=r.agent_id "
                "WHERE r.id=%s AND r.agent_id=%s AND a.leta_id=%s",
                (run_id, agent_id, leta_id),
            )

    async def get_tool_result(self, agent_id: UUID, entry_id: UUID) -> Row | None:
        async with self.transaction() as cursor:
            return await (
                await cursor.execute(
                    "SELECT data FROM activity_log WHERE agent_id=%s "
                    "AND id=%s AND kind='tool_result'",
                    (agent_id, entry_id),
                )
            ).fetchone()

    async def list_roots(
        self, workspace_id: UUID, *, after: UUID | None = None, limit=20
    ):
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT * FROM agents WHERE kind='leta' AND workspace_id=%s "
                "AND (%s::uuid IS NULL OR id>%s) ORDER BY id LIMIT %s",
                (workspace_id, after, after, page_limit(limit)),
            )

    async def activate_leta(self, leta_id: UUID) -> Row:
        async with self.transaction() as cursor:
            root = await self._root(cursor, leta_id, exclusive=True)
            if root["status"] == Lifecycle.ACTIVE:
                return root
            if root["status"] != Lifecycle.INITIALIZING:
                raise fault("RESOURCE_INACTIVE", "Leta cannot be activated")
            return await one(
                cursor,
                "UPDATE agents SET status='active',updated_at=now() WHERE id=%s "
                "RETURNING *",
                (leta_id,),
            )

    async def set_paused(self, leta_id: UUID, paused: bool) -> Row:
        async with self.transaction() as cursor:
            self._active(await self._root(cursor, leta_id, exclusive=True))
            await cursor.execute(
                "UPDATE agents SET paused=%s,updated_at=now() WHERE id=%s",
                (paused, leta_id),
            )
            snapshot = await self._snapshot(cursor, leta_id, None)
            snapshot["agent_ids"] = [
                row["id"]
                for row in await rows(
                    cursor,
                    "SELECT a.id FROM agents a LEFT JOIN boxes b ON b.id=a.box_id "
                    "WHERE a.leta_id=%s AND a.status='active' "
                    "AND (a.box_id IS NULL OR b.status='active') ORDER BY a.id",
                    (leta_id,),
                )
            ]
            return snapshot

    async def create_box(self, value: NewBox) -> Row:
        async with self.transaction() as cursor:
            root = await self._root(cursor, value.leta_id, exclusive=True)
            existing = await (
                await cursor.execute("SELECT * FROM boxes WHERE id=%s", (value.id,))
            ).fetchone()
            roster = {agent.name: agent.id for agent in value.letis}
            expected = value.model_dump(
                exclude={"letis", "edges", "representative"}
            ) | {"representative_agent_id": roster[value.representative]}
            edges = sorted(
                tuple(sorted((roster[a], roster[b]))) for a, b in value.edges
            )
            if existing:
                same(existing, expected)
                children = await rows(
                    cursor, "SELECT * FROM agents WHERE box_id=%s", (value.id,)
                )
                if {child["id"] for child in children} != set(roster.values()):
                    raise fault("STATE_CONFLICT", "box graph differs")
                specs = {agent.id: agent for agent in value.letis}
                for child in children:
                    same(child, specs[child["id"]].model_dump())
                stored_edges = await rows(
                    cursor, "SELECT * FROM box_edges WHERE box_id=%s", (value.id,)
                )
                if (
                    sorted(
                        (edge["agent_low_id"], edge["agent_high_id"])
                        for edge in stored_edges
                    )
                    != edges
                ):
                    raise fault("STATE_CONFLICT", "box edges differ")
                return existing
            self._active(root)
            live = await rows(
                cursor,
                "SELECT name FROM boxes WHERE leta_id=%s AND status<>'archived'",
                (value.leta_id,),
            )
            if any(box_slug(row["name"]) == box_slug(value.name) for row in live):
                raise fault("STATE_CONFLICT", "box home path already reserved")
            box = await insert(cursor, "boxes", expected)
            for agent in value.letis:
                await insert(
                    cursor,
                    "agents",
                    agent.model_dump()
                    | {
                        "leta_id": value.leta_id,
                        "kind": "leti",
                        "box_id": value.id,
                    },
                )
            for low, high in edges:
                await insert(
                    cursor,
                    "box_edges",
                    {
                        "box_id": value.id,
                        "agent_low_id": low,
                        "agent_high_id": high,
                    },
                )
            return box

    async def get_box(self, leta_id: UUID, box_id: UUID, *, details=False) -> Row:
        async with self.transaction() as cursor:
            box = await one(
                cursor,
                "SELECT * FROM boxes WHERE id=%s AND leta_id=%s",
                (box_id, leta_id),
            )
            box["letis"] = await rows(
                cursor, "SELECT * FROM agents WHERE box_id=%s ORDER BY id", (box_id,)
            )
            box["edges"] = await rows(
                cursor,
                "SELECT * FROM box_edges WHERE box_id=%s ORDER BY "
                "agent_low_id,agent_high_id",
                (box_id,),
            )
            if not details:
                return box
            agent_ids = [agent["id"] for agent in box["letis"]]
            box["runs"] = await rows(
                cursor,
                "SELECT DISTINCT ON (agent_id) id,agent_id,status,started_at "
                "FROM runs WHERE agent_id=ANY(%s) "
                "ORDER BY agent_id,started_at DESC,id DESC",
                (agent_ids,),
            )
            box["requests"] = await rows(
                cursor,
                "SELECT id,requester_agent_id,kind,title,status,expires_at "
                "FROM hitl_requests WHERE requester_agent_id=ANY(%s) "
                "AND status='pending' ORDER BY created_at,id",
                (agent_ids,),
            )
            box["schedules"] = await rows(
                cursor,
                "SELECT id,target_agent_id,title,paused FROM schedules "
                "WHERE box_id=%s AND deleted_at IS NULL ORDER BY id",
                (box_id,),
            )
            return box

    async def resolve_box(self, leta_id: UUID, reference: str) -> Row:
        try:
            identity = UUID(reference)
        except ValueError:
            identity = None
        async with self.transaction() as cursor:
            return await one(
                cursor,
                "SELECT * FROM boxes WHERE leta_id=%s AND "
                "((%s::uuid IS NOT NULL AND id=%s) OR "
                "(%s::uuid IS NULL AND name=%s AND status<>'archived'))",
                (leta_id, identity, identity, identity, reference),
            )

    async def list_boxes(self, leta_id: UUID, *, after: UUID | None = None, limit=20):
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT b.*, (SELECT count(*) FROM agents a WHERE a.box_id=b.id) "
                "AS agent_count, (SELECT count(*) FROM hitl_requests h JOIN "
                "agents a ON a.id=h.requester_agent_id WHERE a.box_id=b.id "
                "AND h.status='pending') AS pending_request_count, "
                "(SELECT count(*) FROM schedules s WHERE s.box_id=b.id "
                "AND s.deleted_at IS NULL) AS schedule_count FROM boxes b "
                "WHERE b.leta_id=%s AND (%s::uuid IS NULL OR b.id>%s) "
                "ORDER BY b.id LIMIT %s",
                (leta_id, after, after, page_limit(limit)),
            )

    async def activate_box(self, leta_id: UUID, box_id: UUID) -> Row:
        async with self.transaction() as cursor:
            self._active(await self._root(cursor, leta_id))
            box = await one(
                cursor,
                "SELECT * FROM boxes WHERE id=%s AND leta_id=%s FOR UPDATE",
                (box_id, leta_id),
            )
            if box["status"] == Lifecycle.ACTIVE:
                return box
            if box["status"] != Lifecycle.INITIALIZING:
                raise fault("RESOURCE_INACTIVE", "box cannot be activated")
            await cursor.execute(
                "UPDATE agents SET status='active',updated_at=now() WHERE "
                "box_id=%s AND status='initializing'",
                (box_id,),
            )
            return await one(
                cursor,
                "UPDATE boxes SET status='active',updated_at=now() WHERE id=%s "
                "RETURNING *",
                (box_id,),
            )

    async def _snapshot(
        self, cursor: Cursor, leta_id: UUID, box_id: UUID | None
    ) -> Row:
        agents = await rows(
            cursor,
            "SELECT id FROM agents WHERE leta_id=%s AND (%s::uuid IS NULL OR "
            "box_id=%s) ORDER BY id",
            (leta_id, box_id, box_id),
        )
        ids = [agent["id"] for agent in agents]
        return {
            "agent_ids": ids,
            "box_ids": [
                row["id"]
                for row in await rows(
                    cursor,
                    "SELECT id FROM boxes WHERE leta_id=%s AND (%s::uuid IS NULL "
                    "OR id=%s) ORDER BY id",
                    (leta_id, box_id, box_id),
                )
            ],
            "schedule_ids": [
                row["id"]
                for row in await rows(
                    cursor,
                    "SELECT id FROM schedules WHERE target_agent_id=ANY(%s) AND "
                    "deleted_at IS NULL ORDER BY id",
                    (ids,),
                )
            ],
            "request_ids": [
                row["id"]
                for row in await rows(
                    cursor,
                    "SELECT id FROM hitl_requests WHERE "
                    "requester_agent_id=ANY(%s) AND (status='pending' OR outcome "
                    "IS NULL) ORDER BY id",
                    (ids,),
                )
            ],
        }

    async def begin_delete(self, leta_id: UUID, box_id: UUID | None = None) -> Row:
        async with self.transaction() as cursor:
            root = await self._root(cursor, leta_id, exclusive=box_id is None)
            if box_id is None:
                if root["status"] != Lifecycle.ARCHIVED:
                    await cursor.execute(
                        "UPDATE agents SET status='deleting',updated_at=now() "
                        "WHERE id=%s",
                        (leta_id,),
                    )
            else:
                box = await one(
                    cursor,
                    "SELECT * FROM boxes WHERE id=%s AND leta_id=%s FOR UPDATE",
                    (box_id, leta_id),
                )
                if box["status"] != Lifecycle.ARCHIVED:
                    await cursor.execute(
                        "UPDATE boxes SET status='deleting',updated_at=now() "
                        "WHERE id=%s",
                        (box_id,),
                    )
            return await self._snapshot(cursor, leta_id, box_id)

    async def archive(self, leta_id: UUID, box_id: UUID | None = None):
        async with self.transaction() as cursor:
            root = await self._root(cursor, leta_id, exclusive=box_id is None)
            target = (
                root
                if box_id is None
                else await one(
                    cursor,
                    "SELECT * FROM boxes WHERE id=%s AND leta_id=%s FOR UPDATE",
                    (box_id, leta_id),
                )
            )
            if target["status"] == Lifecycle.ARCHIVED:
                return
            if target["status"] != Lifecycle.DELETING:
                raise fault("STATE_CONFLICT", "close the resource before archiving")
            snapshot = await self._snapshot(cursor, leta_id, box_id)
            running = await rows(
                cursor,
                "SELECT id FROM runs WHERE agent_id=ANY(%s) AND status IN "
                "('running','paused') LIMIT 1",
                (snapshot["agent_ids"],),
            )
            if snapshot["request_ids"] or snapshot["schedule_ids"] or running:
                raise fault(
                    "STATE_CONFLICT", "resource still has active work or input sources"
                )
            await cursor.execute(
                "UPDATE agents SET "
                "status='archived',archived_at=now(),updated_at=now() WHERE "
                "id=ANY(%s) AND status<>'archived'",
                (snapshot["agent_ids"],),
            )
            await cursor.execute(
                "UPDATE boxes SET "
                "status='archived',archived_at=now(),updated_at=now() WHERE "
                "id=ANY(%s) AND status<>'archived'",
                (snapshot["box_ids"],),
            )

    async def _route(self, cursor: Cursor, value: NewMessage, root: Row):
        if value.sender_agent_id is None:
            if value.recipient_user_id is not None:
                raise fault(
                    "FORBIDDEN",
                    "human messages require a verified Leta sender",
                    "forbidden",
                )
            return  # Source adapters validate owner/HITL/schedule/external provenance.
        sender = await one(
            cursor,
            "SELECT * FROM agents WHERE id=%s AND leta_id=%s",
            (value.sender_agent_id, value.leta_id),
        )
        self._active(sender)
        if sender["kind"] == "leta":
            if value.recipient_user_id == root["created_by_user_id"]:
                return
            allowed = await rows(
                cursor,
                "SELECT id FROM boxes WHERE leta_id=%s AND "
                "representative_agent_id=%s AND status='active'",
                (value.leta_id, value.recipient_agent_id),
            )
        else:
            box = await one(
                cursor, "SELECT * FROM boxes WHERE id=%s FOR SHARE", (sender["box_id"],)
            )
            self._active(box)
            if (
                value.recipient_agent_id == value.leta_id
                and box["representative_agent_id"] == sender["id"]
            ):
                return
            low, high = sorted((sender["id"], value.recipient_agent_id or sender["id"]))
            allowed = await rows(
                cursor,
                "SELECT box_id FROM box_edges WHERE box_id=%s AND agent_low_id=%s"
                " AND agent_high_id=%s",
                (sender["box_id"], low, high),
            )
        if not allowed:
            raise fault(
                "FORBIDDEN", "message target is outside the allowed roster", "forbidden"
            )

    async def receive(
        self, value: NewMessage, *, schedule_id: UUID | None = None
    ) -> Row:
        expected = message_values(value)
        async with self.transaction() as cursor:
            saved = await (
                await cursor.execute("SELECT * FROM messages WHERE id=%s", (value.id,))
            ).fetchone()
            if saved:
                same(saved, expected)
                return saved
            root = await self._agent_gate(
                cursor, value.leta_id, value.recipient_agent_id or value.leta_id
            )
            if schedule_id is not None:
                schedule = await one(
                    cursor,
                    "SELECT * FROM schedules WHERE id=%s AND leta_id=%s FOR SHARE",
                    (schedule_id, value.leta_id),
                )
                if (
                    schedule["deleted_at"] is not None
                    or schedule["target_agent_id"] != value.recipient_agent_id
                ):
                    raise fault(
                        "RESOURCE_INACTIVE", "schedule no longer admits this delivery"
                    )
            await self._route(cursor, value, root)
            saved = await (
                await cursor.execute("SELECT * FROM messages WHERE id=%s", (value.id,))
            ).fetchone()
            if saved:
                same(saved, expected)
                return saved
            if value.in_reply_to_message_id:
                prior = await one(
                    cursor,
                    "SELECT * FROM messages WHERE id=%s AND leta_id=%s",
                    (value.in_reply_to_message_id, value.leta_id),
                )
                if (
                    prior["conversation_key"] != expected["conversation_key"]
                    or prior["reply_to"] is None
                ):
                    raise fault(
                        "VALIDATION",
                        "message is not replyable in this conversation",
                        "invalid",
                    )
                if prior["recipient_agent_id"] != value.sender_agent_id:
                    raise fault(
                        "FORBIDDEN",
                        "cannot reply to another agent's message",
                        "forbidden",
                    )
                address = prior["reply_to"]
                target = (
                    value.recipient_user_id
                    if address["type"] == "user"
                    else value.recipient_agent_id
                )
                if address["type"] == "box":
                    box = await one(
                        cursor,
                        "SELECT representative_agent_id FROM boxes WHERE id=%s "
                        "AND leta_id=%s",
                        (UUID(address["id"]), value.leta_id),
                    )
                    expected_target = (
                        value.leta_id
                        if prior["sender_agent_id"] == value.leta_id
                        else box["representative_agent_id"]
                    )
                else:
                    expected_target = UUID(address["id"])
                if target != expected_target:
                    raise fault(
                        "FORBIDDEN",
                        "reply does not match the original address",
                        "forbidden",
                    )
            if value.recipient_agent_id:
                counter = await one(
                    cursor,
                    "UPDATE agents SET inbox_seq=inbox_seq+1 WHERE id=%s "
                    "RETURNING inbox_seq",
                    (value.recipient_agent_id,),
                )
                expected["seq"] = counter["inbox_seq"]
            return await insert(cursor, "messages", expected)

    async def get_message(self, leta_id: UUID, message_id: UUID) -> Row:
        async with self.transaction() as cursor:
            return await one(
                cursor,
                "SELECT * FROM messages WHERE id=%s AND leta_id=%s",
                (message_id, leta_id),
            )

    async def list_inbox(
        self,
        leta_id: UUID,
        agent_id: UUID,
        *,
        after=0,
        through: int | None = None,
        conversation: str | None = None,
        unread_only=False,
        mark_read=False,
        limit=20,
        lookahead=False,
    ):
        if after < 0 or (through is not None and through < after):
            raise fault("VALIDATION", "invalid inbox range", "invalid")
        if mark_read and agent_id != leta_id:
            raise fault("FORBIDDEN", "Leti has no inbox read tool", "forbidden")
        async with self.transaction() as cursor:
            found = await rows(
                cursor,
                "SELECT * FROM messages WHERE leta_id=%s AND "
                "recipient_agent_id=%s AND seq>%s "
                "AND (%s::bigint IS NULL OR seq<=%s) AND (%s::text IS NULL OR "
                "conversation_key=%s) "
                "AND (NOT %s OR read_at IS NULL) ORDER BY seq LIMIT %s",
                (
                    leta_id,
                    agent_id,
                    after,
                    through,
                    through,
                    conversation,
                    conversation,
                    unread_only,
                    page_limit(limit) + int(lookahead),
                ),
            )
            if mark_read and found:
                marked = await rows(
                    cursor,
                    "UPDATE messages SET read_at=COALESCE(read_at,now()) WHERE "
                    "id=ANY(%s) RETURNING id,read_at",
                    ([row["id"] for row in found[:limit]],),
                )
                times = {row["id"]: row["read_at"] for row in marked}
                for row in found[:limit]:
                    row["read_at"] = times[row["id"]]
            return found

    async def list_inbox_groups(
        self,
        leta_id: UUID,
        *,
        source_id: str | None = None,
        unread_only=True,
        before: int | None = None,
        limit=20,
    ) -> list[Row]:
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "WITH grouped AS (SELECT conversation_key,source_type,source_id,"
                "source_label,reply_to,count(*) AS message_count,"
                "count(*) FILTER (WHERE read_at IS NULL) AS unread_count,"
                "max(seq) AS latest_seq FROM messages WHERE leta_id=%s "
                "AND recipient_agent_id=%s AND (NOT %s OR read_at IS NULL) "
                "AND (%s::text IS NULL OR source_id=%s) GROUP BY conversation_key,"
                "source_type,source_id,source_label,reply_to) "
                "SELECT g.*,left(m.content,200) AS preview FROM grouped g "
                "JOIN messages m ON m.recipient_agent_id=%s AND m.seq=g.latest_seq "
                "WHERE (%s::bigint IS NULL OR g.latest_seq<%s) "
                "ORDER BY g.latest_seq DESC LIMIT %s",
                (
                    leta_id,
                    leta_id,
                    unread_only,
                    source_id,
                    source_id,
                    leta_id,
                    before,
                    before,
                    page_limit(limit) + 1,
                ),
            )

    async def list_conversation(
        self,
        leta_id: UUID,
        conversation: str,
        *,
        after: TimeCursor | None = None,
        limit=20,
    ):
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT * FROM messages WHERE leta_id=%s AND conversation_key=%s "
                "AND (%s::timestamptz IS NULL OR (created_at,id)>(%s,%s)) ORDER "
                "BY created_at,id LIMIT %s",
                (
                    leta_id,
                    conversation,
                    after.at if after else None,
                    after.at if after else None,
                    after.id if after else None,
                    page_limit(limit),
                ),
            )

    async def append_activity(
        self, value: NewActivity, *, read_message_ids: list[UUID] | None = None
    ) -> Row:
        expected = value.model_dump()
        async with self.transaction() as cursor:
            agent = await one(
                cursor, "SELECT * FROM agents WHERE id=%s FOR UPDATE", (value.agent_id,)
            )
            saved = await (
                await cursor.execute(
                    "SELECT * FROM activity_log WHERE agent_id=%s AND dedup_key=%s",
                    (value.agent_id, value.dedup_key),
                )
            ).fetchone()
            if saved:
                same(saved, expected)
                return saved
            if value.message_id:
                await one(
                    cursor,
                    "SELECT id FROM messages WHERE id=%s AND leta_id=%s",
                    (value.message_id, agent["leta_id"]),
                )
            if read_message_ids:
                # A lost tool result must not hide its unread input on recovery.
                if agent["kind"] != "leta" or value.kind != "tool_result":
                    raise fault("FORBIDDEN", "invalid inbox read result", "forbidden")
                marked = await cursor.execute(
                    "UPDATE messages SET read_at=COALESCE(read_at,now()) "
                    "WHERE leta_id=%s AND recipient_agent_id=%s AND id=ANY(%s)",
                    (agent["leta_id"], value.agent_id, read_message_ids),
                )
                if marked.rowcount != len(read_message_ids):
                    raise fault(
                        "FORBIDDEN", "inbox read targets another agent", "forbidden"
                    )
            expected["seq"] = (
                await one(
                    cursor,
                    "UPDATE agents SET activity_seq=activity_seq+1 WHERE id=%s "
                    "RETURNING activity_seq",
                    (value.agent_id,),
                )
            )["activity_seq"]
            return await insert(cursor, "activity_log", expected)

    async def list_activity(
        self,
        leta_id: UUID,
        agent_id: UUID,
        *,
        after=0,
        run_id: UUID | None = None,
        limit=20,
    ):
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT l.* FROM activity_log l JOIN agents a ON a.id=l.agent_id "
                "WHERE a.leta_id=%s AND l.agent_id=%s AND l.seq>%s AND (%s::uuid "
                "IS NULL OR l.run_id=%s) ORDER BY l.seq LIMIT %s",
                (leta_id, agent_id, after, run_id, run_id, page_limit(limit)),
            )

    async def get_activity(self, leta_id: UUID, agent_id: UUID, entry_id: UUID) -> Row:
        async with self.transaction() as cursor:
            return await one(
                cursor,
                "SELECT l.* FROM activity_log l JOIN agents a "
                "ON a.id=l.agent_id WHERE a.leta_id=%s AND l.agent_id=%s AND l.id=%s",
                (leta_id, agent_id, entry_id),
            )

    async def search_activity(
        self,
        leta_id: UUID,
        agent_id: UUID,
        *,
        query: str | None = None,
        before: int | None = None,
        limit=20,
    ) -> list[Row]:
        if (
            not 1 <= limit <= 100
            or (before is not None and before < 1)
            or (query is not None and (len(query) > 2000 or "\0" in query))
        ):
            raise fault("VALIDATION", "invalid history query", "invalid")
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT l.id,l.seq,l.kind,l.created_at,"
                "left((l.data-'message')::text,400) AS preview "
                "FROM activity_log l JOIN agents a "
                "ON a.id=l.agent_id WHERE a.leta_id=%s AND l.agent_id=%s "
                "AND (%s::bigint IS NULL OR l.seq<%s) "
                "AND (%s::text IS NULL OR "
                "position(lower(%s) IN lower((l.data-'message')::text))>0) "
                "ORDER BY l.seq DESC LIMIT %s",
                (leta_id, agent_id, before, before, query, query, limit + 1),
            )

    async def bootstrap_agent(self, leta_id: UUID, agent_id: UUID) -> Row:
        async with self.transaction() as cursor:
            return await one(
                cursor,
                "SELECT a.inbox_seq AS latest_seq,COALESCE(r.inbox_cursor,0) AS "
                "cursor,CASE WHEN r.status IN ('running','paused') THEN r.id END "
                "AS run_id,root.paused,a.status,root.status AS root_status,"
                "b.status AS box_status FROM agents a JOIN agents root ON "
                "root.id=a.leta_id LEFT JOIN boxes b ON b.id=a.box_id "
                "LEFT JOIN LATERAL (SELECT id,status,inbox_cursor FROM runs "
                "WHERE agent_id=a.id ORDER BY started_at DESC,id DESC LIMIT 1) r "
                "ON true WHERE a.id=%s AND a.leta_id=%s",
                (agent_id, leta_id),
            )

    async def request_run_yield(
        self, leta_id: UUID, agent_id: UUID, run_id: UUID
    ) -> Row:
        async with self.transaction() as cursor:
            return await one(
                cursor,
                "UPDATE runs r SET yield_requested=CASE WHEN r.status IN "
                "('running','paused') THEN true ELSE r.yield_requested END "
                "FROM agents a WHERE r.id=%s AND r.agent_id=%s AND a.id=r.agent_id "
                "AND a.leta_id=%s RETURNING r.status,r.yield_requested",
                (run_id, agent_id, leta_id),
            )

    async def cancel_unfinished_run(
        self, leta_id: UUID, agent_id: UUID, run_id: UUID
    ) -> Row:
        async with self.transaction() as cursor:
            return await one(
                cursor,
                "UPDATE runs r SET status=CASE WHEN r.finished_at IS NULL THEN "
                "'cancelled' ELSE r.status END,"
                "finished_at=COALESCE(r.finished_at,now()),"
                "yield_requested=false FROM agents a WHERE r.id=%s AND "
                "r.agent_id=%s AND a.id=r.agent_id AND a.leta_id=%s RETURNING r.status",
                (run_id, agent_id, leta_id),
            )

    async def start_run(self, leta_id: UUID, agent_id: UUID, run_id: UUID) -> Row:
        async with self.transaction() as cursor:
            await self._agent_gate(cursor, leta_id, agent_id)
            saved = await (
                await cursor.execute("SELECT * FROM runs WHERE id=%s", (run_id,))
            ).fetchone()
            if saved:
                same(saved, {"agent_id": agent_id})
                return saved
            return await insert(cursor, "runs", {"id": run_id, "agent_id": agent_id})

    async def save_run(
        self,
        leta_id: UUID,
        agent_id: UUID,
        run_id: UUID,
        *,
        status: RunStatus,
        inbox_cursor: int,
        checkpoint_id: str | None = None,
        checkpoint_ns: str | None = None,
        continuation: Row | None = None,
        result: Row | None = None,
        error: Row | None = None,
    ) -> Row:
        async with self.transaction() as cursor:
            agent = await one(
                cursor,
                "SELECT * FROM agents WHERE id=%s AND leta_id=%s FOR UPDATE",
                (agent_id, leta_id),
            )
            run = await one(
                cursor,
                "SELECT * FROM runs WHERE id=%s AND agent_id=%s FOR UPDATE",
                (run_id, agent_id),
            )
            if not run["inbox_cursor"] <= inbox_cursor <= agent["inbox_seq"]:
                raise fault("STATE_CONFLICT", "invalid run inbox progress")
            expected = {
                "status": status,
                "inbox_cursor": inbox_cursor,
                "checkpoint_id": checkpoint_id,
                "checkpoint_ns": checkpoint_ns,
                "continuation": continuation,
                "result": result,
                "error": error,
            }
            if run["status"] in {
                RunStatus.COMPLETED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            }:
                same(run, expected)
                return run
            return await one(
                cursor,
                "UPDATE runs SET "
                "status=%s,inbox_cursor=%s,checkpoint_id=%s,checkpoint_ns=%s,continuation=%s,result=%s,error=%s,yield_requested=false,finished_at=CASE"
                " WHEN %s IN ('completed','failed','cancelled') THEN now() ELSE "
                "NULL END WHERE id=%s RETURNING *",
                (
                    status,
                    inbox_cursor,
                    checkpoint_id,
                    checkpoint_ns,
                    Jsonb(continuation) if continuation is not None else None,
                    Jsonb(result) if result is not None else None,
                    Jsonb(error) if error is not None else None,
                    status,
                    run_id,
                ),
            )

    async def list_runs(
        self,
        leta_id: UUID,
        agent_id: UUID,
        *,
        after: TimeCursor | None = None,
        limit=20,
    ):
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT r.* FROM runs r JOIN agents a ON a.id=r.agent_id WHERE "
                "a.leta_id=%s AND r.agent_id=%s AND (%s::timestamptz IS NULL OR "
                "(r.started_at,r.id)>(%s,%s)) ORDER BY r.started_at,r.id LIMIT %s",
                (
                    leta_id,
                    agent_id,
                    after.at if after else None,
                    after.at if after else None,
                    after.id if after else None,
                    page_limit(limit),
                ),
            )

    async def create_request(
        self, value: NewHumanRequest, *, timeout_seconds: int | None = None
    ) -> Row:
        if timeout_seconds is not None and (
            not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or timeout_seconds < 1
            or value.expires_at is not None
        ):
            raise fault("VALIDATION", "invalid request timeout", "invalid")
        expected = value.model_dump()
        if value.kind == "approval":
            try:
                resource = PersonalScopeResource.model_validate(value.resource)
                if resource.user_id != value.approver_user_id:
                    raise ValueError("resource owner differs from approver")
                expected["resource"] = resource.model_dump(mode="json")
            except ValueError as error:
                raise fault(
                    "VALIDATION", "invalid personal resource", "invalid"
                ) from error
        if timeout_seconds is not None:
            expected["payload"] = value.payload | {"timeout_seconds": timeout_seconds}
        async with self.transaction() as cursor:
            await self._root(cursor, value.leta_id, exclusive=True)
            saved = await (
                await cursor.execute(
                    "SELECT * FROM hitl_requests WHERE id=%s", (value.id,)
                )
            ).fetchone()
            if saved:
                same(
                    saved,
                    {
                        key: item
                        for key, item in expected.items()
                        if (key != "expires_at" or timeout_seconds is None)
                        and (key != "grant_key" or value.grant_key is not None)
                    },
                )
                return saved
            if value.kind == "approval" and value.grant_key is None:
                expected["grant_key"] = uuid7()
            root = await self._agent_gate(
                cursor, value.leta_id, value.requester_agent_id
            )
            if (
                value.kind == "ask"
                and value.approver_user_id != root["created_by_user_id"]
            ):
                raise fault("FORBIDDEN", "ask must target Leta creator", "forbidden")
            if value.kind == "ask":
                try:
                    AskForm.model_validate(value.payload)
                except ValueError as error:
                    raise fault("VALIDATION", "invalid ask form", "invalid") from error
            if timeout_seconds is not None:
                clock = await one(cursor, "SELECT clock_timestamp() AS at")
                try:
                    expected["expires_at"] = clock["at"] + timedelta(
                        seconds=timeout_seconds
                    )
                except OverflowError as error:
                    raise fault(
                        "VALIDATION", "request timeout out of range", "invalid"
                    ) from error
            return await insert(cursor, "hitl_requests", expected)

    async def get_request(self, leta_id: UUID, request_id: UUID) -> Row:
        async with self.transaction() as cursor:
            return await one(
                cursor,
                "SELECT * FROM hitl_requests WHERE leta_id=%s AND id=%s",
                (leta_id, request_id),
            )

    async def resolve_request(self, value: RequestResolution) -> Row:
        async with self.transaction() as cursor:
            request = await one(
                cursor,
                "SELECT * FROM hitl_requests WHERE leta_id=%s AND id=%s FOR UPDATE",
                (value.leta_id, value.request_id),
            )
            root = await one(
                cursor,
                "SELECT created_by_user_id FROM agents WHERE id=%s AND kind='leta'",
                (value.leta_id,),
            )
            if value.action in {"answer", "accept", "deny"}:
                allowed = value.actor_user_id == request["approver_user_id"]
            elif value.action == "cancel":
                allowed = value.actor_user_id == root[
                    "created_by_user_id"
                ] or value.requester_agent_id in {
                    value.leta_id,
                    request["requester_agent_id"],
                }
            else:
                allowed = True
            if not allowed:
                raise fault(
                    "FORBIDDEN", "request is addressed to another actor", "forbidden"
                )
            if value.action == "answer":
                if request["kind"] != "ask":
                    raise fault(
                        "VALIDATION", "approval does not accept form answers", "invalid"
                    )
                try:
                    answers = normalize_answers(
                        AskForm(questions=request["payload"]["questions"]),
                        value.answers,
                    )
                except (ValueError, KeyError) as error:
                    raise fault(
                        "VALIDATION", "invalid form answers", "invalid"
                    ) from error
            else:
                answers = None
                if value.action in {"accept", "deny"} and request["kind"] != "approval":
                    raise fault("VALIDATION", "ask requires form answers", "invalid")
            decision = {"action": value.action}
            if value.actor_user_id is not None:
                decision["actor_user_id"] = str(value.actor_user_id)
            if value.requester_agent_id is not None:
                decision["requester_agent_id"] = str(value.requester_agent_id)
            if answers is not None:
                decision["answers"] = answers
            if value.reason:
                decision["reason"] = value.reason
            if request["status"] != HumanStatus.PENDING:
                if (
                    request["decision"] == decision
                    or value.action == "expire"
                    or request["status"] == HumanStatus.EXPIRED
                ):
                    return request
                raise fault(
                    "STATE_CONFLICT", "request already has a different decision"
                )
            clock = (await one(cursor, "SELECT clock_timestamp() AS at"))["at"]
            overdue = (
                request["expires_at"] is not None and request["expires_at"] <= clock
            )
            if value.action == "expire" and not overdue:
                return request
            if overdue:
                status, decision = HumanStatus.EXPIRED, {"action": "expire"}
            else:
                status = (
                    HumanStatus.CANCELLED
                    if value.action == "cancel"
                    else HumanStatus.RESOLVED
                )
            outcome = (
                None
                if status == HumanStatus.RESOLVED and value.action == "accept"
                else {"status": status, **decision}
            )
            return await one(
                cursor,
                "UPDATE hitl_requests SET status=%s,decision=%s,outcome=%s,"
                "resolved_at=%s WHERE id=%s RETURNING *",
                (
                    status,
                    Jsonb(decision),
                    Jsonb(outcome) if outcome is not None else None,
                    clock,
                    value.request_id,
                ),
            )

    async def save_request_outcome(
        self, leta_id: UUID, request_id: UUID, outcome: dict
    ) -> Row:
        async with self.transaction() as cursor:
            request = await one(
                cursor,
                "SELECT * FROM hitl_requests WHERE leta_id=%s AND id=%s FOR UPDATE",
                (leta_id, request_id),
            )
            if request["outcome"] is not None:
                same(request, {"outcome": outcome})
                return request
            if (
                request["status"] != HumanStatus.RESOLVED
                or request["decision"].get("action") != "accept"
            ):
                raise fault(
                    "STATE_CONFLICT", "only accepted approval awaits a grant outcome"
                )
            return await one(
                cursor,
                "UPDATE hitl_requests SET outcome=%s WHERE id=%s RETURNING *",
                (Jsonb(outcome), request_id),
            )

    async def list_requests(
        self,
        leta_id: UUID,
        *,
        requester_agent_id: UUID | None = None,
        box_id: UUID | None = None,
        status: HumanStatus | None = None,
        after: TimeCursor | None = None,
        limit=20,
    ):
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT * FROM hitl_requests WHERE leta_id=%s AND (%s::uuid IS "
                "NULL OR requester_agent_id=%s) AND (%s::uuid IS NULL OR "
                "requester_agent_id IN (SELECT id FROM agents WHERE box_id=%s)) "
                "AND (%s::text IS NULL OR status=%s) AND (%s::timestamptz IS NULL OR "
                "(created_at,id)>(%s,%s)) ORDER BY created_at,id LIMIT %s",
                (
                    leta_id,
                    requester_agent_id,
                    requester_agent_id,
                    box_id,
                    box_id,
                    status,
                    status,
                    after.at if after else None,
                    after.at if after else None,
                    after.id if after else None,
                    page_limit(limit),
                ),
            )

    async def create_schedule(self, value: NewSchedule) -> Row:
        expected = value.model_dump()
        async with self.transaction() as cursor:
            saved = await (
                await cursor.execute("SELECT * FROM schedules WHERE id=%s", (value.id,))
            ).fetchone()
            if saved:
                same(saved, expected)
                return saved
            await self._agent_gate(cursor, value.leta_id, value.creator_agent_id)
            if value.creator_agent_id != value.leta_id:
                if value.target_agent_id != value.creator_agent_id:
                    raise fault(
                        "FORBIDDEN", "Leti can schedule only itself", "forbidden"
                    )
                child = await one(
                    cursor,
                    "SELECT box_id FROM agents WHERE id=%s",
                    (value.creator_agent_id,),
                )
                if value.box_id != child["box_id"]:
                    raise fault(
                        "VALIDATION", "schedule box does not match target", "invalid"
                    )
            elif value.target_agent_id == value.leta_id:
                if value.box_id is not None:
                    raise fault("VALIDATION", "root schedule has no box", "invalid")
            else:
                box = await one(
                    cursor,
                    "SELECT * FROM boxes WHERE id=%s AND leta_id=%s FOR SHARE",
                    (value.box_id, value.leta_id),
                )
                self._active(box)
                if value.target_agent_id != box["representative_agent_id"]:
                    raise fault(
                        "FORBIDDEN",
                        "Leta must schedule the box representative",
                        "forbidden",
                    )
            await self._agent_gate(cursor, value.leta_id, value.target_agent_id)
            return await insert(cursor, "schedules", expected)

    async def list_schedules(
        self,
        leta_id: UUID,
        *,
        target_agent_id: UUID | None = None,
        after: UUID | None = None,
        box_id: UUID | None = None,
        limit=20,
    ):
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT * FROM schedules WHERE leta_id=%s AND deleted_at IS NULL "
                "AND (%s::uuid IS NULL "
                "OR target_agent_id=%s) AND (%s::uuid IS NULL OR box_id=%s) "
                "AND (%s::uuid IS NULL OR id>%s) ORDER BY "
                "id LIMIT %s",
                (
                    leta_id,
                    target_agent_id,
                    target_agent_id,
                    box_id,
                    box_id,
                    after,
                    after,
                    page_limit(limit),
                ),
            )

    async def get_schedule(self, leta_id: UUID, schedule_id: UUID) -> Row:
        async with self.transaction() as cursor:
            return await one(
                cursor,
                "SELECT * FROM schedules WHERE id=%s AND leta_id=%s",
                (schedule_id, leta_id),
            )

    async def update_schedule(
        self,
        leta_id: UUID,
        schedule_id: UUID,
        requester_agent_id: UUID,
        patch: SchedulePatch,
    ) -> Row:
        async with self.transaction() as cursor:
            await self._agent_gate(cursor, leta_id, requester_agent_id)
            saved = await one(
                cursor,
                "SELECT * FROM schedules WHERE id=%s AND leta_id=%s FOR UPDATE",
                (schedule_id, leta_id),
            )
            self._schedule_actor(saved, requester_agent_id)
            if saved["deleted_at"] is not None:
                raise fault("RESOURCE_INACTIVE", "schedule is deleted")
            await self._agent_gate(cursor, leta_id, saved["target_agent_id"])
            fields = patch.model_dump(exclude_unset=True)
            combined = NewSchedule.model_validate(
                {key: fields.get(key, saved[key]) for key in NewSchedule.model_fields}
            )
            from leta.schedules import compile_schedule

            compile_schedule(combined.spec, end_at=combined.end_at)
            return await one(
                cursor,
                sql.SQL(
                    "UPDATE schedules SET {},updated_at=clock_timestamp() "
                    "WHERE id=%s RETURNING *"
                ).format(
                    sql.SQL(",").join(
                        sql.SQL("{}=%s").format(sql.Identifier(key)) for key in fields
                    )
                ),
                (
                    *[Jsonb(v) if isinstance(v, dict) else v for v in fields.values()],
                    schedule_id,
                ),
            )

    @staticmethod
    def _schedule_actor(saved: Row, agent_id: UUID):
        if agent_id not in {saved["leta_id"], saved["target_agent_id"]}:
            raise fault("FORBIDDEN", "Leti may manage only its schedules", "forbidden")

    async def delete_schedule(
        self, leta_id: UUID, schedule_id: UUID, requester_agent_id: UUID
    ) -> Row:
        async with self.transaction() as cursor:
            # Teardown must remove sources even when their root/box is deleting.
            await self._root(cursor, leta_id)
            saved = await one(
                cursor,
                "SELECT * FROM schedules WHERE id=%s AND leta_id=%s FOR UPDATE",
                (schedule_id, leta_id),
            )
            self._schedule_actor(saved, requester_agent_id)
            if saved["deleted_at"] is not None:
                return saved
            return await one(
                cursor,
                "UPDATE schedules SET deleted_at=clock_timestamp(),"
                "updated_at=clock_timestamp() WHERE id=%s RETURNING *",
                (schedule_id,),
            )

    async def schedule_occurrence(
        self, leta_id: UUID, schedule_id: UUID, message_id: UUID
    ) -> Row | None:
        async with self.transaction() as cursor:
            # Reuse an admitted occurrence even if its definition was edited later.
            exists = await (
                await cursor.execute(
                    "SELECT id FROM messages WHERE id=%s", (message_id,)
                )
            ).fetchone()
            if exists:
                return None
            saved = await one(
                cursor,
                "SELECT * FROM schedules WHERE id=%s AND leta_id=%s",
                (schedule_id, leta_id),
            )
            if saved["deleted_at"] is not None or saved["paused"]:
                return None
            await self._agent_gate(cursor, leta_id, saved["target_agent_id"])
            return saved

    async def calendar_schedules(
        self,
        leta_id: UUID,
        *,
        target_agent_id: UUID | None = None,
        box_id: UUID | None = None,
        schedule_id: UUID | None = None,
    ) -> list[Row]:
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT * FROM schedules WHERE leta_id=%s AND deleted_at IS NULL "
                "AND (%s::uuid IS NULL OR target_agent_id=%s) "
                "AND (%s::uuid IS NULL OR box_id=%s) "
                "AND (%s::uuid IS NULL OR id=%s) ORDER BY id LIMIT 33",
                (
                    leta_id,
                    target_agent_id,
                    target_agent_id,
                    box_id,
                    box_id,
                    schedule_id,
                    schedule_id,
                ),
            )

    async def reserve_api_request(
        self,
        actor_id: UUID,
        key: UUID,
        request_hash: str,
        *,
        resource_id: UUID | None = None,
    ) -> Row:
        async with self.transaction() as cursor:
            await cursor.execute(
                "DELETE FROM idempotency_keys WHERE (actor_id,request_key) IN "
                "(SELECT actor_id,request_key FROM idempotency_keys "
                "WHERE expires_at<=clock_timestamp() ORDER BY expires_at LIMIT 100)"
            )
            await cursor.execute(
                "INSERT INTO "
                "idempotency_keys(actor_id,request_key,request_hash,resource_id) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT(actor_id,request_key) DO NOTHING",
                (actor_id, key, request_hash, resource_id or uuid7()),
            )
            saved = await one(
                cursor,
                "SELECT * FROM idempotency_keys WHERE actor_id=%s "
                "AND request_key=%s FOR UPDATE",
                (actor_id, key),
            )
            same(saved, {"request_hash": request_hash})
            if resource_id is not None:
                same(saved, {"resource_id": resource_id})
            return saved

    async def complete_api_request(self, actor_id: UUID, key: UUID):
        async with self.transaction() as cursor:
            await cursor.execute(
                "UPDATE idempotency_keys SET expires_at=COALESCE(expires_at,"
                "clock_timestamp()+interval '24 hours') WHERE actor_id=%s "
                "AND request_key=%s",
                (actor_id, key),
            )

    async def api_roots(
        self,
        user_id: UUID,
        *,
        workspace_id: UUID | None = None,
        status: str | None = None,
        after: UUID | None = None,
        limit=20,
    ):
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT * FROM agents WHERE kind='leta' "
                "AND created_by_user_id=%s AND (%s::uuid IS NULL OR workspace_id=%s) "
                "AND (%s::text IS NULL OR status=%s) AND (%s::uuid IS NULL OR id>%s) "
                "ORDER BY id LIMIT %s",
                (
                    user_id,
                    workspace_id,
                    workspace_id,
                    status,
                    status,
                    after,
                    after,
                    page_limit(limit),
                ),
            )

    async def api_agents(self, leta_id: UUID, *, after: UUID | None = None, limit=20):
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT a.*,r.id AS run_id,r.status AS run_status, "
                "a.inbox_seq-COALESCE((SELECT max(inbox_cursor) FROM runs WHERE "
                "agent_id=a.id),0) AS pending_input_count "
                "FROM agents a LEFT JOIN LATERAL (SELECT id,status,inbox_cursor "
                "FROM runs "
                "WHERE agent_id=a.id ORDER BY started_at DESC,id DESC LIMIT 1) r "
                "ON true "
                "WHERE a.leta_id=%s AND (%s::uuid IS NULL OR a.id>%s) ORDER BY "
                "a.id LIMIT %s",
                (leta_id, after, after, page_limit(limit)),
            )

    async def api_messages(
        self, leta_id: UUID, user_id: UUID, *, after: TimeCursor | None = None, limit=20
    ):
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT * FROM messages WHERE leta_id=%s AND "
                "((recipient_agent_id=%s AND source_type='owner' AND source_id=%s) "
                "OR (sender_agent_id=%s AND recipient_user_id=%s)) "
                "AND (%s::timestamptz IS NULL OR (created_at,id)>(%s,%s)) "
                "ORDER BY created_at,id LIMIT %s",
                (
                    leta_id,
                    leta_id,
                    str(user_id),
                    leta_id,
                    user_id,
                    after.at if after else None,
                    after.at if after else None,
                    after.id if after else None,
                    page_limit(limit),
                ),
            )

    async def bootstrap_history(self, leta_id: UUID, *, limit=100):
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT l.* FROM activity_log l JOIN agents a ON a.id=l.agent_id "
                "WHERE a.leta_id=%s ORDER BY l.created_at DESC,l.id DESC LIMIT %s",
                (leta_id, page_limit(limit)),
            )

    async def api_run(self, leta_id: UUID, run_id: UUID):
        async with self.transaction() as cursor:
            return await one(
                cursor,
                "SELECT r.* FROM runs r JOIN agents a ON a.id=r.agent_id "
                "WHERE r.id=%s AND a.leta_id=%s",
                (run_id, leta_id),
            )

    async def addressed_requests(
        self,
        user_id: UUID,
        *,
        after: TimeCursor | None = None,
        status: str | None = None,
        limit=20,
    ):
        async with self.transaction() as cursor:
            return await rows(
                cursor,
                "SELECT h.*,a.workspace_id,a.created_by_user_id,a.name AS leta_name,"
                "r.name AS requester_name,r.box_id,b.name AS box_name FROM "
                "hitl_requests h "
                "JOIN agents a ON a.id=h.leta_id JOIN agents r ON "
                "r.id=h.requester_agent_id "
                "LEFT JOIN boxes b ON b.id=r.box_id WHERE h.approver_user_id=%s "
                "AND (%s::text IS NULL OR h.status=%s) "
                "AND (%s::timestamptz IS NULL OR (h.created_at,h.id)>(%s,%s)) "
                "ORDER BY h.created_at,h.id LIMIT %s",
                (
                    user_id,
                    status,
                    status,
                    after.at if after else None,
                    after.at if after else None,
                    after.id if after else None,
                    page_limit(limit),
                ),
            )

    async def addressed_request(self, user_id: UUID, request_id: UUID):
        async with self.transaction() as cursor:
            return await one(
                cursor,
                "SELECT h.*,a.workspace_id,a.created_by_user_id,a.name AS leta_name,"
                "r.name AS requester_name,r.box_id,b.name AS box_name FROM "
                "hitl_requests h "
                "JOIN agents a ON a.id=h.leta_id JOIN agents r ON "
                "r.id=h.requester_agent_id "
                "LEFT JOIN boxes b ON b.id=r.box_id WHERE h.id=%s AND "
                "h.approver_user_id=%s",
                (request_id, user_id),
            )
