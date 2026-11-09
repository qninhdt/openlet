from temporalio.client import Client
from temporalio.converter import DataConverter
from temporalio.exceptions import ApplicationError

from openlet.errors import AppError


async def connect(
    address: str,
    namespace: str,
    *,
    interceptor,
    runtime=None,
    tls: bool = False,
    data_converter: DataConverter = DataConverter.default,
) -> Client:
    if not address or not namespace:
        raise ValueError("invalid Temporal configuration")
    return await Client.connect(
        address,
        namespace=namespace,
        interceptors=[interceptor],
        runtime=runtime,
        tls=tls,
        data_converter=data_converter,
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
