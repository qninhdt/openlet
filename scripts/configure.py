"""Render private native infrastructure outputs from OPENLET_CONFIG."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TypedDict, cast
from urllib.parse import quote, urlparse

import yaml
from openlet_sdk.config import Config, TelemetrySettings, load, secret

ROOT = Path(__file__).resolve().parents[1]


class ListenerFilter(TypedDict):
    typed_config: dict[str, object]


class FilterChain(TypedDict):
    filters: list[ListenerFilter]


class Listener(TypedDict):
    filter_chains: list[FilterChain]


class StaticResources(TypedDict):
    listeners: list[Listener]
    clusters: list[dict[str, object]]


class EnvoyConfig(TypedDict):
    static_resources: StaticResources


def render(name: str, values: Mapping[str, object]) -> dict[str, object]:
    text = (ROOT / "infra/config" / f"{name}.template.yaml").read_text()
    for key, value in values.items():
        text = text.replace(f"@{key}@", json.dumps(value))
    return cast(dict[str, object], yaml.safe_load(text))


def _load_config(config_path: Path | None) -> Config:
    if config_path is None:
        return load()
    with config_path.open() as stream:
        value: object = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError("configuration must be a YAML mapping")
    return cast(Config, value)


def _resolve_secret(value: str, env: Mapping[str, str]) -> str:
    if not (value.startswith("${") and value.endswith("}")):
        raise ValueError("secret must reference a whole ${ENV_VARIABLE} scalar")
    key = value[2:-1]
    result = env.get(key)
    if not result:
        raise ValueError(f"empty required environment variable {key}")
    return result


def configure_tracing(
    envoy: EnvoyConfig, settings: TelemetrySettings, environment: str
) -> None:
    endpoint = settings["otlp_endpoint"]
    if not endpoint:
        return
    url = urlparse(endpoint)
    ratio = settings["trace_sample_ratio"]
    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username
        or url.query
        or url.fragment
        or not math.isfinite(ratio)
        or not 0 <= ratio <= 1
        or settings["metrics_export_interval_seconds"] < 1
    ):
        raise ValueError("invalid telemetry endpoint, sample ratio or metrics interval")
    hcm = envoy["static_resources"]["listeners"][0]["filter_chains"][0]["filters"][0][
        "typed_config"
    ]
    hcm["tracing"] = {
        # Do not capture request paths or query strings in gateway spans.
        "max_path_tag_length": 0,
        "provider": {
            "name": "envoy.tracers.opentelemetry",
            "typed_config": {
                "@type": "type.googleapis.com/envoy.config.trace.v3.OpenTelemetryConfig",
                "service_name": "openlet-gateway",
                "grpc_service": {
                    "envoy_grpc": {"cluster_name": "otel"},
                    "timeout": "3s",
                },
                "resource_detectors": [
                    {
                        "name": "envoy.tracers.opentelemetry.resource_detectors.static_config",
                        "typed_config": {
                            "@type": "type.googleapis.com/envoy.extensions.tracers.opentelemetry.resource_detectors.v3.StaticConfigResourceDetectorConfig",
                            "attributes": {"deployment.environment.name": environment},
                        },
                    },
                    {
                        "name": "envoy.tracers.opentelemetry.resource_detectors.environment",
                        "typed_config": {
                            "@type": "type.googleapis.com/envoy.extensions.tracers.opentelemetry.resource_detectors.v3.EnvironmentResourceDetectorConfig"
                        },
                    },
                ],
                "sampler": {
                    "name": "envoy.tracers.opentelemetry.samplers.parent_based",
                    "typed_config": {
                        "@type": "type.googleapis.com/envoy.extensions.tracers.opentelemetry.samplers.v3.ParentBasedSamplerConfig",
                        "wrapped_sampler": {
                            "name": "envoy.tracers.opentelemetry.samplers.trace_id_ratio_based",
                            "typed_config": {
                                "@type": "type.googleapis.com/envoy.extensions.tracers.opentelemetry.samplers.v3.TraceIdRatioBasedSamplerConfig",
                                "sampling_percentage": {
                                    "numerator": round(ratio * 1_000_000),
                                    "denominator": "MILLION",
                                },
                            },
                        },
                    },
                },
            },
        },
    }
    cluster: dict[str, object] = {
        "name": "otel",
        "type": "STRICT_DNS",
        "connect_timeout": "3s",
        "http2_protocol_options": {},
        "load_assignment": {
            "cluster_name": "otel",
            "endpoints": [
                {
                    "lb_endpoints": [
                        {
                            "endpoint": {
                                "address": {
                                    "socket_address": {
                                        "address": url.hostname,
                                        "port_value": url.port
                                        or (443 if url.scheme == "https" else 80),
                                    }
                                }
                            }
                        }
                    ]
                }
            ],
        },
    }
    if url.scheme == "https":
        cluster["transport_socket"] = {
            "name": "envoy.transport_sockets.tls",
            "typed_config": {
                "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
                "sni": url.hostname,
                "common_tls_context": {
                    "validation_context": {
                        "trusted_ca": {
                            "filename": "/etc/ssl/certs/ca-certificates.crt"
                        },
                        "match_typed_subject_alt_names": [
                            {"san_type": "DNS", "matcher": {"exact": url.hostname}}
                        ],
                    }
                },
            },
        }
    envoy["static_resources"]["clusters"].append(cluster)


def configure(
    output: Path,
    *,
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    dynamic_gateway_port: bool = False,
) -> None:
    environ = os.environ if env is None else env
    c = _load_config(config_path)

    def resolve(value: str) -> str:
        return secret(value) if env is None else _resolve_secret(value, environ)

    profiles = {
        item.strip()
        for item in environ.get("COMPOSE_PROFILES", "").split(",")
        if item.strip()
    }

    dep, svc, deploy = c["dependencies"], c["services"], c["deployment"]
    pg, temporal = dep["postgres"], deploy["temporal"]
    if pg["sslmode"] != "disable":
        raise ValueError("Compose PostgreSQL uses private-network plaintext")
    host, port = svc["gateway"]["http_listen"].rsplit(":", 1)
    ph, pp = svc["platform"]["grpc_target"].rsplit(":", 1)
    fh, fp = svc["letfs"]["grpc_target"].rsplit(":", 1)
    chat_cfg = svc.get("chat")
    ch, cp = (
        chat_cfg["grpc_target"].rsplit(":", 1)
        if chat_cfg is not None
        else ("chat", "9090")
    )
    centrifugo_cfg = dep.get("centrifugo")
    centrifugo_url = urlparse(
        centrifugo_cfg["api_url"]
        if centrifugo_cfg is not None
        else "http://centrifugo:8000/api"
    )
    cen_h = centrifugo_url.hostname or "centrifugo"
    cen_p = centrifugo_url.port or (443 if centrifugo_url.scheme == "https" else 80)
    auth = c["auth"]["clerk"]
    user_id_key = auth.get("user_id_metadata_key", "openlet_user_id")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", user_id_key):
        raise ValueError(
            "auth.clerk.user_id_metadata_key must be a metadata field name"
        )
    jwks = urlparse(auth["jwks_url"])
    if jwks.scheme not in ("http", "https") or not jwks.hostname:
        raise ValueError("JWKS URL must be HTTP(S)")
    envoy = cast(
        EnvoyConfig,
        render(
            "envoy",
            dict(
                LISTEN_HOST=host,
                LISTEN_PORT=int(port),
                PLATFORM_HOST=ph,
                PLATFORM_PORT=int(pp),
                LETFS_HOST=fh,
                LETFS_PORT=int(fp),
                CHAT_HOST=ch,
                CHAT_PORT=int(cp),
                CENTRIFUGO_HOST=cen_h,
                CENTRIFUGO_PORT=int(cen_p),
                ISSUER=auth["issuer"],
                USER_ID_CLAIM="public_metadata." + user_id_key,
                AUDIENCE=auth["audience"],
                JWKS_URL=auth["jwks_url"],
                JWKS_HOST=jwks.hostname,
                JWKS_PORT=jwks.port or (443 if jwks.scheme == "https" else 80),
            ),
        ),
    )
    if jwks.scheme == "https":
        jwks_cluster = next(
            cl
            for cl in envoy["static_resources"]["clusters"]
            if cl["name"] == "clerk_jwks"
        )
        jwks_cluster["transport_socket"] = {
            "name": "envoy.transport_sockets.tls",
            "typed_config": {
                "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
                "sni": jwks.hostname,
                "common_tls_context": {
                    "validation_context": {
                        "trusted_ca": {
                            "filename": "/etc/ssl/certs/ca-certificates.crt"
                        },
                        "match_typed_subject_alt_names": [
                            {"san_type": "DNS", "matcher": {"exact": jwks.hostname}}
                        ],
                    }
                },
            },
        }
    leta_enabled = "leta" in profiles
    if leta_enabled:
        lh, lp = svc["leta"]["http_target"].rsplit(":", 1)
        envoy["static_resources"]["clusters"].append(
            {
                "name": "leta",
                "type": "STRICT_DNS",
                "connect_timeout": "5s",
                "load_assignment": {
                    "cluster_name": "leta",
                    "endpoints": [
                        {
                            "lb_endpoints": [
                                {
                                    "endpoint": {
                                        "address": {
                                            "socket_address": {
                                                "address": lh,
                                                "port_value": int(lp),
                                            }
                                        }
                                    }
                                }
                            ]
                        }
                    ],
                },
            }
        )
        hcm = envoy["static_resources"]["listeners"][0]["filter_chains"][0]["filters"][
            0
        ]["typed_config"]
        routing = cast(dict[str, object], hcm["route_config"])
        hosts = cast(list[dict[str, object]], routing["virtual_hosts"])
        routes = cast(list[dict[str, object]], hosts[0]["routes"])
        routes.insert(
            0,
            {
                "name": "leta",
                "match": {
                    "safe_regex": {
                        "google_re2": {},
                        "regex": "/v1/(workspaces/[^/]+/(letas|models)|hitl-requests)(/.*)?",
                    }
                },
                "route": {"cluster": "leta", "timeout": "0s", "idle_timeout": "0s"},
                "typed_per_filter_config": {
                    "envoy.filters.http.grpc_json_transcoder": {
                        "@type": "type.googleapis.com/envoy.extensions.filters.http.grpc_json_transcoder.v3.GrpcJsonTranscoder",
                        "proto_descriptor": "/etc/openlet/public.pb",
                        "services": [],
                    }
                },
            },
        )
    configure_tracing(envoy, c["telemetry"], c["runtime"]["environment"])
    native = render(
        "temporal",
        dict(
            POSTGRES=f"{pg['host']}:{pg['port']}",
            DATABASE=temporal["database"]["name"],
            VISIBILITY_DATABASE=temporal["visibility_database"],
            USER=temporal["database"]["user"],
            PASSWORD=resolve(temporal["database"]["password"]),
        ),
    )
    db = deploy["spicedb"]["database"]
    uri = f"postgres://{quote(db['user'], safe='')}:{quote(resolve(db['password']), safe='')}@{pg['host']}:{pg['port']}/{db['name']}?sslmode={pg['sslmode']}"
    graph_env = {
        "SPICEDB_DATASTORE_CONN_URI": uri,
        "SPICEDB_GRPC_PRESHARED_KEY": resolve(dep["spicedb"]["key"]),
    }
    sql_env = {
        "SQL_HOST": pg["host"],
        "SQL_PORT": str(pg["port"]),
        "SQL_USER": temporal["database"]["user"],
        "SQL_PASSWORD": resolve(temporal["database"]["password"]),
        "SQL_PLUGIN": "postgres12",
    }
    runtime: dict[str, dict[str, dict[str, object]]] = {
        "services": {
            "postgres": {
                "environment": {
                    "POSTGRES_USER": deploy["postgres"]["admin_user"],
                    "POSTGRES_PASSWORD": resolve(deploy["postgres"]["admin_password"]),
                }
            },
            "spicedb": {"environment": graph_env},
            "spicedb-migrate": {"environment": graph_env},
            "temporal-migrate": {
                "environment": {
                    **sql_env,
                    "TEMPORAL_DATABASE": temporal["database"]["name"],
                    "TEMPORAL_VISIBILITY_DATABASE": temporal["visibility_database"],
                }
            },
            "qdrant": {
                "environment": {
                    "QDRANT__SERVICE__API_KEY": resolve(dep["qdrant"]["api_key"])
                }
            },
        }
    }

    def environment(references: Iterable[str]) -> dict[str, str]:
        return {
            "OPENLET_CONFIG": "/etc/openlet/openlet.yaml",
            "COMPOSE_PROFILES": environ.get("COMPOSE_PROFILES", ""),
            **(
                {"OTEL_RESOURCE_ATTRIBUTES": environ["OTEL_RESOURCE_ATTRIBUTES"]}
                if environ.get("OTEL_RESOURCE_ATTRIBUTES")
                else {}
            ),
            **{value[2:-1]: resolve(value) for value in references},
        }

    refs: dict[str, list[str]] = {
        "platform": [
            svc["platform"]["database"]["password"],
            dep["spicedb"]["key"],
            auth["secret_key"],
            *(
                [centrifugo_cfg["token_hmac_secret"]]
                if centrifugo_cfg is not None
                else []
            ),
        ],
        "letfs": [
            svc["letfs"]["database"]["password"],
            dep["spicedb"]["key"],
            dep["s3"]["access_key_id"],
            dep["s3"]["secret_access_key"],
            dep["qdrant"]["api_key"],
            c["models"]["gateway"]["api_key"],
        ],
        "ingest-cpu": [
            dep["s3"]["access_key_id"],
            dep["s3"]["secret_access_key"],
            *(["${DATALAB_API_KEY}"] if environ.get("DATALAB_API_KEY") else []),
            *(["${DATALAB_HOST}"] if environ.get("DATALAB_HOST") else []),
        ],
        "ingest-io": [
            dep["s3"]["access_key_id"],
            dep["s3"]["secret_access_key"],
            dep["qdrant"]["api_key"],
            c["models"]["gateway"]["api_key"],
        ],
        "databases": [
            deploy["postgres"]["admin_password"],
            svc["platform"]["database"]["password"],
            svc["letfs"]["database"]["password"],
            temporal["database"]["password"],
            db["password"],
        ],
        "resources": [
            dep["spicedb"]["key"],
            dep["qdrant"]["api_key"],
            dep["s3"]["access_key_id"],
            dep["s3"]["secret_access_key"],
        ],
    }
    runtime["services"]["redis"] = {
        "environment": {"REDIS_PASSWORD": resolve(dep["redis"]["password"])}
    }
    if chat_cfg is not None:
        refs["databases"].append(chat_cfg["database"]["password"])
        refs["chat"] = [
            chat_cfg["database"]["password"],
            dep["spicedb"]["key"],
            *(
                [centrifugo_cfg["api_key"], centrifugo_cfg["token_hmac_secret"]]
                if centrifugo_cfg is not None
                else []
            ),
        ]
    if leta_enabled:
        refs["databases"].append(svc["leta"]["database"]["password"])
        lf = c.get("langfuse")
        if lf is None:
            raise ValueError("leta profile requires Langfuse settings")
        refs["leta-api"] = [
            svc["leta"]["database"]["password"],
            dep["spicedb"]["key"],
            c["models"]["gateway"]["api_key"],
            lf["public_key"],
            lf["secret_key"],
            *(
                [centrifugo_cfg["api_key"], centrifugo_cfg["token_hmac_secret"]]
                if centrifugo_cfg is not None
                else []
            ),
        ]
        if web_search := svc["leta"].get("web_search"):
            refs["leta-api"].append(web_search["api_key"])
        refs["leta-worker"] = refs["leta-api"]
        refs["leta-migrate"] = [svc["leta"]["database"]["password"]]
    if "langfuse" in c:
        refs["ingest-io"].extend(
            [c["langfuse"]["public_key"], c["langfuse"]["secret_key"]]
        )
    if "observability" in profiles:
        cloud = c.get("observability")
        lf = c.get("langfuse")
        if cloud is None or lf is None:
            raise ValueError(
                "observability profile requires Grafana Cloud and Langfuse settings"
            )
        refs["databases"].append(cloud["postgres_password"])
        runtime["services"]["alloy"] = {
            "environment": {
                "OPENLET_ENVIRONMENT": c["runtime"]["environment"],
                "GRAFANA_METRICS_ENDPOINT": cloud["metrics"]["endpoint"],
                "GRAFANA_METRICS_USER": cloud["metrics"]["user"],
                "GRAFANA_TRACES_ENDPOINT": cloud["traces"]["endpoint"],
                "GRAFANA_TRACES_USER": cloud["traces"]["user"],
                "GRAFANA_LOGS_ENDPOINT": cloud["logs"]["endpoint"],
                "GRAFANA_LOGS_USER": cloud["logs"]["user"],
                "GRAFANA_CLOUD_TOKEN": resolve(cloud["token"]),
                "LANGFUSE_PUBLIC_KEY": resolve(lf["public_key"]),
                "LANGFUSE_SECRET_KEY": resolve(lf["secret_key"]),
                "LITELLM_MASTER_KEY": resolve(c["models"]["gateway"]["api_key"]),
                "LANGFUSE_OTLP_ENDPOINT": lf["base_url"].rstrip("/")
                + "/api/public/otel",
                "QDRANT_API_KEY": resolve(dep["qdrant"]["api_key"]),
                "QDRANT_METRICS_ADDRESS": dep["qdrant"]["address"].rsplit(":", 1)[0]
                + ":6333",
                "REDIS_ADDRESS": dep["redis"]["address"],
                "REDIS_PASSWORD": resolve(dep["redis"]["password"]),
                "POSTGRES_METRICS_DSN": f"postgresql://{quote(cloud['postgres_user'], safe='')}:{quote(resolve(cloud['postgres_password']), safe='')}@{pg['host']}:{pg['port']}/postgres?sslmode={pg['sslmode']}",
            }
        }
    runtime["services"]["litellm"] = {
        "environment": {
            "LITELLM_MASTER_KEY": resolve(c["models"]["gateway"]["api_key"]),
            "OPENAI_API_KEY": environ["OPENAI_API_KEY"],
            "OPENAI_BASE_URL": environ["OPENAI_BASE_URL"],
        }
    }
    for service, references in refs.items():
        runtime["services"][service] = {"environment": environment(references)}
    if leta_enabled:
        runtime["services"]["leta-api"]["healthcheck"] = {
            "test": [
                "CMD",
                "/app/.venv/bin/python",
                "-c",
                'import urllib.request; urllib.request.urlopen("http://127.0.0.1:'
                + svc["leta"]["http_listen"].rsplit(":", 1)[1]
                + '/ready",timeout=3)',
            ]
        }
    for owner, database, listen in [
        ("platform", svc["platform"]["database"], svc["platform"]["grpc_listen"]),
        ("letfs", svc["letfs"]["database"], svc["letfs"]["grpc_listen"]),
        *(
            [("chat", chat_cfg["database"], chat_cfg["grpc_listen"])]
            if chat_cfg is not None
            else []
        ),
        *([("leta", svc["leta"]["database"], None)] if leta_enabled else []),
    ]:
        dsn = f"postgres://{quote(database['user'], safe='')}:{quote(resolve(database['password']), safe='')}@{pg['host']}:{pg['port']}/{database['name']}?sslmode={pg['sslmode']}"
        runtime["services"][f"{owner}-migrate"] = {
            "environment": {
                "GOOSE_DRIVER": "postgres",
                "GOOSE_DBSTRING": dsn,
                "GOOSE_MIGRATION_DIR": "/migrations",
            }
        }
        if listen is None:
            cast(
                dict[str, str], runtime["services"]["leta-migrate"]["environment"]
            ).update(environment([database["password"]]))
            continue
        runtime["services"][owner]["healthcheck"] = {
            "test": [
                "CMD",
                "grpc-health-probe",
                f"-addr=127.0.0.1:{listen.rsplit(':', 1)[1]}",
            ]
        }
    envoy_runtime: dict[str, object] = {
        "ports": [f"127.0.0.1:{'' if dynamic_gateway_port else port}:{port}"],
        "environment": {
            "OTEL_RESOURCE_ATTRIBUTES": environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
        },
        "healthcheck": {
            "test": ["CMD", "bash", "-c", f"exec 3<>/dev/tcp/127.0.0.1/{port}"]
        },
    }
    if leta_enabled:
        envoy_runtime["depends_on"] = {
            "leta-api": {"condition": "service_healthy"},
        }
    runtime["services"]["envoy"] = envoy_runtime
    os.umask(0o077)
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    alloy = (ROOT / "infra/config/observability/alloy.alloy").read_text()
    alloy = alloy.replace(
        "targets = [] // Redis targets are enabled by configure.py with the Leta profile.",
        "targets = prometheus.exporter.redis.cache.targets",
    )
    (output / "alloy.alloy").write_text(alloy)
    centrifugo_config: dict[str, object] = {
        "client": {
            "allowed_origins": ["*"],
            "token": {
                "hmac_secret_key": resolve(centrifugo_cfg["token_hmac_secret"])
                if centrifugo_cfg is not None
                else "dev-secret",
            },
        },
        "http_api": {
            "key": resolve(centrifugo_cfg["api_key"])
            if centrifugo_cfg is not None
            else "dev-api-key",
        },
        "health": {"enabled": True},
        "engine": {
            "type": "redis",
            "redis": {
                "address": dep["redis"]["address"],
                "password": resolve(dep["redis"]["password"]),
                "db": dep["redis"]["database"],
            },
        },
        "channel": {
            "namespaces": [
                {
                    "name": "chat",
                    "allow_user_limited_channels": True,
                    "allow_subscribe_for_client": False,
                    "history_size": 200,
                    "history_ttl": "300s",
                    "force_recovery": True,
                },
                {
                    "name": "leta",
                    "allow_user_limited_channels": True,
                    "allow_subscribe_for_client": False,
                    "history_size": 200,
                    "history_ttl": "300s",
                    "force_recovery": True,
                },
                {
                    "name": "letfs",
                    "allow_subscribe_for_client": False,
                    "history_size": 100,
                    "history_ttl": "120s",
                    "force_recovery": True,
                },
            ]
        },
    }
    cen_target = output / "centrifugo.json"
    cen_target.write_text(json.dumps(centrifugo_config, indent=2) + "\n")
    cen_target.chmod(0o644)
    outputs: list[tuple[str, object]] = [
        ("envoy", envoy),
        ("temporal", native),
        ("compose.runtime", runtime),
    ]
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
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to openlet.yaml (defaults to OPENLET_CONFIG)",
    )
    args = parser.parse_args()
    configure(args.output, config_path=args.config)
