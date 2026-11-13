import argparse
import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from datetime import timedelta
from importlib.metadata import version
from typing import Literal

import httpx
from openlet_api.letfs.v1.internal_pb2_grpc import LetFSInternalServiceStub
from openlet_sdk.config import load
from openlet_sdk.rpc import channel
from openlet_sdk.telemetry import initialize
from temporalio.client import Client
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.runtime import (
    LogForwardingConfig,
    LoggingConfig,
    OpenTelemetryConfig,
    Runtime,
    TelemetryConfig,
    TelemetryFilter,
)
from temporalio.worker import Worker

from .telemetry import ProcessingIdentity


async def run(role: Literal["cpu", "io"]) -> None:
    config = load()
    runtime = config["runtime"]
    settings = config["services"]["letfs_ingest"]["cpu"] if role == "cpu" else config["services"]["letfs_ingest"]["io"]
    if settings["activity_concurrency"] < 1:
        raise ValueError("activity_concurrency must be positive")
    shutdown = initialize(f"openlet-ingest-{role}", runtime, config["telemetry"])
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    temporal = config["dependencies"]["temporal"]
    telemetry = config["telemetry"]
    metrics = OpenTelemetryConfig(
        url=telemetry["otlp_endpoint"] or "", metric_periodicity=timedelta(seconds=telemetry["metrics_export_interval_seconds"]),
    ) if telemetry["otlp_endpoint"] else None
    native = Runtime(telemetry=TelemetryConfig(
        logging=LoggingConfig(TelemetryFilter(core_level="WARN", other_level="ERROR"), forwarding=LogForwardingConfig(logging.getLogger("temporalio.core"))),
        metrics=metrics, global_tags={"worker_role": role, "service.name": f"openlet-ingest-{role}", "service.version": version("letfs-ingest"), "deployment.environment.name": runtime["environment"]},
    ))
    try:
        async with AsyncExitStack() as stack:
            rpc = await stack.enter_async_context(channel(
                config["services"]["letfs"]["grpc_target"], max_bytes=config["grpc"]["max_receive_bytes"],
            ))
            stub = LetFSInternalServiceStub(rpc)
            http = await stack.enter_async_context(httpx.AsyncClient(timeout=120))
            activities: list[Callable[[ProcessingIdentity], Awaitable[None]]]
            if role == "cpu":
                settings = config["services"]["letfs_ingest"]["cpu"]
                from .parse import Parser, run_child

                if not 0 < settings["min_section_tokens"] <= settings["split_tokens"]:
                    raise ValueError("invalid parser layout limits")
                if await run_child(["letfs_ingest.models", "check"], config["services"]["letfs"]["processing"]["parse_timeout_seconds"]):
                    raise RuntimeError("Docling models/runtime unavailable; prepare models before starting CPU worker")
                activities = [Parser(stub, http, config["services"]["letfs"]).run]
            else:
                settings = config["services"]["letfs_ingest"]["io"]
                from openlet_sdk.config import secret
                from qdrant_client import AsyncQdrantClient

                from .process import Processor
                from .providers import Models

                if not 0 <= settings["chunk_overlap_tokens"] < settings["chunk_size_tokens"] or settings["embedding_batch_size"] < 1 or settings["model_concurrency"] < 1:
                    raise ValueError("invalid indexing/model limits")
                ai = Models(config)
                stack.push_async_callback(ai.client.close)
                vector = config["dependencies"]["qdrant"]
                host, port = vector["address"].rsplit(":", 1)
                qdrant = AsyncQdrantClient(host=host, grpc_port=int(port), prefer_grpc=True, https=vector["tls"], api_key=secret(vector["api_key"]))
                stack.push_async_callback(qdrant.close)
                activities = [Processor(stub, http, ai, qdrant, config).run]
            client = await Client.connect(
                temporal["address"], namespace=temporal["namespace"], tls=temporal["tls"],
                runtime=native, interceptors=[TracingInterceptor()],
            )
            worker = Worker(
                client, task_queue=temporal["queues"]["ingest_cpu"] if role == "cpu" else temporal["queues"]["ingest_io"], activities=activities,
                max_concurrent_activities=settings["activity_concurrency"],
                graceful_shutdown_timeout=timedelta(seconds=runtime["shutdown_timeout_seconds"]),
            )
            async with worker:
                logging.getLogger(__name__).info("ingest %s started", role)
                await stop.wait()
    finally:
        shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("cpu", "io"))
    asyncio.run(run(parser.parse_args().role))
