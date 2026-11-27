"""OpenTelemetry and Langfuse observability setup and trace data masking."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from urllib.parse import quote

from openlet_sdk.telemetry import initialize, initialize_langfuse
from openlet_sdk.types import is_mapping, is_object_list
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import FastAPI
    from langfuse import Langfuse
    from openlet_sdk.config import Config

logger = logging.getLogger(__name__)


def mask_trace_data(*, data: object, **kwargs: object) -> object:
    """Strip inline base64 image payloads before exporting observations to Langfuse."""
    _ = kwargs
    if isinstance(data, str):
        if data.startswith("data:image/") and ";base64," in data:
            prefix = data.split(";base64,", 1)[0]
            return f"{prefix};base64,[omitted {len(data)} chars]"
        return data
    if is_object_list(data):
        return [mask_trace_data(data=item) for item in data]
    if is_mapping(data):
        return {k: mask_trace_data(data=v) for k, v in data.items()}
    return data


def build_rag_baggage(*, session_id: str, agent_id: str, workspace_id: str) -> str:
    """Build W3C baggage header exclusively for LetFS SemanticSearch attribution."""
    pairs = [
        ("langfuse_session_id", quote(session_id, safe="")),
        ("langfuse_metadata_agent_id", quote(json.dumps(agent_id), safe="")),
        ("langfuse_metadata_workspace_id", quote(json.dumps(workspace_id), safe="")),
    ]
    return ",".join(f"{k}={v}" for k, v in pairs)


def setup_observability(
    service_name: str, cfg: Config
) -> tuple[Callable[[], None], Langfuse | None]:
    """Initialize OTel (traces, metrics, gRPC, HTTPX, Psycopg) and Langfuse v5."""
    otel_shutdown = initialize(service_name, cfg["runtime"], cfg["telemetry"])
    PsycopgInstrumentor().instrument()

    lf: Langfuse | None = None
    if lf_cfg := cfg.get("langfuse"):
        lf = initialize_langfuse(lf_cfg, cfg["runtime"], mask=mask_trace_data)

    def shutdown() -> None:
        if lf is not None:
            try:
                lf.flush()
                lf.shutdown()
            except Exception:  # Best-effort telemetry flush/shutdown must not fail exit
                logger.warning("langfuse shutdown failed", exc_info=True)
        otel_shutdown()

    return shutdown, lf


def instrument_fastapi(app: FastAPI) -> None:
    """Attach OpenTelemetry instrumentation to the FastAPI application."""
    FastAPIInstrumentor.instrument_app(app, excluded_urls="ready,health")
