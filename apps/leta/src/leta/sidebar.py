"""Personal agent organization within a workspace, independent of agent configuration."""

import json
from typing import cast
from uuid import UUID

from openlet_sdk.config import JSON
from pydantic import Field, model_validator

from .agents import Input
from .db import Pool


class Folder(Input):
    id: UUID
    name: str = Field(min_length=1, max_length=80)
    parent_id: UUID | None = None


class Layout(Input):
    folders: list[Folder] = Field(default_factory=list[Folder], max_length=100)
    assignments: dict[UUID, UUID] = Field(default_factory=dict[UUID, UUID], max_length=1000)
    pins: list[UUID] = Field(default_factory=list[UUID], max_length=1000)
    order: list[UUID] = Field(default_factory=list[UUID], max_length=1000)
    collapsed: list[UUID] = Field(default_factory=list[UUID], max_length=100)

    @model_validator(mode="after")
    def tree(self) -> "Layout":
        folders = {f.id: f for f in self.folders}
        if len(folders) != len(self.folders) or any(
            not f.name.strip() for f in self.folders
        ):
            raise ValueError("folder IDs must be unique and names cannot be blank")
        for folder in self.folders:
            seen = {folder.id}
            parent = folder.parent_id
            while parent is not None:
                if parent in seen or parent not in folders or len(seen) >= 3:
                    raise ValueError("folders must form a tree of at most three levels")
                seen.add(parent)
                parent = folders[parent].parent_id
        if (
            not set(self.assignments.values()) <= folders.keys()
            or not set(self.collapsed) <= folders.keys()
        ):
            raise ValueError("folder not found")
        if len(set(self.pins)) != len(self.pins) or len(set(self.order)) != len(
            self.order
        ):
            raise ValueError("agent order cannot contain duplicates")
        return self


class Update(Input):
    revision: int = Field(ge=0)
    layout: Layout


class StaleLayout(Exception):
    pass


async def read(db: Pool, workspace: UUID, user: UUID) -> dict[str, JSON]:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT revision,layout FROM agent_sidebar_layouts WHERE workspace_id=%s AND user_id=%s",
                (workspace, user),
            )
        ).fetchone()
    return {
        "revision": cast(int, row["revision"]) if row else 0,
        "layout": cast(JSON, row["layout"])
        if row
        else Layout().model_dump(mode="json"),
    }


async def save(db: Pool, workspace: UUID, user: UUID, body: Update) -> dict[str, JSON]:
    async with db.connection() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO agent_sidebar_layouts(workspace_id,user_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
            (workspace, user),
        )
        row = await (
            await conn.execute(
                """UPDATE agent_sidebar_layouts SET layout=%s::jsonb,revision=revision+1
            WHERE workspace_id=%s AND user_id=%s AND revision=%s RETURNING revision,layout""",
                (
                    json.dumps(body.layout.model_dump(mode="json")),
                    workspace,
                    user,
                    body.revision,
                ),
            )
        ).fetchone()
        if row is None:
            raise StaleLayout()
    return {"revision": cast(int, row["revision"]), "layout": cast(JSON, row["layout"])}
