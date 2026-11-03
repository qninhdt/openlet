import argparse
import asyncio
import logging
import os
import signal
from datetime import timedelta
from importlib import import_module
from pathlib import Path

from temporalio.client import Client
from temporalio.worker import Worker

from letfs_ingest.activity import Processor
from letfs_ingest.indexing import IndexSettings
from letfs_ingest.ingest_rpc import IngestRPC
from letfs_ingest.openrouter import AISettings, OpenRouter
from letfs_ingest.telemetry import configure
from letfs_ingest.text_split import layout_limits


async def main(role):
    address = os.environ["TEMPORAL_ADDRESS"]
    rpc_address = os.environ["LETFS_RPC_ADDRESS"]
    token = Path(os.environ["INGEST_SERVICE_TOKEN_FILE"]).read_text().strip()
    plaintext = os.environ.get("ALLOW_PLAINTEXT_RPC", "false")
    if plaintext not in {"true", "false"}:
        raise ValueError("ALLOW_PLAINTEXT_RPC must be true or false")
    async with IngestRPC(rpc_address, token, allow_plaintext=plaintext == "true"):
        pass
    models = None
    ai = None
    index_settings = None
    if role == "cpu":
        layout_limits()
        models = Path(os.environ["DOCLING_MODELS_PATH"])
        if not models.is_dir():
            raise ValueError("offline models are missing")
        try:
            import_module("onnxruntime")
        except ImportError as error:
            raise RuntimeError(
                "OCR runtime unavailable; install locked processor dependencies"
            ) from error
    async with configure(role) as (tracing, runtime):
        if role == "io":
            index_settings = IndexSettings.from_env()
            ai = OpenRouter(AISettings.from_env())
        try:
            processor = Processor(
                rpc_address,
                token,
                models,
                ai,
                index_settings,
                allow_plaintext=plaintext == "true",
            )
            client = await Client.connect(
                address,
                namespace=os.environ["TEMPORAL_NAMESPACE"],
                interceptors=[tracing],
                runtime=runtime,
            )
            worker = Worker(
                client,
                task_queue=f"openlet-letfs-{role}",
                activities=(
                    [processor.process_file]
                    if role == "cpu"
                    else [processor.enrich_file, processor.index_file]
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
