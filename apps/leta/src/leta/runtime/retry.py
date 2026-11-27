from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from time import monotonic, time

from ..config import ModelConfig, ModelRetryConfig, ModelSpec


class ContextOverflowError(RuntimeError):
    """Raised when the provider rejects a prompt for exceeding context limits."""


_OVERFLOW_MARKERS = (
    "context_length_exceeded",
    "maximum context length",
    "context window",
    "prompt is too long",
    "too many tokens",
    "exceeds the model's maximum",
    "input token count exceeds",
    "request too large",
)

_UNREACHABLE_MARKERS = (
    "enotfound",
    "eai_again",
    "enetunreach",
    "ehostunreach",
    "enetdown",
    "temporary failure in name resolution",
    "name or service not known",
    "network is unreachable",
    "nodename nor servname",
)


def compute_output_limit(
    model: ModelSpec,
    *,
    measured_tokens: int,
    estimated_tokens: int,
    cfg: ModelConfig,
    headroom: float | None = None,
) -> int:
    effective_headroom = cfg.window_headroom if headroom is None else headroom
    requested = min(
        model.max_output_tokens or cfg.output_token_fallback,
        cfg.output_token_max,
    )
    if model.context_window_tokens <= 0:
        return max(cfg.output_token_min, requested)
    room = (
        math.floor(model.context_window_tokens * (1.0 - effective_headroom))
        - measured_tokens
        - math.ceil(estimated_tokens * (1.0 + cfg.estimate_error_margin))
    )
    return min(requested, max(cfg.output_token_min, room))


def _status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    resp = getattr(exc, "response", None)
    if resp is not None:
        code = getattr(resp, "status_code", None)
        if isinstance(code, int):
            return code
    return None


def _headers(exc: BaseException) -> dict[str, str]:
    resp = getattr(exc, "response", None)
    raw = getattr(resp, "headers", None) if resp is not None else None
    if raw is None:
        raw = getattr(exc, "headers", None)
    if raw is None:
        return {}
    try:
        items = raw.items()
    except AttributeError:
        return {}
    return {str(k).lower(): str(v) for k, v in items}


def is_context_overflow(exc: BaseException) -> bool:
    if isinstance(exc, ContextOverflowError):
        return True
    msg = str(exc).lower()
    return any(marker in msg for marker in _OVERFLOW_MARKERS)


def is_unreachable_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _UNREACHABLE_MARKERS)


def is_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True
    name = type(exc).__name__.lower()
    return "timeout" in name or "timed out" in str(exc).lower()


def parse_retry_after(exc: BaseException, max_seconds: float) -> float | None:
    hdrs = _headers(exc)
    val = hdrs.get("retry-after-ms")
    if val is not None:
        try:
            return min(max_seconds, max(0.0, float(val) / 1000.0))
        except ValueError:
            pass
    ra = hdrs.get("retry-after")
    if ra is None:
        return None
    try:
        return min(max_seconds, max(0.0, float(ra)))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(ra)
        return min(max_seconds, max(0.0, dt.timestamp() - time()))
    except Exception:
        return None


def should_retry_header(exc: BaseException) -> bool | None:
    val = _headers(exc).get("x-should-retry")
    if val is None:
        return None
    low = val.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return None


def _is_retryable_status(code: int | None) -> bool:
    return code in (408, 409, 429, 500, 502, 503, 504, 529)


def _jitter(delay: float) -> float:
    return delay * (0.85 + random.random() * 0.3)


async def invoke_with_retry[T](
    fn: Callable[[], Awaitable[T]],
    *,
    cfg: ModelRetryConfig,
    has_output_started: Callable[[], bool] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Port of OpenCode v2 model-retry.ts with unreachable/timeout/Retry-After budgets."""
    general_attempts = 0
    timeout_attempts = 0
    unreachable_started: float | None = None
    unreachable_attempts = 0

    while True:
        try:
            return await fn()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if has_output_started is not None and has_output_started():
                raise
            if is_context_overflow(exc):
                raise ContextOverflowError(str(exc)) from exc

            override = should_retry_header(exc)
            if override is False:
                raise

            code = _status_code(exc)
            if code in (400, 401, 403, 404, 422) and override is not True:
                raise

            if is_unreachable_error(exc):
                now = monotonic()
                if unreachable_started is None:
                    unreachable_started = now
                if now - unreachable_started >= cfg.unreachable_window_seconds:
                    raise
                unreachable_attempts += 1
                base = min(
                    cfg.unreachable_gap_max_seconds,
                    cfg.initial_interval_seconds * (2 ** (unreachable_attempts - 1)),
                )
                delay = min(cfg.unreachable_gap_max_seconds, _jitter(base))
                await sleep(delay)
                continue

            if is_timeout_error(exc):
                timeout_attempts += 1
                if timeout_attempts > cfg.timeout_max_retries:
                    raise
                general_attempts += 1
                if general_attempts > cfg.max_attempts:
                    raise
                base = min(
                    cfg.max_interval_seconds,
                    cfg.initial_interval_seconds * (2 ** (general_attempts - 1)),
                )
                await sleep(_jitter(base))
                continue

            retryable = (
                override is True
                or _is_retryable_status(code)
                or isinstance(exc, (ConnectionError, OSError))
            )
            if not retryable:
                raise

            general_attempts += 1
            if general_attempts > cfg.max_attempts:
                raise
            base = min(
                cfg.max_interval_seconds,
                cfg.initial_interval_seconds * (2 ** (general_attempts - 1)),
            )
            delay = _jitter(base)
            ra = parse_retry_after(exc, cfg.retry_after_max_seconds)
            if ra is not None:
                delay = max(delay, ra)
            await sleep(delay)


async def retry_one_shot[T](
    fn: Callable[[], Awaitable[T]],
    *,
    cfg: ModelRetryConfig,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Retry standalone one-shot calls only on failures proving the provider never ran the request."""
    attempts = 0
    while True:
        try:
            return await fn()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if is_context_overflow(exc):
                raise ContextOverflowError(str(exc)) from exc
            override = should_retry_header(exc)
            if override is False:
                raise
            code = _status_code(exc)
            msg = str(exc).lower()
            not_sent = (
                override is True
                or code in (429, 503, 529)
                or is_unreachable_error(exc)
                or "econnrefused" in msg
                or "connection refused" in msg
            )
            if not not_sent or attempts >= cfg.one_shot_retries:
                raise
            attempts += 1
            base = min(
                cfg.max_interval_seconds,
                cfg.initial_interval_seconds * (2 ** (attempts - 1)),
            )
            delay = _jitter(base)
            ra = parse_retry_after(exc, cfg.retry_after_max_seconds)
            if ra is not None:
                delay = max(delay, ra)
            await sleep(delay)
