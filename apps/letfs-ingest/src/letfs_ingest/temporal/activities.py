import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
from openlet.clients.letfs import Generation
from openlet.errors import AppError
from openlet.temporal import application_error
from temporalio import activity
from temporalio.exceptions import ApplicationError

from letfs_ingest.parser.convert_child import ResourceLimit
from letfs_ingest.processing.processor import Processor

LOG = logging.getLogger(__name__)


def generation(source: dict) -> Generation:
    return Generation(str(UUID(source["file_id"])), source["generation"])


async def heartbeat():
    while True:
        activity.heartbeat()
        await asyncio.sleep(5)


@asynccontextmanager
async def activity_resources():
    pulse = asyncio.create_task(heartbeat())
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as storage:
            yield storage
    finally:
        pulse.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pulse


def failure(error: Exception, fallback: str) -> tuple[str, bool]:
    if isinstance(error, AppError):
        return error.reason, not error.retryable
    if isinstance(error, ResourceLimit):
        return "RESOURCE_LIMIT", True
    return fallback, False


class Activities:
    def __init__(self, processor: Processor, api):
        self.processor = processor
        self.api = api

    async def report_failure(self, report, source: Generation, code: str):
        try:
            async with asyncio.timeout(5):
                await report(source, code)
        except Exception:
            LOG.warning("processing failure reconciliation deferred")

    @activity.defn(name="enrich_file")
    async def enrich_file(self, source: dict) -> dict:
        current = generation(source)
        async with activity_resources() as storage:
            try:
                async with asyncio.timeout(1700):
                    await self.processor.enrich(self.api, storage, current)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                code, terminal = failure(error, "PROCESSING_FAILED")
                if terminal or activity.info().attempt >= 3:
                    await self.report_failure(self.api.fail_enrichment, current, code)
                raise ApplicationError(
                    "semantic enrichment failed", type=code, non_retryable=terminal
                ) from None
        return source

    @activity.defn(name="index_file")
    async def index_file(self, source: dict) -> dict:
        current = generation(source)
        prepared = None
        async with activity_resources() as storage:
            try:
                async with asyncio.timeout(1700):
                    prepared = await self.api.prepare_index(current)
                    if prepared is not None:
                        await self.processor.index(self.api, storage, current, prepared)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                code, terminal = failure(error, "DEPENDENCY_UNAVAILABLE")
                if (
                    (terminal or activity.info().attempt >= 3)
                    and prepared is not None
                    and prepared.vector_space is not None
                ):
                    await self.report_failure(self.api.fail_index, current, code)
                raise ApplicationError(
                    "search indexing failed", type=code, non_retryable=terminal
                ) from None
        return source

    @activity.defn(name="process_file")
    async def process_file(self, source: dict) -> dict:
        current = generation(source)
        async with activity_resources() as storage:
            try:
                async with asyncio.timeout(1700):
                    await self.processor.process(self.api, storage, current)
            except asyncio.CancelledError:
                details = activity.cancellation_details()
                if details and details.cancel_requested:
                    await self.abort(current, "PROCESSING_CANCELLED")
                raise
            except ResourceLimit:
                await self.abort(current, "RESOURCE_LIMIT")
                raise ApplicationError(
                    "processing resource limit",
                    type="RESOURCE_LIMIT",
                    non_retryable=True,
                ) from None
            except AppError as error:
                if not error.retryable:
                    code = (
                        error.reason
                        if error.reason
                        in {"RESOURCE_LIMIT", "QUOTA_EXCEEDED", "DOCUMENT_INVALID"}
                        else "PROCESSING_FAILED"
                    )
                    await self.abort(current, code)
                raise application_error(
                    error,
                    fallback="PROCESSING_FAILED",
                    message=str(error),
                ) from None
            except Exception as error:
                raise application_error(
                    error,
                    fallback="DEPENDENCY_UNAVAILABLE",
                    message="processing dependency failed",
                ) from None
        return source

    async def abort(self, source: Generation, code: str):
        try:
            async with asyncio.timeout(5):
                await self.api.abort_parse(source, code)
        except (Exception, asyncio.CancelledError):
            LOG.warning("generation cleanup deferred to letfs maintenance")
