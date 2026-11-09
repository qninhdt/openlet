from uuid import uuid7

import pytest
from openlet.rpc import Actor
from openlet_api.workspace.v1 import workspace_pb2 as pb

from leta.filesystem.workspace import discover_mounts


class ScopePages:
    def __init__(self, actor, pages):
        self.actor, self.pages, self.calls = actor, pages, []

    async def list_accessible_scopes(self, workspace_id, *, actor, limit, cursor):
        assert actor == self.actor
        self.calls.append(cursor)
        return self.pages[len(self.calls) - 1]


async def test_mount_discovery_pages_and_inherited_box_home():
    actor = Actor("leta", uuid7())
    workspace, fs, home, shared, personal, user, box = [str(uuid7()) for _ in range(7)]
    roots = [str(uuid7()) for _ in range(3)]
    pages = [
        pb.ListAccessibleScopesResponse(
            filesystem_id=fs,
            next_cursor="page-2",
            items=[
                pb.AccessibleScope(
                    id=home,
                    root_id=roots[0],
                    kind="home",
                    rights=pb.ScopeRights(
                        read_metadata=True, read_content=True, write=True
                    ),
                )
            ],
        ),
        pb.ListAccessibleScopesResponse(
            filesystem_id=fs,
            items=[
                pb.AccessibleScope(
                    id=shared,
                    root_id=roots[1],
                    kind="shared",
                    rights=pb.ScopeRights(
                        read_metadata=True, read_content=True, write=True
                    ),
                ),
                pb.AccessibleScope(
                    id=personal,
                    root_id=roots[2],
                    kind="personal",
                    owner={"id": user},
                    rights=pb.ScopeRights(read_metadata=True, read_content=True),
                ),
            ],
        ),
    ]
    client = ScopePages(actor, pages)
    mounts = await discover_mounts(client, workspace, actor, home, box)
    assert client.calls == [None, "page-2"]
    assert [(m.prefix, m.root_id, m.writable) for m in mounts] == [
        ("/home", box, True),
        ("/shared", roots[1], True),
        ("/users/" + user, roots[2], False),
    ]


async def test_mount_discovery_requires_current_home_and_consistent_filesystem():
    actor = Actor("leta", uuid7())
    client = ScopePages(
        actor, [pb.ListAccessibleScopesResponse(filesystem_id=str(uuid7()))]
    )
    with pytest.raises(PermissionError, match="home"):
        await discover_mounts(client, uuid7(), actor, uuid7())
    client = ScopePages(
        actor,
        [
            pb.ListAccessibleScopesResponse(
                filesystem_id=str(uuid7()), next_cursor="next"
            ),
            pb.ListAccessibleScopesResponse(filesystem_id=str(uuid7())),
        ],
    )
    with pytest.raises(ValueError, match="filesystem changed"):
        await discover_mounts(client, uuid7(), actor, uuid7())
