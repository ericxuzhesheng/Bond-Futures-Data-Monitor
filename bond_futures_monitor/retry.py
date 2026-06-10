"""Retry helper for flaky external API calls."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar


logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY_SECONDS = 1.0


def retry_call(
    func: Callable[[], T],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
    description: str = "external call",
) -> T:
    """Call ``func`` with exponential backoff, re-raising the last error."""

    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            if attempt < attempts:
                delay = base_delay_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "%s failed (attempt %d/%d): %s; retrying in %.1fs",
                    description,
                    attempt,
                    attempts,
                    exc,
                    delay,
                )
                time.sleep(delay)
    assert last_exc is not None
    raise last_exc
