import asyncio
import logging
import os
import signal
from datetime import timedelta
from importlib import import_module
from pathlib import Path
from urllib.parse import urlparse

from temporalio.client import Client
from temporalio.worker import Worker

from openlet_processor.activity import Processor
from openlet_processor.indexing import IndexSettings
from openlet_processor.openrouter import AISettings, OpenRouter
from openlet_processor.text_split import layout_limits


async def main():
    layout_limits()
    address = os.environ["TEMPORAL_ADDRESS"].removeprefix("http://")
    base_url = os.environ["LETFS_URL"]
    parsed = urlparse(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid LETFS_URL")
    token = Path(os.environ["PROCESSOR_SERVICE_TOKEN_FILE"]).read_text().strip()
    if len(token) < 32 or any(
        not (c.isascii() and (c.isalnum() or c in "-_")) for c in token
    ):
        raise ValueError("invalid processor token")
    models = Path(os.environ["DOCLING_MODELS_PATH"])
    if not models.is_dir():
        raise ValueError("offline models are missing")
    try:
        import_module("onnxruntime")
    except ImportError as error:
        raise RuntimeError(
            "OCR runtime unavailable; install locked processor dependencies"
        ) from error
    index_settings = IndexSettings.from_env()
    ai = OpenRouter(AISettings.from_env())
    processor = Processor(base_url, token, models, ai, index_settings)
    client = await Client.connect(address, namespace=os.environ["TEMPORAL_NAMESPACE"])
    worker = Worker(
        client,
        task_queue="openlet-letfs-processing",
        activities=[
            processor.process_file,
            processor.enrich_file,
            processor.index_file,
        ],
        max_concurrent_activities=1,
        max_concurrent_activity_task_polls=1,
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
        await ai.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger(__name__).setLevel(logging.INFO)
    asyncio.run(main())
