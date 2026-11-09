"""Best-effort sparse publication stays outside Local SQL Activities."""

import logging
from datetime import timedelta
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from leta.streaming import Publisher

log = logging.getLogger(__name__)


async def publish(leta_id, kind, resource_id):
    try:
        await workflow.execute_activity(
            "publish_resource_event",
            args=[leta_id, kind, resource_id],
            result_type=bool,
            schedule_to_close_timeout=timedelta(seconds=3),
            start_to_close_timeout=timedelta(seconds=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
    except ActivityError:
        workflow.logger.warning("committed resource notification unavailable")


class PublicationActivities:
    def __init__(self, publisher: Publisher | None):
        self.publisher = publisher

    @activity.defn
    async def publish_resource_event(
        self, leta_id: UUID, kind: str, resource_id: UUID
    ) -> bool:
        # Narrow domain fixtures explicitly omit Redis; production always injects it.
        if self.publisher is None:
            return False
        try:
            return await self.publisher.resource(leta_id, kind, resource_id)
        except Exception:
            log.warning(
                "committed resource notification unavailable", extra={"kind": kind}
            )
            return False
