import hmac
from collections.abc import Mapping, Sequence
from uuid import UUID

from openlet.rpc import Actor, Principal


class GatewayAuthenticationError(ValueError):
    pass


def authenticate_gateway(
    headers: Mapping[str, str] | Mapping[str, Sequence[str]],
    token: str,
    *,
    bootstrap: bool = False,
) -> Principal:
    normalized: dict[str, list[str]] = {}
    for key, value in headers.items():
        normalized.setdefault(key.lower(), []).extend(
            [value] if isinstance(value, str) else value
        )
    gateway = normalized.get("x-gateway-token", [])
    subjects = normalized.get("x-clerk-sub", [])
    actors = normalized.get("x-openlet-user-id", [])
    if len(gateway) != 1 or not token or not hmac.compare_digest(gateway[0], token):
        raise GatewayAuthenticationError("gateway authentication required")
    if len(subjects) != 1 or not subjects[0]:
        raise GatewayAuthenticationError("verified subject required")
    if any(
        normalized.get(key)
        for key in ("x-openlet-leta-id", "x-openlet-account-id", "x-openlet-service")
    ):
        raise GatewayAuthenticationError("gateway authentication required")
    if len(actors) > 1:
        raise GatewayAuthenticationError("refresh an onboarded session")
    if bootstrap:
        return Principal("gateway", subject=subjects[0], gateway=True)
    if len(actors) != 1:
        raise GatewayAuthenticationError("refresh an onboarded session")
    try:
        actor = UUID(actors[0])
    except ValueError as error:
        raise GatewayAuthenticationError("refresh an onboarded session") from error
    if actor.int == 0:
        raise GatewayAuthenticationError("refresh an onboarded session")
    return Principal("gateway", Actor("user", actor), subjects[0], True)
