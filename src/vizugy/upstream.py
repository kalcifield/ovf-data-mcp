"""Shared upstream client identity and retry policy.

Both OVF services are slow, lightly provisioned public endpoints. Transient failures
(timeouts, 5xx) are worth one or two more attempts; deterministic failures (4xx, auth,
malformed payloads) are not, and repeating them only adds load upstream.

Every request identifies this tool so OVF can attribute and contact the traffic; both
providers build their client here so that identity cannot drift apart again.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .errors import AccessDeniedError, NotFoundError, UpstreamError


USER_AGENT = "ovf-data-mcp (+https://github.com/kalcifield/ovf-data-mcp)"


def upstream_client(timeout: float) -> httpx.AsyncClient:
    """Build an identified HTTP client for an OVF upstream."""
    return httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )


def _is_transient(exc: BaseException) -> bool:
    # Deterministic outcomes first: these stay failed however often we ask.
    if isinstance(exc, NotFoundError | AccessDeniedError):
        return False
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    # ArcGIS reports failures in a 200 body, surfaced as UpstreamError by the caller.
    return isinstance(exc, httpx.HTTPError | UpstreamError)


F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def upstream_retry(attempts: int, first_delay: float) -> Callable[[F], F]:
    """Retry transient upstream failures, waiting first_delay then doubling."""
    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=first_delay / 2),
        retry=retry_if_exception(_is_transient),
        reraise=True,
    )
