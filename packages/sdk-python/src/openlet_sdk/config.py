import os
from typing import Literal, NotRequired, TypedDict, cast

import yaml

type JSON = None | bool | int | float | str | list[JSON] | dict[str, JSON]
type ReasoningEffort = (
    Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None
)


class RuntimeSettings(TypedDict):
    environment: str
    log_level: str
    shutdown_timeout_seconds: int


class TelemetrySettings(TypedDict):
    otlp_endpoint: str | None
    trace_sample_ratio: float
    metrics_export_interval_seconds: int


class DatabaseSettings(TypedDict):
    name: str
    user: str
    password: str


class MaintenanceSettings(TypedDict):
    interval_seconds: int
    object_gc_grace_seconds: NotRequired[int]


class ProcessingSettings(TypedDict):
    max_artifacts: int
    max_manifest_text_bytes: int
    max_artifact_blob_bytes: int
    parse_timeout_seconds: int
    enrich_index_timeout_seconds: int


class SemanticSearchSettings(TypedDict):
    candidate_limit: int
    result_limit: int


class LetFSSettings(TypedDict):
    grpc_listen: str
    grpc_target: str
    database: DatabaseSettings
    max_text_bytes: int
    max_blob_bytes: int
    multipart_threshold_bytes: int
    multipart_part_bytes: int
    upload_url_ttl_seconds: int
    download_url_ttl_seconds: int
    idempotency_retention_seconds: int
    semantic_search: SemanticSearchSettings
    processing: ProcessingSettings
    maintenance: MaintenanceSettings


class ParseLimits(TypedDict):
    max_pages: int
    max_page_pixels: int
    max_office_expanded_bytes: int
    max_spreadsheet_cells: int
    max_sheets: int
    max_output_bytes: int


class DatalabSettings(TypedDict):
    concurrency: int
    result_concurrency: int
    requests_per_minute: int
    max_response_bytes: int


class CPUSettings(TypedDict):
    activity_concurrency: int
    office_concurrency: NotRequired[int]
    datalab: NotRequired[DatalabSettings]
    split_tokens: int
    limits: ParseLimits


class IOSettings(TypedDict):
    activity_concurrency: int
    model_concurrency: int
    embedding_batch_size: int
    chunk_size_tokens: int
    chunk_overlap_tokens: int


class IngestSettings(TypedDict):
    cpu: CPUSettings
    io: IOSettings


class ProviderSettings(TypedDict):
    base_url: str
    api_key: str
    timeout_seconds: int


class EmbeddingSettings(TypedDict):
    model: str
    dimensions: int


class EnrichmentSettings(TypedDict):
    output_mode: Literal["tools", "json_schema", "text"]
    max_input_characters: int
    max_image_pixels: int
    image_max_side: int
    image_jpeg_quality: int


class ModelsSettings(TypedDict):
    gateway: ProviderSettings
    embedding: EmbeddingSettings
    reranking: NotRequired[dict[str, str] | None]
    enrichment: EnrichmentSettings


class Queues(TypedDict):
    platform: str
    letfs: str
    ingest_cpu: str
    ingest_io: str
    leta: str
    leta_runtime: str
    leta_bridge: str


class TemporalSettings(TypedDict):
    address: str
    namespace: str
    tls: bool
    queues: Queues


class PostgresSettings(TypedDict):
    host: str
    port: int
    sslmode: str


class SpiceDBSettings(TypedDict):
    address: str
    tls: bool
    key: str


class QdrantSettings(TypedDict):
    address: str
    tls: bool
    api_key: str
    collection: str


class S3Settings(TypedDict):
    endpoint: str
    public_endpoint: NotRequired[str]
    processing_download_endpoint: NotRequired[str]
    region: str
    bucket: str
    path_style: bool
    access_key_id: str
    secret_access_key: str


class RedisSettings(TypedDict):
    address: str
    database: int
    password: str


class Dependencies(TypedDict):
    postgres: PostgresSettings
    temporal: TemporalSettings
    spicedb: SpiceDBSettings
    qdrant: QdrantSettings
    s3: S3Settings
    redis: RedisSettings


class PlatformSettings(TypedDict):
    database: DatabaseSettings
    grpc_listen: str
    grpc_target: str
    max_members: int
    default_quota_bytes: int
    invitation_ttl_seconds: int
    idempotency_retention_seconds: int
    maintenance: MaintenanceSettings


class CompactionSettings(TypedDict):
    trigger_fraction: float
    keep_tokens: int
    summary_max_tokens: int


class WebSearchSettings(TypedDict):
    api_key: str


class LetaToolsSettings(TypedDict):
    hitl: NotRequired[bool]
    multi_agent: NotRequired[bool]
    schedule: NotRequired[bool]
    web: NotRequired[bool]
    execute: NotRequired[bool]
    semantic_search: NotRequired[bool]
    activity: NotRequired[bool]


class LetaSettings(TypedDict):
    http_listen: str
    http_target: str
    database: DatabaseSettings
    compaction: CompactionSettings
    web_search: NotRequired[WebSearchSettings]
    tools: NotRequired[LetaToolsSettings]


class Services(TypedDict):
    platform: PlatformSettings
    letfs: LetFSSettings
    letfs_ingest: IngestSettings
    leta: LetaSettings
    gateway: dict[str, str]


class TemporalDeployment(TypedDict):
    database: DatabaseSettings
    visibility_database: str
    namespace_retention_hours: int


class Deployment(TypedDict):
    postgres: dict[str, str]
    temporal: TemporalDeployment
    spicedb: dict[str, DatabaseSettings]


class LangfuseSettings(TypedDict):
    base_url: str
    public_key: str
    secret_key: str
    prompt_label: str


class CloudSignal(TypedDict):
    endpoint: str
    user: str


class ObservabilitySettings(TypedDict):
    metrics: CloudSignal
    traces: CloudSignal
    logs: CloudSignal
    token: str
    postgres_user: str
    postgres_password: str


class Config(TypedDict):
    runtime: RuntimeSettings
    grpc: dict[str, int]
    telemetry: TelemetrySettings
    auth: dict[str, dict[str, str]]
    dependencies: Dependencies
    models: ModelsSettings
    services: Services
    deployment: Deployment
    langfuse: NotRequired[LangfuseSettings]
    observability: NotRequired[ObservabilitySettings]


def load() -> Config:
    with open(os.environ["OPENLET_CONFIG"]) as stream:
        value: object = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError("configuration must be a YAML mapping")
    # The owning process validates the settings it consumes, not other services.
    return cast(Config, value)


def secret(value: str) -> str:
    if not (value.startswith("${") and value.endswith("}")):
        raise ValueError("secret must reference a whole ${ENV_VARIABLE} scalar")
    key = value[2:-1]
    result = os.environ[key]
    if not result:
        raise ValueError(f"empty required environment variable {key}")
    return result
