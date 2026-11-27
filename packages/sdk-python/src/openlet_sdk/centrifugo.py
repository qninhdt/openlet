"""Centrifugo JWT token signing helpers."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

_JWT_HS256_HEADER = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def sign_centrifugo_token(
    secret: str,
    user_id: str,
    *,
    channel: str = "",
    ttl_seconds: int = 3600,
) -> tuple[str, datetime]:
    """Sign an HS256 JWT for Centrifugo v6 connection or channel subscription."""
    if not secret:
        raise ValueError("centrifugo token secret is required")
    if not user_id:
        raise ValueError("user_id is required")
    if ttl_seconds <= 0:
        ttl_seconds = 3600
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    claims: dict[str, str | int] = {
        "sub": user_id,
        "exp": int(expires_at.timestamp()),
    }
    if channel:
        claims["channel"] = channel
    payload = json.dumps(claims, separators=(",", ":")).encode("utf-8")
    signing_input = f"{_JWT_HS256_HEADER}.{_b64url(payload)}"
    sig = hmac.new(
        secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64url(sig)}", expires_at
