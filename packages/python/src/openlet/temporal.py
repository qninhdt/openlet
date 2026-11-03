from temporalio.client import Client
from temporalio.exceptions import ApplicationError

from openlet.errors import AppError


async def connect(address: str, namespace: str, *, interceptor, runtime=None) -> Client:
    if not address or not namespace:
        raise ValueError("invalid Temporal configuration")
    return await Client.connect(
        address,
        namespace=namespace,
        interceptors=[interceptor],
        runtime=runtime,
    )


def application_error(
    error: Exception, *, fallback: str, message: str
) -> ApplicationError:
    if isinstance(error, AppError):
        return ApplicationError(
            message,
            type=error.reason,
            non_retryable=not error.retryable,
        )
    return ApplicationError(message, type=fallback)
