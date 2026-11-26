from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Literal

import grpc.aio
import httpx
import redis.asyncio as aioredis
from openlet_sdk.config import Config, ReasoningEffort, load, secret
from pydantic import BaseModel, Field
from temporalio.client import Client as TemporalClient
from temporalio.contrib.pydantic import pydantic_data_converter

if TYPE_CHECKING:
    from openlet_api.chat.v1.chat_pb2_grpc import ChatServiceAsyncStub
    from openlet_api.chat.v1.internal_pb2_grpc import ChatInternalServiceAsyncStub
    from openlet_api.letfs.v1.internal_pb2_grpc import LetFSInternalServiceAsyncStub
    from openlet_api.letfs.v1.letfs_pb2_grpc import LetFSServiceAsyncStub
    from openlet_api.platform.v1.internal_pb2_grpc import (
        PlatformInternalServiceAsyncStub,
    )
    from openlet_api.platform.v1.platform_pb2_grpc import PlatformServiceAsyncStub

    from .activity import ActivityEmitter, CentrifugoPublisher
    from .auth import Authorization
    from .db import Pool
    from .inbox import InboxGateway


@dataclass(frozen=True, slots=True)
class ToolFlags:
    hitl: bool = True
    subagents: bool = True
    schedule: bool = True
    web: bool = True
    bash: bool = True
    semantic_search: bool = True
    todo: bool = False
    react: bool = True


@dataclass(frozen=True, slots=True)
class ModelRetryConfig:
    max_attempts: int = 10
    initial_interval_seconds: float = 2.0
    max_interval_seconds: float = 10.0
    retry_after_max_seconds: float = 900.0
    timeout_max_retries: int = 3
    unreachable_gap_max_seconds: float = 30.0
    unreachable_window_seconds: float = 3600.0
    one_shot_retries: int = 3


@dataclass(frozen=True, slots=True)
class ModelConfig:
    output_token_fallback: int = 32000
    output_token_max: int = 256000
    output_token_min: int = 1024
    estimate_error_margin: float = 0.15
    window_headroom: float = 0.01
    max_length_continuations: int = 2
    max_steps_per_run: int | None = None
    chars_per_token: int = 4
    image_token_estimate: int = 1500
    pdf_token_estimate: int = 2000
    retry: ModelRetryConfig = field(default_factory=ModelRetryConfig)


@dataclass(frozen=True, slots=True)
class CompactionBackgroundConfig:
    enabled: bool = True
    precompute_lead_tokens: int = 60000
    tail_share: float = 0.4
    cache_lifetime_seconds: int = 300
    cache_margin_seconds: int = 30
    max_failures: int = 2


@dataclass(frozen=True, slots=True)
class CompactionConfig:
    auto: bool = True
    reserve_share: float = 0.15
    reserve_min_tokens: int = 16000
    unknown_window_tokens: int = 200000
    summary_output_floor: int = 32000
    keep_recent_tokens: int = 15000
    recent_tool_output_max_chars: int = 1250
    transcript_clip_chars: int = 2000
    shrink_steps: tuple[float, ...] = (0.85, 0.7, 0.5, 0.35)
    snapshot_max_subagents: int = 20
    snapshot_max_idle_subagents: int = 10
    background: CompactionBackgroundConfig = field(
        default_factory=CompactionBackgroundConfig
    )


@dataclass(frozen=True, slots=True)
class ToolOutputConfig:
    max_lines: int = 2000
    max_bytes: int = 51200
    max_line_length: int = 2000
    spill_dir: str = "/home/.tool-output"
    retention_days: int = 7
    input_repair_max_depth: int = 6
    input_excerpt_limit: int = 2048


@dataclass(frozen=True, slots=True)
class FileToolsConfig:
    read_tail_lines: int = 100
    edit_miss_hint_lines: int = 12
    edit_miss_hint_line_length: int = 200
    search_default_limit: int = 100
    search_timeout_seconds: int = 30


@dataclass(frozen=True, slots=True)
class BashConfig:
    default_timeout_seconds: int = 120
    max_timeout_seconds: int = 600
    python_max_memory: str = "256MB"
    network: Literal["public_only", False] = "public_only"
    shared_mount_read_policy: Literal["fresh", "bounded"] = "fresh"


@dataclass(frozen=True, slots=True)
class MediaConfig:
    max_ingest_bytes: int = 20971520
    image_auto_resize: bool = True
    image_max_width: int = 2000
    image_max_height: int = 2000
    image_max_base64_bytes: int = 5242880
    png_passthrough_max_base64_bytes: int = 393216
    small_png_max_pixels: int = 65536
    jpeg_qualities: tuple[int, ...] = (80, 70, 55, 40)
    history_image_bytes_trigger: int = 26214400
    history_image_bytes_target: int = 15728640


@dataclass(frozen=True, slots=True)
class WebConfig:
    fetch_mode: Literal["direct", "tinyfish", "direct_with_fallback"] = (
        "direct_with_fallback"
    )
    fetch_default_timeout_seconds: int = 30
    fetch_max_timeout_seconds: int = 120
    fetch_max_redirects: int = 10
    fetch_max_response_bytes: int = 5242880
    search_max_results: int = 5


@dataclass(frozen=True, slots=True)
class SubagentsConfig:
    max_depth: int = 3
    max_active_per_leta: int = 16


@dataclass(frozen=True, slots=True)
class MessagingConfig:
    max_attachments: int = 20
    max_sources: int = 64
    active_channel_ttl_seconds: int = 300
    notification_preview_chars: int = 120


@dataclass(frozen=True, slots=True)
class OrchestrationConfig:
    run_timeout_seconds: int = 7200
    heartbeat_interval_seconds: int = 3
    heartbeat_timeout_seconds: int = 60
    lease_ttl_seconds: int = 60
    lease_renew_interval_seconds: int = 10
    max_concurrent_orchestration_activities: int = 64
    max_concurrent_runtime_activities: int = 32


@dataclass(frozen=True, slots=True)
class QueueNames:
    orchestration: str = "openlet-leta-orchestration"
    runtime: str = "openlet-leta-runtime"


@dataclass(frozen=True, slots=True)
class LetaRuntimeConfig:
    http_listen: str = "0.0.0.0:8000"
    grpc_listen: str = "0.0.0.0:9091"
    tools: ToolFlags = field(default_factory=ToolFlags)
    model: ModelConfig = field(default_factory=ModelConfig)
    compaction: CompactionConfig = field(default_factory=CompactionConfig)
    tool_output: ToolOutputConfig = field(default_factory=ToolOutputConfig)
    file_tools: FileToolsConfig = field(default_factory=FileToolsConfig)
    bash: BashConfig = field(default_factory=BashConfig)
    media: MediaConfig = field(default_factory=MediaConfig)
    web: WebConfig = field(default_factory=WebConfig)
    subagents: SubagentsConfig = field(default_factory=SubagentsConfig)
    messaging: MessagingConfig = field(default_factory=MessagingConfig)
    orchestration: OrchestrationConfig = field(default_factory=OrchestrationConfig)
    queues: QueueNames = field(default_factory=QueueNames)
    web_search_api_key: str | None = None

    @classmethod
    def from_openlet_config(cls, cfg: Config) -> LetaRuntimeConfig:
        leta = cfg["services"]["leta"]
        queues = cfg["dependencies"]["temporal"]["queues"]

        t = leta.get("tools", {})
        tools = ToolFlags(
            hitl=bool(t.get("hitl", True)),
            subagents=bool(t.get("subagents", True)),
            schedule=bool(t.get("schedule", True)),
            web=bool(t.get("web", True)),
            bash=bool(t.get("bash", True)),
            semantic_search=bool(t.get("semantic_search", True)),
            todo=bool(t.get("todo", False)),
            react=bool(t.get("react", True)),
        )

        m = leta.get("model")
        if m is not None:
            r = m["retry"]
            model = ModelConfig(
                output_token_fallback=int(m["output_token_fallback"]),
                output_token_max=int(m["output_token_max"]),
                output_token_min=int(m["output_token_min"]),
                estimate_error_margin=float(m["estimate_error_margin"]),
                window_headroom=float(m["window_headroom"]),
                max_length_continuations=int(m["max_length_continuations"]),
                max_steps_per_run=m["max_steps_per_run"],
                chars_per_token=int(m["chars_per_token"]),
                image_token_estimate=int(m["image_token_estimate"]),
                pdf_token_estimate=int(m["pdf_token_estimate"]),
                retry=ModelRetryConfig(
                    max_attempts=int(r["max_attempts"]),
                    initial_interval_seconds=float(r["initial_interval_seconds"]),
                    max_interval_seconds=float(r["max_interval_seconds"]),
                    retry_after_max_seconds=float(r["retry_after_max_seconds"]),
                    timeout_max_retries=int(r["timeout_max_retries"]),
                    unreachable_gap_max_seconds=float(r["unreachable_gap_max_seconds"]),
                    unreachable_window_seconds=float(r["unreachable_window_seconds"]),
                    one_shot_retries=int(r["one_shot_retries"]),
                ),
            )
        else:
            model = ModelConfig()

        comp = leta.get("compaction")
        if comp is not None:
            bg = comp["background"]
            compaction = CompactionConfig(
                auto=bool(comp["auto"]),
                reserve_share=float(comp["reserve_share"]),
                reserve_min_tokens=int(comp["reserve_min_tokens"]),
                unknown_window_tokens=int(comp["unknown_window_tokens"]),
                summary_output_floor=int(comp["summary_output_floor"]),
                keep_recent_tokens=int(comp["keep_recent_tokens"]),
                recent_tool_output_max_chars=int(comp["recent_tool_output_max_chars"]),
                transcript_clip_chars=int(comp["transcript_clip_chars"]),
                shrink_steps=tuple(float(x) for x in comp["shrink_steps"]),
                snapshot_max_subagents=int(comp["snapshot_max_subagents"]),
                snapshot_max_idle_subagents=int(comp["snapshot_max_idle_subagents"]),
                background=CompactionBackgroundConfig(
                    enabled=bool(bg["enabled"]),
                    precompute_lead_tokens=int(bg["precompute_lead_tokens"]),
                    tail_share=float(bg["tail_share"]),
                    cache_lifetime_seconds=int(bg["cache_lifetime_seconds"]),
                    cache_margin_seconds=int(bg["cache_margin_seconds"]),
                    max_failures=int(bg["max_failures"]),
                ),
            )
        else:
            compaction = CompactionConfig()

        to = leta.get("tool_output")
        tool_output = (
            ToolOutputConfig(
                max_lines=int(to["max_lines"]),
                max_bytes=int(to["max_bytes"]),
                max_line_length=int(to["max_line_length"]),
                spill_dir=str(to["spill_dir"]),
                retention_days=int(to["retention_days"]),
                input_repair_max_depth=int(to["input_repair_max_depth"]),
                input_excerpt_limit=int(to["input_excerpt_limit"]),
            )
            if to is not None
            else ToolOutputConfig()
        )

        ft = leta.get("file_tools")
        file_tools = (
            FileToolsConfig(
                read_tail_lines=int(ft["read_tail_lines"]),
                edit_miss_hint_lines=int(ft["edit_miss_hint_lines"]),
                edit_miss_hint_line_length=int(ft["edit_miss_hint_line_length"]),
                search_default_limit=int(ft["search_default_limit"]),
                search_timeout_seconds=int(ft["search_timeout_seconds"]),
            )
            if ft is not None
            else FileToolsConfig()
        )

        bs = leta.get("bash")
        if bs is not None:
            raw_net = bs["network"]
            net_val: Literal["public_only", False] = (
                "public_only" if raw_net == "public_only" else False
            )
            bash = BashConfig(
                default_timeout_seconds=int(bs["default_timeout_seconds"]),
                max_timeout_seconds=int(bs["max_timeout_seconds"]),
                python_max_memory=str(bs["python_max_memory"]),
                network=net_val,
                shared_mount_read_policy=bs["shared_mount_read_policy"],
            )
        else:
            bash = BashConfig()

        md = leta.get("media")
        media = (
            MediaConfig(
                max_ingest_bytes=int(md["max_ingest_bytes"]),
                image_auto_resize=bool(md["image_auto_resize"]),
                image_max_width=int(md["image_max_width"]),
                image_max_height=int(md["image_max_height"]),
                image_max_base64_bytes=int(md["image_max_base64_bytes"]),
                png_passthrough_max_base64_bytes=int(
                    md["png_passthrough_max_base64_bytes"]
                ),
                small_png_max_pixels=int(md["small_png_max_pixels"]),
                jpeg_qualities=tuple(int(q) for q in md["jpeg_qualities"]),
                history_image_bytes_trigger=int(md["history_image_bytes_trigger"]),
                history_image_bytes_target=int(md["history_image_bytes_target"]),
            )
            if md is not None
            else MediaConfig()
        )

        wb = leta.get("web")
        web = (
            WebConfig(
                fetch_mode=wb["fetch_mode"],
                fetch_default_timeout_seconds=int(wb["fetch_default_timeout_seconds"]),
                fetch_max_timeout_seconds=int(wb["fetch_max_timeout_seconds"]),
                fetch_max_redirects=int(wb["fetch_max_redirects"]),
                fetch_max_response_bytes=int(wb["fetch_max_response_bytes"]),
                search_max_results=int(wb["search_max_results"]),
            )
            if wb is not None
            else WebConfig()
        )

        sa = leta.get("subagents")
        subagents = (
            SubagentsConfig(
                max_depth=int(sa["max_depth"]),
                max_active_per_leta=int(sa["max_active_per_leta"]),
            )
            if sa is not None
            else SubagentsConfig()
        )

        ms = leta.get("messaging")
        messaging = (
            MessagingConfig(
                max_attachments=int(ms["max_attachments"]),
                max_sources=int(ms["max_sources"]),
                active_channel_ttl_seconds=int(ms["active_channel_ttl_seconds"]),
                notification_preview_chars=int(ms["notification_preview_chars"]),
            )
            if ms is not None
            else MessagingConfig()
        )

        orch = leta.get("orchestration")
        orchestration = (
            OrchestrationConfig(
                run_timeout_seconds=int(orch["run_timeout_seconds"]),
                heartbeat_interval_seconds=int(orch["heartbeat_interval_seconds"]),
                heartbeat_timeout_seconds=int(orch["heartbeat_timeout_seconds"]),
                lease_ttl_seconds=int(orch["lease_ttl_seconds"]),
                lease_renew_interval_seconds=int(orch["lease_renew_interval_seconds"]),
                max_concurrent_orchestration_activities=int(
                    orch["max_concurrent_orchestration_activities"]
                ),
                max_concurrent_runtime_activities=int(
                    orch["max_concurrent_runtime_activities"]
                ),
            )
            if orch is not None
            else OrchestrationConfig()
        )

        ws_key: str | None = None
        if ws_cfg := leta.get("web_search"):
            ws_key = secret(ws_cfg["api_key"])

        return cls(
            http_listen=leta["http_listen"],
            grpc_listen=leta.get("grpc_listen", "0.0.0.0:9091"),
            tools=tools,
            model=model,
            compaction=compaction,
            tool_output=tool_output,
            file_tools=file_tools,
            bash=bash,
            media=media,
            web=web,
            subagents=subagents,
            messaging=messaging,
            orchestration=orchestration,
            queues=QueueNames(
                orchestration=queues["leta_orchestration"],
                runtime=queues["leta_runtime"],
            ),
            web_search_api_key=ws_key,
        )


class ModelInfoPayload(BaseModel):
    access_groups: list[str] | None = None
    max_input_tokens: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    supported_reasoning_efforts: list[ReasoningEffort] | None = None
    input_cost_per_token: float | None = None
    cache_read_input_token_cost: float | None = None
    output_cost_per_token: float | None = None


class ModelDeploymentPayload(BaseModel):
    model_name: str
    model_info: ModelInfoPayload


class ModelListPayload(BaseModel):
    data: list[ModelDeploymentPayload]


class ModelSpec(BaseModel):
    model_id: str
    reasoning_efforts: list[ReasoningEffort]
    context_window_tokens: int
    max_output_tokens: int
    input_cost_per_token: float = 0.0
    cache_read_input_token_cost: float = 0.0
    output_cost_per_token: float = 0.0


class ModelCatalog:
    def __init__(self, client: httpx.AsyncClient, fallback_output: int = 32000) -> None:
        self.client = client
        self.fallback_output = fallback_output
        self._items: dict[str, ModelSpec] = {}
        self._expires: float = 0.0
        self._lock = asyncio.Lock()

    async def catalog(self) -> dict[str, ModelSpec]:
        if monotonic() < self._expires:
            return self._items
        async with self._lock:
            if monotonic() < self._expires:
                return self._items
            resp = await self.client.get("/model/info")
            resp.raise_for_status()
            groups: dict[str, ModelSpec] = {}
            for dep in ModelListPayload.model_validate(resp.json()).data:
                info = dep.model_info
                if "leta" not in (info.access_groups or []):
                    continue
                if info.max_input_tokens is None:
                    continue
                item = ModelSpec(
                    model_id=dep.model_name,
                    reasoning_efforts=list(
                        dict.fromkeys([None, *(info.supported_reasoning_efforts or [])])
                    ),
                    context_window_tokens=info.max_input_tokens,
                    max_output_tokens=info.max_output_tokens or self.fallback_output,
                    input_cost_per_token=info.input_cost_per_token or 0.0,
                    cache_read_input_token_cost=info.cache_read_input_token_cost or 0.0,
                    output_cost_per_token=info.output_cost_per_token or 0.0,
                )
                if existing := groups.get(item.model_id):
                    item.context_window_tokens = min(
                        item.context_window_tokens, existing.context_window_tokens
                    )
                    item.max_output_tokens = min(
                        item.max_output_tokens, existing.max_output_tokens
                    )
                    item.reasoning_efforts = [
                        e
                        for e in item.reasoning_efforts
                        if e in existing.reasoning_efforts
                    ]
                groups[item.model_id] = item
            self._items = groups
            self._expires = monotonic() + 60.0
            return groups

    async def get(self, model_id: str | None, effort: ReasoningEffort) -> ModelSpec:
        if not model_id:
            item = await self.default_model()
        else:
            item = (await self.catalog()).get(model_id)
            if item is None:
                raise ValueError(f"unknown model: {model_id}")
        if effort not in item.reasoning_efforts:
            raise ValueError(
                f"unsupported reasoning_effort {effort!r} for model {item.model_id}"
            )
        return item

    async def default_model(self) -> ModelSpec:
        cat = await self.catalog()
        if not cat:
            raise ValueError("no leta models configured in gateway")
        return next(iter(cat.values()))


def prompts_dir() -> Path:
    candidates = [
        Path("/app/prompts"),
        Path(__file__).resolve().parents[2] / "prompts",
    ]
    for p in candidates:
        if p.is_dir():
            return p
    return candidates[-1]


class Services:
    """Process-wide dependency container shared across FastAPI, gRPC, and Temporal workers."""

    def __init__(
        self,
        *,
        config: Config,
        settings: LetaRuntimeConfig,
        db: Pool,
        temporal: TemporalClient,
        auth: Authorization,
        platform: PlatformServiceAsyncStub,
        platform_internal: PlatformInternalServiceAsyncStub,
        letfs: LetFSServiceAsyncStub,
        letfs_internal: LetFSInternalServiceAsyncStub,
        chat: ChatServiceAsyncStub,
        chat_internal: ChatInternalServiceAsyncStub,
        redis_client: aioredis.Redis,
        gateway_http: httpx.AsyncClient,
        models: ModelCatalog,
        centrifugo: CentrifugoPublisher,
        centrifugo_secret: str,
        centrifugo_ttl: int,
        activity: ActivityEmitter,
        inbox: InboxGateway,
        channels: list[grpc.aio.Channel],
    ) -> None:
        self.config = config
        self.settings = settings
        self.db = db
        self.temporal = temporal
        self.auth = auth
        self.platform = platform
        self.platform_internal = platform_internal
        self.letfs = letfs
        self.letfs_internal = letfs_internal
        self.chat = chat
        self.chat_internal = chat_internal
        self.redis = redis_client
        self.gateway_http = gateway_http
        self.models = models
        self.centrifugo = centrifugo
        self.centrifugo_secret = centrifugo_secret
        self.centrifugo_ttl = centrifugo_ttl
        self.activity = activity
        self.inbox = inbox
        self._channels = channels

    @property
    def queues(self) -> QueueNames:
        return self.settings.queues

    @classmethod
    async def create(cls, config: Config | None = None) -> Services:
        from openlet_api.chat.v1 import chat_pb2_grpc
        from openlet_api.chat.v1 import internal_pb2_grpc as chat_int
        from openlet_api.letfs.v1 import internal_pb2_grpc as letfs_int
        from openlet_api.letfs.v1 import letfs_pb2_grpc
        from openlet_api.platform.v1 import (
            internal_pb2_grpc as plat_int,
        )
        from openlet_api.platform.v1 import (
            platform_pb2_grpc,
        )

        from .activity import ActivityEmitter, CentrifugoPublisher
        from .auth import Authorization
        from .db import open_pool
        from .inbox import InboxGateway

        cfg = config or load()
        settings = LetaRuntimeConfig.from_openlet_config(cfg)
        pool = await open_pool(cfg)

        t_cfg = cfg["dependencies"]["temporal"]
        temporal = await TemporalClient.connect(
            t_cfg["address"],
            namespace=t_cfg["namespace"],
            tls=t_cfg["tls"],
            data_converter=pydantic_data_converter,
        )

        auth = Authorization.from_config(cfg)

        max_recv = cfg["grpc"]["max_receive_bytes"]
        opts = [
            ("grpc.max_receive_message_length", max_recv),
            ("grpc.max_send_message_length", max_recv),
        ]
        plat_ch = grpc.aio.insecure_channel(
            cfg["services"]["platform"]["grpc_target"], options=opts
        )
        letfs_ch = grpc.aio.insecure_channel(
            cfg["services"]["letfs"]["grpc_target"], options=opts
        )
        chat_target = cfg["services"].get("chat", {"grpc_target": "chat:9090"})[
            "grpc_target"
        ]
        chat_ch = grpc.aio.insecure_channel(chat_target, options=opts)

        r_cfg = cfg["dependencies"]["redis"]
        r_host, r_port = r_cfg["address"].rsplit(":", 1)
        redis_client: aioredis.Redis = aioredis.Redis(
            host=r_host,
            port=int(r_port),
            db=int(r_cfg["database"]),
            password=secret(r_cfg["password"]),
            decode_responses=False,
        )

        gw = cfg["models"]["gateway"]
        gateway_http = httpx.AsyncClient(
            base_url=gw["base_url"].rstrip("/"),
            headers={"Authorization": f"Bearer {secret(gw['api_key'])}"},
            timeout=float(gw["timeout_seconds"]),
        )
        models = ModelCatalog(
            gateway_http, fallback_output=settings.model.output_token_fallback
        )

        cen_cfg = cfg["dependencies"].get("centrifugo")
        cen_api_url = cen_cfg["api_url"] if cen_cfg is not None else ""
        cen_api_key = (
            secret(cen_cfg["api_key"])
            if cen_cfg is not None and cen_cfg.get("api_key")
            else ""
        )
        cen_secret = (
            secret(cen_cfg["token_hmac_secret"])
            if cen_cfg is not None and cen_cfg.get("token_hmac_secret")
            else ""
        )
        cen_ttl = (
            int(cen_cfg.get("token_ttl_seconds", 3600)) if cen_cfg is not None else 3600
        )
        centrifugo = CentrifugoPublisher(api_url=cen_api_url, api_key=cen_api_key)
        activity = ActivityEmitter(pool, centrifugo)
        inbox = InboxGateway(
            db=pool,
            temporal=temporal,
            orchestration_queue=settings.queues.orchestration,
            runtime_queue=settings.queues.runtime,
            run_timeout_seconds=settings.orchestration.run_timeout_seconds,
            heartbeat_timeout_seconds=settings.orchestration.heartbeat_timeout_seconds,
            activity=activity,
        )

        return cls(
            config=cfg,
            settings=settings,
            db=pool,
            temporal=temporal,
            auth=auth,
            platform=platform_pb2_grpc.PlatformServiceStub(plat_ch),
            platform_internal=plat_int.PlatformInternalServiceStub(plat_ch),
            letfs=letfs_pb2_grpc.LetFSServiceStub(letfs_ch),
            letfs_internal=letfs_int.LetFSInternalServiceStub(letfs_ch),
            chat=chat_pb2_grpc.ChatServiceStub(chat_ch),
            chat_internal=chat_int.ChatInternalServiceStub(chat_ch),
            redis_client=redis_client,
            gateway_http=gateway_http,
            models=models,
            centrifugo=centrifugo,
            centrifugo_secret=cen_secret,
            centrifugo_ttl=cen_ttl,
            activity=activity,
            inbox=inbox,
            channels=[plat_ch, letfs_ch, chat_ch],
        )

    async def close(self) -> None:
        await self.centrifugo.close()
        await self.gateway_http.aclose()
        await self.redis.aclose()
        for ch in self._channels:
            await ch.close()
        await self.auth.close()
        await self.db.close()
