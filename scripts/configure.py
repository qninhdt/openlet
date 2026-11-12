"""Render private native infrastructure outputs from OPENLET_CONFIG."""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote, urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load():
    with open(os.environ["OPENLET_CONFIG"]) as stream:
        return yaml.safe_load(stream)


def secret(value):
    if not isinstance(value, str) or not (value.startswith("${") and value.endswith("}")):
        raise ValueError("secret must be a whole ${ENV_VARIABLE} scalar")
    result = os.environ[value[2:-1]]
    if not result:
        raise ValueError(f"empty required environment variable {value[2:-1]}")
    return result


def render(name, values):
    text = (ROOT / "infra/config" / f"{name}.template.yaml").read_text()
    for key, value in values.items():
        text = text.replace(f"@{key}@", json.dumps(value))
    return yaml.safe_load(text)


def configure(output, test=False):
    c = load()
    dep, svc, deploy = c["dependencies"], c["services"], c["deployment"]
    pg, temporal = dep["postgres"], deploy["temporal"]
    if pg["sslmode"] != "disable":
        raise ValueError("Compose PostgreSQL uses private-network plaintext")
    host, port = svc["gateway"]["http_listen"].rsplit(":", 1)
    ph, pp = svc["platform"]["grpc_target"].rsplit(":", 1)
    fh, fp = svc["letfs"]["grpc_target"].rsplit(":", 1)
    auth = c["auth"]["clerk"]
    jwks = urlparse(auth["jwks_url"])
    if jwks.scheme not in ("http", "https") or not jwks.hostname:
        raise ValueError("JWKS URL must be HTTP(S)")
    envoy = render("envoy", dict(LISTEN_HOST=host, LISTEN_PORT=int(port),
        PLATFORM_HOST=ph, PLATFORM_PORT=int(pp), LETFS_HOST=fh, LETFS_PORT=int(fp),
        ISSUER=auth["issuer"], AUDIENCE=auth["audience"], JWKS_URL=auth["jwks_url"],
        JWKS_HOST=jwks.hostname, JWKS_PORT=jwks.port or (443 if jwks.scheme == "https" else 80)))
    if jwks.scheme == "https":
        envoy["static_resources"]["clusters"][2]["transport_socket"] = {
            "name": "envoy.transport_sockets.tls", "typed_config": {
                "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
                "sni": jwks.hostname, "common_tls_context": {"validation_context": {
                    "trusted_ca": {"filename": "/etc/ssl/certs/ca-certificates.crt"},
                    "match_typed_subject_alt_names": [{"san_type": "DNS", "matcher": {"exact": jwks.hostname}}]}}}}
    native = render("temporal", dict(POSTGRES=f'{pg["host"]}:{pg["port"]}',
        DATABASE=temporal["database"]["name"], VISIBILITY_DATABASE=temporal["visibility_database"],
        USER=temporal["database"]["user"], PASSWORD=secret(temporal["database"]["password"])))
    db = deploy["spicedb"]["database"]
    uri = f'postgres://{quote(db["user"], safe="")}:{quote(secret(db["password"]), safe="")}@{pg["host"]}:{pg["port"]}/{db["name"]}?sslmode={pg["sslmode"]}'
    graph_env = {"SPICEDB_DATASTORE_CONN_URI": uri, "SPICEDB_GRPC_PRESHARED_KEY": secret(dep["spicedb"]["key"])}
    sql_env = {"SQL_HOST": pg["host"], "SQL_PORT": str(pg["port"]),
        "SQL_USER": temporal["database"]["user"], "SQL_PASSWORD": secret(temporal["database"]["password"]),
        "SQL_PLUGIN": "postgres12"}
    runtime = {"services": {
        "postgres": {"environment": {"POSTGRES_USER": deploy["postgres"]["admin_user"],
            "POSTGRES_PASSWORD": secret(deploy["postgres"]["admin_password"]) }},
        "spicedb": {"environment": graph_env}, "spicedb-migrate": {"environment": graph_env},
        "temporal-migrate": {"environment": {**sql_env,
            "TEMPORAL_DATABASE": temporal["database"]["name"], "TEMPORAL_VISIBILITY_DATABASE": temporal["visibility_database"]}},
        "qdrant": {"environment": {"QDRANT__SERVICE__API_KEY": secret(dep["qdrant"]["api_key"])}}}}
    def environment(references):
        return {"OPENLET_CONFIG": "/etc/openlet/openlet.yaml", **{value[2:-1]: secret(value) for value in references}}

    refs = {
        "platform": [svc["platform"]["database"]["password"], dep["spicedb"]["key"], auth["secret_key"]],
        "letfs": [svc["letfs"]["database"]["password"], dep["spicedb"]["key"], dep["s3"]["access_key_id"], dep["s3"]["secret_access_key"], dep["qdrant"]["api_key"], c["models"]["provider"]["api_key"]],
        "ingest-cpu": [],
        "ingest-io": [dep["qdrant"]["api_key"], c["models"]["provider"]["api_key"]],
        "databases": [deploy["postgres"]["admin_password"], svc["platform"]["database"]["password"], svc["letfs"]["database"]["password"], temporal["database"]["password"], db["password"]],
        "resources": [dep["spicedb"]["key"], dep["qdrant"]["api_key"], dep["s3"]["access_key_id"], dep["s3"]["secret_access_key"]],
    }
    for service, references in refs.items():
        runtime["services"][service] = {"environment": environment(references)}
    runtime["services"]["database-backup"] = {"environment": {
        "PGHOST": pg["host"], "PGPORT": str(pg["port"]),
        "PGUSER": deploy["postgres"]["admin_user"], "PGPASSWORD": secret(deploy["postgres"]["admin_password"])}}
    for owner in ("platform", "letfs"):
        database = svc[owner]["database"]
        dsn = f'postgres://{quote(database["user"], safe="")}:{quote(secret(database["password"]), safe="")}@{pg["host"]}:{pg["port"]}/{database["name"]}?sslmode={pg["sslmode"]}'
        runtime["services"][f"{owner}-migrate"] = {"environment": {
            "GOOSE_DRIVER": "postgres", "GOOSE_DBSTRING": dsn, "GOOSE_MIGRATION_DIR": "/migrations"}}
        runtime["services"][owner]["healthcheck"] = {"test": ["CMD", "grpc-health-probe", f'-addr=127.0.0.1:{svc[owner]["grpc_listen"].rsplit(":", 1)[1]}']}
    runtime["services"]["envoy"] = {
        "ports": [f"127.0.0.1:{port}:{port}"],
        "healthcheck": {"test": ["CMD", "bash", "-c", f"exec 3<>/dev/tcp/127.0.0.1/{port}"]},
    }
    os.umask(0o077)
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    outputs = [("envoy", envoy), ("temporal", native), ("compose.runtime", runtime)]
    if test:
        outputs.append(("compose.test.runtime", {"services": {"s3": {"environment": {
            "RUSTFS_ACCESS_KEY": secret(dep["s3"]["access_key_id"]),
            "RUSTFS_SECRET_KEY": secret(dep["s3"]["secret_access_key"]),
        }}}}))
    for name, data in outputs:
        content = yaml.safe_dump(data, sort_keys=False)
        if name.startswith("compose."):
            content = content.replace("$", "$$")
        target = output / f"{name}.yaml"
        target.write_text(content)
        target.chmod(0o600 if name.startswith("compose.") else 0o644)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/generated")
    parser.add_argument("--test", action="store_true", help="Render native S3 credentials for the test Compose stack")
    args = parser.parse_args()
    configure(args.output, test=args.test)
