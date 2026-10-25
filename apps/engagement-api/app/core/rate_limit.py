"""Small in-process rate limiter for mutating endpoints.

This is a backstop, not a replacement for the Bot Core order guard.  Bot Core
is the only authorised caller and enforces durable idempotency in its own DB.
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

from app.core.config import settings

_buckets: dict[str, list[float]] = defaultdict(list)


def reset_rate_limits() -> None:
    """Test helper."""
    _buckets.clear()


def check_rate_limit(request: Request) -> None:
    """Fixed-window per-client limit for order creation."""
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = max(1, settings.rate_limit_window)

    bucket = [timestamp for timestamp in _buckets[client] if now - timestamp < window]
    if len(bucket) >= max(1, settings.rate_limit_requests):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )
    bucket.append(now)
    _buckets[client] = bucket
