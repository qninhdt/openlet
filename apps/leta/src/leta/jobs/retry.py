from temporalio.common import RetryPolicy

# Invalid domain input must fail its operation instead of retrying indefinitely.
RETRY = RetryPolicy(
    non_retryable_error_types=[
        "ValueError",
        "ValidationError",
        "PermissionError",
        "LookupError",
        "HTTPException",
        "UniqueViolation",
        "BadRequestError",
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
        "UnprocessableEntityError",
        "GraphRecursionError",
    ]
)
