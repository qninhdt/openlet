import os
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast

import yaml

from .types import (
    JSON as JSON,
)
from .types import (
    JsonObject as JsonObject,
)
from .types import (
    MutableJsonObject as MutableJsonObject,
)

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


class LetFSSearchSettings(TypedDict):
    default_limit: int
    max_limit: int
    timeout_seconds: int
    max_line_chars: int


class SemanticSearchSettings(TypedDict):
    candidate_limit: int
    result_limit: int
    max_result_limit: NotRequired[int]
    timeout_seconds: NotRequired[int]
    max_excerpt_chars: NotRequired[int]


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
    search: NotRequired[LetFSSearchSettings]
    semantic_search: SemanticSearchSettings
    processing: ProcessingSettings
    maintenance: MaintenanceSettings


class ChatOutboxSettings(TypedDict):
    batch_size: int
    poll_interval_seconds: int
    max_backoff_seconds: int
    retention_hours: int


class ChatSettings(TypedDict):
    grpc_listen: str
    grpc_target: str
    database: DatabaseSettings
    outbox: NotRequired[ChatOutboxSettings]


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
    leta_orchestration: str
    leta_runtime: str


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


class CentrifugoSettings(TypedDict):
    api_url: str
    api_key: str
    token_hmac_secret: str
    token_ttl_seconds: NotRequired[int]


class Dependencies(TypedDict):
    postgres: PostgresSettings
    temporal: TemporalSettings
    spicedb: SpiceDBSettings
    qdrant: QdrantSettings
    s3: S3Settings
    redis: RedisSettings
    centrifugo: NotRequired[CentrifugoSettings]


class PlatformSettings(TypedDict):
    database: DatabaseSettings
    grpc_listen: str
    grpc_target: str
    max_members: int
    default_quota_bytes: int
    invitation_ttl_seconds: int
    idempotency_retention_seconds: int
    maintenance: MaintenanceSettings


class LetaToolsSettings(TypedDict):
    hitl: NotRequired[bool]
    subagents: NotRequired[bool]
    schedule: NotRequired[bool]
    web: NotRequired[bool]
    bash: NotRequired[bool]
    semantic_search: NotRequired[bool]
    todo: NotRequired[bool]
    react: NotRequired[bool]


class LetaModelRetrySettings(TypedDict):
    max_attempts: int
    initial_interval_seconds: float
    max_interval_seconds: float
    retry_after_max_seconds: float
    timeout_max_retries: int
    unreachable_gap_max_seconds: float
    unreachable_window_seconds: float
    one_shot_retries: int


class LetaModelSettings(TypedDict):
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
    enabled: bool
    precompute_lead_tokens: int
    tail_share: float
    cache_lifetime_seconds: int
    cache_margin_seconds: int
    max_failures: int


class LetaCompactionSettings(TypedDict):
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
    max_lines: int
    max_bytes: int
    max_line_length: int
    spill_dir: str
    retention_days: int
    input_repair_max_depth: int
    input_excerpt_limit: int


class LetaFileToolsSettings(TypedDict):
    read_tail_lines: int
    edit_miss_hint_lines: int
    edit_miss_hint_line_length: int
    search_default_limit: int
    search_timeout_seconds: int


class LetaBashSettings(TypedDict):
    default_timeout_seconds: int
    max_timeout_seconds: int
    python_max_memory: str
    network: Literal["public_only", False]
    shared_mount_read_policy: Literal["fresh", "bounded"]


class LetaMediaSettings(TypedDict):
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
    fetch_mode: Literal["direct", "tinyfish", "direct_with_fallback"]
    fetch_default_timeout_seconds: int
    fetch_max_timeout_seconds: int
    fetch_max_redirects: int
    fetch_max_response_bytes: int
    search_max_results: int


class WebSearchSettings(TypedDict):
    api_key: str


class LetaSubagentsSettings(TypedDict):
    max_depth: int
    max_active_per_leta: int


class LetaMessagingSettings(TypedDict):
    max_attachments: int
    max_sources: int
    active_channel_ttl_seconds: int
    notification_preview_chars: int


class LetaOrchestrationSettings(TypedDict):
    run_timeout_seconds: int
    heartbeat_interval_seconds: int
    heartbeat_timeout_seconds: int
    lease_ttl_seconds: int
    lease_renew_interval_seconds: int
    max_concurrent_orchestration_activities: int
    max_concurrent_runtime_activities: int


class LetaSettings(TypedDict):
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


class Services(TypedDict):
    platform: PlatformSettings
    letfs: LetFSSettings
    letfs_ingest: IngestSettings
    chat: NotRequired[ChatSettings]
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


def parse_config(value: object) -> Config:
    if not isinstance(value, dict):
        raise ValueError("configuration must be a YAML mapping")
    # The owning process validates the settings it consumes, not other services.
    return cast("Config", value)


def load_path(path: Path) -> Config:
    with path.open(encoding="utf-8") as stream:
        return parse_config(yaml.safe_load(stream))


def load() -> Config:
    return load_path(Path(os.environ["OPENLET_CONFIG"]))


def secret(value: str) -> str:
    if not (value.startswith("${") and value.endswith("}")):
        raise ValueError("secret must reference a whole ${ENV_VARIABLE} scalar")
    key = value[2:-1]
    result = os.environ[key]
    if not result:
        raise ValueError(f"empty required environment variable {key}")
    return result
