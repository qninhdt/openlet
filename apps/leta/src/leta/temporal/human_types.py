from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from leta.domain import ID, Input, NewHumanRequest, NewMessage, Source
from leta.temporal.types import AgentInput


class HumanRequestRef(Input):
    leta_id: ID
    request_id: ID


class OpenHumanRequest(HumanRequestRef):
    creation: NewHumanRequest | None = None
    timeout_seconds: int | None = Field(default=None, gt=0, strict=True)

    @model_validator(mode="after")
    def match_creation(self):
        if self.creation is not None and (
            self.creation.id != self.request_id or self.creation.leta_id != self.leta_id
        ):
            raise ValueError("request identity differs from creation")
        if self.timeout_seconds is not None and self.creation is None:
            raise ValueError("timeout requires request creation")
        return self


class HumanRequestState(HumanRequestRef):
    status: Literal["pending", "resolved", "cancelled", "expired"]
    expires_at: datetime | None = None
    needs_grant: bool = False
    outcome: dict[str, JsonValue] | None = None
    delivery: AgentInput | None = None

    @classmethod
    def from_row(cls, row):
        return cls(
            leta_id=row["leta_id"],
            request_id=row["id"],
            status=row["status"],
            expires_at=row["expires_at"],
            needs_grant=(
                row["status"] == "resolved"
                and row["decision"]["action"] == "accept"
                and row["outcome"] is None
            ),
            outcome=row["outcome"],
            delivery=(
                AgentInput(
                    message=NewMessage(
                        id=row["outcome_message_id"],
                        leta_id=row["leta_id"],
                        recipient_agent_id=row["requester_agent_id"],
                        source=Source(
                            type="hitl", id=str(row["id"]), label=row["title"]
                        ),
                        content=f"Human request {row['status']}: {row['title']}",
                        data={
                            "request_id": str(row["id"]),
                            "kind": row["kind"],
                            "status": row["status"],
                            "outcome": row["outcome"],
                        },
                    )
                )
                if row["outcome"] is not None
                else None
            ),
        )


class HumanRequestOutcome(HumanRequestRef):
    outcome: dict[str, JsonValue]


class SettleHumanRequest(HumanRequestRef):
    reason: str = Field(min_length=1, max_length=4000)
