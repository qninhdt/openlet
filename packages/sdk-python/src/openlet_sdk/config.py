"""Typed configuration schema, YAML loader, and environment secret resolution."""

import os
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast

import yaml

from openlet_sdk.types import JSON, JsonObject, MutableJsonObject, is_str_mapping

__all__ = [
    "JSON",
    "AuthSettings",
    "CPUSettings",
    "CentrifugoSettings",
    "ChatOutboxSettings",
    "ChatSettings",
    "ClerkSettings",
    "CloudSignal",
    "Config",
    "DatabaseSettings",
    "DatalabSettings",
    "Dependencies",
    "Deployment",
    "EmbeddingSettings",
    "EnrichmentSettings",
    "GatewaySettings",
    "GrpcSettings",
    "IOSettings",
    "IngestSettings",
    "JsonObject",
    "LangfuseSettings",
    "LetFSSearchSettings",
    "LetFSSettings",
    "LetaBashSettings",
    "LetaCompactionBackgroundSettings",
    "LetaCompactionSettings",
    "LetaFileToolsSettings",
    "LetaMediaSettings",
    "LetaMessagingSettings",
    "LetaModelRetrySettings",
    "LetaModelSettings",
    "LetaOrchestrationSettings",
    "LetaSettings",
    "LetaSubagentsSettings",
    "LetaToolOutputSettings",
    "LetaToolsSettings",
    "LetaWebSettings",
    "MaintenanceSettings",
    "ModelsSettings",
    "MutableJsonObject",
    "ObservabilitySettings",
    "ParseLimits",
    "PlatformSettings",
    "PostgresDeployment",
    "PostgresSettings",
    "ProcessingSettings",
    "ProviderSettings",
    "QdrantSettings",
    "Queues",
    "ReasoningEffort",
    "RedisSettings",
    "RerankingSettings",
    "RuntimeSettings",
    "S3Settings",
    "SemanticSearchSettings",
    "Services",
    "SpiceDBDeployment",
    "SpiceDBSettings",
    "TelemetrySettings",
    "TemporalDeployment",
    "TemporalSettings",
    "WebSearchSettings",
    "load",
    "load_path",
    "parse_config",
    "secret",
]

type ReasoningEffort = (
    Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None
)


class RuntimeSettings(TypedDict):
    """Process runtime environment and logging configuration."""

    environment: str
    log_level: str
    shutdown_timeout_seconds: int


class TelemetrySettings(TypedDict):
    """OpenTelemetry exporter and sampling settings."""

    otlp_endpoint: str | None
    trace_sample_ratio: float
    metrics_export_interval_seconds: int


class DatabaseSettings(TypedDict):
    """Per-service PostgreSQL database credentials."""

    name: str
    user: str
    password: str


class MaintenanceSettings(TypedDict):
    """Background maintenance sweep configuration."""

    interval_seconds: int
    object_gc_grace_seconds: NotRequired[int]


class ProcessingSettings(TypedDict):
    """LetFS ingest processing limits and timeouts."""

    max_artifacts: int
    max_manifest_text_bytes: int
    max_artifact_blob_bytes: int
    parse_timeout_seconds: int
    enrich_index_timeout_seconds: int


class LetFSSearchSettings(TypedDict):
    """LetFS lexical search defaults and limits."""

    default_limit: int
    max_limit: int
    timeout_seconds: int
    max_line_chars: int


class SemanticSearchSettings(TypedDict):
    """LetFS semantic search candidate and excerpt limits."""

    candidate_limit: int
    result_limit: int
    max_result_limit: NotRequired[int]
    timeout_seconds: NotRequired[int]
    max_excerpt_chars: NotRequired[int]


class LetFSSettings(TypedDict):
    """LetFS service configuration."""

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
    search: NotRequired[LetFSSearchSettings]
    semantic_search: SemanticSearchSettings
    processing: ProcessingSettings
    maintenance: MaintenanceSettings


class ChatOutboxSettings(TypedDict):
    """Chat outbox relay polling and retention settings."""

    batch_size: int
    poll_interval_seconds: int
    max_backoff_seconds: int
    retention_hours: int


class ChatSettings(TypedDict):
    """Chat service configuration."""

    grpc_listen: str
    grpc_target: str
    database: DatabaseSettings
    outbox: NotRequired[ChatOutboxSettings]


class ParseLimits(TypedDict):
    """Document parser safety limits."""

    max_pages: int
    max_page_pixels: int
    max_office_expanded_bytes: int
    max_spreadsheet_cells: int
    max_sheets: int
    max_output_bytes: int


class DatalabSettings(TypedDict):
    """Datalab conversion concurrency and rate limits."""

    concurrency: int
    result_concurrency: int
    requests_per_minute: int
    max_response_bytes: int


class CPUSettings(TypedDict):
    """Ingest CPU worker concurrency and parser limits."""

    activity_concurrency: int
    office_concurrency: NotRequired[int]
    datalab: NotRequired[DatalabSettings]
    split_tokens: int
    limits: ParseLimits


class IOSettings(TypedDict):
    """Ingest IO worker concurrency and chunking settings."""

    activity_concurrency: int
    model_concurrency: int
    embedding_batch_size: int
    chunk_size_tokens: int
    chunk_overlap_tokens: int


class IngestSettings(TypedDict):
    """LetFS ingest worker configuration."""

    cpu: CPUSettings
    io: IOSettings


class ProviderSettings(TypedDict):
    """Model gateway connection settings."""

    base_url: str
    api_key: str
    timeout_seconds: int


class EmbeddingSettings(TypedDict):
    """Embedding model selection and vector dimensions."""

    model: str
    dimensions: int


class EnrichmentSettings(TypedDict):
    """Ingest enrichment output mode and image sizing."""

    output_mode: Literal["tools", "json_schema", "text"]
    max_input_characters: int
    max_image_pixels: int
    image_max_side: int
    image_jpeg_quality: int


class RerankingSettings(TypedDict):
    """Optional reranking model identifier."""

    model: str


class ModelsSettings(TypedDict):
    """Gateway, embedding, reranking, and enrichment model settings."""

    gateway: ProviderSettings
    embedding: EmbeddingSettings
    reranking: NotRequired[RerankingSettings | None]
    enrichment: EnrichmentSettings


class Queues(TypedDict):
    """Temporal task queue names."""

    platform: str
    letfs: str
    ingest_cpu: str
    ingest_io: str
    leta_orchestration: str
    leta_runtime: str


class TemporalSettings(TypedDict):
    """Temporal server connection and task queues."""

    address: str
    namespace: str
    tls: bool
    queues: Queues


class PostgresSettings(TypedDict):
    """Shared PostgreSQL host connection settings."""

    host: str
    port: int
    sslmode: str


class SpiceDBSettings(TypedDict):
    """SpiceDB gRPC connection settings."""

    address: str
    tls: bool
    key: str


class QdrantSettings(TypedDict):
    """Qdrant vector database connection settings."""

    address: str
    tls: bool
    api_key: str
    collection: str


class S3Settings(TypedDict):
    """S3-compatible object storage connection settings."""

    endpoint: str
    public_endpoint: NotRequired[str]
    processing_download_endpoint: NotRequired[str]
    region: str
    bucket: str
    path_style: bool
    access_key_id: str
    secret_access_key: str


class RedisSettings(TypedDict):
    """Redis connection settings."""

    address: str
    database: int
    password: str


class CentrifugoSettings(TypedDict):
    """Centrifugo realtime publish and token signing settings."""

    api_url: str
    api_key: str
    token_hmac_secret: str
    token_ttl_seconds: NotRequired[int]


class Dependencies(TypedDict):
    """External backing infrastructure dependencies."""

    postgres: PostgresSettings
    temporal: TemporalSettings
    spicedb: SpiceDBSettings
    qdrant: QdrantSettings
    s3: S3Settings
    redis: RedisSettings
    centrifugo: NotRequired[CentrifugoSettings]


class PlatformSettings(TypedDict):
    """Platform service configuration."""

    database: DatabaseSettings
    grpc_listen: str
    grpc_target: str
    max_members: int
    default_quota_bytes: int
    invitation_ttl_seconds: int
    idempotency_retention_seconds: int
    maintenance: MaintenanceSettings


class LetaToolsSettings(TypedDict):
    """Optional feature toggles for Leta built-in tools."""

    hitl: NotRequired[bool]
    subagents: NotRequired[bool]
    schedule: NotRequired[bool]
    web: NotRequired[bool]
    bash: NotRequired[bool]
    semantic_search: NotRequired[bool]
    todo: NotRequired[bool]
    react: NotRequired[bool]


class LetaModelRetrySettings(TypedDict):
    """Model call retry and backoff configuration."""

    max_attempts: int
    initial_interval_seconds: float
    max_interval_seconds: float
    retry_after_max_seconds: float
    timeout_max_retries: int
    unreachable_gap_max_seconds: float
    unreachable_window_seconds: float
    one_shot_retries: int


class LetaModelSettings(TypedDict):
    """Leta model token budgets and retry policy."""

    output_token_fallback: int
    output_token_max: int
    output_token_min: int
    estimate_error_margin: float
    window_headroom: float
    max_length_continuations: int
    max_steps_per_run: int | None
    chars_per_token: int
    image_token_estimate: int
    pdf_token_estimate: int
    retry: LetaModelRetrySettings


class LetaCompactionBackgroundSettings(TypedDict):
    """Background compaction precomputation settings."""

    enabled: bool
    precompute_lead_tokens: int
    tail_share: float
    cache_lifetime_seconds: int
    cache_margin_seconds: int
    max_failures: int


class LetaCompactionSettings(TypedDict):
    """Context compaction thresholds and clipping limits."""

    auto: bool
    reserve_share: float
    reserve_min_tokens: int
    unknown_window_tokens: int
    summary_output_floor: int
    keep_recent_tokens: int
    recent_tool_output_max_chars: int
    transcript_clip_chars: int
    shrink_steps: list[float]
    snapshot_max_subagents: int
    snapshot_max_idle_subagents: int
    background: LetaCompactionBackgroundSettings


class LetaToolOutputSettings(TypedDict):
    """Tool output truncation, spilling, and repair settings."""

    max_lines: int
    max_bytes: int
    max_line_length: int
    spill_dir: str
    retention_days: int
    input_repair_max_depth: int
    input_excerpt_limit: int


class LetaFileToolsSettings(TypedDict):
    """File reading, editing, and search tool limits."""

    read_tail_lines: int
    edit_miss_hint_lines: int
    edit_miss_hint_line_length: int
    search_default_limit: int
    search_timeout_seconds: int


class LetaBashSettings(TypedDict):
    """Sandbox bash tool execution and network policy."""

    default_timeout_seconds: int
    max_timeout_seconds: int
    python_max_memory: str
    network: Literal["public_only", False]
    shared_mount_read_policy: Literal["fresh", "bounded"]


class LetaMediaSettings(TypedDict):
    """Media ingestion and image transcoding thresholds."""

    max_ingest_bytes: int
    image_auto_resize: bool
    image_max_width: int
    image_max_height: int
    image_max_base64_bytes: int
    png_passthrough_max_base64_bytes: int
    small_png_max_pixels: int
    jpeg_qualities: list[int]
    history_image_bytes_trigger: int
    history_image_bytes_target: int


class LetaWebSettings(TypedDict):
    """Web fetch and search policy settings."""

    fetch_mode: Literal["direct", "tinyfish", "direct_with_fallback"]
    fetch_default_timeout_seconds: int
    fetch_max_timeout_seconds: int
    fetch_max_redirects: int
    fetch_max_response_bytes: int
    search_max_results: int


class WebSearchSettings(TypedDict):
    """Web search provider credentials."""

    api_key: str


class LetaSubagentsSettings(TypedDict):
    """Subagent recursion depth and concurrency limits."""

    max_depth: int
    max_active_per_leta: int


class LetaMessagingSettings(TypedDict):
    """Agent messaging attachment and notification limits."""

    max_attachments: int
    max_sources: int
    active_channel_ttl_seconds: int
    notification_preview_chars: int


class LetaOrchestrationSettings(TypedDict):
    """Temporal orchestration timeouts, leases, and concurrency."""

    run_timeout_seconds: int
    heartbeat_interval_seconds: int
    heartbeat_timeout_seconds: int
    lease_ttl_seconds: int
    lease_renew_interval_seconds: int
    max_concurrent_orchestration_activities: int
    max_concurrent_runtime_activities: int


class LetaSettings(TypedDict):
    """Leta agent service configuration."""

    http_listen: str
    http_target: str
    grpc_listen: NotRequired[str]
    grpc_target: NotRequired[str]
    database: DatabaseSettings
    tools: NotRequired[LetaToolsSettings]
    model: NotRequired[LetaModelSettings]
    compaction: NotRequired[LetaCompactionSettings]
    tool_output: NotRequired[LetaToolOutputSettings]
    file_tools: NotRequired[LetaFileToolsSettings]
    bash: NotRequired[LetaBashSettings]
    media: NotRequired[LetaMediaSettings]
    web: NotRequired[LetaWebSettings]
    web_search: NotRequired[WebSearchSettings]
    subagents: NotRequired[LetaSubagentsSettings]
    messaging: NotRequired[LetaMessagingSettings]
    orchestration: NotRequired[LetaOrchestrationSettings]


class GatewaySettings(TypedDict):
    """HTTP API gateway configuration."""

    http_listen: str
    public_url: NotRequired[str]


class Services(TypedDict):
    """Per-service configuration sections."""

    platform: PlatformSettings
    letfs: LetFSSettings
    letfs_ingest: IngestSettings
    chat: NotRequired[ChatSettings]
    leta: LetaSettings
    gateway: GatewaySettings


class PostgresDeployment(TypedDict):
    """PostgreSQL bootstrap admin credentials."""

    admin_user: str
    admin_password: str


class SpiceDBDeployment(TypedDict):
    """SpiceDB bootstrap database configuration."""

    database: DatabaseSettings


class TemporalDeployment(TypedDict):
    """Temporal bootstrap database and retention configuration."""

    database: DatabaseSettings
    visibility_database: str
    namespace_retention_hours: int


class Deployment(TypedDict):
    """Infrastructure bootstrap deployment settings."""

    postgres: PostgresDeployment
    temporal: TemporalDeployment
    spicedb: SpiceDBDeployment


class GrpcSettings(TypedDict):
    """Shared gRPC message limits."""

    max_receive_bytes: int


class ClerkSettings(TypedDict):
    """Clerk JWT and user directory settings."""

    issuer: str
    jwks_url: str
    audience: str
    user_id_metadata_key: NotRequired[str]
    api_url: str
    secret_key: str


class AuthSettings(TypedDict):
    """Authentication provider settings."""

    clerk: ClerkSettings


class LangfuseSettings(TypedDict):
    """Langfuse tracing and prompt management settings."""

    base_url: str
    public_key: str
    secret_key: str
    prompt_label: str


class CloudSignal(TypedDict):
    """Grafana Cloud OTLP endpoint and tenant user."""

    endpoint: str
    user: str


class ObservabilitySettings(TypedDict):
    """Grafana Cloud observability and database exporter settings."""

    metrics: CloudSignal
    traces: CloudSignal
    logs: CloudSignal
    token: str
    postgres_user: str
    postgres_password: str


class Config(TypedDict):
    """Root Openlet configuration document."""

    runtime: RuntimeSettings
    grpc: GrpcSettings
    telemetry: TelemetrySettings
    auth: AuthSettings
    dependencies: Dependencies
    models: ModelsSettings
    services: Services
    deployment: Deployment
    langfuse: NotRequired[LangfuseSettings]
    observability: NotRequired[ObservabilitySettings]


def parse_config(value: object) -> Config:
    """Validate that a parsed YAML object is a string-keyed mapping."""
    if not is_str_mapping(value) or not isinstance(value, dict):
        raise ValueError("configuration must be a YAML mapping")
    # The owning process validates the settings it consumes, not other services.
    return cast("Config", value)


def load_path(path: Path) -> Config:
    """Load and parse a YAML configuration file from ``path``."""
    with path.open(encoding="utf-8") as stream:
        return parse_config(yaml.safe_load(stream))


def load() -> Config:
    """Load configuration from the ``OPENLET_CONFIG`` environment variable."""
    return load_path(Path(os.environ["OPENLET_CONFIG"]))


def secret(value: str) -> str:
    """Resolve a ``${ENV_VARIABLE}`` scalar secret reference."""
    if not (value.startswith("${") and value.endswith("}")):
        raise ValueError("secret must reference a whole ${ENV_VARIABLE} scalar")
    key = value[2:-1]
    result = os.environ[key]
    if not result:
        raise ValueError(f"empty required environment variable {key}")
    return result
