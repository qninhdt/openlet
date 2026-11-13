import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import TypedDict

from opentelemetry import metrics, trace
from opentelemetry.trace import StatusCode
from temporalio import activity


class ProcessingIdentity(TypedDict):
    file_id: str
    version: int


duration = metrics.get_meter(__name__).create_histogram("openlet.processing.stage.duration", unit="s")
tracer = trace.get_tracer(__name__)


@contextmanager
def stage(name: str, identity: ProcessingIdentity) -> Iterator[None]:
    started, outcome = perf_counter(), "success"
    with tracer.start_as_current_span(
        f"ingest.{name}", attributes={"file.id": identity["file_id"], "file.version": identity["version"]},
        record_exception=False, set_status_on_exception=False,
    ) as span:
        try:
            yield
        except (Exception, asyncio.CancelledError) as error:
            outcome = "cancelled" if isinstance(error, asyncio.CancelledError) else "error"
            span.set_attribute("error.type", type(error).__name__)
            span.set_status(StatusCode.ERROR)
            raise
        finally:
            duration.record(perf_counter() - started, {"stage": name, "outcome": outcome})
            activity.logger.info("processing stage finished", extra={**identity, "stage": name, "outcome": outcome})
