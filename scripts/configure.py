"""Render private native infrastructure outputs from OPENLET_CONFIG."""

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
from openlet_sdk.config import TelemetrySettings, load, secret

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


def configure(output: Path, test: bool = False) -> None:
    c = load()
    dep, svc, deploy = c["dependencies"], c["services"], c["deployment"]
    pg, temporal = dep["postgres"], deploy["temporal"]
    if pg["sslmode"] != "disable":
        raise ValueError("Compose PostgreSQL uses private-network plaintext")
    host, port = svc["gateway"]["http_listen"].rsplit(":", 1)
    ph, pp = svc["platform"]["grpc_target"].rsplit(":", 1)
    fh, fp = svc["letfs"]["grpc_target"].rsplit(":", 1)
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
        envoy["static_resources"]["clusters"][2]["transport_socket"] = {
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
    leta_enabled = "leta" in os.environ.get("COMPOSE_PROFILES", "").split(",")
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
                        "regex": "/v1/(workspaces/[^/]+/letas|hitl-requests)(/.*)?",
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
            PASSWORD=secret(temporal["database"]["password"]),
        ),
    )
    db = deploy["spicedb"]["database"]
    uri = f"postgres://{quote(db['user'], safe='')}:{quote(secret(db['password']), safe='')}@{pg['host']}:{pg['port']}/{db['name']}?sslmode={pg['sslmode']}"
    graph_env = {
        "SPICEDB_DATASTORE_CONN_URI": uri,
        "SPICEDB_GRPC_PRESHARED_KEY": secret(dep["spicedb"]["key"]),
    }
    sql_env = {
        "SQL_HOST": pg["host"],
        "SQL_PORT": str(pg["port"]),
        "SQL_USER": temporal["database"]["user"],
        "SQL_PASSWORD": secret(temporal["database"]["password"]),
        "SQL_PLUGIN": "postgres12",
    }
    runtime: dict[str, dict[str, dict[str, object]]] = {
        "services": {
            "postgres": {
                "environment": {
                    "POSTGRES_USER": deploy["postgres"]["admin_user"],
                    "POSTGRES_PASSWORD": secret(deploy["postgres"]["admin_password"]),
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
                    "QDRANT__SERVICE__API_KEY": secret(dep["qdrant"]["api_key"])
                }
            },
        }
    }

    def environment(references: Iterable[str]) -> dict[str, str]:
        return {
            "OPENLET_CONFIG": "/etc/openlet/openlet.yaml",
            "COMPOSE_PROFILES": os.environ.get("COMPOSE_PROFILES", ""),
            **(
                {"OTEL_RESOURCE_ATTRIBUTES": os.environ["OTEL_RESOURCE_ATTRIBUTES"]}
                if os.environ.get("OTEL_RESOURCE_ATTRIBUTES")
                else {}
            ),
            **{value[2:-1]: secret(value) for value in references},
        }

    refs = {
        "platform": [
            svc["platform"]["database"]["password"],
            dep["spicedb"]["key"],
            auth["secret_key"],
        ],
        "letfs": [
            svc["letfs"]["database"]["password"],
            dep["spicedb"]["key"],
            dep["s3"]["access_key_id"],
            dep["s3"]["secret_access_key"],
            dep["qdrant"]["api_key"],
            c["models"]["gateway"]["api_key"],
        ],
        "ingest-cpu": ["${DATALAB_API_KEY}"]
        if os.environ.get("DATALAB_API_KEY")
        else [],
        "ingest-io": [dep["qdrant"]["api_key"], c["models"]["gateway"]["api_key"]],
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
    if leta_enabled:
        refs["databases"].append(svc["leta"]["database"]["password"])
        lf = c.get("langfuse")
        if lf is None:
            raise ValueError("leta profile requires Langfuse settings")
        refs["leta-api"] = [
            svc["leta"]["database"]["password"],
            dep["spicedb"]["key"],
            dep["redis"]["password"],
            c["models"]["gateway"]["api_key"],
            lf["public_key"],
            lf["secret_key"],
        ]
        if web_search := svc["leta"].get("web_search"):
            refs["leta-api"].append(web_search["api_key"])
        refs["leta-worker"] = refs["leta-api"]
        refs["leta-migrate"] = [svc["leta"]["database"]["password"]]
        runtime["services"]["redis"] = {
            "environment": {"REDIS_PASSWORD": secret(dep["redis"]["password"])}
        }
    if "langfuse" in c:
        refs["ingest-io"].extend(
            [c["langfuse"]["public_key"], c["langfuse"]["secret_key"]]
        )
    if "observability" in os.environ.get("COMPOSE_PROFILES", "").split(","):
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
                "GRAFANA_CLOUD_TOKEN": secret(cloud["token"]),
                "LANGFUSE_PUBLIC_KEY": secret(lf["public_key"]),
                "LANGFUSE_SECRET_KEY": secret(lf["secret_key"]),
                "LITELLM_MASTER_KEY": secret(c["models"]["gateway"]["api_key"]),
                "LANGFUSE_OTLP_ENDPOINT": lf["base_url"].rstrip("/")
                + "/api/public/otel",
                "QDRANT_API_KEY": secret(dep["qdrant"]["api_key"]),
                "QDRANT_METRICS_ADDRESS": dep["qdrant"]["address"].rsplit(":", 1)[0]
                + ":6333",
                "REDIS_ADDRESS": dep["redis"]["address"],
                "REDIS_PASSWORD": secret(dep["redis"]["password"])
                if "leta" in os.environ.get("COMPOSE_PROFILES", "").split(",")
                else "",
                "POSTGRES_METRICS_DSN": f"postgresql://{quote(cloud['postgres_user'], safe='')}:{quote(secret(cloud['postgres_password']), safe='')}@{pg['host']}:{pg['port']}/postgres?sslmode={pg['sslmode']}",
            }
        }
    runtime["services"]["litellm"] = {
        "environment": {
            "LITELLM_MASTER_KEY": secret(c["models"]["gateway"]["api_key"]),
            "OPENAI_API_KEY": os.environ["OPENAI_API_KEY"],
            "OPENAI_BASE_URL": os.environ["OPENAI_BASE_URL"],
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
    runtime["services"]["database-backup"] = {
        "environment": {
            "PGHOST": pg["host"],
            "PGPORT": str(pg["port"]),
            "PGUSER": deploy["postgres"]["admin_user"],
            "PGPASSWORD": secret(deploy["postgres"]["admin_password"]),
        }
    }
    for owner, database, listen in [
        ("platform", svc["platform"]["database"], svc["platform"]["grpc_listen"]),
        ("letfs", svc["letfs"]["database"], svc["letfs"]["grpc_listen"]),
        *([("leta", svc["leta"]["database"], None)] if leta_enabled else []),
    ]:
        dsn = f"postgres://{quote(database['user'], safe='')}:{quote(secret(database['password']), safe='')}@{pg['host']}:{pg['port']}/{database['name']}?sslmode={pg['sslmode']}"
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
    runtime["services"]["envoy"] = {
        "ports": [f"127.0.0.1:{port}:{port}"],
        "environment": {
            "OTEL_RESOURCE_ATTRIBUTES": os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
        },
        "healthcheck": {
            "test": ["CMD", "bash", "-c", f"exec 3<>/dev/tcp/127.0.0.1/{port}"]
        },
    }
    os.umask(0o077)
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    alloy = (ROOT / "infra/config/observability/alloy.alloy").read_text()
    if leta_enabled:
        alloy = alloy.replace(
            "targets = [] // Redis targets are enabled by configure.py with the Leta profile.",
            "targets = prometheus.exporter.redis.cache.targets",
        )
    (output / "alloy.alloy").write_text(alloy)
    outputs: list[tuple[str, object]] = [
        ("envoy", envoy),
        ("temporal", native),
        ("compose.runtime", runtime),
    ]
    if test:
        outputs.append(
            (
                "compose.test.runtime",
                {
                    "services": {
                        "s3": {
                            "environment": {
                                "RUSTFS_ACCESS_KEY": secret(dep["s3"]["access_key_id"]),
                                "RUSTFS_SECRET_KEY": secret(
                                    dep["s3"]["secret_access_key"]
                                ),
                            }
                        }
                    }
                },
            )
        )
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
        "--test",
        action="store_true",
        help="Render native S3 credentials for the test Compose stack",
    )
    args = parser.parse_args()
    configure(args.output, test=args.test)
