import base64
import hashlib
import hmac

from openlet_sdk.centrifugo import sign_centrifugo_token
from pydantic import TypeAdapter

_CLAIMS_ADAPTER = TypeAdapter(dict[str, str | int])


def _decode_part(part: str) -> dict[str, str | int]:
    padded = part + "=" * (-len(part) % 4)
    return _CLAIMS_ADAPTER.validate_json(base64.urlsafe_b64decode(padded))


def test_sign_centrifugo_token_connect_and_subscription() -> None:
    secret = "test-secret"
    tok, exp = sign_centrifugo_token(secret, "u-1", ttl_seconds=600)
    parts = tok.split(".")
    assert len(parts) == 3
    sig = hmac.new(
        secret.encode(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256
    ).digest()
    assert parts[2] == base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")
    claims = _decode_part(parts[1])
    assert claims["sub"] == "u-1"
    assert claims["exp"] == int(exp.timestamp())
    assert "channel" not in claims

    sub_tok, _ = sign_centrifugo_token(
        secret, "u-1", channel="leta:activity:l-1", ttl_seconds=300
    )
    sub_claims = _decode_part(sub_tok.split(".")[1])
    assert sub_claims["channel"] == "leta:activity:l-1"
