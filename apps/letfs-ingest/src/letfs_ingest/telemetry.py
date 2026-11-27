"""OpenTelemetry spans, stage metrics, retry helper, and Temporal heartbeats."""

from __future__ import annotations

import asyncio
import random
from contextlib import asynccontextmanager, contextmanager
from time import perf_counter
from typing import TYPE_CHECKING, TypedDict

from opentelemetry import metrics, trace
from opentelemetry.trace import StatusCode
from temporalio import activity

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Generator


class ProcessingIdentity(TypedDict):
    """Structured logging identity attached to ingest stage logs."""

    blob_id: str


duration = metrics.get_meter(__name__).create_histogram(
    "openlet.processing.stage.duration", unit="s"
)
tracer = trace.get_tracer(__name__)


async def retry_transient[T](
    op: Callable[[], Awaitable[T]],
    *,
    should_retry: Callable[[BaseException], bool],
    attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 8.0,
    on_attempt: Callable[[int], None] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Retry transient failures with exponential backoff and bounded jitter."""
    delay = base_delay
    for attempt in range(1, attempts + 1):
        if on_attempt is not None:
            on_attempt(attempt)
        try:
            return await op()
        except Exception as exc:
            if attempt == attempts or not should_retry(exc):
                raise
            await sleep(delay + random.uniform(0.0, 0.5))  # noqa: S311  # Non-cryptographic retry jitter.
            delay = min(max_delay, delay * 2.0)
    raise AssertionError("unreachable")


@contextmanager
def stage(name: str, identity: ProcessingIdentity) -> Generator[None]:
    """Instrument a processing stage with an OpenTelemetry span, histogram, and log."""
    started, outcome = perf_counter(), "success"
    with tracer.start_as_current_span(
        f"ingest.{name}",
        attributes={"blob.id": identity["blob_id"]},
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield
        except (Exception, asyncio.CancelledError) as error:
            outcome = (
                "cancelled" if isinstance(error, asyncio.CancelledError) else "error"
            )
            span.set_attribute("error.type", type(error).__name__)
            span.set_status(StatusCode.ERROR)
            raise
        finally:
            duration.record(
                perf_counter() - started, {"stage": name, "outcome": outcome}
            )
            activity.logger.info(
                "processing stage finished",
                extra={**identity, "stage": name, "outcome": outcome},
            )


@asynccontextmanager
async def heartbeats(interval: float = 10.0) -> AsyncGenerator[None]:
    """Send periodic Temporal activity heartbeats until the context exits."""
    stop = asyncio.Event()

    async def beat() -> None:
        while not stop.is_set():
            activity.heartbeat()
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                continue

    task = asyncio.create_task(beat())
    try:
        yield
    finally:
        stop.set()
        await task
