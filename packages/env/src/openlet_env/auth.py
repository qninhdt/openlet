"""Project-local RS256 keypair, JWKS generation, and <1ms JWT signing."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal, TypedDict
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pydantic import BaseModel, ConfigDict

from openlet_env.models import SigningKeyMeta

if TYPE_CHECKING:
    from pathlib import Path

    from openlet_sdk.types import MutableJsonObject


class _RsaPublicJwk(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kty: Literal["RSA"]
    n: str
    e: str


class RsaJwk(TypedDict):
    """RSA public JSON Web Key entry."""

    kty: Literal["RSA"]
    n: str
    e: str
    kid: str
    alg: Literal["RS256"]
    use: Literal["sig"]


class Jwks(TypedDict):
    """JWKS document containing active signing keys."""

    keys: list[RsaJwk]


class LocalAuth:
    """Manages a per-project RS256 signing key and issues Openlet-compatible JWTs."""

    def __init__(
        self,
        *,
        private_pem: bytes,
        kid: str,
        issuer: str = "http://wiremock:8080",
        audience: str = "openlet",
        user_id_claim: str = "openlet_user_id",
    ) -> None:
        self._private_pem = private_pem
        loaded_key = serialization.load_pem_private_key(private_pem, password=None)
        if not isinstance(loaded_key, rsa.RSAPrivateKey):
            raise TypeError("signing key must be an RSA private key")
        self._private_key = loaded_key
        self.kid = kid
        self.issuer = issuer
        self.audience = audience
        self.user_id_claim = user_id_claim

    @classmethod
    def load_or_create(
        cls,
        directory: Path,
        *,
        issuer: str = "http://wiremock:8080",
        audience: str = "openlet",
        user_id_claim: str = "openlet_user_id",
    ) -> LocalAuth:
        """Load an existing RS256 signing keypair from ``directory`` or generate one."""
        pem_path = directory / "signing-key.pem"
        meta_path = directory / "signing-key.json"
        if pem_path.is_file() and meta_path.is_file():
            meta = SigningKeyMeta.model_validate_json(meta_path.read_text("utf-8"))
            return cls(
                private_pem=pem_path.read_bytes(),
                kid=meta.kid,
                issuer=issuer,
                audience=audience,
                user_id_claim=user_id_claim,
            )
        directory.mkdir(parents=True, exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        kid = str(uuid4())
        pem_path.write_bytes(pem)
        pem_path.chmod(0o600)
        meta_path.write_text(
            SigningKeyMeta(kid=kid).model_dump_json() + "\n", encoding="utf-8"
        )
        meta_path.chmod(0o600)
        return cls(
            private_pem=pem,
            kid=kid,
            issuer=issuer,
            audience=audience,
            user_id_claim=user_id_claim,
        )

    def jwks(self) -> Jwks:
        """Return the public JWKS payload for the active signing key."""
        public_key = self._private_key.public_key()
        raw_jwk = _RsaPublicJwk.model_validate(
            RSAAlgorithm.to_jwk(public_key, as_dict=True)
        )
        jwk: RsaJwk = {
            "kty": raw_jwk.kty,
            "n": raw_jwk.n,
            "e": raw_jwk.e,
            "kid": self.kid,
            "alg": "RS256",
            "use": "sig",
        }
        return {"keys": [jwk]}

    def sign(
        self,
        subject: str,
        user_id: str | None = None,
        *,
        ttl_seconds: int = 3600,
    ) -> str:
        """Sign an RS256 JWT for ``subject`` with an optional Openlet user ID claim."""
        now = int(time.time())
        payload: MutableJsonObject = {
            "sub": subject,
            "iss": self.issuer,
            "aud": self.audience,
            "iat": now,
            "exp": now + ttl_seconds,
        }
        if user_id:
            payload["public_metadata"] = {self.user_id_claim: user_id}
        return jwt.encode(
            payload,
            self._private_pem,
            algorithm="RS256",
            headers={"kid": self.kid},
        )
