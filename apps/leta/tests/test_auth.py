from uuid import uuid4

import pytest
from fastapi import HTTPException
from leta.auth import Actor, human
from starlette.requests import Request


def test_human_forwards_consistency_without_changing_actor_identity() -> None:
    user = uuid4()
    actor = human(
        Request(
            {
                "type": "http",
                "headers": [
                    (b"x-openlet-user-id", str(user).encode()),
                    (b"x-openlet-zed-token", b"creation-revision"),
                ],
            }
        )
    )
    assert actor == Actor("user", user)
    assert actor.metadata == (
        ("x-openlet-user-id", str(user)),
        ("x-openlet-zed-token", "creation-revision"),
    )
    assert Actor("user", user).metadata == (("x-openlet-user-id", str(user)),)


@pytest.mark.parametrize(
    "headers",
    [
        [(b"x-openlet-zed-token", b"creation-revision")],
        [(b"x-openlet-user-id", b"invalid")],
        [(b"x-openlet-user-id", str(uuid4()).encode())] * 2,
        [
            (b"x-openlet-user-id", str(uuid4()).encode()),
            (b"x-openlet-agent-id", str(uuid4()).encode()),
        ],
    ],
)
def test_consistency_never_substitutes_for_one_verified_user(
    headers: list[tuple[bytes, bytes]],
) -> None:
    with pytest.raises(HTTPException) as error:
        human(Request({"type": "http", "headers": headers}))
    assert error.value.status_code == 401
