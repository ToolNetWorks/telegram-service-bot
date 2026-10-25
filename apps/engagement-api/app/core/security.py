"""Internal authentication for the Engagement API."""
from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

from app.core.config import settings


def _extract_token(request: Request) -> str:
    token = request.headers.get("X-Internal-Token", "").strip()
    if token:
        return token
    authorization = request.headers.get("Authorization", "")
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() == "bearer":
        return credentials.strip()
    return ""


def verify_internal_token(request: Request) -> None:
    """Validate the shared Bot Core -> Engagement API token."""
    provided = _extract_token(request)
    expected = settings.internal_token
    # compare_digest avoids leaking the token through timing differences.
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal token",
            headers={"WWW-Authenticate": "Bearer"},
        )
