"""Run the real Python activities against the disposable Go/Temporal fixture."""

import asyncio
import os
from datetime import timedelta
from pathlib import Path

from openlet.clients.letfs import ProcessingClient
from openlet.rpc import RpcClient
from temporalio.client import Client
from temporalio.worker import Worker

from letfs_ingest.clients.openrouter import AISettings, OpenRouter
from letfs_ingest.clients.qdrant import IndexSettings
from letfs_ingest.processing.processor import Processor
from letfs_ingest.temporal.activities import Activities


async def main():
    client = await Client.connect(
        os.environ["OPENLET_TEST_TEMPORAL"], namespace="openlet"
    )
    ai = OpenRouter(
        AISettings(
            api_key="controlled-provider-token",
            generation_model="fixture-generation",
            base_url=os.environ["OPENLET_TEST_PROVIDER"] + "/api/v1",
            allow_http=True,
        )
    )
    processor = Processor(
        Path(os.environ["OPENLET_TEST_MODELS"]),
        ai,
        IndexSettings(os.environ["OPENLET_TEST_QDRANT"], "isolated-qdrant-test-token"),
    )
    try:
        async with RpcClient(
            os.environ["OPENLET_TEST_RPC"],
            os.environ["OPENLET_TEST_INGEST_TOKEN"],
            allow_plaintext=True,
        ) as rpc:
            activities = Activities(processor, ProcessingClient(rpc))
            async with (
                Worker(
                    client,
                    task_queue="openlet-letfs-cpu",
                    activities=[activities.process_file],
                    max_concurrent_activities=1,
                    graceful_shutdown_timeout=timedelta(seconds=5),
                ),
                Worker(
                    client,
                    task_queue="openlet-letfs-io",
                    activities=[activities.enrich_file, activities.index_file],
                    max_concurrent_activities=4,
                    graceful_shutdown_timeout=timedelta(seconds=5),
                ),
            ):
                workflow = os.environ["OPENLET_TEST_WORKFLOW"]
                source = await asyncio.wait_for(
                    client.get_workflow_handle(workflow).result(), timeout=150
                )
                assert source == {
                    "file_id": os.environ["OPENLET_TEST_FILE"],
                    "generation": 1,
                }
                replay = await client.execute_workflow(
                    "ProcessFile",
                    {
                        "source": source,
                        "parse_required": False,
                        "enrichment_required": False,
                    },
                    id=workflow + "-index-only",
                    task_queue="openlet-letfs",
                    execution_timeout=timedelta(seconds=30),
                )
                assert replay == source
    finally:
        await ai.close()
    print("native-python-activities-ok")


if __name__ == "__main__":
    asyncio.run(main())
