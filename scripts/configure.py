#!/usr/bin/env python3
"""Render native infrastructure configuration; secrets stay under ignored .local/."""

import argparse
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlparse


SOURCE_ROOT = Path(__file__).resolve().parents[1]
ROOT = SOURCE_ROOT
DATABASE_SERVICES = ("user", "workspace", "letfs")
SECRET_NAMES = (
    "postgres_password",
    "gateway_token",
    "user_service_token",
    "workspace_service_token",
    "processor_service_token",
    "user_db_password",
    "workspace_db_password",
    "letfs_db_password",
    "temporal_db_password",
    "temporal_visibility_db_password",
)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.chmod(0o600)
    path.write_text(value)
    path.chmod(0o444)


def load_template(relative_path):
    return json.loads((SOURCE_ROOT / relative_path).read_text())


def tls_transport_socket(host):
    return {
        "name": "envoy.transport_sockets.tls",
        "typed_config": {
            "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
            "sni": host,
            "common_tls_context": {
                "validation_context": {
                    "trusted_ca": {
                        "filename": "/etc/ssl/certs/ca-certificates.crt"
                    },
                    "match_typed_subject_alt_names": [
                        {
                            "san_type": "DNS",
                            "matcher": {"exact": host},
                        }
                    ],
                }
            },
        },
    }


def envoy_config(issuer, jwks_url, audience, gateway_token, rate, burst):
    parsed_url = urlparse(jwks_url)
    if (
        parsed_url.scheme not in ("https", "http")
        or not parsed_url.hostname
        or parsed_url.username
        or parsed_url.password
    ):
        raise ValueError("invalid JWKS_URL")

    config = load_template("deploy/envoy/openlet.template.json")
    resources = config["static_resources"]
    clusters = {cluster["name"]: cluster for cluster in resources["clusters"]}
    jwks_cluster = clusters["jwks"]
    jwks_address = jwks_cluster["load_assignment"]["endpoints"][0]["lb_endpoints"][
        0
    ]["endpoint"]["address"]["socket_address"]
    jwks_address["address"] = parsed_url.hostname
    jwks_address["port_value"] = parsed_url.port or (
        443 if parsed_url.scheme == "https" else 80
    )
    if parsed_url.scheme == "https":
        jwks_cluster["transport_socket"] = tls_transport_socket(parsed_url.hostname)

    connection_manager = resources["listeners"][0]["filter_chains"][0]["filters"][
        0
    ]["typed_config"]
    virtual_host = connection_manager["route_config"]["virtual_hosts"][0]
    virtual_host["request_headers_to_add"][0]["header"]["value"] = gateway_token

    filters = {
        item["name"]: item["typed_config"]
        for item in connection_manager["http_filters"]
    }
    jwt_provider = filters["envoy.filters.http.jwt_authn"]["providers"]["clerk"]
    jwt_provider["issuer"] = issuer
    jwt_provider["audiences"] = [audience]
    jwt_provider["remote_jwks"]["http_uri"]["uri"] = jwks_url

    token_bucket = filters["envoy.filters.http.local_ratelimit"]["token_bucket"]
    token_bucket["max_tokens"] = burst
    token_bucket["tokens_per_fill"] = rate
    return config


def temporal_config(secret_dir):
    config = load_template("deploy/temporal/openlet.template.json")
    datastores = config["persistence"]["datastores"]
    for label, scope in (
        ("default", "temporal"),
        ("visibility", "temporal_visibility"),
    ):
        password_path = secret_dir / f"{scope}_db_password"
        datastores[label]["sql"]["password"] = password_path.read_text().strip()
    return config


def create_secrets(secret_dir):
    for name in SECRET_NAMES:
        path = secret_dir / name
        if not path.exists():
            write(path, secrets.token_urlsafe(32))


def write_database_urls(secret_dir):
    for service in DATABASE_SERVICES:
        password = (secret_dir / f"{service}_db_password").read_text().strip()
        database_url = (
            f"postgres://openlet_{service}:{password}"
            f"@postgres:5432/openlet_{service}?sslmode=disable"
        )
        write(secret_dir / f"{service}_database_url", database_url)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    base = ROOT / ".local"
    base.mkdir(mode=0o700, exist_ok=True)
    local = base / "test" if args.test else base
    local.mkdir(mode=0o700, exist_ok=True)
    local.chmod(0o700)

    secret_dir = local / "secrets"
    secret_dir.mkdir(mode=0o700, exist_ok=True)
    create_secrets(secret_dir)
    write_database_urls(secret_dir)

    issuer = "http://issuer:8080" if args.test else os.environ.get("JWT_ISSUER", "")
    jwks_url = "http://issuer:8080/.well-known/jwks.json" if args.test else os.environ.get("JWKS_URL", "")
    audience = "openlet-test" if args.test else os.environ.get("JWT_AUDIENCE", "")
    if not issuer or not jwks_url or not audience:
        parser.error(
            "set JWT_ISSUER, JWKS_URL and JWT_AUDIENCE "
            "(or use --test for isolated tests)"
        )
    parsed_issuer = urlparse(issuer)
    if parsed_issuer.scheme not in ("http", "https") or not parsed_issuer.hostname or parsed_issuer.username or parsed_issuer.password:
        parser.error("invalid JWT_ISSUER")
    if not args.test and (
        not issuer.startswith("https://") or not jwks_url.startswith("https://")
    ):
        parser.error("external JWT issuer and JWKS require HTTPS")
    clerk_secret=secret_dir / "clerk_secret_key"
    if args.test:
        if not clerk_secret.exists():
            write(clerk_secret,secrets.token_urlsafe(32))
    elif value:=os.environ.get("CLERK_SECRET_KEY"):
        write(clerk_secret,value)
    elif not clerk_secret.exists():
        parser.error("set CLERK_SECRET_KEY for the development Clerk instance")

    if not args.test:
        endpoint=urlparse(os.environ.get("S3_ENDPOINT",""))
        if endpoint.scheme!="https" or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            parser.error("set an HTTPS S3_ENDPOINT for the selected private bucket")
        signing_endpoint=urlparse(os.environ.get("S3_SIGNING_ENDPOINT", os.environ.get("S3_ENDPOINT", "")))
        if signing_endpoint.scheme!="https" or not signing_endpoint.hostname or signing_endpoint.username or signing_endpoint.password or signing_endpoint.query or signing_endpoint.fragment:
            parser.error("S3_SIGNING_ENDPOINT requires HTTPS and no credentials, query or fragment")
    for name,env_name in [("s3_access_key_id","S3_ACCESS_KEY_ID"),("s3_secret_access_key","S3_SECRET_ACCESS_KEY")]:
        path=secret_dir/name
        if args.test:
            if not path.exists(): write(path,secrets.token_urlsafe(32))
        elif value:=os.environ.get(env_name): write(path,value)
        elif not path.exists(): parser.error(f"set {env_name} for the selected private S3 bucket")
    if args.test:
        write(local/"seaweedfs.json",json.dumps({"identities":[{"name":"openlet-test","credentials":[{"accessKey":(secret_dir/"s3_access_key_id").read_text().strip(),"secretKey":(secret_dir/"s3_secret_access_key").read_text().strip()}],"actions":["Read","Write","List","Tagging","Admin"]}]}))

    rate = int(os.environ.get("GATEWAY_RATE", "100"))
    burst = int(os.environ.get("GATEWAY_BURST", "200"))
    if not 0 < rate <= burst:
        parser.error("require 0 < GATEWAY_RATE <= GATEWAY_BURST")

    gateway_token = (secret_dir / "gateway_token").read_text().strip()
    envoy = envoy_config(issuer, jwks_url, audience, gateway_token, rate, burst)
    write(local / "envoy.json", json.dumps(envoy, indent=2))
    write(local / "temporal.yaml", json.dumps(temporal_config(secret_dir), indent=2))
    print("Rendered private configuration under .local; no secret values printed.")


if __name__ == "__main__":
    main()
