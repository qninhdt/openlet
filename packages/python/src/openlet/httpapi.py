from dataclasses import asdict

from openlet.errors import problem


def problem_json(error: Exception, request_id: str = "") -> tuple[int, dict, dict]:
    value = problem(error, request_id)
    return (
        value.status,
        {"content-type": "application/problem+json", "cache-control": "no-store"},
        asdict(value),
    )
