"""Health and dependency probes."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.runtime import catalog_service
from app.providers import provider_registry
from app.schemas import (
    HealthDependenciesResponse,
    HealthLiveResponse,
    HealthReadyResponse,
    HealthResponse,
)

router = APIRouter(tags=["Health"])


@router.get("/health/live", response_model=HealthLiveResponse)
async def health_live() -> HealthLiveResponse:
    """Liveness: the process is running.  Never checks external services."""
    return HealthLiveResponse(status="alive", timestamp=datetime.now(timezone.utc))


@router.get("/health/ready", response_model=HealthReadyResponse)
async def health_ready():
    """Readiness: the catalog is loaded and at least one provider is configured.

    Provider availability is deliberately not checked here; a provider outage
    must not restart the container.  See /health/dependencies.
    """
    platforms = catalog_service.list_platforms()
    configured = sum(1 for provider in provider_registry.all() if provider.configured)
    ready = bool(platforms) and configured > 0
    payload = HealthReadyResponse(
        status="ready" if ready else "not_ready",
        timestamp=datetime.now(timezone.utc),
        catalog="loaded" if platforms else "unavailable",
        providers_configured=configured,
        providers_total=len(provider_registry.all()),
    )
    if not ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload.model_dump(mode="json"),
        )
    return payload


async def _provider_statuses() -> dict[str, str]:
    async def check(name: str, provider) -> tuple[str, str]:
        if not provider.configured:
            return name, "not_configured"
        try:
            await asyncio.wait_for(provider.get_balance(), timeout=5)
            return name, "ok"
        except Exception:
            return name, "error"

    results = await asyncio.gather(
        *(check(name, provider_registry.get(name)) for name in provider_registry.names())
    )
    return dict(results)


def _overall(statuses: dict[str, str]) -> str:
    if not statuses:
        return "unhealthy"
    values = list(statuses.values())
    if all(value == "ok" for value in values):
        return "healthy"
    if any(value == "ok" for value in values):
        return "degraded"
    return "degraded" if any(value == "not_configured" for value in values) else "unhealthy"


@router.get("/health/dependencies", response_model=HealthDependenciesResponse)
async def health_dependencies() -> HealthDependenciesResponse:
    """Informational dependency check; always returns HTTP 200."""
    statuses = await _provider_statuses()
    return HealthDependenciesResponse(
        timestamp=datetime.now(timezone.utc),
        status=_overall(statuses),
        providers=statuses,
    )


@router.get("/health", response_model=HealthResponse)
async def health_legacy() -> HealthResponse:
    """Backward-compatible aggregate health endpoint."""
    statuses = await _provider_statuses()
    return HealthResponse(
        status=_overall(statuses),
        timestamp=datetime.now(timezone.utc),
        providers=statuses,
    )
