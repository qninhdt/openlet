"""Render the development deployment's private native configuration."""

import argparse
import json
import os
import secrets
from pathlib import Path
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
DATABASES = ("account", "workspace", "letfs", "temporal", "temporal_visibility")
GENERATED = (
    "postgres_password",
    "gateway_token",
    "workspace_service_token",
    "processor_service_token",
    "qdrant_api_key",
)
PROVIDED = {
    "clerk_secret_key": "CLERK_SECRET_KEY",
    "s3_access_key_id": "S3_ACCESS_KEY_ID",
    "s3_secret_access_key": "S3_SECRET_ACCESS_KEY",
    "openrouter_api_key": "OPENROUTER_API_KEY",
}


def endpoint(value: str, label: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "?" in value
        or "#" in value
    ):
        raise ValueError(
            f"{label} must be an HTTPS URL without userinfo/query/fragment"
        )
    try:
        _ = parsed.port
    except ValueError:
        raise ValueError(f"{label} has an invalid port") from None
    if any(c.isspace() for c in value):
        raise ValueError(f"{label} must not contain whitespace")
    return value


def private_write(path: Path, value: str) -> None:
    if path.is_symlink():
        raise ValueError("refusing a symlink in generated configuration")
    if path.exists():
        path.chmod(0o600)
    path.write_text(value)
    # The private parent protects host access; nonroot containers read mounted files.
    path.chmod(0o644)


def configure(state: Path, environment: dict[str, str]) -> None:
    issuer = endpoint(environment.get("JWT_ISSUER", ""), "JWT_ISSUER")
    jwks = endpoint(environment.get("JWKS_URL", ""), "JWKS_URL")
    endpoint(environment.get("S3_ENDPOINT", ""), "S3_ENDPOINT")
    for key in ("S3_SIGNING_ENDPOINT", "CLERK_API_URL", "OPENROUTER_URL"):
        if environment.get(key):
            endpoint(environment[key], key)
    audience = environment.get("JWT_AUDIENCE", "")
    if not audience or any(c.isspace() for c in audience):
        raise ValueError("JWT_AUDIENCE must be nonempty without whitespace")
    rate, burst = (
        int(environment.get("GATEWAY_RATE", "100")),
        int(environment.get("GATEWAY_BURST", "200")),
    )
    if not 0 < rate <= burst <= 4294967295:
        raise ValueError("require 0 < GATEWAY_RATE <= GATEWAY_BURST")
    if state.is_symlink() or (state / "secrets").is_symlink():
        raise ValueError("refusing a symlinked state directory")
    marker = state / "runtime.json"
    if marker.exists() and json.loads(marker.read_text()) != {
        "kind": "development",
        "worktree": str(ROOT),
    }:
        raise ValueError("state belongs to another environment/worktree")
    if (state / "environment.json").exists() or state.name == "api-e2e":
        raise ValueError("development bootstrap cannot use API E2E state")
    existing: dict[str, str] = {}
    for name in (*GENERATED, *(f"{db}_db_password" for db in DATABASES), *PROVIDED):
        path = state / "secrets" / name
        if path.is_symlink():
            raise ValueError("refusing a symlinked secret")
        if path.exists():
            value = path.read_text().strip()
        elif name in PROVIDED:
            value = environment.get(PROVIDED[name], "").strip()
        else:
            value = secrets.token_urlsafe(32)
        if not value or any(c.isspace() for c in value):
            raise ValueError(
                f"{PROVIDED.get(name, name)} must be configured without whitespace"
            )
        if name not in PROVIDED and len(value) < 32:
            raise ValueError(
                f"existing {name} is invalid; explicit rotation is required"
            )
        existing[name] = value
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    (state / "secrets").mkdir(exist_ok=True, mode=0o700)
    (state / "secrets").chmod(0o700)
    for name, value in existing.items():
        private_write(state / "secrets" / name, value)
    for app in DATABASES[:3]:
        password = quote(existing[f"{app}_db_password"], safe="")
        private_write(
            state / "secrets" / f"{app}_database_url",
            f"postgres://openlet_{app}:{password}@postgres:5432/openlet_{app}?sslmode=disable",
        )
    sql = "\\set ON_ERROR_STOP on\n"
    for db in DATABASES:
        role = f"openlet_{db}"
        password = existing[f"{db}_db_password"].replace("'", "''")
        sql += f"CREATE ROLE {role} LOGIN PASSWORD '{password}';\n"
        sql += f"ALTER ROLE {role} SET statement_timeout='15s';\nALTER ROLE {role} SET lock_timeout='5s';\n"
        sql += f"CREATE DATABASE {role} OWNER {role};\nREVOKE ALL ON DATABASE {role} FROM PUBLIC;\n"
    private_write(state / "init.sql", sql)
    temporal = json.loads((ROOT / "infra/config/temporal.template.json").read_text())
    for store, db in (("default", "temporal"), ("visibility", "temporal_visibility")):
        temporal["persistence"]["datastores"][store]["sql"]["password"] = existing[
            f"{db}_db_password"
        ]
    private_write(state / "temporal.json", json.dumps(temporal))
    envoy = json.loads((ROOT / "infra/config/envoy.template.json").read_text())
    manager = envoy["static_resources"]["listeners"][0]["filter_chains"][0]["filters"][
        0
    ]["typed_config"]
    manager["route_config"]["virtual_hosts"][0]["request_headers_to_add"][0]["header"][
        "value"
    ] = existing["gateway_token"]
    jwt = next(
        f
        for f in manager["http_filters"]
        if f["name"] == "envoy.filters.http.jwt_authn"
    )["typed_config"]["providers"]["clerk"]
    jwt.update(issuer=issuer, audiences=[audience])
    jwt["remote_jwks"]["http_uri"]["uri"] = jwks
    parsed = urlsplit(jwks)
    cluster = next(
        c for c in envoy["static_resources"]["clusters"] if c["name"] == "jwks"
    )
    cluster["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"][
        "address"
    ]["socket_address"] = {"address": parsed.hostname, "port_value": parsed.port or 443}
    cluster["transport_socket"] = {
        "name": "envoy.transport_sockets.tls",
        "typed_config": {
            "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
            "sni": parsed.hostname,
            "common_tls_context": {
                "validation_context": {
                    "trusted_ca": {"filename": "/etc/ssl/certs/ca-certificates.crt"},
                    "match_typed_subject_alt_names": [
                        {"san_type": "DNS", "matcher": {"exact": parsed.hostname}}
                    ],
                }
            },
        },
    }
    limiter = next(
        f
        for f in manager["http_filters"]
        if f["name"] == "envoy.filters.http.local_ratelimit"
    )["typed_config"]
    limiter["token_bucket"].update(max_tokens=burst, tokens_per_fill=rate)
    private_write(state / "envoy.json", json.dumps(envoy))
    private_write(marker, json.dumps({"kind": "development", "worktree": str(ROOT)}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=ROOT / ".local")
    args = parser.parse_args()
    try:
        configure(args.state.absolute(), dict(os.environ))
    except (ValueError, OSError) as error:
        parser.exit(1, f"Bootstrap failed: {error}\n")
    print("Private configuration ready; existing credentials preserved.")


if __name__ == "__main__":
    main()
