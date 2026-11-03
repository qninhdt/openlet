from dataclasses import dataclass
from http import HTTPStatus


@dataclass(frozen=True)
class Problem:
    type: str
    title: str
    status: int
    detail: str
    code: str
    request_id: str = ""


class AppError(Exception):
    """A safe failure whose reason and retry policy survive transport boundaries."""

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        kind: str = "internal",
        retryable: bool = True,
    ):
        super().__init__(message)
        self.reason = reason
        self.kind = kind
        self.retryable = retryable


_STATUS = {
    "invalid": 400,
    "out_of_range": 400,
    "unauthenticated": 401,
    "forbidden": 403,
    "missing": 404,
    "exists": 409,
    "conflict": 409,
    "precondition": 400,
    "limit": 429,
    "unavailable": 503,
    "canceled": 499,
    "timeout": 504,
    "unsupported": 501,
}
_REASON_STATUS = {
    "PRECONDITION_REQUIRED": 428,
    "REVISION_MISMATCH": 412,
    "TARGET_MISMATCH": 412,
    "COPY_EXPIRED": 410,
    "REQUEST_LIMIT": 413,
    "INVALID_RANGE": 416,
}


def problem(error: Exception, request_id: str = "") -> Problem:
    if isinstance(error, AppError):
        status = _REASON_STATUS.get(error.reason, _STATUS.get(error.kind, 500))
        detail, code = str(error), error.reason
    else:
        status, detail, code = 500, "internal server error", "INTERNAL"
    title = "Client Closed Request" if status == 499 else HTTPStatus(status).phrase
    return Problem("about:blank", title, status, detail, code, request_id)
