import argparse
import asyncio
import logging
import signal
from datetime import timedelta
from importlib import import_module

from openlet.clients.letfs import ProcessingClient
from openlet.rpc import RpcClient
from openlet.telemetry import configure
from openlet.temporal import connect
from temporalio.worker import Worker

from letfs_ingest.clients.openrouter import AISettings, OpenRouter
from letfs_ingest.clients.qdrant import IndexSettings
from letfs_ingest.config import WorkerConfig
from letfs_ingest.parser.text_split import layout_limits
from letfs_ingest.processing.processor import Processor
from letfs_ingest.temporal.activities import Activities


async def main(role):
    config = WorkerConfig.from_env(role)
    models = None
    ai = None
    index_settings = None
    if role == "cpu":
        layout_limits()
        models = config.models
        if not models.is_dir():
            raise ValueError("offline models are missing")
        try:
            import_module("onnxruntime")
        except ImportError as error:
            raise RuntimeError(
                "OCR runtime unavailable; install locked processor dependencies"
            ) from error
    async with configure("openlet-letfs-ingest", role) as (tracing, runtime):
        if role == "io":
            index_settings = IndexSettings.from_env()
            ai = OpenRouter(AISettings.from_env())
        try:
            processor = Processor(models, ai, index_settings)
            client = await connect(
                config.temporal_address,
                config.temporal_namespace,
                interceptor=tracing,
                runtime=runtime,
            )
            async with RpcClient(
                config.rpc_address,
                config.rpc_token,
                allow_plaintext=config.allow_plaintext,
            ) as rpc:
                activities = Activities(processor, ProcessingClient(rpc))
                worker = Worker(
                    client,
                    task_queue=f"openlet-letfs-{role}",
                    activities=(
                        [activities.process_file]
                        if role == "cpu"
                        else [activities.enrich_file, activities.index_file]
                    ),
                    max_concurrent_activities=1 if role == "cpu" else 4,
                    max_concurrent_activity_task_polls=1 if role == "cpu" else 2,
                    graceful_shutdown_timeout=timedelta(seconds=20),
                    max_heartbeat_throttle_interval=timedelta(seconds=5),
                )
                stopped = asyncio.Event()
                loop = asyncio.get_running_loop()
                for sig in (signal.SIGTERM, signal.SIGINT):
                    loop.add_signal_handler(sig, stopped.set)
                try:
                    async with worker:
                        logging.getLogger(__name__).info("processing worker polling")
                        await stopped.wait()
                finally:
                    for sig in (signal.SIGTERM, signal.SIGINT):
                        loop.remove_signal_handler(sig)
        finally:
            if ai is not None:
                await ai.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a Letfs processing worker")
    parser.add_argument("role", choices=("cpu", "io"))
    asyncio.run(main(parser.parse_args().role))
